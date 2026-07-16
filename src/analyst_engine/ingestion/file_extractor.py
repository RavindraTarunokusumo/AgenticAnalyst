"""Synchronous extraction for uploaded PDF/plain-text files."""

from __future__ import annotations

import hashlib
import io
from pathlib import Path
from typing import Protocol, runtime_checkable

from pypdf import PdfReader
from pypdf.errors import PyPdfError

from analyst_engine.domain.models import ExtractorKind
from analyst_engine.ingestion.models import ExtractedArticle


class FileExtractionError(RuntimeError):
    """Raised when a file extractor cannot produce usable text."""


@runtime_checkable
class FileExtractor(Protocol):
    def extract(self, filename: str, content: bytes) -> ExtractedArticle: ...


def _title_from_filename(filename: str) -> str:
    return Path(filename).stem


class PdfFileExtractor:
    """Extracts text from an uploaded PDF via pypdf."""

    def extract(self, filename: str, content: bytes) -> ExtractedArticle:
        try:
            reader = PdfReader(io.BytesIO(content))
            text = "\n".join(page.extract_text() or "" for page in reader.pages)
        except PyPdfError as exc:
            raise FileExtractionError(f"failed to read PDF {filename!r}: {exc}") from exc

        cleaned_text = text.strip()
        if not cleaned_text:
            raise FileExtractionError(f"PDF {filename!r} has no extractable text")

        title = None
        if reader.metadata is not None:
            title = reader.metadata.title
        if title is None or not title.strip():
            title = _title_from_filename(filename)

        return ExtractedArticle(
            url=filename,
            title=title,
            text=cleaned_text,
            language=None,
            extractor=ExtractorKind.FILE_PDF,
            raw_content_hash=hashlib.sha256(content).hexdigest(),
            published_at=None,
            author=None,
        )


class TextFileExtractor:
    """Decodes an uploaded plain-text file as UTF-8."""

    def extract(self, filename: str, content: bytes) -> ExtractedArticle:
        cleaned_text = content.decode("utf-8", errors="replace").strip()
        if not cleaned_text:
            raise FileExtractionError(f"text file {filename!r} has no content")

        return ExtractedArticle(
            url=filename,
            title=_title_from_filename(filename),
            text=cleaned_text,
            language=None,
            extractor=ExtractorKind.FILE_TEXT,
            raw_content_hash=hashlib.sha256(content).hexdigest(),
            published_at=None,
            author=None,
        )
