# 2026-07-15 — Archive Retrieval / Semantic Search (codex/archive-retrieval)

**Merge:** PR #7 (https://github.com/RavindraTarunokusumo/AgenticAnalyst/pull/7)
**Merge commit:** 87bba3dda3a8b80c3ade649b097a2bf3cab5f940
**Feature branch:** codex/archive-retrieval
**Merged:** 2026-07-15T20:30:39Z

## Completed Work

- [x] `ModelGateway.embed()` abstract method + `FakeModelGateway.embed()`
      (`3c0424d`) - scope extension: 5 more test-local fakes across 5 files
      also directly extend `ModelGateway` and needed `embed()` too, landed in
      the same commit to keep collection green
- [x] `DashScopeAdapter.embed()` + happy/error tests (`a444a9b`)
- [x] `OpenRouterAdapter.embed()` + rejection test (`f95c6af`)
- [x] `search_embeddings_by_similarity()` repository function + pgvector
      integration test (`974ebe2`)
- [x] Best-effort embedding wired into `synthesize` node, SAVEPOINT-protected
      (`05a5312`)
- [x] `GET /archive/search` route + response model + route tests (`45ecb06`)
- [x] Docs: `docs/architecture.md`, `docs/changelog.md` (`2a4c352`)
- [x] Code review fixes: `RetryableModelError` handling, embed() moved out of
      `session_scope` (`86595dd`)
- [x] Merge conflict resolution against `main` (TODO.md, app.py imports/route
      ordering, changelog.md, architecture.md) (`842d219`, `de6d7d8`)

## Summary

`Embedding` (domain model + `save_embedding` repository function) existed
from an earlier slice but was never called from any pipeline or graph node -
there was no embedding generation step and no read API to query by
similarity, the largest gap between the product (three cadences of briefs,
browsable only by cadence+date) and "narrative memory you can actually
query," per `TODO.md`'s Future Backlog.

This slice adds `ModelGateway.embed()` (DashScope calls the real embeddings
endpoint; OpenRouter unconditionally rejects, no embeddings endpoint there),
best-effort embedding generation wired into the `synthesize` node after
`save_brief`, a `search_embeddings_by_similarity` repository function
(pgvector cosine-distance ordering, optional cadence filter), and a new
`GET /archive/search` route.

The plan's suggested transaction-safety resolution for the synthesize-node
side effect (a bare `try/except Exception: pass` around `save_embedding`)
was verified empirically to be insufficient: a DB-level `save_embedding`
failure (e.g. a vector-dimension mismatch) aborts the whole Postgres
transaction, so the plain try/except still leaves `session_scope`'s
subsequent `commit()` raising `PendingRollbackError` - the brief would not
actually persist despite the exception being "swallowed." Fixed with a
SAVEPOINT (`session.begin_nested()`), verified by temporarily reverting to
the plain try/except, confirming the new DB-level-failure integration test
failed exactly as predicted, then restoring the fix.

An independent ephemeral code-review agent found three issues: `search_archive`
only caught `TerminalModelError`, not `RetryableModelError` (a transient
DashScope timeout/rate-limit would surface as a raw 500) - fixed, now both
map to a 503 with distinct messaging; `gateway.embed()` (a network call) ran
inside the SAVEPOINT alongside the DB-only `save_embedding` write, holding a
pooled DB connection/transaction open during the network call - fixed by
moving `embed()` out of `session_scope` entirely; and a suggestion to have
`search_embeddings_by_similarity` return the SQL-computed cosine distance
instead of recomputing similarity in Python - pushed back on (negligible
cost at the current `limit<=50` scale; would touch an already-tested
repository return contract for no measurable gain).

Root cause: not a bug - a net-new feature closing a named product gap.

## Verification

- `uv run ruff format --check .` / `uv run ruff check .` / `uv run mypy src
  tests` / `uv run pytest` - all green at each commit; 263 passed, 2 skipped
  on the feature branch, 266 passed, 2 skipped on `main` after both this and
  the UI slice merged.
- 16 integration tests (including the new pgvector-ordering and
  DB-level-embedding-failure tests) passed against a real
  `pgvector/pgvector:0.8.0-pg16` Testcontainer.
- CI (`quality` job) green on the final commit.
