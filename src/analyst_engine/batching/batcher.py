from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID, uuid4

from analyst_engine.domain.models import Article, ArticleBatch, GroupingMethod

_TOKEN_RE = re.compile(r"[a-z0-9]+")
_MIN_TOKEN_LENGTH = 2
_MIN_BATCH_SIZE = 3
_MAX_BATCH_SIZE = 5


@dataclass(frozen=True)
class BatcherResult:
    batches: list[ArticleBatch]
    carried_forward_ids: list[UUID]


def _title_tokens(title: str | None) -> frozenset[str]:
    if not title:
        return frozenset()
    tokens = _TOKEN_RE.findall(title.lower())
    return frozenset(t for t in tokens if len(t) >= _MIN_TOKEN_LENGTH)


def _jaccard(a: frozenset[str], b: frozenset[str]) -> float:
    if not a or not b:
        return 0.0
    union = a | b
    if not union:
        return 0.0
    return len(a & b) / len(union)


def _sort_key(article: Article) -> tuple[datetime, str, UUID]:
    return (article.published_at, article.url_fingerprint, article.id)


def _derive_batch_key(
    article_ids_in_order: list[UUID],
    grouping_method: GroupingMethod,
    grouping_algorithm_version: str,
    threshold: float,
) -> str:
    parts = [str(a) for a in article_ids_in_order]
    parts.append(grouping_method.value)
    parts.append(grouping_algorithm_version)
    parts.append(f"{threshold:.6f}")
    raw = "|".join(parts)
    return hashlib.sha256(raw.encode()).hexdigest()


def batch_articles(
    articles: list[Article],
    *,
    title_similarity_threshold: float,
    grouping_algorithm_version: str,
) -> BatcherResult:
    """Deterministically group eligible articles into batches of 3-5.

    Partitions by language, orders deterministically within each partition,
    then greedily forms groups using fixed seed-based similarity matching.
    Pure and deterministic: identical input always produces identical output.
    """
    by_language: dict[str | None, list[Article]] = {}
    for article in articles:
        by_language.setdefault(article.language, []).append(article)

    run_id = uuid4()
    all_batches: list[ArticleBatch] = []
    all_carried_forward: list[UUID] = []

    for language_key in sorted(by_language.keys(), key=lambda k: (k is None, k or "")):
        partition = sorted(by_language[language_key], key=_sort_key)
        remaining = list(partition)

        while remaining:
            seed = remaining.pop(0)
            seed_tokens = _title_tokens(seed.title)
            current_group = [seed]
            still_remaining: list[Article] = []
            for candidate in remaining:
                if len(current_group) >= _MAX_BATCH_SIZE:
                    still_remaining.append(candidate)
                    continue
                similarity = _jaccard(seed_tokens, _title_tokens(candidate.title))
                if similarity >= title_similarity_threshold:
                    current_group.append(candidate)
                else:
                    still_remaining.append(candidate)
            remaining = still_remaining

            if len(current_group) >= _MIN_BATCH_SIZE:
                article_ids = [a.id for a in current_group]
                batch_key = _derive_batch_key(
                    article_ids,
                    GroupingMethod.TITLE_TOKEN_JACCARD,
                    grouping_algorithm_version,
                    title_similarity_threshold,
                )
                all_batches.append(
                    ArticleBatch(
                        article_ids=article_ids,
                        batch_key=batch_key,
                        grouping_method=GroupingMethod.TITLE_TOKEN_JACCARD,
                        embedding_model="none",
                        similarity_threshold=title_similarity_threshold,
                        grouping_run_id=run_id,
                    )
                )
            else:
                all_carried_forward.extend(a.id for a in current_group)

    return BatcherResult(batches=all_batches, carried_forward_ids=all_carried_forward)
