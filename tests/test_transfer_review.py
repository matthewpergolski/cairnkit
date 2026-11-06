"""Defects that an independent review found in `memory export` and `memory import`."""

from __future__ import annotations

import stat

from test_transfer import added, memory, new_repo, ok

from cairnkit.selection import clean


def plan_of(tmp_path, text: str, name: str = "proj") -> str:
    root = new_repo(tmp_path / name)
    return ok(root, "import", "-", stdin=text)


def would_add(plan: str) -> str:
    return plan.split("Would skip", 1)[0]


def test_a_byte_order_mark_does_not_hide_the_first_heading(tmp_path):
    root = new_repo(tmp_path / "proj")
    paste = tmp_path / "paste.md"
    paste.write_bytes(
        "﻿## Identity\n- [2020-01-01] - I am a nurse in Berlin.\n".encode()
        + b"## Decisions\n- [2026-10-01] - Use Postgres.\n"
    )
    plan = ok(root, "import", str(paste))
    assert "nurse" not in would_add(plan) and "Use Postgres." in would_add(plan)
    piped = ok(root, "import", "-", stdin=paste.read_text(encoding="utf-8"))
    assert "nurse" not in would_add(piped)


def test_a_plain_personal_title_is_a_heading(tmp_path):
    plan = plan_of(
        tmp_path,
        "## Decisions\n- Use Postgres.\nPersonal details, preferences:\n- lives in Paris\n"
        "Identity\n- is a nurse\n## Notes on me\n- likes cats\n",
    )
    shown = would_add(plan)
    assert "Use Postgres." in shown
    assert not any(word in shown for word in ("Paris", "nurse", "cats"))


def test_headings_match_whole_words(tmp_path):
    plan = plan_of(
        tmp_path,
        "## Recommended practices\n- Run the linter first.\n"
        "## Intended design\n- One queue per tenant.\n"
        "## Estate planning\n- The will is with the lawyer.\n",
    )
    assert "ended in the source" not in plan
    assert "The will is with the lawyer." not in would_add(plan)


def test_the_prompt_heading_with_its_description_reads_as_other(tmp_path):
    plan = plan_of(
        tmp_path, "## Other: other facts about the project\n- The API lives in src/api.\n", "d"
    )
    assert "+ fact" in plan and "The API lives in src/api." in would_add(plan)


def test_a_projects_line_must_name_this_project_as_a_word(tmp_path):
    plan = plan_of(
        tmp_path, "## Projects\n- dev of Dashboard uses D3.\n- The d service is on port 9.\n", "d"
    )
    shown = would_add(plan)
    assert "D3" not in shown and "port 9" in shown


def test_a_quoted_native_type_is_read_and_an_unknown_type_is_skipped(tmp_path):
    root = new_repo(tmp_path / "proj")
    notes = tmp_path / "notes"
    notes.mkdir()
    (notes / "who.md").write_text('---\ntype: "user"\n---\nThe owner is a nurse in Berlin.\n')
    (notes / "odd.md").write_text("---\ntype: scratch\n---\nA loose thought.\n")
    (notes / "rule.md").write_text("---\ntype: 'feedback'\n---\nNever push on Friday.\n")
    plan = ok(root, "import", str(notes))
    shown = would_add(plan)
    assert "nurse" not in shown and "A loose thought." not in shown
    assert "rule, loads as data" in shown and "Never push on Friday." in shown


def test_export_does_not_write_through_a_link_or_keep_a_wide_mode(tmp_path):
    root = new_repo(tmp_path / "proj")
    (root / "private").mkdir()
    (root / "private" / "link.md").symlink_to("../README.md")
    code, _, err = memory(root, "export", "--output", "private/link.md", "--force")
    assert code != 0 and "link" in err
    assert (root / "README.md").read_text() == "x\n"
    wide = root / "private" / "p.md"
    wide.write_text("old\n")
    wide.chmod(0o644)
    ok(root, "export", "--output", "private/p.md", "--force")
    assert stat.S_IMODE(wide.stat().st_mode) == 0o600


def test_export_refuses_a_path_another_repo_would_track(tmp_path):
    root = new_repo(tmp_path / "proj")
    other = new_repo(tmp_path / "other")
    code, _, err = memory(root, "export", "--output", str(other / "e.md"))
    assert code != 0 and "git does not ignore" in err
    assert not (other / "e.md").exists()


def test_a_paste_over_the_size_limit_is_refused_not_cut(tmp_path):
    root = new_repo(tmp_path / "proj")
    big = "## Decisions\n" + "- [2026-10-01] - Use Postgres for the queue.\n" * 30_000
    code, _, err = memory(root, "import", "-", "--yes", stdin=big)
    assert code != 0 and "larger than" in err
    assert added(tmp_path / "proj.memory") == []


def test_loose_and_future_dates(tmp_path):
    root = new_repo(tmp_path / "proj")
    ok(
        root,
        "import",
        "-",
        "--yes",
        stdin="## Decisions\n[2026-1-5] - Use Postgres.\n[2026-10-01 12:00] - Use Redis.\n"
        "[2099-01-01] - Ship the beta.\n",
    )
    got = {f["text"]: f["happened_at"] for f in added(tmp_path / "proj.memory")}
    assert got["Use Postgres."] == "2026-01-05" and got["Use Redis."] == "2026-10-01"
    assert got["Ship the beta."] == "2026-11-06"


def test_a_status_line_with_its_own_date_keeps_one_date(tmp_path):
    root = new_repo(tmp_path / "proj")
    (tmp_path / "proj.memory" / "notes").mkdir(exist_ok=True)
    (tmp_path / "proj.memory" / "notes" / "status.md").write_text("- [2026-02-02] - Rel 0.4\n")
    out = ok(root, "export")
    assert "[2026-02-02] - Rel 0.4" in out and "] - [" not in out


def test_clean_drops_bidi_marks():
    assert clean("a‮b⁦c⁩d") == "abcd"
