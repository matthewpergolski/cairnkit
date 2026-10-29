"""`memory skills status|install`, and the advisory line. Nothing here touches the real machine."""

import io
import json
import os
from pathlib import Path

import pytest
from conftest import git
from test_migrate import old_repo, sibling

from cairnkit import config, skills
from cairnkit.cli import main

CMD = "memory skills install pstack --yes"
SKILLS = ("poteto-mode", "unslop", "tdd")


class World:
    """A fake home, a fake network and a fake `claude` command."""

    def __init__(self, tmp_path: Path, monkeypatch):
        self.home = Path(os.environ["HOME"])
        self.latest = "0.15.32"
        self.fetches = 0
        self.commands: list[list[str]] = []
        self.claude_ok = True
        self.commit = "9580c23696ac8d7abed0c166f2f9918800afb819"
        self.clones = 0
        self.source = tmp_path / "source"
        monkeypatch.setattr(skills, "fetch_text", self._fetch)
        monkeypatch.setattr(
            skills, "_which", lambda name: "/bin/claude" if self.claude_ok else None
        )
        monkeypatch.setattr(skills, "_run", self._run)
        monkeypatch.setattr(skills, "checkout", self._checkout)
        self.make_source()

    def _fetch(self, url):
        self.fetches += 1
        if self.latest is None:
            raise OSError("offline")
        return json.dumps({"name": "pstack", "version": self.latest})

    def _run(self, argv, timeout=120):
        self.commands.append(list(argv))
        return 0, ""

    def _checkout(self):
        self.clones += 1
        return self.source, self.commit

    def make_source(self, names=SKILLS, version=None):
        top = self.source / "pstack"
        for old in (top / "skills").glob("*") if (top / "skills").is_dir() else []:
            for f in sorted(old.rglob("*"), reverse=True):
                f.unlink() if f.is_file() else f.rmdir()
            old.rmdir()
        for name in names:
            folder = top / "skills" / name
            folder.mkdir(parents=True, exist_ok=True)
            (folder / "SKILL.md").write_text(f"---\nname: {name}\n---\nBody of {name}.\n")
        (top / "LICENSE").write_text("MIT License\n")
        (top / "plugin.json").write_text(json.dumps({"version": version or self.latest}))

    def claude(self, version="0.15.32", marketplace=True):
        root = self.home / ".claude" / "plugins"
        path = root / "cache" / "cursor-plugins" / "pstack" / version
        path.mkdir(parents=True)
        (path / "plugin.json").write_text(json.dumps({"name": "pstack", "version": version}))
        entry = {"scope": "user", "installPath": str(path), "version": "wrong"}
        (root / "installed_plugins.json").write_text(
            json.dumps({"version": 2, "plugins": {"pstack@cursor-plugins": [entry]}})
        )
        if marketplace:
            self.marketplace()

    def marketplace(self):
        root = self.home / ".claude" / "plugins"
        root.mkdir(parents=True, exist_ok=True)
        (root / "known_marketplaces.json").write_text(json.dumps({"cursor-plugins": {}}))

    def mark(self, tool, version="0.15.32", names=SKILLS):
        base = skills.skills_dir(tool)
        (base / ".pstack").mkdir(parents=True, exist_ok=True)
        (base / ".pstack" / "install.json").write_text(
            json.dumps({"version": version, "commit": "abc", "skills": list(names)})
        )
        for name in names:
            (base / name).mkdir(exist_ok=True)
            (base / name / "SKILL.md").write_text("x")
        return base

    def dirs(self, *names):
        for name in names:
            (self.home / name).mkdir(parents=True, exist_ok=True)

    def find(self, *tools):
        """Create the user-level home folder that means each tool is present."""
        for tool in tools:
            skills.tool_home(tool).mkdir(parents=True, exist_ok=True)


@pytest.fixture
def world(tmp_path, monkeypatch):
    return World(tmp_path, monkeypatch)


def run(capsys, *argv):
    capsys.readouterr()
    code = main(list(argv))
    return code, capsys.readouterr().out


# --- status -------------------------------------------------------------------------


def test_status_reports_claude_code_installed_and_current(world, capsys):
    world.claude("0.15.32")
    code, out = run(capsys, "skills", "status")
    assert code == 0
    line = next(x for x in out.splitlines() if "Claude Code" in x)
    assert "0.15.32" in line and "up to date" in line
    assert "latest: 0.15.32" in out


def test_status_takes_the_version_from_the_plugin_json(world, capsys):
    world.claude("0.15.30")  # installed_plugins.json says "wrong"
    _, out = run(capsys, "skills", "status")
    line = next(x for x in out.splitlines() if "Claude Code" in x)
    assert "0.15.30" in line and "behind" in line and "0.15.32" in line


def test_status_names_each_tool_that_it_finds_or_not(world, capsys):
    world.dirs(".codex")
    _, out = run(capsys, "skills", "status")
    assert "Codex" in out and "not installed" in next(x for x in out.splitlines() if "Codex" in x)
    assert "not found" in next(x for x in out.splitlines() if "Cursor" in x)
    assert "not found" in next(x for x in out.splitlines() if "OpenCode" in x)
    assert "not found" in next(x for x in out.splitlines() if x.strip().startswith("Pi:"))


def test_status_reads_the_marker_of_a_copied_install(world, capsys):
    world.mark("codex", "0.15.32")
    _, out = run(capsys, "skills", "status")
    assert "0.15.32" in next(x for x in out.splitlines() if "Codex" in x)


# --- the latest version -------------------------------------------------------------


def test_the_latest_version_is_cached_for_one_day(world, monkeypatch):
    monkeypatch.setenv("MEMORY_NOW", "2026-10-24T08:00:00+00:00")
    assert skills.latest_version() == "0.15.32"
    assert skills.latest_version() == "0.15.32"
    assert world.fetches == 1
    monkeypatch.setenv("MEMORY_NOW", "2026-10-24T20:00:00+00:00")
    assert skills.latest_version() == "0.15.32" and world.fetches == 1
    monkeypatch.setenv("MEMORY_NOW", "2026-10-25T09:00:00+00:00")
    world.latest = "0.16.0"
    assert skills.latest_version() == "0.16.0" and world.fetches == 2


def test_offline_the_latest_is_unknown_and_nothing_fails(world, capsys):
    world.claude("0.15.30")
    world.latest = None
    code, out = run(capsys, "skills", "status")
    assert code == 0 and "latest: unknown" in out
    assert skills.advisory() is None  # installed, and no way to say it is behind


def test_offline_keeps_the_last_known_version(world, monkeypatch):
    monkeypatch.setenv("MEMORY_NOW", "2026-10-24T08:00:00+00:00")
    assert skills.latest_version() == "0.15.32"
    world.latest = None
    monkeypatch.setenv("MEMORY_NOW", "2026-10-26T08:00:00+00:00")
    assert skills.latest_version() == "0.15.32"


def test_a_bad_answer_never_raises(world, monkeypatch):
    monkeypatch.setattr(skills, "fetch_text", lambda url: "<html>not json</html>")
    assert skills.latest_version() is None
    monkeypatch.setattr(skills, "fetch_text", lambda url: json.dumps({"version": 5}))
    assert skills.latest_version() is None


# --- the advisory line --------------------------------------------------------------


def test_the_advisory_is_silent_when_every_tool_is_current(world):
    world.claude("0.15.32")
    world.mark("codex")
    assert skills.advisory() is None


def test_the_advisory_is_silent_when_no_tool_is_found(world):
    assert skills.advisory() is None


def test_no_network_when_no_tool_applies(world, mem, capsys, monkeypatch):
    assert skills.advisory() is None  # no tool found
    world.dirs(".codex")
    assert skills.advisory(["claude"]) is None  # a tool is found, but not the one asked for
    assert skills.session_line(mem) is None  # the running tool is not known
    monkeypatch.setenv("CLAUDECODE", "1")
    assert skills.session_line(mem) is None  # it runs Claude Code, which is not found
    for command in ("check", "load"):
        run(capsys, command)
    assert world.fetches == 0


def test_the_advisory_names_a_missing_tool_and_the_one_command(world):
    world.claude("0.15.32")
    world.dirs(".codex")
    line = skills.advisory()
    assert line and "\n" not in line
    assert "Codex" in line and "missing" in line and "Claude Code" not in line
    assert line.endswith(CMD) or CMD in line


def test_the_advisory_names_a_tool_that_is_behind(world):
    world.claude("0.15.30")
    line = skills.advisory()
    assert "Claude Code" in line and "0.15.30" in line and "0.15.32" in line and CMD in line


def test_check_prints_the_advisory_and_load_prints_it(world, mem, capsys, monkeypatch):
    world.dirs(".codex")
    monkeypatch.setenv("CODEX_THREAD_ID", "t1")
    _, out = run(capsys, "check")
    assert CMD in out
    _, out = run(capsys, "load")
    assert CMD in out
    assert sum(CMD in line for line in out.splitlines()) == 1


def test_check_and_load_are_silent_when_current(world, mem, capsys):
    world.claude("0.15.32")
    for command in ("check", "load"):
        _, out = run(capsys, command)
        assert "pstack" not in out


def test_skills_check_false_silences_the_advisory(world, mem, capsys, monkeypatch):
    world.dirs(".codex")
    monkeypatch.setenv("CODEX_THREAD_ID", "t1")
    (mem / "config.toml").write_text("skills_check = false\n")
    for command in ("check", "load"):
        _, out = run(capsys, command)
        assert "pstack" not in out


def test_the_advisory_never_blocks_when_the_check_breaks(world, mem, capsys, monkeypatch):
    monkeypatch.setenv("CODEX_THREAD_ID", "t1")

    def boom():
        raise RuntimeError("broken")

    monkeypatch.setattr(skills, "installed_version", lambda tool: boom())
    world.dirs(".codex")
    assert run(capsys, "check")[0] == 0
    assert run(capsys, "load")[0] == 0


# --- install: the plan --------------------------------------------------------------


def test_install_shows_a_plan_and_changes_nothing_without_yes(world, capsys):
    world.dirs(".claude", ".codex")
    code, out = run(capsys, "skills", "install", "pstack")
    assert code == 0
    assert "claude plugin marketplace add cursor/plugins" in out
    assert "claude plugin install pstack@cursor-plugins --scope user" in out
    assert "Codex" in out and "--yes" in out
    assert world.commands == [] and world.clones == 0
    assert not (world.home / ".codex" / "skills").exists()


def test_install_with_no_tool_found_says_so(world, capsys):
    code, out = run(capsys, "skills", "install", "pstack", "--yes")
    assert code == 0 and "No agent tool found" in out
    assert world.commands == []


# --- install: Claude Code -----------------------------------------------------------


def test_install_claude_adds_the_marketplace_then_the_plugin(world, capsys):
    world.dirs(".claude")
    code, _ = run(capsys, "skills", "install", "pstack", "--yes")
    assert code == 0
    assert world.commands == [
        ["claude", "plugin", "marketplace", "add", "cursor/plugins"],
        ["claude", "plugin", "install", "pstack@cursor-plugins", "--scope", "user"],
    ]


def test_install_claude_skips_a_marketplace_that_is_known(world, capsys):
    world.dirs(".claude")
    world.marketplace()
    run(capsys, "skills", "install", "pstack", "--yes")
    assert world.commands == [
        ["claude", "plugin", "install", "pstack@cursor-plugins", "--scope", "user"]
    ]


def test_install_updates_claude_that_is_behind(world, capsys):
    world.claude("0.15.30")
    code, _ = run(capsys, "skills", "install", "pstack", "--yes")
    assert code == 0
    assert world.commands == [
        ["claude", "plugin", "marketplace", "update", "cursor-plugins"],
        ["claude", "plugin", "update", "pstack@cursor-plugins", "--scope", "user"],
    ]


def test_a_rerun_with_nothing_to_do_says_so(world, capsys):
    world.claude("0.15.32")
    world.mark("codex")
    code, out = run(capsys, "skills", "install", "pstack", "--yes")
    assert code == 0 and "Nothing to do" in out
    assert world.commands == [] and world.clones == 0


def test_install_without_the_claude_command_fails_and_says_why(world, capsys):
    world.dirs(".claude")
    world.claude_ok = False
    code, out = run(capsys, "skills", "install", "pstack", "--yes")
    assert code == 1 and "claude" in out and "not on PATH" in out


def test_a_failed_claude_command_fails_the_install(world, capsys, monkeypatch):
    world.dirs(".claude")
    monkeypatch.setattr(skills, "_run", lambda argv, timeout=120: (1, "boom"))
    code, out = run(capsys, "skills", "install", "pstack", "--yes")
    assert code == 1 and "boom" in out


# --- install: copy for Codex and Cursor ---------------------------------------------


def test_install_codex_copies_the_skills_the_license_and_a_marker(world, capsys):
    world.dirs(".codex")
    code, _ = run(capsys, "skills", "install", "pstack", "--tool", "codex", "--yes")
    assert code == 0
    base = world.home / ".codex" / "skills"
    for name in SKILLS:
        assert (base / name / "SKILL.md").read_text().startswith("---")
    assert (base / ".pstack" / "LICENSE").read_text() == "MIT License\n"
    marker = json.loads((base / ".pstack" / "install.json").read_text())
    assert marker["version"] == "0.15.32" and marker["commit"] == world.commit
    assert sorted(marker["skills"]) == sorted(SKILLS)
    assert world.commands == []


def test_install_cursor_uses_its_user_skills_folder(world, capsys):
    world.dirs(".cursor")
    run(capsys, "skills", "install", "pstack", "--tool", "cursor", "--yes")
    assert (world.home / ".cursor" / "skills" / "unslop" / "SKILL.md").is_file()


def test_opencode_detection_uses_xdg_config_home(world, monkeypatch):
    other = world.home / "xdg-config"
    monkeypatch.setenv("XDG_CONFIG_HOME", str(other))
    assert not skills.detected("opencode")
    (other / "opencode").mkdir(parents=True)
    assert skills.detected("opencode")
    assert skills.skills_dir("opencode") == other / "opencode" / "skills"


def test_xdg_config_home_outside_fake_home_is_honoured_and_isolated(
    world, tmp_path_factory, monkeypatch
):
    """An explicit XDG_CONFIG_HOME wins even when it is not under HOME.

    The shared fixture pins XDG under the fake machine; this test then points
    it somewhere else entirely and checks HOME/.config/opencode is never used.
    """
    outside = tmp_path_factory.mktemp("xdg-outside-home")
    assert not outside.resolve().is_relative_to(Path.home().resolve())
    home_config = Path.home() / ".config" / "opencode"
    monkeypatch.setenv("XDG_CONFIG_HOME", str(outside))
    assert skills.tool_home("opencode") == outside / "opencode"
    assert skills.skills_dir("opencode") == outside / "opencode" / "skills"
    assert not skills.detected("opencode")
    (outside / "opencode").mkdir(parents=True)
    assert skills.detected("opencode")
    world.mark("opencode", "0.15.32")
    assert (outside / "opencode" / "skills" / ".pstack" / "install.json").is_file()
    assert not home_config.exists()


def test_fixture_pins_xdg_config_home_under_the_fake_machine(world):
    """Default test env must not inherit a runner XDG_CONFIG_HOME."""
    xdg = Path(os.environ["XDG_CONFIG_HOME"])
    assert xdg.is_absolute()
    assert not xdg.resolve().is_relative_to(Path.home().resolve())
    assert skills.tool_home("opencode") == xdg / "opencode"


def test_pi_detection_uses_dot_pi_and_skills_under_agent(world):
    assert not skills.detected("pi")
    world.find("pi")
    assert skills.detected("pi")
    assert skills.skills_dir("pi") == world.home / ".pi" / "agent" / "skills"


def test_status_reports_opencode_and_pi_found_or_not(world, capsys):
    world.find("opencode")
    world.mark("opencode", "0.15.30")
    _, out = run(capsys, "skills", "status")
    open_line = next(x for x in out.splitlines() if "OpenCode" in x)
    pi_line = next(x for x in out.splitlines() if x.strip().startswith("Pi:"))
    assert "0.15.30" in open_line and "behind" in open_line
    assert "not found" in pi_line


def test_status_reads_the_marker_for_opencode_and_pi(world, capsys):
    world.find("opencode", "pi")
    world.mark("opencode", "0.15.32")
    world.mark("pi", "0.15.32")
    _, out = run(capsys, "skills", "status")
    assert "up to date" in next(x for x in out.splitlines() if "OpenCode" in x)
    assert "up to date" in next(x for x in out.splitlines() if x.strip().startswith("Pi:"))


def test_install_plan_for_opencode_and_pi_changes_nothing(world, capsys):
    world.find("opencode", "pi")
    code, out = run(capsys, "skills", "install", "pstack", "--tool", "opencode")
    assert code == 0
    assert "OpenCode" in out and str(skills.skills_dir("opencode")) in out
    assert "--yes" in out and world.clones == 0
    assert not skills.skills_dir("opencode").exists()
    code, out = run(capsys, "skills", "install", "pstack", "--tool", "pi")
    assert code == 0
    assert "Pi" in out and str(skills.skills_dir("pi")) in out
    assert not skills.skills_dir("pi").exists()


def test_install_opencode_copies_to_config_skills(world, capsys):
    world.find("opencode")
    code, _ = run(capsys, "skills", "install", "pstack", "--tool", "opencode", "--yes")
    assert code == 0
    base = skills.skills_dir("opencode")
    for name in SKILLS:
        assert (base / name / "SKILL.md").is_file()
    marker = json.loads((base / ".pstack" / "install.json").read_text())
    assert marker["version"] == "0.15.32" and sorted(marker["skills"]) == sorted(SKILLS)
    assert not (world.home / ".agents" / "skills").exists()
    assert not (world.home / ".claude" / "skills").exists()


def test_install_pi_copies_to_agent_skills(world, capsys):
    world.find("pi")
    code, _ = run(capsys, "skills", "install", "pstack", "--tool", "pi", "--yes")
    assert code == 0
    base = skills.skills_dir("pi")
    assert (base / "tdd" / "SKILL.md").is_file()
    assert json.loads((base / ".pstack" / "install.json").read_text())["version"] == "0.15.32"
    assert not (world.home / ".agents" / "skills").exists()


def test_advisory_names_opencode_when_missing(world):
    world.find("opencode")
    line = skills.advisory()
    assert line and "OpenCode" in line and "missing" in line and CMD in line


def test_the_default_installs_every_tool_that_it_finds(world, capsys):
    world.dirs(".claude", ".codex")
    run(capsys, "skills", "install", "pstack", "--yes")
    assert (world.home / ".codex" / "skills" / "tdd" / "SKILL.md").is_file()
    assert not (world.home / ".cursor" / "skills").exists()
    assert any(c[:3] == ["claude", "plugin", "install"] for c in world.commands)


def test_a_copy_install_rerun_changes_nothing(world, capsys):
    world.dirs(".codex")
    run(capsys, "skills", "install", "pstack", "--tool", "codex", "--yes")
    world.clones = 0
    code, out = run(capsys, "skills", "install", "pstack", "--tool", "codex", "--yes")
    assert code == 0 and "Nothing to do" in out and world.clones == 0


def test_an_update_replaces_owned_skills_and_drops_the_ones_that_left(world, capsys):
    world.dirs(".codex")
    run(capsys, "skills", "install", "pstack", "--tool", "codex", "--yes")
    world.latest = "0.16.0"
    world.make_source(names=("unslop", "tdd", "newone"), version="0.16.0")
    (world.home / ".codex" / "skills" / "tdd" / "SKILL.md").write_text("old local edit")
    code, _ = run(capsys, "skills", "install", "pstack", "--tool", "codex", "--yes")
    base = world.home / ".codex" / "skills"
    assert code == 0
    assert (base / "newone" / "SKILL.md").is_file()
    assert not (base / "poteto-mode").exists()
    assert "Body of tdd" in (base / "tdd" / "SKILL.md").read_text()
    assert json.loads((base / ".pstack" / "install.json").read_text())["version"] == "0.16.0"


def test_a_skill_of_the_user_with_the_same_name_is_kept(world, capsys):
    world.dirs(".codex")
    mine = world.home / ".codex" / "skills" / "tdd"
    mine.mkdir(parents=True)
    (mine / "SKILL.md").write_text("mine")
    code, out = run(capsys, "skills", "install", "pstack", "--tool", "codex", "--yes")
    assert code == 0 and (mine / "SKILL.md").read_text() == "mine"
    assert "tdd" in out and "kept" in out
    assert (world.home / ".codex" / "skills" / "unslop" / "SKILL.md").is_file()


def test_clean_install_copies_every_skill_and_reports_counts(world, capsys):
    world.dirs(".codex")
    code, out = run(capsys, "skills", "install", "pstack", "--tool", "codex", "--yes")
    assert code == 0
    base = world.home / ".codex" / "skills"
    for name in SKILLS:
        assert (base / name / "SKILL.md").is_file()
    assert "3 skill(s) installed" in out or "installed 3" in out
    assert "0 skipped" in out
    marker = json.loads((base / ".pstack" / "install.json").read_text())
    assert sorted(marker["skills"]) == sorted(SKILLS)


def test_preexisting_same_named_are_kept_without_adopt_and_counts_say_why(world, capsys):
    world.dirs(".codex")
    base = world.home / ".codex" / "skills"
    for name in SKILLS:
        (base / name).mkdir(parents=True)
        (base / name / "SKILL.md").write_text(f"mine {name}")
    code, out = run(capsys, "skills", "install", "pstack", "--tool", "codex", "--yes")
    assert code == 0
    for name in SKILLS:
        assert (base / name / "SKILL.md").read_text() == f"mine {name}"
    assert "0 skill(s) installed" in out or "installed 0" in out
    assert "3 skipped" in out
    assert "kept your own" in out
    marker = json.loads((base / ".pstack" / "install.json").read_text())
    assert marker["skills"] == []


def test_adopt_replaces_same_named_folders_and_installs_every_skill(world, capsys):
    world.dirs(".codex")
    base = world.home / ".codex" / "skills"
    for name in SKILLS:
        (base / name).mkdir(parents=True)
        (base / name / "SKILL.md").write_text(f"mine {name}")
    code, out = run(capsys, "skills", "install", "pstack", "--tool", "codex", "--adopt", "--yes")
    assert code == 0
    for name in SKILLS:
        assert "Body of" in (base / name / "SKILL.md").read_text()
    assert "3 skill(s) installed" in out or "installed 3" in out
    assert "0 skipped" in out
    assert "adopt" in out.lower() or "replaced" in out.lower()
    marker = json.loads((base / ".pstack" / "install.json").read_text())
    assert sorted(marker["skills"]) == sorted(SKILLS)


def test_all_flag_is_the_same_as_adopt(world, capsys):
    world.dirs(".cursor")
    base = world.home / ".cursor" / "skills"
    (base / "tdd").mkdir(parents=True)
    (base / "tdd" / "SKILL.md").write_text("mine")
    code, _out = run(capsys, "skills", "install", "pstack", "--tool", "cursor", "--all", "--yes")
    assert code == 0
    assert "Body of tdd" in (base / "tdd" / "SKILL.md").read_text()
    assert sorted(json.loads((base / ".pstack" / "install.json").read_text())["skills"]) == sorted(
        SKILLS
    )


def test_stale_marker_partial_install_is_filled_on_rerun(world, capsys):
    """A marker that lists only some skills must not block installing the rest."""
    world.dirs(".codex")
    base = world.mark("codex", names=("tdd",))  # version matches latest; only one owned
    skills.record_catalog(len(SKILLS))
    # Pretend an earlier plugin left the other names (unowned): they were "kept".
    for name in ("poteto-mode", "unslop"):
        (base / name).mkdir()
        (base / name / "SKILL.md").write_text(f"old plugin {name}")
    # Without --adopt: missing owned gaps are none; unowned stay. Status must show partial.
    _, status = run(capsys, "skills", "status")
    line = next(x for x in status.splitlines() if "Codex" in x)
    assert "1/3" in line or "1 of 3" in line
    # --adopt claims the leftover same-named folders so every skill is owned and current.
    code, out = run(capsys, "skills", "install", "pstack", "--tool", "codex", "--adopt", "--yes")
    assert code == 0
    assert "Nothing to do" not in out
    for name in SKILLS:
        assert "Body of" in (base / name / "SKILL.md").read_text()
    marker = json.loads((base / ".pstack" / "install.json").read_text())
    assert sorted(marker["skills"]) == sorted(SKILLS)
    assert "3 skill(s) installed" in out or "installed 3" in out


def test_status_shows_installed_vs_available_skill_counts(world, capsys):
    world.dirs(".codex")
    world.mark("codex", names=("tdd", "unslop"))  # 2 of 3 from the fake source catalog
    # Seed the catalog count the status line reads (same place install writes).
    skills.record_catalog(len(SKILLS))
    _, out = run(capsys, "skills", "status")
    line = next(x for x in out.splitlines() if "Codex" in x)
    assert "2/3" in line or "2 of 3" in line


def test_install_touches_no_tracked_file_in_a_repo(world, repo, capsys):
    world.dirs(".codex", ".claude")
    run(capsys, "skills", "install", "pstack", "--yes")
    assert git(repo, "status", "--porcelain") == ""


def test_a_failed_checkout_fails_the_install_and_copies_nothing(world, capsys, monkeypatch):
    world.dirs(".codex")

    def fail():
        raise OSError("no network")

    monkeypatch.setattr(skills, "checkout", fail)
    code, out = run(capsys, "skills", "install", "pstack", "--tool", "codex", "--yes")
    assert code == 1 and "no network" in out
    assert not (world.home / ".codex" / "skills").exists()


# --- the session-start hook and auto update -----------------------------------------


def start(capsys, monkeypatch, agent="claude"):
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps({"session_id": "s"})))
    capsys.readouterr()
    assert main(["hook", "session-start", "--agent", agent]) == 0
    return capsys.readouterr().out


def test_session_start_shows_the_advisory_and_installs_nothing_by_default(
    world, mem, capsys, monkeypatch
):
    world.dirs(".codex")
    out = start(capsys, monkeypatch, "codex")
    assert CMD in out
    assert world.clones == 0 and not (world.home / ".codex" / "skills").exists()


def test_session_start_updates_when_skills_auto_update_is_true(world, mem, capsys, monkeypatch):
    world.dirs(".codex")
    (mem / "config.toml").write_text("skills_auto_update = true\n")
    out = start(capsys, monkeypatch)
    assert (world.home / ".codex" / "skills" / "tdd" / "SKILL.md").is_file()
    assert "pstack updated" in out and "Codex" in out
    assert CMD not in out  # it is current now
    assert sum("pstack" in line for line in out.splitlines()) == 1


def test_auto_update_is_silent_when_current(world, mem, capsys, monkeypatch):
    world.claude("0.15.32")
    (mem / "config.toml").write_text("skills_auto_update = true\n")
    out = start(capsys, monkeypatch)
    assert "pstack" not in out and world.commands == []


def test_auto_update_that_fails_still_starts_the_session(world, mem, capsys, monkeypatch):
    world.dirs(".codex")
    (mem / "config.toml").write_text("skills_auto_update = true\n")

    def fail():
        raise OSError("no network")

    monkeypatch.setattr(skills, "checkout", fail)
    out = start(capsys, monkeypatch, "codex")
    assert "auto-update failed" in out and CMD in out


# --- init and migrate ---------------------------------------------------------------


def test_init_ends_with_the_advisory(world, repo, capsys):
    world.dirs(".codex")
    _, out = run(capsys, "init", "--no-default-rules")
    assert out.strip().splitlines()[-1].endswith(CMD) or CMD in out.splitlines()[-1]


def test_init_is_silent_when_skills_are_current(world, repo, capsys):
    world.claude("0.15.32")
    _, out = run(capsys, "init", "--no-default-rules")
    assert "pstack" not in out


def test_migrate_lists_the_install_in_the_follow_up_task(world, repo, capsys):
    world.dirs(".codex")
    old_repo(repo)
    code, out = run(capsys, "migrate", "--yes", "--no-default-rules")
    assert code == 0 and CMD in out
    task = (sibling(repo, ".memory") / "proposals" / "migrate-followups.md").read_text()
    assert task.startswith("# Migration follow-up (pending)")
    assert CMD in task


def test_skills_check_false_keeps_migrate_off_the_network(world, repo, capsys, monkeypatch):
    # migrate makes config.toml itself, so set the value through the defaults.
    monkeypatch.setitem(config.DEFAULTS, "skills_check", False)
    world.dirs(".codex")
    old_repo(repo)
    _, out = run(capsys, "migrate", "--yes", "--no-default-rules")
    assert "pstack" not in out
    assert world.fetches == 0
    task = sibling(repo, ".memory") / "proposals" / "migrate-followups.md"
    assert not task.exists() or CMD not in task.read_text()


def test_migrate_task_has_no_install_line_when_current(world, repo, capsys):
    world.claude("0.15.32")
    old_repo(repo)
    _, out = run(capsys, "migrate", "--yes", "--no-default-rules")
    assert "pstack" not in out
    path = sibling(repo, ".memory") / "proposals" / "migrate-followups.md"
    assert not path.exists() or CMD not in path.read_text()


# --- quiet: only the tool that runs this session, and not forever -------------------


@pytest.mark.parametrize(
    "marker,tool,value",
    [
        ("CLAUDECODE", "claude", "1"),
        ("CODEX_THREAD_ID", "codex", "1"),
        ("CODEX_SANDBOX", "codex", "1"),
        ("CODEX_CI", "codex", "1"),
        ("CURSOR_AGENT", "cursor", "1"),
        ("CURSOR_TRACE_ID", "cursor", "1"),
        ("OPENCODE", "opencode", "1"),
        ("OPENCODE_SESSION_ID", "opencode", "s1"),
        ("PI_CODING_AGENT", "pi", "true"),
    ],
)
def test_the_running_tool_comes_from_the_environment(monkeypatch, marker, tool, value):
    monkeypatch.setenv(marker, value)
    assert skills.running_tool() == tool


def test_the_running_tool_is_unknown_with_no_marker_or_with_two(monkeypatch):
    assert skills.running_tool() is None
    monkeypatch.setenv("CLAUDECODE", "1")
    monkeypatch.setenv("CURSOR_AGENT", "1")
    assert skills.running_tool() is None


def test_the_hook_agent_beats_the_environment(monkeypatch):
    monkeypatch.setenv("CLAUDECODE", "1")
    assert skills.running_tool("codex") == "codex"
    assert skills.running_tool("generic") == "claude"


def test_a_session_hears_only_about_its_own_tool(world, mem, capsys, monkeypatch):
    world.dirs(".codex", ".cursor")
    world.find("opencode", "pi")
    monkeypatch.setenv("CODEX_THREAD_ID", "t1")
    for command in ("check", "load"):
        _, out = run(capsys, command)
        line = next(x for x in out.splitlines() if "pstack" in x)
        assert "Codex" in line and "Cursor" not in line
        assert "OpenCode" not in line and "Pi" not in line


def test_an_opencode_session_hears_only_about_opencode(world, mem, capsys, monkeypatch):
    world.find("opencode", "pi")
    monkeypatch.setenv("OPENCODE", "1")
    _, out = run(capsys, "check")
    line = next(x for x in out.splitlines() if "pstack" in x)
    assert "OpenCode" in line and "Pi" not in line


def test_an_unknown_session_hears_nothing(world, mem, capsys, monkeypatch):
    world.dirs(".codex", ".cursor", ".claude")
    for command in ("check", "load"):
        _, out = run(capsys, command)
        assert "pstack" not in out
    assert "pstack" not in start(capsys, monkeypatch, "generic")


def test_the_hook_names_the_tool_that_called_it(world, mem, capsys, monkeypatch):
    world.dirs(".codex", ".cursor")
    out = start(capsys, monkeypatch, "cursor")
    line = next(x for x in out.splitlines() if "pstack" in x)
    assert "Cursor" in line and "Codex" not in line
    assert "pstack" not in start(capsys, monkeypatch, "claude")  # not found on this machine


def test_status_by_hand_still_lists_every_tool(world, capsys, monkeypatch):
    world.dirs(".codex", ".cursor")
    monkeypatch.setenv("CODEX_THREAD_ID", "t1")
    _, out = run(capsys, "skills", "status")
    assert "Codex" in out and "Cursor" in out and "Claude Code" in out
    assert "OpenCode" in out and "Pi:" in out


def _shown(out):
    return sum(CMD in line for line in out.splitlines())


def test_a_behind_line_stops_after_three_sessions(world, mem, capsys, monkeypatch):
    world.claude("0.15.30")
    shown = [_shown(start(capsys, monkeypatch, "claude")) for _ in range(5)]
    assert shown == [1, 1, 1, 0, 0]
    assert "pstack" not in run(capsys, "load")[1]
    assert "pstack" not in run(capsys, "check")[1]


def test_a_newer_latest_brings_the_line_back_for_three_more(world, mem, capsys, monkeypatch):
    world.claude("0.15.30")
    monkeypatch.setenv("MEMORY_NOW", "2026-10-24T08:00:00+00:00")
    for _ in range(4):
        start(capsys, monkeypatch, "claude")
    world.latest = "0.16.0"
    monkeypatch.setenv("MEMORY_NOW", "2026-10-26T08:00:00+00:00")
    shown = [_shown(start(capsys, monkeypatch, "claude")) for _ in range(4)]
    assert shown == [1, 1, 1, 0]
    assert "0.16.0" in skills.advisory(["claude"])


def test_a_manual_load_or_check_does_not_use_up_the_three(world, mem, capsys, monkeypatch):
    world.claude("0.15.30")
    monkeypatch.setenv("CLAUDECODE", "1")
    for _ in range(5):
        assert _shown(run(capsys, "load")[1]) == 1
        assert _shown(run(capsys, "check")[1]) == 1
    assert _shown(start(capsys, monkeypatch, "claude")) == 1


def test_the_count_is_kept_in_a_small_file_in_the_memory_folder(world, mem, capsys, monkeypatch):
    world.claude("0.15.30")
    start(capsys, monkeypatch, "claude")
    state = json.loads((mem / ".skills-advisory.json").read_text())
    assert state["shown"]["claude"]["sessions"] == 1


def test_a_broken_state_file_never_blocks(world, mem, capsys, monkeypatch):
    world.claude("0.15.30")
    (mem / ".skills-advisory.json").write_text("{not json")
    assert _shown(start(capsys, monkeypatch, "claude")) == 1


def test_init_mentions_found_tools_once_per_memory_folder(world, repo, capsys):
    world.dirs(".codex", ".cursor")
    _, out = run(capsys, "init", "--no-default-rules")
    line = next(x for x in out.splitlines() if "pstack" in x)
    assert "Codex" in line and "Cursor" in line
    _, again = run(capsys, "init", "--no-default-rules")
    assert "pstack" not in again


def test_init_dry_run_does_not_use_up_the_one_mention(world, repo, capsys):
    world.dirs(".codex")
    assert CMD in run(capsys, "init", "--dry-run", "--no-default-rules")[1]
    assert CMD in run(capsys, "init", "--no-default-rules")[1]
    assert "pstack" not in run(capsys, "init", "--no-default-rules")[1]


def test_init_says_nothing_for_a_tool_that_is_not_found(world, repo, capsys):
    world.claude("0.15.32")
    assert "pstack" not in run(capsys, "init", "--no-default-rules")[1]


def test_migrate_mentions_once_but_the_task_keeps_its_item(world, repo, capsys):
    world.dirs(".codex")
    old_repo(repo)
    _, out = run(capsys, "migrate", "--yes", "--no-default-rules")
    assert _shown(out) == 1
    task = sibling(repo, ".memory") / "proposals" / "migrate-followups.md"
    assert CMD in task.read_text()
    _, again = run(capsys, "migrate", "--yes", "--no-default-rules")
    assert "pstack" not in again
    assert CMD in task.read_text()
