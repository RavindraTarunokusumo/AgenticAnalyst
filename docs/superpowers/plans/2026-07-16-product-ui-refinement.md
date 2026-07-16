# Product UI Refinement - Lightweight Implementation Plan

Spec: `docs/superpowers/specs/2026-07-16-product-ui-refinement-design.md` (accepted).

## File Structure / Task Decomposition

### Backend

1. **`pypdf` dependency** - `pyproject.toml` + regenerated `uv.lock`. No code.
2. **`ExtractorKind` gains upload members** - `domain/models.py`. The enum
   today only has `PRIMARY_HTTP`/`CRAWL4AI` (`domain/models.py:56-60`); a
   `FileExtractor` needs its own value(s) to stamp on `ExtractedArticle.
   extractor` (spec didn't call this out explicitly - a real gap the plan
   is closing). Stored as `String(32)` with no DB check constraint
   (`persistence/models.py:137`), so this is additive/no migration.
3. **`FileExtractor` protocol + implementations** - new
   `ingestion/file_extractor.py` (parallels `ingestion/extractor.py`'s
   `ArticleExtractor` shape). PDF extraction via `pypdf`, plain-text via
   UTF-8 decode (`errors="replace"`, matching `PrimaryHttpExtractor`'s
   existing convention).
4. **`IngestionService` refactor + `ingest_file`** - `ingestion/service.py`.
   Extracts the shared dedup-check-through-persist tail out of
   `_ingest_candidate` into two private helpers both it and the new
   `ingest_file` call. Highest-risk task (touches existing, tested logic).
5. **`POST /ingestion/files` route** - `api/app.py` (new route +
   `IngestionResultResponse` reuse, `_require_key` gate) and `runtime.py`
   (constructs the `file_extractors` mapping once, injected into
   `IngestionService`, mirroring how `primary_extractor`/
   `fallback_extractor` are already constructed once and injected).
6. **Backend tests** - new `tests/unit/test_file_extractor.py`; extend
   `tests/unit/test_ingestion_service.py` (new `ingest_file` cases) and
   `tests/api/test_ingestion.py` (new route, multipart via `TestClient`'s
   `files=` param).

### Frontend

7. **`api.ts` additions** - `frontend/src/api.ts`: new types + typed write
   wrappers, all `X-API-Key`-aware, all throwing on non-2xx (existing
   convention, `api.ts:63-79`).
8. **Onboarding + gating** - new `frontend/src/components/Onboarding.tsx`;
   `App.tsx` gains the `GET /sources` on-mount check and conditional render.
9. **Add-content UI** - new `frontend/src/components/AddContentPanel.tsx`,
   `IngestionResultList.tsx`, `RecentActivityList.tsx`.
10. **API key settings** - new `frontend/src/components/ApiKeySettings.tsx`.
11. **`App.tsx` final wiring** - state + handlers connecting 8/9/10 to the
    `api.ts` wrappers from Task 7.
12. **Docs** - `docs/architecture.md` (new route, `FileExtractor`, new
    frontend components), `docs/commands.md` (any new local-dev note, e.g.
    setting `ALLOW_UNAUTHENTICATED_WRITE` for local testing of the new UI
    flows), `docs/changelog.md`.

Frontend unit tests are not a hard gate, matching this repo's established
precedent (the original Brief Viewer plan/spec didn't mandate them either -
`docs/superpowers/plans/2026-07-15-ui-brief-viewer.md` Task 8, spec §8).
`npm run lint` / `npm run build` (`tsc -b` type-check gate) remain the
frontend's existing CI bar and apply unchanged to all new components.

## Build Order

**Backend chain (sequential, shared-file dependencies):**
1 -> 2 -> 3 -> 4 -> 5 -> 6

Task 4 depends on Task 3's `FileExtractor` protocol existing (even as a
stub) to type its `file_extractors` parameter, and on Task 2's enum values.
Task 5 depends on Task 4's `ingest_file` signature being final.

**Frontend chain (sequential internally, but independent of backend files):**
7 -> 8, 9, 10 (can proceed in any order once 7's types/wrappers are fixed,
they touch disjoint new component files) -> 11 -> (12 docs, once both
chains are stable)

**Cross-chain:** Backend (1-6) and frontend (7-11) touch fully disjoint
files (`src/analyst_engine/`, `pyproject.toml`, `tests/` vs. `frontend/`) -
per CLAUDE.md's parallel-worktree guidance, these two chains can run as two
independent implementer tracks once this plan's interfaces below are fixed,
same pattern as the 2026-07-15 parallel-slices session. End-to-end manual
verification (an actual file upload through the running UI) still requires
both chains landed, so treat that as the final joint step, not something
either track can self-verify alone.

## Per-Task Interfaces

### Task 3: `FileExtractor` (`ingestion/file_extractor.py`)

```
Produces:
  class FileExtractionError(RuntimeError)  # parallels ExtractionFailedError
  Protocol FileExtractor:
    def extract(self, filename: str, content: bytes) -> ExtractedArticle
      # synchronous - no I/O, unlike ArticleExtractor.extract which fetches
  class PdfFileExtractor(FileExtractor)   # pypdf-backed
  class TextFileExtractor(FileExtractor)  # UTF-8 decode, errors="replace"
```

Both implementations raise `FileExtractionError` (not a bare `Exception`)
when no usable text results (e.g. a PDF with no extractable text layer) -
`IngestionService.ingest_file` (Task 4) catches this specifically to record
an `extraction_failed` result, not to be confused with an
`unsupported_file_type` rejection which never reaches the extractor at all.
`ExtractedArticle.title` for `TextFileExtractor` is the filename minus its
extension (spec §5.1); `ExtractedArticle.published_at` is left `None` for
both (spec §4.1: uploads have no real publish date; `ingest_file`, not the
extractor, is what actually decides to stamp `ingested_at` as
`published_at` - see Task 4).

### Task 4: `IngestionService` refactor + `ingest_file`

```
Consumes: FileExtractor (Task 3), ExtractorKind upload member(s) (Task 2)

Produces (new/changed on IngestionService):
  __init__ gains: file_extractors: dict[str, FileExtractor]
    # keyed by content-type string, e.g. {"application/pdf": ..., "text/plain": ...}

  async def ingest_file(
      self, source_id: UUID, filename: str, content: bytes, content_type: str,
  ) -> IngestionResult

  # New private helpers, both called by the existing _ingest_candidate AND
  # by ingest_file - this is the "shared tail" the spec (§5.1) requires:
  async def _check_duplicate(
      self, candidate: ArticleCandidate, url: str, fingerprint: str,
      started_at: datetime,
  ) -> IngestionResult | None
      # None if no existing article; otherwise the already-built duplicate
      # IngestionResult (current inline logic at service.py:192-201, moved
      # verbatim in behavior, not rewritten).

  async def _finalize_extracted(
      self, candidate: ArticleCandidate, canonical_url: str, fingerprint: str,
      extracted: ExtractedArticle, started_at: datetime,
  ) -> IngestionResult
      # title/published_at/content-length validation + Article build +
      # race-safe persist (current inline logic at service.py:249-290+,
      # moved verbatim in behavior).
```

`_ingest_candidate` becomes: canonicalize -> `_check_duplicate` (return if
not None) -> extract-with-fallback (unchanged try/except block) ->
`_finalize_extracted`. Behavior must be byte-for-byte identical to today -
this is a pure extract-method refactor, not a logic change. Verify via the
existing `tests/unit/test_ingestion_service.py` and
`tests/integration/test_ingestion_concurrency.py` passing unmodified before
adding any new file-upload test (isolates "did the refactor break anything"
from "does the new feature work").

`ingest_file`: compute `content_hash = sha256(content).hexdigest()`, build
`url = f"upload://{content_hash}"`, `fingerprint = content_hash` (spec
§4.1), construct an `ArticleCandidate(source_id=source_id, source_feed_id=
None, url=url, title=None, author=None, published_at=None, entry_id=None)`,
call `_check_duplicate` (return if found), look up
`self.file_extractors.get(content_type)` - if missing, record a failure
with `error_code="unsupported_file_type"` (same `_record_failure` helper
`_ingest_candidate` already uses, unchanged signature). On a hit, call
`extractor.extract(filename, content)`; on `FileExtractionError`, record
`error_code="extraction_failed"`. On success, if
`extracted.published_at is None`, copy it with `extracted.published_at =
self._clock()` before calling `_finalize_extracted` (this is where "uploads
use ingestion time as published_at" from spec §4.1 actually gets applied -
not inside the extractor, which has no clock).

### Task 5: `POST /ingestion/files` route

```
Consumes: IngestionService.ingest_file (Task 4)

Produces:
  POST /ingestion/files  (multipart/form-data: source_id, file)
    -> 200 IngestionResultResponse  (single object, not a list - one file
       per call, per spec §5.1)
    -> same _require_key gate as /sources and /ingestion/urls
```

Route reads `await file.read()` once, checks `len(content) >
settings.article_max_response_size_bytes` before calling `ingest_file` -
oversized uploads never reach extraction. If the check fails, build the
same `IngestionResultResponse` shape the service returns for other
failures (`status="failed"`, `error_code="file_too_large"`) directly in the
route rather than a raw `413`, so the frontend's per-item result renderer
(Task 9) handles every failure mode uniformly with no special-casing.
`runtime.py` gains the `file_extractors` dict construction (Task 3's two
classes, keyed `"application/pdf"` / `"text/plain"`) alongside the existing
`build_ingestion_service` wiring.

### Task 7: `api.ts` additions

```
Produces (types, mirroring api/app.py's Pydantic models exactly):
  Source { id, stable_id, name, normalized_domain, feeds: FeedHealth[] }
  FeedHealth { id, feed_url, enabled, poll_interval_minutes,
               last_polled_at, last_success_at, last_error_summary }
  IngestionResult { candidate_url, status, article_id, error_code, error_summary }
  IngestionAttempt { id, source_id, source_feed_id, requested_url,
                      canonical_url, status, http_status, extractor,
                      article_id, error_code, error_summary,
                      started_at, completed_at }

  fetchSources(): Promise<Source[]>
  registerSource(apiKey: string, req: {stable_id, name, normalized_domain,
                 feeds: {feed_url, enabled?, poll_interval_minutes?}[]}
                ): Promise<Source>
  ingestUrls(apiKey: string, sourceId: string, urls: string[]
            ): Promise<IngestionResult[]>
  ingestFile(apiKey: string, sourceId: string, file: File
            ): Promise<IngestionResult>
  fetchIngestionAttempts(limit?: number): Promise<IngestionAttempt[]>
```

All write wrappers set `X-API-Key: apiKey`; all wrappers (read and write)
throw on non-2xx via the existing `parseErrorDetail` helper (`api.ts:46-61`,
reused unchanged) - do not add a second error-handling convention.
`ingestFile` builds a `FormData` (source_id + file), not a JSON body.

### Task 8: Onboarding + gating (`Onboarding.tsx`, `App.tsx`)

```
Consumes: fetchSources, registerSource (Task 7)

Produces:
  <Onboarding onRegistered={(source: Source, apiKey: string) => void} />
  App.tsx new state: sources: Source[] | null, sourcesLoading: boolean,
                      sourcesError: string | null,
                      apiKey: string | null  (initialized from
                      localStorage.getItem('ae_api_key'))
```

On mount, `App.tsx` calls `fetchSources()` (no key needed - `GET /sources`
is a read route, no `X-API-Key`). Empty array -> render `<Onboarding>` in
place of the normal 3-panel view. Non-empty -> normal view (unchanged from
today) plus the new "Add content" control becomes visible. `Onboarding`'s
own submit calls `registerSource` with the key the user just typed (not yet
in `localStorage` at that point), and on success both persists it
(`localStorage.setItem('ae_api_key', apiKey)`) and invokes
`onRegistered(source, apiKey)` so `App.tsx` can populate `sources`/`apiKey`
state without a redundant re-fetch.

### Task 9: Add-content UI

```
Consumes: registerSource, ingestUrls, ingestFile, fetchIngestionAttempts
          (Task 7); apiKey, sources[0].id (Task 8/11)

Produces:
  <AddContentPanel apiKey={string} sourceId={string}
                    onSubmitted={() => void} />
    # internal mode state: 'links' | 'feed' | 'file'; renders
    # <IngestionResultList> for whichever mode's response came back;
    # calls onSubmitted() once a request settles (success or failure) so
    # the parent can refetch recent activity.
  <IngestionResultList results={IngestionResult[]} />
  <RecentActivityList attempts={IngestionAttempt[] | null}
                       loading={boolean} error={string | null} />
```

`RecentActivityList` is rendered by `App.tsx` (Task 11), not owned by
`AddContentPanel` - it reflects `GET /ingestion/attempts` history
independent of any single panel session, matching spec §3.2's "persistent
view... not a live/polled feed." `App.tsx` refetches it in the
`onSubmitted` callback.

Two things `AddContentPanel` must distinguish (spec §7 edge cases): a
**thrown** error from an `api.ts` wrapper (network failure, or a 401/403
from a wrong/expired API key - `_require_key` rejects before the service
ever runs, so there's no `IngestionResultResponse` body to parse) versus a
**successful response whose items include per-URL/file failures**
(`status: "failed"` inside an otherwise-200 `IngestionResult[]`). The former
renders as a single inline panel error ("check your API key" for
401/403, the raw message otherwise); the latter renders via
`IngestionResultList` per spec §3.2. Do not conflate the two into one error
path - a wrong API key is not a per-item ingestion failure.

`IngestionResultList` should render an uploaded file's `candidate_url`
(which will be the synthetic `upload://<hash>` from spec §4.1, not a
human-readable filename) reasonably - e.g. falling back to whatever
filename the panel already has in local state for that submission, rather
than printing the raw hash-URL. This is a display nicety, not a new backend
field - `IngestionResultResponse` is not changed to carry a filename.

### Task 10: API key settings

```
Consumes: apiKey (Task 8), a setter callback from App.tsx

Produces:
  <ApiKeySettings apiKey={string | null} onSave={(key: string) => void} />
```

`onSave` both updates `App.tsx`'s `apiKey` state and writes
`localStorage.setItem('ae_api_key', key)` - same storage key `Onboarding`
(Task 8) uses, so either entry point keeps the two in sync.

### Task 11: `App.tsx` final wiring

No new produces beyond the assembled app - wires Tasks 8/9/10's components
and Task 7's wrappers together: `sources`/`apiKey` state (Task 8) feeds
`AddContentPanel`'s `sourceId`/`apiKey` props (Task 9) and
`ApiKeySettings`'s `apiKey` prop (Task 10); `AddContentPanel`'s
`onSubmitted` triggers the `RecentActivityList` refetch. The existing
cadence/brief-list/brief-detail state and handlers (`App.tsx:9-72`) are
unchanged - this task only adds to `App.tsx`, it does not restructure the
existing read-only behavior.

## Risks

- **Refactor regression (Task 4)**: extracting `_check_duplicate`/
  `_finalize_extracted` out of `_ingest_candidate` is the single highest-risk
  step in this plan - it touches tested, production logic that every
  existing ingestion path (manual URL, feed poll) depends on. Run
  `tests/unit/test_ingestion_service.py` and
  `tests/integration/test_ingestion_concurrency.py` immediately after the
  refactor, before writing a single line of new file-upload code, to
  isolate a refactor-only regression from a new-feature bug.
- **`ExtractorKind` is additive, not migrated**: confirmed the column is a
  plain `String(32)` (`persistence/models.py:137`) with no DB-level enum
  constraint - adding new Python enum members needs no Alembic migration.
  Flag explicitly so the implementer doesn't add one speculatively.
- **Large-upload memory use**: Task 5's route reads the full multipart body
  into memory before the size check, rather than streaming/bounding the
  read like `bounded_http.py` does for HTTP fetches. Acceptable for a first
  version (uploaded articles/PDFs aren't expected to be large), but this is
  a known ceiling, not an oversight - do not silently "fix" it into a
  streaming implementation mid-task; if it needs to change, that's a
  follow-up, not scope creep into this plan.
- **Client-held API key (Tasks 8/10)**: `localStorage` is readable by any
  JS running on the page - this is a deliberate, already-accepted trade-off
  from spec acceptance (§ "API key handling" decision), not a gap to
  "harden" during implementation. No login/session system exists to do
  better against in this slice.
- **Multipart testing**: FastAPI's `TestClient` supports a `files=` kwarg
  for multipart requests directly - use that in Task 6's route tests rather
  than hand-constructing multipart bodies.
- **New Python dependency (`pypdf`)**: Task 1 requires `uv sync` to
  regenerate `uv.lock`; treat the first CI run after this dependency lands
  as a required check (matching the 2026-07-14 session's insight that a
  local "tests passed" claim isn't sufficient when environment/dependency
  drift is possible - here, a fresh `uv.lock` resolution).
- **CI**: no workflow changes needed - the existing `quality` job already
  runs `pytest`/`mypy`/`ruff` over all of `src`/`tests`, and the existing
  `frontend` job already runs `npm run lint`/`npm run build` over all of
  `frontend/src`. Both pick up this plan's new files automatically.
