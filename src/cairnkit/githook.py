"""Git hooks: the pre-commit memory guard, the post-checkout link for a new
worktree, personal pre-push / post-merge / post-commit hooks, and the opt-in
commit-msg guard.

Personal quiet hooks never fail git. post-commit drafts pending candidates
fast (~1s). pre-push and post-merge run the fuller propose + auto-tidy pass
(~3s). Each hook is a marked block in a shell script. A foreign hook is kept:
the block goes right after its first line. Uninstall removes only the block.
"""

from __future__ import annotations

import shlex
import sys
from pathlib import Path

from cairnkit import markers
from cairnkit.paths import Project, run_git

START = "# >>> cairnkit >>>"
END = "# <<< cairnkit <<<"
# The markers before the rename. A block found with them is replaced by a new one.
PAIRS = ((START, END), ("# >>> project-memory >>>", "# <<< project-memory <<<"))
SHELLS = ("sh", "bash", "zsh", "dash", "ksh")
SHARED_DIR = ".githooks"
GUARD_MARK = "# Refuse AI self-attribution lines."
GUARD_REF = "githook:commit-msg"

# Extended regular expressions, matched without case on each line that is not a
# comment. They name AI tools on purpose: the guard exists to catch them.
DEFAULT_GUARD_PATTERNS = [
    "^co-authored-by:.*(claude|anthropic|openai|chatgpt|gpt-?[0-9]|codex|copilot|cursor"
    "|gemini|grok|devin|aider|windsurf|codeium|tabnine|amazon q)",
    "^[^a-z0-9]*generated (with|by) ",
]


def hooks_dir(project: Project) -> Path | None:
    out = run_git(project.root, "rev-parse", "--path-format=absolute", "--git-path", "hooks")
    return Path(out) if out else None


def _inside_worktree(project: Project, folder: Path) -> bool:
    common = project.common_dir.resolve() if project.common_dir else None
    for checkout in project.checkouts:
        try:
            folder.resolve().relative_to(checkout.resolve())
        except ValueError:
            continue
        if common is None:
            return True
        try:
            folder.resolve().relative_to(common)
        except ValueError:
            return True
    return False


def _quote(pattern: str) -> str:
    return "'" + pattern.replace("'", "'\\''") + "'"


def pre_commit_body(shared: bool) -> str:
    if shared:
        # A tracked hook: clones without the tool skip it.
        return "if command -v memory >/dev/null 2>&1; then memory hook pre-commit || exit 1; fi\n"
    py = shlex.quote(sys.executable)
    return f"if [ -x {py} ]; then {py} -m cairnkit hook pre-commit || exit 1; fi\n"


# Wall-clock bound for quiet git hooks. Matches hookrun budgets: the
# in-process SIGALRM only starts after import, so the shell must bound start too.
_QUIET_BUDGET = 3
_POST_COMMIT_BUDGET = 1


def quiet_body(event: str, budget: int | None = None) -> str:
    """A personal hook. It never fails git, and it does not read stdin or arguments.

    Bounds hung process start with timeout/gtimeout when present, else perl's
    alarm+exec (ships on macOS and Linux; alarm survives exec, so there is no
    watcher and no orphan). The perl command runs in a redirected group so
    bash, which is /bin/sh on macOS, does not print its alarm line. With none
    of those tools, the command runs unbounded. Stdout and stderr go to
    /dev/null so a missing package or early failure stays silent. Stdin is
    /dev/null so a pre-push ref list is not eaten. Always ends with || true
    so git proceeds. post-commit uses a 1s shell budget; pre-push/post-merge
    use 3s.
    """
    py = shlex.quote(sys.executable)
    seconds = _QUIET_BUDGET if budget is None else budget
    run = f"{py} -m cairnkit hook {event} </dev/null >/dev/null 2>&1"
    return (
        f"if [ -x {py} ]; then\n"
        f"  if command -v timeout >/dev/null 2>&1; then\n"
        f"    timeout -k 1 {seconds} {run} || true\n"
        f"  elif command -v gtimeout >/dev/null 2>&1; then\n"
        f"    gtimeout -k 1 {seconds} {run} || true\n"
        f"  elif command -v perl >/dev/null 2>&1; then\n"
        f"    {{ perl -e 'alarm {seconds}; exec @ARGV' -- {run} || true; }} >/dev/null 2>&1\n"
        f"  else\n"
        f"    {run} || true\n"
        f"  fi\n"
        f"fi\n"
    )


def pre_push_body() -> str:
    return quiet_body("pre-push")


# refresh.repo_line nudges when a post-merge block lacks this line.
DOCS_CHECK_MARK = "# cairnkit:docs-check"
DOCS_CHECK_WARN = "cairnkit: docs/state looks out of date; run memory docs --force"
_DOCS_CHECK_BUDGET = 1


def _docs_check_python() -> str:
    # Timed child must be PY itself (quiet_body pattern). A nested `sh -c`
    # under timeout orphans the hung interpreter on macOS after the bound.
    # Same compare as `docs --check`; print only the one warn line when stale.
    # One physical shell line (via exec of a small block) so redirects stay
    # on the timeout/gtimeout line with the PY path.
    block = (
        "from cairnkit.paths import find_project\n"
        "from cairnkit.hookrun import has_memory\n"
        "from cairnkit.docs_cmd import Stale, atlas_freshness\n"
        "p = find_project()\n"
        "if not has_memory(p, None):\n"
        "    raise SystemExit(0)\n"
        "r = atlas_freshness(p)\n"
        f"if isinstance(r, Stale):\n"
        f"    print({DOCS_CHECK_WARN!r})\n"
    )
    return f"exec({block!r})"


def docs_check_stanza() -> str:
    py = shlex.quote(sys.executable)
    seconds = _DOCS_CHECK_BUDGET
    run = f"{py} -c {shlex.quote(_docs_check_python())}"
    return (
        f"{DOCS_CHECK_MARK}\n"
        f"# same compare as memory docs --check\n"
        f"if [ -d docs/state ] && [ -x {py} ]; then\n"
        "  if command -v timeout >/dev/null 2>&1; then\n"
        f"    timeout -k 1 {seconds} {run} </dev/null 2>/dev/null || true\n"
        "  elif command -v gtimeout >/dev/null 2>&1; then\n"
        f"    gtimeout -k 1 {seconds} {run} </dev/null 2>/dev/null || true\n"
        "  elif command -v perl >/dev/null 2>&1; then\n"
        f"    {{ perl -e 'alarm {seconds}; exec @ARGV' -- {run} || true; }} "
        "</dev/null 2>/dev/null\n"
        "  else\n"
        f"    {run} </dev/null 2>/dev/null || true\n"
        "  fi\n"
        "fi\n"
    )


def post_merge_body() -> str:
    return docs_check_stanza() + quiet_body("post-merge")


def post_commit_body() -> str:
    return quiet_body("post-commit", budget=_POST_COMMIT_BUDGET)


def post_checkout_body(shared: bool) -> str:
    # Only `git worktree add` (the old HEAD is all zeros). Never fails the git command.
    if shared:
        test, run = "command -v memory >/dev/null 2>&1", "memory"
    else:
        py = shlex.quote(sys.executable)
        test, run = f"[ -x {py} ]", f"{py} -m cairnkit"
    return (
        'case "$1" in\n'
        "  *[!0]*) ;;\n"
        f"  *) if {test}; then {run} hook post-checkout || true; fi ;;\n"
        "esac\n"
    )


def guard_body(patterns: list[str]) -> str:
    args = " ".join(f"-e {_quote(p)}" for p in patterns)
    return (
        f"{GUARD_MARK} Edit the patterns to change the rule.\n"
        f"if grep -v '^#' \"$1\" | grep -iqE {args}; then\n"
        '  echo "commit refused: the message has an AI attribution line:" >&2\n'
        f"  grep -v '^#' \"$1\" | grep -inE {args} >&2\n"
        '  echo "Remove the line and commit again." >&2\n'
        "  exit 1\n"
        "fi\n"
    )


def _block(body: str) -> str:
    return f"{START}\n{body}{END}\n"


def _strip(text: str) -> str:
    _, (start_mark, end_mark) = markers.find(text, PAIRS)
    start, end = text.find(start_mark), text.find(end_mark)
    if start == -1 or end < start:
        return text
    return text[:start] + text[end + len(end_mark) :].removeprefix("\n")


def holds_block(text: str) -> bool:
    """True when text holds a start or an end marker, new or old."""
    return any(mark in text for pair in PAIRS for mark in pair)


class BrokenBlock(Exception):
    """A hook file has a lost marker or two blocks. It must not change."""

    def __init__(self, path: Path):
        super().__init__(str(path))
        self.path = path


def is_broken(path: Path) -> bool:
    try:
        text = path.read_text(errors="replace")
    except OSError:
        return False
    return markers.find(text, PAIRS)[0] == "broken"


def broken_paths(project: Project, hooks: list[str], shared: bool = False) -> list[Path]:
    """The hook files that this install would write and that have broken markers."""
    paths = []
    folder = hooks_dir(project) if project.is_git else None
    if folder is not None and not _inside_worktree(project, folder):
        paths += [folder / hook for hook in hooks]
    if shared:
        paths += [
            project.root / SHARED_DIR / h for h in ("commit-msg", "pre-commit", "post-checkout")
        ]
    return [p for p in paths if is_broken(p)]


def write_block(path: Path, body: str, dry_run: bool) -> list[str]:
    ours = _block(body)
    if not path.exists():
        new = "#!/bin/sh\n" + ours
    else:
        old = path.read_text()
        if markers.find(old, PAIRS)[0] == "broken":
            raise BrokenBlock(path)
        first, _, rest = old.partition("\n")
        is_shell = first.startswith("#!") and any(first.rstrip().endswith(s) for s in SHELLS)
        if not holds_block(old) and not is_shell:
            return [f"skip {path}: not a shell script. Add this by hand:\n{ours}"]
        new = f"{first}\n{ours}{_strip(rest)}"
        if new == old:
            return []
    if not dry_run:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(new)
        path.chmod(path.stat().st_mode | 0o755)
    return [f"write {path}"]


def install(project: Project, hook: str, body: str, dry_run: bool) -> list[str]:
    folder = hooks_dir(project)
    if folder is None:
        return []
    if _inside_worktree(project, folder):
        return [
            f"skip {hook}: core.hooksPath points into the repo ({folder}). "
            f"Add this block to {folder / hook} by hand, or use the shared option:\n" + _block(body)
        ]
    return write_block(folder / hook, body, dry_run)


def install_shared(project: Project, patterns: list[str], dry_run: bool) -> list[str]:
    """Write tracked hooks in .githooks/ that work for clones with no tool."""
    folder = project.root / SHARED_DIR
    steps = write_block(folder / "commit-msg", guard_body(patterns), dry_run)
    steps += write_block(folder / "pre-commit", pre_commit_body(shared=True), dry_run)
    steps += write_block(folder / "post-checkout", post_checkout_body(shared=True), dry_run)
    hooks_path = run_git(project.root, "config", "--get", "core.hooksPath")
    if hooks_path != SHARED_DIR:
        steps.append(
            "note: commit .githooks/ and tell each clone to run once: "
            "git config core.hooksPath .githooks"
        )
    return steps


def guard_installed(project: Project) -> bool:
    """True when git runs our commit-msg guard (local hooks or core.hooksPath)."""
    folder = hooks_dir(project) if project.is_git else None
    hook = folder / "commit-msg" if folder else None
    if hook is None or not hook.is_file():
        return False
    text = hook.read_text(errors="replace")
    return holds_block(text) and GUARD_MARK in text


def uninstall(project: Project, hook: str, dry_run: bool) -> list[str]:
    folder = hooks_dir(project)
    if folder is None or not (folder / hook).exists():
        return []
    path = folder / hook
    old = path.read_text()
    if not holds_block(old):
        return []
    if _inside_worktree(project, folder):
        # Shared hooks are tracked: removing them changes the team's files.
        return [
            f"skip {hook}: core.hooksPath points into the repo ({folder}). "
            f"Remove the marked block from {path} by hand if you mean to."
        ]
    new = _strip(old)
    if not dry_run:
        if new.strip() in ("#!/bin/sh", ""):
            path.unlink()
        else:
            path.write_text(new)
    return [f"update {path}"]
