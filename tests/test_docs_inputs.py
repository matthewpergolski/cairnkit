"""`memory docs` reads project files that it does not trust: odd, huge, linked or hostile."""

from __future__ import annotations

import random
import re
import subprocess
import sys
import time
from pathlib import Path

import pytest
from conftest import git
from test_docs_generic import front, page, pages, state, write

from cairnkit.cli import main
from cairnkit.docs_inventory import inventory
from cairnkit.docs_script import specifiers


def all_text(repo: Path) -> str:
    return "\n".join(page(repo, rel) for rel in sorted(pages(repo)))


def snapshot(folder: Path) -> dict[str, bytes]:
    return {
        p.relative_to(folder).as_posix(): p.read_bytes() for p in folder.rglob("*") if p.is_file()
    }


def summaries(repo: Path) -> dict[str, str | None]:
    return {item.path: item.summary for item in inventory(repo).files}


def test_a_file_too_deep_to_read_leaves_that_file_empty_and_the_atlas_writes(
    mem: Path, repo: Path, capsys
):
    """`urlpatterns = a + a + ...` raised RecursionError and stopped docs, --check and status."""
    write(repo / "site" / "__init__.py", "")
    write(repo / "site" / "good.py", '"""Good module."""\nfrom site import chain\n')
    write(repo / "site" / "chain.py", "urlpatterns = " + " + ".join(["a"] * 5000) + "\n")
    write(repo / "site" / "deep.py", 'urlpatterns = [path("x/", ' + "-" * 3000 + "a)]\n")
    assert main(["docs"]) == 0
    assert "Good module." in all_text(repo)
    capsys.readouterr()
    assert main(["docs", "--check"]) == 0
    assert capsys.readouterr().out == ""
    write(repo / "site" / "good.py", '"""Better module."""\n')
    assert main(["status"]) == 0
    assert "docs/state" in capsys.readouterr().out


def test_a_tracked_link_to_a_file_outside_the_repo_is_not_read(mem: Path, repo: Path):
    outside = repo.parent / "outside"
    write(outside / "secret.py", '"""Outside secret text."""\n')
    write(repo / "app" / "__init__.py", "")
    write(repo / "app" / "main.py", '"""Main module."""\n')
    (repo / "app" / "linked.py").symlink_to(outside / "secret.py")
    (repo / "app" / "inner.py").symlink_to(repo / "app" / "main.py")
    git(repo, "add", "-A")
    assert main(["docs"]) == 0
    text = all_text(repo)
    assert "Main module." in text
    assert "Outside secret" not in text
    assert "linked.py" not in text and "inner.py" not in text


def test_a_linked_manifest_outside_the_repo_is_not_read(mem: Path, repo: Path):
    outside = repo.parent / "outside"
    write(outside / "pyproject.toml", '[project]\nname = "x"\ndescription = "Outside text."\n')
    (repo / "pyproject.toml").symlink_to(outside / "pyproject.toml")
    assert main(["docs"]) == 0
    assert "Outside text." not in all_text(repo)


def test_docs_does_not_write_or_delete_through_a_linked_state_folder(mem: Path, repo: Path, capsys):
    write(repo / "app" / "__init__.py", "")
    write(repo / "app" / "main.py", '"""Main module."""\n')
    assert main(["docs"]) == 0
    elsewhere = repo.parent / "elsewhere"
    state(repo).rename(elsewhere)
    old = (elsewhere / "components" / "app.md").read_text(encoding="utf-8")
    (elsewhere / "components" / "gone.md").write_text(old, encoding="utf-8")
    (elsewhere / "README.md").unlink()
    state(repo).symlink_to(elsewhere, target_is_directory=True)
    before = snapshot(elsewhere)
    capsys.readouterr()
    assert main(["docs", "--force"]) != 0
    assert "docs/state" in capsys.readouterr().err
    assert snapshot(elsewhere) == before


def test_docs_does_not_write_through_a_linked_page(mem: Path, repo: Path, capsys):
    write(repo / "app" / "__init__.py", "")
    write(repo / "app" / "main.py", '"""Main module."""\n')
    assert main(["docs"]) == 0
    outside = repo.parent / "outside.md"
    readme = state(repo) / "README.md"
    outside.write_text(readme.read_text(encoding="utf-8") + "\nEdited.\n", encoding="utf-8")
    readme.unlink()
    readme.symlink_to(outside)
    folder = repo.parent / "linked-components"
    (state(repo) / "components").rename(folder)
    (state(repo) / "components").symlink_to(folder, target_is_directory=True)
    (folder / "gone.md").write_text((folder / "app.md").read_text(encoding="utf-8"))
    before_page, before_folder = outside.read_bytes(), snapshot(folder)
    assert main(["docs", "--force"]) == 0
    assert outside.read_bytes() == before_page
    assert snapshot(folder) == before_folder
    assert readme.is_symlink()


def test_untracked_files_count_unless_git_ignores_them(mem: Path, repo: Path):
    write(repo / ".gitignore", ".worktrees/\nscratch/\n")
    write(repo / "app" / "__init__.py", "")
    write(repo / "app" / "new.py", '"""Not added yet."""\n')
    write(repo / "scratch" / "tmp.py", '"""Ignored scratch."""\n')
    found = summaries(repo)
    assert found.get("app/new.py") == "Not added yet."
    assert "scratch/tmp.py" not in found


def test_a_failed_git_listing_fails_docs_and_writes_nothing(
    mem: Path, repo: Path, capsys, monkeypatch
):
    """A walk that ignores .gitignore gave a different atlas than git did on another machine."""
    from cairnkit import paths

    real = paths.run_git

    def no_listing(root, *args, **kwargs):
        return None if "ls-files" in args else real(root, *args, **kwargs)

    monkeypatch.setattr(paths, "run_git", no_listing)
    write(repo / "app" / "main.py", '"""Main module."""\n')
    capsys.readouterr()
    assert main(["docs"]) != 0
    assert "git" in capsys.readouterr().err
    assert not state(repo).exists()


def test_a_folder_without_git_is_walked_with_a_bound(tmp_path: Path, monkeypatch):
    from cairnkit import docs_inventory

    monkeypatch.setattr(docs_inventory, "MAX_WALK", 5)
    for index in range(20):
        write(tmp_path / "plain" / f"m{index:02d}.py", f'"""Module {index}."""\n')
    found = docs_inventory.project_paths(tmp_path / "plain")
    assert found == [f"m{index:02d}.py" for index in range(5)]


def test_a_huge_file_is_left_empty(mem: Path, repo: Path, monkeypatch):
    from cairnkit import docs_inventory

    monkeypatch.setattr(docs_inventory, "MAX_FILE_BYTES", 200)
    write(repo / "app" / "__init__.py", "")
    write(repo / "app" / "small.py", '"""Small module."""\n')
    write(repo / "app" / "big.py", '"""Big module."""\n' + "x = 1\n" * 100)
    found = summaries(repo)
    assert found["app/small.py"] == "Small module."
    assert found["app/big.py"] is None


def test_a_file_with_a_byte_order_mark_keeps_its_summary_and_imports(mem: Path, repo: Path):
    bom = "﻿"
    write(repo / "app" / "__init__.py", "")
    write(repo / "app" / "a.py", bom + '"""First step."""\nfrom app import b\n')
    write(repo / "app" / "b.py", '"""Second step."""\n')
    write(repo / "package.json", bom + '{"name": "web", "description": "The web part."}\n')
    write(repo / "src" / "main.ts", bom + 'import "./side";\n')
    write(repo / "src" / "side.ts", bom + "// Side effects.\nexport {};\n")
    items = {item.path: item for item in inventory(repo).files}
    assert items["app/a.py"].summary == "First step."
    assert items["app/a.py"].imports == ("app/b.py",)
    assert items["src/main.ts"].imports == ("src/side.ts",)
    assert items["src/side.ts"].summary == "Side effects."
    assert main(["docs"]) == 0
    assert "The web part." in all_text(repo)


@pytest.mark.parametrize(
    "hand",
    [
        "---\ntitle: The shop\n---\n\nid: evil\n",
        "---\ntitle: The shop\n---\n\n---\nid: evil\n---\n",
    ],
)
def test_only_the_front_matter_of_a_hand_page_gives_its_id(mem: Path, repo: Path, hand: str):
    write(repo / "app" / "__init__.py", "")
    write(repo / "app" / "main.py", '"""Main module."""\n')
    write(state(repo) / "README.md", hand)
    assert main(["docs"]) == 0
    parents = {front(page(repo, rel)).get("parent") for rel in pages(repo) - {"README.md"}}
    assert parents and "evil" not in parents


@pytest.mark.parametrize(
    ("rel", "text"),
    [
        ("site/deep.py", "x = " + "-" * 400_000 + "1\n"),
        ("package.json", "[" * 200_000),
        ("web/tsconfig.json", "[" * 200_000),
        ("pyproject.toml", "a=" + "[" * 100_000),
    ],
    ids=["python-parser-stack", "package-json", "tsconfig", "pyproject"],
)
def test_a_file_too_deep_to_parse_counts_as_empty(mem: Path, repo: Path, capsys, rel, text):
    """A parser ran out of stack (MemoryError, RecursionError) and stopped docs and status."""
    write(repo / "site" / "__init__.py", "")
    write(repo / "site" / "good.py", '"""Good module."""\n')
    write(repo / "web" / "package.json", '{"name": "web"}\n')
    write(repo / "web" / "main.ts", "// The web entry.\nexport {};\n")
    write(repo / rel, text)
    assert main(["docs"]) == 0
    assert "Good module." in all_text(repo)
    capsys.readouterr()
    assert main(["docs", "--check"]) == 0
    assert capsys.readouterr().out == ""
    write(repo / "site" / "good.py", '"""Better module."""\n')
    assert main(["status"]) == 0
    assert "docs/state" in capsys.readouterr().out


@pytest.mark.parametrize("rel", [".claude/settings.json", ".cursor/hooks.json"])
def test_a_too_deep_agent_settings_file_stops_no_command(mem: Path, repo: Path, capsys, rel):
    write(repo / rel, "[" * 200_000)
    assert main(["status"]) == 0
    assert main(["load"]) == 0
    capsys.readouterr()
    assert main(["migrate"]) == 0
    assert main(["hooks", "install"]) in (0, 1)


@pytest.mark.parametrize(
    ("rel", "text"),
    [("package.json", "[" * 200_000), ("pyproject.toml", "a=" + "[" * 100_000)],
    ids=["package-json", "pyproject"],
)
def test_the_toolchain_scan_reads_a_too_deep_manifest_as_empty(tmp_path: Path, rel, text):
    from cairnkit.detect import detect

    write(tmp_path / "biome.json", "{}\n")
    write(tmp_path / rel, text)
    found = detect(tmp_path)
    assert not found["uv"].found and not found["ruff"].found
    assert found["biome"].found and not found["biome-run"].found


def run_cli(repo: Path, *args: str, timeout: float = 30) -> subprocess.CompletedProcess:
    """The CLI in its own process, so that a hang fails the test and does not stop the run."""
    argv = [sys.executable, "-m", "cairnkit", *args]
    return subprocess.run(argv, cwd=repo, capture_output=True, text=True, timeout=timeout)


def test_a_script_full_of_import_words_maps_in_time(mem: Path, repo: Path):
    """`import a ` 50000 times ran 30+ s of CPU: the import scan was quadratic."""
    write(repo / "web" / "package.json", '{"name": "web"}\n')
    write(repo / "web" / "index.js", "import a " * 50_000)
    write(repo / "web" / "main.js", '// The entry.\nimport "./index.js";\n')
    done = run_cli(repo, "docs")
    assert done.returncode == 0, done.stderr
    assert "The entry." in all_text(repo)


@pytest.mark.parametrize(
    "text",
    [
        "import a " * 20_000,
        "export a " * 20_000,
        "\n" * 100_000,
        "import" + " " * 100_000,
        "import" + " " * 100_000 + "x",
        "import(" * 50_000,
    ],
    ids=["import-words", "export-words", "blank-lines", "trailing-space", "space-run", "calls"],
)
def test_the_import_scan_is_linear(text: str):
    start = time.process_time()
    specifiers(text)
    assert time.process_time() - start < 1.0


def test_a_page_full_of_open_script_tags_maps_in_time(mem: Path, repo: Path):
    write(repo / "web" / "package.json", '{"name": "web"}\n')
    write(repo / "web" / "main.js", "// The entry.\n")
    write(repo / "web" / "index.html", "<script " * 20_000)
    start = time.process_time()
    inventory(repo)
    assert time.process_time() - start < 2.0


@pytest.mark.parametrize(
    ("text", "found"),
    [
        ('import { from } from "./a";\n', ["./a"]),
        ("import type { A } from './types';\n", ["./types"]),
        ('import React, {\n  useState,\n} from "react";\n', ["react"]),
        ('export * from "./all";\nexport { b as c } from "./b";\n', ["./all", "./b"]),
        ('const x = 1;\nimport "./side";\n', ["./side"]),
        ('const a = require("./r");\nconst b = import("./d");\n', ["./d", "./r"]),
        ('import from from "./f";\n', ["./f"]),
        ('const s = "x";import y from "./y"', ["./y"]),
        ('importer from "./no";\nexport default from "./no2";\n', ["./no2"]),
        ('const from = "./nope";\n', []),
        ('"use strict"; import b from "./y"', ["./y"]),
        ('f("a");import b from "./y"', ["./y"]),
        ('var a="x";import b from "./y";', ["./y"]),
        ('import a from "import b from "z"', ["import b from "]),
    ],
)
def test_the_import_scan_finds_each_import(text: str, found: list[str]):
    assert specifiers(text) == found


_OLD_FROM = re.compile(
    r"""\b(?:import|export)\s+(?:type\s+)?[\w*{}\s,$]*?\bfrom\s*["']([^"'\n]+)["']"""
)
_OLD_BARE = re.compile(r"""(?:^|[;\n])\s*import\s*["']([^"'\n]+)["']""")
_OLD_CALL = re.compile(r"""\b(?:import|require)\s*\(\s*["']([^"'\n]+)["']\s*\)""")
_PIECES = [
    "import", "export", "from", "type", "require", " ", "  ", "\n", "\t", '"', "'", ";",
    "(", ")", "{", "}", ",", "*", "$", "a", "b", "./y", "x=", "use strict", "=", ".", "importer",
]  # fmt: skip


def test_the_import_scan_agrees_with_the_quadratic_regexes():
    """The linear scan replaced three regexes. On normal text it must find what they found."""
    rng = random.Random(20261106)
    for _ in range(20_000):
        text = "".join(rng.choice(_PIECES) for _ in range(rng.randint(1, 30)))
        old = _OLD_FROM.findall(text) + _OLD_BARE.findall(text) + _OLD_CALL.findall(text)
        assert specifiers(text) == sorted(set(old)), repr(text)


def test_a_link_that_a_check_saw_as_a_file_is_not_followed(mem: Path, repo: Path, monkeypatch):
    """A check before the open can be stale: the file can turn into a link between the two."""
    import os

    from cairnkit.docs_inventory import read_file

    outside = repo.parent / "outside.py"
    write(outside, '"""Outside secret text."""\n')
    plain = repo / "app" / "plain.py"
    write(plain, '"""Plain module."""\n')
    link = repo / "app" / "main.py"
    link.symlink_to(outside)
    real_lstat = os.lstat

    def stale_lstat(path, *args, **kwargs):
        return real_lstat(plain if Path(path) == link else path, *args, **kwargs)

    monkeypatch.setattr(os, "lstat", stale_lstat)
    assert read_file(repo, "app/plain.py") == '"""Plain module."""\n'
    assert read_file(repo, "app/main.py") is None


def test_a_file_under_a_linked_folder_is_not_read(mem: Path, repo: Path):
    from cairnkit.docs_inventory import read_file

    write(repo.parent / "outside" / "secret.py", '"""Outside secret text."""\n')
    (repo / "app").symlink_to(repo.parent / "outside")
    assert read_file(repo, "app/secret.py") is None


@pytest.mark.parametrize("args", [("docs", "--check"), ("docs", "--force"), ("status",)])
def test_a_pipe_in_the_state_folder_does_not_hang(mem: Path, repo: Path, args):
    """`mkfifo docs/state/x.md`: the open of a pipe waits for a writer, and none comes."""
    import os

    write(repo / "app" / "__init__.py", "")
    write(repo / "app" / "main.py", '"""Main module."""\n')
    assert main(["docs"]) == 0
    os.mkfifo(state(repo) / "x.md")
    done = run_cli(repo, *args)
    assert done.returncode == 0, done.stderr
    assert (state(repo) / "x.md").exists()
