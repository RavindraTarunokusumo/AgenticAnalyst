"""Article extraction via bounded HTTP and optional Crawl4AI fallback."""

from __future__ import annotations

import hashlib
from datetime import datetime
from typing import Any, Protocol, runtime_checkable

import httpx
from crawl4ai import AsyncWebCrawler, CrawlerRunConfig  # type: ignore[import-untyped]

from analyst_engine.domain.models import ExtractorKind
from analyst_engine.ingestion.bounded_http import bounded_fetch
from analyst_engine.ingestion.html_clean import clean_html, parse_datetime_string
from analyst_engine.ingestion.models import CleanedContent, ExtractedArticle


class ExtractionFailedError(RuntimeError):
    """Raised when an extractor cannot produce a usable article."""


@runtime_checkable
class ArticleExtractor(Protocol):
    async def extract(self, url: str) -> ExtractedArticle: ...


class PrimaryHttpExtractor:
    """Fetches article HTML with bounded HTTP and deterministic cleaning."""

    def __init__(
        self,
        client: httpx.AsyncClient,
        *,
        timeout_seconds: float,
        size_limit_bytes: int,
        user_agent: str,
    ) -> None:
        self._client = client
        self._timeout_seconds = timeout_seconds
        self._size_limit_bytes = size_limit_bytes
        self._user_agent = user_agent

    async def extract(self, url: str) -> ExtractedArticle:
        result = await bounded_fetch(
            self._client,
            url,
            timeout_seconds=self._timeout_seconds,
            size_limit_bytes=self._size_limit_bytes,
            user_agent=self._user_agent,
        )
        if result.status_code < 200 or result.status_code >= 300:
            raise ExtractionFailedError(
                f"article fetch returned non-success status {result.status_code}"
            )

        html_text = result.body.decode("utf-8", errors="replace")
        cleaned = clean_html(html_text)
        raw_content_hash = hashlib.sha256(result.body).hexdigest()
        return ExtractedArticle(
            url=result.final_url,
            title=cleaned.title,
            text=cleaned.text,
            language=cleaned.language,
            extractor=ExtractorKind.PRIMARY_HTTP,
            raw_content_hash=raw_content_hash,
            published_at=cleaned.published_at,
            author=cleaned.author,
        )


class Crawl4AIExtractor:
    """Thin adapter around Crawl4AI's AsyncWebCrawler for fallback extraction."""

    def __init__(
        self,
        *,
        timeout_seconds: float,
        crawler: Any | None = None,
    ) -> None:
        self._timeout_seconds = timeout_seconds
        self._crawler = crawler

    def _build_config(self) -> CrawlerRunConfig:
        return CrawlerRunConfig(page_timeout=int(self._timeout_seconds * 1000))

    async def extract(self, url: str) -> ExtractedArticle:
        config = self._build_config()
        if self._crawler is not None:
            result = await self._crawler.arun(url=url, config=config)
            return _map_crawl_result(result)

        async with AsyncWebCrawler() as crawler:
            result = await crawler.arun(url=url, config=config)
            return _map_crawl_result(result)


def _map_crawl_result(result: Any) -> ExtractedArticle:
    if not result.success:
        message = result.error_message or "crawl4ai extraction failed"
        raise ExtractionFailedError(message)

    html = result.html or ""
    cleaned = clean_html(html)
    metadata = result.metadata or {}

    title = _non_empty_str(metadata.get("title")) or cleaned.title
    language = _non_empty_str(metadata.get("language")) or cleaned.language
    author = _non_empty_str(metadata.get("author")) or cleaned.author
    published_at = _extract_published_at_from_metadata(metadata) or cleaned.published_at
    text = _extract_crawl_text(result, cleaned)

    final_url = result.redirected_url or result.url
    raw_content_hash = hashlib.sha256(html.encode("utf-8")).hexdigest()

    return ExtractedArticle(
        url=final_url,
        title=title,
        text=text,
        language=language,
        extractor=ExtractorKind.CRAWL4AI,
        raw_content_hash=raw_content_hash,
        published_at=published_at,
        author=author,
    )


def _extract_crawl_text(result: Any, cleaned: CleanedContent) -> str:
    markdown = result.markdown
    if markdown is not None:
        raw_markdown = getattr(markdown, "raw_markdown", None)
        if isinstance(raw_markdown, str) and raw_markdown.strip():
            return raw_markdown.strip()
        markdown_text = str(markdown).strip()
        if markdown_text:
            return markdown_text
    return cleaned.text


def _extract_published_at_from_metadata(metadata: dict[str, Any]) -> datetime | None:
    for key in ("published_date", "article:published_time", "article:modified_time"):
        raw_value = metadata.get(key)
        if not isinstance(raw_value, str):
            continue
        parsed = parse_datetime_string(raw_value)
        if parsed is not None:
            return parsed
    return None


def _non_empty_str(value: Any) -> str | None:
    if isinstance(value, str):
        stripped = value.strip()
        if stripped:
            return stripped
    return None


def should_use_fallback(extracted: ExtractedArticle, *, min_content_length: int) -> bool:
    """Return True when primary extraction lacks a usable title or enough body text."""
    if extracted.title is None or not extracted.title.strip():
        return True
    return len(extracted.text.strip()) < min_content_length
