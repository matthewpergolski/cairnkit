"""A mask replaces the value that looks secret, and the rest of the text stays readable."""

from __future__ import annotations

import pytest

from cairnkit.secretscan import find_secrets, mask, mask_record, readable

KEY = "-----BEGIN RSA PRIVATE KEY-----\nabc123\n-----END RSA PRIVATE KEY-----"


@pytest.mark.parametrize(
    ("text", "value", "kept"),
    [
        ("login password=hunter2hunter2 fails", "hunter2hunter2", "login password="),
        ('use token: "abc 123 def" here', "abc 123 def", "use token"),
        ("run with ghp_abcdefghijklmnopqrstuvwxyz0123456789 today", "ghp_", "run with"),
        ("call ?token=abc123def now", "abc123def", "call ?token="),
        ("db postgres://app:s3cretpw99@db/app is up", "s3cretpw99", "db postgres://app:"),
        ("send Bearer abcdefghijklmnop1234 first", "abcdefghijklmnop1234", "send Bearer"),
        ("the password is hunter2hunter2 today", "hunter2hunter2", "the password is"),
        (f"key {KEY} ends here", "abc123", "key "),
        (f"cut {KEY[:40]}", "abc123", "cut "),
    ],
)
def test_the_value_goes_and_the_rest_stays(text, value, kept):
    out = mask(text)
    assert value not in out
    assert kept in out
    assert "[secret: " in out
    assert not find_secrets(out)


def test_a_clean_text_is_the_same_text():
    text = "the max_tokens=4096 limit holds on Friday"
    assert mask(text) == text


def test_a_mask_of_a_mask_is_the_same():
    once = mask("login password=hunter2hunter2 and ghp_abcdefghijklmnopqrstuvwxyz0123456789")
    assert mask(once) == once
    assert find_secrets(once) == []


@pytest.mark.parametrize(
    "text",
    [
        "login password=[secret: assigned secret] fails",
        "call ?token=[secret: secret in URL] now",
        "a cut text ends in [secret: assigned sec",
    ],
)
def test_a_mask_is_no_secret_when_it_is_copied(text):
    assert find_secrets(text) == []


def test_a_mask_cannot_carry_a_real_token():
    token = "ghp_abcdefghijklmnopqrstuvwxyz0123456789"
    assert find_secrets(f"[secret: {token}]")
    assert token not in mask(f"[secret: {token}]")


def test_each_free_text_field_of_a_record_is_masked():
    record = {
        "id": "f-20261001-aaaa",
        "kind": "fact",
        "text": "a password=hunter2hunter2",
        "summary": "b password=hunter2hunter2",
        "source": "note:password=hunter2hunter2",
        "tags": ["password=hunter2hunter2"],
        "history": [{"id": "f-20261001-aaaa", "reason": "c password=hunter2hunter2"}],
    }
    out = mask_record(record)
    assert "hunter2" not in str(out)
    assert out["id"] == "f-20261001-aaaa"
    assert out["text"].startswith("a password=")
    assert "hunter2" in record["text"]


@pytest.mark.parametrize(
    ("text", "gone", "kept"),
    [
        ("the value is plain words here", "", "the value is plain words here"),
        ("run ghp_abcdefghijklm then stop", "ghp_", "run"),
        ("password=hunter2hunter2 and more", "hunter2", "and more"),
        ("use token abc123def456 today", "abc123", "today"),
        ("see aVeryRandomLookingWord now", "aVery", "now"),
    ],
)
def test_readable_keeps_only_plain_words(text, gone, kept):
    out = readable(text)
    assert kept in out
    if gone:
        assert gone not in out
