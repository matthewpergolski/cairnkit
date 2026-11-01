"""Each line of a status note reaches the load, or the load says that it was cut."""

from __future__ import annotations

import pytest

from cairnkit.cli import main


def load(capsys) -> list[str]:
    capsys.readouterr()
    assert main(["load"]) == 0
    return capsys.readouterr().out.splitlines()


def status(mem, content: bytes) -> None:
    (mem / "notes" / "status.md").write_bytes(content)


def test_an_issue_number_at_the_start_of_a_line_is_not_a_heading(mem, capsys):
    status(mem, b"#96 is open and do not merge\n")
    assert "- [status] #96 is open and do not merge" in load(capsys)


@pytest.mark.parametrize("line", ["##Open", "#! keep", "#", "####### seven"])
def test_a_line_that_is_not_a_markdown_heading_stays(mem, capsys, line):
    status(mem, f"{line}\n".encode())
    assert f"- [status] {line}" in load(capsys)


def test_a_section_heading_stays_so_a_list_keeps_its_meaning(mem, capsys):
    status(mem, b"## Merged\n- #91\n## Open\n- #97\n")
    out = load(capsys)
    at = [out.index(f"- [status] {x}") for x in ("## Merged", "- #91", "## Open", "- #97")]
    assert at == sorted(at)


def test_a_title_on_the_first_line_is_not_a_status_line(mem, capsys):
    status(mem, b"# Status\n\nOne line.\n# A later heading\n")
    out = load(capsys)
    assert "- [status] # Status" not in out
    assert "- [status] One line." in out
    assert "- [status] # A later heading" in out


def test_one_latin_1_byte_keeps_the_whole_status(mem, capsys):
    status(mem, b"Caf\xe9 deploy is blocked\nSecond line\n")
    out = load(capsys)
    assert any("deploy is blocked" in line for line in out)
    assert "- [status] Second line" in out


def test_one_latin_1_byte_keeps_the_branch_note(mem, capsys):
    (mem / "branches").mkdir(exist_ok=True)
    (mem / "branches" / "main.md").write_bytes(b"Caf\xe9 note\n")
    assert any(line.startswith("- [branch] Caf") for line in load(capsys))


def test_a_status_that_cannot_be_read_says_so(mem, capsys):
    (mem / "notes" / "status.md").mkdir()
    assert any(
        line.startswith("- [status]") and "could not be read" in line for line in load(capsys)
    )


def test_no_status_file_prints_nothing(mem, capsys):
    (mem / "notes" / "status.md").unlink(missing_ok=True)
    assert not any("[status]" in line for line in load(capsys))


def test_a_comment_and_blank_lines_are_not_counted_as_cut(mem, capsys):
    status(mem, b"<!-- note -->\n\n" + b"".join(b"line %d\n" % n for n in range(8)))
    out = load(capsys)
    assert not any("lines shown" in line for line in out)
    assert "- [status] line 7" in out


def test_a_long_status_says_how_many_lines_were_cut(mem, capsys):
    status(mem, b"".join(b"line %d\n" % n for n in range(12)))
    out = load(capsys)
    assert "- [status] line 7" in out
    assert "- [status] line 8" not in out
    assert any(x.startswith("- [status] (8 of 12 lines shown. The rest is in ") for x in out)


def test_a_status_of_exactly_the_limit_is_not_cut(mem, capsys):
    status(mem, b"".join(b"line %d\n" % n for n in range(8)))
    assert not any("lines shown" in line for line in load(capsys))


def test_a_cut_branch_note_also_says_so(mem, capsys):
    (mem / "branches").mkdir(exist_ok=True)
    (mem / "branches" / "main.md").write_bytes(b"".join(b"line %d\n" % n for n in range(9)))
    out = load(capsys)
    assert any(x.startswith("- [branch] (8 of 9 lines shown. The rest is in ") for x in out)
