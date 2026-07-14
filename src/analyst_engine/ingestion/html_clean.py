"""Deterministic HTML cleaning using only the Python standard library."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser

from analyst_engine.ingestion.models import CleanedContent

_SKIP_TAGS = frozenset({"script", "style", "nav", "header", "footer", "aside", "form", "noscript"})
_BLOCK_BOUNDARY_TAGS = frozenset({"p", "h1", "h2", "h3", "h4", "h5", "h6", "li", "blockquote"})
_WHITESPACE_RE = re.compile(r"\s+")
_META_PUBLISH_PRIORITY: tuple[tuple[str, str], ...] = (
    ("property", "article:published_time"),
    ("name", "date"),
    ("name", "publish-date"),
    ("name", "parsely-pub-date"),
)


def _collapse_whitespace(text: str) -> str:
    return _WHITESPACE_RE.sub(" ", text).strip()


def parse_datetime_string(value: str) -> datetime | None:
    """Parse ISO-8601 or RFC 2822 datetime strings from page metadata."""
    normalized = value.strip()
    if not normalized:
        return None

    iso_candidate = normalized.replace("Z", "+00:00")
    try:
        iso_parsed = datetime.fromisoformat(iso_candidate)
    except ValueError:
        pass
    else:
        if iso_parsed.tzinfo is None:
            iso_parsed = iso_parsed.replace(tzinfo=UTC)
        return iso_parsed

    try:
        parsed = parsedate_to_datetime(normalized)
    except (ValueError, TypeError):
        return None

    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed


def _resolve_published_at(
    meta_tags: list[tuple[str, str, str]],
    time_datetime: str | None,
) -> datetime | None:
    for attr_name, attr_value in _META_PUBLISH_PRIORITY:
        for meta_attr, meta_value, content in meta_tags:
            if meta_attr == attr_name and meta_value == attr_value:
                parsed = parse_datetime_string(content)
                if parsed is not None:
                    return parsed

    if time_datetime is not None:
        return parse_datetime_string(time_datetime)
    return None


class _HtmlCleaner(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.skip_depth = 0
        self.title: str | None = None
        self.h1: str | None = None
        self.language: str | None = None
        self.blocks: list[str] = []
        self._current_parts: list[str] = []
        self._in_title = False
        self._title_parts: list[str] = []
        self._in_h1 = False
        self._h1_parts: list[str] = []
        self._in_head = False
        self._head_depth = 0
        self._meta_tags: list[tuple[str, str, str]] = []
        self._author_meta: str | None = None
        self._time_datetime: str | None = None
        self._in_author = False
        self._author_parts: list[str] = []
        self._author: str | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag_lower = tag.lower()
        attr_map = {name.lower(): (value or "") for name, value in attrs}

        if tag_lower == "head":
            self._in_head = True
            self._head_depth += 1

        if tag_lower == "html":
            lang = attr_map.get("lang")
            if lang:
                self.language = lang.split("-")[0].split("_")[0].lower()

        if tag_lower in _SKIP_TAGS:
            self.skip_depth += 1
            return

        if self.skip_depth > 0:
            return

        if tag_lower == "meta" and self._in_head:
            content = attr_map.get("content", "").strip()
            if content:
                property_name = attr_map.get("property")
                if property_name:
                    self._meta_tags.append(("property", property_name, content))
                name = attr_map.get("name")
                if name:
                    self._meta_tags.append(("name", name, content))
                    if name == "author" and self._author_meta is None:
                        self._author_meta = content

        if tag_lower == "time" and self._time_datetime is None:
            datetime_value = attr_map.get("datetime", "").strip()
            if datetime_value:
                self._time_datetime = datetime_value

        rel_value = attr_map.get("rel", "")
        if self._author is None and "author" in {part.strip() for part in rel_value.split()}:
            self._in_author = True
            self._author_parts = []

        if tag_lower == "title":
            self._in_title = True
            self._title_parts = []
        elif tag_lower == "h1" and self.h1 is None:
            self._in_h1 = True
            self._h1_parts = []
        elif tag_lower == "br":
            self._current_parts.append("\n")
        elif tag_lower in _BLOCK_BOUNDARY_TAGS:
            self._flush_block()

    def handle_endtag(self, tag: str) -> None:
        tag_lower = tag.lower()
        if tag_lower == "head" and self._head_depth > 0:
            self._head_depth -= 1
            if self._head_depth == 0:
                self._in_head = False

        if tag_lower in _SKIP_TAGS:
            if self.skip_depth > 0:
                self.skip_depth -= 1
            return

        if self.skip_depth > 0:
            return

        if tag_lower == "title":
            self._in_title = False
            if self.title is None:
                title_text = _collapse_whitespace("".join(self._title_parts))
                if title_text:
                    self.title = title_text
        elif tag_lower == "h1" and self.h1 is None:
            self._in_h1 = False
            h1_text = _collapse_whitespace("".join(self._h1_parts))
            if h1_text:
                self.h1 = h1_text
        elif self._in_author:
            self._in_author = False
            author_text = _collapse_whitespace("".join(self._author_parts))
            if author_text and self._author is None:
                self._author = author_text
        elif tag_lower in _BLOCK_BOUNDARY_TAGS:
            self._flush_block()

    def handle_data(self, data: str) -> None:
        if self.skip_depth > 0:
            return
        if self._in_title:
            self._title_parts.append(data)
        elif self._in_h1:
            self._h1_parts.append(data)
        elif self._in_author:
            self._author_parts.append(data)
        elif data:
            self._current_parts.append(data)

    def _flush_block(self) -> None:
        if not self._current_parts:
            return
        raw = "".join(self._current_parts)
        lines = [_collapse_whitespace(line) for line in raw.split("\n")]
        block_text = "\n".join(line for line in lines if line)
        if block_text:
            self.blocks.append(block_text)
        self._current_parts = []

    def finalize(self) -> CleanedContent:
        self._flush_block()
        title = self.title or self.h1
        text = "\n\n".join(self.blocks).strip()
        published_at = _resolve_published_at(self._meta_tags, self._time_datetime)
        author = self._author_meta or self._author
        return CleanedContent(
            title=title,
            text=text,
            language=self.language,
            published_at=published_at,
            author=author,
        )


def clean_html(html: str) -> CleanedContent:
    """Extract title, language, and cleaned body text from HTML."""
    parser = _HtmlCleaner()
    parser.feed(html)
    parser.close()
    return parser.finalize()
