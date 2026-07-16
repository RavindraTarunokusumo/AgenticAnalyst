"""FastAPI application factory with health, readiness, and manual triggers."""

from __future__ import annotations

import math
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

from fastapi import Depends, FastAPI, File, Form, HTTPException, Security, UploadFile
from fastapi.responses import JSONResponse
from fastapi.security.api_key import APIKeyHeader
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncEngine

from analyst_engine.api.readiness import ReadinessStatus, check_readiness
from analyst_engine.config import Settings
from analyst_engine.domain.models import Cadence, IngestionStatus, Source, SourceFeed
from analyst_engine.ingestion.canonicalize import UrlValidationError, canonicalize_url
from analyst_engine.models.gateway import RetryableModelError, TerminalModelError
from analyst_engine.persistence.engine import session_scope
from analyst_engine.persistence.repositories import (
    get_articles_by_ids,
    get_batch_summaries_by_ids,
    get_brief_by_id,
    get_source_by_stable_id,
    get_sources_by_ids,
    list_ingestion_attempts,
    list_prior_briefs,
    list_source_feeds_for_source,
    list_sources,
    search_embeddings_by_similarity,
    upsert_source,
    upsert_source_feed,
)
from analyst_engine.pipeline.periodic_brief import PeriodicPipelineResult
from analyst_engine.runtime import (
    RuntimeDependencies,
    build_daily_brief_pipeline,
    build_ingestion_service,
    build_periodic_brief_pipeline,
    create_runtime,
)
from analyst_engine.workflows.runner import WorkflowRunner

# Very simple harness auth (token from env or header for local dev)
API_KEY_HEADER = APIKeyHeader(name="X-API-Key", auto_error=False)

# Built frontend assets (frontend/dist, copied here by the Dockerfile's
# frontend-build stage) or the committed placeholder for a fresh checkout
# with no frontend build yet run - see docs/commands.md.
STATIC_DIR = Path(__file__).resolve().parent / "static"


class TriggerRequest(BaseModel):
    cadence: str
    covered_start: date
    covered_end: date


class TriggerResponse(BaseModel):
    run_id: str
    status: str
    idempotency_key: str


class RegisterFeedRequest(BaseModel):
    feed_url: str
    enabled: bool = True
    poll_interval_minutes: int | None = None


class RegisterSourceRequest(BaseModel):
    stable_id: str
    name: str
    normalized_domain: str
    feeds: list[RegisterFeedRequest] = []


class FeedHealthResponse(BaseModel):
    id: UUID
    feed_url: str
    enabled: bool
    poll_interval_minutes: int
    last_polled_at: datetime | None
    last_success_at: datetime | None
    last_error_summary: str | None


class SourceResponse(BaseModel):
    id: UUID
    stable_id: str
    name: str
    normalized_domain: str
    feeds: list[FeedHealthResponse]


class IngestUrlsRequest(BaseModel):
    source_id: UUID
    urls: list[str]


class IngestionResultResponse(BaseModel):
    candidate_url: str
    status: str
    article_id: UUID | None
    error_code: str | None
    error_summary: str | None


class IngestionAttemptResponse(BaseModel):
    id: UUID
    source_id: UUID
    source_feed_id: UUID | None
    requested_url: str
    canonical_url: str | None
    status: str
    http_status: int | None
    extractor: str | None
    article_id: UUID | None
    error_code: str | None
    error_summary: str | None
    started_at: datetime
    completed_at: datetime | None


class TriggerDailyPipelineRequest(BaseModel):
    target_date: date


class DailyPipelineResultResponse(BaseModel):
    target_date: date
    feeds_polled: int
    articles_succeeded: int
    articles_duplicate: int
    articles_failed: int
    batches_created: int
    batches_reused: int
    summaries_created: int
    summaries_reused: int
    summaries_selected: int
    is_no_content: bool
    workflow_run_id: UUID | None
    workflow_status: str | None
    brief_id: UUID | None


class TriggerPeriodicPipelineRequest(BaseModel):
    target_date: date


class PeriodicPipelineResultResponse(BaseModel):
    cadence: str
    covered_start: date
    covered_end: date
    summaries_selected: int
    is_no_content: bool
    workflow_run_id: UUID | None
    workflow_status: str | None
    brief_id: UUID | None


class ResolvedCitationResponse(BaseModel):
    article_id: UUID
    excerpt: str | None
    article_title: str
    article_url: str
    source_name: str


class ResolvedBatchSummaryResponse(BaseModel):
    id: UUID
    model: str
    prompt_version: str
    summary: str
    source_notes: str | None
    entities: list[str]
    topics: list[str]
    citations: list[ResolvedCitationResponse]


class BriefListItemResponse(BaseModel):
    id: UUID
    cadence: str
    covered_start: date
    covered_end: date
    created_at: datetime


class BriefDetailResponse(BaseModel):
    id: UUID
    cadence: str
    covered_start: date
    covered_end: date
    content: str
    narrative_state_version_id: UUID | None
    created_by_run_id: UUID
    created_at: datetime
    cited_summaries: list[ResolvedBatchSummaryResponse]


class ArchiveSearchResultResponse(BaseModel):
    brief_id: UUID
    cadence: str
    covered_start: date
    covered_end: date
    created_at: datetime
    content: str
    similarity_score: float


def get_settings() -> Settings:
    # In real app this would be injected from lifespan or dependency
    return Settings()  # relies on .env


_ARCHIVE_SNIPPET_LENGTH = 280


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    dot = float(sum(x * y for x, y in zip(a, b, strict=True)))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (norm_a * norm_b)


def _feed_to_health_response(feed: SourceFeed) -> FeedHealthResponse:
    return FeedHealthResponse(
        id=feed.id,
        feed_url=feed.feed_url,
        enabled=feed.enabled,
        poll_interval_minutes=feed.poll_interval_minutes,
        last_polled_at=feed.last_polled_at,
        last_success_at=feed.last_success_at,
        last_error_summary=feed.last_error_summary,
    )


def _source_to_response(source: Source, feeds: list[SourceFeed]) -> SourceResponse:
    return SourceResponse(
        id=source.id,
        stable_id=source.stable_id,
        name=source.name,
        normalized_domain=source.normalized_domain,
        feeds=[_feed_to_health_response(feed) for feed in feeds],
    )


def _periodic_result_to_response(result: PeriodicPipelineResult) -> PeriodicPipelineResultResponse:
    return PeriodicPipelineResultResponse(
        cadence=result.cadence.value,
        covered_start=result.covered_start,
        covered_end=result.covered_end,
        summaries_selected=result.summaries_selected,
        is_no_content=result.is_no_content,
        workflow_run_id=result.workflow_run_id,
        workflow_status=result.workflow_status.value if result.workflow_status else None,
        brief_id=result.brief_id,
    )


def create_app(
    *,
    settings_factory: Callable[[], Settings] = get_settings,
    runtime_factory: Callable[[Settings], Awaitable[RuntimeDependencies]] = create_runtime,
    readiness_checker: Callable[[AsyncEngine], Awaitable[ReadinessStatus]] = check_readiness,
) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        runtime = await runtime_factory(settings_factory())
        try:
            runner = WorkflowRunner(
                runtime.settings,
                runtime.gateway,
                runtime.session_factory,
                runtime.checkpointer_factory,
            )
            ingestion_service = build_ingestion_service(runtime)
            pipeline = build_daily_brief_pipeline(
                runtime,
                ingestion_service=ingestion_service,
                runner=runner,
            )
            weekly_pipeline = build_periodic_brief_pipeline(
                runtime, runner=runner, cadence=Cadence.WEEKLY
            )
            monthly_pipeline = build_periodic_brief_pipeline(
                runtime, runner=runner, cadence=Cadence.MONTHLY
            )
            app.state.runtime = runtime
            app.state.engine = runtime.engine
            app.state.runner = runner
            app.state.ingestion_service = ingestion_service
            app.state.pipeline = pipeline
            app.state.weekly_pipeline = weekly_pipeline
            app.state.monthly_pipeline = monthly_pipeline
            yield
        finally:
            await runtime.close()

    app = FastAPI(title="AnalystEngine Harness", lifespan=lifespan)

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/readyz")
    async def readyz() -> JSONResponse:
        runtime: RuntimeDependencies = app.state.runtime
        readiness = await readiness_checker(runtime.engine)
        return JSONResponse(
            status_code=200 if readiness.status == "ready" else 503,
            content=readiness.model_dump(exclude_none=True),
        )

    async def _require_key(key: str | None = Security(API_KEY_HEADER)) -> str:
        if key is None or not key.strip():
            if app.state.runtime.settings.allow_unauthenticated_write:
                return "local"
            raise HTTPException(status_code=401, detail="API key required")
        return key

    @app.post("/workflows/trigger", response_model=TriggerResponse)
    async def trigger(
        req: TriggerRequest,
        _key: str = Depends(_require_key),
    ) -> TriggerResponse:
        run_id: UUID | None
        status: str | None
        covered_start: date
        covered_end: date
        if req.cadence == "daily":
            daily_result = await app.state.pipeline.run(req.covered_start)
            run_id = daily_result.workflow_run_id
            status = daily_result.workflow_status.value if daily_result.workflow_status else None
            covered_start = covered_end = daily_result.target_date
        elif req.cadence == "weekly":
            weekly_result = await app.state.weekly_pipeline.run(req.covered_start)
            run_id = weekly_result.workflow_run_id
            status = weekly_result.workflow_status.value if weekly_result.workflow_status else None
            covered_start = weekly_result.covered_start
            covered_end = weekly_result.covered_end
        elif req.cadence == "monthly":
            monthly_result = await app.state.monthly_pipeline.run(req.covered_start)
            run_id = monthly_result.workflow_run_id
            status = (
                monthly_result.workflow_status.value if monthly_result.workflow_status else None
            )
            covered_start = monthly_result.covered_start
            covered_end = monthly_result.covered_end
        else:
            raise HTTPException(status_code=400, detail="unknown cadence")
        if run_id is None or status is None:
            raise HTTPException(status_code=409, detail="no content for the requested window")
        # Mirrors WorkflowRunner._ensure_run's own key derivation - built from
        # each pipeline's actual, normalized covered_start/covered_end (not
        # the raw request), since weekly/monthly may not be Monday/month-
        # aligned as submitted.
        idempotency_key = f"{req.cadence}:{covered_start.isoformat()}:{covered_end.isoformat()}"
        return TriggerResponse(
            run_id=str(run_id),
            status=status,
            idempotency_key=idempotency_key,
        )

    @app.post("/sources", response_model=SourceResponse)
    async def register_source(
        req: RegisterSourceRequest,
        _key: str = Depends(_require_key),
    ) -> SourceResponse:
        runtime: RuntimeDependencies = app.state.runtime
        settings = runtime.settings

        canonical_feeds: list[tuple[RegisterFeedRequest, str, str]] = []
        for feed_req in req.feeds:
            try:
                canonical_url, fingerprint = canonicalize_url(
                    feed_req.feed_url, block_private_networks=True
                )
            except UrlValidationError as exc:
                raise HTTPException(status_code=422, detail=str(exc)) from exc
            canonical_feeds.append((feed_req, canonical_url, fingerprint))

        async with session_scope(runtime.session_factory) as session:
            await upsert_source(
                session,
                Source(
                    stable_id=req.stable_id,
                    name=req.name,
                    normalized_domain=req.normalized_domain,
                ),
            )
            persisted = await get_source_by_stable_id(session, req.stable_id)
            if persisted is None:
                raise HTTPException(status_code=500, detail="source persistence failed")

            for feed_req, canonical_url, fingerprint in canonical_feeds:
                await upsert_source_feed(
                    session,
                    SourceFeed(
                        source_id=persisted.id,
                        feed_url=canonical_url,
                        feed_url_fingerprint=fingerprint,
                        enabled=feed_req.enabled,
                        poll_interval_minutes=(
                            feed_req.poll_interval_minutes or settings.default_poll_interval_minutes
                        ),
                    ),
                )

            feeds = await list_source_feeds_for_source(session, persisted.id)
            return _source_to_response(persisted, feeds)

    @app.get("/sources", response_model=list[SourceResponse])
    async def get_sources() -> list[SourceResponse]:
        runtime: RuntimeDependencies = app.state.runtime
        async with session_scope(runtime.session_factory) as session:
            sources = await list_sources(session)
            result: list[SourceResponse] = []
            for source in sources:
                feeds = await list_source_feeds_for_source(session, source.id)
                result.append(_source_to_response(source, feeds))
            return result

    @app.post("/ingestion/urls", response_model=list[IngestionResultResponse])
    async def ingest_urls(
        req: IngestUrlsRequest,
        _key: str = Depends(_require_key),
    ) -> list[IngestionResultResponse]:
        results = await app.state.ingestion_service.ingest_urls(req.source_id, req.urls)
        return [
            IngestionResultResponse(
                candidate_url=result.candidate_url,
                status=result.status.value,
                article_id=result.article_id,
                error_code=result.error_code,
                error_summary=result.error_summary,
            )
            for result in results
        ]

    @app.post("/ingestion/files", response_model=IngestionResultResponse)
    async def ingest_file_route(
        source_id: UUID = Form(...),
        file: UploadFile = File(...),
        _key: str = Depends(_require_key),
    ) -> IngestionResultResponse:
        runtime: RuntimeDependencies = app.state.runtime
        content = await file.read()
        if len(content) > runtime.settings.article_max_response_size_bytes:
            return IngestionResultResponse(
                candidate_url=file.filename or "upload",
                status=IngestionStatus.FAILED.value,
                article_id=None,
                error_code="file_too_large",
                error_summary=(
                    f"file size {len(content)} exceeds maximum "
                    f"{runtime.settings.article_max_response_size_bytes} bytes"
                ),
            )
        result = await app.state.ingestion_service.ingest_file(
            source_id, file.filename or "upload", content, file.content_type or ""
        )
        return IngestionResultResponse(
            candidate_url=result.candidate_url,
            status=result.status.value,
            article_id=result.article_id,
            error_code=result.error_code,
            error_summary=result.error_summary,
        )

    @app.get("/ingestion/attempts", response_model=list[IngestionAttemptResponse])
    async def get_ingestion_attempts(
        status: str | None = None,
        limit: int = 50,
    ) -> list[IngestionAttemptResponse]:
        parsed_status: IngestionStatus | None = None
        if status is not None:
            try:
                parsed_status = IngestionStatus(status)
            except ValueError as exc:
                raise HTTPException(status_code=422, detail="unknown status") from exc

        runtime: RuntimeDependencies = app.state.runtime
        async with session_scope(runtime.session_factory) as session:
            attempts = await list_ingestion_attempts(session, status=parsed_status, limit=limit)

        return [
            IngestionAttemptResponse(
                id=attempt.id,
                source_id=attempt.source_id,
                source_feed_id=attempt.source_feed_id,
                requested_url=attempt.requested_url,
                canonical_url=attempt.canonical_url,
                status=attempt.status.value,
                http_status=attempt.http_status,
                extractor=attempt.extractor.value if attempt.extractor is not None else None,
                article_id=attempt.article_id,
                error_code=attempt.error_code,
                error_summary=attempt.error_summary,
                started_at=attempt.started_at,
                completed_at=attempt.completed_at,
            )
            for attempt in attempts
        ]

    @app.post("/pipelines/daily", response_model=DailyPipelineResultResponse)
    async def trigger_daily_pipeline(
        req: TriggerDailyPipelineRequest,
        _key: str = Depends(_require_key),
    ) -> DailyPipelineResultResponse:
        result = await app.state.pipeline.run(req.target_date)
        return DailyPipelineResultResponse(
            target_date=result.target_date,
            feeds_polled=result.feeds_polled,
            articles_succeeded=result.articles_succeeded,
            articles_duplicate=result.articles_duplicate,
            articles_failed=result.articles_failed,
            batches_created=result.batches_created,
            batches_reused=result.batches_reused,
            summaries_created=result.summaries_created,
            summaries_reused=result.summaries_reused,
            summaries_selected=result.summaries_selected,
            is_no_content=result.is_no_content,
            workflow_run_id=result.workflow_run_id,
            workflow_status=result.workflow_status.value if result.workflow_status else None,
            brief_id=result.brief_id,
        )

    @app.post("/pipelines/weekly", response_model=PeriodicPipelineResultResponse)
    async def trigger_weekly_pipeline(
        req: TriggerPeriodicPipelineRequest,
        _key: str = Depends(_require_key),
    ) -> PeriodicPipelineResultResponse:
        result = await app.state.weekly_pipeline.run(req.target_date)
        return _periodic_result_to_response(result)

    @app.post("/pipelines/monthly", response_model=PeriodicPipelineResultResponse)
    async def trigger_monthly_pipeline(
        req: TriggerPeriodicPipelineRequest,
        _key: str = Depends(_require_key),
    ) -> PeriodicPipelineResultResponse:
        result = await app.state.monthly_pipeline.run(req.target_date)
        return _periodic_result_to_response(result)

    @app.get("/briefs", response_model=list[BriefListItemResponse])
    async def list_briefs(cadence: str = "daily") -> list[BriefListItemResponse]:
        try:
            parsed_cadence = Cadence(cadence)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail="unknown cadence") from exc

        runtime: RuntimeDependencies = app.state.runtime
        async with session_scope(runtime.session_factory) as session:
            # list_prior_briefs uses covered_end < before (strictly earlier) -
            # its other caller needs that for narrative-context loading, but a
            # brief listing must include one generated earlier today, so push
            # the cutoff to tomorrow rather than excluding today's own brief.
            briefs = await list_prior_briefs(
                session, parsed_cadence, before=date.today() + timedelta(days=1)
            )

        return [
            BriefListItemResponse(
                id=brief.id,
                cadence=brief.cadence.value,
                covered_start=brief.covered_start,
                covered_end=brief.covered_end,
                created_at=brief.created_at,
            )
            for brief in briefs
        ]

    @app.get("/briefs/{brief_id}", response_model=BriefDetailResponse)
    async def get_brief_detail(brief_id: UUID) -> BriefDetailResponse:
        runtime: RuntimeDependencies = app.state.runtime
        async with session_scope(runtime.session_factory) as session:
            brief = await get_brief_by_id(session, brief_id)
            if brief is None:
                raise HTTPException(status_code=404, detail="brief not found")

            summaries = await get_batch_summaries_by_ids(session, brief.cited_batch_summary_ids)
            article_ids = {
                citation.article_id for summary in summaries for citation in summary.citations
            }
            articles = await get_articles_by_ids(session, list(article_ids))
            sources = await get_sources_by_ids(
                session, list({article.source_id for article in articles})
            )

        articles_by_id = {article.id: article for article in articles}
        sources_by_id = {source.id: source for source in sources}

        cited_summaries: list[ResolvedBatchSummaryResponse] = []
        for summary in summaries:
            resolved_citations: list[ResolvedCitationResponse] = []
            for citation in summary.citations:
                article = articles_by_id.get(citation.article_id)
                if article is None:
                    resolved_citations.append(
                        ResolvedCitationResponse(
                            article_id=citation.article_id,
                            excerpt=citation.excerpt,
                            article_title="",
                            article_url="",
                            source_name="",
                        )
                    )
                    continue
                source = sources_by_id.get(article.source_id)
                resolved_citations.append(
                    ResolvedCitationResponse(
                        article_id=citation.article_id,
                        excerpt=citation.excerpt,
                        article_title=article.title,
                        article_url=article.url,
                        source_name=source.name if source is not None else "",
                    )
                )
            cited_summaries.append(
                ResolvedBatchSummaryResponse(
                    id=summary.id,
                    model=summary.model,
                    prompt_version=summary.prompt_version,
                    summary=summary.summary,
                    source_notes=summary.source_notes,
                    entities=summary.entities,
                    topics=summary.topics,
                    citations=resolved_citations,
                )
            )

        return BriefDetailResponse(
            id=brief.id,
            cadence=brief.cadence.value,
            covered_start=brief.covered_start,
            covered_end=brief.covered_end,
            content=brief.content,
            narrative_state_version_id=brief.narrative_state_version_id,
            created_by_run_id=brief.created_by_run_id,
            created_at=brief.created_at,
            cited_summaries=cited_summaries,
        )

    @app.get("/archive/search", response_model=list[ArchiveSearchResultResponse])
    async def search_archive(
        q: str, cadence: str | None = None, limit: int = 10
    ) -> list[ArchiveSearchResultResponse]:
        if not q.strip():
            raise HTTPException(status_code=422, detail="q must not be blank")
        if not 1 <= limit <= 50:
            raise HTTPException(status_code=422, detail="limit must be between 1 and 50")
        parsed_cadence: Cadence | None = None
        if cadence is not None:
            try:
                parsed_cadence = Cadence(cadence)
            except ValueError as exc:
                raise HTTPException(status_code=422, detail="unknown cadence") from exc

        runtime: RuntimeDependencies = app.state.runtime
        try:
            query_vector, _usage = await runtime.gateway.embed(text=q, correlation_id=str(uuid4()))
        except TerminalModelError as exc:
            raise HTTPException(
                status_code=503,
                detail="archive search unavailable: embeddings not supported by the "
                "configured model provider",
            ) from exc
        except RetryableModelError as exc:
            raise HTTPException(
                status_code=503,
                detail="archive search temporarily unavailable: embedding request failed, "
                "try again",
            ) from exc

        async with session_scope(runtime.session_factory) as session:
            results = await search_embeddings_by_similarity(
                session, query_vector, cadence=parsed_cadence, limit=limit
            )

        return [
            ArchiveSearchResultResponse(
                brief_id=brief.id,
                cadence=brief.cadence.value,
                covered_start=brief.covered_start,
                covered_end=brief.covered_end,
                created_at=brief.created_at,
                content=brief.content[:_ARCHIVE_SNIPPET_LENGTH],
                similarity_score=_cosine_similarity(query_vector, embedding.vector),
            )
            for embedding, brief in results
        ]

    app.mount("/ui", StaticFiles(directory=STATIC_DIR, html=True), name="ui")

    return app
