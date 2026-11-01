"""The shape of a value decides, so ordinary notes pass and real secrets stay refused."""

from __future__ import annotations

from pathlib import Path

import pytest

from cairnkit.secretscan import find_secrets, match_shapes

CORPUS = Path(__file__).parent / "test_goal_fixes.py"


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
        "passphrase=correct.horse.battery",
        "token=abcdef123456",
        "DEPLOY_KEY=dragonflies",
        "SSH_KEY=dragonflies",
        "deploy_key=dragonflies",
        "db_password=dragonflies",
        "HTTP_PASSWORD=dragonflies",
        "spring.datasource.password=dragonflies",
        '{"password": "dragonflies"}',
        'password="correct horse battery"',
        "mysql --password hunter2",
        "curl --token=abcdef123456",
    ],
)
def test_a_value_behind_a_secret_label_is_refused(text):
    assert find_secrets(text)


@pytest.mark.parametrize(
    "text",
    [
        "password=settings.DB_PASSWORD",
        "password=config.db.password",
        "password = os.getenv(",
        'token = ENV["TOKEN"]',
        "token=self.token",
        "password=/run/secrets/db_password",
        "SSH_KEY=~/.ssh/id_ed25519",
        "SSL_KEY=server.pem",
        "API_KEY=https://vault.internal/keys",
        "api_key: str",
        "max_tokens=128000",
        "input_tokens: 500000",
        "token_type: bearer",
        "PASSWORD_FILE=hunter2hunter2",
        "CACHE_KEY=user_session",
        "password: required",
    ],
)
def test_a_value_that_is_clearly_not_one_passes(text):
    assert find_secrets(text) == []


@pytest.mark.parametrize(
    "text",
    [
        "the db password is hunter2",
        "password is hunter2.",
        'the password was "swordfish"',
        "the password is 'swordfish'",
        "the password is `swordfish`",
        "the API key is abc123def",
        "the token was abc123def456",
        "the password for staging is hunter2",
        "password changed to hunter2",
        "password is now hunter2",
        "the secret is 12345678",
        "the password is P@ssword!",
    ],
)
def test_a_value_in_prose_is_refused(text):
    assert find_secrets(text)


@pytest.mark.parametrize(
    "text",
    [
        "password is required for login",
        "the password is stored in the vault",
        "password is 8 chars long",
        "the password is 12 characters",
        "the token is valid for 30 days",
        "the token was 30days old",
        "the token is base64",
        "the secret is sha256-hashed",
        "the password is $DB_PASSWORD",
        "the token is process.env.API_TOKEN",
        "the secret is v1.2.3",
    ],
)
def test_english_about_a_password_passes(text):
    assert find_secrets(text) == []


@pytest.mark.parametrize(
    "text",
    [
        "the password is swordfish",
        "the password swordfish opens staging",
        "Bearer correct-horse-battery-staple-word",
        "sk-correct-horse-battery-staple-word",
        "https://example.com/?code=dragonfly",
        "postgres://user:password@db.internal",
        "password=ab1",
        "INVITE_CODE=welcome",
    ],
)
def test_the_remaining_misses_are_these(text):
    """No shape tells these from English or a placeholder. A real value in .env is still found."""
    assert find_secrets(text) == []


def test_the_fast_clue_never_hides_a_shape():
    this_file = Path(__file__).read_text()
    lines = [*this_file.splitlines(), *CORPUS.read_text().splitlines()]
    texts = [line.strip(' ",') for line in lines]
    hits = [text for text in texts if match_shapes(text)]
    assert len(hits) > 40
    assert [text for text in hits if not find_secrets(text)] == []
