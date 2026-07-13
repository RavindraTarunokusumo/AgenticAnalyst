"""Offline unit tests for feed parsing."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

import pytest

from analyst_engine.ingestion.feed_parser import FeedParseError, parse_feed

_SOURCE_ID = UUID("11111111-1111-1111-1111-111111111111")
_SOURCE_FEED_ID = UUID("22222222-2222-2222-2222-222222222222")
_FEED_URL = "https://example.com/feed.xml"


def test_parse_rss_feed_returns_three_ordered_candidates() -> None:
    raw = b"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>Example</title>
    <item>
      <title>First</title>
      <link>https://example.com/a</link>
      <guid>guid-a</guid>
      <author>Alice</author>
      <pubDate>Mon, 01 Jan 2024 10:00:00 GMT</pubDate>
    </item>
    <item>
      <title>Second</title>
      <link>https://example.com/b</link>
      <guid>guid-b</guid>
      <pubDate>Mon, 01 Jan 2024 11:00:00 GMT</pubDate>
    </item>
    <item>
      <title>Third</title>
      <link>https://example.com/c</link>
      <guid>guid-c</guid>
      <pubDate>Mon, 01 Jan 2024 12:00:00 GMT</pubDate>
    </item>
  </channel>
</rss>
"""

    candidates = parse_feed(raw, _FEED_URL, _SOURCE_ID, source_feed_id=_SOURCE_FEED_ID)

    assert len(candidates) == 3
    assert [candidate.title for candidate in candidates] == ["First", "Second", "Third"]
    assert [candidate.url for candidate in candidates] == [
        "https://example.com/a",
        "https://example.com/b",
        "https://example.com/c",
    ]
    assert candidates[0].author == "Alice"
    assert candidates[0].source_id == _SOURCE_ID
    assert candidates[0].source_feed_id == _SOURCE_FEED_ID
    assert candidates[0].entry_id == "guid-a"
    assert candidates[0].published_at == datetime(2024, 1, 1, 10, 0, 0, tzinfo=UTC)


def test_parse_atom_feed_returns_candidates() -> None:
    raw = b"""<?xml version="1.0" encoding="utf-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <title>Atom Example</title>
  <entry>
    <title>Atom Entry</title>
    <link href="https://example.com/atom-1"/>
    <id>urn:uuid:atom-1</id>
    <author><name>Bob</name></author>
    <published>2024-02-01T08:30:00Z</published>
  </entry>
</feed>
"""

    candidates = parse_feed(raw, _FEED_URL, _SOURCE_ID)

    assert len(candidates) == 1
    assert candidates[0].title == "Atom Entry"
    assert candidates[0].url == "https://example.com/atom-1"
    assert candidates[0].author == "Bob"
    assert candidates[0].entry_id == "urn:uuid:atom-1"
    assert candidates[0].published_at == datetime(2024, 2, 1, 8, 30, 0, tzinfo=UTC)


def test_parse_feed_skips_entries_missing_link() -> None:
    raw = b"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>Example</title>
    <item>
      <title>No Link</title>
      <description>Entry without link or guid</description>
    </item>
    <item>
      <title>Has Link</title>
      <link>https://example.com/keep</link>
      <guid>guid-keep</guid>
      <pubDate>Mon, 01 Jan 2024 10:00:00 GMT</pubDate>
    </item>
  </channel>
</rss>
"""

    candidates = parse_feed(raw, _FEED_URL, _SOURCE_ID)

    assert len(candidates) == 1
    assert candidates[0].title == "Has Link"
    assert candidates[0].url == "https://example.com/keep"


def test_parse_feed_continues_when_bozo_but_entries_present() -> None:
    raw = b"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>Broken But Usable</title>
    <item>
      <title>Still Valid</title>
      <link>https://example.com/usable</link>
      <guid>guid-usable</guid>
      <pubDate>Mon, 01 Jan 2024 10:00:00 GMT</pubDate>
    </item>
  </channel>
  <!-- trailing garbage to trigger lenient bozo parsing -->
  <<not-xml>>
</rss>
"""

    candidates = parse_feed(raw, _FEED_URL, _SOURCE_ID)

    assert len(candidates) == 1
    assert candidates[0].title == "Still Valid"
    assert candidates[0].url == "https://example.com/usable"


def test_parse_feed_raises_for_fully_malformed_document() -> None:
    with pytest.raises(FeedParseError, match="malformed and contains no entries"):
        parse_feed(b"this is not a feed", _FEED_URL, _SOURCE_ID)


def test_parse_feed_orders_candidates_deterministically() -> None:
    raw = b"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>Ordering</title>
    <item>
      <title>Late</title>
      <link>https://example.com/z</link>
      <guid>guid-z</guid>
      <pubDate>Mon, 03 Jan 2024 10:00:00 GMT</pubDate>
    </item>
    <item>
      <title>Early</title>
      <link>https://example.com/a</link>
      <guid>guid-a</guid>
      <pubDate>Mon, 01 Jan 2024 10:00:00 GMT</pubDate>
    </item>
    <item>
      <title>Same Time First URL</title>
      <link>https://example.com/b</link>
      <guid>guid-b</guid>
      <pubDate>Mon, 02 Jan 2024 10:00:00 GMT</pubDate>
    </item>
    <item>
      <title>Same Time Second URL</title>
      <link>https://example.com/c</link>
      <guid>guid-c</guid>
      <pubDate>Mon, 02 Jan 2024 10:00:00 GMT</pubDate>
    </item>
    <item>
      <title>No Date</title>
      <link>https://example.com/no-date</link>
      <guid>guid-no-date</guid>
    </item>
  </channel>
</rss>
"""

    candidates = parse_feed(raw, _FEED_URL, _SOURCE_ID)

    assert [candidate.title for candidate in candidates] == [
        "No Date",
        "Early",
        "Same Time First URL",
        "Same Time Second URL",
        "Late",
    ]
