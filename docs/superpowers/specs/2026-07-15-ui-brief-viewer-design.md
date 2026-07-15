# UI / Brief Viewer Design

## 1. Purpose

AnalystEngine is API-only end to end today (`docs/architecture.md`: "The
product is API-only end to end"). `GET /briefs` and `GET /briefs/{brief_id}`
already return everything a human needs to read a brief, but the only way to
reach them is `curl`/`gh`/a REST client. This slice adds a minimal read-only
web page that lets a human browse briefs by cadence and read one, with zero
new write surface and zero new backend capability - it is presentation only.

## 2. What Already Exists (verified against the current codebase)

- `GET /briefs?cadence=daily|weekly|monthly` -> `list[BriefListItemResponse]`
  (`id`, `cadence`, `covered_start`, `covered_end`, `created_at`) -
  `api/app.py:489-515`. Already cadence-generic (parses via `Cadence(cadence)`,
  400 on invalid value). No changes needed.
- `GET /briefs/{brief_id}` -> `BriefDetailResponse` (`content`, plus
  `cited_summaries: list[ResolvedBatchSummaryResponse]`, each citation already
  resolved to `article_url`/`source_name` via `ResolvedCitationResponse`) -
  `api/app.py:517+`. No changes needed.
- Both routes are read routes and stay open with no `X-API-Key` requirement
  (`docs/architecture.md` §API/Delivery) - the viewer needs no auth story.
- No templating engine, no static-file mount, and no frontend dependency
  exists anywhere in `pyproject.toml` today - confirmed by grep, this is a
  greenfield addition, not a hookup to existing infrastructure.
- FastAPI is built on Starlette, which ships `starlette.staticfiles.
  StaticFiles` - already present transitively via the existing `fastapi`
  dependency. No new package is required to serve a static page.

## 3. Product Behavior

### 3.1 Scope: read-only, single static page, no build step

One static HTML file (inline CSS + vanilla JS, no framework, no bundler, no
npm) that:

1. On load, fetches `GET /briefs?cadence=daily` and renders a list (date
   range + created_at per row, newest first - the API already returns them
   in that order per `list_prior_briefs`).
2. A cadence selector (`<select>`: daily/weekly/monthly) re-fetches
   `GET /briefs?cadence=<value>` on change.
3. Clicking a list row fetches `GET /briefs/{brief_id}` and renders the brief
   `content` (plain text/markdown-as-text, no markdown rendering library -
   `content` is a plain string field, not HTML) plus a citations list (each
   citation's `article_url` as a link, `source_name` as a label).
4. No pagination control - `GET /briefs` has no documented limit/offset
   params today; the viewer renders whatever the endpoint returns. (Follow-up,
   not in scope: paginating `GET /briefs` itself.)

### 3.2 Explicitly out of scope

- No write actions (no trigger buttons, no source management UI) - keeps the
  read-open/write-`X-API-Key`-gated boundary untouched.
- No auth/login screen - matches the existing "read routes stay open" design.
- No new backend logic, schema, or response fields.
- No client-side routing/framework/build tooling.
- No markdown rendering of `content` - rendered as preformatted text.

## 4. Data Model

None. No new domain models, ORM tables, or migrations. The page is a pure
consumer of the two existing response models above.

## 5. Interfaces

### 5.1 New backend surface

- `app.mount("/ui", StaticFiles(directory=<path>, html=True), name="ui")` in
  `api/app.py`'s app-factory function, registered **after** all `@app.get`/
  `@app.post` route declarations (mount order does not affect precedence for
  disjoint path prefixes, but keeping it last matches the existing
  registration convention of routes-then-wiring in that function).
  - Serves `GET /ui/` -> `index.html` (the `html=True` flag makes StaticFiles
    resolve directory index requests without an explicit filename).
  - Static directory: `src/analyst_engine/api/static/` (new directory,
    tracked in git, containing exactly `index.html`).
- No new Pydantic response models, no new repository functions, no new
  pipeline/graph changes.

### 5.2 Consumes (existing, unchanged)

- `GET /briefs?cadence=<str>` -> `list[BriefListItemResponse]`
- `GET /briefs/{brief_id}` -> `BriefDetailResponse`

### 5.3 Produces

- `GET /ui/` -> `text/html` (the viewer page)
- Static asset requests under `/ui/*` -> whatever else lives in the static
  directory (none beyond `index.html` for this slice)

## 6. Workflow

1. Browser loads `/ui/`.
2. Page JS calls `fetch('/briefs?cadence=daily')`, renders list.
3. User changes cadence dropdown -> re-fetch with new `cadence` query param.
4. User clicks a brief row -> `fetch('/briefs/{id}')`, render detail view
   (content + citations), with a "back to list" control that re-renders the
   last-fetched list from memory (no re-fetch needed).
5. No server-side state; every load is a fresh fetch against the existing
   read API.

## 7. Edge Cases

- Empty brief list for a cadence (no briefs generated yet): render an empty
  state message, not a blank page or JS error.
- `GET /briefs/{brief_id}` 404 (stale/bad ID, e.g. a race with data changing
  between list-fetch and click): render an inline error message in the
  detail pane, do not navigate away or throw an unhandled rejection.
- Network/fetch failure (backend down): render a visible error state, not a
  silent blank page.
- `content` containing characters that would be interpreted as HTML: must be
  inserted via `textContent`/`innerText`, never `innerHTML`, to avoid
  reflecting API data as executable markup (defense-in-depth XSS
  prevention - `content` today only comes from LLM-generated brief text
  which is already treated as untrusted downstream, per
  `docs/patterns.md`'s "no compatibility shims"/no free trust extension
  principle).
- Long article/source lists per brief: no truncation logic added; renders
  whatever the API returns.

## 8. Success Criteria

- A human can open `/ui/`, see the three cadences, and read the full content
  and citations of any existing brief without using `curl` or a REST client.
- Zero new write routes, zero new auth requirements, zero new third-party
  frontend dependency in `pyproject.toml`.
- Existing `GET /briefs` / `GET /briefs/{brief_id}` contracts and tests are
  untouched (no response-model changes).

## 9. Constraints

- No new Python dependency (StaticFiles ships with the existing `fastapi`
  transitive dependency on Starlette - verify still true at implementation
  time via `uv tree | grep starlette` before assuming).
- No frontend build step, no npm/node toolchain introduced to the repo or
  Docker image.
- Must not touch `pipeline/`, `workflows/`, `persistence/`, or `domain/` -
  this slice is additive-only at the API/static layer.
- Must not weaken the existing write-route `X-API-Key` gate or open any new
  write path.

## 10. Out of Scope / Explicit Non-Goals

- Pagination, search, filtering beyond cadence.
- Any visual design system beyond "readable, functional." No design-taste
  skill invocation warranted for an internal read-only debug-grade viewer.
- Mobile-responsive polish beyond not being unusable on a narrow viewport.
- Server-side rendering/templating (Jinja2 or otherwise) - a static file is
  sufficient since there is no per-request server-side state to inject.
