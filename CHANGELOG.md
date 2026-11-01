# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- Stop names a correction from the owner, or a file that was here at the session start and is gone,
  once, and asks if a trap belongs in memory. The tool writes no fact. On a labelled set of 40
  ordinary prompts and 30 corrections, 0 false nudges and 1 miss.

### Changed

- `memory status`, `memory check` and `memory load` read one health function and print one answer
  line. `memory check: ok` now means that nothing is open, and open work outside the facts prints
  as `to do`. `Repo files: current.` and `memory check: skipped` are gone.
- Stop blocks on all that `memory check --strict` fails, also a false `enforced_by`.
- Cursor uses `postToolUse` in place of `afterShellExecution`, whose output its docs do not read,
  and `beforeSubmitPrompt`. After a compaction it gets the load itself at its next tool result.
  A pass after failures now counts on Cursor. `memory init --refresh` writes the new hooks.
- The session start spends fewer words on tool text: the footer and the rules no longer overlap.

### Fixed

- After a move, hooks beside `core.hooksPath` that are gone now read as an error that names
  `memory hooks install`, in place of a false warning while each commit failed.
- Auto-tidy retires a near repeat only when the words match in order after case, plural,
  punctuation and stop words. Staging against production and three times against five now go to
  the agent task. An exact repeat now needs the same order, and it keeps symbols and non-ASCII
  words, so reversed words and `C++` against `C#` stay two facts, at `memory add` too.
- A damaged line loses only that line. A cut inside a character no longer hides each fact of that
  writer. An add after a torn tail loads, purge works, and U+2028 in a text no longer splits a record.
- One record that the code cannot use is skipped and counted. It no longer stops the load or crashes
  `memory check`.
- A session start has a total budget of 7 seconds, under the shortest adapter timeout. Optional
  steps stop first, and the load still prints the facts. A lock wait ends after 5 seconds, and
  `memory add` says that it wrote nothing. With a slow git, `memory add` still lands soon.
- A bad value or a typo in `config.toml` keeps auto-tidy off, and `memory check` names it.
- The clean-up of 0.3.1 ends a mined fact only with proof that its gate wrote it, so a fact that a
  person accepted stays.
- A stop blocks once for a given problem, and each line names its command.

### Removed

- The `grep` and the skills demand in the done test of `memory migrate`, and the `(done)` state of
  its task. A task file exists only while items are open.
- Each path that wrote to a tracked file: `--gitignore`, `--commit-msg-guard=shared`, the
  `AGENTS.md` pointer and `memory migrate --fix-references`. Migrate now lists old paths in the
  agent task. `memory init --refresh` no longer rewrites `.githooks/`, and no command removes an
  old block from a tracked `CLAUDE.md` or `AGENTS.md`: it writes `CLAUDE.local.md` and says so.
- Scenario folding in `memory load`. Each fact that loads now shows its text.
- The commit miner, the quality gate, `memory candidates` and the `post-commit` hook. An agent
  writes each fact. A memory from 0.3.1 ends the facts that the miner wrote, at the next session
  start. They stay in the archive.
- The `docs/state` line that `post-merge` printed on each merge. `memory status` shows the state,
  and says what `memory docs --force` writes. Nobody has to act at a merge.
- Every rule that ended a fact because of its age: `STALE_DAYS`, the 14-day default of `--short`,
  `short_term_days`, `memory tidy --days` and `proposals/stale-pending.md`.
- Moving facts into a rules file through `memory tidy`. A pinned fact already loads each session.

### Added

- `memory repair` settles a bad line with an appended record and keeps the bytes. It also drops a
  bad setting from `config.toml` and keeps a copy. A gone `held_by` clears with
  `memory change ID --status active`. `memory purge` is needed only for a secret.

- `memory migrate` lists each check of the old tooling once, by name, with what happens to it now.
- `memory migrate` says which checkout it acts on and what the install step reaches.
- The worklist marks a repeat of an earlier line or a stored fact (`tier: repeat`, `repeat_of`).
- The status heading of `memory load` counts the commits that HEAD is past the newest commit the
  note names. A clipped note says how many lines it shows. Neither ends a fact.
- An agent tool that you install after setup connects by itself at the next session start, push
  or merge. It prints nothing, writes no tracked file and keeps your choice of tools.
- `memory add` needs only the text. `--basis` defaults to `guess` and `--source` to
  `session:<today>`. The output names the default basis. A near repeat with basis `guess`
  no longer retires a `seen` fact in auto-tidy.
- `evals/agents`: a kit that runs real agents on `dev` against production.
- The attribution guard refuses a commit whose author or committer is an AI tool, and a
  `Made-with` line. A personal `pre-push` check refuses the same in a commit that skipped
  `commit-msg`. A person whose name holds a tool word passes.
- `memory add` of a rule against AI attribution turns the guard on at once.
- The guard knows model names such as Fable and Opus, and `Assisted-by`, `Signed-off-by` and
  `Written by` lines. A co-author named Claude Monet now passes.
- With a Python that is gone, the pre-commit hook still refuses the private paths and lets other
  commits through. `memory status`, `memory check` and the load name the gone Python, for git
  hooks and agent hooks.
- A rule whose `enforced_by` check is not there loads as advisory, and `memory check` warns.
- Under a `core.hooksPath` in the repo, git 2.54 or newer runs the personal hooks beside the
  tracked ones, from the local git config. No tracked file changes.
- `memory check` and `memory status` print the real hook state, and warn when `core.hooksPath`
  hides the hooks. The session start names the fix to the agent.
- `memory update --channel dev|stable`. An install pinned to the `dev` branch follows that branch.
- Hook adapters for Pi, OpenCode and Grok Build, as untracked files.
- A subagent gets a load of 300 words at its start on Claude Code and Codex.
- The pre-commit hook prints a stored trap that matches the staged files. Git output reaches every
  agent, including one with no adapter. It never refuses the commit.
- The session start names new notes in Claude Code's own memory, once, so that an agent can copy
  what matters.
- The session hears about events by name: a command that failed and then passed, a command that
  still fails, and a revert. The tool writes no fact for them.
- `memory add` names an older fact in the same area that may now be stale. It ends nothing.
- A running session hears about facts from other branches, about auto-tidy changes, and about
  stored facts that match files it changed later (`UserPromptSubmit`, and after each tool).

### Changed

- `memory skills install pstack` with no `--tool` updates only the tools that have pstack. To add
  a tool, use `--tool NAME` or `--tool all`. `skills_auto_update` adds no tool.
- The pstack line moved from the load and `memory check` to `memory status`.
- The Codex trust line shows only after Codex has run a session.
- The update notice shows once per version pair in a load, and never in a subagent load.
  `memory status` always shows it.
- A session start has 31 fewer words that are not facts. The look-up line printed twice.
- Setup is one step. `memory init` connects the agent tools and the git hooks, with a short
  output (`--verbose` prints each step, `--no-hooks` skips the hooks). A rule against AI
  attribution installs its commit-msg check by itself.
- `--short` ends with its branch, or when an agent ends it. The clock alone ends nothing.
- With no signal about the work, `memory load` keeps one place for each area, and a trap holds it.
- A trap in a changed area ranks higher. Uncommitted changes and each part of a changed path are
  signals, and a fact that names a changed file ranks higher.

### Fixed

- A renamed or moved project keeps its memory with no step. A valid link wins over the folder
  name. A dangling link repairs itself from a record in the git folder and an id in the memory.
  `memory init` no longer replaces a valid link with an empty folder, and it refuses to make an
  empty memory where it sees signs of an old one. It names the folder it found.
- The memory of a submodule or nested repo stays outside the outer work tree. An older memory
  inside one gets a local exclude that git must confirm, so `git add -A` there cannot commit it.
- The load warns when a branch from before a migration has replaced the link with a real folder.
- All worktrees of a bare repo, or of a submodule, share one memory.
- A short note from a rebase belongs to the branch being rebased.
- Stored text reaches an agent only as data: in a frame, or on one labelled line. News hooks now
  use the frame. A stored newline, the frame end or a terminal code cannot forge a line on any path.
- A rule that an agent wrote with no person behind it, or a preset file that an agent added, now
  prints inside the data frame. Preset rules, a person's rules and an agent's `told` rules stay
  instructions, and a `told` rule from an agent names that agent.
- `memory load` keeps a status line such as `#96 is open`, keeps section headings, and keeps the
  status when one byte is not UTF-8. A status file that cannot be read says so.
- `memory show` prints the body of a fact that has a summary.
- `memory --version` and `memory status` name the channel and the commit of a dev build, a checkout
  or a folder build. A release still prints the bare number. The update check of a dev install
  compares commits.
- `Repo files: current.` is now true: a leftover `post-commit` block, an old marker pair or the 0.3.1
  candidate file counts as out of date. `memory init --refresh` removes them and ends the mined facts.
- `memory instructions` says that a subagent may need `memory load` in its brief.
- The pre-commit hook no longer refuses a staged removal of a private path. Before this, each
  commit after `memory migrate --yes --untrack` was refused.
- The migration task names each old hook that reads the old notes, with its file and line, not
  only the old checker. Its `Now` line quotes the file.
- A rerun of `memory migrate` no longer scans, reports or installs again. It reads the task again,
  and it removes the task when nothing is left. A deleted task stays deleted.
- An old `notes/` folder is no longer nested as `notes/notes/`. Two copies of one file no longer
  both look active: the other copy goes to `proposals/old-copies/`, and an old path that a doc names
  holds only a pointer. `memory check` names a later file outside `notes/`.
- `memory check` says that its `ok` covers only the facts and the links while a migration is open.
- The migration task reads the docs and hooks of the checkout where it runs, and a doc may keep its
  old name once it describes the new tool.
- pstack can no longer keep a migration task open. The run and `memory status` still name it.
- When Claude Code or Cursor connects, the Grok adapter goes, so that each hook runs once.
- A live note no longer ends by mistake. A branch that is checked out stays open, and a merge read
  needs real evidence. A note follows `git branch -m`.
- Session start takes about 1 second at 2000 facts, not 48 seconds. Before this, a large memory
  could miss the hook's limit of 10 seconds and load nothing.
- The secret scan reads the shape of a value, so ordinary lines such as `pwd=/home/app` pass.
- The secret scan refuses a value behind a secret label unless its shape says that it is no value.
  It also refuses `the db password is hunter2`, a quoted value in prose, and a value after a flag.
- `memory add` and `memory check` refuse a real value from an untracked `.env*` file, and they
  name only the variable and the file.
- `memory load`, `show` and `search` hold back a stored fact or note line that the scan catches,
  and they tell the agent to run `memory purge`. Stop names a note line that holds a secret.
- A failed command that holds a secret is stored and shown as a stand-in. `memory migrate` leaves
  a secret out of the worklist, `memory check` reads `proposals/`, and `memory purge` refreshes
  the tidy task at once.
- A new worktree gets the adapter files. A preset added after setup gets its commit-msg check. A
  line such as `Generated by openapi-generator` passes the check.
- Events and news are not lost when more than 5 arrive, and they reach Pi and Grok.
- Claude Code and Cursor failures now reach the loop breaker through their failure events. Before
  this, a Claude Code failure never reached it, and text on stderr could read as a failure.
- Codex reloads the memory after a compaction. Cursor hears about a compaction at its next stop.
- A problem in the memory no longer stops a commit. The pre-commit hook refuses only
  private memory paths.
- `--until-merged` keeps a note open while a remote copy of its branch exists, and it
  ends a note when its branch was squash-merged.
- A branch in no ref no longer reads as merged by itself. A fact records the branch tip
  (`branch_tip`), and auto-tidy records a branch that comes later. With no record, the note
  stays and `memory tidy` says that merged is unknown. `memory add` names a branch that does
  not exist at once. A merged and deleted branch still ends its note.
- `memory change ID --held-by PATH` without `--status promoted` says what it needs.
- The secret scan finds named secrets such as `CRON_SECRET=`, payment keys, bearer tokens
  and secrets in URLs. `memory check` also scans `notes/` and `branches/`.
- `memory search` takes several words with no quotes. `memory add --kind rule --summary`
  writes the rule and says that it does not store the summary. `--area` is optional.
- `post-merge` allows 3 seconds for the docs check, so a slow start does not lose its line.

## [0.3.1] - 2026-10-30

### Added

- Pull requests fail when the body is not one six-section STE copy; other repos
  can copy `scripts/check_pr_body.py` and `.github/workflows/pr-standards.yml` (#20).
- `scripts/pr_body.py` strips packaging, validates the body, and prefers
  `gh pr edit --body-file` (#20).
- `docs/pr-workflow.md` documents the short STE pull-request flow (#20).

### Changed

- `memory docs` inventories the project checkout (packages, entry points, README
  sections, import graph) instead of always describing cairnkit. Session and
  fact-lifecycle pages stay in cairnkit's own atlas only (#19).
- Review-gate needs dispositions and the current head sha; placeholder and
  duplicate-body checks are stricter (#20).

### Fixed

- `memory update` on a git URL detects a newer tagged release when no install
  commit is recorded (reads a `vX.Y.Z` tag at HEAD, else the highest remote
  release tag) (#19).
- `memory update` strips a uv git pin (`?rev=`, `#<commit>`, or `@ref`),
  lists the clean remote, installs the newest release tag, and records
  `git+<url>@<tag>`. With no release tag it installs `HEAD` and records the
  clean URL. An older remote tag is not treated as an update. Only strict
  `X.Y.Z` / `vX.Y.Z` tags count. A trailing `.git` on the record does not
  drop the recorded commit (#21).

### Upgrade

- Installs still on 0.3.0: run
  `uv tool install --force git+https://github.com/matthewpergolski/cairnkit@v0.3.1`
  once. After that, `memory update` works.

## [0.3.0] - 2026-10-30

### Added

- `memory docs` writes a Nessa Docs atlas under `docs/state` with no model and no network (#14).
- Auto propose and tidy on personal git hooks and long sessions, plus a loop breaker after three identical command failures (#15).
- Untracked rules blocks with one tracked `AGENTS.md` pointer line so clones stay usable without cairnkit (#15).
- `memory docs --check` reports drifted `docs/state` pages without writing; `verify.sh` runs it (#17).
- Post-merge prints one line when the atlas is stale so you can run `memory docs --force` (#17).
- `memory skills` installs every pstack skill with `--adopt` and shows installed versus available counts (#8).
- OpenCode, Pi, and Grok Build appear in pstack skills status and install (#13).
- Personal `pre-push` and `post-merge` hooks run gated auto-tidy after a push or a merge.
- `memory status` and `memory update` show the installed git ref and the upgrade delta.
- Faster CLI startup; CI also runs on Python 3.15 (#1).

### Changed

- Non-rule fact body cap is 2000 characters with an optional `summary`; rules stay at 400 (#15).
- Session and git hooks stay silent when `memory init` was never run (#15).
- Identity check accepts owner GitHub squash merges titled `(#N)` (#15).
- Every worktree gets its `memory-bank` link before hooks install or checks run.
- Personal git tidy hooks stay quiet and time-bounded (perl alarm; no hung watcher).
- Package version has one source: `src/cairnkit/__init__.py` (hatch dynamic).
- CI runs `verify.sh` and Linux e2e; pull requests check neutral identity and the six-section PR body.

## [0.2.0] - 2026-10-26

Baseline before the 0.3.0 work above.

[Unreleased]: https://github.com/matthewpergolski/cairnkit/compare/v0.3.1...HEAD
[0.3.1]: https://github.com/matthewpergolski/cairnkit/compare/v0.3.0...v0.3.1
[0.3.0]: https://github.com/matthewpergolski/cairnkit/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/matthewpergolski/cairnkit/releases/tag/v0.2.0
