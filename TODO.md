# TODO.md

This file contains active or future work only.

Completed sessions must be moved to `docs/iterations/archive/`.

## Backlog

## Session: RSS-to-Daily-Brief Vertical Slice (2026-07-13)

Spec: `docs/superpowers/specs/2026-07-13-rss-daily-brief-design.md`
Plan: `docs/superpowers/plans/2026-07-13-rss-daily-brief.md`

- [x] Task 1: Domain models (`SourceFeed`, `IngestionAttempt`, enums; `batch_key` deferred to Task 2) + config settings (`542215a`)
- [x] Task 2: Persistence schema + Alembic migration (source_feed, ingestion_attempt, batch constraints) (`315279d`)
- [ ] Task 3: Repositories (feed/attempt/article/batch/summary lookups)
- [ ] Task 4: `UrlCanonicalizer` + shared bounded-fetch/SSRF helper
- [ ] Task 5: `FeedClient` + `FeedParser`
- [ ] Task 6: HTML cleaner + `ArticleExtractor` (primary + Crawl4AI fallback)
- [ ] Task 7: `ArticleBatcher`
- [ ] Task 8: `BatchSummarizer`
- [ ] Task 9: `IngestionService`
- [ ] Task 10: `DailyBriefPipeline`
- [ ] Task 11: Runtime wiring + scheduler
- [ ] Task 12: API routes (sources, ingestion, pipelines/daily, briefs)
- [ ] Task 13: Integration/API test sweep + success-criteria verification
- [ ] Task 14: Documentation reconciliation

## Session: Harness Design (2026-07-10)

- [x] Write and validate the approved local-first technical harness specification.
- [x] Clarify batch-summary provenance and the temporal-holdout demo test.
- [x] Defer claim-event persistence and define cadence-specific frontier outputs.
- [x] Accelerate the temporal-holdout replay without relaxing visibility controls.
- [x] Produce the lightweight implementation contract for the approved technical harness.


## Session: <Session Name> (<YYYY-MM-DD>)

- [ ] <sub-item 1>
- [ ] <sub-item 2>
- [ ] <sub-item 3>

## Future Backlog

- [ ] <future item>
