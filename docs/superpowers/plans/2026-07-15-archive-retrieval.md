# Archive Retrieval / Semantic Search - Lightweight Implementation Plan

Spec: `docs/superpowers/specs/2026-07-15-archive-retrieval-design.md` (accepted).

## File Structure / Task Decomposition

1. **`ModelGateway.embed()` abstract method** - `src/analyst_engine/models/gateway.py`
2. **`DashScopeAdapter.embed()`** - `src/analyst_engine/models/dashscope.py`
3. **`OpenRouterAdapter.embed()`** - `src/analyst_engine/models/openrouter.py`
4. **Update `tests/fixtures.py::FakeModelGateway`** - must implement `embed()` or every
   existing test that instantiates it breaks (it's an ABC subclass; a new abstract
   method makes the class uninstantiable until implemented everywhere).
5. **`search_embeddings_by_similarity()` repository function** - `src/analyst_engine/persistence/repositories.py`
6. **Wire best-effort embedding into `synthesize` node** - `src/analyst_engine/workflows/graphs.py`
7. **`GET /archive/search` route + response model** - `src/analyst_engine/api/app.py`
8. **Tests**: unit (adapter embed happy/error path, best-effort swallow, response model),
   integration (real pgvector ordering assertion - spec §8 requires this, no mock substitute)
9. **Docs**: `docs/architecture.md` (new route), `docs/database.md` (no change - table
   already documented), `docs/changelog.md`

## Build Order

1 -> 2, 3 (parallel, disjoint files) -> 4 (must land before any test touching
`FakeModelGateway` runs) -> 5 -> 6 -> 7 -> 8 -> 9

Steps 2 and 3 are independent (different adapter files) and can be done in either
order or in parallel; both depend on step 1's method signature existing first.

## Per-Task Interfaces

### Task 1: `ModelGateway.embed()`

```
Consumes: text: str, correlation_id: str
Produces: tuple[list[float], ModelUsage]
Raises: RetryableModelError | TerminalModelError (never persists state)
```

Add as a second `@abstractmethod` alongside `generate()`. Any class extending
`ModelGateway` that doesn't implement it becomes uninstantiable - this is the
signal that catches Task 4 if skipped (pytest collection/instantiation will fail
loudly, not silently).

### Task 2: `DashScopeAdapter.embed()`

```
Consumes: text: str, correlation_id: str
Produces: tuple[list[float], ModelUsage]
```

Calls `self._client.embeddings.create(model=self.get_model_for_task(ModelTask.EMBED),
input=text, extra_headers={"x-correlation-id": correlation_id})`. Reuse the exact
`APITimeoutError`/`RateLimitError` -> `RetryableModelError`, `APIError` -> `TerminalModelError`
mapping already in `generate()` (extract a shared private helper if that avoids
duplicating the except block; do not fork the mapping logic). Vector comes from
`response.data[0].embedding`; `ModelUsage` from `response.usage` (embeddings responses
have `prompt_tokens`/`total_tokens`, no `completion_tokens` - default that field to 0).

### Task 3: `OpenRouterAdapter.embed()`

```
Consumes: text: str, correlation_id: str
Produces: tuple[list[float], ModelUsage]
```

One line: `self.get_model_for_task(ModelTask.EMBED)` - already raises `TerminalModelError`
unconditionally (existing code, untouched). No API call is ever reached.

### Task 4: `FakeModelGateway.embed()`

```
Consumes: text: str, correlation_id: str
Produces: tuple[list[float], ModelUsage]
```

Deterministic fake vector (fixed-length list of floats, dimension must satisfy the
domain `Embedding.vector` validator's `>= 2` minimum - use a realistic size matching
whatever the real `Vector(1536)` column expects for any test that persists it, or a
short deterministic vector for tests that only check the call happened). Also add a
second fake mode: a fake that raises (`RetryableModelError` or `TerminalModelError`)
from `embed()` specifically, needed by Task 6's "best-effort" test (spec §8's third
success criterion) - either a constructor flag on `FakeModelGateway` or a small
subclass in the test module, implementer's choice.

### Task 5: `search_embeddings_by_similarity()`

```
Consumes: session: AsyncSession, query_vector: list[float], *, cadence: Cadence | None, limit: int
Produces: list[tuple[Embedding, Brief]]  # nearest-first
```

Join `embedding` to `brief` on `brief_id`; order by
`ORMEmbedding.vector.cosine_distance(query_vector)` ascending (pgvector SQLAlchemy
comparator); apply `.where(ORMBrief.cadence == cadence.value)` only when `cadence`
is not `None`; `.limit(limit)`. Map ORM rows back through the existing
`_brief_to_domain`/embedding-to-domain conversion pattern already used elsewhere in
this file (do not hand-roll a new mapping style).

### Task 6: `synthesize` node embedding side effect

```
Consumes: nothing new at BriefGenerationInput/Output boundary
Produces: same node output dict, unchanged
```

Insert immediately after the existing `await save_brief(session, output.brief)`
line (`graphs.py:151`), inside the same `session_scope` block:

```
try:
    vector, _usage = await gateway.embed(text=output.brief.content, correlation_id=inp.correlation_id)
    await save_embedding(session, Embedding(
        brief_id=output.brief.id,
        model=gateway.get_model_for_task(ModelTask.EMBED),
        vector=vector,
        metadata={"cadence": cadence.value, "covered_start": ..., "covered_end": ...},
    ))
except ModelError:
    pass
```

**Cross-task risk this plan exists to catch**: `save_embedding`'s own DB-layer
exceptions are *not* `ModelError` subclasses, so the bare `except ModelError` does
**not** protect the brief's own `save_brief` insert from a transient embedding-write
failure inside the same transaction (spec §7 flags this explicitly as unresolved).
Resolution for this plan: wrap the `save_embedding` call in its own inner
`try/except Exception: pass` (or catch `SQLAlchemyError` specifically) so *any*
failure in the embed-and-save side effect - model error or DB error - cannot roll
back `save_brief`'s already-flushed row in the same `session_scope`. Do not let a
narrower except clause slip through review here; this is the one edge case the spec
explicitly deferred to implementation.

### Task 7: `GET /archive/search`

```
Consumes: q: str (required, non-blank), cadence: str | None, limit: int = 10 (1-50)
Produces: list[ArchiveSearchResultResponse]
```

New Pydantic response model near `BriefListItemResponse` (§3.2 spec fields:
`brief_id`, `cadence`, `covered_start`, `covered_end`, `created_at`, `content`
snippet, `similarity_score`). Handler: validate `q`/`limit` (400 on violation,
mirroring the existing `Cadence(...)` -> 400 pattern), call
`app.state.runtime.gateway.embed(text=q, correlation_id=<uuid4>)` inside a
try/except catching `TerminalModelError` -> 503 (sanitized message per spec §3.2),
then `session_scope` + `search_embeddings_by_similarity` + map to response list.

## Risks

- **FakeModelGateway breakage** (Task 4): every existing test importing it will fail
  to instantiate the class until `embed()` exists there too. Land Task 4 in the same
  commit as Task 1, not deferred - do not let CI discover this.
- **pgvector dimension mismatch**: spec §4 flags `Vector(1536)` as a pre-existing
  constraint; verify DashScope's actual `text-embedding-v4` output dimension before
  writing the integration test - a mismatch is a blocker to raise, not silently pad/
  truncate.
- **Transaction-safety edge case** (Task 6): the single highest-risk line in this
  slice per spec §7 - get the inner try/except right, and write the "fake gateway
  raises on embed(), brief still persists" test (spec §8) before considering Task 6
  done, not as an afterthought.
- **Docker/CI parity**: the integration test in Task 8 needs real pgvector - same
  Docker-only-locally caveat as every prior slice (`docs/insights.md`); it will not
  run in this environment without Docker, only in CI.
