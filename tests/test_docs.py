from __future__ import annotations

from pathlib import Path

from conftest import git

from cairnkit.cli import main


def state_dir(repo: Path) -> Path:
    return repo / "docs" / "state"


def test_docs_refuses_without_init(repo: Path, capsys):
    code = main(["docs"])
    assert code == 1
    err = capsys.readouterr().err
    assert "memory init" in err
    assert not state_dir(repo).exists()


def test_docs_dry_run_writes_nothing(mem: Path, repo: Path, capsys):
    code = main(["docs", "--dry-run"])
    assert code == 0
    out = capsys.readouterr().out
    assert "docs/state" in out
    assert not state_dir(repo).exists()


def test_docs_writes_nessa_root_with_mermaid(mem: Path, repo: Path):
    code = main(["docs"])
    assert code == 0
    root = state_dir(repo) / "README.md"
    text = root.read_text(encoding="utf-8")
    assert text.startswith("---\n")
    assert "id:" in text
    assert "kind: system" in text
    assert "parent: null" in text
    assert "```mermaid" in text
    assert "status: implemented" in text


def test_docs_writes_lifecycle_and_session_pages(mem: Path, repo: Path):
    assert main(["docs"]) == 0
    names = {p.name for p in state_dir(repo).rglob("*.md")}
    assert "README.md" in names
    assert "fact-lifecycle.md" in names
    assert "agent-session.md" in names
    life = (state_dir(repo) / "fact-lifecycle.md").read_text(encoding="utf-8")
    assert "kind: statechart" in life
    assert "stateDiagram" in life
    session = (state_dir(repo) / "agent-session.md").read_text(encoding="utf-8")
    assert "kind: flow" in session
    assert "```mermaid" in session


def test_docs_refuses_existing_without_force(mem: Path, repo: Path, capsys):
    assert main(["docs"]) == 0
    before = (state_dir(repo) / "README.md").read_text(encoding="utf-8")
    code = main(["docs"])
    assert code == 1
    assert "already exists" in capsys.readouterr().err
    assert (state_dir(repo) / "README.md").read_text(encoding="utf-8") == before


def test_docs_force_overwrites(mem: Path, repo: Path):
    assert main(["docs"]) == 0
    readme = state_dir(repo) / "README.md"
    readme.write_text("stale\n", encoding="utf-8")
    assert main(["docs", "--force"]) == 0
    text = readme.read_text(encoding="utf-8")
    assert text.startswith("---\n")
    assert "kind: system" in text


def test_docs_records_source_revision(mem: Path, repo: Path):
    head = git(repo, "rev-parse", "HEAD").strip()
    assert main(["docs"]) == 0
    text = (state_dir(repo) / "README.md").read_text(encoding="utf-8")
    assert f'sourceRevision: "{head}"' in text
