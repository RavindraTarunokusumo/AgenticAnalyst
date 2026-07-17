"""Offline unit tests for pure topic keyword matching."""

from __future__ import annotations

from analyst_engine.topics.matcher import matches


def test_word_boundary_war_does_not_match_warsaw() -> None:
    assert matches(["war"], "Warsaw summit opens") is False
    assert matches(["war"], "War breaks out") is True
    assert matches(["war"], "The war ends") is True


def test_case_insensitive() -> None:
    assert matches(["Iran"], "IRAN nuclear talks") is True
    assert matches(["iran"], "Iran") is True
    assert matches(["NUCLEAR"], "nuclear deal") is True


def test_multi_word_keyword() -> None:
    assert matches(["nuclear talks"], "Geneva nuclear talks collapse") is True
    assert matches(["nuclear talks"], "nuclear weapons talks resume") is False
    assert matches(["nuclear talks"], "prenuclear talks") is False


def test_regex_metacharacters_matched_literally() -> None:
    assert matches(["C++"], "Learning C++ basics") is True
    assert matches(["C++"], "Learning C basics") is False
    assert matches(["AT&T"], "AT&T reports earnings") is True
    assert matches(["AT&T"], "ATT reports earnings") is False
    assert matches(["3.5"], "version 3.5 released") is True
    assert matches(["3.5"], "version 35 released") is False
    assert matches(["a|b"], "choose a|b carefully") is True
    assert matches(["a|b"], "choose a or b carefully") is False
    assert matches([".*"], "use .* as wildcard") is True
    assert matches([".*"], "use anything as wildcard") is False
    assert matches(["(foo)"], "see (foo) here") is True
    assert matches(["(foo)"], "see foo here") is False


def test_none_and_empty_fields() -> None:
    assert matches(["iran"], None) is False
    assert matches(["iran"], "") is False
    assert matches(["iran"], None, "") is False
    assert matches(["iran"], None, "Iran news") is True
    assert matches([], "Iran news") is False
    assert matches([""], "Iran news") is False


def test_matches_any_of_several_fields() -> None:
    assert matches(["tehran"], "Markets rise", "Tehran responds to proposal") is True
    assert matches(["tehran"], "Markets rise", "No match here") is False
    assert matches(["tehran", "iran"], "Quiet day", "Iran border news") is True


def test_non_ascii_keywords() -> None:
    assert matches(["北京"], "访问北京的记者") is True
    assert matches(["北京"], "访问上海的记者") is False
    assert matches(["café"], "A café opens downtown") is True
    assert matches(["café"], "A CAFÉ opens downtown") is True
    assert matches(["café"], "A cafeteria opens") is False
