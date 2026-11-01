"""Git hooks: the pre-commit memory guard, the post-checkout link for a new
worktree, personal pre-push / post-merge hooks, and the attribution guard, which
installs by itself when the memory holds a rule against AI attribution.

The guard is two checks. commit-msg refuses an AI attribution line and an AI author
or committer. pre-push refuses the same in a commit that skipped commit-msg, such as
a rebase or a commit from plumbing. It reads only commits that no remote holds and that
no ref held when the guard was installed, so old history never stops a push. An AI line in
a commit that another person committed is named, not refused.

When core.hooksPath names a folder outside this repo's git folder, git does not read
.git/hooks. A folder in the work tree can be tracked, and a folder elsewhere can serve other
repos, so the tool writes in neither. Our files then live in .git/cairnkit-hooks, and the local
git config runs them beside that folder (git 2.54 or newer). The stored command names no
path, so a moved repo keeps working. core.hooksPath stays as it is.

Personal quiet hooks never fail git, apart from that guard. pre-push and post-merge
run auto-tidy (~3s). Each hook is a marked block in a shell script. A foreign hook is kept:
the block goes right after its first line. Uninstall removes only the block.
"""

from __future__ import annotations

import re
import shlex
import sys
from functools import lru_cache
from pathlib import Path
from typing import NamedTuple

from cairnkit import markers
from cairnkit.paths import LINK_NAME, PATH_FILE, Project, run_git

START = "# >>> cairnkit >>>"
END = "# <<< cairnkit <<<"
# The markers before the rename. A block found with them is replaced by a new one.
PAIRS = ((START, END), ("# >>> project-memory >>>", "# <<< project-memory <<<"))
SHELLS = ("sh", "bash", "zsh", "dash", "ksh")
GUARD_MARK = "# Refuse AI self-attribution lines."
GUARD_REF = "githook:commit-msg"
IDENTITY_MARK = "# Refuse an AI author or committer."
PUSH_MARK = "# Refuse a new commit with an AI identity or attribution line."
# In the git folder: one `^HASH` line for each ref at install. Older commits are not new ones.
BASE_FILE = "cairnkit-guard-base"
# In the git folder, not a hook, so nothing that git passes to a hook can select it. The fix that
# a refused push prints runs it on each commit.
FIX_FILE = "cairnkit-fix-commit"
OLD_FIX_MODE = '"$1" = cairnkit-fix-commit'
PYTHON_GONE_MARK = "# The Python of this hook cannot run the tool."
PERSONAL_HOOKS = ("pre-commit", "post-checkout", "pre-push", "post-merge")
# Under a core.hooksPath outside the git folder, our files live here and the git config runs them.
PRIVATE_DIR = "cairnkit-hooks"
CONFIG_PREFIX = "cairnkit-"
CONFIG_HOOKS_SINCE = "2.54"

# Extended regular expressions, matched without case. They name AI tools on purpose: the
# guard exists to catch them. A name counts only as a whole name, so "Cursor Smith" and
# "Jane Cursor" pass. These names are also people's names, so alone they need a tool word,
# a version or a tool address: "Opus 4.7" is refused, and "Opus <opus@example.com>" passes as
# an author. A trailer that credits a bare model name is refused at any address, because that
# is the line the guard exists to stop. `identity_patterns` and `patterns` can override this.
_PERSON_LIKE = (
    "(claude|devin|fable|opus|sonnet|haiku|mythos|jules|kimi"
    "|kiro|cline|cody|junie|amp|trae|warp|roo|kilo|augment)"
)
_MODEL = "(claude|fable|opus|sonnet|haiku|mythos)"
_NO_REPLY = "<no-?reply[^@>]*@"
_FAMILY = "(opus|sonnet|haiku|fable|mythos)"
_TOOL_WORD = f"(agent|ai|bot|code|cli|assistant|build|model|k[0-9][a-z0-9.]*|{_FAMILY})"
# These words end a model's name, and they are also surnames, so a person-like name cannot use them.
_TIER_WORD = "(pro|mini|max|flash|turbo|lite|ultra)"
_VERSION_END = f"( [0-9][0-9.]*( ({_TOOL_WORD}|{_TIER_WORD}))*)?( \\([^)]*\\))?"
_TOOL = (
    "(anthropic|openai|cursor|copilot|codex|chatgpt|gpt-?[0-9][a-z0-9.]*|gemini|grok|aider"
    "|windsurf|codeium|tabnine|amazon q|opencode|deepseek|llama|qwen[0-9.]*|mistral"
    "|qoder|qodo|zencoder|roocode|kilocode|glm-?[0-9][a-z0-9.]*|o[0-9](-[a-z]+)?)"
)
_MAKER = "((github|openai|anthropic|google|amazon|microsoft) )?"
_NAME = (
    f"{_MAKER}({_TOOL}(-[a-z0-9.-]+)?( ({_TOOL_WORD}|{_TIER_WORD}))*{_VERSION_END}"
    f"|{_PERSON_LIKE}(-({_FAMILY}|code|ai|[0-9])[a-z0-9.-]*|( {_TOOL_WORD})+|( [0-9][0-9.]*))"
    f"{_VERSION_END})"
)
_BOT_NAME = (
    "[^<@]*(claude|codex|copilot|cursor|devin|gemini|grok|jules|aider|windsurf|opencode"
    "|kiro|cline|qoder|zencoder|agent|-ai)[^<@]*\\[bot\\]"
)
# A dotted version in a name is a tool's shape, for a name that no list here holds yet.
_DOTTED = " v?[0-9]+\\.[0-9][0-9.]*"
_ADDRESSES = (
    f"<([0-9]+\\+)?{_BOT_NAME}@users\\.noreply\\.github\\.com>",
    "<([0-9]+\\+)?copilot@users\\.noreply\\.github\\.com>",
    "<copilot@github\\.com>",
    "<(cursoragent|cursor-agent)@",
    "<(noreply|cursor|agent)@cursor\\.(com|sh)>",
    "<(noreply|claude|claude-code)@anthropic\\.com>",
    "<(noreply|codex|chatgpt)@openai\\.com>",
    "<(noreply|aider)@aider\\.(chat|ai)>",
    "<devin@(cognition\\.ai|devin\\.ai)>",
    "<noreply@(x\\.ai|windsurf\\.com|codeium\\.com)>",
    "<no-?reply[^@>]*@[^>]*\\.ai>",
    # A person can work at these companies, so only a tool's own mailbox name counts.
    "<(no-?reply|agent|kiro|qoder|cline|roo|amp|junie|kilo|trae|auggie|cody|warp|zencoder)@"
    "(kiro\\.(dev|ai)|qoder\\.com|cline\\.bot|roocode\\.com|ampcode\\.com|jetbrains\\.com"
    "|kilocode\\.ai|trae\\.ai|augmentcode\\.com|sourcegraph\\.com|warp\\.dev|zencoder\\.ai)>",
)
_CREDIT = "^(co-?authored-by|co-?developed-by|co-?written-by): *"
_TRAILER = (
    "^(co-?authored-by|co-?developed-by|co-?written-by|signed-off-by|assisted-by|authored-by"
    "|written-by|created-by|drafted-by|generated-(by|with)|made-with|created-with|written-with"
    "|ai-[a-z-]+): *"
)
_ANY_NAME = (
    "(\\bai\\b|claude|anthropic|openai|chatgpt|gpt-?[0-9]|codex|copilot|cursor|gemini|grok|devin"
    "|aider|windsurf|codeium|tabnine|amazon q|deepseek|opus|sonnet|haiku|fable|mythos"
    "|\\bkiro\\b|qoder|\\bcline\\b|zencoder|\\bjunie\\b|\\bglm\\b)"
)
# Matched on each line of a commit message that is not a comment.
DEFAULT_GUARD_PATTERNS = [
    f"{_TRAILER}{_NAME}( *<|[ :.]*$|:)",
    f"{_TRAILER}{_PERSON_LIKE}([ .]*$|:| {_NO_REPLY})",
    f"{_TRAILER}{_MODEL} *<",
    f"{_TRAILER}{_BOT_NAME}",
    f"{_TRAILER}[^<]*({'|'.join(_ADDRESSES)})",
    f"{_CREDIT}[^<]*{_DOTTED} *<",
    f"{_CREDIT}[^<]* v?[0-9][0-9.]*[ .]*$",
    f"^assisted-by: *[^:]*:.*{_ANY_NAME}",
    f"{_TRAILER}[^<]* agent( v?[0-9][0-9.]*)?( *<|[ .]*$)",
    "^[^a-z0-9]*generated with ",
    f"^[^a-z0-9]*generated by .*{_ANY_NAME}",
    f"^[^a-z0-9]*(made|written|authored|created|assisted|drafted|co-written)[- ](with|by):? *"
    f"(the )?\\[?({_NAME}|{_PERSON_LIKE})(\\]\\([^)]*\\))?[ .!]*$",
    f"^[^a-z0-9]*{_MAKER}({_PERSON_LIKE}|{_TOOL})( {_TOOL_WORD})* [0-9][0-9.]*[ .]*$",
    "^[^a-z0-9]*(gpt-?[0-9][a-z0-9.]*|o[0-9]-[a-z]+)[ .]*$",
]

# Matched on "Name <email>". A pushed commit follows that with a tab and its id, so a
# pattern must not end in $.
DEFAULT_IDENTITY_PATTERNS = [
    f"^{_NAME} <",
    f"^{_PERSON_LIKE} {_NO_REPLY}",
    f"^{_BOT_NAME} <",
    f"^[^<]*{_DOTTED} <",
    "^[^<]*\\(aider\\) <",
    *_ADDRESSES,
]


ALL_HOOKS = ("pre-commit", "post-checkout", "pre-push", "post-merge", "post-commit", "commit-msg")


class GuardPatterns(NamedTuple):
    message: list[str]
    identity: list[str]


class HookState(NamedTuple):
    line: str
    fixable: bool = False
    dead: bool = False


def git_folder(project: Project) -> Path | None:
    """The folder that git reads hooks from. core.hooksPath can put it in the repo."""
    out = run_git(project.root, "rev-parse", "--path-format=absolute", "--git-path", "hooks")
    return Path(out) if out else None


def _private_dir(project: Project) -> Path | None:
    return project.common_dir / PRIVATE_DIR if project.common_dir else None


def hooks_dir(project: Project) -> Path | None:
    """The folder that holds our hook files. It is always in this repo's git folder."""
    folder = git_folder(project)
    if folder is None or _is_private(project, folder):
        return folder
    return _private_dir(project)


@lru_cache(maxsize=1)
def git_runs_config_hooks() -> bool:
    """Git 2.54 runs hook.<name>.command beside the hooks folder, for each hook event."""
    found = re.search(r"(\d+)\.(\d+)", run_git(Path("."), "version") or "")
    return bool(found) and (int(found[1]), int(found[2])) >= (2, 54)


def _is_private(project: Project, folder: Path) -> bool:
    """True for a folder in this repo's git folder: never tracked, and no other repo reads it."""
    return project.common_dir is not None and folder.resolve().is_relative_to(
        project.common_dir.resolve()
    )


def _quote(pattern: str) -> str:
    return "'" + pattern.replace("'", "'\\''") + "'"


def pre_commit_body() -> str:
    py = shlex.quote(sys.executable)
    private = f"^({re.escape(LINK_NAME)}(/|$)|{re.escape(PATH_FILE)}$)"
    gone = f"memory: the hooks here need {sys.executable}, and it cannot run the tool."
    # With no working Python the fixed private names are still refused, and nothing else is.
    # The import comes first, because a Python without the tool also exits 1.
    return (
        f"if [ -x {py} ] && {py} -c 'import cairnkit' >/dev/null 2>&1; then\n"
        f"  {py} -m cairnkit hook pre-commit || exit 1\n"
        "else\n"
        f"  {PYTHON_GONE_MARK}\n"
        f"  echo {_quote(gone + ' Run `memory init --refresh`.')} >&2\n"
        "  cairnkit_found=$(git diff --cached --name-only --diff-filter=d | "
        f"grep -E {_quote(private)}) || true\n"
        '  if [ -n "$cairnkit_found" ]; then\n'
        '    echo "memory: commit refused. These paths are private memory and must not be '
        'committed:" >&2\n'
        "    printf '%s\\n' \"$cairnkit_found\" >&2\n"
        '    echo "Unstage them with git reset." >&2\n'
        "    exit 1\n"
        "  fi\n"
        "fi\n"
    )


# Wall-clock bound for quiet git hooks. Matches hookrun budgets: the
# in-process SIGALRM only starts after import, so the shell must bound start too.
_QUIET_BUDGET = 3


def quiet_body(event: str) -> str:
    """A personal hook. It never fails git, and it does not read stdin or arguments.

    Bounds hung process start with timeout/gtimeout when present, else perl's
    alarm+exec (ships on macOS and Linux; alarm survives exec, so there is no
    watcher and no orphan). The perl command runs in a redirected group so
    bash, which is /bin/sh on macOS, does not print its alarm line. With none
    of those tools, the command runs unbounded. Stdout and stderr go to
    /dev/null so a missing package or early failure stays silent. Stdin is
    /dev/null so a pre-push ref list is not eaten. Always ends with || true
    so git proceeds. pre-push and post-merge use a 3s shell budget.
    """
    py = shlex.quote(sys.executable)
    seconds = _QUIET_BUDGET
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


def _grep_args(patterns: list[str]) -> str:
    return " ".join(f"-e {_quote(p)}" for p in patterns)


# The config that a refused push prints. An empty list means the defaults, so these match nothing.
_OVERRIDE = (
    "[commit_msg_guard]",
    'patterns = ["^no-such-line$"]',
    'identity_patterns = ["^no-such-identity <"]',
)


def _echo(*lines: str) -> str:
    return "".join(f"  echo {_quote(line)} >&2\n" for line in lines)


_FIX_RUN = f'sh "$(git rev-parse --git-common-dir)/{FIX_FILE}"'

# One fix for each pushed ref that holds a refused commit. Each command can move only that ref.
# The oldest refused commit in it is the start, so the rebase leaves older history as it is.
_FIX_COMMANDS = r"""  cairnkit_q() {
    case "$1" in
      (*[!A-Za-z0-9._/@^:+=,~-]*|'') printf "'%s'" "$(printf '%s' "$1" | sed "s/'/'\\\\''/g")" ;;
      (*) printf '%s' "$1" ;;
    esac
  }
  cairnkit_here=$(git symbolic-ref -q HEAD)
  cairnkit_tip=$(git rev-parse -q --verify HEAD)
  cairnkit_top=$(git rev-parse --show-toplevel 2>/dev/null)
  if [ -n "$cairnkit_here" ]; then cairnkit_back="$(cairnkit_q "${cairnkit_here#refs/heads/}")"
  else cairnkit_back="--detach $cairnkit_tip"; fi
  cairnkit_run='@FIX_RUN@'
  cairnkit_want=$(printf '%s\n' "$cairnkit_refused" | awk '{print $1}' | tr '\n' ' ')
  printf '%s\n' "$cairnkit_refs" | while read -r cairnkit_a cairnkit_new cairnkit_b cairnkit_old; do
    case "$cairnkit_new" in (*[!0]*) ;; (*) continue ;; esac
    cairnkit_known=
    if git cat-file -e "$cairnkit_old^{commit}" 2>/dev/null; then
      cairnkit_known="^$cairnkit_old"
    fi
    cairnkit_oldest=$(git rev-list --abbrev-commit --topo-order --reverse "$cairnkit_new" \
      $cairnkit_known --not --remotes 2>/dev/null | awk -v want="$cairnkit_want" \
      'BEGIN { n = split(want, w, " "); for (i = 1; i <= n; i++) k[w[i]] = 1 }
       $1 in k { print; exit }')
    [ -n "$cairnkit_oldest" ] || continue
    cairnkit_onto=--root
    if git rev-parse -q --verify "$cairnkit_oldest^" >/dev/null; then
      cairnkit_onto="$cairnkit_oldest^"
    fi
    cairnkit_step="rebase --rebase-merges --exec '$cairnkit_run' $cairnkit_onto"
    if [ "$cairnkit_a" = HEAD ] && [ -n "$cairnkit_here" ]; then cairnkit_a=$cairnkit_here; fi
    case "$cairnkit_a" in
      (refs/heads/*)
        cairnkit_name=$(cairnkit_q "${cairnkit_a#refs/heads/}")
        cairnkit_at=$(git worktree list --porcelain | awk -v want="branch $cairnkit_a" \
          '/^worktree /{ p = substr($0, 10) } $0 == want { print p; exit }')
        if [ "$cairnkit_a" = "$cairnkit_here" ]; then
          cairnkit_fix="git $cairnkit_step $cairnkit_name"
        elif [ -n "$cairnkit_at" ] && [ "$cairnkit_at" != "$cairnkit_top" ]; then
          echo "$cairnkit_a is checked out in $cairnkit_at, so the fix runs there:" >&2
          cairnkit_fix="git -C $(cairnkit_q "$cairnkit_at") $cairnkit_step $cairnkit_name"
        else
          cairnkit_fix="git $cairnkit_step $cairnkit_name && git switch $cairnkit_back"
        fi ;;
      (refs/tags/*)
        cairnkit_name=$(cairnkit_q "${cairnkit_a#refs/tags/}")
        echo "$cairnkit_a is a tag, so the fix also moves that tag:" >&2
        if [ "$(git cat-file -t "$cairnkit_a")" = tag ]; then
          cairnkit_move="git tag -l --format='%(contents)' $cairnkit_name"
          cairnkit_move="$cairnkit_move | git tag -f -a -F - $cairnkit_name"
        else
          cairnkit_move="git tag -f $cairnkit_name"
        fi
        cairnkit_fix="git switch --detach $(cairnkit_q "$cairnkit_a") && git $cairnkit_step"
        cairnkit_fix="$cairnkit_fix && $cairnkit_move && git switch $cairnkit_back" ;;
      (HEAD)
        echo "HEAD is on no branch, so the fix moves only HEAD. Then push again:" >&2
        cairnkit_fix="git $cairnkit_step" ;;
      (*)
        echo "$cairnkit_a is not a branch, so the fix pushes the fixed commit by itself:" >&2
        cairnkit_fix="git switch --detach $cairnkit_new && git $cairnkit_step"
        cairnkit_fix="$cairnkit_fix && git push $(cairnkit_q "$1") HEAD:$(cairnkit_q "$cairnkit_b")"
        cairnkit_fix="$cairnkit_fix && git switch $cairnkit_back" ;;
    esac
    if [ "$cairnkit_a" = "$cairnkit_here" ] || [ "$cairnkit_a" = HEAD ]; then
      if [ "$cairnkit_oldest" = "$(git rev-list -1 --abbrev-commit HEAD)" ]; then
        echo "To fix that one commit with no rebase:" >&2
        printf '  %s\n' "$cairnkit_run" >&2
      fi
    fi
    printf '  %s\n' "$cairnkit_fix" >&2
  done
""".replace("@FIX_RUN@", _FIX_RUN)


_FIX_HELPERS = ("cairnkit_identity() ", "cairnkit_message() ")


def _fix_file(helpers: list[str]) -> str:
    """Amend HEAD: drop such lines and an AI author. A commit that a remote holds stays."""
    return (
        "#!/bin/sh\n"
        + "".join(f"{line}\n" for line in helpers)
        + '[ -n "$(git rev-list -1 HEAD --not --remotes)" ] || exit 0\n'
        "cairnkit_reset=\n"
        "if git log -1 --format='%an <%ae>' | cairnkit_identity -q; then "
        "cairnkit_reset=--reset-author; fi\n"
        'if [ -n "$cairnkit_reset" ] '
        "|| git log -1 --format='%cn <%ce>' | cairnkit_identity -q "
        "|| git log -1 --format=%B | cairnkit_message -q; then\n"
        "  git log -1 --format=%B | cairnkit_message -v | "
        "git commit -q --amend --allow-empty --allow-empty-message $cairnkit_reset -F - || exit 1\n"
        "fi\n"
    )


def _push_refusal() -> str:
    return (
        '  echo "push refused: these new commits have an AI identity or attribution line:" >&2\n'
        "  printf '%s\\n' \"$cairnkit_refused\" >&2\n"
        '  if [ ! -f "$cairnkit_base" ]; then\n'
        + _echo(
            f"The file {BASE_FILE} is gone, so each commit that no remote holds counts as new."
        ).replace("  echo", "    echo")
        + "  fi\n"
        f'  if [ -f "$(git rev-parse --git-common-dir)/{FIX_FILE}" ]; then\n'
        + _echo("A fix rewrites each commit from that point, so their hashes change.")
        + _FIX_COMMANDS
        + "  else\n"
        + _echo(f"The file {FIX_FILE} is gone. Run `memory hooks install`, then push again.")
        + "  fi\n"
        + _echo(
            "To allow such lines here, add this to memory-bank/config.toml, "
            "then run `memory hooks install`:",
            *(f"  {line}" for line in _OVERRIDE),
        )
        + "  exit 1\n"
    )


def _push_check(patterns: GuardPatterns) -> str:
    identity, message = _grep_args(patterns.identity), _grep_args(patterns.message)
    return (
        f"{PUSH_MARK} `[commit_msg_guard]` in config.toml sets the patterns.\n"
        f'cairnkit_identity() {{ grep "$@" -iE {identity}; }}\n'
        f'cairnkit_message() {{ grep "$@" -iE {message}; }}\n'
        # A hook that runs after this block in the same file also reads the ref list on stdin.
        # The here-document gives it back.
        "cairnkit_refs=\n"
        "if [ ! -t 0 ]; then cairnkit_refs=$(cat); fi\n"
        'if [ -n "$cairnkit_refs" ]; then\n'
        "  exec <<CAIRNKIT_REFS\n"
        "$cairnkit_refs\n"
        "CAIRNKIT_REFS\n"
        "fi\n"
        f'cairnkit_base="$(git rev-parse --git-common-dir)/{BASE_FILE}"\n'
        # Tab-separated: age, hash, who answers for it, then the identity or the line.
        "cairnkit_scan() {\n"
        "  cairnkit_list=$(grep .)\n"
        '  [ -n "$cairnkit_list" ] || return 0\n'
        "  { printf '%s\\n' \"$cairnkit_list\" | git log --stdin --no-walk "
        "--format='%an <%ae>%x09%h%x09identity' 2>/dev/null | cairnkit_identity\n"
        "    printf '%s\\n' \"$cairnkit_list\" | git log --stdin --no-walk "
        "--format='%cn <%ce>%x09%h%x09identity' 2>/dev/null | cairnkit_identity\n"
        "    printf '%s\\n' \"$cairnkit_list\" | git log --stdin --no-walk "
        "--format='cairnkit-commit %h %ce%n%B' 2>/dev/null | grep -v '^#' "
        "| cairnkit_message -e '^cairnkit-commit ' "
        '| awk \'/^cairnkit-commit /{ h = $2; e = $3; next } { print $0 "\\t" h "\\t" e }\'\n'
        "  } | awk -F'\\t' -v age=\"$1\" "
        '\'{ print age "\\t" $(NF-1) "\\t" $NF "\\t" $1 }\'\n'
        "}\n"
        "cairnkit_found=$(printf '%s\\n' \"$cairnkit_refs\" | "
        "while read -r cairnkit_a cairnkit_new cairnkit_b cairnkit_old; do\n"
        # The leading parens are for bash 3.2, /bin/sh on macOS: it misreads a bare `)` in $().
        '  case "$cairnkit_new" in (*[!0]*) ;; (*) continue ;; esac\n'
        "  cairnkit_known=\n"
        '  if git cat-file -e "$cairnkit_old^{commit}" 2>/dev/null; then '
        'cairnkit_known="^$cairnkit_old"; fi\n'
        '  cairnkit_all=$(git rev-list "$cairnkit_new" $cairnkit_known --not --remotes '
        "2>/dev/null)\n"
        # A shallow clone's edge is a commit that this clone did not make.
        '  cairnkit_since=$({ cat "$cairnkit_base"; '
        "sed 's/^/^/' \"$(git rev-parse --git-path shallow)\"; } 2>/dev/null | "
        'git rev-list --ignore-missing --stdin "$cairnkit_new" $cairnkit_known --not --remotes '
        "2>/dev/null)\n"
        "  printf '%s\\n' \"$cairnkit_since\" | cairnkit_scan new\n"
        '  printf \'%s\\n%s\\n%s\\n\' "$cairnkit_all" "$cairnkit_since" "$cairnkit_since" '
        "| sort | uniq -u | cairnkit_scan old\n"
        "done | sort -u)\n"
        "cairnkit_me=$(git var GIT_COMMITTER_IDENT 2>/dev/null | sed 's/.*<//; s/>.*//')\n"
        "cairnkit_refused=$(printf '%s\\n' \"$cairnkit_found\" | awk -F'\\t' "
        '-v me="$cairnkit_me" '
        '\'$1 == "new" && ($3 == "identity" || $3 == me) { print $2 " " $4 }\')\n'
        'if [ -n "$cairnkit_refused" ]; then\n' + _push_refusal() + "fi\n"
        "cairnkit_named=$(printf '%s\\n' \"$cairnkit_found\" | awk -F'\\t' "
        '-v me="$cairnkit_me" '
        '\'$1 == "new" && $3 != "identity" && $3 != me { print $2 " " $4 }\')\n'
        'if [ -n "$cairnkit_named" ]; then\n'
        '  echo "note: another person committed these lines, so the push goes on:" >&2\n'
        "  printf '%s\\n' \"$cairnkit_named\" >&2\n"
        "fi\n"
        "cairnkit_older=$(printf '%s\\n' \"$cairnkit_found\" | awk -F'\\t' "
        "'$1 == \"old\" { print $2 }' | sort -u | wc -l | tr -d ' ')\n"
        'if [ "$cairnkit_older" != 0 ]; then\n'
        '  echo "note: this push holds $cairnkit_older older commit(s) with an AI identity or '
        'attribution line. The guard came later, so they pass." >&2\n'
        "fi\n"
    )


def pre_push_body(check: GuardPatterns | None = None) -> str:
    return (_push_check(check) if check else "") + quiet_body("pre-push")


def post_merge_body() -> str:
    return quiet_body("post-merge")


def post_checkout_body() -> str:
    # Only `git worktree add` (the old HEAD is all zeros). Never fails the git command.
    py = shlex.quote(sys.executable)
    test, run = f"[ -x {py} ]", f"{py} -m cairnkit"
    return (
        'case "$1" in\n'
        "  *[!0]*) ;;\n"
        f"  *) if {test}; then {run} hook post-checkout || true; fi ;;\n"
        "esac\n"
    )


# Each tool's own switch for the line it adds. They are the owner's global settings, so the
# tool only names them. Check them against each tool's public docs before a change.
TOOL_SETTINGS = (
    'Claude Code: "attribution": {"commit": ""} in ~/.claude/settings.json',
    'Cursor: "attribution": {"attributeCommitsToAgent": false} in ~/.cursor/cli-config.json',
)


def guard_body(patterns: GuardPatterns) -> str:
    message, identity = _grep_args(patterns.message), _grep_args(patterns.identity)
    settings = "".join(f"  echo {_quote('  ' + line)} >&2\n" for line in TOOL_SETTINGS)
    return (
        f"{GUARD_MARK} Edit the patterns to change the rule.\n"
        f"if grep -v '^#' \"$1\" | grep -iqE {message}; then\n"
        '  echo "commit refused: the message has an AI attribution line:" >&2\n'
        f"  grep -v '^#' \"$1\" | grep -inE {message} >&2\n"
        '  echo "Remove the line and commit again." >&2\n'
        '  echo "If a tool added it, tell the owner once. This setting stops it:" >&2\n'
        f"{settings}"
        "  exit 1\n"
        "fi\n"
        f"{IDENTITY_MARK}\n"
        "cairnkit_found=$({ git var GIT_AUTHOR_IDENT; git var GIT_COMMITTER_IDENT; } 2>/dev/null "
        f"| sed 's/ [0-9]* [-+][0-9]*$//' | grep -iE {identity}) || true\n"
        'if [ -n "$cairnkit_found" ]; then\n'
        '  echo "commit refused: the author or committer is an AI tool:" >&2\n'
        "  printf '%s\\n' \"$cairnkit_found\" >&2\n"
        "  echo \"Commit under the owner's name. Check user.name, user.email and the "
        'GIT_AUTHOR_* and GIT_COMMITTER_* variables." >&2\n'
        '  echo "To fix the last commit: git commit --amend --reset-author" >&2\n'
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


def broken_paths(project: Project, hooks: list[str]) -> list[Path]:
    """The hook files that this install would write and that have broken markers."""
    folder = hooks_dir(project) if project.is_git else None
    return [folder / hook for hook in hooks if is_broken(folder / hook)] if folder else []


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


def _config_name(hook: str) -> str:
    return f"hook.{CONFIG_PREFIX}{hook}"


def _command(hook: str) -> str:
    """A path stored here dies when the repo moves, and then git refuses every commit."""
    return f'"$(git rev-parse --path-format=absolute --git-common-dir)"/{PRIVATE_DIR}/{hook}'


def _stored_command(project: Project, hook: str) -> str | None:
    return run_git(project.root, "config", "--local", "--get", f"{_config_name(hook)}.command")


def _is_wired(project: Project, hook: str) -> bool:
    return _stored_command(project, hook) == _command(hook)


def _wire(project: Project, hook: str, dry_run: bool) -> list[str]:
    """Ask git to run our file for this hook event, beside the folder that core.hooksPath names."""
    if _is_wired(project, hook):
        return []
    if not dry_run:
        run_git(project.root, "config", "--local", f"{_config_name(hook)}.event", hook)
        run_git(project.root, "config", "--local", f"{_config_name(hook)}.command", _command(hook))
    return [f"connect {hook} in the local git config, beside core.hooksPath"]


def heal_wiring(project: Project) -> None:
    """Replace a command that an earlier install stored with a path. Never raises."""
    if not project.is_git:
        return
    stored = run_git(
        project.root, "config", "--local", "--get-regexp", r"^hook\.cairnkit-.*\.command$"
    )
    for line in (stored or "").splitlines():
        key, _, value = line.partition(" ")
        hook = key.removeprefix(f"hook.{CONFIG_PREFIX}").removesuffix(".command")
        if value != _command(hook):
            run_git(project.root, "config", "--local", key, _command(hook))


def _remove_block(path: Path, dry_run: bool) -> list[str]:
    if not path.is_file():
        return []
    # Bytes, because a foreign line can hold a CR or any encoding, and it must not change.
    old = path.read_bytes().decode("utf-8", "surrogateescape")
    if not holds_block(old):
        return []
    new = _strip(old)
    if not dry_run:
        if new.strip() in ("#!/bin/sh", ""):
            path.unlink()
        else:
            path.write_bytes(new.encode("utf-8", "surrogateescape"))
    return [f"update {path}"]


def remove_old_post_commit(project: Project) -> None:
    """0.3.1 mined commits from this hook, and its block is our own text in an untracked place.

    Only the folder in the git folder counts. A folder that core.hooksPath names, or a link out
    of the git folder, can be tracked.
    """
    if project.common_dir is None:
        return
    path = project.common_dir / "hooks" / "post-commit"
    if path.resolve().is_relative_to(project.common_dir.resolve()) and not is_broken(path):
        _remove_block(path, False)


def _unwire(project: Project, hook: str, dry_run: bool) -> list[str]:
    private = _private_dir(project)
    if private is None:
        return []
    steps = _remove_block(private / hook, dry_run)
    if _stored_command(project, hook) is not None:
        steps.append(f"disconnect {hook} from the local git config")
        if not dry_run:
            run_git(project.root, "config", "--local", "--remove-section", _config_name(hook))
    if not dry_run and private.is_dir() and not any(private.iterdir()):
        private.rmdir()
    return steps


def _runs_memory(path: Path, hook: str) -> bool:
    """True for a block of ours, or for a line that someone pasted into their own hook."""
    try:
        text = path.read_text(errors="replace")
    except OSError:
        return False
    return holds_block(text) or f"-m cairnkit hook {hook}" in text


def _keep_guard_files(project: Project, body: str) -> None:
    """The files of the push check. An install's base stays, and a lost one is not an install.

    Only a push check that was not running gets a new base. The body holds the check's patterns,
    so the fix file takes its helpers from the text that the hook runs.
    """
    if project.common_dir is None or not project.common_dir.is_dir():
        return
    base, fix = project.common_dir / BASE_FILE, project.common_dir / FIX_FILE
    if PUSH_MARK not in body:
        base.unlink(missing_ok=True)
        fix.unlink(missing_ok=True)
        return
    running = _running_file(project, "pre-push")
    was_on = running is not None and PUSH_MARK in running.read_text(errors="replace")
    if not was_on and not base.exists():
        tips = run_git(project.root, "for-each-ref", "--format=%(objectname)") or ""
        head = run_git(project.root, "rev-parse", "-q", "--verify", "HEAD") or ""
        base.write_text("".join(f"^{sha}\n" for sha in [*tips.split(), *head.split()]))
    helpers = [line for line in body.splitlines() if line.startswith(_FIX_HELPERS)]
    fix.write_text(_fix_file(helpers))


def install(project: Project, hook: str, body: str, dry_run: bool) -> list[str]:
    if hook == "pre-push" and not dry_run:
        _keep_guard_files(project, body)
    folder = git_folder(project)
    if folder is None:
        return []
    if _is_private(project, folder):
        return _unwire(project, hook, dry_run) + write_block(folder / hook, body, dry_run)
    if _runs_memory(folder / hook, hook):
        note = (
            f"note {folder / hook} holds a memory hook from an older version, and each repo "
            "that uses that folder runs it. The tool does not change that folder. "
            "Remove the marked block by hand if no repo needs it."
        )
        return [*_unwire(project, hook, dry_run), note]
    if not git_runs_config_hooks():
        return [
            f"skip {hook}: core.hooksPath is {folder}, and the tool writes only in this repo's "
            f"git folder, so {hook} does not run here. "
            f"Git {CONFIG_HOOKS_SINCE} or newer can run it beside that folder."
        ]
    idle = project.common_dir / "hooks" / hook
    steps = write_block(_private_dir(project) / hook, body, dry_run)
    return steps + _wire(project, hook, dry_run) + _remove_block(idle, dry_run)


def _running_file(project: Project, hook: str) -> Path | None:
    """The file of ours that git runs for this hook, or None."""
    folder = git_folder(project) if project.is_git else None
    if folder is None:
        return None
    private = _private_dir(project) / hook
    if private.is_file() and _is_wired(project, hook) and git_runs_config_hooks():
        return private
    return folder / hook if _runs_memory(folder / hook, hook) else None


def is_running(project: Project, hook: str) -> bool:
    return _running_file(project, hook) is not None


def guard_installed(project: Project) -> bool:
    """True when git runs our commit-msg guard, wherever that file is."""
    path = _running_file(project, "commit-msg")
    return path is not None and GUARD_MARK in path.read_text(errors="replace")


def _dead_wiring(project: Project) -> str | None:
    """A file that the local git config runs and that is gone. A moved repo leaves one."""
    pattern = f"^hook\\.{CONFIG_PREFIX}.*\\.command$"
    listed = run_git(project.root, "config", "--local", "--get-regexp", pattern) or ""
    for line in listed.splitlines():
        stored = line.partition(" ")[2]
        # A command that finds the git folder when it runs has no path that a move can break.
        command = [] if "$(" in stored else shlex.split(stored)
        if command and not Path(command[0]).exists():
            return command[0]
    return None


def hook_state(project: Project) -> HookState:
    """What git really runs here, for `memory check` and `memory status`."""
    folder = git_folder(project) if project.is_git else None
    if folder is None:
        return HookState("")
    dead = _dead_wiring(project)
    if dead:
        return HookState(
            f"git hooks: the local git config runs {dead}, which is gone, so each commit and each "
            "branch switch fails. Run `memory hooks install` now.",
            dead=True,
        )
    setting = run_git(project.root, "config", "--get", "core.hooksPath")
    if any(_stored_command(project, hook) not in (None, _command(hook)) for hook in PERSONAL_HOOKS):
        return HookState(
            "warning: the local git config runs the memory hooks through a path that an earlier "
            "install stored, and a move of this repo breaks it. Run `memory hooks install`.",
            fixable=True,
        )
    missing = [hook for hook in PERSONAL_HOOKS if not is_running(project, hook)]
    idle = any(
        folder != project.common_dir / "hooks"
        and _runs_memory(project.common_dir / "hooks" / hook, hook)
        for hook in PERSONAL_HOOKS
    )
    private = _is_private(project, folder)
    if missing and (idle or not private):
        can_fix = git_runs_config_hooks() or private
        fix = (
            "Run `memory hooks install` to run them beside it. That folder stays as it is."
            if can_fix
            else f"Git {CONFIG_HOOKS_SINCE} or newer can run them beside it."
        )
        return HookState(
            f"warning: core.hooksPath is {setting}, so git does not run the memory hooks. {fix}",
            fixable=can_fix,
        )
    if len(missing) == len(PERSONAL_HOOKS):
        return HookState("git hooks: not installed. `memory hooks install` adds them.")
    if missing:
        names = ", ".join(missing)
        return HookState(f"git hooks: {names} missing. `memory hooks install` adds them.")
    where = _running_file(project, PERSONAL_HOOKS[0]).parent
    shown = (
        where.relative_to(project.root).as_posix() if where.is_relative_to(project.root) else where
    )
    if setting and where == _private_dir(project):
        return HookState(f"git hooks: on, beside core.hooksPath {setting} ({shown})")
    return HookState(f"git hooks: on ({shown})")


def uninstall(project: Project, hook: str, dry_run: bool) -> list[str]:
    if hook == "pre-push" and not dry_run:
        _keep_guard_files(project, "")
    folder = git_folder(project)
    if folder is None:
        return []
    steps = _unwire(project, hook, dry_run)
    if _is_private(project, folder):
        return steps + _remove_block(folder / hook, dry_run)
    steps += _remove_block(project.common_dir / "hooks" / hook, dry_run)
    if (folder / hook).is_file() and holds_block((folder / hook).read_text()):
        # That folder can be tracked, or other repos can use it.
        steps.append(
            f"skip {hook}: core.hooksPath is {folder}, and the tool does not change that folder. "
            f"Remove the marked block from {folder / hook} by hand if you mean to."
        )
    return steps
