# 2026-07-15 — UI / Brief Viewer (codex/ui-brief-viewer)

**Merge:** PR #6 (https://github.com/RavindraTarunokusumo/AgenticAnalyst/pull/6)
**Merge commit:** e85f202af8750c5b166ba5d28721794d8f0daca9
**Feature branch:** codex/ui-brief-viewer
**Merged:** 2026-07-15T20:24:55Z

## Completed Work

- [x] `frontend/` scaffold - Vite + React + TS + Tailwind (`aec2035`)
- [x] API client module (`frontend/src/api.ts`) (`5fd109e`)
- [x] Components: `CadenceTabs`, `BriefList`, `BriefDetail`, loading/empty/error
      states (`ae1b965`)
- [x] App shell / state (`frontend/src/App.tsx`) (`4d12bfe`)
- [x] Backend static mount (`api/app.py`) + local-dev fallback placeholder
      (`9334828`)
- [x] `Dockerfile` multi-stage build - Node build stage + `COPY` into runtime
      stage (`8daedad`)
- [x] CI: frontend job (`npm ci`, `oxlint`, `npm run build`) (`a596b16`)
- [x] Tests: backend mount smoke test, Dockerfile-structure assertion update
      (`2a956b6`)
- [x] Docs: `docs/architecture.md`, `docs/commands.md`, `docs/changelog.md`
      (`75505de`)
- [x] Code review fixes: stale-fetch race in `handleSelectBrief`, citation-href
      scheme validation, missing dev-server proxy (`240f6f8`)
- [x] Merge conflict resolution against `main` (TODO.md adjacency) (`aaa0256`)

## Summary

The product was API-only end to end (RSS-to-Daily and Weekly/Monthly slices
both explicitly scoped UI out) - `GET /briefs` was only usable via
`curl`/`gh`. This slice adds a read-only React + TypeScript + Vite +
Tailwind CSS SPA (`frontend/`, the repo's first Node/npm toolchain), served
at `GET /ui/*` via FastAPI's `StaticFiles`, backed entirely by the existing
`GET /briefs`/`GET /briefs/{brief_id}` routes - cadence tabs, a brief list
panel, and a detail panel (content, resolved citations, entity/topic chips).

The spec was originally scoped as a bare static HTML file with no build
step; the user explicitly rejected that during spec acceptance ("No static
build, full implementation with working buttons, visuals and panels"),
requiring a substantive spec rewrite to a real React app before planning
began. The Dockerfile gained a first Node `frontend-build` stage whose
`dist/` output is copied into the existing Python runtime stage, keeping one
deployable image; a committed placeholder `index.html` keeps `/ui/` from
404ing on a fresh checkout with no frontend build run yet (`frontend/dist/`
is gitignored). CI gained a parallel `frontend` job so a broken frontend
build is caught in CI, not only at Docker-image build time.

An independent ephemeral code-review agent found three real issues, all
fixed before merge: a stale-response race in `handleSelectBrief` (a slower
detail fetch for an earlier click could overwrite a faster one for a later
click, or repopulate state after a cadence switch had already reset it -
fixed with a request-id ref guard, extended to `handleCadenceChange` too,
which the reviewer's finding required to close fully); an unvalidated
citation `href` (article URLs are already canonicalized to http(s) at
ingestion time, so not currently exploitable, but hardened as defense-in-
depth against a future write path); and `docs/commands.md` claiming a Vite
dev-server proxy that was never actually configured (added the real proxy
rather than weakening the docs claim).

Root cause: not a bug - a net-new feature closing a named product gap.

## Verification

- `uv run ruff format --check .` / `uv run ruff check .` / `uv run mypy src
  tests` / `uv run pytest` - all green (248 passed, 2 skipped) at each
  commit; 266 passed, 2 skipped on `main` after both this and the archive-
  retrieval slice merged.
- `npm run build` (`tsc -b && vite build`) / `npm run lint` (oxlint) - clean.
- Manual validation: built the real frontend bundle and served it through
  the actual `create_app()` static mount (via the existing `make_client`
  test harness, no live DB needed) - confirmed `GET /ui/` returns the real
  built `index.html`, its JS asset bundle loads with the correct
  content-type, and `GET /healthz` is unaffected.
- CI (`quality` + new `frontend` job) green on the final commit.
