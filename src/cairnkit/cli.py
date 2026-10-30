"""cairnkit (short name: memory): a private, dated memory for any project, kept outside
the repo."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from cairnkit import __version__
from cairnkit.clock import parse_time
from cairnkit.schema import BASES, KINDS, STATUSES

# The agent tools the hook command knows. Kept here so building the parser imports no adapter.
AGENTS = ("claude", "codex", "cursor", "generic")


def _time(value: str) -> str:
    try:
        parse_time(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"{value!r} is not an ISO 8601 date or date-time") from exc
    return value


def build_parser() -> argparse.ArgumentParser:
    # Two commands run this: cairnkit, and its short name memory.
    prog = "cairnkit" if Path(sys.argv[0]).name == "cairnkit" else "memory"
    parser = argparse.ArgumentParser(prog=prog, description=__doc__)
    parser.add_argument("--version", action="version", version=f"{prog} {__version__}")
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--path", help="memory folder (else MEMORY_DIR, .memory-path, default)")
    sub = parser.add_subparsers(dest="command", metavar="COMMAND")

    p = sub.add_parser(
        "init", parents=[common], help="make the memory folder and link it into each checkout"
    )
    p.add_argument("--dry-run", action="store_true", help="show the steps; change nothing")
    p.add_argument(
        "--gitignore",
        action="store_true",
        help="also add the ignore lines to .gitignore (default: only .git/info/exclude)",
    )
    p.add_argument(
        "--refresh",
        action="store_true",
        help="rewrite the rules block and hooks that memory wrote here, in place",
    )
    p.add_argument(
        "--write-instructions",
        nargs="?",
        const="local",
        choices=("local", "shared"),
        help="add the agent rules block to CLAUDE.local.md (ignored by git), plus untracked "
        "harness copies; moves any cairnkit block out of tracked CLAUDE.md / AGENTS.md. "
        "shared is refused",
    )
    p.add_argument(
        "--instructions-file",
        help="untracked file for --write-instructions, relative to the checkout",
    )

    p.add_argument(
        "--preset",
        action="append",
        metavar="NAME",
        help="add the rules of a preset: commits, basic, dev or none (the default); "
        "repeat to stack presets",
    )
    p.add_argument(
        "--no-default-rules", action="store_true", help="add no rule facts (same as --preset none)"
    )

    p = sub.add_parser(
        "migrate",
        parents=[common],
        help="fold a prose memory folder (memory-bank) into the memory",
        description="Move an old prose memory folder out of the repo (to <repo>.memory-old, "
        "never deleted), run `memory init`, copy the old files into notes/, and write a "
        "worklist of candidate facts (proposals/migrate-candidates.jsonl). It writes no "
        "fact and calls no model. Without --yes it shows the plan and changes nothing: run "
        "`memory migrate`, read the plan, then run `memory migrate --yes`. Add "
        "--fix-references to also rewrite old paths in docs and add hooks. What needs "
        "judgment goes to proposals/migrate-followups.md, a task for an agent. A rerun "
        "finishes a run that stopped.",
    )
    p.add_argument(
        "--from",
        dest="from_dir",
        default="memory-bank",
        metavar="DIR",
        help="the old folder, inside the project (default: memory-bank)",
    )
    p.add_argument(
        "--yes",
        action="store_true",
        help="do it. Without --yes, migrate only shows the plan and changes nothing",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="show the plan (the default; kept for compatibility). Refused with --yes",
    )
    p.add_argument(
        "--preset",
        action="append",
        metavar="NAME",
        help="rules to add, as for `memory init`: commits, basic, dev or none (the default)",
    )
    p.add_argument("--no-default-rules", action="store_true", help="same as --preset none")
    p.add_argument(
        "--untrack",
        action="store_true",
        help="when git tracks the old folder, remove it from the index (never commits)",
    )
    p.add_argument(
        "--fix-references",
        action="store_true",
        help="also rewrite old paths (memory-bank/X to memory-bank/notes/X) in top-level and "
        "docs *.md files, and add the memory hooks where a hook runs the old checker. Working "
        "tree only; never commits. Needs --yes to act",
    )

    p = sub.add_parser("preset", help="list, show or add rule presets")
    preset_sub = p.add_subparsers(dest="preset_command", metavar="ACTION", required=True)
    preset_sub.add_parser("list", help="list the presets")
    h = preset_sub.add_parser("show", help="print the rules of a preset")
    h.add_argument("name")
    h.add_argument(
        "--detect", action="store_true", help="say which rules init would add in this project"
    )
    h = preset_sub.add_parser(
        "add", parents=[common], help="add the missing rules of presets to this memory"
    )
    h.add_argument("names", nargs="*", metavar="NAME")
    h.add_argument(
        "--file",
        action="append",
        default=[],
        metavar="PATH",
        help="add the rules of a preset file that the project owns (same format); "
        "repeat for more files",
    )
    h.add_argument("--dry-run", action="store_true", help="show the rules; change nothing")

    p = sub.add_parser("skills", help="check or install the pstack skills for your agent tools")
    skills_sub = p.add_subparsers(dest="skills_command", metavar="ACTION", required=True)
    skills_sub.add_parser("status", help="say which tools have pstack, and which version")
    h = skills_sub.add_parser(
        "install", help="install or update pstack at user level (shows the plan without --yes)"
    )
    h.add_argument("name", choices=("pstack",))
    h.add_argument(
        "--tool",
        choices=("claude", "codex", "cursor", "opencode", "pi", "grok", "all"),
        help="one tool (default: every tool that is found)",
    )
    h.add_argument(
        "--adopt",
        "--all",
        dest="adopt",
        action="store_true",
        help="replace same-named skill folders so every pstack skill is installed",
    )
    h.add_argument("--yes", action="store_true", help="do it; without this, only show the plan")

    p = sub.add_parser("update", help="install the newest memory from its source")
    mode = p.add_mutually_exclusive_group()
    mode.add_argument("--check", action="store_true", help="only say if an update exists")
    mode.add_argument("--dry-run", action="store_true", help="check, then list the steps")
    p.add_argument("--source", metavar="PATH|URL", help="the folder or git URL to install from")

    sub.add_parser(
        "status", parents=[common], help="say the version, the source, and what needs an update"
    )

    p = sub.add_parser("instructions", help="print or write the rules block for agents")
    p.add_argument(
        "--write-instructions",
        nargs="?",
        const="local",
        choices=("local", "shared"),
        help="write the block to CLAUDE.local.md (ignored) and untracked harness copies; "
        "moves any cairnkit block out of tracked CLAUDE.md / AGENTS.md. shared is refused",
    )
    p.add_argument(
        "--instructions-file",
        help="untracked file to write, relative to the checkout",
    )

    p = sub.add_parser("add", parents=[common], help="write a new fact")
    p.add_argument("text", help="one or two plain sentences, at most 400 characters")
    p.add_argument("--kind", choices=KINDS, default="fact")
    p.add_argument("--area", required=True, help="one area of the work, for example deploy")
    p.add_argument("--basis", choices=BASES, required=True, help="seen, told or guess")
    p.add_argument("--source", required=True, help="commit:<hash>, file:<path>, session:<date>")
    p.add_argument("--tag", action="append", help="a search word (repeat for more)")
    p.add_argument("--happened-at", type=_time, help="when it became true (default: today)")
    p.add_argument("--link", action="append", help="<rel>:<id>, rel related|depends_on|...")
    p.add_argument("--pinned", action="store_true", help="load in every session")
    p.add_argument(
        "--enforced-by", metavar="TYPE:VALUE", help="rules only: the check that fails, e.g. ci:lint"
    )
    p.add_argument("--supersedes", metavar="ID", help="this fact replaces ID")
    p.add_argument("--reason", help="why ID is replaced (with --supersedes)")
    p.add_argument("--short", action="store_true", help="short-term working note")
    p.add_argument("--expires", type=_time, help="end date of a short-term fact")
    p.add_argument(
        "--until-merged",
        nargs="?",
        const="",
        metavar="BRANCH",
        help="short-term until BRANCH (default: this branch) is merged",
    )

    p = sub.add_parser("change", parents=[common], help="change the status or links of a fact")
    p.add_argument("id")
    p.add_argument("--status", choices=STATUSES)
    p.add_argument("--reason", help="why (required with --status)")
    p.add_argument("--superseded-by", metavar="ID")
    p.add_argument("--held-by", metavar="PATH", help="tracked file that now holds the rule")
    p.add_argument("--link", action="append", help="<rel>:<id> to add")
    group = p.add_mutually_exclusive_group()
    group.add_argument("--enforced-by", metavar="TYPE:VALUE", help="rules only: the check")
    group.add_argument("--no-enforced-by", action="store_true", help="the rule is advisory again")

    for name, text in (("keep", "make a short-term fact long-term"), ("promote", None)):
        # `promote` is the old name of `keep`. It has no help line, so it stays hidden.
        p = sub.add_parser(name, parents=[common], **({"help": text} if text else {}))
        p.add_argument("id")
        p.add_argument("--reason")

    p = sub.add_parser("purge", parents=[common], help="remove a fact for good (secrets only)")
    p.add_argument("id")
    p.add_argument("--reason", required=True, help="for example: secret")
    p.add_argument("--yes", action="store_true", help="confirm; there is no undo")

    p = sub.add_parser("check", parents=[common], help="check facts, links and secrets")
    p.add_argument("--strict", action="store_true", help="warnings are errors too")
    p.add_argument("--advisory", action="store_true", help="also list rules that no check enforces")

    p = sub.add_parser("hooks", help="connect memory to agent tools and git")
    hooks_sub = p.add_subparsers(dest="hooks_command", metavar="ACTION", required=True)
    h = hooks_sub.add_parser("install", parents=[common], help="install the hooks")
    h.add_argument("--agent", default="auto", choices=("auto", *AGENTS))
    h.add_argument("--dry-run", action="store_true")
    h.add_argument(
        "--no-git-hook",
        action="store_true",
        help="skip the git pre-commit, post-checkout, pre-push and post-merge hooks",
    )
    h.add_argument(
        "--commit-msg-guard",
        nargs="?",
        const="local",
        choices=("local", "shared"),
        help="also install a commit-msg hook that rejects AI attribution lines: local "
        "(.git/hooks) or shared (tracked .githooks/, for clones)",
    )
    h = hooks_sub.add_parser("uninstall", parents=[common], help="remove the hooks")
    h.add_argument("--dry-run", action="store_true")

    # Called by the installed hooks. Not for people.
    p = sub.add_parser("hook", parents=[common])
    p.add_argument(
        "event",
        choices=("session-start", "stop", "pre-commit", "post-checkout", "pre-push", "post-merge"),
    )
    p.add_argument("--agent", default="generic", choices=AGENTS)

    p = sub.add_parser("load", parents=[common], help="print the facts for this session")
    p.add_argument("--area", help="only this area (and pinned facts)")
    p.add_argument("--budget", type=int, default=600, help="word budget; 0 for no limit")
    p.add_argument(
        "--explain", action="store_true", help="also print the rank of each fact and why"
    )

    p = sub.add_parser("show", parents=[common], help="print one fact and its history")
    p.add_argument("id")

    p = sub.add_parser("tidy", parents=[common], help="propose clean-up changes for review")
    p.add_argument("--days", type=int, default=90, help="a long fact older than this is stale")
    p.add_argument("--apply", nargs="+", metavar="ID", help="write the approved proposals")
    p.add_argument(
        "--auto",
        action="store_true",
        help="retire the clear mechanical cases now (exact duplicates, ended short-term "
        "facts), log each one, delete nothing. The session-start hook does this too, "
        "and so do the personal pre-push and post-merge git hooks",
    )
    p.add_argument("--dry-run", action="store_true", help="with --auto: show, change nothing")
    p.add_argument(
        "--release",
        action="store_true",
        help="after a review of undone retires: start a new window for the auto mode",
    )

    p = sub.add_parser("search", parents=[common], help="find facts, then note lines, by words")
    p.add_argument(
        "query",
        help="words or a question; a fact with any of the words is found (--strict: all). "
        "With no whole-word match, a word of 4+ letters may start a longer one "
        "(deploy finds deployment)",
    )
    p.add_argument("--all", action="store_true", help="also non-active facts, with reasons")
    p.add_argument(
        "--strict",
        action="store_true",
        help="the old match: every word must appear, as a substring, no ranking by rarity",
    )
    p.add_argument("--limit", type=int, default=20)

    p = sub.add_parser(
        "docs",
        parents=[common],
        help="write a Nessa Docs atlas (docs/state) for this project",
    )
    p.add_argument("--dry-run", action="store_true", help="show the pages; write nothing")
    p.add_argument(
        "--force",
        action="store_true",
        help="overwrite an existing docs/state atlas",
    )
    return parser


def _open(project, args):
    from cairnkit.memory import Memory

    return Memory.open(project, getattr(args, "path", None))


def run(args) -> int:
    # Imported here, not at the top: building the parser (--help, --version) needs none of this.
    from cairnkit import autotidy, followups
    from cairnkit import presets as presets_module
    from cairnkit import skills as skills_module
    from cairnkit.autotidy import run_auto
    from cairnkit.check import run_check
    from cairnkit.docs_cmd import run_docs
    from cairnkit.hookrun import run_hook
    from cairnkit.hooks_cmd import run_install, run_uninstall
    from cairnkit.init import run_init
    from cairnkit.instructions import block as instructions_block
    from cairnkit.instructions import write_instructions
    from cairnkit.load import run_load
    from cairnkit.memory import MemoryMissing
    from cairnkit.migrate import run_migrate
    from cairnkit.paths import find_project, resolve_memory_dir
    from cairnkit.reading import run_search, run_show
    from cairnkit.refresh import run_refresh
    from cairnkit.tidy import run_tidy
    from cairnkit.update import run_status, run_update
    from cairnkit.writing import Refused, add_fact, change_fact, fail, keep_fact, purge_fact

    if args.command == "update":
        return run_update(args.source, args.check, args.dry_run)
    project = find_project()
    if args.command == "docs":
        return run_docs(project, args.path, args.dry_run, args.force)
    if args.command == "instructions":
        if args.write_instructions:
            return write_instructions(
                project, args.write_instructions, args.instructions_file, dry_run=False
            )
        print(instructions_block(), end="")
        return 0
    if args.command == "skills":
        if args.skills_command == "status":
            return skills_module.run_status()
        return skills_module.run_install(args.tool, args.yes, adopt=args.adopt)
    if args.command == "preset":
        if args.preset_command == "list":
            return presets_module.run_list()
        if args.preset_command == "show":
            return presets_module.run_show(args.name, project if args.detect else None)
        return presets_module.run_add(project, args.path, args.names, args.dry_run, args.file)
    if args.command == "init" and args.refresh:
        return run_refresh(project, args.path, args.dry_run)
    if args.command in ("init", "migrate"):
        chosen = args.preset
        if args.no_default_rules:
            chosen = [*(chosen or []), presets_module.NONE]
        try:
            presets_module.check_names(chosen or [])
        except presets_module.UnknownPreset as exc:
            print(f"error: {exc}\nNothing changed.", file=sys.stderr)
            return 1
        if args.command == "migrate":
            if args.dry_run and args.yes:
                print(
                    "error: --dry-run and --yes contradict each other. "
                    "Use one. Without --yes, migrate only shows the plan.\nNothing changed.",
                    file=sys.stderr,
                )
                return 1
            return run_migrate(
                project,
                args.path,
                args.from_dir,
                not args.yes,
                chosen,
                args.untrack,
                args.fix_references,
            )
        code = run_init(project, args.path, args.dry_run, args.gitignore, chosen)
        if code == 0 and args.write_instructions:
            code = write_instructions(
                project, args.write_instructions, args.instructions_file, args.dry_run
            )
        line = None
        if code == 0:
            memdir, _ = resolve_memory_dir(project, args.path)
            line = skills_module.once_line(memdir, record=not args.dry_run)
        if line:
            print(line)
        return code
    if args.command == "status":
        return run_status(project, args.path)
    if args.command == "check":
        return run_check(project, args.path, args.strict, args.advisory)
    if args.command == "hooks":
        if args.hooks_command == "install":
            return run_install(
                project,
                args.agent,
                args.dry_run,
                not args.no_git_hook,
                args.commit_msg_guard,
                args.path,
            )
        return run_uninstall(project, args.dry_run)
    if args.command == "hook":
        return run_hook(project, args.path, args.event, args.agent)
    if args.command == "load":
        return run_load(project, args.path, args.area, max(args.budget, 0), args.explain)
    try:
        memory = _open(project, args)
        if args.command == "add":
            new = add_fact(memory, args)
            if new:
                print(f"added {new}")
        elif args.command == "change":
            change_fact(memory, args)
            print(f"changed {args.id}")
        elif args.command in ("keep", "promote"):
            keep_fact(memory, args.id, args.reason)
            print(f"kept {args.id} as long-term")
        elif args.command == "purge":
            dropped = purge_fact(memory, args.id, args.reason, args.yes)
            print(f"purged {args.id}: removed {dropped} line(s), wrote a tombstone")
        elif args.command == "show":
            return run_show(memory, args.id)
        elif args.command == "tidy":
            if args.dry_run and not args.auto:
                return fail("--dry-run goes with --auto")
            if args.auto and args.apply:
                return fail("--auto and --apply do not go together")
            if args.release:
                autotidy.release(memory)
                followups.refresh(memory)
                print("released: the auto mode counts a new window of 3 sessions and 7 days")
                return 0
            if args.auto:
                return run_auto(memory, args.dry_run)
            return run_tidy(memory, args.days, args.apply)
        elif args.command == "search":
            return run_search(memory, args.query, args.all, args.limit, args.strict)
    except (MemoryMissing, Refused) as exc:
        return fail(str(exc))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command is None:
        parser.print_help()
        return 0
    return run(args)


if __name__ == "__main__":
    sys.exit(main())
