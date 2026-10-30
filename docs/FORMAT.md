# On-disk format

This page specifies the files that cairnkit reads and writes. It is precise
enough to write another implementation of the `memory` command in another
language. It describes version 0.2.0.

For what each kind and scope means, see [memory-types.md](memory-types.md).

All text files are UTF-8 with `\n` line ends. All JSON is plain JSON.

## 1. Where the memory folder is

The memory folder is outside the project. The project is the main checkout of
a git repo, or a plain folder.

The memory folder is the first of these:

1. the `--path DIR` flag;
2. the `MEMORY_DIR` environment variable;
3. the first line of `.memory-path` in the main checkout. A relative path is
   relative to the main checkout. `~` is expanded;
4. the default: `<parent of main checkout>/<name of main checkout>.memory`.

The main checkout is the parent of the common git folder
(`git rev-parse --git-common-dir`), when that folder is named `.git`. All
worktrees of one repo use the same memory folder.

Each checkout (the main checkout and each worktree) holds a symbolic link
named `memory-bank` to the memory folder. The link target is a relative path,
from the checkout to the memory folder. A real folder named `memory-bank` is
an error.

`memory init` adds these two lines to `.git/info/exclude` (in the common git
folder, so every worktree has them). It adds a line only when it is missing,
after the header line `# Private project memory (a link to a folder outside the repo)`:

```
memory-bank
.memory-path
```

Write `memory-bank` with no trailing slash. Git sees a link as a file, and
`memory-bank/` does not match a file.

Outside git, the project is the nearest folder, from the current folder up,
that holds a `memory-bank` link or a `.memory-path` file. The walk stops
before the home folder and the file system root.

## 2. The memory folder

```
<project>.memory/
  README.md                     what this folder is
  config.toml                   settings (section 5)
  facts/<writer>.jsonl          the fact files (section 3); default.jsonl holds the preset rules
  notes/status.md               prose: where things stand now
  notes/**                      other prose notes (read by `memory search`, never parsed)
  branches/<branch>.md          working notes for one branch
  proposals/<date>.md           output of `memory tidy`
  proposals/tidy-followups.md   the agent task for similar pairs (rebuilt; removed when empty)
  proposals/migrate-candidates.jsonl   output of `memory migrate`
  proposals/migrate-followups.md       the agent task of `memory migrate --fix-references`
  auto-tidy.log                 one line per retire, with the undo command (tidy --auto, session start, push, merge)
  tool-version.json             the tool version that last wrote the repo files (section 6)
  .sessions/<session>.json      hook state per session (safe to delete)
  .usage/<writer>.log           lookups for the rank: one line per lookup, a time and a fact id (safe to delete)
  .auto-tidy-state.json         the state of `auto_tidy = "auto"` (safe to delete)
  .auto-tidy.lock               the lock for a retire
  .skills-advisory.json         how often the pstack line was shown (safe to delete)
```

An implementation must create `facts/`, `notes/`, `branches/`, `README.md`
and `config.toml`. It may skip the other files. Files that start with a dot
are caches or locks.

### Pages, front matter and index

There is no page front matter and no index file. Notes and branch files are
plain Markdown with no required structure. The tool never parses them. The
fact files are the only structured data. A reader builds the index in memory:
it reads every `facts/*.jsonl` file and folds the records (section 3).

## 3. Fact files

The memory folder holds one fact file per writer: `facts/<writer>.jsonl`.
The writer is the `MEMORY_WRITER` environment variable, else the git branch
name, else `main`. Each character that is not a letter, a digit, `.`, `_` or
`-` becomes `-`. Leading and trailing `.` and `-` are removed. An empty result
is `main`. One file per writer lets two agents in two worktrees write at the
same time with no conflict. Readers merge all files.

Each line is one JSON object, written with no spaces between items
(`separators=(",", ":")`) and non-ASCII characters as they are. There are
three record types: `fact`, `change` and `tombstone`.

A write appends all its lines in one write, under an exclusive `flock` on the
file (no lock on Windows). When the file does not end with `\n`, the write
starts with `\n`.

An id is `f-YYYYMMDD-xxxx`: the date of `learned_at` and 4 random lower-case
hex characters. A new id must not exist in any fact file.

### Rules

- **Append only.** The tool adds lines. It never edits or deletes a line.
- **The current state of a fact** is the fact plus all its changes, applied
  in order of `at`.
- **The only rewrite** is `memory purge`. It removes the lines of one id and
  adds a tombstone.

### Fact

| Field | Required | Meaning |
|---|---|---|
| `type` | yes | `"fact"` |
| `id` | yes | `f-YYYYMMDD-xxxx`: the date it was learned and 4 random hex characters. Never reused. |
| `kind` | yes | `rule`, `decision`, `event`, `trap`, `preference`, `lesson` or `fact`. `memory load` shows `rule` facts first. |
| `text` | yes | The fact body. At most 2000 characters (400 for `kind` `rule`). |
| `summary` | no | Short load line. At most 200 characters. Not for rules. Load shows this instead of the full body when set. |
| `area` | yes | One area of the work, for example `deploy` or `database`. |
| `tags` | no | A list of words for search and ranking. |
| `happened_at` | yes | When it happened or became true. A date (`2026-10-03`) or a date-time. |
| `learned_at` | yes | When it was written. A date-time with an offset. |
| `source` | yes | Where it came from, as `<kind>:<value>`: `commit:<hash>`, `pr:<n>`, `file:<path>`, `session:<date>`, `person:<role>`. The rules of the `commits` preset use `default`. Other preset rules use `preset:<name>`, for example `preset:dev`. A rule from a preset file uses the prefix of its key as the name. |
| `basis` | yes | `seen` (observed), `told` (a person said so) or `guess` (inferred). It is the writer's own claim. A `told` fact is never superseded or retired by a fact with another basis. |
| `author` | no | `agent:<tool>` (`claude`, `codex` or `cursor`) when the tool could tell that an agent wrote the fact. Absent otherwise, and in older facts. |
| `status` | yes | Always `active` in a fact record. Changes set other values. |
| `scope` | no | `long` (default) or `short`. |
| `expires_at` | no | Short-term only. The date-time when the fact ends. Default: `learned_at` + `short_term_days` (14) from `config.toml`. |
| `until_branch_merged` | no | Short-term only. The fact ends when this branch is merged into the default branch, or when the branch is deleted. |
| `links` | no | A list of `{"rel": ..., "id": ...}`. `rel` is `related`, `depends_on`, `caused_by`, `contradicts` or `similar_to`. |
| `pinned` | no | `true` loads the fact in every session. Use it rarely. |
| `enforced_by` | no | Rules only. The check that fails when the rule is broken, as `<type>:<value>`: `githook:commit-msg`, `lint:ruff:T201`, `test:tests/test_x.py`, `ci:<job>`. No spaces, at most 120 characters after the colon. A rule without it is advisory. |
| `preset_rule` | no | Rules from a preset only. The rule key, for example `dev.tests`. `memory preset add` uses it to add each rule once. |
| `writer` | yes | The writer name. |

### Change

A change does not edit the fact. It adds a new state.

| Field | Required | Meaning |
|---|---|---|
| `type` | yes | `"change"` |
| `id` | yes | The id of the fact that changes. |
| `at` | yes | When the change was made. |
| `status` | no | The new status. |
| `reason` | with `status` | Why. |
| `superseded_by` | with `superseded` | The id of the newer fact. |
| `held_by` | with `promoted` | The path of the tracked file that now holds the rule (a rule file, doc, test or lint check). It must exist. |
| `scope` | no | `long` or `short`. `memory keep` writes `"scope": "long"`. |
| `add_links` | no | Links to add. |
| `enforced_by` | no | Rules only. A `<type>:<value>` string sets it. `null` clears it (the rule is advisory again). |
| `writer` | yes | The writer name. |

A change must set at least one of `status`, `scope`, `add_links` or
`enforced_by`.

### Status

| Status | Meaning | Loaded? |
|---|---|---|
| `active` | True now, as far as we know. | Yes |
| `superseded` | A newer fact replaces it. | No |
| `expired` | It was true, and it stopped being true by time. A short-term fact that has ended also reads as `expired` (computed, not written). | No |
| `wrong` | It was never true, or it was a bad guess. | No |
| `promoted` | A tracked file in the project now holds it. | No |

### Tombstone

`memory purge ID --reason secret --yes` writes one tombstone and removes all
other lines for that id, in every fact file.

| Field | Meaning |
|---|---|
| `type` | `"tombstone"` |
| `id` | The purged id. Links and changes to it stay valid. |
| `at` | When it was purged. |
| `reason` | Why. Do not repeat the secret here. |
| `writer` | The writer name. |

A tombstone holds no content.

### Example

```json
{"type":"fact","id":"f-20261003-e5f6","kind":"decision","text":"The shop and its admin app use two separate database projects.","area":"database","happened_at":"2026-10-03","learned_at":"2026-10-03T12:00:00-05:00","source":"session:2026-10-03","basis":"told","status":"active","scope":"long","writer":"main"}
{"type":"fact","id":"f-20261003-0a1b","kind":"decision","text":"The shop and its admin app use one database project with two schemas.","area":"database","happened_at":"2026-10-03","learned_at":"2026-10-03T23:30:00-05:00","source":"commit:abc1234","basis":"seen","status":"active","scope":"long","writer":"main"}
{"type":"change","id":"f-20261003-e5f6","at":"2026-10-03T23:30:00-05:00","status":"superseded","superseded_by":"f-20261003-0a1b","reason":"One project stays on the free tier.","writer":"main"}
```

More examples: [tests/fixtures/example-facts.jsonl](../tests/fixtures/example-facts.jsonl).


## 4. Short-term facts and computed state

A reader computes the status of a fact; it does not only read it:

- Fold: start with the fact record. Apply each change record for its id in
  order of `at`. A later value wins. `add_links` adds to `links`.
- A short-term fact (`scope: short`) whose `expires_at` is past, or whose
  `until_branch_merged` branch is merged into the default branch or deleted,
  reads as `expired`. Nothing is written. `memory tidy --auto` may write the
  change later.
- The default branch is `origin/HEAD`, else `main`, else `master`.

## 5. `config.toml`

```toml
short_term_days = 14          # end of a short-term fact with no expires_at
# rules_file = "CLAUDE.local.md"  # untracked rules file for `memory tidy`; unset: CLAUDE.local.md
auto_tidy = "auto"            # "auto", "report" (only say), "on" (retire) or "off"
skills_check = true           # false: no advisory line about the pstack skills (also init, migrate)
skills_auto_update = false    # true: session start installs or updates pstack (user level)
                              # (fills missing skills; does not --adopt same-named folders)

[areas]                       # path prefix -> area, for ranking in `memory load`
"src/db/" = "database"

[commit_msg_guard]            # extended regular expressions, matched without case
patterns = ["^co-authored-by:.*(some-tool)", "^generated with "]
```

## 6. Text that the tool writes into repo files

Each block has a start marker and an end marker. A writer finds the block by
its markers and replaces the text between them, markers included. Text
outside the markers never changes.

Marker rules for every block:

- One start marker, then one end marker: the block is found. Replace it in
  place. Never add a second block.
- No marker: add the block (where the section says).
- Anything else (a lost marker, two blocks, or markers of the new and the old
  name in one file) is broken. Change nothing and report the file.
- The old markers, from the name `project-memory`, are read as well. A block
  found with old markers is replaced by one block with the new markers.

### Rules block for agents

Files: `CLAUDE.local.md` (the default), untracked harness copies
(`.cursor/rules/cairnkit.mdc`, `.pi/APPEND_SYSTEM.md`),
`AGENTS.local.md` (older versions), or an untracked file that a person names.
Tracked `CLAUDE.md` and `AGENTS.md` never receive a new cairnkit block. A
write or refresh moves any existing cairnkit block out of those files into
`CLAUDE.local.md`, leaving hand-written text. `AGENTS.md` may gain one
generic pointer line to `CLAUDE.md` / `CLAUDE.local.md` (no cairnkit markers).

| | Start | End |
|---|---|---|
| New | `<!-- cairnkit:start -->` | `<!-- cairnkit:end -->` |
| Old | `<!-- project-memory:start -->` | `<!-- project-memory:end -->` |

The block is the start marker line, the text of `memory instructions`, and
the end marker line. A new block goes at the end of the file, after one blank
line. `memory init --refresh` only replaces a block that exists in an
untracked file; it migrates blocks out of tracked shared files.

A reader that looks for hand-written rules in these files skips the block,
from a line that is a start marker to the line that is its end marker. A start
marker with no end marker runs to the end of the file.

### Rules block of `memory tidy`

File: `rules_file` from `config.toml`. Unset, it is `CLAUDE.local.md`. A
tracked path is refused.

| | Start | End |
|---|---|---|
| New | `<!-- cairnkit:rules:start -->` | `<!-- cairnkit:rules:end -->` |
| Old | `<!-- project-memory:rules:start -->` | `<!-- project-memory:rules:end -->` |

A new block is:

```
<!-- cairnkit:rules:start -->
## Rules learned from project memory

- RULE TEXT
<!-- cairnkit:rules:end -->
```

An approved rule adds one line `- RULE TEXT` right before the end marker,
once.

### Git hooks

Files: `pre-commit`, `post-checkout`, `pre-push`, `post-merge`, `post-commit`
and `commit-msg`
in the hooks folder that git uses (`git rev-parse --git-path hooks`).
The shared option writes `commit-msg`, `pre-commit` and `post-checkout` into
`.githooks/`. It does not write `pre-push` or `post-merge`. Those two stay
in this clone.

| | Start | End |
|---|---|---|
| New | `# >>> cairnkit >>>` | `# <<< cairnkit <<<` |
| Old | `# >>> project-memory >>>` | `# <<< project-memory <<<` |

A new hook file is `#!/bin/sh`, then the block. In a hook file that exists,
the block goes right after the first line. A file whose first line is not a
`#!` line for `sh`, `bash`, `zsh`, `dash` or `ksh`, and that holds no block,
is not changed. The file mode gets `+x`. Uninstall removes the block, and
removes the file when only `#!/bin/sh` is left.

Block bodies (`PY` is the full path of the Python that runs the tool):

- `pre-commit`: `if [ -x PY ]; then PY -m cairnkit hook pre-commit || exit 1; fi`.
  Shared: `memory hook pre-commit`, run only when `memory` is on `PATH`.
- `post-checkout`: runs `PY -m cairnkit hook post-checkout` only when `$1`
  (the old HEAD) is all zeros, which is `git worktree add`. It never fails.
- `post-commit`: the same quiet shape as `pre-push`, with a 1 second bound
  (`timeout -k 1 1`, or `perl` `alarm 1`). It drafts pending candidates from
  the commit just made. It ends with `|| true`. Not part of the shared option.
- `pre-push`: a short shell block. When `PY` is executable it
  runs `PY -m cairnkit hook pre-push` with stdin, stdout and stderr on `/dev/null`,
  under a few-second wall-clock bound (`timeout` / `gtimeout` when present,
  else `perl` `alarm`+`exec`, which ships on macOS and Linux). The perl
  command runs in a group that discards output, so the shell's alarm line is
  not printed. With none of those tools the command runs unbounded. It ends
  with `|| true`. It does not read the hook arguments. It never fails the
  push. Not part of the shared option.
- `post-merge`: that same quiet tidy block, after a docs check that runs
  only when `docs/state` is a directory and `PY` is executable. The docs
  check half begins with the line `# cairnkit:docs-check` so
  `memory init --refresh` can tell an older post-merge body apart without a
  package version bump. The check asks `PY -c` whether
  `has_memory(find_project(), None)` is true, and discards that probe's
  stdout and stderr. A false or failed probe skips the rest. Otherwise it
  runs `PY -m cairnkit docs --check`, captures that command's stdout, and
  discards its stderr. The bound is 1 second (`timeout -k 1 1`, or
  `gtimeout`, or `perl` `alarm 1`). When the check exits 1 and the captured
  stdout is not empty, the hook prints
  `cairnkit: docs/state looks out of date; run memory docs --force`
  on its own stdout. It does not print the page list. The timed command
  ends with `|| true`. The hook writes nothing and never fails the merge.
  Not part of the shared option.
- `commit-msg` (opt-in): a comment line that starts with
  `# Refuse AI self-attribution lines.`, then `grep -iqE` with the patterns of
  `[commit_msg_guard]` on the lines of `$1` that do not start with `#`. A
  match prints the line and exits 1.

### Agent hooks

Files that git does not track. A tracked file is never written; the tool
prints the commands instead. Each file is added to `.git/info/exclude`.

| Agent | File | Events |
|---|---|---|
| Claude Code | `.claude/settings.local.json` | `hooks.SessionStart[]`: `{"matcher": "startup\|resume\|clear\|compact", "hooks": [{"type": "command", "command": CMD, "timeout": 10}]}`; `hooks.Stop[]`: `{"hooks": [{"type": "command", "command": CMD, "timeout": 30}]}`; `hooks.PostToolUse[]` for `after-shell` |
| Codex | `.codex/hooks.json` | the same shape, matcher `startup\|resume`, plus `PostToolUse` |
| Cursor | `.cursor/hooks.json` | `version: 1`; `hooks.sessionStart[]`: `{"command": CMD, "timeout": 10}`; `hooks.stop[]`: `{"command": CMD, "timeout": 30, "loop_limit": 1}`; `hooks.afterShellExecution[]` for `after-shell` |

`CMD` is `PY -m cairnkit hook EVENT --agent AGENT`, with `EVENT`
`session-start`, `stop`, or `after-shell`. Claude Code and Codex also install
`PostToolUse` for `after-shell`. Cursor also installs `afterShellExecution`
for `after-shell`. A hook entry belongs to the tool when its command
holds `cairnkit hook`, or the old `project_memory hook`. Install first removes
the entries that belong to the tool, then adds new ones, so a hook is never
written twice. Other entries stay.

### `tool-version.json`

In the memory folder. It records the tool version that last wrote the blocks
and hooks of this repo:

```json
{"version": "0.2.0", "at": "2026-10-25T09:00:00+00:00", "blocks": ["CLAUDE.local.md"]}
```

`blocks` lists the files that got a rules block, relative to the checkout.
When `version` is lower than the running tool, the session start prints one
line that asks for `memory init --refresh`. The same line appears when the
local `post-merge` hook holds a cairnkit block that either lacks
`# cairnkit:docs-check` or lacks `docs --check`, even when `version` equals
the running tool. A release that changes a block or hook raises the version,
except this post-merge docs check. The comment in the hook is the signal,
so that addition does not raise the version.

## 7. The hook commands

`memory hook EVENT --agent AGENT` reads a JSON object on stdin (or nothing).
The session key is `session_id`, else `conversation_id`, else `default`.

- `session-start`: prints the output of `memory load` and a short rules text.
  For `cursor` it prints `{"additional_context": TEXT}`. It always exits 0.
- `stop`: when `stop_hook_active` is true or `loop_count` is above 0, it says
  nothing more. Else, when `memory check --strict` finds a problem, or the
  session changed the work and wrote no fact, it asks the agent to continue.
  When the same command has failed 3 times in a row, the message also says
  to stop, run `memory check`, and ask. Output is
  `{"decision": "block", "reason": TEXT}` for `claude` and `codex`,
  `{"followup_message": TEXT}` for `cursor`, and TEXT on stderr with exit 1
  for `generic`. With nothing to say it prints nothing (`claude`, `generic`)
  or `{}` (`codex`, `cursor`), and exits 0.
- `post-commit`: drafts pending candidates from the commit just made, then
  runs the candidate quality gate and the same auto-tidy step as `pre-push`.
  It prints nothing and always exits 0. The shell bounds it to about 1 second.
  With no memory folder it does nothing.
- `after-shell` and `post-tool`: record one shell or tool result for the loop
  breaker. On the third identical failure the hook returns the same nudge as
  `stop`. A payload with no command, or a command and no outcome (`exit_code`,
  `status`, or `error`), is ignored. The hook always exits 0.
- `pre-commit`: exits 1 when a staged path is `memory-bank`, `.memory-path`
  or inside the memory folder, or when `memory check` finds an error. With no
  memory folder it exits 0.
- `post-checkout`: makes the `memory-bank` link in a new worktree.
- `pre-push` and `post-merge`: run the same auto-tidy step as `session-start`.
  They do not count as a session start. The tidy command prints nothing
  (including when the interpreter lacks cairnkit). They always exit 0. With no
  memory folder the tidy does nothing. Before the tidy command, the
  `post-merge` shell runs `PY -m cairnkit docs --check`, as the post-merge
  block above describes. When that check exits 1 and its stdout
  is not empty, the shell prints one line on stdout. The tidy command's
  shell bounds hung process start to a few seconds when
  `timeout`, `gtimeout`, or `perl` is on `PATH` (stock macOS has `perl`).
  The perl command runs in a group that discards output, so the shell's
  alarm line is not printed. Without any of those the start is unbounded.
  Once cairnkit is running, an in-process budget of a few seconds stops a
  slow tidy and leaves the memory as it is. A held tidy lock can add up to about three seconds to a push or a
  merge before that budget stops the wait.
  `git push --no-verify` skips the pre-push hook, as git does for every
  pre-push hook. Before the gate they only report. After the gate they retire.
  The same lock, and the same retire id, keep one retire when a session start
  runs at the same time. They also draft pending candidates from recent
  commits (lessons, decisions, traps) before that tidy step.

### Loop breaker

`<memory>/.loop-breaker.json` stores `command` and `streak`. It is safe to
delete. `session.note_failure` records one failed command. The third identical
failure makes `stop`, and `after-shell` when an adapter can see the failure,
tell the agent to stop, run `memory check`, and ask.

| Agent | Sees a command failure |
|---|---|
| Claude Code | Yes. `PostToolUse` runs `memory hook after-shell`. |
| Codex | Yes. The same `PostToolUse` shape. |
| Cursor | Yes. `afterShellExecution` runs `memory hook after-shell`. |
| Generic | No per-command hook. `stop` still shows the nudge when a failure was recorded another way. |
| OpenCode | No hook adapter. It cannot observe a command failure. |
| Pi | No hook adapter. It cannot observe a command failure. |
| Grok Build | No hook adapter. It cannot observe a command failure. |

## 8. Install record and update receipt

These files are in the uv tool environment (`uv tool dir`/`cairnkit`), not in
the memory folder.

- `uv-receipt.toml`: written by uv. The tool reads
  `tool.requirements[]` for the entry whose `name` is `cairnkit` (or the old
  `project-memory`). Its `editable`, `directory` or `git` value is the source.
  `tool.entrypoints[]` with `name = "memory"` gives the installed command.
- `cairnkit-install.json`: written by `memory update` after each install. An
  older install has `project-memory-install.json`; it is read when the new
  file is missing.

```json
{"source": "git+https://github.com/matthewpergolski/cairnkit", "commit": "<40 hex>", "version": "0.2.0", "installed_at": "2026-10-25T09:00:00+00:00"}
```

The record counts only when its source is the current source and its version
is the running version.

The user cache is `$XDG_CACHE_HOME/cairnkit`, else `~/.cache/cairnkit`:

- `update-check.json`: the last update check (`checked`, `source`,
  `installed`, `newer`, `from`, `to`, and `failed` after a failure). It is
  fresh for one day, or one hour after a failure.
- `wheels/<12 hex of the environment path>/install-*/<wheel>`: the wheel that
  the uv receipt points to after `memory update`.
- `wheels/update.lock`: the lock that one update holds from the check to the
  end.
- `cursor-plugins/` and `pstack-latest.json`: the pstack skills check.
- `pstack-catalog.json`: how many pstack skills the last-seen source had
  (`count`, optional `skills` names, `checked`). Written by
  `memory skills install pstack`. `memory skills status` uses it for the
  installed/available skill counts per tool.

User-level skill markers (not in the memory folder; under
`~/.codex/skills/.pstack/`, `~/.cursor/skills/.pstack/`,
`~/.config/opencode/skills/.pstack/` (or `$OPENCODE_CONFIG_DIR/skills/.pstack/`),
`~/.pi/agent/skills/.pstack/` (or `$PI_CODING_AGENT_DIR/skills/.pstack/`), or
`~/.grok/skills/.pstack/` (or `$GROK_HOME/skills/.pstack/`)):

- `install.json`: written by a Codex/Cursor/OpenCode/Pi/Grok Build copy
  install. Fields include `name`, `version`, `commit`, `source`, `skills`
  (every skill folder this install owns), `catalog` (how many skills the
  source had), and `installed_at`. A same-named folder that was skipped stays
  off `skills` until `memory skills install pstack --adopt` (or `--all`)
  replaces it.
- `LICENSE`: a copy of the pstack license from the source.

## 9. Checks

`memory check` reports:

- a line that is not valid JSON, a missing field, or a value that is not allowed;
- a duplicate fact id;
- text longer than 2000 characters (400 for `kind` `rule`);
- text that looks like a secret (keys, tokens, passwords, private keys) in any field;
- a change to an unknown fact;
- `superseded_by` or a link to an unknown fact;
- `held_by` that does not exist;
- a missing, broken or wrong `memory-bank` link, or a real folder in its place, in any checkout.

A writer name that differs from the file name is a warning, not an error.
So is an active rule fact that `AGENTS.md`, `CLAUDE.md` or `CLAUDE.local.md`
already says in the same words. `--strict` makes each warning an error.

