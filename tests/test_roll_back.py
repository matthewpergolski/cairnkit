"""The owner can roll back: the 0.3.1 code reads what this code wrote, and the way back works."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tarfile
from pathlib import Path

import pytest
from conftest import git

HERE = Path(__file__).parent.parent
ADD = ["--area", "general", "--basis", "seen", "--source", "session:2026-11-01"]
BAD_TEXT = '{"type":"fact","id":"f-20261001-dead","text":"A true fact that a crash cu'


@pytest.fixture(scope="module")
def old_src(tmp_path_factory) -> Path:
    """The code of the tag, from `git archive`, and run from there."""
    known = subprocess.run(["git", "tag", "-l", "v0.3.1"], cwd=HERE, capture_output=True, text=True)
    if "v0.3.1" not in known.stdout:
        pytest.skip("this clone has no tag v0.3.1")
    folder = tmp_path_factory.mktemp("v031")
    tar = folder / "v031.tar"
    subprocess.run(["git", "archive", "-o", str(tar), "v0.3.1", "src"], cwd=HERE, check=True)
    with tarfile.open(tar) as archive:
        archive.extractall(folder, filter="data")
    return folder / "src"


class Tools:
    def __init__(self, root: Path, old_src: Path) -> None:
        self.root = root
        self.old_src = old_src
        self.mem = root.parent / f"{root.name}.memory"

    def _env(self, src: Path, extra: dict | None) -> dict:
        return {**os.environ, "PYTHONPATH": str(src), **(extra or {})}

    def _run(self, src: Path, args: tuple, extra: dict | None) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, "-m", "cairnkit", *args],
            cwd=self.root,
            env=self._env(src, extra),
            capture_output=True,
            text=True,
            timeout=60,
        )

    def new(self, *args: str, env: dict | None = None) -> subprocess.CompletedProcess:
        return self._run(HERE / "src", args, env)

    def old(self, *args: str) -> subprocess.CompletedProcess:
        return self._run(self.old_src, args, None)

    def old_commit(self, name: str) -> subprocess.CompletedProcess:
        (self.root / name).write_text("x\n")
        git(self.root, "add", name)
        return subprocess.run(
            ["git", "commit", "-q", "-m", f"add {name}"],
            cwd=self.root,
            env=self._env(self.old_src, None),
            capture_output=True,
            text=True,
            timeout=60,
        )

    def go_back(self) -> None:
        """What a person does after `memory update` rolled the tool back."""
        for args in (["init", "--refresh"], ["hooks", "install"]):
            done = self.old(*args)
            assert done.returncode == 0, done.stdout + done.stderr

    def append(self, name: str, text: str) -> None:
        with (self.mem / "facts" / name).open("a") as out:
            out.write(text)

    def stored(self) -> str:
        return "".join(path.read_text() for path in (self.mem / "facts").glob("*.jsonl"))

    def add(self, text: str, *extra: str, env: dict | None = None) -> str:
        done = self.new("add", text, *ADD, *extra, env=env)
        assert done.returncode == 0, done.stderr
        return done.stdout.strip().split()[-1]

    def assert_old_works(self, fact_ids: list[str], name: str) -> None:
        loaded = self.old("load")
        assert loaded.returncode == 0
        for fact_id in fact_ids:
            assert fact_id in loaded.stdout
        checked = self.old("check")
        assert checked.returncode == 0, checked.stdout + checked.stderr
        added = self.old("add", f"Added under the old tool for {name}", *ADD)
        assert added.returncode == 0, added.stderr
        committed = self.old_commit(name)
        assert committed.returncode == 0, committed.stderr


@pytest.fixture
def tools(repo, old_src, monkeypatch) -> Tools:
    new = Tools(repo, old_src)
    assert new.new("init", "--no-default-rules").returncode == 0
    assert new.new("hooks", "install").returncode == 0
    monkeypatch.setenv("MEMORY_WRITER", "main")
    return new


def test_a_repair_writes_nothing_that_the_old_tool_refuses(tools):
    kept = tools.add("A true fact stays through the roll back")
    tools.append("other.jsonl", json.dumps(_stray_record()) + "\n")
    repaired = tools.new("repair")
    assert repaired.returncode == 0, repaired.stdout
    assert '"repair"' not in tools.stored()
    tools.go_back()
    tools.assert_old_works([kept], "after-repair.txt")
    back = tools.new("check", "--strict")
    assert back.returncode == 0, back.stdout
    assert "differs" not in back.stdout


def _stray_record() -> dict:
    return {
        "type": "fact",
        "id": "f-20261001-beef",
        "kind": "fact",
        "text": "A fact with a writer that is not its file",
        "area": "general",
        "happened_at": "2026-10-01",
        "learned_at": "2026-10-01T10:00:00+00:00",
        "source": "session:1",
        "basis": "seen",
        "status": "active",
        "scope": "long",
        "writer": "someone-else",
    }


def test_a_torn_line_stops_the_old_tool_the_same_with_or_without_a_repair(tools):
    kept = tools.add("A true fact stays through the roll back")
    tools.append("main.jsonl", BAD_TEXT + "\n")
    tools.go_back()
    no_repair = tools.old("check").stdout
    assert tools.old("load").returncode == 0
    assert tools.new("repair").returncode == 0
    with_repair = tools.old("check").stdout
    assert with_repair == no_repair
    assert "type 'repair'" not in with_repair
    assert kept in tools.old("load").stdout
    refused = tools.old_commit("still-torn.txt")
    assert refused.returncode != 0
    assert "not valid JSON" in refused.stderr
    assert "repair" not in refused.stderr.replace("memory repair", "")
    assert tools.new("check", "--strict").returncode == 0


def test_a_repair_from_an_earlier_dev_build_stays_settled(tools):
    tools.append("main.jsonl", BAD_TEXT + "\n")
    assert tools.new("repair").returncode == 0
    file_of_settled = tools.mem / "repairs.jsonl"
    settled = [json.loads(line) for line in file_of_settled.read_text().splitlines()]
    file_of_settled.unlink()
    assert tools.new("check").returncode == 1
    tools.append("main.jsonl", json.dumps({**settled[0], "type": "repair"}) + "\n")
    assert tools.new("check", "--strict").returncode == 0


def test_each_new_field_passes_both_ways(tools):
    env = {"CLAUDECODE": "1"}
    git(tools.root, "switch", "-qc", "feature")
    short = tools.add("A note for this branch only", "--short")
    agent = tools.add("A fact that an agent wrote", env=env)
    rule = tools.new("add", "Run the checks first", "--kind", "rule", *ADD, env=env)
    assert rule.returncode == 0, rule.stderr
    word = tools.add("The job runs as deploy-bot on Sunday")
    tools.append("main.jsonl", '{"type":"fact","text":"password=hunter2hunter2 torn"\n')
    ref = next(
        word for word in tools.new("load").stdout.split() if word.startswith("line-")
    ).rstrip(":,")
    assert tools.new("purge", ref, "--reason", "secret", "--yes").returncode == 0
    assert ref in tools.stored()
    (tools.root / ".env").write_text("ADMIN_PASSWORD=deploy-bot\n")
    git(tools.root, "add", ".gitignore")
    git(tools.root, "config", "core.excludesFile", "/dev/null")
    with (tools.root / ".git" / "info" / "exclude").open("a") as out:
        out.write(".env\n")
    assert tools.new("load").returncode == 0
    assert (tools.mem / ".identity").exists()
    assert (tools.mem / "facts" / ".write.lock").exists()
    assert '"branch_tip"' in tools.stored()
    assert '"author"' in tools.stored()

    tools.go_back()
    tools.assert_old_works([short, agent, word], "after-fields.txt")

    back = tools.new("check", "--strict")
    assert back.returncode == 0 or "`.env`" in back.stdout, back.stdout
    loaded = tools.new("load").stdout
    assert short in loaded and agent in loaded and word in loaded


def test_a_branch_tip_noted_later_passes_the_old_tool(tools):
    git(tools.root, "switch", "-qc", "feature")
    old_note = {
        **_stray_record(),
        "id": "f-20261001-cafe",
        "writer": "main",
        "scope": "short",
        "until_branch_merged": "feature",
        "text": "A note from before the branch tip was stored",
    }
    tools.append("main.jsonl", json.dumps(old_note) + "\n")
    started = subprocess.run(
        [sys.executable, "-m", "cairnkit", "hook", "session-start", "--agent", "claude"],
        cwd=tools.root,
        env=tools._env(HERE / "src", None),
        input="{}",
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert started.returncode == 0, started.stderr
    assert '"branch_tip"' in tools.stored()
    tools.go_back()
    tools.assert_old_works(["f-20261001-cafe"], "after-tip.txt")
