# How memory fits with CLAUDE.md and AGENTS.md

A project gives its agents two kinds of text: **instructions** and **facts**.
Instructions go in hand-written files that the agent tools read. Facts go in
memory. This page gives the test for each line, three examples, and the list
of files that `memory` adds to a project.

## The test: instruction or fact

Ask one question about each line: is it an instruction or a fact?

| | Instruction | Fact |
|---|---|---|
| It says | How to work. | What is true here. |
| It changes | Almost never. It is always true for this project. | Over time. It has a date and a reason. |
| Examples | "Write a failing test first." "Use uv." "No AI attribution." "One pull request per feature." | A decision, a trap, a result, the status of a task, a preference of the owner. |
| It goes in | One hand-written instruction file (see below). | Memory: `memory add`. |
| Tracked by git | Yes, except the local file. | Never. |

**Rules about memory itself ship inside the tool.** "Search before you add"
and "never store a secret in a note" are examples. You do not write them. The
session-start hook prints a short form. `memory instructions` prints the full
text, the **rules block**.

A rule fact (`kind: rule`) is an instruction that is stored in memory. The
rule presets add rule facts. The test still applies to them: an instruction
for the whole project belongs in an instruction file.

When you cannot decide, write the line as a fact. A fact that stays true and
that every contributor needs can move into an instruction file later, through
`memory tidy` (see [Where does each rule go](greenfield.md#where-does-each-rule-go)).

## Where each line goes

| Place | What it holds | Tracked | Who reads it |
|---|---|---|---|
| `CLAUDE.md` | Hand-written project instructions. cairnkit never puts its marked block here. | Yes | Claude Code; Grok Build. |
| `AGENTS.md` | Hand-written project instructions, plus one optional pointer line to `CLAUDE.md` / `CLAUDE.local.md`. | Yes | Codex, OpenCode, Pi, Cursor, and others that read `AGENTS.md`. |
| `CLAUDE.local.md` | The cairnkit rules block, plus private checkout notes. | No. `.git/info/exclude`. | Claude Code; Grok Build. |
| `.cursor/rules/cairnkit.mdc` | Untracked Cursor project rule (`alwaysApply`). | No | Cursor. |
| `.pi/APPEND_SYSTEM.md` | Untracked Pi append to the system prompt. | No | Pi (after project trust). |
| The agent tool's user-level rules file | Your personal instructions for every project. | Outside any repo | You, in all projects. |
| Memory (`memory-bank`, a link to `../<project>.memory/`) | Facts: dated, replaceable, searchable, private. | Never | You and your agents, in this project. |

Claude Code reads `AGENTS.md` only when the project has no `CLAUDE.md`,
`.claude/CLAUDE.md` or `CLAUDE.local.md`. To load both, put `@AGENTS.md` on its
own line at the top of `CLAUDE.md` or `CLAUDE.local.md`.

`AGENTS.md`, `CLAUDE.md` and `CLAUDE.local.md` are the project's policy, or
the policy of the template that the project came from. People write them.
`memory` does not write them by default (see
[What memory adds to a project](#what-memory-adds-to-a-project)).

Which agent tool reads which instruction file comes from each tool's own docs.
This repo does not test it.

This page uses the same places as the table in
[Where does each rule go](greenfield.md#where-does-each-rule-go). It adds the
instruction-or-fact test. The commit rules (no AI attribution) are
instructions. So they belong in `CLAUDE.md` or in your user-level rules file.
`memory init` does not add them to memory. `memory preset add commits` adds
them when you want them there.

## Three examples

Three small projects. Each cell shows lines that end up in that place.

| Project | `CLAUDE.md` (tracked) | `CLAUDE.local.md` (private) | Memory (private, dated) |
|---|---|---|---|
| **A web app** (a team; backend and frontend) | Write a failing test first. One pull request per feature. Run `bun run check` before you push. No AI attribution in commits or pull requests. | The dev server runs on port 5174 on this computer. | Decision: sessions use tokens, not cookies, because the mobile client needs them. Trap: the upload test fails near midnight UTC. Status: the login form is done; the error states are open. |
| **A data pipeline** (one person) | Use uv for Python. Each job must be safe to run twice. Never commit sample data. | Read raw files from `~/data/raw` on this computer. | Fact: the vendor feed sends dates as day/month since September. Result: the full backfill took 3 hours 10 minutes. Preference: the owner wants one log line per job, not a progress bar. |
| **A hobby audio tool** (one person) | Keep the audio thread free of allocations. Add a test for each new effect. | The test audio interface on this computer is device 2. | Trap: the reverb clips above 0.9 gain. Event: a soft limiter fixed the clipping but added 12 ms of latency, so it was removed. Status: delay is done; chorus is next. |

Look at each memory cell. Every line can stop being true. Every line has a
date and a reason. Look at each `CLAUDE.md` cell. Every line is true on every
day of the project.

## What memory adds to a project

`memory init` and `memory hooks install` add these items. Check them first
with `memory init --dry-run` and `memory hooks install --dry-run`.

| Item | Made by | Tracked | Notes |
|---|---|---|---|
| `../<project>.memory/` | `memory init` | No: it is outside the repo | The memory folder. `--path DIR` puts it in another place. |
| `memory-bank` link | `memory init` | No | A link to the memory folder, in each checkout and worktree. `memory-bank` and `.memory-path` go into `.git/info/exclude`. `--gitignore` also writes them to `.gitignore`. |
| `.claude/settings.local.json` | `memory hooks install` (Claude Code found) | No | Session-start and stop hooks. Added to `.git/info/exclude`. |
| `.codex/hooks.json` | `memory hooks install` (Codex found) | No | The same hooks. Added to `.git/info/exclude`. |
| `.cursor/hooks.json` | `memory hooks install` (Cursor found) | No | The same hooks. Added to `.git/info/exclude`. |
| `.git/hooks/pre-commit` | `memory hooks install` | No: it is inside `.git` | Refuses a commit that stages the `memory-bank` link. `--no-git-hook` skips it. |
| `.git/hooks/post-checkout` | `memory hooks install` | No | Links the memory into a new worktree made with `git worktree add`. With `--commit-msg-guard=shared`, `.githooks/post-checkout` (tracked) does the same, once each clone runs `git config core.hooksPath .githooks`. Re-run `memory hooks install` in an older project to get it. |
| `.git/hooks/pre-push` | `memory hooks install` | No: it is inside `.git`. Not shared. | Runs auto-tidy after a push. Personal to this clone. Not written to `.githooks/`. `--no-git-hook` skips it. It never blocks the push. `git push --no-verify` skips it, as git does for every pre-push hook. A held tidy lock can add up to about three seconds. Re-run `memory hooks install` in an older project to get it. |
| `.git/hooks/post-merge` | `memory hooks install` | No: it is inside `.git`. Not shared. | Runs auto-tidy after a merge. When memory exists and `docs/state` is stale, it also prints one line asking for `memory docs --force`. Personal to this clone. Not written to `.githooks/`. `--no-git-hook` skips it. It never blocks the merge. A held tidy lock can add up to about three seconds. |
| `.git/hooks/commit-msg` | `memory hooks install --commit-msg-guard` only | No | Refuses AI attribution lines in a commit message. |
| `.githooks/` | `memory hooks install --commit-msg-guard=shared` only | Yes | The commit-msg guard, pre-commit hook and post-checkout hook, for every clone. Does not include `pre-push` or `post-merge`. |

The hook files go into every checkout and worktree of the repo. An existing
file is merged, never replaced. When git tracks a hook file, the tool does
not change it. It prints the lines to add by hand.

### What memory does not change

`memory` does not write `CLAUDE.md`, `CLAUDE.local.md` or `AGENTS.md` by
default. A person runs `--write-instructions` when they want the rules block:

- `memory instructions --write-instructions` (local only) writes the rules
  block to `CLAUDE.local.md` and untracked harness copies
  (`.cursor/rules/cairnkit.mdc` for Cursor, `.pi/APPEND_SYSTEM.md` for Pi).
  Each harness path goes into `.git/info/exclude`. For Codex it adds one
  generic pointer line to tracked `AGENTS.md` (create if missing; idempotent;
  no cairnkit markers) and removes a leftover `AGENTS.override.md` if present.
  It refuses a rules-block file that git tracks, and a local file that is a
  link to a tracked file. It never writes through such a link. Older versions
  wrote `AGENTS.local.md`. The tool does not move or delete that file. It
  prints a note, and `memory init --refresh` keeps updating the block in it.
  - Claude Code reads `AGENTS.md` only when the project has no `CLAUDE.md`,
    `.claude/CLAUDE.md` or `CLAUDE.local.md`. When `AGENTS.md` is a real file
    and the repo has no `CLAUDE.md` or `.claude/CLAUDE.md`, a new
    `CLAUDE.local.md` would hide it. So the tool puts the line `@AGENTS.md`
    and a blank line at the top of `CLAUDE.local.md`, outside the markers, and
    prints a note. A later local write adds the line to an older file that
    lacks it. `memory init --refresh` and later writes keep it, and never add
    it twice. The tool does not add it when `CLAUDE.local.md` is `AGENTS.md`
    itself.
  - Any cairnkit block already in tracked `CLAUDE.md` or `AGENTS.md` is moved
    out into `CLAUDE.local.md`. Hand-written text outside the markers stays.
  - `--write-instructions=shared` is refused. Cloning never needs cairnkit for
    instruction files; the only committed cairnkit output is optional Nessa
    Docs pages under `docs/state/`.
  - **OpenCode gap:** OpenCode has no stable untracked project rules file. It
    loads committed `AGENTS.md` and optional `instructions` paths from
    `opencode.json`. Do not fall back to a tracked cairnkit write.
- `--instructions-file PATH` picks another untracked file. Tracked paths are
  refused.
- `memory init --write-instructions` does the same at init.
- `memory init --refresh` moves cairnkit blocks out of tracked `CLAUDE.md` /
  `AGENTS.md`, then replaces the block in place in each untracked file that
  already holds it. It never adds a block to a tracked shared file. See
  [Updating memory](update.md).
- `memory tidy --apply ID`, for a rule proposal, adds one line to a second
  marked block (`<!-- cairnkit:rules:start -->`) in the local rules file.
  Unless `rules_file` in `config.toml` names one, that is `CLAUDE.local.md`.
  A tracked `rules_file` is refused.
- `memory migrate --yes --fix-references` rewrites exact old memory paths in
  the top-level `*.md` files and in `docs/`. These can include `CLAUDE.md` and
  `AGENTS.md`. It changes the working tree only. It never commits.

## A template repo owns the dev flow

A template repo is a starter project with a good dev flow: a backend, a
frontend, pull requests, code review and deploys. The template owns the
dev-flow instructions. They live in its `AGENTS.md` and `CLAUDE.md`, and each
new project gets a copy.

Memory is the piece that you add to a project made from the template:

1. Make the project from the template. The instruction files come with it.
2. Run `memory init`, then `memory hooks install`.
3. Optional: add the template's tool rules to memory. The template keeps
   these rules (for example "use uv" or "pass `ruff check`") in its own
   preset file, for example `agents/preset.toml`. Git tracks that file. Run
   `memory preset add --file agents/preset.toml`. Keep each rule in one
   place: in the preset file or in `AGENTS.md`, not in both. See
   [Presets from a file](presets.md#presets-from-a-file).
4. Do not commit the memory. Facts, notes and status stay untracked. Only the
   instruction files and the preset file are tracked.
5. When an agent tool has no hook adapter, run
   `memory instructions --write-instructions` so the untracked local files
   hold the rules block. Tell the agent (in hand-written instructions or the
   local file) to run `memory load` at session start when the harness has no
   hook (see [What each agent tool reads](#what-each-agent-tool-reads)).

So the template and memory do not overlap. The template says how to work.
Memory records what happened and what is true now.

## What each agent tool reads

| Agent tool | Hook adapter in `memory` | Untracked rules path | Status |
|---|---|---|---|
| Claude Code | `.claude/settings.local.json` | `CLAUDE.local.md` | Built. Checked against the public docs. |
| Codex | `.codex/hooks.json` | Tracked `AGENTS.md` pointer to `CLAUDE.md` / `CLAUDE.local.md` | Built, **experimental**. |
| Cursor | `.cursor/hooks.json` | `.cursor/rules/cairnkit.mdc` | Built, **experimental**. Cloud agents do not run `sessionStart`. |
| Grok Build | None | `CLAUDE.local.md` (also listed in Grok's discovery names) | No hook adapter. Docs also say gitignored files are skipped during discovery while recommending `CLAUDE.local.md` in `.gitignore`; cairnkit uses `.git/info/exclude` instead. |
| Pi | None | `.pi/APPEND_SYSTEM.md` | No hook adapter yet. |
| OpenCode | None | **Gap:** no stable untracked project rules file without a tracked `opencode.json` `instructions` entry or a plugin. | No hook adapter. Do not write a tracked cairnkit block. |
| Any other tool | None. `memory hooks install --agent generic` prints the commands to connect by hand. | Connect by hand. | Manual. |

A tool without a hook gets memory only when its instructions tell it to run
`memory load`. The rules block says that a hook runs `memory load`, and it
tells the agent to run `memory check --strict` before it finishes. Auto-tidy
still runs after a push or a merge. That step does not load the memory. The
git hooks are personal to this clone.

## Built

These items were planned. They are built now.

- **A smaller `dev` preset.** The `dev` preset holds only generic rules:
  checks, tests, small diffs, git, secrets. It has no rule for one tool.
  `dev.uv`, `dev.ruff`, `dev.bun`, `dev.biome` and `dev.pins` left it. Rules
  like these belong in the template's `AGENTS.md`, or in the template's own
  preset file. See [presets.md](presets.md).
- **Presets from a file.** `memory preset add --file PATH` adds the rules of
  a preset file that the project owns. The file has the same format as the
  built-in presets. A template ships its tool rules this way. See
  [Presets from a file](presets.md#presets-from-a-file).
- **`memory init` adds only memory rules.** Plain `memory init` adds no rule
  facts. The rules about memory itself ship inside the tool. It no longer
  adds the `commits` rules. To add them, run `memory preset add commits`.
- **A duplicate check.** `memory check` warns when an active rule fact is
  also in `AGENTS.md`, `CLAUDE.md` or `CLAUDE.local.md`. What is compared:
  - The words, in the same order. Case, punctuation, markup and line wraps do
    not count. A link counts as its text, not its target. An HTML tag is left
    out.
  - One item: a bullet or a paragraph. The words must cover whole sentences
    of it. Where the sentences break inside does not count, so `Do X. Do Y.`
    matches `Do X; do Y.`. But `Use uv.` does not match `Use uv for Python.`
  - Not the block that `memory` writes between its marker lines, and not an
    HTML comment, also over many lines. A start marker or a comment with no
    end runs to the end of the file.

  The warning names the file, the line and the fact id. Under `--strict` it
  is an error. See [If you have duplicates](#if-you-have-duplicates).
- **`memory migrate` skips rules that have a home.** A line of the old notes
  that `AGENTS.md`, `CLAUDE.md` or `CLAUDE.local.md` already holds, in the
  same words, does not go into the worklist of candidate facts. Migrate says
  how many it skipped. See [brownfield.md](brownfield.md).
- **Git-event tidy.** `memory hooks install` adds personal `pre-push` and
  `post-merge` hooks. They run the same auto-tidy step as session start.
  They are not shared. They work for every agent, including OpenCode and Pi.
  `git push --no-verify` skips the pre-push hook. A held tidy lock can add
  up to about three seconds to a push or a merge.

## If you have duplicates

The same instruction in two places costs context in every session. The two
copies also drift apart. Keep one copy.

- **An instruction in `AGENTS.md` and in memory.** Keep `AGENTS.md`. Mark the
  memory copy `promoted`:
  `memory change ID --status promoted --held-by AGENTS.md --reason "Lives in AGENTS.md."`.
  The fact leaves the load. The archive keeps it. `memory preset add` does not
  add an ended preset rule again.
- **The same line in `CLAUDE.md` and `AGENTS.md`.** Keep it in `AGENTS.md`.
  Delete it from `CLAUDE.md`. Put `@AGENTS.md` on its own line at the top of
  `CLAUDE.md`. Claude Code loads the other file only through that import. A
  sentence such as "see AGENTS.md" does not load it.
- **A fact in an instruction file** (a status, a result, a date). Add it to
  memory with `memory add`. Then delete it from the file by hand.
- **A rule that a check enforces.** Keep the check. The note is only its
  reason. See
  [Where does each rule go](greenfield.md#where-does-each-rule-go).

`memory check` finds a rule fact that an instruction file repeats in the same
words. For a copy in other words, run `memory load`, read the rules, and
search the instruction files by hand.
