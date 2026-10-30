import time

from conftest import add_worktree, git, make_fact, write_facts

from cairnkit import load as load_module
from cairnkit.cli import main

NOW = "2026-10-20T12:00:00+00:00"


def load(capsys, *args):
    capsys.readouterr()
    code = main(["load", *args])
    out = capsys.readouterr()
    assert code == 0
    return out.out + out.err


def change(fid, **extra):
    return {
        "type": "change",
        "id": fid,
        "at": "2026-10-05T00:00:00+00:00",
        "writer": "main",
        **extra,
    }


def test_no_memory_warns_and_exits_zero(repo, capsys):
    out = load(capsys)
    assert "not loaded" in out
    assert " ok" not in out


def test_broken_link_warns_and_exits_zero(repo, mem, capsys, tmp_path):
    mem.rename(tmp_path / "moved")
    out = load(capsys)
    assert "not loaded" in out


def test_only_active_facts_are_shown(mem, capsys, monkeypatch):
    monkeypatch.setenv("MEMORY_NOW", NOW)
    write_facts(
        mem,
        [
            make_fact("f-20261001-0001", "Alive fact."),
            make_fact("f-20261001-0002", "Old fact."),
            make_fact("f-20261001-0003", "Wrong fact."),
            make_fact(
                "f-20261001-0004",
                "Expired short fact.",
                scope="short",
                expires_at="2026-10-10T00:00:00+00:00",
            ),
            change(
                "f-20261001-0002", status="superseded", superseded_by="f-20261001-0001", reason="r"
            ),
            change("f-20261001-0003", status="wrong", reason="r"),
        ],
    )
    out = load(capsys)
    assert "Alive fact." in out
    for gone in ("Old fact.", "Wrong fact.", "Expired short fact."):
        assert gone not in out


def test_budget_is_held_and_pinned_always_shown(mem, capsys, monkeypatch):
    monkeypatch.setenv("MEMORY_NOW", NOW)
    facts = [
        make_fact(f"f-20261001-{i:04x}", f"Fact number {i} has six words.") for i in range(200)
    ]
    facts.append(
        make_fact(
            "f-20261001-ffff", "Pinned rule.", pinned=True, learned_at="2025-01-01T00:00:00+00:00"
        )
    )
    write_facts(mem, facts)
    out = load(capsys, "--budget", "60")
    lines = [line for line in out.splitlines() if line.startswith("- [")]
    assert "Pinned rule." in out
    words = sum(len(line.split()) for line in lines)
    assert words <= 60 + 10
    # Budget still drops facts: either "not shown" or folded into a scenario line.
    assert "not shown" in out or "folded into scenarios" in out
    assert "memory search" in out or "memory show" in out


def test_area_filter(mem, capsys):
    write_facts(
        mem,
        [
            make_fact("f-20261001-0001", "Deploy fact.", area="deploy"),
            make_fact("f-20261001-0002", "Database fact.", area="database"),
        ],
    )
    out = load(capsys, "--area", "deploy")
    assert "Deploy fact." in out and "Database fact." not in out


def test_newer_fact_wins_a_tight_budget(mem, capsys, monkeypatch):
    monkeypatch.setenv("MEMORY_NOW", NOW)
    write_facts(
        mem,
        [
            make_fact(
                "f-20261001-0001", "Older fact here.", learned_at="2026-06-01T00:00:00+00:00"
            ),
            make_fact(
                "f-20261001-0002", "Newer fact here.", learned_at="2026-10-19T00:00:00+00:00"
            ),
        ],
    )
    out = load(capsys, "--budget", "8")
    assert "Newer fact here." in out and "Older fact here." not in out


def test_changed_paths_raise_their_area(repo, mem, capsys, monkeypatch):
    monkeypatch.setenv("MEMORY_NOW", NOW)
    (mem / "config.toml").write_text('[areas]\n"src/db/" = "database"\n')
    wt = add_worktree(repo, "tune")
    (wt / "src" / "db").mkdir(parents=True)
    (wt / "src" / "db" / "x.py").write_text("x = 1\n")
    git(wt, "add", "-A")
    git(wt, "commit", "-q", "-m", "db change")
    main(["init", "--no-default-rules"])
    monkeypatch.chdir(wt)
    write_facts(
        mem,
        [
            make_fact(
                "f-20261001-0001",
                "Database trap here.",
                area="database",
                learned_at="2026-08-01T00:00:00+00:00",
            ),
            make_fact(
                "f-20261001-0002",
                "Interface fact here.",
                area="ui",
                learned_at="2026-10-19T00:00:00+00:00",
            ),
        ],
    )
    out = load(capsys, "--budget", "8")
    assert "Database trap here." in out


def test_branch_words_match_tags(repo, mem, capsys, monkeypatch):
    monkeypatch.setenv("MEMORY_NOW", NOW)
    wt = add_worktree(repo, "fix-email-retry")
    main(["init", "--no-default-rules"])
    monkeypatch.chdir(wt)
    write_facts(
        mem,
        [
            make_fact(
                "f-20261001-0001",
                "Mail fact here.",
                tags=["email"],
                learned_at="2026-08-01T00:00:00+00:00",
            ),
            make_fact(
                "f-20261001-0002", "Other fact here.", learned_at="2026-10-19T00:00:00+00:00"
            ),
        ],
    )
    out = load(capsys, "--budget", "8")
    assert "Mail fact here." in out


def test_short_term_section_for_this_branch_comes_first(repo, mem, capsys, monkeypatch):
    monkeypatch.setenv("MEMORY_NOW", NOW)
    wt = add_worktree(repo, "feat")
    main(["init", "--no-default-rules"])
    monkeypatch.chdir(wt)
    write_facts(
        mem,
        [
            make_fact("f-20261001-0001", "Long fact.", scope="long"),
            make_fact(
                "f-20261001-0002",
                "My branch note.",
                scope="short",
                writer="feat",
                until_branch_merged="feat",
            ),
            make_fact(
                "f-20261001-0003",
                "Other branch note.",
                scope="short",
                writer="other",
                until_branch_merged="other",
            ),
        ],
        name="mixed.jsonl",
    )
    out = load(capsys)
    assert "Short-term" in out
    assert out.index("My branch note.") < out.index("Long fact.")
    assert "Other branch note." not in out


def test_short_fact_expires_when_its_branch_is_merged(repo, mem, capsys, monkeypatch):
    monkeypatch.setenv("MEMORY_NOW", NOW)
    git(repo, "branch", "done-branch")
    (repo / "f.txt").write_text("x")
    git(repo, "add", "f.txt")
    git(repo, "commit", "-q", "-m", "advance main")
    write_facts(
        mem,
        [
            make_fact(
                "f-20261001-0002",
                "Done branch note.",
                scope="short",
                until_branch_merged="done-branch",
            ),
        ],
    )
    assert "Done branch note." not in load(capsys)


def test_notes_are_printed(repo, mem, capsys):
    (mem / "notes" / "status.md").write_text("# Status\n\nRelease is next week.\n")
    assert "Release is next week." in load(capsys)


def test_bad_line_warns_but_loads_the_rest(mem, capsys):
    write_facts(mem, [make_fact("f-20261001-0001", "Good fact.")])
    with (mem / "facts" / "main.jsonl").open("a") as fh:
        fh.write("{broken\n")
    out = load(capsys)
    assert "Good fact." in out and "warning" in out


def test_unexpected_error_never_blocks(mem, capsys, monkeypatch):
    def boom(*_args, **_kwargs):
        raise RuntimeError("disk on fire")

    monkeypatch.setattr(load_module, "build_output", boom)
    out = load(capsys)
    assert "not loaded" in out and "disk on fire" in out


def test_one_thousand_facts_load_fast(mem, capsys):
    facts = [
        make_fact(
            f"f-2026{(i % 9) + 1:02d}01-{i:04x}",
            f"Fact {i} about area {i % 7}.",
            area=f"a{i % 7}",
            tags=[f"t{i % 11}"],
        )
        for i in range(1000)
    ]
    write_facts(mem, facts)
    start = time.perf_counter()
    load(capsys)
    assert time.perf_counter() - start < 1.0


def test_fresh_status_template_is_not_printed(mem, capsys):
    out = load(capsys)
    assert "Status" not in out
    assert "Rewrite this file" not in out
