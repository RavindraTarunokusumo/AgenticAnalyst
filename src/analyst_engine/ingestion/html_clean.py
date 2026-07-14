"""Deterministic HTML cleaning using only the Python standard library."""

from __future__ import annotations

import re
from html.parser import HTMLParser

from analyst_engine.ingestion.models import CleanedContent

_SKIP_TAGS = frozenset({"script", "style", "nav", "header", "footer", "aside", "form", "noscript"})
_BLOCK_BOUNDARY_TAGS = frozenset({"p", "h1", "h2", "h3", "h4", "h5", "h6", "li", "blockquote"})
_WHITESPACE_RE = re.compile(r"\s+")


def _collapse_whitespace(text: str) -> str:
    return _WHITESPACE_RE.sub(" ", text).strip()


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

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag_lower = tag.lower()
        if tag_lower == "html":
            for name, value in attrs:
                if name.lower() == "lang" and value:
                    self.language = value.split("-")[0].split("_")[0].lower()
                    break

        if tag_lower in _SKIP_TAGS:
            self.skip_depth += 1
            return

        if self.skip_depth > 0:
            return

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
        elif tag_lower in _BLOCK_BOUNDARY_TAGS:
            self._flush_block()

    def handle_data(self, data: str) -> None:
        if self.skip_depth > 0:
            return
        if self._in_title:
            self._title_parts.append(data)
        elif self._in_h1:
            self._h1_parts.append(data)
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
        return CleanedContent(title=title, text=text, language=self.language)


def clean_html(html: str) -> CleanedContent:
    """Extract title, language, and cleaned body text from HTML."""
    parser = _HtmlCleaner()
    parser.feed(html)
    parser.close()
    return parser.finalize()
