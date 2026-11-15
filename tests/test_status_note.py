"""What the load says about the status note. It only reads: nothing ends because of it."""

import re

from conftest import git
from test_hook_size import fill, run_hook

from cairnkit.cli import main
from cairnkit.load import NOTE_WORDS


def commit(repo, message: str) -> str:
    git(repo, "commit", "-q", "--allow-empty", "-m", message)
    return git(repo, "rev-parse", "--short", "HEAD").strip()


def setup(repo, capsys) -> None:
    assert main(["init", "--preset", "none"]) == 0
    capsys.readouterr()


def status(repo, text: str) -> None:
    (repo / "memory-bank" / "notes" / "status.md").write_text(f"# Status\n{text}\n")


def heading(capsys) -> str:
    capsys.readouterr()
    assert main(["load"]) == 0
    return next(x for x in capsys.readouterr().out.splitlines() if x.startswith("## Status"))


def test_the_heading_counts_commits_past_the_commit_it_names(repo, capsys):
    setup(repo, capsys)
    named = commit(repo, "one")
    commit(repo, "two")
    commit(repo, "three")
    status(repo, f"All checks pass at `{named}`.")
    assert "HEAD is 2 commit(s) past the newest commit it names" in heading(capsys)


def test_old_commits_cited_as_history_do_not_count(repo, capsys):
    setup(repo, capsys)
    old = commit(repo, "one")
    new = commit(repo, "two")
    status(repo, f"Sections came in `{old}`. All checks pass at `{new}`.")
    assert heading(capsys) == "## Status (notes/status.md)"


def test_no_commit_named_means_no_count(repo, capsys):
    setup(repo, capsys)
    commit(repo, "one")
    status(repo, "PR 96 merged. deadbeef is not a commit here, and neither is 1234567.")
    assert heading(capsys) == "## Status (notes/status.md)"


def test_the_check_stays_silent_about_it_and_no_fact_ends(repo, capsys):
    setup(repo, capsys)
    assert (
        main(
            [
                "add",
                "A fact.",
                "--kind",
                "lesson",
                "--area",
                "x",
                "--basis",
                "seen",
                "--source",
                "session:2026-11-01",
            ]
        )
        == 0
    )
    named = commit(repo, "one")
    commit(repo, "two")
    status(repo, f"At `{named}`.")
    capsys.readouterr()
    assert main(["check", "--strict"]) == 0
    out = capsys.readouterr().out
    assert "past the newest" not in out
    assert main(["load"]) == 0
    assert "A fact." in capsys.readouterr().out


def test_a_long_note_says_how_much_was_clipped(repo, capsys):
    setup(repo, capsys)
    status(repo, "\n".join(f"Line {n}." for n in range(1, 13)))
    capsys.readouterr()
    assert main(["load"]) == 0
    out = capsys.readouterr().out
    assert "Line 8." in out and "Line 9." not in out
    assert "8 of 12 lines shown" in out
    assert "notes/status.md" in out[out.index("8 of 12") :]


def test_a_short_note_says_nothing_about_clipping(repo, capsys):
    setup(repo, capsys)
    status(repo, "One line.")
    capsys.readouterr()
    assert main(["load"]) == 0
    assert "lines shown" not in capsys.readouterr().out


def facts_shown(text: str) -> int:
    return int(re.search(r"(\d+) fact\(s\) shown", text)[1])


def test_a_long_status_leaves_the_hook_room_for_facts_and_names_the_full_note(repo, mem):
    """A field load spent 740 of 2,112 words on the status, and the hook cut 106 facts."""
    fill(mem, 200, 4, 0)
    line = " ".join(["the release waits on the queue migration"] * 20)
    (mem / "notes" / "status.md").write_text("".join(f"- {n}: {line}\n" for n in range(8)))
    long = run_hook(repo, "session-start")
    cap = " ".join(f"- {n}: {line}" for n in range(8)).split()[:NOTE_WORDS]
    (mem / "notes" / "status.md").write_text(" ".join(cap) + "\n")
    short = run_hook(repo, "session-start", session_id="s2")
    status = [
        x.removeprefix("- [status] ") for x in long.splitlines() if x.startswith("- [status]")
    ]
    assert sum(len(x.split()) for x in status[:-1]) <= NOTE_WORDS + 1
    assert status[-1].startswith(f"({NOTE_WORDS} of ") and "notes/status.md" in status[-1]
    assert facts_shown(long) >= facts_shown(short) - 1, "the status past the cap costs no fact"
