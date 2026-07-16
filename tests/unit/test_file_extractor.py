"""Offline unit tests for uploaded-file extractors."""

from __future__ import annotations

import hashlib
import io

import pytest
from pypdf import PdfWriter
from pypdf.generic import ContentStream, DictionaryObject, NameObject

from analyst_engine.domain.models import ExtractorKind
from analyst_engine.ingestion.file_extractor import (
    FileExtractionError,
    PdfFileExtractor,
    TextFileExtractor,
)


def _make_pdf_bytes(text: str = "", *, title: str | None = None) -> bytes:
    writer = PdfWriter()
    page = writer.add_blank_page(width=300, height=300)
    if text:
        font = DictionaryObject()
        font[NameObject("/Type")] = NameObject("/Font")
        font[NameObject("/Subtype")] = NameObject("/Type1")
        font[NameObject("/BaseFont")] = NameObject("/Helvetica")
        font_ref = writer._add_object(font)  # noqa: SLF001 - test-only PDF construction
        resources = page[NameObject("/Resources")]
        font_dict = DictionaryObject()
        font_dict[NameObject("/F1")] = font_ref
        resources[NameObject("/Font")] = font_dict

        content = ContentStream(None, writer)
        content.set_data(f"BT /F1 24 Tf 20 150 Td ({text}) Tj ET".encode())
        page.replace_contents(content)
    if title is not None:
        writer.add_metadata({"/Title": title})

    buffer = io.BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


def test_pdf_file_extractor_returns_text_and_metadata_title() -> None:
    pdf_bytes = _make_pdf_bytes("Hello uploaded PDF world", title="My PDF Title")
    extractor = PdfFileExtractor()

    result = extractor.extract("report.pdf", pdf_bytes)

    assert result.title == "My PDF Title"
    assert result.text == "Hello uploaded PDF world"
    assert result.extractor is ExtractorKind.FILE_PDF
    assert result.raw_content_hash == hashlib.sha256(pdf_bytes).hexdigest()
    assert result.published_at is None
    assert result.author is None
    assert result.language is None


def test_pdf_file_extractor_falls_back_to_filename_when_no_metadata_title() -> None:
    pdf_bytes = _make_pdf_bytes("Body text with no PDF title metadata")
    extractor = PdfFileExtractor()

    result = extractor.extract("quarterly-report.pdf", pdf_bytes)

    assert result.title == "quarterly-report"


def test_pdf_file_extractor_raises_on_no_extractable_text() -> None:
    pdf_bytes = _make_pdf_bytes("")
    extractor = PdfFileExtractor()

    with pytest.raises(FileExtractionError):
        extractor.extract("blank.pdf", pdf_bytes)


def test_pdf_file_extractor_raises_on_malformed_pdf() -> None:
    extractor = PdfFileExtractor()

    with pytest.raises(FileExtractionError):
        extractor.extract("not-a-pdf.pdf", b"this is not a pdf file at all")


def test_text_file_extractor_decodes_utf8_and_derives_title_from_filename() -> None:
    extractor = TextFileExtractor()
    content = b"Uploaded plain-text article body."

    result = extractor.extract("notes.txt", content)

    assert result.title == "notes"
    assert result.text == "Uploaded plain-text article body."
    assert result.extractor is ExtractorKind.FILE_TEXT
    assert result.raw_content_hash == hashlib.sha256(content).hexdigest()
    assert result.published_at is None
    assert result.author is None
    assert result.language is None


def test_text_file_extractor_replaces_invalid_utf8_bytes() -> None:
    extractor = TextFileExtractor()
    content = b"Valid start \xff\xfe invalid bytes then more text"

    result = extractor.extract("mixed.txt", content)

    assert "Valid start" in result.text
    assert "invalid bytes then more text" in result.text


def test_text_file_extractor_raises_on_empty_content() -> None:
    extractor = TextFileExtractor()

    with pytest.raises(FileExtractionError):
        extractor.extract("empty.txt", b"   \n\t  ")
