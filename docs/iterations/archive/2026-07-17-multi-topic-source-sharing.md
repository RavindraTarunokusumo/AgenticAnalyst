# 2026-07-17 — Multi-Topic Source Sharing / Composite Uniqueness (codex/multi-topic-sources)

**Merge:** PR #10 (https://github.com/RavindraTarunokusumo/AgenticAnalyst/pull/10)
**Merge commit:** f6b414b23de92e7fa724b1bd7cbc09aaed189156
**Feature branch:** codex/multi-topic-sources
**Merged:** 2026-07-18T00:35:44Z

Spec: `docs/superpowers/specs/2026-07-17-multi-topic-source-sharing-design.md` (`accd105`)
Plan: `docs/superpowers/plans/2026-07-17-multi-topic-source-sharing.md` (`accd105`)

The deferred follow-on to Topic-First Analyst Slice 1 (PR #9). Slice 1 scoped
sources/articles/briefs to a topic but left three uniqueness constraints
global. This slice widens them to composite so the **same source and the same
URL can be used across multiple topics** — a confirmed requirement.

## Completed Work

- [x] **M1** ORM composite uniqueness (`688adbf`) — dropped inline `unique=True`
      on `source.stable_id` / `article.url_fingerprint` /
      `source_feed.feed_url_fingerprint`; added composite `UniqueConstraint`s:
      `(topic_id, stable_id)`, `(topic_id, url_fingerprint)`,
      `(source_id, feed_url_fingerprint)`.
- [x] **M2** Alembic migration `b8e4c1a09f3d` (`e1c8359`, `down_revision =
      00f3ae192a5a`) — drop the three global uniques, create the composites;
      reversible (downgrade can fail if cross-topic duplicates already exist —
      inherent to narrowing a uniqueness scope). Applied up/down against real
      Postgres via the integration suite's `migrated` fixture.
- [x] **M3+M4+M5+M5b** Repository scoping + caller ripple + acceptance test
      (`b14c67b`) — `get_source_by_stable_id`/`upsert_source` scoped by
      `topic_id`; `get_article_by_fingerprint` by `topic_id`;
      `get_source_feed_by_fingerprint`/`upsert_source_feed` by `source_id`
      (an unscoped lookup now returns >1 row and 500s once two topics share an
      identifier). Callers updated in `api/app.py` and both
      `ingestion/service.py` dedup sites. Discriminating Postgres-backed
      acceptance test reuses the **identical** `stable_id` + `url_fingerprint`
      across two topics. **M5b** (extension, Rule 2): the full-gate ripple
      Grok's scoped run missed — `test_ingestion_service.py` fakes gained the
      `*, topic_id` kwarg; `test_readiness_checks.py`'s migration-head constant
      bumped to `b8e4c1a09f3d`.
- [x] **M6** Docs (`335790c`) — `docs/database.md` composite uniqueness scopes
      + migration note; `docs/changelog.md` 2026-07-17 entry.

## Deviation from the original backlog note

The backlog proposed `(topic_id, feed_url_fingerprint)` for `source_feed`. We
used `(source_id, feed_url_fingerprint)` instead — a feed's natural key is
source + URL, and `source_id` already carries the topic, so adding a `topic_id`
column to `source_feed` would be a redundant denormalization.

## Validation

- Implementer: grok-4.5 subagent (ephemeral session, cleaned up).
- Independent senior full gate: `ruff format --check` + `ruff check` +
  `mypy src tests` + full `pytest` (**347 passed, 2 skipped**). The full gate
  caught cross-cutting breakage the implementer's scoped run missed (M5b).
- CI: `quality` + `frontend` green.
- Grok bundled review (grok-4.5, cleaned up): approve, no high-confidence
  issues (no remaining global lookups; migration symmetric; single head;
  acceptance test discriminating).

## Still deferred (Future Backlog)

- **Topic delete blocked by `not_relevant` attempts** — `ON DELETE RESTRICT`
  UX nit, split out of this slice.
