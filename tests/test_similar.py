"""The similarity test: 80 percent of the words, and no changed number, negation or opposite."""

import pytest

from cairnkit.similar import analyze, similar_pairs, similarity


def sim(a, b):
    return similarity(analyze(a), analyze(b))


LONG = "Branch main is rebased on master; lint and tests pass, and the build is not blocked by CI"


def test_the_same_words_are_exact():
    assert sim("Deploys need a clean tree.", "deploys NEED a clean tree") == 1.0


def test_an_ordinary_word_change_is_similar():
    assert sim(LONG, LONG.replace("lint", "style")) is not None


@pytest.mark.parametrize(
    "other",
    [
        LONG.replace("is rebased", "is not rebased"),  # a second "not" in a text that has one
        LONG.replace("tests pass", "tests never pass"),
        LONG.replace("is not blocked", "is blocked"),  # one "not" less
        LONG.replace("master;", "master 2;"),
    ],
)
def test_a_changed_count_of_a_number_or_negation_is_not_similar(other):
    assert sim(LONG, other) is None


def test_a_repeated_number_that_changes_count_is_not_similar():
    a = "Retry 3 times, wait 3 seconds, then stop and report the failure to the job owner"
    assert sim(a, a.replace("then stop", "3 then stop")) is None


def test_pairs_scan_applies_the_same_guard():
    words = {
        "a": analyze(LONG),
        "b": analyze(LONG.replace("is rebased", "is not rebased")),
        "c": analyze(LONG.replace("lint", "style")),
    }
    pairs = {(p.a, p.b) for p in similar_pairs(words)}
    assert ("a", "c") in pairs and ("a", "b") not in pairs
