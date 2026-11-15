"""The similarity test: 75 percent of the words, with a plural and a stop word ignored."""

import pytest

from cairnkit.similar import analyze, similar_pairs, similarity


def sim(a, b):
    return similarity(analyze(a), analyze(b))


LONG = "Branch main is rebased on master; lint and tests pass, and the build is not blocked by CI"


def test_the_same_words_are_exact():
    assert sim("Deploys need a clean tree.", "deploys NEED a clean tree") == 1.0


def test_an_ordinary_word_change_is_similar():
    assert sim(LONG, LONG.replace("lint", "style")) is not None


def test_a_plural_and_a_stop_word_do_not_count():
    assert sim("rails", "rail") == 1.0
    assert sim("plan A", "plan") == 1.0
    assert sim("The tables are here", "table here") == 1.0


@pytest.mark.parametrize(
    "other",
    [
        LONG.replace("is rebased", "is not rebased"),
        LONG.replace("tests pass", "tests never pass"),
        LONG.replace("master;", "master 2;"),
    ],
)
def test_a_flag_costs_one_look_so_a_negation_or_a_number_is_flagged_too(other):
    assert sim(LONG, other) is not None


def test_pairs_scan_applies_the_same_test():
    words = {
        "a": analyze(LONG),
        "b": analyze("A short text that shares nothing"),
        "c": analyze(LONG.replace("lint", "style")),
    }
    pairs = {frozenset((p.a, p.b)) for p in similar_pairs(words)}
    assert frozenset(("a", "c")) in pairs and frozenset(("a", "b")) not in pairs
