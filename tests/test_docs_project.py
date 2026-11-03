"""Project-true `memory docs`: inventory the checkout, cairnkit pages only for cairnkit."""

from __future__ import annotations

from pathlib import Path

import pytest

from cairnkit.cli import main
from cairnkit.docs_inventory import ProjectKind, detect_project_kind


def state_dir(repo: Path) -> Path:
    return repo / "docs" / "state"


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _pyproject(name: str, description: str, scripts: str = "") -> str:
    return (
        f'[project]\nname = "{name}"\nversion = "0.1.0"\ndescription = "{description}"\n{scripts}'
    )


def plant_docsearch(repo: Path) -> None:
    _write(
        repo / "pyproject.toml",
        _pyproject(
            "docsearch",
            "Multi-module document search pipeline.",
            '[project.scripts]\ndocsearch = "docsearch.cli:main"\n',
        ),
    )
    _write(
        repo / "README.md",
        "# docsearch\n\nPipeline.\n\n## Ingest\n\nRead docs.\n\n"
        "## Search\n\nRetrieve.\n\n## Rerank\n\nOrder.\n",
    )
    pkg = repo / "src" / "docsearch"
    _write(pkg / "__init__.py", '"""Document search."""\n')
    _write(
        pkg / "ingest.py",
        '"""Ingest raw documents."""\nfrom . import chunking, llm\n',
    )
    _write(
        pkg / "chunking.py",
        '"""Split documents into chunks."""\nfrom docsearch.llm import embed\n',
    )
    _write(
        pkg / "search.py",
        '"""Retrieve candidate chunks."""\n'
        "from docsearch.ingest import run\n"
        "from docsearch.chunking import split\n"
        "from docsearch.rerank import order\n",
    )
    _write(
        pkg / "rerank.py",
        '"""Order retrieved chunks."""\n'
        "from docsearch.search import run\n"
        "from docsearch.llm import embed\n",
    )
    _write(
        pkg / "judge.py",
        '"""Score ordered chunks."""\n'
        "from docsearch.rerank import order\n"
        "from docsearch.decider import choose\n"
        "from docsearch.search import run\n",
    )
    _write(
        pkg / "decider.py",
        '"""Pick a final answer."""\n'
        "from docsearch.judge import score\n"
        "from docsearch.llm import embed\n",
    )
    _write(
        pkg / "llm.py",
        '"""Embed text locally."""\ndef embed(texts):\n    return list(texts)\n',
    )
    _write(
        pkg / "cli.py",
        '"""Command line entry."""\n'
        "from docsearch.ingest import run\n"
        "from docsearch.search import run as search_run\n"
        "from docsearch.judge import score\n"
        "from docsearch.decider import choose\n",
    )
    _write(
        pkg / "notes.py",
        '"""Scratch notes that nothing imports."""\ndef scratch():\n    return None\n',
    )


def _forbid_cairnkit(repo: Path) -> None:
    banned = (
        "agent-session",
        "fact-lifecycle",
        "fact store",
        "memory session",
        "memory-bank",
        "cairnkit",
    )
    for path in state_dir(repo).rglob("*.md"):
        text = path.read_text(encoding="utf-8").lower()
        for word in banned:
            assert word not in text, f"{path.name} contains {word}"


def test_project_kind_gate(tmp_path: Path):
    named = tmp_path / "named"
    named.mkdir()
    _write(named / "pyproject.toml", _pyproject("cairnkit", "memory"))
    assert detect_project_kind(named) is ProjectKind.CAIRNKIT

    other_case = tmp_path / "case"
    other_case.mkdir()
    _write(other_case / "pyproject.toml", _pyproject("Cairnkit", "memory"))
    assert detect_project_kind(other_case) is ProjectKind.GENERIC

    signed = tmp_path / "signed"
    folder = signed / "src" / "cairnkit"
    _write(folder / "__init__.py", "")
    for stem in ("memory", "schema", "state", "store", "cli"):
        _write(folder / f"{stem}.py", f"# {stem}\n")
    assert detect_project_kind(signed) is ProjectKind.CAIRNKIT

    loose = tmp_path / "loose"
    loose_dir = loose / "src" / "cairnkit"
    _write(loose_dir / "__init__.py", "")
    _write(loose_dir / "cli.py", "# cli\n")
    _write(loose_dir / "memory.py", "# memory\n")
    assert detect_project_kind(loose) is ProjectKind.GENERIC

    no_init = tmp_path / "no-init"
    bare = no_init / "src" / "cairnkit"
    for stem in ("memory", "schema", "state", "store"):
        _write(bare / f"{stem}.py", f"# {stem}\n")
    assert detect_project_kind(no_init) is ProjectKind.GENERIC

    generic = tmp_path / "generic"
    _write(generic / "pyproject.toml", _pyproject("docsearch", "search"))
    _write(generic / "src" / "docsearch" / "__init__.py", "")
    _write(generic / "src" / "docsearch" / "ingest.py", "# ingest\n")
    assert detect_project_kind(generic) is ProjectKind.GENERIC


def test_docs_generic_docsearch_page_follows_imports(mem: Path, repo: Path):
    plant_docsearch(repo)
    assert main(["docs", "--force"]) == 0
    names = {p.relative_to(state_dir(repo)).as_posix() for p in state_dir(repo).rglob("*.md")}
    assert names == {"README.md", "components/src-docsearch.md"}
    _forbid_cairnkit(repo)

    root = (state_dir(repo) / "README.md").read_text(encoding="utf-8")
    assert "kind: system" in root
    assert 'sourceRevision: "' in root
    assert "README.md" in root.split("---", 2)[1]
    assert "`docsearch.cli:main`" in root
    assert "```mermaid" in root

    page = (state_dir(repo) / "components" / "src-docsearch.md").read_text(encoding="utf-8")
    assert "kind: module" in page
    assert "sourceRevision:" not in page
    assert "Python package. Source root `src`. Import name `docsearch`." in page
    assert '["ingest.py"]' in page and '["chunking.py"]' in page
    assert "| `ingest.py` | Ingest raw documents. | 2 |" in page
    assert "| `notes.py` | Scratch notes that nothing imports. | 0 |" in page


def test_docs_generic_package_edges(mem: Path, repo: Path):
    _write(repo / "pyproject.toml", _pyproject("bridge", "Two packages."))
    _write(repo / "src" / "alpha" / "__init__.py", "")
    _write(
        repo / "src" / "alpha" / "core.py",
        '"""Core."""\nfrom beta.util import helper\n',
    )
    _write(repo / "src" / "beta" / "__init__.py", "")
    _write(repo / "src" / "beta" / "util.py", '"""Util."""\ndef helper():\n    return 1\n')
    assert main(["docs", "--force"]) == 0
    root = (state_dir(repo) / "README.md").read_text(encoding="utf-8")
    assert 'c_src_alpha["src/alpha"]' in root
    assert "c_src_alpha --> c_src_beta" in root
    names = {p.name for p in state_dir(repo).rglob("*.md")}
    assert names == {"README.md", "src-alpha.md", "src-beta.md"}
    _forbid_cairnkit(repo)


def test_docs_check_goes_stale_when_an_import_changes(mem: Path, repo: Path, capsys):
    plant_docsearch(repo)
    assert main(["docs", "--force"]) == 0
    ingest = repo / "src" / "docsearch" / "ingest.py"
    ingest.write_text('"""Ingest raw documents."""\nfrom . import llm\n', encoding="utf-8")
    capsys.readouterr()
    code = main(["docs", "--check"])
    out = capsys.readouterr()
    assert code == 1
    assert out.err == ""
    assert out.out.splitlines() == ["docs/state/components/src-docsearch.md"]


def test_docs_generic_rerun_is_byte_stable(mem: Path, repo: Path):
    plant_docsearch(repo)
    assert main(["docs", "--force"]) == 0
    first = {
        path.relative_to(repo).as_posix(): path.read_bytes()
        for path in state_dir(repo).rglob("*.md")
    }
    assert main(["docs", "--force"]) == 0
    second = {
        path.relative_to(repo).as_posix(): path.read_bytes()
        for path in state_dir(repo).rglob("*.md")
    }
    assert first == second


def test_docs_cairnkit_kind_writes_session_lifecycle_and_architecture(mem: Path, repo: Path):
    _write(
        repo / "pyproject.toml",
        _pyproject("cairnkit", "A private, dated memory for any project."),
    )
    folder = repo / "src" / "cairnkit"
    _write(folder / "__init__.py", "")
    for name in ("cli", "hookrun", "load", "schema", "state", "store", "memory", "docs_cmd"):
        _write(folder / f"{name}.py", f"# {name}\n")
    assert main(["docs", "--force"]) == 0
    names = {p.name for p in state_dir(repo).rglob("*.md")}
    assert {"README.md", "agent-session.md", "fact-lifecycle.md", "architecture.md"} <= names
    life = (state_dir(repo) / "fact-lifecycle.md").read_text(encoding="utf-8")
    session = (state_dir(repo) / "agent-session.md").read_text(encoding="utf-8")
    arch = (state_dir(repo) / "architecture.md").read_text(encoding="utf-8")
    assert "kind: statechart" in life and "stateDiagram" in life
    assert "kind: flow" in session and "```mermaid" in session
    assert "kind: service" in arch
    assert "Commands --> docs_cmd" in arch
    assert "sourceRevision:" not in life
    assert "sourceRevision:" not in session
    assert "sourceRevision:" not in arch
    assert "modules" not in names


def test_docs_unparseable_module_does_not_crash(mem: Path, repo: Path):
    _write(repo / "pyproject.toml", _pyproject("plain", "Plain."))
    _write(repo / "src" / "plain" / "__init__.py", "")
    _write(repo / "src" / "plain" / "ok.py", '"""Ok."""\n')
    _write(repo / "src" / "plain" / "broken.py", "def (\n")
    assert main(["docs", "--force"]) == 0
    assert (state_dir(repo) / "README.md").is_file()
    assert not (state_dir(repo) / "agent-session.md").exists()


@pytest.mark.parametrize(
    "flag",
    [["docs"], ["docs", "--force"]],
)
def test_docs_still_refuses_without_init_for_a_generic_tree(repo: Path, capsys, flag):
    plant_docsearch(repo)
    code = main(flag)
    assert code == 1
    assert "memory init" in capsys.readouterr().err
    assert not state_dir(repo).exists()
