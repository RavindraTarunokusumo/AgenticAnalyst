# Archive Retrieval / Semantic Search Design

## 1. Purpose

Give Agentic Analyst "narrative memory you can actually query." Today three
cadences of briefs exist and are browsable only by cadence+date
(`GET /briefs`). The `embedding` table, the `Embedding` domain model, and
`save_embedding` (`persistence/repositories.py:439`) already exist, but
nothing ever calls them: no embedding is generated when a brief is created,
and there is no read API to query by similarity. This slice closes both
halves of that gap - generation and retrieval - for briefs only (not raw
articles, matching the existing `docs/database.md` invariant "embeddings
stored only for briefs").

## 2. What Already Exists (verified against the current codebase, not assumed)

- `embedding` table/migration, `Embedding` domain model (`brief_id`, `model`,
  `vector: list[float]`, `metadata: dict`), ORM `Embedding` with
  `vector: Vector(1536)` (pgvector, fixed 1536 dims) - `persistence/
  models.py:209-218`.
- `save_embedding(session, emb) -> Embedding` - `persistence/
  repositories.py:439`. Never called from any pipeline, graph node, or
  route today (confirmed by repo-wide grep).
- `ModelTask.EMBED` already exists in the `ModelTask` enum (`models/
  gateway.py`) and `settings.embedding_model` (default `"text-embedding-v4"`,
  `config.py:131`) is already mapped for it in `DashScopeAdapter.
  _model_map` and explicitly rejected in `OpenRouterAdapter.
  get_model_for_task` (`raise TerminalModelError("OpenRouter adapter does
  not support embeddings")`). **However, no actual embedding call exists
  anywhere** - `ModelGateway` only declares `generate()` (chat-completion +
  structured-output shape) and `get_model_for_task()`. `generate()`'s
  contract (`output_schema: type[BaseModel]`, JSON-mode chat completion)
  does not fit an embeddings call (different endpoint, returns a raw
  vector, no JSON schema). This is genuinely unbuilt, not a hookup.
- Both adapters already hold an `AsyncOpenAI` client
  (`openai` SDK, already a dependency) which natively exposes
  `client.embeddings.create(model=..., input=...)` - no new package needed.
- `_frontier_synthesis` / the shared `synthesize` node in `_build_graph`
  (`workflows/graphs.py:37-161`) is the single node all three cadence graphs
  (`build_daily_graph`/`build_weekly_graph`/`build_monthly_graph`) already
  share. It persists `NarrativeStateVersion`, `PredictionExpectation`s, and
  `Brief` inside one `session_scope` block, then returns. This is the one
  place a `Brief` object exists, already-persisted, for every cadence,
  without duplicating logic per cadence.
- No logging framework exists anywhere in `src/` (verified by repo-wide
  grep for `logging`/`getLogger` - zero hits). The closest existing
  precedent for a non-fatal side-effect failure is LangSmith tracing:
  `docs/patterns.md` - "LangSmith tracing failures are non-fatal
  (observability degradation only)."
- `GET /briefs` / `GET /briefs/{brief_id}` and their response models
  (`api/app.py:175-193`) are the existing read-route pattern to mirror:
  open (no `X-API-Key`), Pydantic response models, resolved citations.

## 3. Product Behavior

### 3.1 Generation: embed every brief at creation time, best-effort

After `save_brief` succeeds inside `synthesize`'s existing `session_scope`
block (`graphs.py`), call `gateway.embed(text=output.brief.content,
correlation_id=inp.correlation_id)` and, on success, `save_embedding` an
`Embedding(brief_id=output.brief.id, model=gateway.get_model_for_task(
ModelTask.EMBED), vector=<result>, metadata={"cadence": cadence.value,
"covered_start": ..., "covered_end": ...})` in the same session.

This must be **best-effort, not fatal to brief creation**:

- `OpenRouterAdapter` raises `TerminalModelError` for `ModelTask.EMBED`
  unconditionally (see §2) - if embedding generation were fatal, every
  brief creation on an OpenRouter-configured deployment would break, which
  is an unacceptable regression to a feature this slice must not touch.
- Catch `ModelError` (both `RetryableModelError` and `TerminalModelError`)
  around the embed+save step specifically, swallow it, and continue
  returning the normal node output unchanged. No retry loop - a missed
  embedding is a degraded-search outcome, not a lost brief.
- No logging call is added for the swallowed failure (see §2 - no logging
  framework exists in this codebase; introducing one for a single call site
  is out of scope for this slice, ponytail: ship without it, add structured
  logging repo-wide as its own slice if/when it's needed for more than one
  call site).

### 3.2 Retrieval: `GET /archive/search`

A new read route embeds a free-text query and returns the nearest briefs by
cosine similarity, ordered nearest-first.

- Query params: `q: str` (required, the search text), `cadence: str | None`
  (optional filter, same `Cadence(...)` parsing/400 pattern as
  `GET /briefs`), `limit: int = 10` (bounded, e.g. 1-50, reject/clamp
  outside that range rather than allowing an unbounded scan).
- Embeds `q` via the same `gateway.embed()` used at generation time.
- Queries `embedding` joined to `brief` (join on `brief_id`, not a
  denormalized `cadence` field inside `embedding.metadata` - the `brief`
  row is the single source of truth for cadence/covered dates, avoiding a
  second copy that could drift; `metadata` on `Embedding` remains populated
  for debugging/future filters but is not the query's source of truth),
  ordered by `embedding.vector.cosine_distance(query_vector)` ascending
  (pgvector's SQLAlchemy comparator, already available via the existing
  `pgvector.sqlalchemy.Vector` column type - no new dependency), limited to
  `limit` rows, optionally filtered on `brief.cadence = <cadence>`.
- Returns a new lightweight response model per result: `brief_id`,
  `cadence`, `covered_start`, `covered_end`, `created_at`, a `content`
  snippet (bounded prefix of `Brief.content`, not the full text - mirrors
  `GET /briefs`'s list/detail split; caller fetches full content via the
  existing `GET /briefs/{brief_id}` for a match they want to read), and a
  `similarity_score` (e.g. `1 - cosine_distance`, higher is more similar).
- Provider without embedding support (OpenRouter): the route calls the same
  `gateway.embed()` as generation, so it fails the same way - catch
  `TerminalModelError` and return `503` with a sanitized message ("archive
  search unavailable: embeddings not supported by the configured model
  provider"), matching the existing "sanitized component status, no
  exception bodies" readiness convention (`docs/architecture.md`
  Invariants).
- Empty result set (no embeddings exist yet, e.g. fresh deployment, or all
  briefs predate this slice) is a normal `200` with an empty list, not an
  error.

## 4. Data Model

No schema changes. No new migration. Reuses the existing `embedding` table
and `Embedding` domain/ORM models as-is (`vector: Vector(1536)` already
matches `text-embedding-v4`'s output dimension - verify at implementation
time against the actual DashScope model card; if it does not match, the
`Vector(1536)` column width is an existing constraint from a prior slice,
not something this slice may change without its own migration, so a
mismatch blocks this slice and must be raised, not silently worked around).

## 5. Interfaces

### 5.1 `ModelGateway` (new abstract method)

```
async def embed(self, *, text: str, correlation_id: str) -> tuple[list[float], ModelUsage]
```

- Same error contract as `generate()`: raises `RetryableModelError` /
  `TerminalModelError`, never persists state, narrow boundary.
- `DashScopeAdapter.embed`: Consumes `text`, `correlation_id`. Calls
  `self._client.embeddings.create(model=self.get_model_for_task(
  ModelTask.EMBED), input=text, extra_headers={"x-correlation-id":
  correlation_id})`. Produces `(vector, ModelUsage)`. Same
  `APITimeoutError`/`RateLimitError` -> `RetryableModelError`,
  other `APIError` -> `TerminalModelError` mapping already used by
  `generate()` (reuse, do not duplicate the mapping logic if it can be
  shared).
- `OpenRouterAdapter.embed`: Consumes `text`, `correlation_id`. First call
  is `self.get_model_for_task(ModelTask.EMBED)`, which already raises
  `TerminalModelError` unconditionally (§2) - no new logic, just satisfies
  the abstract method by delegating to the existing rejection.

### 5.2 `persistence/repositories.py` (new function)

```
async def search_embeddings_by_similarity(
    session: AsyncSession,
    query_vector: list[float],
    *,
    cadence: Cadence | None,
    limit: int,
) -> list[tuple[Embedding, Brief]]
```

- Consumes an already-embedded query vector (embedding happens in the API
  layer via the gateway, not inside the repository - repositories stay
  free of gateway/model-provider imports, matching the existing "domain
  stays free of ... SDK imports" / narrow-gateway-boundary pattern).
- Produces ordered `(Embedding, Brief)` pairs, nearest-first.

### 5.3 `workflows/graphs.py` (modified: `synthesize` node only)

- Consumes: nothing new at the input boundary (`BriefGenerationInput`
  unchanged).
- Produces: same `{"brief": ..., "proposed_narrative": ..., "error": None}`
  dict shape, unchanged - the embedding step is a side effect appended
  after `save_brief`, not a new output field. `BriefGenerationOutput` /
  `BriefGenerationInput` (`workflows/state.py`) are unchanged.

### 5.4 `api/app.py` (new route)

- `GET /archive/search?q=<str>&cadence=<str|omit>&limit=<int=10>` ->
  `list[ArchiveSearchResultResponse]` (new response model, §3.2 fields).
  Open read route (no `X-API-Key`), same as `GET /briefs`.
- Consumes: `app.state.runtime.gateway` (already available to the app
  factory, same as other routes) for the query embed call, plus a DB
  session via `session_scope` (same pattern as every other route).

## 6. Workflow

### 6.1 Generation (every brief, every cadence)

1. `synthesize` node calls `_frontier_synthesis`, gets `BriefGenerationOutput`.
2. Inside the existing `session_scope`: `save_narrative_version` ->
   `save_prediction_expectation` (loop) -> `save_brief` (all unchanged,
   existing order).
3. New: `try: vector, _usage = await gateway.embed(text=output.brief.
   content, correlation_id=inp.correlation_id); await save_embedding(
   session, Embedding(brief_id=output.brief.id, model=gateway.
   get_model_for_task(ModelTask.EMBED), vector=vector, metadata={...}))
   except ModelError: pass`.
4. Return node output unchanged (step 3's outcome is not reflected in the
   returned dict - callers of the graph never needed to know whether
   archival succeeded, matching the "best-effort" framing in §3.1).

### 6.2 Retrieval

1. Client calls `GET /archive/search?q=...`.
2. Route handler calls `gateway.embed(text=q, correlation_id=<generated>)`.
   On `TerminalModelError`, return `503`.
3. Route handler calls `search_embeddings_by_similarity` with the resulting
   vector, optional `cadence`, and `limit`.
4. Maps each `(Embedding, Brief)` pair to `ArchiveSearchResultResponse` and
   returns the list (empty list, not error, if none found).

## 7. Edge Cases

- No embeddings exist yet (fresh DB, or every existing brief predates this
  slice - there is no backfill in this slice's scope, see §10): search
  returns `200` with `[]`.
- OpenRouter-configured deployment: both generation (silently skipped, §3.1)
  and search (`503`, §3.2) degrade gracefully; brief creation itself is
  unaffected.
- `limit` out of the allowed range: reject with `400` (mirrors the existing
  `Cadence(...)` `ValueError` -> `400` pattern already used by
  `GET /briefs`), do not silently clamp - matches this codebase's existing
  preference for explicit validation errors over silent correction.
- `q` empty/whitespace-only: `400` - an empty embed call is not a
  meaningful search and should not silently return arbitrary "nearest"
  results.
- Embedding generation succeeds but `save_embedding` hits a DB error
  (e.g. transient): since it runs inside the same `session_scope` as
  `save_brief`, an uncaught DB error here would roll back the **entire**
  transaction, undoing the already-synthesized brief - this is
  unacceptable (a network-flaky embedding write must not be able to lose a
  brief). The `try/except ModelError` in §3.1/§6.1 catches only
  `ModelError` from the gateway; the implementer must additionally ensure
  any DB-layer error from `save_embedding` itself is equally non-fatal to
  the brief (broaden the catch or isolate the embed+save in a way that
  cannot roll back the brief's own insert - an explicit design point for
  the lightweight plan to resolve, not left ambiguous at implementation
  time).
- Two briefs with identical/near-identical content (e.g. a quiet news day):
  no dedup logic - `search` legitimately returns near-duplicate results;
  this is correct behavior for a similarity search, not a bug.

## 8. Success Criteria

- Every new `Brief` created by any cadence (daily/weekly/monthly) gets an
  `Embedding` row on the happy path, verified by an integration test
  reading `embedding` after a graph run.
- `GET /archive/search?q=...` returns real nearest-neighbor results ordered
  by similarity against a seeded corpus of briefs with distinct content, in
  a Postgres+pgvector-backed integration test (this cannot be verified
  without a real pgvector index - no fake/mocked vector math substitute is
  acceptable for the ordering assertion specifically).
- A brief-creation run still succeeds end-to-end when the gateway is a fake
  that raises on `embed()` (proves the best-effort/non-fatal contract).
- Zero changes to `_frontier_synthesis`'s existing LLM-synthesis logic,
  `BriefGenerationInput`/`Output` state shapes, or any existing response
  model - purely additive.

## 9. Constraints

- No new third-party dependency (`pgvector.sqlalchemy.Vector` and the
  `openai` SDK's `embeddings.create` are both already present).
- No new migration / schema change.
- Must not modify `_frontier_synthesis`'s synthesis logic itself, only
  append the embed+save step after `save_brief` inside `synthesize`.
- Must not make embedding generation a precondition for a `Brief` existing
  (§3.1, §7 - a graph run must not fail solely because embedding failed).
- Repositories stay free of `ModelGateway`/SDK imports (§5.2) - the search
  route, not the repository function, owns the embed-the-query-text call.

## 10. Out of Scope / Explicit Non-Goals

- Backfilling embeddings for briefs created before this slice ships (a
  separate, explicit follow-up if wanted - this slice only wires
  generation going forward).
- Embedding raw articles (`docs/database.md` invariant: "embeddings stored
  only for briefs").
- Any UI for archive search (this repo's separate UI slice, if accepted,
  may add a search box against this API later, but is not this spec's
  concern).
- Reranking, hybrid keyword+vector search, or any relevance tuning beyond
  raw cosine-distance ordering.
- Rate limiting / cost controls on repeated `GET /archive/search` calls
  (each call makes one live embedding-model request) - no different from
  every other route's existing lack of rate limiting, not a new gap
  introduced by this slice.
