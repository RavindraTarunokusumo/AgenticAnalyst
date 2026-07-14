"""Offline unit tests for article extractors."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any

import httpx
import pytest

from analyst_engine.domain.models import ExtractorKind
from analyst_engine.ingestion.extractor import (
    Crawl4AIExtractor,
    ExtractionFailedError,
    PrimaryHttpExtractor,
    should_use_fallback,
)
from analyst_engine.ingestion.models import ExtractedArticle

_USER_AGENT = "AnalystEngine-Test/0.1"
_TIMEOUT_SECONDS = 5.0
_SIZE_LIMIT_BYTES = 1_000_000
_ARTICLE_URL = "https://93.184.216.34/article.html"


def _primary_extractor(handler: httpx.AsyncBaseTransport) -> PrimaryHttpExtractor:
    return PrimaryHttpExtractor(
        httpx.AsyncClient(transport=handler),
        timeout_seconds=_TIMEOUT_SECONDS,
        size_limit_bytes=_SIZE_LIMIT_BYTES,
        user_agent=_USER_AGENT,
    )


@dataclass
class _FakeMarkdown:
    raw_markdown: str

    def __str__(self) -> str:
        return self.raw_markdown


@dataclass
class _FakeCrawlResult:
    success: bool
    html: str
    url: str
    redirected_url: str | None = None
    metadata: dict[str, Any] | None = None
    markdown: _FakeMarkdown | None = None
    error_message: str | None = None


class _FakeCrawler:
    def __init__(self, result: _FakeCrawlResult) -> None:
        self._result = result
        self.last_url: str | None = None
        self.last_config: Any | None = None

    async def arun(self, url: str, config: Any = None, **kwargs: Any) -> _FakeCrawlResult:
        self.last_url = url
        self.last_config = config
        return self._result


@pytest.mark.asyncio
async def test_primary_http_extractor_returns_extracted_article() -> None:
    html = """
    <html lang="en">
      <head><title>Test Article</title></head>
      <body><p>Primary extractor body content with enough length for acceptance.</p></body>
    </html>
    """
    body = html.encode("utf-8")

    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["user-agent"] == _USER_AGENT
        return httpx.Response(200, content=body, request=request)

    extractor = _primary_extractor(httpx.MockTransport(handler))
    extracted = await extractor.extract(_ARTICLE_URL)

    assert extracted.url == _ARTICLE_URL
    assert extracted.title == "Test Article"
    assert "Primary extractor body content" in extracted.text
    assert extracted.language == "en"
    assert extracted.extractor is ExtractorKind.PRIMARY_HTTP
    assert extracted.raw_content_hash == hashlib.sha256(body).hexdigest()


@pytest.mark.asyncio
async def test_primary_http_extractor_raises_on_non_success_status() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, content=b"not found", request=request)

    extractor = _primary_extractor(httpx.MockTransport(handler))

    with pytest.raises(ExtractionFailedError, match="non-success status 404"):
        await extractor.extract(_ARTICLE_URL)


@pytest.mark.asyncio
async def test_crawl4ai_extractor_returns_extracted_article_from_fake_crawler() -> None:
    html = """
    <html lang="en">
      <head><title>Fallback Title</title></head>
      <body><p>Ignored when markdown is present.</p></body>
    </html>
    """
    fake_result = _FakeCrawlResult(
        success=True,
        html=html,
        url=_ARTICLE_URL,
        redirected_url="https://93.184.216.34/final.html",
        metadata={"title": "Metadata Title", "language": "en"},
        markdown=_FakeMarkdown("Crawl4AI markdown body with sufficient extracted content."),
    )
    fake_crawler = _FakeCrawler(fake_result)
    extractor = Crawl4AIExtractor(timeout_seconds=_TIMEOUT_SECONDS, crawler=fake_crawler)

    extracted = await extractor.extract(_ARTICLE_URL)

    assert fake_crawler.last_url == _ARTICLE_URL
    assert fake_crawler.last_config is not None
    assert fake_crawler.last_config.page_timeout == int(_TIMEOUT_SECONDS * 1000)
    assert extracted.url == "https://93.184.216.34/final.html"
    assert extracted.title == "Metadata Title"
    assert extracted.text == "Crawl4AI markdown body with sufficient extracted content."
    assert extracted.language == "en"
    assert extracted.extractor is ExtractorKind.CRAWL4AI
    assert extracted.raw_content_hash == hashlib.sha256(html.encode("utf-8")).hexdigest()


@pytest.mark.asyncio
async def test_crawl4ai_extractor_raises_when_fake_crawler_reports_failure() -> None:
    fake_result = _FakeCrawlResult(
        success=False,
        html="",
        url=_ARTICLE_URL,
        error_message="blocked by bot protection",
    )
    extractor = Crawl4AIExtractor(
        timeout_seconds=_TIMEOUT_SECONDS,
        crawler=_FakeCrawler(fake_result),
    )

    with pytest.raises(ExtractionFailedError, match="blocked by bot protection"):
        await extractor.extract(_ARTICLE_URL)


def test_should_use_fallback_when_title_missing() -> None:
    extracted = ExtractedArticle(
        url=_ARTICLE_URL,
        title=None,
        text="x" * 300,
        language="en",
        extractor=ExtractorKind.PRIMARY_HTTP,
        raw_content_hash="abc",
        published_at=None,
        author=None,
    )

    assert should_use_fallback(extracted, min_content_length=200) is True


def test_should_use_fallback_when_content_too_short() -> None:
    extracted = ExtractedArticle(
        url=_ARTICLE_URL,
        title="Valid Title",
        text="too short",
        language="en",
        extractor=ExtractorKind.PRIMARY_HTTP,
        raw_content_hash="abc",
        published_at=None,
        author=None,
    )

    assert should_use_fallback(extracted, min_content_length=200) is True


def test_should_use_fallback_false_when_title_and_length_are_adequate() -> None:
    extracted = ExtractedArticle(
        url=_ARTICLE_URL,
        title="Valid Title",
        text="x" * 250,
        language="en",
        extractor=ExtractorKind.PRIMARY_HTTP,
        raw_content_hash="abc",
        published_at=None,
        author=None,
    )

    assert should_use_fallback(extracted, min_content_length=200) is False
