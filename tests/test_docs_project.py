"""Project-true `memory docs`: inventory the checkout, cairnkit pages only for cairnkit."""

from __future__ import annotations

from pathlib import Path

import pytest

from cairnkit.cli import main
from cairnkit.docs_inventory import ProjectKind, detect_project_kind, inventory


def state_dir(repo: Path) -> Path:
    return repo / "docs" / "state"


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _pyproject(name: str, description: str, scripts: str = "") -> str:
    return (
        "[project]\n"
        f'name = "{name}"\n'
        'version = "0.1.0"\n'
        f'description = "{description}"\n'
        f"{scripts}"
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
    _write(pkg / "notes.py", '"""Scratch notes that nothing imports."""\ndef scratch():\n    return None\n')


def _forbid_cairnkit(repo: Path) -> None:
    banned = ("agent-session", "fact-lifecycle", "fact store", "memory session", "memory-bank", "cairnkit")
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


def test_inventory_reads_console_scripts_and_readme_sections(tmp_path: Path):
    root = tmp_path / "proj"
    _write(
        root / "pyproject.toml",
        '[project]\nname = "docsearch"\nversion = "0.1.0"\n'
        'description = "Search."\n\n'
        '[project.entry-points."console_scripts"]\n'
        'search = "docsearch.search:run"\n',
    )
    headings = "\n".join(f"## Section {i}\n\nbody\n" for i in range(10))
    _write(root / "README.md", f"# docsearch\n\n### Skip me\n\n{headings}")
    inv = inventory(root)
    assert inv.kind is ProjectKind.GENERIC
    assert inv.project_name == "docsearch"
    assert [(ep.name, ep.module) for ep in inv.entry_points] == [("search", "docsearch.search")]
    assert len(inv.readme_sections) == 8
    assert inv.readme_sections[0].heading == "Section 0"
    assert inv.readme_sections[-1].heading == "Section 7"
    assert all(section.heading != "Skip me" for section in inv.readme_sections)


def test_docs_generic_docsearch_pages_follow_imports(mem: Path, repo: Path):
    plant_docsearch(repo)
    assert main(["docs", "--force"]) == 0
    names = {p.relative_to(state_dir(repo)).as_posix() for p in state_dir(repo).rglob("*.md")}
    assert "README.md" in names
    assert "architecture.md" in names
    assert "agent-session.md" not in names
    assert "fact-lifecycle.md" not in names
    _forbid_cairnkit(repo)

    root = (state_dir(repo) / "README.md").read_text(encoding="utf-8")
    assert "kind: system" in root
    assert 'sourceRevision: "' in root
    assert "README.md" in root.split("---", 2)[1]
    assert "Codebase" in root
    assert "docsearch" in root
    assert "```mermaid" in root

    arch = (state_dir(repo) / "architecture.md").read_text(encoding="utf-8")
    assert "kind: service" in arch
    assert "sourceRevision:" not in arch
    assert "docsearch.cli:main" in arch
    for heading in ("Ingest", "Search", "Rerank"):
        assert heading in arch
    assert "docsearch_ingest --> docsearch_chunking" in arch
    assert "docsearch_search --> docsearch_rerank" in arch

    expected = {
        "docsearch-ingest",
        "docsearch-chunking",
        "docsearch-search",
        "docsearch-rerank",
        "docsearch-judge",
        "docsearch-decider",
        "docsearch-llm",
        "docsearch-cli",
    }
    modules = state_dir(repo) / "modules"
    stems = {p.stem for p in modules.glob("*.md")}
    assert stems == expected
    ingest = (modules / "docsearch-ingest.md").read_text(encoding="utf-8")
    assert "kind: module" in ingest
    assert "sourceRevision:" not in ingest
    assert "Ingest raw documents." in ingest
    assert "docsearch_chunking" in ingest
    assert "docsearch-notes.md" not in names


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
    arch = (state_dir(repo) / "architecture.md").read_text(encoding="utf-8")
    assert "alpha --> beta" in arch
    names = {p.name for p in state_dir(repo).rglob("*.md")}
    assert "agent-session.md" not in names
    assert "fact-lifecycle.md" not in names
    _forbid_cairnkit(repo)


def test_docs_generic_subpackage_pages(mem: Path, repo: Path):
    _write(repo / "pyproject.toml", _pyproject("pipe", "Nested packages."))
    _write(repo / "src" / "pipe" / "__init__.py", "")
    _write(repo / "src" / "pipe" / "ingest" / "__init__.py", "")
    _write(repo / "src" / "pipe" / "ingest" / "loader.py", '"""Load files."""\n')
    _write(repo / "src" / "pipe" / "search" / "__init__.py", "")
    _write(repo / "src" / "pipe" / "search" / "query.py", '"""Run a query."""\n')
    assert main(["docs", "--force"]) == 0
    modules = state_dir(repo) / "modules"
    assert (modules / "pipe-ingest.md").is_file()
    assert (modules / "pipe-search.md").is_file()
    assert not (modules / "pipe-ingest-loader.md").exists()
    text = (modules / "pipe-ingest.md").read_text(encoding="utf-8")
    assert "kind: module" in text
    assert "loader" in text
    names = {p.name for p in state_dir(repo).rglob("*.md")}
    assert "agent-session.md" not in names
    _forbid_cairnkit(repo)


def test_docs_generic_module_pages_capped_and_stable(mem: Path, repo: Path):
    _write(repo / "pyproject.toml", _pyproject("pkg", "Many modules."))
    pkg = repo / "src" / "pkg"
    _write(pkg / "__init__.py", "")
    count = 20
    for index in range(count):
        targets = [f"a{(index + 1) % count:02d}", f"a{(index + 2) % count:02d}"]
        body = f'"""Module a{index:02d}."""\n' + "".join(f"import pkg.{name}\n" for name in targets)
        _write(pkg / f"a{index:02d}.py", body)
    assert main(["docs", "--force"]) == 0
    first = sorted(p.name for p in (state_dir(repo) / "modules").glob("*.md"))
    assert first == [f"pkg-a{index:02d}.md" for index in range(16)]
    assert main(["docs", "--force"]) == 0
    second = sorted(p.name for p in (state_dir(repo) / "modules").glob("*.md"))
    assert second == first
    names = {p.name for p in state_dir(repo).rglob("*.md")}
    assert "agent-session.md" not in names
    assert "fact-lifecycle.md" not in names


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
    assert "docs/state/architecture.md" in out.out.splitlines()


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
