"""`memory docs` owns the pages that it wrote. A hand-written page in that folder is not its own."""

from __future__ import annotations

import pytest

from cairnkit.cli import main

HAND = "# Runbook\n\nHand-written. Do not lose this.\n"
SAME_KEYS_OTHER_WRITING = (
    "---\nid: runbook\ntitle: The on-call runbook\nkind: flow\nstatus: implemented\n"
    "summary: How we page.\nparent: null\nsources:\n  - ops/page.sh\ndiagramLinks: {}\n---\n\n"
    "# Runbook\n"
)
EXTRA_KEY = (
    '---\nid: runbook\ntitle: runbook\nkind: flow\nstatus: implemented\nsummary: "How we page."\n'
    "parent: null\nowner: ops\nsources:\n  []\ndiagramLinks: {}\n---\n\n# Runbook\n"
)
OLD_ATLAS_PAGE = (
    '---\nid: pkg-old\ntitle: "pkg.old"\nkind: module\nstatus: implemented\n'
    'summary: "A module that left."\nparent: architecture\nsources:\n  - src/pkg/old.py\n'
    "diagramLinks: {}\n---\n\n# pkg.old\n"
)


@pytest.fixture
def state(repo):
    return repo / "docs" / "state"


def check(capsys):
    capsys.readouterr()
    code = main(["docs", "--check"])
    return code, capsys.readouterr().out


def status(capsys):
    capsys.readouterr()
    assert main(["status"]) == 0
    return capsys.readouterr().out


def put(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


@pytest.mark.parametrize("text", [HAND, SAME_KEYS_OTHER_WRITING, EXTRA_KEY])
def test_a_hand_page_reads_current_and_force_keeps_it(mem, state, capsys, text):
    assert main(["docs"]) == 0
    page = state / "guides" / "runbook.md"
    put(page, text)
    assert check(capsys) == (0, "")
    assert "docs/state" not in status(capsys)
    capsys.readouterr()
    assert main(["docs", "--force"]) == 0
    assert "runbook.md" not in capsys.readouterr().out
    assert page.read_text(encoding="utf-8") == text
    assert check(capsys) == (0, "")


def test_force_dry_run_does_not_offer_to_remove_a_hand_page(mem, state, capsys):
    assert main(["docs"]) == 0
    put(state / "runbook.md", HAND)
    capsys.readouterr()
    assert main(["docs", "--force", "--dry-run"]) == 0
    assert "runbook.md" not in capsys.readouterr().out


def test_an_old_atlas_page_with_no_source_is_stale_and_force_removes_it(mem, state, capsys):
    assert main(["docs"]) == 0
    page = state / "modules" / "pkg-old.md"
    put(page, OLD_ATLAS_PAGE)
    put(state / "runbook.md", HAND)
    assert check(capsys) == (1, "docs/state/modules/pkg-old.md\n")
    assert main(["docs", "--force"]) == 0
    assert "removed docs/state/modules/pkg-old.md" in capsys.readouterr().out
    assert not page.exists()
    assert not page.parent.exists()
    assert (state / "runbook.md").read_text(encoding="utf-8") == HAND
    assert check(capsys) == (0, "")


def test_force_leaves_an_empty_folder_that_it_did_not_empty(mem, state):
    assert main(["docs"]) == 0
    empty = state / "drafts"
    empty.mkdir()
    assert main(["docs", "--force"]) == 0
    assert empty.is_dir()


def test_a_folder_of_hand_pages_alone_holds_no_atlas(mem, state, capsys):
    put(state / "runbook.md", HAND)
    assert check(capsys) == (0, "")
    assert "docs/state" not in status(capsys)


def test_the_first_write_goes_beside_hand_pages_with_no_force(mem, state, capsys):
    put(state / "runbook.md", HAND)
    capsys.readouterr()
    assert main(["docs"]) == 0
    assert (state / "README.md").is_file()
    assert (state / "runbook.md").read_text(encoding="utf-8") == HAND
    assert check(capsys) == (0, "")


@pytest.mark.parametrize("flags", [["docs"], ["docs", "--force"]])
def test_a_hand_page_at_an_atlas_path_is_kept_and_named(mem, state, capsys, flags):
    readme = state / "README.md"
    put(readme, HAND)
    capsys.readouterr()
    assert main(flags) == 0
    out = capsys.readouterr().out
    assert readme.read_text(encoding="utf-8") == HAND
    assert "keep docs/state/README.md" in out
    assert "Wrote" in out


def test_a_hand_page_at_an_atlas_path_is_not_stale(mem, state, capsys):
    assert main(["docs"]) == 0
    put(state / "README.md", HAND)
    assert check(capsys) == (0, "")
    assert "docs/state" not in status(capsys)


def test_a_folder_at_an_atlas_path_is_left_alone(mem, state, capsys):
    assert main(["docs"]) == 0
    readme = state / "README.md"
    readme.unlink()
    readme.mkdir()
    assert main(["docs", "--force"]) == 0
    assert readme.is_dir()


def test_status_says_plainly_what_force_does(mem, state, capsys):
    assert main(["docs"]) == 0
    readme = state / "README.md"
    readme.write_text(readme.read_text(encoding="utf-8") + "drift\n", encoding="utf-8")
    line = next(item for item in status(capsys).splitlines() if "docs/state" in item)
    assert "no model and no network" in line
    assert "only the atlas pages" in line
    assert "keeps" in line
    assert "other Markdown" in line
    assert "removes other" not in line
