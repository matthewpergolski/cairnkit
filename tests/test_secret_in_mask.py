"""A real value inside the mask syntax is still a secret: `[secret: X]` hides only a mask name."""

from __future__ import annotations

import pytest
from conftest import make_fact, write_facts

from cairnkit.cli import main
from cairnkit.envsecrets import read_env_values
from cairnkit.paths import find_project
from cairnkit.secretscan import find_secrets, mask

AWS = "AKIAIOSFODNN7EXAMPLE"
SEED = "JBSWY3DPEHPK3PXP"
ADD = ["--area", "x", "--basis", "seen", "--source", "session:1"]


def stored(mem) -> str:
    return "".join(path.read_text() for path in (mem / "facts").glob("*.jsonl"))


@pytest.mark.parametrize(
    "extra",
    [
        ["--tag", f"[secret: {AWS}]"],
        ["--area", "x", "--basis", "seen", "--source", f"doc:see [secret: {AWS}]"],
        ["--tag", "[secret: AWS access key]"],
    ],
    ids=["tag", "source", "mask copy in a tag"],
)
def test_add_refuses_a_value_or_a_mask_in_any_free_field(mem, capsys, extra):
    argv = ["add", "deploy key note", *ADD, *extra]
    assert main(argv) == 1
    captured = capsys.readouterr()
    assert AWS not in captured.out + captured.err
    assert AWS not in stored(mem) and "[secret: " not in stored(mem)


def test_a_reason_with_a_wrapped_value_is_refused(mem, capsys):
    assert main(["add", "old note", *ADD, "--short"]) == 0
    old = capsys.readouterr().out.split()[1]
    argv = ["add", "new note", *ADD, "--supersedes", old, "--reason", f"[secret: {AWS}]"]
    assert main(argv) == 1
    assert main(["keep", old, "--reason", f"[secret: {AWS}]"]) == 1
    assert AWS not in stored(mem)


def test_a_wrapped_env_value_is_refused(repo, mem, capsys):
    (repo / ".env").write_text(f"OTP_SECRET={SEED}\n")
    argv = ["add", "the login seed", "--area", "x", "--basis", "seen"]
    assert main([*argv, "--source", "s:1", "--tag", f"[secret: {SEED}]"]) == 1
    assert SEED not in stored(mem)


def test_check_and_show_find_a_wrapped_value_on_disk(mem, capsys):
    write_facts(mem, [make_fact("f-20261001-aaaa", "deploy key note", tags=[f"[secret: {AWS}]"])])
    assert main(["check"]) != 0
    assert "f-20261001-aaaa" in capsys.readouterr().out
    main(["show", "f-20261001-aaaa"])
    assert AWS not in capsys.readouterr().out


def test_find_secrets_reads_the_name_inside_a_mask():
    assert find_secrets(f"[secret: {AWS}]")
    assert find_secrets(f"the seed is [secret: {AWS}")
    assert find_secrets("login password: [secret: HUNTER2X9Q] works")
    assert find_secrets("a copied [secret: AWS access key] and [secret: hidden text]") == []
    assert find_secrets("a cut text ends in [secret: AWS acc") == []
    assert AWS not in mask(f"tag [secret: {AWS}]")


def test_an_env_mask_reads_as_a_mask_and_its_value_does_not(repo):
    (repo / ".env").write_text(f"OTP_SECRET={SEED}\n")
    known = read_env_values(find_project(repo))
    masked = mask(f"the seed {SEED} is set", known)
    assert masked == "the seed [secret: OTP_SECRET] is set"
    assert find_secrets(masked, known) == []
    assert find_secrets("cut at [secret: OTP_SE", known) == []
    assert find_secrets(f"wrapped [secret: {SEED}]", known)
    assert mask(masked, known) == masked
