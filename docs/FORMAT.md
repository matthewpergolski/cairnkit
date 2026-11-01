# On-disk format

This page specifies the files that cairnkit reads and writes. It is precise
enough to write another implementation of the `memory` command in another
language. It describes version 0.3.1. It also includes the changes under
`Unreleased` in [CHANGELOG.md](../CHANGELOG.md), which are on the `dev` branch.

For what each kind and scope means, see [memory-types.md](memory-types.md).

All text files are UTF-8 with `\n` line ends. All JSON is plain JSON.

## 1. Where the memory folder is

The memory folder is outside the project. The project is the main checkout of
a git repo, or a plain folder.

The memory folder is the first of these:

1. the `--path DIR` flag;
2. the `MEMORY_DIR` environment variable;
3. the first line of `.memory-path` in the project's home, when that folder holds `facts/`.
   A relative path is relative to the home. `~` is expanded;
4. the folder that a `memory-bank` link resolves to, when it holds `facts/`. The link of the
   main checkout goes first;
5. the folder with the id in `<common git folder>/cairnkit-memory`: at the recorded path, or
   directly in the parent of the home or of the recorded path, when it is the only folder there
   with that id and its name is the recorded name, `<name of home>.memory` or the default name;
6. the `.memory-path` target that does not exist yet;
7. the default: `<parent of home>/<name of home>.memory`.

The home is the first entry of `git worktree list`: the main checkout, or the bare repo. A
submodule's first entry is its git folder, so its home is the `core.worktree` of that folder.
All worktrees of one repo use the same memory folder. For a bare repo, the default drops a
`.git` suffix. A bare folder whose name starts with `.` uses the name of its parent:
`proj/.bare` gives `proj/proj.memory`.

When the home is inside another work tree, the default is
`<parent of the outermost work tree>/<outermost name>.<path inside it, joined by dots>.memory`.
An existing `<name of home>.memory` that holds `facts/` is kept. The sibling is also used when
that parent is not writable. Any memory inside a work tree gets a line `/<path>` in that repo's
`info/exclude`, and `git check-ignore` must confirm it.

`<common git folder>/cairnkit-memory` has three lines: the memory id, its absolute path, and
the absolute path of the common git folder that wrote the file.
`.identity` in the memory folder has three lines: a random id, the project's root commits
separated by spaces, and the owner: the absolute path of the owner's common git folder, or of
the folder of a project with no git. Neither file holds a time. A file with fewer lines is from
an earlier version, and the next load adds the line when the memory is this project's.

A memory belongs to another project when its owner still exists and that owner's record names
the memory, or when its owner is gone and its root commits share none with this repo. An owner
that is gone, or that now uses another memory, means that the repo moved: the memory passes to
this project. A record that names another live git folder means that this repo is a copy.
`<common git folder>/cairnkit-copy-noted` holds that repo's git folder after the copy has heard
this once. The local git setting `cairnkit.sharedmemory = true` says that a project shares
another project's memory on purpose.

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
  notes/**                      other prose notes (read by `memory search`, never parsed)
  branches/<branch>.md          working notes for one branch
  proposals/<date>.md           output of `memory tidy`
  proposals/tidy-followups.md   the agent task for similar pairs (rebuilt; removed when empty)
  proposals/migrate-candidates.jsonl   output of `memory migrate`
  proposals/migrate-followups.md       the agent task of `memory migrate` (removed when nothing is open)
  proposals/old-copies/**              copies that lost to a note; an agent compares, then deletes each one
  auto-tidy.log                 one line per retire, with the undo command (tidy --auto, session start, stop, push, merge)
  tool-version.json             the tool version that last wrote the repo files (section 6)
  .sessions/<session>.json      hook state per session (safe to delete)
  .usage/<writer>.log           lookups for the rank: one line per lookup, a time and a fact id (safe to delete)
  .auto-tidy-state.json         the state of `auto_tidy = "auto"` (safe to delete)
  .auto-tidy.lock               the lock for a retire
  .stop-problems.json           hashes of the problems that a stop already named (safe to delete)
  config.toml.bad               the old file, when `memory repair` changed `config.toml`
  .loop-breaker.json            the last command and its fail streak (safe to delete)
  .loop-breaker.lock            the lock for that file
  .native-memory.json           the Claude Code native notes that the session start already named (safe to delete)
  .skills-advisory.json         whether init or migrate named pstack once (safe to delete)
  .agents-seen.json             the agent tools seen at setup and since; a tool not in it is new
  .rule-notices                 ids of rules that an agent changed; the next load names each once
  .identity                     this memory's id and its project's root commits (section 1); do not copy it to another memory
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
four record types: `fact`, `change`, `tombstone` and `repair`.

A write appends all its lines in one write, under an exclusive `flock` on the
file (no lock on Windows). When the file does not end with `\n`, the write
starts with `\n`. A wait for the lock ends after 5 seconds, and then nothing is written.

A reader works by line, in bytes. Only `\n` ends a line. A line that is not UTF-8 or not JSON, or a
record with no usable `id` or `text`, is skipped and counted. The other lines still count.

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
| `source` | yes | Where it came from, as `<kind>:<value>`: `commit:<hash>`, `pr:<n>`, `file:<path>`, `session:<date>`, `person:<role>`. `memory add` writes `session:<today>` when no source is given. The rules of the `commits` preset use `default`. Other preset rules use `preset:<name>`, for example `preset:dev`. A rule from a preset file uses the prefix of its key as the name. |
| `basis` | yes | `seen` (observed), `told` (a person said so) or `guess` (inferred). It is the writer's own claim. `memory add` writes `guess` when no basis is given. An exact repeat with no basis keeps the basis of the older fact. A `told` fact is never superseded or retired by a fact with another basis. Auto-tidy does not let a near repeat with basis `guess` retire a `seen` fact. |
| `author` | no | `agent:<tool>` (`claude`, `codex`, `cursor`, `opencode`, `pi` or `grok`) when the tool could tell that an agent wrote the fact. Two tools' markers give `agent:claude+cursor`. Absent otherwise, and in older facts. |
| `status` | yes | Always `active` in a fact record. Changes set other values. |
| `scope` | no | `long` (default) or `short`. |
| `expires_at` | no | The date-time when the fact ends. Present only when an agent passed `--expires`. It counts only with `scope: short`. There is no default. |
| `until_branch_merged` | no | Short-term only. The fact ends when this branch reads as merged (section 4). `--short` sets it to the current branch unless `--expires` is given. |
| `branch_tip` | no | The full commit hash of that branch when the fact was written, from a local branch or a remote copy. Absent when no ref had the name. It is the record that the branch existed (section 4). |
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
| `held_by` | with `promoted` | The path of the tracked file that now holds the rule (a rule file, doc, test or lint check). It must exist when the change is written. Later, `memory check` accepts a path that exists here or in the history of any branch. |
| `scope` | no | `long` or `short`. `memory keep` writes `"scope": "long"`. |
| `add_links` | no | Links to add. |
| `enforced_by` | no | Rules only. A `<type>:<value>` string sets it. `null` clears it (the rule is advisory again). |
| `branch_tip` | no | Auto-tidy only. The first tip that it saw of the end branch of a fact with no `branch_tip`. It changes no status. |
| `cid` | no | A hash that auto-tidy writes. Two sessions that write the same change write it once. A reader applies only the first change with a `cid`. |
| `case` | no | Auto-tidy only. Why it retired the fact: `duplicate`, `near-duplicate`, `ended`, `file-gone` or `mined`. |
| `writer` | yes | The writer name. |

A change must set at least one of `status`, `scope`, `add_links`, `enforced_by` or
`branch_tip`.

### Status

| Status | Meaning | Loaded? |
|---|---|---|
| `active` | True now, as far as we know. | Yes, within the word budget |
| `superseded` | A newer fact replaces it. | No |
| `expired` | It stopped being true. An agent ended it, or auto-tidy wrote a short-term note as ended. A short-term fact that has ended also reads as `expired` (computed, not written). A long-term fact never expires by itself. | No |
| `wrong` | It was never true, or it was a bad guess. | No |
| `promoted` | A tracked file in the project now holds it. | No |

### Tombstone

`memory purge ID --reason secret --yes` writes one tombstone and removes all
other lines for that id, in every fact file. `ID` must be the id of a record, or the
`line-HASH` that `memory check` prints for a damaged line. A purge refuses text that looks
secret as an id or a reason. It refuses a fact with a mask that holds true text, unless a
live fact supersedes it, or the call gives both `--reason secret` and `--yes`.

| Field | Meaning |
|---|---|
| `type` | `"tombstone"` |
| `id` | The purged id. Links and changes to it stay valid. |
| `at` | When it was purged. |
| `reason` | Why. Do not repeat the secret here. |
| `writer` | The writer name. |

A tombstone holds no content.

### Repair

`memory repair` writes one for each bad line. The line stays in the file. A reader and
`memory check` stop counting a line whose bytes match. A new bad line has other bytes.

| Field | Required | Value |
|---|---|---|
| `type` | yes | `"repair"` |
| `file` | yes | The name of the fact file that holds the line. |
| `sha` | yes | The first 16 characters of the SHA-1 of the line, with no outer white space. |
| `line` | no | The line number when it was written. |
| `at` | yes | The time. |
| `writer` | yes | The writer. |

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
- A short-term fact (`scope: short`) reads as `expired` when its `expires_at` is
  past, or when its `until_branch_merged` branch reads as merged. Nothing is written.
  Auto-tidy may write the change later.
- A long-term fact never reads as `expired` by itself, also when it holds
  `expires_at`.
- The default branch is `origin/HEAD`, else `main`, else `master`. A repo with no
  default branch reads no branch as merged, and the default branch itself never reads
  as merged.
- A branch with a local copy reads as merged when its tip is not the tip of the
  default branch and one of these is true: the tip is an ancestor of the default
  branch, or `git merge-tree --write-tree BASE TIP` gives the tree of the default
  branch (a squash merge; git 2.38 or later).
- A branch in no ref in `refs/heads` or `refs/remotes` reads as merged or deleted only
  when `branch_tip` names a commit in this clone, or when a reflog shows that the branch
  was renamed and the new name is in no ref. Otherwise it reads as unknown: the fact stays
  active, and `memory tidy` names it. A fact from before `branch_tip` has none, so it
  stays until auto-tidy sees its branch, or until an agent ends it.

A short-term fact loads when `until_branch_merged` is the current branch. With no
such field, it loads when `writer` is the current writer.

## 5. `config.toml`

```toml
auto_tidy = "auto"            # "auto", "report" (only say), "on" (retire) or "off"
skills_check = true           # false: no line about the pstack skills (status, init, migrate)
skills_auto_update = false    # true: session start updates pstack where it is installed (user level)
                              # (adds no tool; does not --adopt same-named folders)

[areas]                       # path prefix -> area, for ranking in `memory load`
"src/db/" = "database"

[commit_msg_guard]            # extended regular expressions, matched without case
patterns = ["^co-authored-by:.*(some-tool)", "^generated with "]
```

A file that cannot be parsed, a bad `auto_tidy` value and a key close to `auto_tidy` turn auto-tidy
off, the safest behavior. `memory check` names each bad setting, and `memory repair` drops it.

A file from an older version may hold `short_term_days` or `rules_file`. The tool
uses neither.

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
write or refresh changes no tracked file. It removes an old block from an untracked file, and it
writes the rules to `CLAUDE.local.md`. An old block in a tracked file stays, with a note.

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

### Git hooks

Files: `pre-commit`, `post-checkout`, `pre-push`, `post-merge` and `commit-msg`
in the hooks folder that git uses (`git rev-parse --git-path hooks`).
When that folder is outside the repo's git folder (`core.hooksPath` names a folder in a
checkout, or a global folder), the tool writes nothing there. The files go to
`.git/cairnkit-hooks` instead, and each one gets `hook.cairnkit-NAME.event` and
`hook.cairnkit-NAME.command` in the local git config, so git 2.54 or newer runs it beside that
folder. The command is
`"$(git rev-parse --path-format=absolute --git-common-dir)"/cairnkit-hooks/NAME`. It holds no
path, so a moved or copied repo keeps working. Session start replaces a path that an earlier
install stored. A hook in that folder that already runs memory gets no second run, and the tool
names it. Git older than 2.54 does not read `hook.*`, so it ignores these settings with no
error: only the hook in its hooks folder runs. The tool writes nothing then, and it says so.
Install and refresh remove a `post-commit` block that 0.3.1 wrote.

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

- `pre-commit`: when `PY` can import the tool, `PY -m cairnkit hook pre-commit || exit 1`.
  Otherwise it prints one line that names `memory init --refresh`, and refuses only
  `memory-bank` and `.memory-path` in the staged files, with `sh`, `git` and `grep`.
- `post-checkout`: runs `PY -m cairnkit hook post-checkout` only when `$1`
  (the old HEAD) is all zeros, which is `git worktree add`. It never fails.
- `pre-push`: a short shell block. When `PY` is executable it
  runs `PY -m cairnkit hook pre-push` with stdin, stdout and stderr on `/dev/null`,
  under a wall-clock bound of 3 seconds (`timeout` / `gtimeout` when present,
  else `perl` `alarm`+`exec`, which ships on macOS and Linux). The perl
  command runs in a group that discards output, so the shell's alarm line is
  not printed. With none of those tools the command runs unbounded. It ends
  with `|| true`. It does not read the hook arguments. It never fails the push.
  When the commit-msg guard is installed, a check comes first. It begins with
  `# Refuse a new commit with an AI identity or attribution line.`, reads the
  ref list on stdin and puts it back for the rest of the file. For each ref it greps
  the commits that no remote holds, with the identity patterns on
  `Name <email>`, a tab and the short id, and with the message patterns on the
  message. A new commit is one that `.git/cairnkit-guard-base` and a shallow edge do
  not reach. That file holds a `^HASH` line for each ref when the check was installed. If
  it is gone, the hook writes it again. A new commit with an AI identity, or with a line and
  the current user as committer, prints the lines and exits 1. A line with another committer
  is named. An older commit counts in one line. With the argument `cairnkit-fix-commit`, the
  check instead amends HEAD to drop such lines and an AI author, and exits. The rebase that
  a refused push prints runs it.
- `post-merge`: that same quiet tidy block. It never fails the merge.
- `commit-msg`: a comment line that starts with
  `# Refuse AI self-attribution lines.`, then `grep -iqE` with the patterns of
  `[commit_msg_guard]` on the lines of `$1` that do not start with `#`. A
  match prints the line and the settings that stop a tool adding it, and exits 1.
  Then a line `# Refuse an AI author or committer.`, and `grep -iE` with
  `identity_patterns` of `[commit_msg_guard]` on `git var GIT_AUTHOR_IDENT` and
  `git var GIT_COMMITTER_IDENT`, as `Name <email>`. An identity pattern must not end
  in `$`. A match prints the identity and exits 1. It installs when an active rule fact matches
  `attribution`, `co-author` or `generated with` (no case), or with
  `--commit-msg-guard`.

### Agent hooks

Files that git does not track. A tracked file is never written; the tool
prints the commands instead. Each file is added to `.git/info/exclude`.

`CMD` is `PY -m cairnkit hook EVENT --agent AGENT`. A timeout is in seconds.

| Agent | File | Events and hook events |
|---|---|---|
| Claude Code | `.claude/settings.local.json` | `SessionStart` (matcher `startup\|resume\|clear\|compact`, timeout 10): `session-start`. `Stop` (timeout 30): `stop`. `PostToolUse` and `PostToolUseFailure` (timeout 5): `after-shell`. `UserPromptSubmit` (timeout 5): `prompt`. `SubagentStart` (timeout 10): `subagent-start`. |
| Codex | `.codex/hooks.json` | The same shape, with no `PostToolUseFailure`. |
| Grok Build | `.grok/hooks/cairnkit.json` | The same shape as Claude Code. |
| Cursor | `.cursor/hooks.json` | `version: 1`. `hooks.sessionStart[]` (timeout 10): `session-start`. `hooks.stop[]` (timeout 30, `loop_limit: 1`): `stop`. `hooks.afterShellExecution[]` and `hooks.postToolUseFailure[]` (timeout 5): `after-shell`. `hooks.preCompact[]` (timeout 5): `pre-compact`. |

A JSON entry has the shape `{"matcher": ..., "hooks": [{"type": "command", "command":
CMD, "timeout": N}]}`, except in Cursor, where an entry is `{"command": CMD, "timeout":
N}`. A hook entry belongs to the tool when its command holds `cairnkit hook`, or the
old `project_memory hook`. Install first removes the entries that belong to the tool,
then adds new ones, so a hook is never written twice. Other entries stay.

Pi and OpenCode load code, so the tool owns one generated file for each. The first
line holds `cairnkit hook`. A file with that path and without that text is not
changed.

| Agent | File | Tool events and hook events |
|---|---|---|
| Pi | `.pi/extensions/cairnkit.ts` | `session_start` and `session_compact`: `session-start`, held until the next prompt. `before_agent_start`: `prompt`, then returns a hidden message with the held load and the news. `tool_result` for `bash`: `after-shell`. `agent_end`: `stop`, sent once as a follow-up that starts a turn. |
| OpenCode | `.opencode/plugins/cairnkit.js` | `session.created` and `session.compacted`: `session-start`, sent with `noReply`. `session.idle`: `stop`, sent once as a prompt. `tool.execute.after` for `bash`: `after-shell`, sent with `noReply`. |

### `tool-version.json`

In the memory folder. It records the tool version that last wrote the blocks
and hooks of this repo:

```json
{"version": "0.2.0", "at": "2026-10-25T09:00:00+00:00", "blocks": ["CLAUDE.local.md"]}
```

`blocks` lists the files that got a rules block, relative to the checkout.
When `version` is lower than the running tool, the session start prints one
line that asks for `memory init --refresh`. The same line appears when the
local `post-merge` hook still holds `# cairnkit:docs-check`, the docs check
that older builds of the same version wrote. A release that changes a block
or hook raises the version.

## 7. The hook commands

`memory hook EVENT --agent AGENT` reads a JSON object on stdin (or nothing).
The session key is `session_id`, else `conversation_id`, else `default`. When the
environment holds `GROK_HOOK_EVENT`, the agent is `grok`, because Grok Build also runs
a project's Claude Code and Cursor hooks. With no memory folder, each event does
nothing and exits 0, except that `pre-commit` still refuses a private memory path.

- `session-start`: ends the facts that the 0.3.1 commit miner wrote, and removes its
  files. Runs the auto-tidy step. Names new native memory notes. Prints the output of
  `memory load` and a short rules text. For `cursor` it prints
  `{"additional_context": TEXT}`. For `grok` it holds the text in the session file,
  prints `{"systemMessage": "Project memory is ready."}`, and the next `after-shell`
  gives the text. A payload with `source: compact` keeps the same session. It always
  exits 0.
- `stop`: when `stop_hook_active` is true or `loop_count` is above 0, it says
  nothing more. Else it runs auto-tidy when the last tidy is more than one day old.
  Then it builds a message from these parts: problems from `memory check --strict`,
  the loop nudge, the news (see `prompt`), and the events of this session. The events
  are a command that failed at least twice and then passed, a command that failed at
  least twice and has not passed, and a revert since the session started. Each event
  is named once. With no event, and when the work changed and no fact was written, the
  message reminds the agent once for each state of the work. Output is
  `{"decision": "block", "reason": TEXT}` for `claude`, `codex` and `grok`,
  `{"followup_message": TEXT}` for `cursor`, TEXT on stdout with exit 0 for `pi` and
  `opencode`, and TEXT on stderr with exit 1 for `generic`. With nothing to say it
  prints nothing, or `{}` for `codex` and `cursor`, and exits 0.
- `prompt`: prints the news on stdout. The news is a compaction notice, up to 5 facts
  that another branch or auto-tidy wrote or ended since the load, and up to 5 stored
  facts that match files changed since the load, traps first. Each item is named once.
  It always exits 0.
- `after-shell` and `post-tool`: record one shell or tool result for the loop
  breaker and for the events of `stop`. Then they add the same news as `prompt`, and
  the load that `grok` holds. The third identical failure adds the nudge. The output is
  `{"hookSpecificOutput": {"hookEventName": EVENT, "additionalContext": TEXT}}` for
  `claude`, `codex` and `grok`, `{"additional_context": TEXT, "followup_message": TEXT}`
  for `cursor`, and TEXT on stdout for `pi` and `opencode`. A payload with no command, or
  a command and no outcome, is not counted. The hook always exits 0.
- `subagent-start`: prints `{"hookSpecificOutput": {"hookEventName": "SubagentStart",
  "additionalContext": TEXT}}`, where TEXT is a load of 300 words. It writes nothing.
- `pre-compact`: marks the session as compacted, so that the next news says so.
- `pre-commit`: exits 1 only when a staged path is `memory-bank`, `.memory-path`
  or inside the memory folder. Else it prints each stored trap (up to 3) that matches
  the staged files on stderr, each on one line labelled as data, and exits 0. A problem in the
  memory never stops a commit.
- `post-checkout`: makes the `memory-bank` link and the adapter files in a new worktree.
- `pre-push` and `post-merge`: run the same auto-tidy step as `session-start`.
  `post-commit` does the same, for a hook that 0.3.1 wrote.
  They do not count as a session start. The tidy command prints nothing
  (including when the interpreter lacks cairnkit). They always exit 0. With no
  memory folder the tidy does nothing. The tidy
  command's shell bounds hung process start to 3 seconds when
  `timeout`, `gtimeout`, or `perl` is on `PATH` (stock macOS has `perl`).
  The perl command runs in a group that discards output, so the shell's
  alarm line is not printed. Without any of those the start is unbounded.
  Once cairnkit is running, an in-process budget of 3 seconds stops a
  slow tidy and leaves the memory as it is. A held tidy lock can add up to about
  three seconds to a push or a merge before that budget stops the wait.
  `git push --no-verify` skips the pre-push hook, as git does for every
  pre-push hook. Before the gate they only report. After the gate they retire.
  The same lock, and the same retire id, keep one retire when a session start
  runs at the same time.

### Loop breaker

`<memory>/.loop-breaker.json` stores `command` and `streak`. It is safe to
delete. A pass or a different command resets the streak. The third identical failure
makes `after-shell` add the nudge when an adapter can see the failure, and `stop`
shows it while the streak stands. The nudge says to stop retrying, find the cause,
search the memory, or ask the person.

| Agent | Sees a command failure |
|---|---|
| Claude Code | Yes. `PostToolUseFailure` runs `memory hook after-shell`. `PostToolUse` fires only on a success. |
| Codex | Yes. `PostToolUse` fires for each result. The exit code is in the text of the result. |
| Cursor | Yes. `postToolUseFailure` runs `memory hook after-shell`. `afterShellExecution` has no exit code, so it says nothing about the outcome. |
| Grok Build | The same events as Claude Code. Not checked in a real run. |
| Pi | Yes, for `bash`, from `tool_result`. Not checked in a real run. |
| OpenCode | Yes, for `bash`, from `tool.execute.after`. Not checked in a real run. |
| Generic | No per-command hook, so it cannot report a command. `stop` still shows the nudge when a failure was recorded another way. |

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
{"source": "git+https://github.com/matthewpergolski/cairnkit@v0.2.0", "commit": "<40 hex>", "version": "0.2.0", "installed_at": "2026-10-25T09:00:00+00:00"}
```

When the update found a release tag, `source` is `git+<url>@<tag>`. When the
remote has no release tag, `source` is `git+<url>` with no tag. The record
counts only when its source is the current source and its version is the
running version. Parsing the record and parsing the current source give the
same source. A pin on the uv receipt does not make them different.

The channel is in `$XDG_CONFIG_HOME/cairnkit/channel`, else
`~/.config/cairnkit/channel`. It holds `stable` or `dev`. `memory update --channel`
writes it. With no file, an install pinned to `@dev` is on `dev`, and any other
install is on `stable`.

The user cache is `$XDG_CACHE_HOME/cairnkit`, else `~/.cache/cairnkit`:

- `update-check.json`: the last update check (`checked`, `source`,
  `installed`, `newer`, `from`, `to`, and `failed` after a failure). It is
  fresh for one day, or one hour after a failure.
- `update-notice.json`: the last update notice that a load showed. It holds
  the notice to once per version pair.
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
- text that looks like a secret (keys, tokens, passwords, private keys, payment keys,
  bearer tokens, named secrets such as `CRON_SECRET=`, secrets in URLs) in any field, a damaged
  line or `config.toml`. Each read masks it as `[secret: NAME]`. It stays on disk until a purge,
  and `memory repair` does not settle it;
- a change to an unknown fact;
- `superseded_by` or a link to an unknown fact;
- the current `held_by` of a promoted fact, when it does not exist here or in the history of any
  branch. `memory change ID --status active` clears it;
- a missing, broken or wrong `memory-bank` link, or a real folder in its place, in any checkout.

A writer name that differs from the file name is a warning, not an error.
So is an active rule fact that `AGENTS.md`, `CLAUDE.md` or `CLAUDE.local.md`
already says in the same words. So is a `*.md` file in `notes/` or `branches/` that
holds a secret shape, a line of the `.memory-old` copy with one, and a fact that holds a plain
word from a `.env` file. `--strict` makes each warning an error. A value in git history or in
Claude Code's own memory is a note and sets no exit code, because this tool does not change
either one.
