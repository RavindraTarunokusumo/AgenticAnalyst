"""Pure keyword relevance predicate for topic filtering.

Keywords are untrusted (LLM suggestions and user edits) and are always
escaped before compilation so metacharacters match literally.
"""

from __future__ import annotations

import re

# ASCII-only boundary class (not ``\\w``): ``\\b``/``\\w`` break on keywords that
# start or end with non-word chars (C++, .*), and treat CJK letters as word
# chars so ``北京`` would fail inside ``访问北京的记者``. ASCII boundaries keep
# ``war`` out of ``Warsaw`` while allowing script-without-spaces matches.
_ASCII_WORD = r"A-Za-z0-9_"


def matches(keywords: list[str], *fields: str | None) -> bool:
    """Return True if any keyword matches any non-empty field.

    Case-insensitive, word-boundary, any-match. Boundaries are ASCII
    alphanumerics/underscore lookarounds around a ``re.escape``'d keyword.
    """
    texts = [field for field in fields if field]
    if not texts or not keywords:
        return False

    for keyword in keywords:
        if not keyword:
            continue
        pattern = re.compile(
            rf"(?<![{_ASCII_WORD}]){re.escape(keyword)}(?![{_ASCII_WORD}])",
            re.IGNORECASE,
        )
        for text in texts:
            if pattern.search(text) is not None:
                return True
    return False
