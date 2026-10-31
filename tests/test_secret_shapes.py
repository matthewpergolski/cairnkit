"""The shape of a value decides, so ordinary notes pass and real secrets stay refused."""

from __future__ import annotations

import pytest

from cairnkit.secretscan import find_secrets


@pytest.mark.parametrize(
    "text",
    [
        "PRIMARY_KEY=user_id",
        "SORT_KEY=created_at",
        "FOREIGN_KEY=orders.user_id",
        "pwd=/home/app",
        "password=./secrets/db.txt",
        'secret = os.environ["SECRET"]',
        "password = getpass()",
        "API_KEY=settings.API_KEY",
        "token: process.env.API_TOKEN",
        "GITHUB_TOKEN=secrets.GITHUB_TOKEN",
        "SSH_PUBLIC_KEY=ssh-ed25519",
        "open https://example.com/cb?code=abcdef",
        "postgres://user:pass@localhost",
        "postgres://user:password@localhost/db",
        "redis://admin:changeme@127.0.0.1",
        "postgres://user:$DB_PASSWORD@localhost",
        "postgres://user:${DB_PASSWORD}@localhost",
        "postgres://user:<password>@localhost",
        "password=changeme",
        "API_KEY=your_api_key_here",
        "Bearer tokens-must-be-rotated-every-30-days",
        "Send Bearer tokens-must-be-rotated-every-30-days.",
        "sk-learn-compatibility-layer-breaks-on-numpy2",
    ],
)
def test_ordinary_text_is_not_refused(text):
    assert find_secrets(text) == []


@pytest.mark.parametrize(
    "text",
    [
        "PASSWORD=hunter2hunter2",
        "password: Xy9kLm2Qz",
        "password=dragonfly",
        "DB_PASSWORD=correcthorse",
        "password=hunter_two_three",
        "pwd=/Ab3dEfG9/hIj",
        "pwd=/wJalrXUtnFEMI/K7MDENG",
        "secret=abc.def1ghi",
        "password=hunter2(abc",
        "secret=supersecretvalue",
        "API_KEY=a1b2c3d4e5",
        "SECRET_KEY=django-insecure-abc123xyz",
        "AWS_SECRET_ACCESS_KEY=wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY",
        "DEPLOY_KEY=9f8e7d6c5b",
        "NEXT_PUBLIC_API_TOKEN=abc123def456",
        "postgres://admin:hunter2@db.internal",
        "postgres://user:dragonfly@localhost",
        "postgres://user:S3cr3t@h",
        "Bearer abcdefghijklmnopqrstuvwx",
        "Bearer abc-def-ghi-jkl-mno-pqrs-tuv",
        "Bearer 1234-5678-9012-3456",
        "sk-proj-Ab3dEf9hIj2kLm4nOp6q",
        "sk-abcdefghijklmnopqrstuvwx",
        "sk-ant-api03-abcDEF123456ghiJKL",
        "sk-abcd-efgh-ijkl-mnop-qrst",
        "https://example.com/?token=abcdefgh",
        "https://example.com/?code=4/0AX4XfWh",
        "https://example.com/?sig=abc123def",
        "https://example.com/?api_key=abcdefgh",
    ],
)
def test_a_real_secret_is_still_refused(text):
    assert find_secrets(text)


def test_a_harmless_value_does_not_hide_a_real_one_later_in_the_text():
    assert find_secrets("pwd=/home/app and later password=hunter2hunter2")
    assert find_secrets("Bearer tokens-must-be-rotated-every-30-days, Bearer abc123def456ghi789")
    assert find_secrets("postgres://user:pass@localhost postgres://user:hunter2@db")


@pytest.mark.parametrize(
    "text",
    [
        "password=correct.horse.battery",
        "Bearer correct-horse-battery-staple-word",
        "sk-correct-horse-battery-staple-word",
        "DEPLOY_KEY=dragonflies",
        "https://example.com/?code=dragonfly",
        "postgres://user:password@db.internal",
    ],
)
def test_the_accepted_misses_are_these_word_shaped_values(text):
    """The price of the shape test. A change here moves the line between the two risks."""
    assert find_secrets(text) == []
