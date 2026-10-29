# Contributing

## Set up

```sh
uv sync --group dev
./scripts/verify.sh      # ruff check, ruff format --check, pytest (CI runs this)
bash scripts/e2e.sh      # end-to-end run; the last line is "e2e: ok" (CI on Linux)
bash scripts/install-verify-pre-push.sh   # optional: local pre-push runs verify.sh
```

The optional pre-push hook lives under `.git/hooks/` and keeps a cairnkit
marked tidy block when one is already there, so the two chain.

## Rules

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
   them: `adapters.py`, `hookrun.py`, `hooks_cmd.py`, `skills.py`, the CLI
   choices, and the commit-msg guard patterns. Check each adapter against the
   tool's public docs before you change it.
7. **Plain docs.** Short sentences. One instruction per sentence. Active voice.
8. **Neutral git identity.** Author, committer, and any `Co-authored-by` /
   `Signed-off-by` trailer must be
   `cairnkit contributors <cairnkit@users.noreply.github.com>`. Added file
   lines may use that address or generic examples (`git@github.com`,
   `*@example.*`); other personal-looking addresses fail the check (paths
   under `tests/` are skipped for the file-text scan). Locally:
   `python3 scripts/check_identity.py origin/main..HEAD`. CI runs the same
   check on pull requests (`base..head`) and on pushes to `main`
   (`before..sha`) as a post-hoc alarm when commits land by fast-forward.
9. **Six-section PR body.** Pull request descriptions use the headings in
   `.github/pull_request_template.md` in order (TL;DR, How it works,
   Summary, Files changed, How to test, Review), include a `mermaid` fence,
   and must not carry Cursor agent footer markers (`CURSOR_AGENT_PR_BODY`,
   Open in Cursor / Open in Web), `Generated with`, or model names/ids.
   Product names (Claude, Cursor, Codex) are fine. Locally:
   `python3 scripts/check_pr_body.py path/to/body.md`. Pull requests run
   the same check in CI.
10. **Review gate.** The PR body's `## Review` section must not stay
   `Pending` (or empty). Any Blocker or High finding on that section must be
   marked `fixed` or `rejected` on the same line. Locally:
   `python3 scripts/check_review_gate.py path/to/body.md`. Pull requests run
   the same check as the `review-gate` CI job.

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
  migrate_refs.py  old-layout paths: rewrite exact ones, list the rest, the agent task
  clock.py       times
  schema.py      record fields and checks of one record
  secretscan.py  secret patterns
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
  rules_target.py  which file takes the rules block (CLAUDE.local.md; CLAUDE.md or AGENTS.md)
  ignore.py      .git/info/exclude
  tidy.py        memory tidy (no AI)
  autotidy.py    memory tidy --auto: retire the clear cases; session start and git hooks call it
  followups.py   the agent task for similar pairs and other follow-ups
  session.py     hook state per session
  hookrun.py     memory hook EVENT --agent NAME (output per agent)
  adapters.py    agent hook configs, one per agent tool
  markers.py     the start and end markers of a block, new and old names
  githook.py     git pre-commit, post-checkout, pre-push, post-merge (tidy) and commit-msg guard
  install_source.py  where memory was installed from; the cached newer check
  update.py      memory update and memory status
  progress.py    the step display of memory update
  refresh.py     the tool version that wrote the repo files; memory init --refresh
  hooks_cmd.py   memory hooks install / uninstall
  check.py       memory check
  selection.py   ranking for load
  usage.py       when a fact was last looked up; feeds the rank
  load.py        memory load
  reading.py     show, search
  ranking.py     words, stems and BM25 for search
  skills.py      memory skills: the pstack skills check and install
tests/           pytest; each test makes a throwaway git repo
benchmarks/      retrieval eval of search, with a synthetic fixture (see its README)
scripts/verify.sh   all checks (ruff, format, pytest); CI calls this
scripts/e2e.sh      end-to-end run in temp repos (a worktree, a plain folder, presets); CI on Linux
scripts/install-verify-pre-push.sh  optional local pre-push that runs verify.sh; chains with cairnkit hooks
scripts/check_identity.py  merge-time check: neutral author/committer/trailers and file emails
scripts/check_pr_body.py    PR body check: six headings, mermaid, no agent footer or model ids
scripts/check_review_gate.py  PR Review section: not Pending; Blocker/High must be fixed or rejected
.github/pull_request_template.md  the six-section PR description skeleton
```
