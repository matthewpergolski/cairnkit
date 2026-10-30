# cairnkit

cairnkit gives a project a private memory for coding agents. It is a
command-line tool that you install once. It is not a template to fork.

The memory lives **outside** the project, in a sibling folder. The project
holds only a link to it, and git ignores the link. You cannot commit or push
the memory by mistake.

Each fact is one short, dated line in a JSON Lines file. The tool never edits
or deletes a fact. To change a fact, it adds a new record. Old facts stay as
history.

## Install

You need git, Python 3.12 or later, and [uv](https://docs.astral.sh/uv/).

```sh
uv tool install git+https://github.com/matthewpergolski/cairnkit
cairnkit --version
```

This installs two commands: `cairnkit` and `memory`. They are the same
program. `memory` is the short name. This README uses `memory`.

If the shell does not find the command, run `uv tool update-shell` and open a
new terminal.

## Quick start

Run this in a new, empty folder. It takes about two minutes.

```sh
git init demo
cd demo
memory init
memory add "The test suite needs Docker running." --kind trap --area tests --basis seen --source session:2026-10-25
memory load
memory search docker
memory check
memory status
```

- `memory init` makes the memory folder `../demo.memory` and the link
  `memory-bank`. It adds the link to `.git/info/exclude`, so git ignores it.
- `memory add` writes one fact. It prints the new fact id.
- `memory load` prints what an agent sees at session start.
- `memory search` finds facts by words or by a question.
- `memory check` checks the facts and the link, and looks for secrets in the facts.
- `memory status` prints the version, the installed short commit, the install
  source, and the update lines. When a newer commit exists, it also shows
  what changed (subjects, or a GitHub compare URL).

To connect your agent tool, run `memory hooks install` in the project. Then
the agent loads the memory at session start and checks it at session end.
Start with `--dry-run` to see what it would write. The same command adds two
personal git hooks, `pre-push` and `post-merge`. They run auto-tidy after a
push or a merge. They are not shared. On a merge, when memory exists and
`docs/state` is out of date, `post-merge` prints
`cairnkit: docs/state looks out of date; run memory docs --force`.
The merge still succeeds. They work for every agent, including
OpenCode, Pi and Grok Build.

## What it is, and what it is not

It is:

- A local command-line tool, with no runtime dependencies beyond Python.
- A store of dated facts for one project, shared by all its worktrees.
- A set of hooks that give the facts to an agent and check them at the end.

It is not:

- A server, a cloud service or a sync tool. The memory stays on one computer.
  No fact is sent anywhere. These are the only uses of the network:
  - The update check (session start, `memory status`, `memory update
    --check`): `git ls-remote` on the git URL you installed from. A local
    folder is read with local git only.
  - `memory update`: fetches the checked commit from that git URL. Its
    `uv build` can download build tools from PyPI.
  - The pstack skills check (session start, `memory check`, `memory init`,
    `memory migrate`, `memory skills status`): reads `pstack/plugin.json`
    from `github.com/cursor/plugins`, at most once a day (once an hour after
    a failure). It runs only when Claude Code, Codex, Cursor, OpenCode, Pi or
    Grok Build is found on the computer. `skills_check = false` in
    `config.toml` turns it off, except in `memory skills status`, which you
    run on purpose.
  - `memory skills install pstack --yes`: reads `pstack/plugin.json`, runs
    `git clone` of `github.com/cursor/plugins`, and for Claude Code runs
    `claude plugin marketplace add` and `claude plugin install`.
- A vector database or a model. Search is plain word matching, ranked with BM25.
- A replacement for `AGENTS.md`, `CLAUDE.md`, docs or tests. Instructions for
  every contributor belong there. See
  [How memory fits with CLAUDE.md and AGENTS.md](#how-memory-fits-with-claudemd-and-agentsmd).

## Supported agents

| Agent | What exists | Status |
|---|---|---|
| Claude Code | Hook adapter: `.claude/settings.local.json` (`SessionStart`, `Stop`). | Checked against the public docs. |
| Codex | Hook adapter: `.codex/hooks.json` (`SessionStart`, `Stop`). Tracked `AGENTS.md` pointer to `CLAUDE.md` / `CLAUDE.local.md`. | **Experimental.** Project hooks run only in a trusted project. |
| Cursor | Hook adapter: `.cursor/hooks.json` (`sessionStart`, `stop`). Untracked rules: `.cursor/rules/cairnkit.mdc`. | **Experimental.** Cloud agents do not run `sessionStart`. |
| OpenCode | No hook adapter. No stable untracked project rules file. | Gap: see [docs/layering.md](docs/layering.md). |
| Pi | No hook adapter. `--write-instructions` also writes untracked `.pi/APPEND_SYSTEM.md`. | Local rules path only. |
| Grok Build | No hook adapter. Reads `CLAUDE.local.md` (same file Claude Code uses). | Local rules path only. |
| Any other agent | `memory hooks install --agent generic` prints the two commands to connect by hand. | Manual. |

For an agent with no hook: run `memory instructions --write-instructions`.
It writes the rules block only to untracked files (`CLAUDE.local.md`, plus
harness copies such as `.cursor/rules/cairnkit.mdc` and `.pi/APPEND_SYSTEM.md`,
all via `.git/info/exclude`). It never writes a cairnkit block into tracked
`CLAUDE.md` or `AGENTS.md`. For Codex it adds one generic pointer line to
tracked `AGENTS.md` (create if missing): read `CLAUDE.md` and
`CLAUDE.local.md` when present. Where a harness has no untracked load path
(OpenCode today), do not fall back to a tracked rules block; connect with
hooks or a local config you own. Auto-tidy after a push or merge still runs
once hooks are installed; that does not load the memory.

Details: [Agent hooks](#agent-hooks) and [docs/layering.md](docs/layering.md).

## How updates work

```sh
memory update            # check, fetch, build, install, verify
memory update --check    # only say if an update exists
memory update --dry-run  # check, then list the steps
```

`memory update` installs the newest commit from the place you installed it
from: the GitHub URL above, another git URL, or a local folder. It reads the
source from the uv receipt. It shows each step and prints the old and the new
version. A failed build leaves the installed tool as it was. When nothing is
newer, it changes nothing. One exception: the first `memory update` after a
fresh install has no record of the installed commit, so it installs once
more to write that record. A local folder must have no uncommitted changes,
and `memory update` does not pull it.

`memory status` and the session start show one line when the source is
newer. They show another line when this repo's hooks and rules block come
from an older version. Then run `memory init --refresh`. It rewrites them in
place. Each repo catches up the next time it is used. An update never touches
memory folders. Details: [docs/update.md](docs/update.md).

An install from before the rename to cairnkit (`project-memory`) cannot
update itself, and its hooks call the old tool. Move it in this order:

1. `uv tool install --force --reinstall git+https://github.com/matthewpergolski/cairnkit`
2. In each repo that used the old tool: `memory init --refresh`. It points the
   agent hooks and git hooks at the new tool.
3. Then `uv tool uninstall project-memory`, and the install command of step 1
   again: the uninstall also removes the `memory` link.

Details: [docs/update.md](docs/update.md#from-project-memory-to-cairnkit).

## Uninstall

In each project where you used it:

```sh
memory hooks uninstall   # removes only the hooks that memory added
rm memory-bank           # the link; the memory folder stays
rm -f .memory-path       # only if you used --path
```

These stay, and you can remove them by hand:

- the lines that `memory init` and `memory hooks install` added to
  `.git/info/exclude` (`memory-bank`, `.memory-path`, and the agent hook
  files such as `.claude/settings.local.json`);
- empty `.claude/`, `.codex/` or `.cursor/` folders that held only those hook
  files;
- the rules block, if you wrote one, between the `<!-- cairnkit:start -->`
  and `<!-- cairnkit:end -->` lines, the file `CLAUDE.local.md` if
  `--write-instructions` made it (or `AGENTS.local.md`, which older versions
  wrote), and the `AGENTS.md` that only points to `CLAUDE.md`, if it made
  that;
- the tracked hooks in `.githooks/` from `--commit-msg-guard=shared`.
  `memory hooks uninstall` looks only in the hooks folder that git uses, and
  it never changes tracked hooks;
- the `memory-bank` link in each other worktree. Remove it there too;
- the user cache `~/.cache/cairnkit/`;
- the pstack skills, if you installed them: they are at user level, in
  Claude Code and in `~/.codex/skills`, `~/.cursor/skills`,
  `~/.config/opencode/skills`, `~/.pi/agent/skills` and `~/.grok/skills`.

Then remove the tool:

```sh
uv tool uninstall cairnkit
```

The memory folder (`../<project>.memory/`) is not deleted. Delete it yourself
when you do not need the facts.

## Who runs what

You run two commands, once per project:

```sh
memory init
memory hooks install
```

After that, **agents do the rest**:

- At session start, a hook gives the agent the rules and the useful facts.
- During the session, the agent writes facts with `memory add` and changes them
  with `memory change`.
- At session end, a hook runs `memory check --strict`. When the agent changed
  the work and wrote no fact, the hook reminds it once. When the check finds a
  problem, the agent must fix it before it finishes (in tools that support it).
- A git pre-commit hook refuses a commit that stages the memory link.
- A git post-checkout hook links each new worktree (`git worktree add`) to
  the memory. In a worktree that still has no link, `memory load` and
  `memory check` make it and say so in one line. This needs symlink support
  (on Windows: developer mode or admin). A bare repository is not covered yet.

**Clean-up needs no person.** At each session start, the hook retires what
needs no judgment: exact duplicates and short-term facts that have ended.
The same step runs after a push or a merge. Those git hooks are personal.
They live in this clone's `.git/hooks`. They are not shared, and they are
not written to `.githooks/`. A teammate who does not use cairnkit never
runs them. A teammate who does has their own memory and their own hooks.
The two do not conflict. This works for every agent, including OpenCode,
Pi and Grok Build. A push or a merge does not count as a session start. The git hook
never stops git. It prints nothing. A few-second shell bound covers a hung
python start when `timeout`, `gtimeout`, or `perl` is available (stock macOS
has `perl`). The perl command runs in a group that discards output, so the
shell's alarm line is not printed. Without any of those the start is unbounded.
Once cairnkit runs, the same short budget stops a slow tidy. A held tidy lock can add up to about
three seconds. `git push --no-verify` skips the pre-push hook, as git does for
every pre-push hook.

Nothing is deleted. Each retire is a change record and one line in
`auto-tidy.log`, with the command that undoes it.

The default mode is `auto_tidy = "auto"`. For the first 3 session starts and
7 days (the later of the two), the step only reports what it would retire.
A push or a merge uses that same gate. It does not add to the session count.
Then the step turns itself on. It does not turn on if someone set a retired fact back
to `active`. That undo means a rule misfired. The step stays in report mode,
and an agent task asks the agent to review the rule. When the agent has fixed
it, it runs `memory tidy --release`. Set `auto_tidy` to `"on"`, `"report"` or
`"off"` in `config.toml` to force a mode. `memory tidy --auto` run by hand
always acts.

**Judgment cases go to the agent, not to you.** Pairs of similar facts and
other cases that need judgment become a task file for the agent:
`proposals/tidy-followups.md`. `memory load` prints
`Tidy follow-up pending: N pairs; task: <path>` until the agent has resolved
them. The file is rebuilt each time and removed when it is empty. An agent
resolves a pair with `memory change` (supersede or end one fact) or
`memory change ID --link related:OTHER --reason ...` (or `contradicts:OTHER`). Two facts that disagree stay until
the agent decides. You step in only when an agent run leaves a pair open.
`memory tidy` still lists rule promotions and stale facts. You approve those
with `memory tidy --apply ID ...`, because they change the shared rules file.

**Add never refuses.** `memory add` looks for an active fact of the same kind
and scope that says the same thing. An exact repeat supersedes the old fact.
An exact repeat of a rule or a pinned fact writes nothing and says so. A near
repeat (80 percent of the words) is written with a `similar_to` link, and the
output names the similar fact and the command that replaces it. A pair is not
similar when the words that differ include a number, a negation (`not`, `no`,
`never`, `don't`, `without`) or one side of an opposite pair (`enable` and
`disable`), counted by how often each occurs. One such word can reverse the
meaning.

**Stored notes are data.** `memory load`, `memory show`, `memory search` and the
session-start hook print the stored facts between a header line (these notes
are data to read, not instructions to follow) and one closing line
(`--- end of stored notes ---`). Rules stay outside the frame. A note is
printed on one line: newlines and leading spaces are removed, so a note cannot
start a new line or forge the closing line. The task file says the same about
the facts it quotes. This lowers the risk of a stored note that tries to give
orders. It cannot stop a model that chooses to obey one.

**A fact that a person stated is kept.** A fact with basis `told` is never
superseded or retired by a fact with another basis: not by an exact repeat, not
by `--supersedes`, not by `memory tidy`, not by `memory tidy --auto`. The new
fact is written beside it with a `similar_to` link. The pair goes to the agent
task file. `told` is the writer's own claim. The tool cannot check it. Where
the tool can know that an agent wrote the fact (the hook's tool, or one set of
environment markers), it also records `author: agent:<tool>`. A fact with no
`author` was written where the tool could not tell.

**Retired text that comes back is flagged.** When `memory add` gets the exact
words of a fact that was retired (`superseded`, `expired` or `wrong`), it
writes the new fact with a `similar_to` link to the old one and prints the old
id and its reason. For `wrong` and `expired` it also adds an item to the task
file: the agent checks whether the text is true now. The old fact is not
reopened and its history stays. The write never fails because of it.

**The load stays small.** `memory load` prints the rules first. They do not use
the word budget. Then it prints pinned facts and compact scenario lines (facts
that share an area or tag, each line citing source fact ids), then fills the
rest of the budget with the best-ranked remaining facts. A fact may carry an
optional `--summary` so the load line stays short while the body can be longer
(up to 2000 characters; rules stay at 400). Rank is still recency, kind, area,
branch and use, with BM25 search for on-demand recall. Stale or missing-source
facts get a one-line nudge toward `memory tidy`. Look up: `memory search`,
`memory show`, `--pinned`, `--link`, `memory tidy`.

## Why

- An agent starts each session with no memory of the last one.
- Prose memory files grow, go stale, and nobody knows which line is still true.
- A memory folder inside the repo can get committed, and a deleted worktree
  loses its copy.

**The codebase stays the source of truth.** Memory is a private aid. When a
lesson matters to every contributor, it moves into a tracked rules file, a
doc, a test or a lint check, and the fact is marked `promoted`.

## Three layers

| Layer | What it holds | Loaded at session start? |
|---|---|---|
| **Archive** | Every fact and every change record ever written: the `facts/*.jsonl` store. Nothing in it is deleted. | No. Use `memory search --all`. |
| **Long-term** | Active facts with `scope: long`: rules, decisions, lessons, traps, preferences. This is the default. | Yes, within the word budget. Rules come first. |
| **Short-term** | Active facts with `scope: short`: working notes for one branch or task. Each ends on a date (`expires_at`, default 14 days) or when its branch is merged (`until_branch_merged`). | Yes, for the current branch only, in a small section. |

A short-term fact that has ended reads as `expired`. The tool computes this
when it reads, and `memory tidy --auto` writes it down later. `memory keep ID` makes a
short-term fact long-term. (`promote` is the old name of `keep`.)

**Forgetting is a status change.** `memory change ID --status expired` or
`--status wrong`, with a reason. The fact leaves the load, and the archive
keeps it, so an agent can answer "did we try this before?".

**The only deletion is `purge`**, for a secret or private data stored by
mistake: `memory purge ID --reason secret --yes`. It removes every line for
that id and writes a tombstone (id, date, reason, no content).

## Memory types

Common agent-memory terms, and where each one is in `memory`. Detail:
[docs/memory-types.md](docs/memory-types.md).

| Term | In `memory` |
|---|---|
| Context (working memory) | The agent's own context. The tool does not own it. `memory load` puts memory into it. |
| Long-term | Facts with `scope: long` (the default). Loaded at session start. |
| Short-term | Facts with `scope: short`, and `branches/<branch>.md`. Loaded on their branch only. |
| Archive | All records in `facts/*.jsonl`. Not loaded. Found with `memory search --all`. |
| Episodic | `kind: event`: something that happened, and its result, on `happened_at`. |
| Semantic | `kind: rule`, `decision`, `fact`, `preference`, `trap` or `lesson`. A lesson is the reusable part of an event. |
| Rule tier | `enforced_by: <type>:<value>` names the check that fails when a rule is broken. A rule without it is advisory. `memory check --advisory` lists those. |
| Confidence | `basis: seen`, `told` or `guess`. A guess stays a guess until a new `seen` fact replaces it. |

| Step | Command |
|---|---|
| Extract | `memory add` (the agent writes the fact) |
| Store | one JSON line in `facts/<writer>.jsonl`, append only |
| Retrieve | `memory load` (session-start hook), `memory search`, `memory show` |
| Update | `memory add --supersedes ID` (replace), `memory change`, `memory keep` |
| Forget | `memory change ID --status expired\|wrong`; the archive keeps the fact |
| Delete | `memory purge`, for secrets only |

When a new fact disagrees with an old one, decide: does it replace the old
fact (`--supersedes`), or is it true only in a smaller scope (keep the old
fact, add the new one with a narrower area or `--short`, and link them)?

## Where it works

- **Any git repo.** All worktrees and branches of one repo share one memory.
  Each branch writes its own file. Short-term facts load only on their
  branch.
- **Any folder that is not a git repo.** From a subfolder, the tool walks up
  to the nearest folder with a `memory-bank` link (not past the home folder).
  `memory init` in a subfolder of a project is refused. There are no
  branches, so `--until-merged` and `branches/*.md` do not apply.
- **Any agent tool on the same computer.** A tool connected with
  `memory hooks install` gets the memory at session start. Any other agent
  gets it only when its instructions tell it to run `memory load`
  (`memory instructions` prints that block).
- The memory is a local folder. Another computer does not see it unless you
  copy it there.

## Rule presets

`memory init --preset NAME` adds rule facts from a **preset** (`kind: rule`).
Plain `memory init` adds none: the rules about memory itself ship inside the
tool. Rule facts change like any fact: mark one `wrong` for a project where
it does not apply.

- `commits` (3 rules): never add an AI co-author trailer, never
  add a "Generated with" footer, and never say that a model wrote a change.
  These rules have `source: default`.
- `basic` (8 rules): for an agent that talks about the files in a folder. Ask
  before you change files or run commands, cite the file and line, say when
  the files do not hold the answer, keep contents and secrets private.
- `dev` (16 or 17 rules): for a codebase. It holds `commits`, most `basic`
  rules, and rules for checks, tests, small diffs, git and lock files. It has
  no rule for one tool (uv, ruff, Bun, Biome, version pins). Such rules
  belong in the project's or template's `CLAUDE.md` or `AGENTS.md`, or in a preset file
  that the project owns.

Use `memory init --preset dev`, or `memory preset add dev` for a memory that
exists. Presets stack, and each rule is added once. `--no-default-rules` is
the same as `--preset none`, the default. `memory preset add --file PATH`
adds the rules of a preset file that the project owns, in the same format.
Details: [docs/presets.md](docs/presets.md).

When git runs the commit-msg guard, the co-author rule is **enforced**
(`enforced_by: githook:commit-msg`). All other rules are **advisory**:
no check fails when one is broken. `memory load` shows the two groups apart.

Once you add a preset, its rules live in memory. Every session loads them
first. Nothing is written to a tracked file. An instruction for every
contributor still belongs in hand-written `CLAUDE.md` or `AGENTS.md` (see the
next section). The cairnkit rules block itself stays local:
`memory instructions --write-instructions` writes `CLAUDE.local.md` (and
untracked harness copies) and moves any old cairnkit block out of tracked
files. Cloning a repo never needs cairnkit for those files; the only
committed cairnkit output is optional Nessa Docs pages under `docs/state/`.

`memory hooks install --commit-msg-guard=shared` still writes tracked hooks in
`.githooks/` when a team opts in. The commit-msg hook refuses AI attribution
lines. It needs only `sh` and `grep`. Each clone runs
`git config core.hooksPath .githooks` once.

A rule that a tool checks is better than a note anywhere. See
[docs/greenfield.md](docs/greenfield.md#where-does-each-rule-go).

## How memory fits with CLAUDE.md and AGENTS.md

Ask one question about each line: is it an **instruction** or a **fact**?

| Line | Example | Where it goes |
|---|---|---|
| Instruction: how to work, always true | "Write a failing test first." "Use uv." | `CLAUDE.md`, tracked. `AGENTS.md` points at it. |
| Private instruction for this checkout | "The dev server runs on port 5174 here." | `CLAUDE.local.md`, ignored by git. |
| Fact: true now, with a date and a reason | A decision, a trap, a result, a status. | Memory (`memory add`). Never committed. |

People write the instruction files. A template repo can own them. `memory`
does not change them unless a person runs
`memory instructions --write-instructions` (or one of the few
commands listed on the page below). The rules about memory itself ship inside
the tool.

Claude Code reads `AGENTS.md` only when the project has no `CLAUDE.md`,
`.claude/CLAUDE.md` or `CLAUDE.local.md`. So when a repo has an `AGENTS.md` and
no `CLAUDE.md`, the local write puts `@AGENTS.md` at the top of
`CLAUDE.local.md`, outside the markers, and prints a note. If you keep both
`CLAUDE.md` and `AGENTS.md`, put `@AGENTS.md` at the top of `CLAUDE.md` yourself
to load both.

What memory adds to a project, what each agent tool reads, three examples,
and what is planned: [docs/layering.md](docs/layering.md).

## pstack skills

pstack is a set of agent skills (MIT, from `github.com/cursor/plugins`). The
memory tool does not need it. It checks for it and keeps it current, at user
level only. It writes nothing into a repo.

- `memory skills status` says, for Claude Code, Codex, Cursor, OpenCode, Pi
  and Grok Build, whether pstack is installed and which version. It also says
  the latest version, and for each tool the installed skill count versus the
  available count (so a partial install is visible). The latest version comes
  from `pstack/plugin.json` on the `main` branch of `cursor/plugins`. The
  answer is cached for one day. Offline, it is skipped.
- `memory skills install pstack` shows the plan. `--yes` does it. The same
  command updates. A rerun with nothing to do says so. `--tool NAME` picks one
  tool (`claude`, `codex`, `cursor`, `opencode`, `pi`, `grok`, or `all`). For
  Claude Code it runs `claude plugin marketplace add cursor/plugins` and
  `claude plugin install pstack@cursor-plugins --scope user` (Claude loads
  the plugin's `skills/` as a unit; it does not copy into `~/.claude/skills`).
  For Codex, Cursor, OpenCode, Pi and Grok Build it copies the skill folders
  into that tool's native user skills directory (`~/.codex/skills`,
  `~/.cursor/skills`, `~/.config/opencode/skills` or `$OPENCODE_CONFIG_DIR/skills`,
  `~/.pi/agent/skills` or `$PI_CODING_AGENT_DIR/skills`, `~/.grok/skills` or
  `$GROK_HOME/skills`), with the LICENSE and a marker file
  (`.pstack/install.json`: the version, the source commit, and every skill it
  owns). OpenCode also discovers `~/.claude/skills` and `~/.agents/skills`; Pi
  also discovers `~/.agents/skills`; Grok Build also discovers
  `~/.agents/skills` and Claude-compatible skills; the installer does not write
  those shared folders, so it does not double-install. The command output says
  how many skill(s) were installed and how many were skipped and why. By
  default it keeps a skill of yours that has the same name. `--adopt` (also
  `--all`) replaces those same-named folders so every pstack skill is
  installed, and prints which ones it adopted.
- The advisory is quiet. A session hears only about the tool that runs it. The
  tool is known from the hook's `--agent`, or from one set of environment
  markers (`CLAUDECODE`; `CODEX_CI`, `CODEX_SANDBOX` or `CODEX_THREAD_ID`;
  `CURSOR_AGENT` or `CURSOR_TRACE_ID`; `OPENCODE` or `OPENCODE_SESSION_ID`;
  `PI_CODING_AGENT`; `GROK_SESSION_ID`, `GROK_HOOK_EVENT` or
  `GROK_WORKSPACE_ROOT`). When it is not known, nothing is printed.
  `memory load` (at session start) and `memory check` print one line when
  pstack is missing or behind for that tool. The line ends with
  `Run: memory skills install pstack --yes`. For one pair of installed and
  latest versions it shows in 3 session starts, then stops. A newer latest
  version starts a new count. The count is in `.skills-advisory.json` in the
  memory folder. A manual `memory load` or `memory check` does not use it up.
- `memory init` and `memory migrate` print one line at the end for the tools
  that are found on the machine, once per memory folder. `migrate` also puts
  the line in `proposals/migrate-followups.md`, so the agent runs it.
  `memory skills status` always lists every tool.
- `skills_check = false` in `config.toml` turns the line off.
  `skills_auto_update = true` makes the session-start hook run the update
  itself, and print one line that it did. The default is off.

## Greenfield vs brownfield projects

- **Greenfield** (a new project, or one with no agent memory yet):
  `memory init`, then `memory hooks install`. Step by step:
  [docs/greenfield.md](docs/greenfield.md).
- **Brownfield** (a project that already has agent notes, hooks or rules):
  - A real `memory-bank` folder with files is refused by `memory init`. Use
    `memory migrate`. It shows the plan and changes nothing. Read it, then run
    `memory migrate --yes`. It moves the old folder aside,
    runs `init`, copies the notes into `notes/`, and writes a worklist of
    candidate facts. It writes no fact. `--fix-references` also rewrites the
    old paths in your docs and adds the hooks, and the lines that need
    judgment go to a task file for an agent. You fix nothing by hand. Steps and the manual fallback:
    [docs/brownfield.md](docs/brownfield.md).
  - Existing hook settings are merged, never replaced. A tracked hook config is
    left alone, and the tool prints the lines to add by hand.
  - Existing rules files are not changed, except the optional marked block.
  - Durable lessons go from memory into the shared rules file only through
    `memory tidy` proposals that a person approves.

## Commands

| Command | Who | What it does |
|---|---|---|
| `memory init [--path DIR] [--dry-run] [--gitignore] [--preset NAME ...] [--no-default-rules] [--write-instructions[=local]]` | you, once | Makes the memory folder, links it into every checkout and worktree, ignores the link, adds the preset rules. With `--write-instructions`, writes the rules block to untracked `CLAUDE.local.md` (and harness copies) and moves any cairnkit block out of tracked `CLAUDE.md` / `AGENTS.md`. `shared` is refused. |
| `memory migrate [--yes] [--fix-references] [--from DIR] [--path DIR] [--preset NAME ...] [--untrack]` | you, once, for a project with a prose `memory-bank` | Without `--yes`, shows the plan and changes nothing (`--dry-run` is the same; with `--yes` it is refused). With `--yes`: moves the old folder to `<repo>.memory-old`, runs `init`, copies the old files into `notes/`, writes `proposals/migrate-candidates.jsonl` (candidate facts, no fact written, with the lines that only a worktree's own old notes have, without the lines that `AGENTS.md`, `CLAUDE.md` or `CLAUDE.local.md` already hold), runs `check`. `--untrack` stages the removal of a tracked old folder; nothing is committed. `--fix-references` rewrites exact old paths (`memory-bank/X` to `memory-bank/notes/X`) in top-level and `docs/` `*.md` files and adds the memory hooks where a hook runs the old checker (working tree only, never committed). What is left goes to `proposals/migrate-followups.md`, a task for an agent; `memory load` reminds you until it is done. |
| `memory preset list`, `memory preset show NAME [--detect]`, `memory preset add [NAME ...] [--file PATH ...] [--dry-run]` | you, sometimes | Lists the rule presets, prints their rules, adds the missing ones to a memory. `--file` adds the rules of a preset file that the project owns. |
| `memory skills status`, `memory skills install pstack [--tool NAME] [--adopt\|--all] [--yes]` | you, once; the hook, if `skills_auto_update` is on | Shows or installs the pstack skills at user level. Status includes installed/available skill counts. Plan by default; `--yes` acts. `--adopt` (or `--all`) replaces same-named folders so every pstack skill is installed. |
| `memory update [--check\|--dry-run] [--source PATH\|URL]`, `memory status` | you, when a line says so | Installs the newest `memory` from its source, step by step. Shows the subjects (or a GitHub compare URL) between the installed ref and the new one. `status` prints the version, the installed short commit, the source and the update lines. |
| `memory init --refresh [--dry-run]` | an agent, when the session start says so | Rewrites the rules block, agent hooks and git hooks that memory wrote, in place. Never adds a second block. |
| `memory hooks install [--agent auto\|claude\|codex\|cursor\|generic] [--dry-run] [--no-git-hook] [--commit-msg-guard[=local\|shared]]` | you, once | Connects the agent tool and git. Adds personal `pre-push` and `post-merge` hooks that run auto-tidy. They are not shared. When memory exists and `docs/state` is stale, `post-merge` prints one line that asks for `memory docs --force`. `--no-git-hook` skips every git hook. `memory hooks uninstall` removes only what it added. |
| `memory tidy [--days 90]`, `memory tidy --apply ID ...` | you, sometimes | Proposes clean-up; writes only the approved changes. |
| `memory tidy --auto [--dry-run]`, `memory tidy --release` | the session-start hook; the personal pre-push and post-merge hooks; you, to look; an agent, to release a hold | Retires the clear cases now: an exact duplicate (the older fact is superseded by the newest), a short-term fact past its end date or whose branch is merged, and a short-term fact whose `source: file:PATH` is in no checkout. Never touches a rule, a pinned fact, or a fact that a person set back to `active`. One line per retire in `auto-tidy.log`, with the undo command. Deletes nothing. A push or a merge does not count as a session start. `--release` clears the hold that an undo set, after the agent has reviewed the rule. |
| `memory add [--supersedes ID]`, `change`, `keep`, `search`, `show` | agents | Write, change and find facts. `add` never refuses. It supersedes an exact repeat and links a near repeat with `similar_to`. `search` ranks facts by BM25: a fact that holds any word of the query is found, a rare word counts more than a common one, and filler words such as `the` and `how` and a plural ending do not matter, so a question works. When no whole word matches anywhere, it tries the words (4 letters or more) as the start of a longer word, so `deploy` finds "deployment" and `pass` finds "passed", and it says so on the first line. A short start must be a whole word with an ending: `retr` does not find "retries". A fact id is one word, so `memory search f-20261026-a053` finds that fact only. `--strict` brings back the old match, where every word must appear as a substring (also for an empty query, which is an error without it). `search` also lists up to 5 lines of `notes/`, best first, after the facts, as `memory-bank/notes/PATH:LINE: text`. It does not follow links out of `notes/`. |
| `memory load [--budget N] [--explain]`, `memory check [--strict]` | hooks | Session start and session end. |
| `memory check --advisory` | you, sometimes | Also lists the rules that no check enforces. |
| `memory instructions [--write-instructions[=local\|shared]]` | anyone | Prints the rules block for agents. With `--write-instructions`, writes it to the same files as `memory init`. |
| `memory docs [--dry-run] [--force] [--check]` | you, after `memory init` for a write; you or CI for `--check` | Writes a Nessa Docs atlas under `docs/state` (system map, agent session flow, fact lifecycle; plus package architecture when `src/cairnkit` is present). No model and no network. Refuses an existing atlas unless `--force`. `--check` compares `docs/state` to a fresh atlas and writes nothing. No `memory init` is required. Exit 0 and no output when the folder is missing or the pages match. Exit 1 and one repo-relative path per line when a page differs, is missing, or is extra. `sourceRevision` lines are ignored. Combining `--check` with `--force` or `--dry-run` is an error. Browse the folder with [Nessa Docs](https://github.com/nessalabs/nessa-docs). |
| `memory purge ID --reason secret --yes` | you, rarely | Removes a secret for good. |

### Where the memory lives

The tool uses the first of these:

1. the `--path DIR` flag (`init` writes it to `.memory-path`);
2. the `MEMORY_DIR` environment variable;
3. the first line of `.memory-path` in the main checkout;
4. the default: `../<project folder>.memory/`.

To move the memory: move the folder, then run `memory init --path NEW_PLACE`.

### The gitignore trap

Write `memory-bank`, **not** `memory-bank/`. A pattern with a trailing slash
matches only a directory. Git sees a link as a file, so `memory-bank/` does
not ignore it, and `git add -A` stages the link.

`memory init` writes `memory-bank` and `.memory-path` to `.git/info/exclude`.
That file is local, and it covers every worktree. Nothing in the repo
changes. Add `--gitignore` to also write the lines to `.gitignore`.

## Agent hooks

`memory hooks install` finds the agent tools for this project (a `.claude/`,
`.codex/` or `.cursor/` folder, or the tool on `PATH`). With no match it uses
`generic`, which prints the commands to connect by hand.

| Agent | File (local, added to `.git/info/exclude`) | Session start | Session end | Status |
|---|---|---|---|---|
| Claude Code | `.claude/settings.local.json` | `SessionStart`: stdout goes into the context | `Stop`: `{"decision": "block"}` makes the agent continue once | Checked against the public docs |
| Codex | `.codex/hooks.json` | `SessionStart`: stdout goes into the context | `Stop`: JSON `{"decision": "block"}` | **Experimental.** Project hooks run only in a trusted project, after you review them in `/hooks`. |
| Cursor | `.cursor/hooks.json` | `sessionStart`: `additional_context` | `stop`: `followup_message`, `loop_limit: 1` | **Experimental.** Cloud agents do not run `sessionStart`. |
| Generic | none | `python -m cairnkit hook session-start` prints text | `... hook stop` exits 1 with a message on stderr | Connect by hand. No per-command hook. |

A repeated failing command is a loop. After the same command fails 3 times,
`stop` says to stop, run `memory check`, and ask. Claude Code and Codex see
the failure on `PostToolUse`. Cursor sees it on `afterShellExecution`.
OpenCode, Pi, and Grok Build have no hook adapter, so they cannot observe a
command failure. The generic adapter cannot either. `stop` still shows the
nudge when something else recorded the streak.

Rules for every adapter:

- It merges with the settings that are there. It never replaces them. It
  refuses a file that is not valid JSON.
- It never writes a config file that git tracks. It prints the lines instead.
- It is safe to run again. It writes each hook once.
- The hooks call `python -m cairnkit` with the full path of the Python
  that runs the tool, so they do not depend on `PATH`.
- The session-start hook never blocks a session. The stop hook never loops: it
  stays quiet when the tool says it already continued the agent once.

## CI

There is no memory folder on CI. `memory check` prints
`memory check: skipped: no memory folder at <path>` and exits 0.

## Work on the tool

```sh
git clone https://github.com/matthewpergolski/cairnkit.git
cd cairnkit
uv sync --group dev
./scripts/verify.sh      # same command CI runs for lint and tests
bash scripts/e2e.sh      # end-to-end; CI runs this on Linux
```

To use your checkout as the installed tool, run `uv tool install .` in it.
Then `memory update` installs from that folder. See
[CONTRIBUTING.md](CONTRIBUTING.md).

## More

- [docs/greenfield.md](docs/greenfield.md) and [docs/brownfield.md](docs/brownfield.md): step by step.
- [docs/memory-types.md](docs/memory-types.md): memory types, lifecycle, and where it works.
- [docs/layering.md](docs/layering.md): how memory fits with `CLAUDE.md`, `CLAUDE.local.md` and `AGENTS.md`.
- [docs/FORMAT.md](docs/FORMAT.md): the on-disk format, precise enough to write another implementation.
- [ROADMAP.md](ROADMAP.md): what may come next.
- [CONTRIBUTING.md](CONTRIBUTING.md): how to work on the tool.

## License

MIT. See [LICENSE](LICENSE).
