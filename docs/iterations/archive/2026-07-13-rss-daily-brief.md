# 2026-07-13 — RSS-to-Daily-Brief Vertical Slice (codex/rss-daily-brief-plan)

**Merge:** PR #3 (https://github.com/RavindraTarunokusumo/AgenticAnalyst/pull/3)
**Merge commit:** 9848a9c36868a9bcbaa72741e12918dedbdfc116
**Feature branch:** codex/rss-daily-brief-plan
**Merged:** 2026-07-14T22:01:19Z

Spec: `docs/superpowers/specs/2026-07-13-rss-daily-brief-design.md`
Plan: `docs/superpowers/plans/2026-07-13-rss-daily-brief.md`

## Completed Work

- [x] Task 1: Domain models (`SourceFeed`, `IngestionAttempt`, enums; `batch_key` deferred to Task 2) + config settings (`542215a`)
- [x] Task 2: Persistence schema + Alembic migration (source_feed, ingestion_attempt, batch constraints) (`315279d`)
- [x] Task 3: Repositories (feed/attempt/article/batch/summary lookups) (`374164d`)
- [x] Task 4: `UrlCanonicalizer` + shared bounded-fetch/SSRF helper (`1ab237f`)
- [x] Task 5: `FeedClient` + `FeedParser` (`165540e`)
- [x] Task 6: HTML cleaner + `ArticleExtractor` (primary + Crawl4AI fallback) (`24f5c4c`)
  - [x] Extension: isolate crawl4ai's import-time `load_dotenv()` pollution from the test suite (env_ignore_empty, delenv fixes, root conftest.py) (`56a08d4`)
- [x] Task 7: `ArticleBatcher` (`3278c76`)
- [x] Task 8: `BatchSummarizer` (`1970485`)
- [x] Task 9: `IngestionService` (`1424473`)
  - [x] Extension: `ExtractedArticle` page-metadata publish time/author, discovered as a Task 6 gap while designing this task (`0cb94fc`)
- [x] Task 10: `DailyBriefPipeline` (`edd4845`)
  - [x] Fix: idempotent-rerun citation-exclusion + no-content short-circuit bugs, found via the end-to-end integration test (same commit)
- [x] Task 11: Runtime wiring + scheduler (`a32b407`)
- [x] Task 12: API routes (sources, ingestion, pipelines/daily, briefs) (`b26c667`, tests `197e0d0`)
  - [x] Fix: /briefs date-cutoff exclusion bug found + fixed during review (same commit as production code)
  - [x] Fix: TestClient lifespan never entered + accidental-pass auth test, found + fixed while verifying test coverage (test commit)
- [x] Task 13: Integration/API test sweep + success-criteria verification (see commit body for the full spec §11 checklist)
- [x] Task 14: Documentation reconciliation (`613e256`; written directly, Grok delegation killed 3x with no output)
- [x] Task 15: Submit PR (#3), security review + code review (self-conducted, native Agent tooling; Grok fallback clause invoked after Task 14's 3x failure) - 2 confirmed SSRF findings fixed (`36bd5db`), 1 rejected; code review raised 2 Important findings, 1 accepted as pre-existing out-of-scope, 1 refuted as a false positive with code-level evidence - see PR #3 comments
  - [x] Fix: CI-only failures (Docker unavailable locally, so this never surfaced pre-push) - 5 repository/integration test modules shared one physical CI Postgres database with no per-test cleanup, causing unique-constraint collisions and unscoped-query assertions to see leftover rows from earlier tests; added `truncate_domain_tables()` and wired it into each affected module's `migrated` fixture (`9fd0b72`) - CI green on re-run

## Summary

Added Agentic Analyst's first complete product loop: RSS/Atom feed polling and manual URL submission both route through one SSRF-safe ingestion path (canonicalize-then-fetch, re-validated on every redirect hop, IP-pinned connection to close a DNS-rebinding TOCTOU window, terminal rejection on SSRF failure rather than falling back to a weaker-validated extractor), a deterministic stdlib HTML extractor with a Crawl4AI fallback, title-token-Jaccard article batching, LLM batch summarization with anti-prompt-injection framing and citation-provenance validation, and a `DailyBriefPipeline` that is now the sole entry point for both the scheduler's daily job and the new `POST /pipelines/daily` route. New read/write API surface for sources, ingestion, and briefs; write/trigger routes now reject an absent API key unless explicitly opted out via `ALLOW_UNAUTHENTICATED_WRITE`.

Two SSRF gaps were found and fixed via a self-conducted post-implementation security review (native Agent tooling, since Grok's own delegation had already failed 3x on this session's simpler Task 14): a rejected `UrlValidationError` from the primary extractor was previously treated like any other extraction failure and could trigger the unvalidated Crawl4AI fallback; and `bounded_fetch` validated a hostname's resolved IP but then handed the same hostname to httpx for the actual connection, reopening a DNS-rebinding window. A separate CI-only test-isolation bug (5 repository/integration test modules sharing one CI Postgres database with no per-test cleanup) was found and fixed after the first PR push, since it never surfaced locally where Docker is unavailable.

## Verification

- `uv run ruff format --check .` / `uv run ruff check .` — passed (final state).
- `uv run mypy src tests` — clean (strict mode).
- `uv run pytest` (local, Docker unavailable) — 205 passed, 21 skipped (Docker-only integration tests + 2 opt-in evaluation/live-smoke tests).
- GitHub Actions `quality` job (CI Postgres service) — green on final push (run `29368501219`), after fixing the 5 CI-only test-isolation failures found on the first push.
- Self-conducted security review (native Agent tooling, adversarial multi-agent verification against a strict SSRF/auth exclusion list): 2 of 3 candidate findings confirmed at high confidence (8-9/10) and fixed; 1 rejected (3/10) as an intentional, spec-accepted, test-codified design decision.
- Self-conducted code review (native Agent tooling, `requesting-code-review` pattern): 0 Critical, 2 Important findings triaged — 1 accepted as pre-existing out-of-scope (API key verification), 1 refuted as a false positive with code-level evidence (a claimed empty-`batch_summaries`-reaches-`run_daily` path that the actual control flow prevents).
