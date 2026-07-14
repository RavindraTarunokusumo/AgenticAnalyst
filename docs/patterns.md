# Key Patterns

## Identifier Pattern

- Use stable UUIDs and URL fingerprints for internal state and deduplication.
- `stable_id` on sources and `idempotency_key` on workflow runs are the keys for lookup and uniqueness.
- Display names and human titles are never used as keys.

## State Pattern

- Domain Pydantic models are the source of truth for contracts.
- ORM models are an internal persistence detail; repositories translate.
- Narrative State is versioned; each version carries parent pointer and change log.
- LangGraph checkpoints capture graph state independently of our analytical records.

## Snapshot Pattern

Settings are loaded once at process start (or per test fixture). Long-running operations (scheduled workflows, evaluation replays) capture the effective Settings at invocation time via the run record.

## Persistence Pattern

- Every write path accepts an `AsyncSession`.
- Use `session_scope(factory)` for automatic commit/rollback/close.
- The caller (workflow or API handler) decides transaction boundaries.
- Idempotency checks (`get_workflow_run_by_idempotency`) happen inside the same session as the potential insert.
- Citation lineage is validated by repositories and higher-level workflow nodes before any Narrative State mutation.

## External Side-Effect Pattern

- Provider calls, web fetches, and search are behind narrow adapters (ModelGateway, ingestion strategies).
- No direct SDK or HTTP calls from domain, repositories, or graph nodes except through the approved gateway.
- LangSmith tracing failures are non-fatal (observability degradation only).
- URLs are canonicalized and SSRF-checked (`canonicalize_url`) before every request, including every redirect hop - never delegate redirect-following to a client library's own follower for an untrusted URL.
- The validated host is resolved once (`resolve_validated_address`) and the connection is pinned to that literal IP, with the original hostname preserved via the `Host` header and TLS SNI extension - a second, independent DNS lookup at connect time (e.g. httpx re-resolving the hostname) reopens a DNS-rebinding window between validation and connection.
- A rejected `UrlValidationError`/`PrivateNetworkError` from a primary extractor is terminal, never a trigger for a fallback extractor - a weaker-validated fallback path (e.g. Crawl4AI, which does no host/redirect validation of its own) must not be able to succeed where the primary's SSRF check already blocked the request.

## Code Style

- Comments sparse and behavior-oriented.
- Clear names over clever abstractions.
- No compatibility shims.
- Domain stays free of SQLAlchemy, FastAPI, LangGraph, and SDK imports.

## Anti-Patterns

- Writing directly to the DB outside a repository + session.
- Using display names or titles as primary keys.
- Mutating Narrative State from a malformed model response.
- Hiding Docker/Testcontainers requirements behind silent skips that turn into hard failures in CI.
