from conftest import make_fact, write_facts

from cairnkit.cli import main


def run(capsys, *args):
    capsys.readouterr()
    code = main(list(args))
    return code, capsys.readouterr().out


def seed(mem):
    write_facts(
        mem,
        [
            make_fact("f-20261001-0001", "We tried a queue for email retries.", tags=["email"]),
            make_fact("f-20261001-0002", "Email retries use a cron job.", tags=["email"]),
            {
                "type": "change",
                "id": "f-20261001-0001",
                "at": "2026-10-03T00:00:00+00:00",
                "status": "superseded",
                "superseded_by": "f-20261001-0002",
                "reason": "The queue lost jobs on restart.",
                "writer": "main",
            },
        ],
    )


def test_show_prints_history(mem, capsys):
    seed(mem)
    code, out = run(capsys, "show", "f-20261001-0001")
    assert code == 0
    assert "We tried a queue" in out
    assert "superseded" in out and "The queue lost jobs" in out
    assert "f-20261001-0002" in out


def test_show_unknown_id(mem, capsys):
    code, _ = run(capsys, "show", "f-20261001-9999")
    assert code == 1


def test_search_default_is_active_only(mem, capsys):
    seed(mem)
    code, out = run(capsys, "search", "email retries")
    assert code == 0
    assert "cron job" in out and "queue" not in out


def test_search_all_shows_history_with_reason(mem, capsys):
    seed(mem)
    code, out = run(capsys, "search", "queue", "--all")
    assert code == 0
    assert "We tried a queue" in out
    assert "superseded" in out and "lost jobs on restart" in out


def test_search_no_match(mem, capsys):
    seed(mem)
    code, out = run(capsys, "search", "kubernetes")
    assert code == 0 and "no match" in out


def write_note(mem, rel, text):
    path = mem / "notes" / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


def test_search_shows_note_lines_after_facts(mem, capsys):
    seed(mem)
    write_note(mem, "ops/email.md", "# Email\n\nThe email retries run at 02:00.\nOther line.\n")
    code, out = run(capsys, "search", "email retries")
    assert code == 0
    assert "memory-bank/notes/ops/email.md:3: The email retries run at 02:00." in out
    assert out.index("cron job") < out.index("notes/ops/email.md")
    assert "Other line" not in out


def test_search_finds_a_note_when_no_fact_matches(mem, capsys):
    seed(mem)
    write_note(mem, "status.md", "# Status\n\nKubernetes is out of scope.\n")
    code, out = run(capsys, "search", "kubernetes")
    assert code == 0 and "no match" not in out
    assert "memory-bank/notes/status.md:3: Kubernetes is out of scope." in out


def test_search_keeps_note_output_short(mem, capsys):
    long_line = "word " * 60 + "needle " + "word " * 60
    write_note(mem, "long.md", long_line + "\n" + "needle\n" * 9)
    _, out = run(capsys, "search", "needle")
    lines = [line for line in out.splitlines() if "notes/long.md" in line]
    assert len(lines) == 5
    assert "needle" in lines[0] and len(lines[0]) < 160
    assert "5 more line(s) in notes" in out


def test_search_does_not_follow_links_out_of_notes(mem, capsys, tmp_path):
    outside = tmp_path / "outside"
    (outside / "deep").mkdir(parents=True)
    (outside / "secret.md").write_text("needle in a linked file\n")
    (outside / "deep" / "a.md").write_text("needle in a linked folder\n")
    write_note(mem, "real.md", "needle in a real note\n")
    (mem / "notes" / "file.md").symlink_to(outside / "secret.md")
    (mem / "notes" / "dir").symlink_to(outside / "deep", target_is_directory=True)
    _, out = run(capsys, "search", "needle")
    assert "needle in a real note" in out
    assert "linked" not in out


def test_search_skips_a_notes_folder_that_is_a_link(mem, capsys, tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "a.md").write_text("needle outside\n")
    for path in (mem / "notes").iterdir():
        path.unlink()
    (mem / "notes").rmdir()
    (mem / "notes").symlink_to(outside, target_is_directory=True)
    _, out = run(capsys, "search", "needle")
    assert "needle outside" not in out and "no match" in out
