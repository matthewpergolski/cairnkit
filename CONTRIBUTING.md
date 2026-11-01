# Contributing

## Set up

```sh
uv sync --group dev
./scripts/verify.sh      # ruff check, ruff format --check, pytest, memory docs --check (CI runs this)
bash scripts/e2e.sh      # end-to-end run; the last line is "e2e: ok" (CI on Linux)
bash scripts/install-verify-pre-push.sh   # optional: local pre-push runs verify.sh
```

The optional pre-push hook lives under `.git/hooks/` and keeps a cairnkit
marked tidy block when one is already there, so the two chain.

## Changelog and releases

Feature and fix PRs add one-line notes under `## [Unreleased]` in
`CHANGELOG.md` (Keep a Changelog headings: Added, Changed, Removed, Fixed). A release
PR renames that section to a version and date, leaves an empty
`## [Unreleased]` on top, and bumps `__version__` in `src/cairnkit/__init__.py`
(and `docs/FORMAT.md` to match). The 0.3.x series bumps the patch number for
each release, and this includes features. Do not tag from the PR; tagging
follows after the release lands on `main`. Do not put a release tag on `dev`:
`memory update` reads every tag on the remote, so installed tools on the `stable`
channel would take it. An install on the `dev` channel takes the newest commit of
`dev`, so keep that branch working.

## Rules

Read [the goal](README.md#the-goal) before you change or review anything. It is
the standard for each change. A manual step in the code or the docs does not
show that the step is intended.

1. **Write a failing test first.** Each feature and each bug fix starts with
   a test that fails. Commit the test, then the code that makes it pass.
2. **Keep changes small.** One feature per commit. Small modules.
3. **No heavy dependencies.** Use the standard library. Ask before you add a
   runtime dependency.
4. **Never rewrite fact files.** Only `purge` may rewrite a file. Any other
   write appends. A test checks that earlier bytes do not change.
5. **`memory load` never blocks a session.** It exits 0 and says plainly
   when it read nothing.
6. **Keep the core generic.** No personal data, no names of private
   projects. Agent tools are named only where hooks and skills connect to
   them: `adapters.py`, `hookrun.py`, `hooks_cmd.py`, `loopbreak.py`, `native.py`,
   `harness_local.py`, `skills.py`, the CLI choices, and the attribution guard
   in `githook.py`. Check each adapter against the tool's public docs before you change it.
7. **Plain docs.** Short sentences. One instruction per sentence. Active voice.
8. **Neutral git identity.** Author, committer, and any `Co-authored-by` /
   `Signed-off-by` trailer must be
   `cairnkit contributors <cairnkit@users.noreply.github.com>`. Added file
   lines may use that address or generic examples (`git@github.com`,
   `*@example.*`); other personal-looking addresses fail the check (paths
   under `tests/` are skipped for the file-text scan). Locally:
   `uv run python scripts/check_identity.py origin/main..HEAD`. CI runs the same
   check on pull requests (`base..head`) and on pushes to `main`
   (`before..sha`) as a post-hoc alarm when commits land by fast-forward.
9. **Six-section PR body.** Pull request descriptions use the headings in
   `.github/pull_request_template.md` in order (TL;DR, How it works,
   Summary, Files changed, How to test, Review), include a `mermaid` fence
   under How it works, and must not carry `Generated with`, model names/ids, or Co-authored-by /
   Signed-off-by trailers inside the six-section body. A single
   `CURSOR_AGENT_PR_BODY` wrap plus cursor.com footer is packaging
   (Option A; see `docs/pr-workflow.md`); a second copy outside the
   markers fails. Product
   names (Claude, Cursor, Codex) are fine. Also fails on placeholder text
   (Pending, TBD, TODO, paste-later notes), How to test lines that are not
   exactly Unit:/Smoke:/End-to-end: with a command+result or
   `not needed, because`, prose sentences over ~25 words (STE rough check;
   skips code, tables, mermaid), and a Review section without
   fixed/accepted/rejected findings or the current head sha. Locally:
   `PR_HEAD_SHA=$(git rev-parse HEAD) uv run python scripts/check_pr_body.py path/to/body.md`.
   Pull requests run the same check via `.github/workflows/pr-standards.yml`
   (copyable with `scripts/check_pr_body.py`).
10. **Review gate.** The PR body's `## Review` section must not stay
   `Pending` (or empty). Any Blocker or High finding on that section must be
   marked `fixed` or `rejected` on the same line. Locally:
   `uv run python scripts/check_review_gate.py path/to/body.md`. Pull requests run
   the same check as the `review-gate` CI job.
11. **Tidy is mechanical, and age ends nothing.** `memory tidy --auto` retires only
   the clear cases: an exact or near repeat, an ended short-term note, and a short-term
   note whose source file is gone. `memory tidy` lists changes that an agent applies,
   and it never asks a person to review a queue. Do not add a rule that ends a fact
   because of its age, its active days or a count of loads. Do not add a step that
   moves a fact into a tracked file. See
   [the test record](docs/forgetting-tests.md).
12. **No tool text loads as a fact.** A hook names an event to the agent. Only the
   agent writes a fact.
13. **No tracked writes.** A setup or hook path must not write a tracked file. When a
   file is tracked, the code skips it and says so. Under a tracked `core.hooksPath`, the hooks
   run from `.git/cairnkit-hooks` through the local git config.

## Layout

```
src/cairnkit/
  __init__.py    the version (hatchling reads it; keep FORMAT.md equal)
  __main__.py    python -m cairnkit, which the hooks run
  cli.py         arguments and dispatch; the cairnkit and memory commands
  paths.py       project, checkouts, memory folder, git helpers
  init.py        memory init
  migrate.py     memory migrate (move the old folder aside, init, copy, worklist)
  candidates.py  candidate facts from prose notes (read only, no model)
  migrate_refs.py  old-layout paths, old checks, files outside the layout, the agent task
  clock.py       times
  schema.py      record fields and checks of one record
  secretscan.py  secret patterns
  envsecrets.py  real values from untracked .env files
  store.py       read and append JSONL; purge rewrite
  state.py       fold changes into current state; computed expiry
  config.py      config.toml
  memory.py      one opened memory
  writing.py     add, change, keep, purge
  similar.py     exact and near repeats of a fact
  rules.py       commits rule facts and the commit-msg guard sync
  presets.py     rule presets: load, resolve, plan, seed; memory preset
  preset_data/   the presets as TOML (commits, basic, dev)
  detect.py      toolchain detection for preset rules (read only)
  instructions.py  the rules block for agents
  instruction_files.py  AGENTS.md, CLAUDE.md, CLAUDE.local.md: lines that hold a rule
  rules_target.py  which file takes the rules block (CLAUDE.local.md), and the checks on it
  harness_local.py  untracked rules copies for Cursor and Pi
  ignore.py      .git/info/exclude
  tidy.py        memory tidy: lists exact repeats, ended pinned notes and chains (no AI)
  autotidy.py    memory tidy --auto: retire the clear cases; session start, stop and git hooks call it
  followups.py   the agent task for similar pairs and other follow-ups
  hygiene.py     the load line that names facts whose source is gone
  legacy.py      ends what the 0.3.1 commit miner wrote, and removes its files
  session.py     hook state per session; the stop reminder
  signals.py     events and news that a session hears; stored traps for a commit
  native.py      names new notes in Claude Code's own memory
  loopbreak.py   counts repeated command failures; the nudge
  hookrun.py     memory hook EVENT --agent NAME (output per agent)
  adapters.py    agent hook configs and generated files, one per agent tool
  discover.py    the short rules and the look-up line of the load and --help
  markers.py     the start and end markers of a block, new and old names
  githook.py     git pre-commit, post-checkout, pre-push, post-merge (tidy) and commit-msg guard
  install_source.py  where memory was installed from; the cached newer check
  update.py      memory update and memory status
  progress.py    the step display of memory update
  refresh.py     the tool version that wrote the repo files; memory init --refresh
  hooks_cmd.py   memory hooks install / uninstall
  check.py       memory check
  selection.py   rank for load; the budget and one place per area
  usage.py       when a fact was last looked up; feeds the rank
  load.py        memory load
  reading.py     show, search
  ranking.py     words, stems and BM25 for search
  skills.py      memory skills: the pstack skills check and install
  docs_cmd.py    memory docs: the atlas under docs/state
  docs_inventory.py  docs_modules.py  docs_pages_cairnkit.py  docs_pages_generic.py  the atlas inputs and pages
tests/           pytest; each test makes a throwaway git repo
benchmarks/      retrieval eval of search, and forgetting/ (see its README); both synthetic
scripts/verify.sh   all checks (ruff, format, pytest, memory docs --check); CI calls this
scripts/e2e.sh      end-to-end run in temp repos (a worktree, a plain folder, presets); CI on Linux
scripts/install-verify-pre-push.sh  optional local pre-push that runs verify.sh; chains with cairnkit hooks
scripts/check_identity.py  merge-time check: neutral author/committer/trailers and file emails
scripts/pr_body.py         render/check/set PR body (strips agent wrap; gh --body-file)
scripts/check_pr_body.py    PR body check (Python 3.10+ stdlib): six headings, mermaid, STE, How to test, Review sha (stdlib; copyable)
scripts/check_review_gate.py  PR Review section: not Pending; Blocker/High must be fixed or rejected
.github/workflows/pr-standards.yml  copyable PR-body CI (pairs with check_pr_body.py)
.github/pull_request_template.md  the six-section PR description skeleton
```
