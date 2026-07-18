# Multi-Topic Source Sharing — Composite Uniqueness (Slice: follow-on to PR #9)

**Status:** accepted
**Date:** 2026-07-17
**Depends on:** Topic-First Analyst Slice 1 (PR #9)

## 1. Problem

Slice 1 scoped sources, articles, and briefs to a topic, but left three
uniqueness constraints **global**:

- `source.stable_id` UNIQUE
- `article.url_fingerprint` UNIQUE
- `source_feed.feed_url_fingerprint` UNIQUE

The user confirmed a real requirement: **the same source (and the same URL)
must be usable across multiple topics.** Today the global constraints break
this two ways:

1. Re-registering a shared source under a second topic silently **reassigns**
   the existing row (upsert matches on global `stable_id`), so the source
   appears under only one topic.
2. The same URL ingested under a second topic is **dup-suppressed** against the
   first topic's article (`get_article_by_fingerprint` matches globally), so it
   never enters the second topic's pool.

## 2. Goal

Make the three uniqueness scopes composite so an identifier is unique *within a
topic*, not globally:

| Table | Old scope | New scope |
|-------|-----------|-----------|
| `source` | `stable_id` | `(topic_id, stable_id)` |
| `article` | `url_fingerprint` | `(topic_id, url_fingerprint)` |
| `source_feed` | `feed_url_fingerprint` | `(source_id, feed_url_fingerprint)` |

### Deviation from the TODO note

The Future-Backlog note proposed `(topic_id, feed_url_fingerprint)` for
`source_feed`. **We use `(source_id, feed_url_fingerprint)` instead.** A feed's
natural key is source + URL, and `source_feed.source_id` already carries the
topic (source → topic). Adding a `topic_id` column to `source_feed` would be a
redundant denormalization. Each topic gets its own `source` row, so per-source
feed uniqueness already isolates topics.

## 3. Correctness core — the getters become live 500s

Once two topics legitimately share an identifier, a **global** lookup returns
two rows and `scalar_one_or_none()` raises `MultipleResultsFound` → HTTP 500.
This is the whole point of the feature, so every global lookup on these
identifiers MUST be scoped:

- `get_source_by_stable_id(session, stable_id)` → add `topic_id` param, filter `ORMSource.topic_id == topic_id`.
- `get_article_by_fingerprint(session, fingerprint)` → add `topic_id` param, filter `ORMArticle.topic_id == topic_id`.
- `get_source_feed_by_fingerprint(session, fingerprint)` → add `source_id` param, filter `ORMSourceFeed.source_id == source_id`. (Test-only today, but same failure mode.)
- `upsert_source` match query → `stable_id == … AND topic_id == source.topic_id`.
- `upsert_source_feed` match query → `feed_url_fingerprint == … AND source_id == feed.source_id`.

Both call sites of `get_article_by_fingerprint` in `ingestion/service.py`
(the pre-insert dedup at ~451 and the IntegrityError winner re-fetch at ~553)
must pass `topic_id`.

## 4. Data model / migration

New Alembic revision, `down_revision = "00f3ae192a5a"`.

`upgrade()`:
- `op.drop_constraint("source_stable_id_key", "source", type_="unique")`
- `op.create_unique_constraint("uq_source_topic_stable_id", "source", ["topic_id", "stable_id"])`
- `op.drop_constraint("article_url_fingerprint_key", "article", type_="unique")`
- `op.create_unique_constraint("uq_article_topic_url_fingerprint", "article", ["topic_id", "url_fingerprint"])`
- `op.drop_constraint("source_feed_feed_url_fingerprint_key", "source_feed", type_="unique")`
- `op.create_unique_constraint("uq_source_feed_source_url_fingerprint", "source_feed", ["source_id", "feed_url_fingerprint"])`

Constraint names verified against the live dev Postgres (port 15433).

`downgrade()`: reverse (drop composite, re-add the global unique).
`# ponytail:` note — the global re-add will fail if cross-topic duplicates
already exist; inherent to widening a uniqueness scope, acceptable for a
downgrade path.

## 5. ORM

For each of the three columns: remove inline `unique=True` **and** add the
composite `sa.UniqueConstraint(...)` to the model's `__table_args__` (matching
the migration's constraint names). Both changes — leaving `unique=True` while
adding the composite makes the ORM disagree with the DB and corrupts the next
autogenerate.

## 6. Acceptance test (discriminating)

A Postgres-backed test that **reuses the identical identifier across two
topics** — this is what distinguishes the fix from the bug (a test with
distinct per-topic identifiers passes both before and after):

1. Register the same `stable_id` under topic A and topic B → two distinct
   `source` rows, no error.
2. Ingest the same `url_fingerprint` under topic A and topic B → both articles
   persist, each in its own topic's pool; the second insert does not raise.
3. `get_source_by_stable_id(topic_a)` and `(topic_b)` each return their own row.

## 7. Non-goals

- Topic-delete-blocked-by-`not_relevant`-attempts UX nit — deferred, still in
  the Future Backlog.
- No frontend change (the API contract for `stable_id`/`url_fingerprint` is
  unchanged; only server-side scoping and the schema move).

## 8. Success criteria

- Full backend gate green: `ruff format --check`, `ruff check`, `mypy src tests`, `pytest`.
- Migration applies and reverses against real Postgres.
- The discriminating acceptance test passes (and would fail against `main`).
