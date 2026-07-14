"""Offline unit tests for deterministic HTML cleaning."""

from __future__ import annotations

from datetime import UTC, datetime

from analyst_engine.ingestion.html_clean import clean_html


def test_clean_html_extracts_title_from_title_tag() -> None:
    html = """
    <html lang="en-US">
      <head><title>  Daily   Brief  </title></head>
      <body><p>Body text.</p></body>
    </html>
    """

    result = clean_html(html)

    assert result.title == "Daily Brief"
    assert result.language == "en"
    assert result.text == "Body text."


def test_clean_html_falls_back_to_first_h1_when_title_missing() -> None:
    html = """
    <html>
      <body>
        <h1>  Article   Heading  </h1>
        <p>First paragraph.</p>
      </body>
    </html>
    """

    result = clean_html(html)

    assert result.title == "Article Heading"
    assert result.language is None


def test_clean_html_returns_none_title_when_missing() -> None:
    html = "<html><body><p>Only body text.</p></body></html>"

    result = clean_html(html)

    assert result.title is None
    assert result.text == "Only body text."


def test_clean_html_extracts_language_from_html_tag() -> None:
    html = '<html lang="fr-CA"><body><p>Bonjour.</p></body></html>'

    result = clean_html(html)

    assert result.language == "fr"
    assert result.text == "Bonjour."


def test_clean_html_excludes_script_style_and_nav_content() -> None:
    html = """
    <html>
      <body>
        <nav>Skip this navigation</nav>
        <p>Keep this paragraph.</p>
        <script>alert("hidden");</script>
        <style>.hidden { display: none; }</style>
        <header>Header boilerplate</header>
        <footer>Footer boilerplate</footer>
      </body>
    </html>
    """

    result = clean_html(html)

    assert "Skip this navigation" not in result.text
    assert "alert" not in result.text
    assert ".hidden" not in result.text
    assert "Header boilerplate" not in result.text
    assert "Footer boilerplate" not in result.text
    assert result.text == "Keep this paragraph."


def test_clean_html_preserves_paragraph_order_with_blank_line_separation() -> None:
    html = """
    <html>
      <body>
        <p>First paragraph.</p>
        <h2>Section title</h2>
        <p>Second paragraph.</p>
        <blockquote>Quoted insight.</blockquote>
      </body>
    </html>
    """

    result = clean_html(html)

    assert result.text == (
        "First paragraph.\n\nSection title\n\nSecond paragraph.\n\nQuoted insight."
    )


def test_clean_html_collapses_whitespace_within_text_fragments() -> None:
    html = """
    <html>
      <body>
        <p>  Lots   of    spaces  </p>
        <p>Line one<br>   line   two  </p>
      </body>
    </html>
    """

    result = clean_html(html)

    assert result.text == "Lots of spaces\n\nLine one\nline two"


def test_clean_html_extracts_article_published_time_meta_tag() -> None:
    html = """
    <html>
      <head>
        <meta property="article:published_time" content="2026-07-10T08:00:00Z">
      </head>
      <body><p>Published article body.</p></body>
    </html>
    """

    result = clean_html(html)

    assert result.published_at == datetime(2026, 7, 10, 8, 0, tzinfo=UTC)


def test_clean_html_falls_back_to_time_element_when_meta_missing() -> None:
    html = """
    <html>
      <body>
        <time datetime="2026-07-10">July 10</time>
        <p>Article body.</p>
      </body>
    </html>
    """

    result = clean_html(html)

    assert result.published_at == datetime(2026, 7, 10, 0, 0, tzinfo=UTC)


def test_clean_html_ignores_malformed_date_strings() -> None:
    html = """
    <html>
      <head>
        <meta property="article:published_time" content="not-a-real-date">
      </head>
      <body><p>Article body.</p></body>
    </html>
    """

    result = clean_html(html)

    assert result.published_at is None


def test_clean_html_extracts_author_meta_tag() -> None:
    html = """
    <html>
      <head><meta name="author" content="Jane Doe"></head>
      <body><p>Article body.</p></body>
    </html>
    """

    result = clean_html(html)

    assert result.author == "Jane Doe"
