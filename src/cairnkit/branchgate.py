"""The branch-note gate, a test arm that is off by default.

In an agent's shell, with the local git setting on, a commit or a push can refuse until the branch
has a short note, and a push can refuse until that note changed. The refusal prints the command
that fixes it. It looks only at whether a note exists and changed, and it does not read its quality.

Each answer that git does not give, and each state that is not plain work on a branch, lets git go
on. A person never reaches this gate, and a rebase, a merge or a fix of an old commit must not stop.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shlex
import subprocess
from pathlib import Path

from cairnkit import plainfile, skills
from cairnkit.memory import Memory
from cairnkit.paths import Project, default_branch, run_git
from cairnkit.state import effective_status

SETTING = "cairnkit.branchnotegate"
# In the git folder: for each branch, the note at its last push, and the push that may have landed.
STATE_FILE = "cairnkit-branch-notes.json"
REFUSED = 3
_IN_PROGRESS = (
    "MERGE_HEAD",
    "CHERRY_PICK_HEAD",
    "REVERT_HEAD",
    "BISECT_LOG",
    "rebase-merge",
    "rebase-apply",
)
_AMEND = re.compile(r"\bgit\b.*\s--amend\b")
_PROCESS_LEVELS = 4


def _is_on(project: Project) -> bool:
    """The environment comes first, so a person's commit runs no extra git."""
    return (
        skills.in_agent_shell()
        and project.is_git
        and run_git(project.root, "config", "--local", "--type=bool", "--get", SETTING) == "true"
    )


def _note_print(memory: Memory, branch: str) -> str | None:
    """A print of the open short notes of this branch. None when it has no note."""
    notes = sorted(
        f"{state['id']} {state.get('text', '')}"
        for state in memory.states.values()
        if state.get("scope") == "short"
        and state.get("until_branch_merged") == branch
        and effective_status(state)[0] == "active"
    )
    return hashlib.sha256("\n".join(notes).encode()).hexdigest()[:16] if notes else None


def _add_line(branch: str, text: str) -> str:
    return f"  memory add {shlex.quote(f'Branch {branch}: {text}')} --short"


def _no_note(action: str, branch: str) -> str:
    return (
        f"memory: {action} refused. Branch {branch} has no note. Run this with your own words, "
        f"then {action} again:\n"
        + _add_line(branch, "<what it is for>; next: <the next step>; open: <any review finding>")
    )


def _same_note(branch: str) -> str:
    return (
        f"memory: push refused. The note of branch {branch} did not change since its last push. "
        "Run this with your own words, then push again:\n"
        + _add_line(branch, "<what changed>; next: <the next step>; open: <any review finding>")
    )


def _base_refs(root: Path, base: str) -> list[str]:
    """The default branch here and on each remote. A new branch often starts from a fetched tip."""
    found = run_git(root, "for-each-ref", "--format=%(refname)", f"refs/heads/{base}")
    far = run_git(root, "for-each-ref", "--format=%(refname)", f"refs/remotes/*/{base}")
    return [*(found or "").split(), *(far or "").split()]


def _in_progress(root: Path) -> bool:
    """A merge, a rebase or a pick ends with a commit that is not new work on this branch."""
    args = [item for name in _IN_PROGRESS for item in ("--git-path", name)]
    paths = run_git(root, "rev-parse", "--path-format=absolute", *args)
    return paths is None or any(Path(path).exists() for path in paths.splitlines())


def _amending() -> bool:
    """Git tells a pre-commit hook nothing about --amend, so this reads the commands above it."""
    pid = os.getpid()
    for _ in range(_PROCESS_LEVELS):
        try:
            done = subprocess.run(
                ["ps", "-o", "ppid=,args=", "-p", str(pid)],
                capture_output=True,
                text=True,
                errors="replace",
                timeout=1,
                check=False,
            )
        except (OSError, subprocess.SubprocessError):
            return False
        parent, _, command = done.stdout.strip().partition(" ")
        if _AMEND.search(command):
            return True
        if not parent.isdigit() or int(parent) <= 1:
            return False
        pid = int(parent)
    return False


def on_commit(project: Project, flag: str | None) -> str | None:
    """The refusal for this commit, or None. Only a first commit with no note refuses."""
    if not _is_on(project):
        return None
    root = project.root
    branch = run_git(root, "symbolic-ref", "--quiet", "--short", "HEAD")
    base = default_branch(root)
    if not branch or not base or branch == base or _in_progress(root):
        return None
    refs = _base_refs(root, base)
    own = run_git(root, "rev-list", "--max-count=1", "HEAD", "--not", *refs) if refs else None
    if own != "" or _note_print(Memory.open(project, flag), branch) or _amending():
        return None
    return _no_note("commit", branch)


def _read_state(path: Path) -> dict:
    try:
        data = json.loads(plainfile.read_text(path, encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _is_zero(sha: str) -> bool:
    return not sha.strip("0")


def _settle(root: Path, record: dict, far: str) -> None:
    """Git has no hook after a push, so the next push learns from the remote that the last landed.

    A push that failed or a dry run left a commit that the remote does not hold, and it counts for
    nothing.
    """
    pending = record.get("pending")
    if isinstance(pending, dict) and not _is_zero(far):
        landed = run_git(root, "merge-base", "--is-ancestor", str(pending.get("sha")), far)
        if landed is not None:
            record["pushed"] = pending.get("note")
            record.pop("pending")


def _no_new_work(root: Path, base: str, local: str, far: str) -> bool:
    """Only a rebase, a merge of the base or a fix of a message: this push holds no new patch."""
    refs = _base_refs(root, base)
    known = not _is_zero(far) and run_git(root, "cat-file", "-e", f"{far}^{{commit}}") is not None
    own = run_git(root, "rev-list", "--no-merges", local, "--not", *refs, *([far] if known else []))
    if not refs or not own:
        return True
    if not known:
        return False
    patches = run_git(root, "cherry", far, local)
    if patches is None:
        return False
    new = {line[2:] for line in patches.splitlines() if line.startswith("+ ")}
    return not new & set(own.split())


def on_push(project: Project, flag: str | None, refs: str) -> str | None:
    """The refusal for this push, or None. `refs` is what git gives a pre-push hook on stdin."""
    if not _is_on(project) or project.common_dir is None:
        return None
    root = project.root
    base = default_branch(root)
    path = project.common_dir / STATE_FILE
    state = _read_state(path)
    memory = Memory.open(project, flag)
    refusals = []
    for line in refs.splitlines():
        parts = line.split()
        if len(parts) != 4 or not parts[0].startswith("refs/heads/") or _is_zero(parts[1]):
            continue
        branch = parts[0].removeprefix("refs/heads/")
        if not base or branch == base:
            continue
        local, far = parts[1], parts[3]
        record = state.setdefault(branch, {})
        _settle(root, record, far)
        if _no_new_work(root, base, local, far):
            continue
        note = _note_print(memory, branch)
        if note is None:
            refusals.append(_no_note("push", branch))
        elif note == record.get("pushed"):
            refusals.append(_same_note(branch))
        else:
            record["pending"] = {"note": note, "sha": local}
    plainfile.write_text(path, json.dumps(state, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    return "\n".join(refusals) or None


def forget(project: Project, dry_run: bool) -> list[str]:
    """What an uninstall takes back: the state and the setting. Both are in the git folder."""
    path = project.common_dir / STATE_FILE if project.common_dir else None
    has_state = path is not None and path.exists()
    if not has_state and run_git(project.root, "config", "--local", "--get", SETTING) is None:
        return []
    if not dry_run:
        if has_state:
            path.unlink()
        run_git(project.root, "config", "--local", "--unset", SETTING)
    return [f"remove the branch-note gate state and {SETTING}"]
