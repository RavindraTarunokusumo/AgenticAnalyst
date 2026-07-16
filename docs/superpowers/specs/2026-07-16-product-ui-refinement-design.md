# Product UI Refinement Design

## 1. Purpose

The Brief Viewer UI (`frontend/`, PR #6) is deliberately read-only - it only
calls `GET /briefs` and `GET /briefs/{brief_id}`. The backend already has a
full write surface for getting content into the system
(`POST /sources`, `POST /ingestion/urls`, `GET /ingestion/attempts`) but none
of it is reachable from the UI; every user still has to `curl` a source into
existence before the viewer shows anything. This slice wires that existing
write surface into the UI (plus one new backend capability, direct file
upload) so a first-time user can go from "empty database" to "briefs on
screen" without leaving the browser. Visual/design polish is explicitly out
of scope (per product direction) - this is a functionality slice only.

## 2. What Already Exists (verified against the current codebase)

- `POST /sources` (`api/app.py:371`): idempotent source + feed registration.
  `RegisterSourceRequest` is `{stable_id, name, normalized_domain, feeds: []}`
  - `feeds` already defaults to `[]`, so a feed-less "manual content" source
  is already supported with no backend change.
- `POST /ingestion/urls` (`api/app.py:430`): `{source_id, urls: [...]}` ->
  `list[IngestionResultResponse]`. Calls
  `IngestionService.ingest_urls`, which awaits `_ingest_candidate` per URL
  **synchronously in the request** - the HTTP response already contains each
  URL's terminal status (`success`/`duplicate`/`failed` + `article_id` or
  `error_code`/`error_summary`). There is no background job for this route;
  "loading" is exactly "this request is in flight," nothing more.
- `GET /ingestion/attempts` (`api/app.py:447`): open read route, optional
  `status` filter, returns recent `IngestionAttemptResponse` rows
  (`source_id`, `requested_url`, `status`, `extractor`, `article_id`,
  `error_code`/`error_summary`, `started_at`/`completed_at`).
- All three write routes above sit behind `_require_key`
  (`api/app.py:321`): a `X-API-Key` header, bypassed only when
  `settings.allow_unauthenticated_write` is true (local dev only). The UI
  today sends this header on zero requests.
- `IngestionService._ingest_candidate` (`ingestion/service.py:174`) is the
  single tail every candidate (feed-polled or manually-submitted URL) runs
  through: `canonicalize_url` -> dedup check by `url_fingerprint` -> extract
  (`ArticleExtractor.extract(url)`) -> validate title/`published_at`/content
  length -> persist via `save_article` (race-safe re-check on
  `IntegrityError`). Everything from the dedup check onward does not depend
  on the candidate having come from a real HTTP fetch.
- `Article` (`domain/models.py:89` / `persistence/models.py:39`) requires a
  non-null `url` and a unique `url_fingerprint`; there is no "uploaded, no
  URL" concept in the schema today.
- No PDF/text-extraction dependency exists anywhere in `pyproject.toml`
  today (grep confirmed) - file upload is a genuinely new capability, not a
  hookup to existing infrastructure.
- `frontend/src/App.tsx` owns all state via plain `useState`, no router, no
  global store (established YAGNI precedent from the original UI spec,
  §3.1 of `2026-07-15-ui-brief-viewer-design.md`) - this slice follows the
  same pattern rather than introducing routing/state-management libraries.

## 3. Product Behavior

### 3.1 Onboarding: first-run source setup

- On app load, `GET /sources` runs before the normal 3-panel view mounts.
- If the list is empty, render an onboarding screen instead of the normal
  view: fields for source name, normalized domain, an optional feed URL, and
  an API key field. Submitting calls `POST /sources` (feed list is `[]` if
  the optional feed field was left blank) using the entered key as
  `X-API-Key`, then stores that key in `localStorage` and transitions to the
  normal view.
- If `GET /sources` (or the onboarding `POST /sources`) fails, show an
  inline error state on the onboarding screen - do not silently retry or
  fall through to the normal view with no source.
- Once at least one source exists, this screen never shows again
  automatically; a source is a precondition for `POST /ingestion/urls` and
  the new `POST /ingestion/files` (both require `source_id`), which is why
  onboarding is gating rather than optional.

### 3.2 Add content: links, feeds, files

- A persistent "Add content" control (available once onboarding is past)
  opens a panel with three modes:
  1. **Paste link(s)** - one or more URLs (newline/comma separated) ->
     `POST /ingestion/urls` with the onboarding source's `id`.
  2. **Add feed** - a feed URL -> `POST /sources` against the existing
     source's `stable_id` (idempotent registration already handles
     add-a-feed-to-existing-source; no new endpoint needed).
  3. **Upload file** - a PDF or `.txt` file -> `POST /ingestion/files` (new,
     §5.1).
- All three attach `X-API-Key` from `localStorage`.
- Submission renders: an in-flight spinner while the request is outstanding
  (all three routes are synchronous - there is nothing to poll mid-request),
  then a per-item result list from the response (`success` / `duplicate` /
  `failed`, with `error_summary` shown for failures).
- After any submission completes (success or failure), refetch
  `GET /ingestion/attempts?limit=10` and render it as a small "recent
  activity" list in the same panel - a persistent view of ingestion history
  independent of the current submission, not a live/polled feed (nothing
  changes attempt rows outside of a request the UI itself just made).

### 3.3 API key settings

- A small settings affordance (e.g. in the header) lets the user view/edit
  the stored key later, for the case where it rotates or was mistyped during
  onboarding. Same `localStorage` key onboarding writes to.

### 3.4 Explicitly out of scope

- Any visual/design-system rework (explicit product direction for this
  slice - functionality only).
- Real-time push/websocket status - ingestion is synchronous server-side, so
  there is no server-driven event to push.
- Multi-source management UI (listing/editing/deleting arbitrary sources) -
  onboarding creates exactly one default source; feeds can be added to it
  ad hoc via §3.2 mode 2, but there is no source list/switcher screen.
- `.docx`/other document formats - PDF + plain text only for file upload.
- Any change to `POST /sources` / `POST /ingestion/urls` / dedup semantics
  for URL-based ingestion.

## 4. Data Model

### 4.1 New: synthetic URL scheme for uploaded files

`Article.url` is non-null and `url_fingerprint` is uniquely indexed; an
uploaded file has neither a real URL nor feed-derived metadata. Uploads use:

- `url = f"upload://{content_hash}"` where `content_hash` is the SHA-256 hex
  digest of the raw uploaded bytes.
- `url_fingerprint = content_hash` (same value) - dedup for uploads is by
  exact content hash, not `canonicalize_url`'s normalization (which assumes
  an `http(s)` URL and does not apply to a synthetic scheme). Two different
  files with identical bytes dedup as duplicates; this matches the existing
  dedup contract's spirit ("stable hash of normalized URL/content for
  deduplication") without touching `canonicalize_url` or its private/loopback
  host validation, which is meaningless for a local upload.
- `published_at = ingested_at` (upload time) - uploaded files carry no
  publish-date metadata; unlike feed/URL candidates there is no
  `candidate.published_at` or page metadata to fall back to. This is a
  deliberate simplification, not a bug: it is called out explicitly here so
  it isn't mistaken for a missing-metadata failure later.
- No migration needed - `url`/`url_fingerprint` are existing `TEXT`/`String`
  columns; a `upload://` value is just a string that happens not to be a
  real URL. Nothing downstream (batching, summarization, brief citation
  resolution) assumes `url` is fetchable.

### 4.2 No new tables

Uploaded content becomes an ordinary `Article` row and flows through the
unmodified batching -> summarization -> brief pipeline exactly like a
URL-ingested one. No new ORM model, no new migration.

## 5. Interfaces

### 5.1 New backend surface

- `POST /ingestion/files` (new route in `api/app.py`, same `_require_key`
  gate as the other write routes): multipart form body
  (`source_id: UUID`, `file: UploadFile`). Response:
  `IngestionResultResponse` (same shape `POST /ingestion/urls` already
  returns per item - reuse the model, one item since this route accepts one
  file per call).
  - Validates content-type/extension against an accept-list (`application/
    pdf`, `text/plain`) before extraction; rejects anything else with
    `error_code="unsupported_file_type"` (same failure shape as other
    `_record_failure` paths, not a raw 415 with no body context, so the UI's
    existing per-item result rendering handles it uniformly).
  - Enforces a size limit against `settings.article_max_response_size_bytes`
    - the same setting `PrimaryHttpExtractor` already caps HTTP-fetched
    article bodies with (`runtime.py:67`) - applied here to the multipart
    body instead of an HTTP fetch, so an uploaded file is bounded by the
    same "max size of one article's raw content" policy as a fetched one.
- New `ingestion/file_extractor.py`: `FileExtractor` protocol
  (`extract(filename: str, content: bytes) -> ExtractedArticle`), parallel
  in shape to `ArticleExtractor` (`extractor.py`) but keyed on bytes instead
  of a URL to fetch. Two implementations:
  - PDF: uses `pypdf` (new dependency - pure-Python, no system deps,
    smallest well-maintained option; PDF text extraction is not reasonably
    achievable from the stdlib, unlike `html_clean.py`'s deliberate
    stdlib-only HTML parsing).
  - Plain text: decode as UTF-8 (replace errors, matching
    `PrimaryHttpExtractor`'s existing `errors="replace"` convention), title
    is the filename minus extension (no in-band title metadata in a `.txt`
    file).
- `IngestionService` gains `ingest_file(source_id: UUID, filename: str,
  content: bytes) -> IngestionResult`. Implementation: compute
  `content_hash`, build the synthetic `url`/`url_fingerprint` (§4.1), run the
  **same dedup-check-through-persist tail** `_ingest_candidate` already
  implements. That tail (dedup check, title/content-length validation,
  race-safe persist) is refactored out of `_ingest_candidate` into a private
  helper both `_ingest_candidate` and `ingest_file` call, taking
  `(candidate, canonical_url, fingerprint, extracted: ExtractedArticle,
  started_at)` - avoids duplicating the persist/failure-recording logic
  for the new path. `_ingest_candidate` itself keeps everything upstream of
  that (canonicalize, HTTP extraction + Crawl4AI fallback) unchanged;
  `ingest_file` skips straight to the shared tail with its synthetic
  URL/fingerprint and a `FileExtractor`-produced `ExtractedArticle` instead
  of an HTTP-fetched one.
- `pyproject.toml`: add `pypdf` as a runtime dependency (only new Python
  dependency in this slice).

### 5.2 Consumes (existing, unchanged)

- `GET /sources` -> `list[SourceResponse]`
- `POST /sources` -> `SourceResponse`
- `POST /ingestion/urls` -> `list[IngestionResultResponse]`
- `GET /ingestion/attempts?limit=<int>` -> `list[IngestionAttemptResponse]`

### 5.3 Produces (frontend, new)

- `frontend/src/api.ts` gains typed wrappers: `fetchSources`,
  `registerSource`, `ingestUrls`, `ingestFile`, `fetchIngestionAttempts` -
  same "throw on non-2xx" convention the existing `fetchBriefList`/
  `fetchBriefDetail` wrappers already use. Write wrappers accept an
  `apiKey: string` parameter and set `X-API-Key`.
- New components: `Onboarding` (screen), `AddContentPanel` (the 3-mode
  panel), `IngestionResultList` (per-item status), `RecentActivityList`
  (attempts feed), `ApiKeySettings` (small header affordance). Same
  presentational/no-own-fetch-calls convention as the existing
  `components/` (state lives in `App.tsx`, per §2's established pattern).
- `App.tsx` gains: `sources` state + the onboarding-gate `useEffect`, an
  `apiKey` state initialized from `localStorage`, and handlers wiring the
  new panel's submit actions to the new `api.ts` wrappers.

## 6. Workflow

1. Browser loads `/ui/`. App fetches `GET /sources`.
2. **Empty** -> onboarding screen renders. User fills name/domain
   (+ optional feed URL) + API key, submits -> `POST /sources` -> key saved
   to `localStorage` -> transition to normal view with the new source in
   state (no extra re-fetch needed, the `POST /sources` response already has
   it).
3. **Non-empty** -> normal 3-panel view renders immediately (unchanged from
   the existing Brief Viewer), plus the "Add content" control is now visible.
4. User opens "Add content", picks a mode, submits:
   - Link(s) -> spinner -> `POST /ingestion/urls` response renders as a
     per-URL result list.
   - Feed -> spinner -> `POST /sources` (existing `stable_id`, new feed
     appended) response renders as a single result.
   - File -> spinner -> `POST /ingestion/files` response renders as a
     single result.
5. Regardless of outcome, `GET /ingestion/attempts?limit=10` refetches and
   the "recent activity" list updates in place.
6. Newly ingested articles flow through the existing, unmodified pipeline
   (batching -> summarization -> next brief run) - this UI slice does not
   trigger that pipeline; a new brief showing the content still depends on
   the next scheduled/manually-triggered pipeline run, same as today.

## 7. Edge Cases

- `GET /sources` fails on initial load (network/backend down): show an
  error state, not a blank page and not a false "empty, please onboard"
  screen (distinguish "confirmed empty" from "failed to check").
- Onboarding `POST /sources` with a `stable_id`/`normalized_domain` that
  already exists: the route is already idempotent (`upsert_source`) -
  surface the returned source and proceed rather than treating it as an
  error.
- Wrong/expired API key: any write call gets `401`/`403` from
  `_require_key` - render an inline "check your API key" error in the
  relevant panel (add-content result list or the settings affordance), not
  a generic failure message, and do not clear the stored key automatically
  (avoid forcing re-entry on a transient failure).
- File exceeds the size limit or has an unsupported type: `IngestionResult`
  with a specific `error_code` (`file_too_large` / `unsupported_file_type`),
  rendered the same way any other failed item renders (§3.2) - no special
  UI path.
- PDF with no extractable text (e.g. scanned image, no text layer): treated
  like any other "content too short" failure via the shared persist-tail
  validation (§5.1) - no OCR, that's out of scope.
- Duplicate content (same URL or same file bytes resubmitted): existing
  `duplicate` status path (already handled by `_ingest_candidate`'s dedup
  check, and by construction for uploads via §4.1's content-hash
  fingerprint) - rendered as `duplicate`, not `failed`.
- Multiple URLs submitted together where some succeed and some fail: the
  per-item result list already reflects this per `IngestionResultResponse`
  shape - no special aggregate "partial success" state needed beyond
  rendering each item's own status.

## 8. Success Criteria

- A user with a fresh (source-less) deployment can go from opening `/ui/`
  to seeing at least one ingested `Article` on screen (via the "recent
  activity" list) without using `curl`/a REST client/the backend directly.
- All three add-content modes (link, feed, file) work end to end against a
  running backend with `allow_unauthenticated_write=true` (local dev) and
  with a real API key set.
- PDF and plain-text file uploads extract usable text and produce a
  persisted `Article` indistinguishable, from the pipeline's perspective,
  from a URL-ingested one.
- Existing read-only Brief Viewer behavior (cadence tabs, brief list,
  brief detail) is unchanged.
- No visual/design-system changes beyond the minimum structural markup the
  new screens/panels need to function.

## 9. Constraints

- No change to `canonicalize_url`, its private/loopback/reserved-host
  validation, or any URL-based dedup semantics.
- No change to `pipeline/`, `workflows/`, `batching/`, `summarization/` -
  this slice only adds a new way to get an `Article` row persisted; nothing
  about what happens after persistence changes.
- Exactly one new Python dependency (`pypdf`); no new Node dependency beyond
  what the existing frontend toolchain already has.
- `X-API-Key` gate on write routes is unchanged and not weakened - the UI
  adapts to the existing auth requirement, it does not loosen it.
- Single deployable image invariant (from the original UI spec) is
  unaffected - no new service/container.

## 10. Out of Scope / Explicit Non-Goals

- Visual/design-system rework of any kind (explicit product direction).
- Real-time push/websocket ingestion status.
- Multi-source management (list/edit/delete arbitrary sources).
- `.docx` or other non-PDF/text file formats.
- OCR for scanned/image-only PDFs.
- Manually triggering a pipeline run from the UI (still out of scope, same
  as the original Brief Viewer spec) - newly ingested content appears in a
  brief only once the existing scheduler/manual-trigger path runs.
- A guided "tour" of the existing read-only panels - onboarding here means
  first-run source setup only, not a UI walkthrough.
