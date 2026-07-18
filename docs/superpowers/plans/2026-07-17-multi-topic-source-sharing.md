# Plan — Multi-Topic Source Sharing (composite uniqueness)

Spec: `docs/superpowers/specs/2026-07-17-multi-topic-source-sharing-design.md`

Single cohesive change (schema + repository + one caller signature ripple +
test). Files touch a shared contract, so **one sequential Grok task**, not
parallel.

## File structure / build order

1. **ORM** — `src/analyst_engine/persistence/models.py`
   - `Source`: drop `unique=True` on `stable_id`; add
     `sa.UniqueConstraint("topic_id", "stable_id", name="uq_source_topic_stable_id")` to `__table_args__`.
   - `Article`: drop `unique=True` on `url_fingerprint`; add
     `sa.UniqueConstraint("topic_id", "url_fingerprint", name="uq_article_topic_url_fingerprint")`.
   - `SourceFeed`: drop `unique=True` on `feed_url_fingerprint`; add
     `sa.UniqueConstraint("source_id", "feed_url_fingerprint", name="uq_source_feed_source_url_fingerprint")`.

2. **Migration** — `alembic/versions/<new>_composite_topic_uniqueness.py`
   - `down_revision = "00f3ae192a5a"`.
   - drop/create per spec §4 (constraint names are verified-real).

3. **Repository** — `src/analyst_engine/persistence/repositories.py`
   - **Consumes/Produces (signature changes):**
     - `get_source_by_stable_id(session, stable_id, *, topic_id: uuid.UUID) -> Source | None` — add `WHERE topic_id == topic_id`.
     - `get_article_by_fingerprint(session, fingerprint, *, topic_id: uuid.UUID) -> Article | None` — add `WHERE topic_id == topic_id`.
     - `get_source_feed_by_fingerprint(session, fingerprint, *, source_id: uuid.UUID) -> SourceFeed | None` — add `WHERE source_id == source_id`.
     - `upsert_source`: match query gains `AND ORMSource.topic_id == source.topic_id`.
     - `upsert_source_feed`: match query gains `AND ORMSourceFeed.source_id == feed.source_id`.

4. **Callers** (ripple from the signature changes):
   - `src/analyst_engine/api/app.py:487` — `get_source_by_stable_id(session, req.stable_id, topic_id=req.topic_id)`.
   - `src/analyst_engine/ingestion/service.py:451` and `:553` — pass `topic_id=topic_id` (both inside functions that already have `topic_id`).
   - `tests/integration/test_topic_scoped_pipeline.py:421,422,435` — `get_source_feed_by_fingerprint(session, fp, source_id=<source>.id)`.

5. **Test** — extend `tests/integration/test_topic_scoped_pipeline.py` (or a new
   `test_multi_topic_source_sharing.py`) with the discriminating acceptance test
   (spec §6): same `stable_id` under two topics → 2 rows; same `url_fingerprint`
   under two topics → 2 articles; no raise. Postgres-backed.

## Risks

- **`MultipleResultsFound` 500** if any getter left global (spec §3) — the whole
  point; the acceptance test catches it only if it reuses the *identical*
  identifier across topics.
- **Constraint-name drift** — names verified against live DB; do not guess.
- **ORM/DB disagreement** — must both drop `unique=True` and add the composite.

## Verification (senior, full gate)

`ruff format --check` + `ruff check` + `mypy src tests` + `pytest`; apply the
migration up/down against real Postgres; confirm the acceptance test fails on
`main` (bug present) and passes here.
