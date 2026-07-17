from pathlib import Path

import pytest

from src.gazetteer import Gazetteer

DATA = Path(__file__).resolve().parents[1] / "data" / "symbols.csv"


@pytest.fixture(scope="module")
def gz():
    return Gazetteer.load(DATA)


def test_cashtag_resolves(gz):
    assert gz.candidate_symbols("$AAPL is flying") == ["AAPL"]


def test_alias_resolves(gz):
    assert "RELIANCE.NS" in gz.candidate_symbols("RIL looks strong")
    assert "RELIANCE.NS" in gz.candidate_symbols("Reliance results out")


def test_multiword_alias(gz):
    assert "^NSEBANK" in gz.candidate_symbols("Bank Nifty broke resistance")


def test_ambiguous_word_ignored_bare(gz):
    # "vi" is an alias for Vodafone Idea but also a common word -> only via cashtag
    assert "IDEA.NS" not in gz.candidate_symbols("I use the vi editor")
    assert "IDEA.NS" in gz.candidate_symbols("$VI is moving")


def test_no_false_positive_on_plain_text(gz):
    assert gz.candidate_symbols("good morning everyone, hope you are well") == []


def test_is_valid(gz):
    assert gz.is_valid("RELIANCE.NS")
    assert not gz.is_valid("TOTALLYFAKE.NS")


def test_dedup(gz):
    syms = gz.candidate_symbols("Reliance, RIL, $RELIANCE all the same")
    assert syms.count("RELIANCE.NS") == 1
