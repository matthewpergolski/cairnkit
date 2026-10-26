# Contributing

## Set up

```sh
uv sync --group dev
./scripts/verify.sh      # ruff check, ruff format --check, pytest
bash scripts/e2e.sh      # end-to-end run; the last line is "e2e: ok"
```

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

## Layout

```
src/cairnkit/
  __init__.py    the version (keep it equal to pyproject.toml)
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
  ignore.py      .git/info/exclude
  tidy.py        memory tidy (no AI)
  autotidy.py    memory tidy --auto: retire the clear cases, with the undo log
  followups.py   the agent task for similar pairs and other follow-ups
  session.py     hook state per session
  hookrun.py     memory hook EVENT --agent NAME (output per agent)
  adapters.py    agent hook configs, one per agent tool
  markers.py     the start and end markers of a block, new and old names
  githook.py     git pre-commit, post-checkout (new worktree link) and commit-msg guard
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
scripts/verify.sh   all checks
scripts/e2e.sh      end-to-end run in temp repos (a worktree, a plain folder, presets)
```
