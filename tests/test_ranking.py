"""The word ranking of `memory search`, without the command."""

from cairnkit.ranking import query_terms, stem, words


def test_words_drop_filler_and_stem():
    assert words("The Retries, and the EMAILS!") == ["the", "retry", "and", "the", "email"]
    assert query_terms("How are email retries handled again?") == [
        "email",
        "retries",
        "handled",
    ]
    assert query_terms("movie movies") == ["movie"]
    assert query_terms("the of") == ["the", "of"]
    assert query_terms("?!") == []
    assert stem("processes") == "process" and stem("class") == "class" and stem("is") == "is"


def test_stem_keeps_a_word_and_its_plural_together():
    for single, plural in [("box", "boxes"), ("index", "indexes"), ("retry", "retries")]:
        assert stem(plural) == stem(single)
