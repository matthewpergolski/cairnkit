"""Defects that real agents reported against 0.3.1. Each one broke the goal in the README."""

from __future__ import annotations

import pytest
from conftest import git
from test_update import head
from test_update import machine as update_machine

from cairnkit import install_source
from cairnkit.cli import main
from cairnkit.hookrun import pre_commit
from cairnkit.memory import Memory
from cairnkit.paths import find_project, merged_checker
from cairnkit.secretscan import find_secrets


def _commit(repo, name):
    (repo / name).write_text("x\n")
    git(repo, "add", name)
    git(repo, "commit", "-qm", name)


def test_a_branch_with_only_a_remote_copy_is_not_merged(repo):
    _commit(repo, "a")
    git(repo, "checkout", "-qb", "work")
    _commit(repo, "b")
    git(repo, "update-ref", "refs/remotes/origin/work", "HEAD")
    git(repo, "checkout", "-q", "-")
    git(repo, "branch", "-qD", "work")
    assert merged_checker(repo)("work") is False


def test_a_branch_in_no_ref_reads_as_ended(repo):
    _commit(repo, "a")
    assert merged_checker(repo)("gone") is True


def test_a_squash_merged_branch_with_a_local_copy_reads_as_merged(repo):
    _commit(repo, "a")
    base = git(repo, "branch", "--show-current").strip()
    git(repo, "checkout", "-qb", "work")
    _commit(repo, "b")
    _commit(repo, "c")
    git(repo, "checkout", "-q", base)
    git(repo, "merge", "-q", "--squash", "work")
    git(repo, "commit", "-qm", "squash")
    assert merged_checker(repo)("work") is True


def test_an_open_branch_is_not_merged(repo):
    _commit(repo, "a")
    base = git(repo, "branch", "--show-current").strip()
    git(repo, "checkout", "-qb", "work")
    _commit(repo, "b")
    git(repo, "checkout", "-q", base)
    assert merged_checker(repo)("work") is False


def test_a_memory_problem_does_not_stop_a_commit(mem, repo):
    facts = mem / "facts" / "main.jsonl"
    facts.parent.mkdir(exist_ok=True)
    with facts.open("a") as fh:
        fh.write("not json\n")
    assert pre_commit(find_project(), None) == 0


def test_a_commit_of_the_memory_link_is_still_refused(mem, repo, capsys):
    git(repo, "add", "-f", "memory-bank")
    assert pre_commit(find_project(), None) == 1
    assert "private memory" in capsys.readouterr().err


def test_a_held_by_file_on_another_branch_is_not_a_problem(mem, repo, capsys):
    _commit(repo, "a")
    base = git(repo, "branch", "--show-current").strip()
    git(repo, "checkout", "-qb", "work")
    _commit(repo, "rules.md")
    assert main(["add", "A rule.", "--area", "x", "--basis", "told", "--source", "session:1"]) == 0
    fact = capsys.readouterr().out.strip().split()[-1]
    assert (
        main(["change", fact, "--status", "promoted", "--held-by", "rules.md", "--reason", "moved"])
        == 0
    )
    git(repo, "checkout", "-q", base)
    capsys.readouterr()
    assert main(["check", "--strict"]) == 0


@pytest.mark.parametrize(
    "text",
    [
        "INVITE_CODE=abc123def",
        "export HOST_CODE=9f8e7d6c",
        "CRON_SECRET=hunter2hunter2",
        "MY_API_KEY: abcdef123456",
        "STRIPE_KEY=rk_live_abcdefghijklmnop",
        "rk_live_abcdefghijklmnop1234",
        "sk_test_abcdefghijklmnop1234",
        "Authorization: Bearer abcdefghijklmnop123456",
        "open https://example.com/join?k=abcd1234ef",
        "https://example.com/x?a=1&token=abcd1234ef",
    ],
)
def test_common_secret_shapes_are_found(text):
    assert find_secrets(text)


@pytest.mark.parametrize(
    "text",
    [
        "EXIT_CODE=failed in the deploy step",
        "STATUS_CODE=500000 is not a real code",
        "Set CRON_SECRET=$CRON_SECRET in the shell",
        "Use API_KEY=<your-key> from the vault",
        "PUBLIC_KEY=abcdef123456 is safe to print",
        "the bearer token expired on Tuesday afternoon",
        "see https://example.com/page?page=200000",
    ],
)
def test_ordinary_text_is_not_a_secret(text):
    assert not find_secrets(text)


def test_check_warns_about_a_secret_in_notes(mem, capsys):
    notes = mem / "notes"
    notes.mkdir(exist_ok=True)
    (notes / "status.md").write_text("Token: CRON_SECRET=hunter2hunter2\n")
    assert main(["check"]) == 0
    assert "status.md" in capsys.readouterr().out


def test_search_takes_several_words_with_no_quotes(mem, capsys):
    add = ["--area", "x", "--basis", "seen", "--source", "session:1"]
    assert main(["add", "The deploy needs a full pool.", *add]) == 0
    capsys.readouterr()
    assert main(["search", "deploy", "pool"]) == 0
    assert "full pool" in capsys.readouterr().out


def test_a_rule_with_a_summary_is_written(mem, capsys):
    add = ["--area", "x", "--basis", "told", "--source", "session:1", "--kind", "rule"]
    assert main(["add", "Never force push.", "--summary", "No force.", *add]) == 0
    captured = capsys.readouterr()
    assert "summary" in captured.out + captured.err
    states = Memory.open(find_project(), None).states.values()
    assert [s.get("summary") for s in states if s["text"] == "Never force push."] == [None]


def test_add_works_with_no_area(mem, capsys):
    assert main(["add", "A fact.", "--basis", "seen", "--source", "session:1"]) == 0
    states = Memory.open(find_project(), None).states.values()
    assert [s["area"] for s in states if s["text"] == "A fact."] == ["general"]


def test_until_merged_with_an_unknown_branch_says_so(mem, repo, capsys):
    add = ["--area", "x", "--basis", "seen", "--source", "session:1"]
    assert main(["add", "Note.", "--until-merged", "not-yet", *add]) == 0
    assert "not-yet" in capsys.readouterr().out


ADD = ["--area", "x", "--basis", "seen", "--source", "session:1"]


def _states(text):
    states = Memory.open(find_project(), None).states.values()
    return [s for s in states if s.get("text") == text]


def _add_out(capsys, *args):
    capsys.readouterr()
    assert main(["add", *args, *ADD]) == 0
    return capsys.readouterr().out


def _load(capsys):
    capsys.readouterr()
    assert main(["load", "--budget", "0"]) == 0
    return capsys.readouterr().out


def test_until_merged_with_a_tag_says_no_branch_exists(mem, repo, capsys):
    git(repo, "tag", "v1")
    assert "no branch v1" in _add_out(capsys, "Note.", "--until-merged", "v1")


def test_until_merged_head_means_this_branch(mem, repo, capsys):
    git(repo, "switch", "-qc", "work")
    out = _add_out(capsys, "Note.", "--until-merged", "HEAD")
    assert "no branch" not in out
    assert _states("Note.")[0]["until_branch_merged"] == "work"
    assert "Note." in _load(capsys)


def test_until_merged_head_on_a_detached_head_is_refused(mem, repo, capsys):
    git(repo, "checkout", "-q", "--detach")
    assert main(["add", "Note.", "--until-merged", "HEAD", *ADD]) == 1
    assert "detached" in capsys.readouterr().err


def test_until_merged_with_a_remote_copy_gives_no_warning(mem, repo, capsys):
    git(repo, "update-ref", "refs/remotes/origin/far", "HEAD")
    out = _add_out(capsys, "Note.", "--until-merged", "far")
    assert "reads as ended" not in out and "no branch" not in out
    assert not merged_checker(repo)("far")


def test_expires_implies_short_term(mem, repo, capsys):
    git(repo, "switch", "-qc", "work")
    _add_out(capsys, "Old date.", "--expires", "2020-01-01")
    _add_out(capsys, "Far date.", "--expires", "2099-01-01")
    assert _states("Old date.")[0]["scope"] == "short"
    assert _states("Far date.")[0]["scope"] == "short"
    out = _load(capsys)
    assert "Old date." not in out
    assert "Far date." in out


def test_a_short_note_on_the_default_branch_says_it_has_no_end_event(mem, capsys):
    out = _add_out(capsys, "Note.", "--short")
    fact = out.strip().split()[-1]
    lines = [line for line in out.splitlines() if "no end event" in line]
    assert len(lines) == 1
    assert "default branch" in lines[0]
    assert f"memory change {fact} --status expired" in lines[0]


def test_a_short_note_on_a_detached_head_says_it_has_no_end_event(mem, repo, capsys):
    git(repo, "checkout", "-q", "--detach")
    assert "detached HEAD" in _add_out(capsys, "Note.", "--short")


def test_a_short_note_in_a_plain_folder_says_it_has_no_end_event(tmp_path, monkeypatch, capsys):
    home = tmp_path / "home"
    (home / "plain").mkdir(parents=True)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.chdir(home / "plain")
    assert main(["init", "--no-default-rules"]) == 0
    assert "no end event" in _add_out(capsys, "Note.", "--short")


@pytest.mark.parametrize("extra", [["--short"], ["--until-merged"]])
def test_a_short_note_on_a_work_branch_needs_no_such_line(mem, repo, capsys, extra):
    git(repo, "switch", "-qc", "work")
    assert "no end event" not in _add_out(capsys, "Note.", *extra)


def test_a_note_with_a_date_needs_no_such_line(mem, capsys):
    assert "no end event" not in _add_out(capsys, "Note.", "--short", "--expires", "2099-01-01")


NEAR = "The deploy script needs a full database pool to pass."
NEARER = "The deploy script needs a full database pool to pass today."


def test_a_near_repeat_says_that_auto_tidy_can_supersede_the_older_fact(mem, capsys):
    _add_out(capsys, NEAR)
    out = _add_out(capsys, NEARER)
    assert "similar to" in out
    assert "Both stay active" not in out
    assert "auto-tidy" in out


def test_a_near_repeat_of_a_stated_fact_says_that_both_stay(mem, capsys):
    capsys.readouterr()
    assert main(["add", NEAR, "--area", "x", "--basis", "told", "--source", "session:1"]) == 0
    out = _add_out(capsys, NEARER)
    assert "Both stay active" in out
    assert "auto-tidy" not in out


machine = update_machine

URL_RECEIPT = (
    '[tool]\nrequirements = [{{ name = "cairnkit", git = "{url}" }}]\n'
    'entrypoints = [{{ name = "memory", install-path = "{entry}" }}]\n'
)


@pytest.fixture
def channels(machine, monkeypatch):
    """A git source with a tag at 0.2.0 and a dev branch at 0.3.0, as an install of dev."""
    source = machine.source
    git(source, "tag", "v0.2.0")
    machine.stable = head(source)
    git(source, "switch", "-qc", "dev")
    (source / "pyproject.toml").write_text('[project]\nname = "cairnkit"\nversion = "0.3.0"\n')
    git(source, "commit", "-qam", "dev work")
    machine.dev = head(source)
    git(source, "switch", "-q", "main")
    machine.url = source.as_uri()
    (machine.env / "uv-receipt.toml").write_text(
        URL_RECEIPT.format(url=machine.url, entry=machine.bin / "memory")
    )
    machine.on = lambda version: (
        monkeypatch.setattr(install_source, "current_version", lambda: version),
        monkeypatch.setenv("FAKE_NEW_VERSION", version),
    )
    machine.saved = lambda: (
        install_source._channel_path().read_text().strip()
        if install_source._channel_path().exists()
        else None
    )
    install_source.set_channel("dev")
    machine.on("0.3.0")
    install_source.write_record(install_source.parse(machine.url), machine.dev, "0.3.0", None)
    return machine


@pytest.mark.parametrize("mode", ["--check", "--dry-run"])
def test_a_look_at_another_channel_reads_that_channel_and_changes_nothing(channels, capsys, mode):
    before = channels.record()
    assert main(["update", "--channel", "stable", mode]) == 0
    out = capsys.readouterr().out
    assert channels.stable[:7] in out
    assert "0.2.0" in out
    assert "Up to date" not in out
    assert channels.saved() == "dev"
    assert channels.record() == before
    assert channels.uv_calls() == []
    assert not install_source._cache_path().exists()


def test_a_check_of_another_channel_tells_the_command_to_switch(channels, capsys):
    assert main(["update", "--channel", "stable", "--check"]) == 0
    assert "memory update --channel stable" in capsys.readouterr().out


def test_dev_to_a_lower_stable_version_and_back(channels, monkeypatch, capsys):
    monkeypatch.setenv("FAKE_NEW_VERSION", "0.2.0")
    assert main(["update", "--channel", "stable"]) == 0
    assert "memory updated" in capsys.readouterr().out
    assert channels.saved() == "stable"
    record = channels.record()
    assert (record["commit"], record["version"]) == (channels.stable, "0.2.0")

    channels.on("0.2.0")
    assert main(["update"]) == 0
    assert "up to date" in capsys.readouterr().out.lower()

    assert main(["update", "--channel", "dev", "--check"]) == 0
    assert channels.dev[:7] in capsys.readouterr().out
    assert channels.saved() == "stable"

    monkeypatch.setenv("FAKE_NEW_VERSION", "0.3.0")
    assert main(["update", "--channel", "dev"]) == 0
    assert channels.saved() == "dev"
    record = channels.record()
    assert (record["commit"], record["version"]) == (channels.dev, "0.3.0")


def test_a_failed_switch_keeps_the_old_channel(channels, monkeypatch, capsys):
    monkeypatch.setenv("FAKE_UV_BUILD_FAIL", "1")
    assert main(["update", "--channel", "stable"]) == 1
    assert channels.saved() == "dev"
    assert channels.record()["commit"] == channels.dev


def test_a_switch_to_the_same_commit_saves_the_channel_and_installs_nothing(channels, capsys):
    install_source.write_record(install_source.parse(channels.url), channels.stable, "0.3.0", None)
    assert main(["update", "--channel", "stable"]) == 0
    assert channels.saved() == "stable"
    assert channels.uv_calls() == []


def test_an_install_pinned_to_dev_stays_on_dev_after_an_update(machine, monkeypatch, capsys):
    source = machine.source
    git(source, "tag", "v0.2.0")
    git(source, "switch", "-qc", "dev")
    git(source, "commit", "-q", "--allow-empty", "-m", "dev work")
    git(source, "switch", "-q", "main")
    (machine.env / "uv-receipt.toml").write_text(
        URL_RECEIPT.format(url=f"{source.as_uri()}@dev", entry=machine.bin / "memory")
    )
    assert main(["update"]) == 0
    assert machine.record()["commit"] == git(source, "rev-parse", "dev").strip()
    assert install_source.channel() == "dev"


@pytest.mark.parametrize("extra", [[], ["--check"], ["--dry-run"]])
def test_a_channel_on_a_folder_source_is_refused_and_not_saved(machine, capsys, extra):
    assert main(["update", "--channel", "dev", *extra]) == 1
    err = capsys.readouterr().err
    assert "folder" in err and "--channel" in err
    assert not install_source._channel_path().exists()
    assert machine.uv_calls() == []
