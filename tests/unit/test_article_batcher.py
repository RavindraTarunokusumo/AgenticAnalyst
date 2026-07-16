"""Offline unit tests for deterministic article batching."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from fixtures import DEFAULT_TOPIC_ID  # type: ignore[import-not-found]

from analyst_engine.batching.batcher import batch_articles
from analyst_engine.domain.models import Article, ArticleBatch, GroupingMethod

_SOURCE_ID = UUID("11111111-1111-1111-1111-111111111111")
_BASE_TIME = datetime(2026, 7, 13, 12, 0, tzinfo=UTC)
_THRESHOLD = 0.35
_ALGORITHM_VERSION = "v1"

_SIMILAR_TITLE = "Fed Raises Interest Rates Today"
_NEAR_SIMILAR_TITLE = "Fed Raises Interest Rates Again"
_DISSIMILAR_TITLE = "Local Sports Team Wins Championship Game"


def _make_article(
    *,
    article_id: UUID,
    title: str = _SIMILAR_TITLE,
    url_fingerprint: str,
    published_at: datetime = _BASE_TIME,
    language: str | None = "en",
) -> Article:
    return Article(
        topic_id=DEFAULT_TOPIC_ID,
        id=article_id,
        source_id=_SOURCE_ID,
        url=f"https://example.com/{url_fingerprint}",
        url_fingerprint=url_fingerprint,
        title=title,
        published_at=published_at,
        language=language,
    )


def _batch_fields(batch: ArticleBatch) -> tuple[str, list[UUID], GroupingMethod, float | None, str]:
    return (
        batch.batch_key,
        batch.article_ids,
        batch.grouping_method,
        batch.similarity_threshold,
        batch.embedding_model,
    )


def test_five_similar_articles_form_one_batch_of_five() -> None:
    articles = [
        _make_article(
            article_id=UUID(f"00000000-0000-0000-0000-00000000000{i}"),
            url_fingerprint=f"fp-{i}",
        )
        for i in range(1, 6)
    ]

    result = batch_articles(
        articles,
        title_similarity_threshold=_THRESHOLD,
        grouping_algorithm_version=_ALGORITHM_VERSION,
    )

    assert len(result.batches) == 1
    assert len(result.batches[0].article_ids) == 5
    assert result.batches[0].article_ids == [a.id for a in articles]
    assert result.carried_forward_ids == []


def test_seven_similar_articles_batch_first_five_in_sort_order() -> None:
    articles = [
        _make_article(
            article_id=UUID(f"00000000-0000-0000-0000-00000000000{i}"),
            url_fingerprint=f"fp-{i:02d}",
        )
        for i in range(1, 8)
    ]

    result = batch_articles(
        articles,
        title_similarity_threshold=_THRESHOLD,
        grouping_algorithm_version=_ALGORITHM_VERSION,
    )

    assert len(result.batches) == 1
    assert result.batches[0].article_ids == [a.id for a in articles[:5]]
    assert result.carried_forward_ids == [articles[5].id, articles[6].id]


def test_four_similar_and_two_dissimilar_articles() -> None:
    similar = [
        _make_article(
            article_id=UUID(f"10000000-0000-0000-0000-00000000000{i}"),
            title=_SIMILAR_TITLE,
            url_fingerprint=f"sim-{i}",
        )
        for i in range(1, 5)
    ]
    dissimilar = [
        _make_article(
            article_id=UUID("20000000-0000-0000-0000-000000000001"),
            title=_DISSIMILAR_TITLE,
            url_fingerprint="diff-1",
        ),
        _make_article(
            article_id=UUID("20000000-0000-0000-0000-000000000002"),
            title="Weather Forecast Shows Rain Tomorrow",
            url_fingerprint="diff-2",
        ),
    ]
    articles = similar + dissimilar

    result = batch_articles(
        articles,
        title_similarity_threshold=_THRESHOLD,
        grouping_algorithm_version=_ALGORITHM_VERSION,
    )

    assert len(result.batches) == 1
    assert result.batches[0].article_ids == [a.id for a in similar]
    assert result.carried_forward_ids == [dissimilar[0].id, dissimilar[1].id]


def test_different_languages_are_not_batched_together() -> None:
    articles = [
        _make_article(
            article_id=UUID("30000000-0000-0000-0000-000000000001"),
            url_fingerprint="en-1",
            language="en",
        ),
        _make_article(
            article_id=UUID("30000000-0000-0000-0000-000000000002"),
            url_fingerprint="fr-1",
            language="fr",
        ),
        _make_article(
            article_id=UUID("30000000-0000-0000-0000-000000000003"),
            url_fingerprint="en-2",
            language="en",
        ),
        _make_article(
            article_id=UUID("30000000-0000-0000-0000-000000000004"),
            url_fingerprint="fr-2",
            language="fr",
        ),
        _make_article(
            article_id=UUID("30000000-0000-0000-0000-000000000005"),
            url_fingerprint="en-3",
            language="en",
        ),
    ]

    result = batch_articles(
        articles,
        title_similarity_threshold=_THRESHOLD,
        grouping_algorithm_version=_ALGORITHM_VERSION,
    )

    assert len(result.batches) == 1
    en_ids = {a.id for a in articles if a.language == "en"}
    fr_ids = {a.id for a in articles if a.language == "fr"}
    batched_ids = set(result.batches[0].article_ids)
    assert batched_ids == en_ids
    assert set(result.carried_forward_ids) == fr_ids


def test_language_none_forms_its_own_partition() -> None:
    none_lang = [
        _make_article(
            article_id=UUID("40000000-0000-0000-0000-000000000001"),
            url_fingerprint="none-1",
            language=None,
        ),
        _make_article(
            article_id=UUID("40000000-0000-0000-0000-000000000002"),
            url_fingerprint="none-2",
            language=None,
        ),
        _make_article(
            article_id=UUID("40000000-0000-0000-0000-000000000003"),
            url_fingerprint="none-3",
            language=None,
        ),
    ]

    result = batch_articles(
        none_lang,
        title_similarity_threshold=_THRESHOLD,
        grouping_algorithm_version=_ALGORITHM_VERSION,
    )

    assert len(result.batches) == 1
    assert result.batches[0].article_ids == [a.id for a in none_lang]
    assert result.carried_forward_ids == []


def test_batch_articles_is_deterministic() -> None:
    articles = [
        _make_article(
            article_id=UUID(f"50000000-0000-0000-0000-00000000000{i}"),
            title=_SIMILAR_TITLE if i <= 4 else _NEAR_SIMILAR_TITLE,
            url_fingerprint=f"det-{i}",
            published_at=datetime(2026, 7, 13, i, 0, tzinfo=UTC),
        )
        for i in range(1, 6)
    ]

    first = batch_articles(
        articles,
        title_similarity_threshold=_THRESHOLD,
        grouping_algorithm_version=_ALGORITHM_VERSION,
    )
    second = batch_articles(
        articles,
        title_similarity_threshold=_THRESHOLD,
        grouping_algorithm_version=_ALGORITHM_VERSION,
    )

    assert [_batch_fields(batch) for batch in first.batches] == [
        _batch_fields(batch) for batch in second.batches
    ]
    assert first.carried_forward_ids == second.carried_forward_ids


def test_empty_titles_are_not_spuriously_batched() -> None:
    articles = [
        _make_article(
            article_id=UUID("60000000-0000-0000-0000-000000000001"),
            title="",
            url_fingerprint="empty-1",
        ),
        _make_article(
            article_id=UUID("60000000-0000-0000-0000-000000000002"),
            title="",
            url_fingerprint="empty-2",
        ),
    ]

    result = batch_articles(
        articles,
        title_similarity_threshold=_THRESHOLD,
        grouping_algorithm_version=_ALGORITHM_VERSION,
    )

    assert result.batches == []
    assert result.carried_forward_ids == [articles[0].id, articles[1].id]


def test_exactly_three_similar_articles_form_one_batch() -> None:
    articles = [
        _make_article(
            article_id=UUID(f"70000000-0000-0000-0000-00000000000{i}"),
            url_fingerprint=f"three-{i}",
        )
        for i in range(1, 4)
    ]

    result = batch_articles(
        articles,
        title_similarity_threshold=_THRESHOLD,
        grouping_algorithm_version=_ALGORITHM_VERSION,
    )

    assert len(result.batches) == 1
    assert result.batches[0].article_ids == [a.id for a in articles]
    assert result.carried_forward_ids == []
    assert result.batches[0].grouping_method == GroupingMethod.TITLE_TOKEN_JACCARD
    assert result.batches[0].embedding_model == "none"


def test_one_or_two_articles_are_carried_forward() -> None:
    one = [
        _make_article(
            article_id=UUID("80000000-0000-0000-0000-000000000001"),
            url_fingerprint="solo-1",
        )
    ]
    two = [
        _make_article(
            article_id=UUID("80000000-0000-0000-0000-000000000002"),
            url_fingerprint="pair-1",
        ),
        _make_article(
            article_id=UUID("80000000-0000-0000-0000-000000000003"),
            url_fingerprint="pair-2",
        ),
    ]

    one_result = batch_articles(
        one,
        title_similarity_threshold=_THRESHOLD,
        grouping_algorithm_version=_ALGORITHM_VERSION,
    )
    two_result = batch_articles(
        two,
        title_similarity_threshold=_THRESHOLD,
        grouping_algorithm_version=_ALGORITHM_VERSION,
    )

    assert one_result.batches == []
    assert one_result.carried_forward_ids == [one[0].id]
    assert two_result.batches == []
    assert two_result.carried_forward_ids == [two[0].id, two[1].id]


def test_no_article_assigned_to_more_than_one_batch() -> None:
    articles = [
        _make_article(
            article_id=UUID(f"90000000-0000-0000-0000-00000000000{i}"),
            title=_SIMILAR_TITLE if i % 2 == 1 else _NEAR_SIMILAR_TITLE,
            url_fingerprint=f"mix-{i:02d}",
            language="en" if i <= 6 else "de",
        )
        for i in range(1, 9)
    ]

    result = batch_articles(
        articles,
        title_similarity_threshold=_THRESHOLD,
        grouping_algorithm_version=_ALGORITHM_VERSION,
    )

    all_batched_ids: list[UUID] = []
    for batch in result.batches:
        all_batched_ids.extend(batch.article_ids)

    assert len(all_batched_ids) == len(set(all_batched_ids))
    assert set(all_batched_ids).isdisjoint(set(result.carried_forward_ids))
    assert len(all_batched_ids) + len(result.carried_forward_ids) == len(articles)
