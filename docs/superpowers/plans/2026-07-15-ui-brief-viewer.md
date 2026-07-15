# UI / Brief Viewer - Lightweight Implementation Plan

Spec: `docs/superpowers/specs/2026-07-15-ui-brief-viewer-design.md` (accepted, revised
to a React app - see spec §3.1 revision note).

## File Structure / Task Decomposition

1. **`frontend/` scaffold** - Vite + React + TS + Tailwind project
   (`frontend/package.json`, `frontend/vite.config.ts`, `frontend/tailwind.config.ts`,
   `frontend/src/main.tsx`, `frontend/src/index.css`, `frontend/index.html`)
2. **API client module** - `frontend/src/api.ts` (typed fetch wrappers for the two
   existing routes, mirroring the Pydantic response shapes)
3. **Components**: `CadenceTabs`, `BriefList`, `BriefDetail`, `LoadingState`,
   `EmptyState`, `ErrorState` - `frontend/src/components/`
4. **App shell / state** - `frontend/src/App.tsx` (selected cadence, selected brief
   ID, list data, detail data, loading/error flags - plain `useState`, no store lib)
5. **Backend mount** - one line in `src/analyst_engine/api/app.py`'s `create_app()`
6. **`Dockerfile` multi-stage build** - add a Node build stage, `COPY` its output
   into the existing Python stage
7. **Local-dev fallback** - placeholder `src/analyst_engine/api/static/index.html`
   (or documented `npm run build` prerequisite) so `uv run`/pytest never 404 on a
   fresh checkout with no frontend build yet run (spec §5.2)
8. **Tests**: backend (route mount serves something at `/ui/`, existing `GET /briefs`
   tests untouched), frontend (component-level tests only if the plan's build order
   leaves time - not a hard gate per spec §8, which doesn't list frontend unit tests
   as a success criterion)
9. **Docs**: `docs/architecture.md` (new `/ui/` mount + Node build stage),
   `docs/commands.md` (`npm install`/`npm run build`/`npm run dev` local commands),
   `docs/changelog.md`

## Build Order

1 -> 2 -> 3, 4 (component shells can be built alongside the API client once its
shape is fixed) -> 5, 6, 7 (backend-side, independent of frontend internals, can
proceed in parallel with 3/4 once 1-2 exist) -> 8 -> 9

Task 5 (the `app.mount` line) only depends on the static directory path existing
(even empty/placeholder) - it does not need the full frontend built first, so it
can land early to unblock backend testing.

## Per-Task Interfaces

### Task 2: API client (`frontend/src/api.ts`)

```
Consumes: fetch('/briefs?cadence=<daily|weekly|monthly>') -> BriefListItem[]
Consumes: fetch('/briefs/{id}') -> BriefDetail
Produces (TS types, mirroring api/app.py's Pydantic models exactly):
  BriefListItem { id, cadence, covered_start, covered_end, created_at }
  BriefDetail { id, cadence, covered_start, covered_end, content,
                narrative_state_version_id, created_by_run_id, created_at,
                cited_summaries: ResolvedBatchSummary[] }
  ResolvedBatchSummary { id, model, prompt_version, summary, source_notes,
                          entities, topics, citations: ResolvedCitation[] }
  ResolvedCitation { article_url, source_name, ... }
```

Field names/types must match `BriefListItemResponse`/`BriefDetailResponse`
(`api/app.py:175-193`) exactly - if those response models ever change, this file is
the single place to update on the frontend side. Both fetch functions throw on
non-2xx (including 404) so callers can drive the error-state UI; do not swallow
errors inside this module.

### Task 3/4: Components + App shell

```
CadenceTabs: Consumes { active: Cadence, onChange: (c: Cadence) => void }
BriefList: Consumes { items: BriefListItem[] | null, loading: bool, error: string | null,
                       onSelect: (id: string) => void }
BriefDetail: Consumes { brief: BriefDetail | null, loading: bool, error: string | null }
```

`App.tsx` owns all state and wires `api.ts` calls to these props - components stay
presentational (no fetch calls inside components themselves), so component tests
(if written) can mock props directly without a network layer.

### Task 5: Backend mount

```
Consumes: nothing new (static directory path)
Produces: GET /ui/ and /ui/* served from src/analyst_engine/api/static/
```

`app.mount("/ui", StaticFiles(directory=<static_dir>, html=True), name="ui")` added
in `create_app()` (`api/app.py`) after all `@app.get`/`@app.post` declarations,
before `return app` (line ~588). Must not shadow any existing route prefix - `/ui`
does not collide with any current route (`/healthz`, `/readyz`, `/workflows`,
`/sources`, `/ingestion`, `/pipelines`, `/briefs`).

### Task 6: Dockerfile multi-stage

```
Consumes: frontend/ source tree
Produces: src/analyst_engine/api/static/ populated in the final image
```

New first stage (e.g. `FROM node:22-slim AS frontend-build`, `WORKDIR /app/frontend`,
`COPY frontend/package*.json ./`, `RUN npm ci`, `COPY frontend/ ./`,
`RUN npm run build`). In the existing `runtime` stage, after `COPY src ./src`, add
`COPY --from=frontend-build /app/frontend/dist ./src/analyst_engine/api/static`.
Everything else in the current single-stage Dockerfile (Playwright/Chromium install,
non-root user, entrypoint) is unchanged - this task only adds the new stage and one
`COPY --from`.

### Task 7: Local-dev fallback

```
Consumes: nothing
Produces: a non-404 response at GET /ui/ even with no frontend build run locally
```

Simplest option (recommended over a documented mandatory local step, per YAGNI -
fewer required manual steps beats a doc that will be skipped): commit a minimal
static `src/analyst_engine/api/static/index.html` placeholder ("Run `npm run
build` in frontend/ to build the viewer.") to git, and add `frontend/dist/` (the
real build output, which overwrites the placeholder locally when built) to
`.gitignore`. CI/Docker builds always overwrite it via Task 6; local backend-only
work never 404s.

## Risks

- **Node toolchain drift**: this is the first Node dependency in the repo - pin
  `package-lock.json` (committed) and a Node version (`.nvmrc` or Dockerfile's
  explicit tag) so builds are reproducible, matching the existing `.python-version`
  pinning convention already used for Python.
- **Static-mount path collision**: verify `/ui` doesn't collide with any future
  route prefix before merging (currently clear - see Task 5).
- **CI**: the existing `ci` workflow (`quality` job, seen on PR #5) runs
  `ruff`/`mypy`/`pytest` - it will not build or test the frontend unless this slice
  also adds an `npm run build`/lint step to CI. Flag explicitly for the implementer:
  either extend CI in this same PR (recommended, so a broken frontend build isn't
  discovered only in the Docker image build) or note the gap in `docs/testing.md`
  if deferred - do not leave it silently unaddressed.
- **Placeholder/build drift**: if `frontend/dist/` is gitignored (Task 7) and CI
  doesn't build it, a reviewer testing `/ui/` locally without running `npm run
  build` will only see the placeholder and may mistake it for a bug - document this
  clearly in `docs/commands.md` (Task 9).
