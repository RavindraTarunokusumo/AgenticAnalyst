# UI / Brief Viewer Design

## 1. Purpose

Agentic Analyst is API-only end to end today (`docs/architecture.md`: "The
product is API-only end to end"). `GET /briefs` and `GET /briefs/{brief_id}`
already return everything a human needs to read a brief, but the only way to
reach them is `curl`/`gh`/a REST client. This slice adds a real, read-only
web app (working panels and interactions, not a bare debug page) that lets
a human browse briefs by cadence and read one, with zero new write surface
and zero new backend capability - it is presentation only, backed entirely
by the two existing read routes.

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

### 3.1 Scope: read-only, real frontend app with a build step

Revised per explicit product direction: a bare static HTML file was rejected
in favor of a full working UI (real interactive components, visuals, panels)
- not a debug-grade page. Stack: **React + TypeScript + Vite + Tailwind CSS**
(most common, well-supported combination for this shape of app; no exotic
tooling). This is a genuine new capability for the repo (first Node/npm
toolchain, first frontend build step) - the trade against "no new tooling"
is deliberate and accepted by the product direction, not a silent scope
creep.

- New `frontend/` directory at repo root: Vite + React + TS project,
  `package.json`/`package-lock.json` tracked in git, `node_modules/`
  gitignored.
- Panels/components (all read-only, all driven by existing API data):
  - **Cadence tabs/switcher** (daily/weekly/monthly) - active tab drives the
    list query.
  - **Brief list panel** - cards or rows for `GET /briefs?cadence=<value>`
    results (covered date range, created_at), selectable.
  - **Brief detail panel** - shows `GET /briefs/{brief_id}` result: content
    (preformatted, not raw HTML - see §7 XSS note, unchanged), a citations
    panel listing each resolved citation (`article_url` as a link,
    `source_name` as a label, `entities`/`topics` chips if present on the
    underlying `ResolvedBatchSummaryResponse` - already returned today).
  - Loading, empty, and error states are real UI states (skeleton/spinner,
    "no briefs yet" empty panel, inline error panel), not console errors.
- No pagination control - `GET /briefs` has no documented limit/offset
  params today; the viewer renders whatever the endpoint returns. (Follow-up,
  not in scope: paginating `GET /briefs` itself.)
- No client-side routing library needed for three panels/one selected-brief
  state - plain React state (`useState`) is sufficient; do not add
  `react-router` for a single-route app (YAGNI - add it if/when a second
  route, e.g. the archive-search UI noted in §10, actually lands).

### 3.2 Explicitly out of scope

- No write actions (no trigger buttons, no source management UI) - keeps the
  read-open/write-`X-API-Key`-gated boundary untouched.
- No auth/login screen - matches the existing "read routes stay open" design.
- No new backend logic, schema, or response fields.
- No client-side routing library (§3.1 - plain component state covers this
  slice's three panels).
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
    tracked in git as **build output**, not hand-authored source - see §5.4).
- No new Pydantic response models, no new repository functions, no new
  pipeline/graph changes. The backend's only change is the one `app.mount`
  line plus whatever compiled frontend assets land in the static directory.

### 5.2 Frontend build (new)

- `frontend/`: Vite + React + TS source (`src/`, `index.html` entry,
  `package.json`, `vite.config.ts`, `tailwind.config.ts`). `npm run build`
  outputs to `frontend/dist/`.
- `Dockerfile` gains a Node build stage (multi-stage build: Node stage runs
  `npm ci && npm run build`, final Python stage `COPY`s
  `frontend/dist/` -> `src/analyst_engine/api/static/`) so the shipped image
  remains a single deployable artifact - unchanged invariant from
  `docs/architecture.md` ("Local Compose declares exactly `app`, `postgres`,
  and `searxng` services", i.e. no separate frontend service/container).
- Local dev: `frontend/dist/` (or a committed placeholder) must exist for
  `uv run` / pytest to start the API without requiring a Node toolchain on
  every contributor machine for backend-only work - the lightweight plan
  must resolve exactly how (e.g. `.gitignore` the build output but document
  `npm run build` as a required local step before `docker compose up`, or
  commit a minimal fallback `index.html` so `StaticFiles` never 404s on a
  fresh checkout with no frontend build yet run).

### 5.3 Consumes (existing, unchanged)

- `GET /briefs?cadence=<str>` -> `list[BriefListItemResponse]`
- `GET /briefs/{brief_id}` -> `BriefDetailResponse`

### 5.4 Produces

- `GET /ui/` -> `text/html` (the app shell)
- Static asset requests under `/ui/*` -> the built JS/CSS bundle and any
  other Vite build output (hashed filenames, per Vite's default build
  behavior), not just a single `index.html`.

## 6. Workflow

1. Browser loads `/ui/` -> React app shell mounts, default cadence tab
   (daily) selected.
2. App fetches `GET /briefs?cadence=daily`, shows a loading state, then
   renders the list panel (or the empty-state panel if `[]`).
3. User switches cadence tab -> re-fetch with new `cadence` query param,
   list panel shows its loading state again.
4. User selects a brief row -> `fetch('/briefs/{id}')`, detail panel shows
   its own loading state, then renders content + citations panel on
   success or an inline error panel on failure/404. The list panel and its
   already-fetched data are unaffected (no re-fetch on "back").
5. No server-side state; every fetch is against the existing read API. All
   state (selected cadence, selected brief, in-flight/error status) lives
   in React component state, not a global store (YAGNI for this size app).

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

- A human can open `/ui/`, switch cadence tabs, browse the brief list panel,
  select a brief, and read its full content and resolved citations panel -
  all via real interactive components, not raw text - without using `curl`
  or a REST client.
- Loading, empty, and error states are visibly distinct panels, not console
  errors or blank screens.
- Zero new write routes, zero new auth requirements, zero new Python
  dependency in `pyproject.toml` (the frontend's Node dependencies are
  scoped to `frontend/` and do not touch the Python dependency graph).
- Existing `GET /briefs` / `GET /briefs/{brief_id}` contracts and tests are
  untouched (no response-model changes).
- `docker compose up` still produces one deployable `app` image containing
  the built frontend - no separate frontend service/container.

## 9. Constraints

- No new Python dependency (StaticFiles ships with the existing `fastapi`
  transitive dependency on Starlette - verify still true at implementation
  time via `uv tree | grep starlette` before assuming). The frontend
  toolchain (Node/npm/React/Vite/Tailwind) is a new **Node** dependency
  tree, scoped entirely to `frontend/`, and must never leak into
  `pyproject.toml`/`uv`'s dependency graph.
- Single deployable image invariant preserved: the Node build stage exists
  only inside the multi-stage `Dockerfile`, never as a separate Compose
  service (§5.4).
- Must not touch `pipeline/`, `workflows/`, `persistence/`, or `domain/` -
  this slice is additive-only at the API/static layer plus the new
  `frontend/` tree.
- Must not weaken the existing write-route `X-API-Key` gate or open any new
  write path - the frontend only ever calls the existing open read routes.

## 10. Out of Scope / Explicit Non-Goals

- Pagination, search, filtering beyond cadence.
- Mobile-responsive polish beyond not being unusable on a narrow viewport
  (real panels/components still apply, but exhaustive breakpoint tuning is
  not required for this slice).
- Server-side rendering/templating (Jinja2 or otherwise) - React renders
  client-side against the existing JSON API; no per-request server-side
  state to inject.
- Any write actions, auth/login screen, or new backend response fields
  (unchanged from the original scope, §3.2).
- The archive-search box mentioned as a future consumer in the Archive
  Retrieval spec's §10 - this slice's panels are cadence browse + detail
  only; wiring a search box against `GET /archive/search` is a follow-up.
