# cairnkit

cairnkit gives any coding agent a private memory for a project, and the memory
is meant to run by itself. It is a command-line tool that you install once. It
is not a template to fork.

The memory lives **outside** the project, in a sibling folder. The project
holds only a link to it, and git ignores the link. You cannot commit or push
the memory by mistake.

Each fact is one short, dated line in a JSON Lines file. The tool never edits
or deletes a fact. To change a fact, it adds a new record. Old facts stay as
history.

## The goal

Read this section first. It is the standard for each feature, review and
proposal. The other sections describe what the tool does today. When one of
them disagrees with this section, that is a gap. It is not a reason to change
the goal.

cairnkit must just work with any coding agent, and it must be pleasant for the
agent and the developer. The developer talks to the agent and uses their
skills, such as pstack. The tool brings the memory and makes the agent use it.
Things are remembered, forgotten and tidied with no work from the developer.
If the developer must do this work, there is no reason to use the tool.

The memory is personal. It belongs to one developer, and each project has its
own memory, which the developer can move wherever they want. The tool does not
share a memory, or an enforcement of a memory, with other contributors. The tool
does not write either one to a tracked file.

### How memory must work

1. **Capture.** The agent writes a fact with `memory add` when something
   significant happens: a decision, a mistake, a correction, a surprise, or a
   failure and what fixed it. It does not capture routine steps or text that git
   or the code already holds. Each fact stays in the history. The tool sees
   events, such as a failed command or a revert, and names the event to the
   agent. The tool writes no text that loads.
2. **Load.** Rules and pinned facts always load. All other facts compete for a
   word budget. A fact about the work in progress ranks higher, and a newer fact
   ranks before an older one. With no signal about the work, one third of the
   budget keeps one place for each area, and a trap holds that place. A fact that
   does not fit is not forgotten. It stays searchable, and it comes back when its
   area is in use.
3. **Refine.** The agent replaces, ends, links or pins a fact when it learns more.
   This is never a required step. A fact that nobody refines stays eligible.
4. **Forget.** A fact stops loading only because of a recorded event, or because it
   loses its place in the word budget. These are the events: a newer fact replaced
   it, the agent marked it wrong or ended it, its end date passed because the agent
   set one, its branch is confirmed merged, or it is a short-term note and its source
   file is gone. A long-term fact whose source file is gone does not end. The load
   names it to the agent, and the agent decides. The clock alone ends nothing, and
   neither does silence from the agent, so a vacation changes nothing. The archive
   keeps each ended fact. Only `memory purge` deletes data.

Each step must also work inside a long session, because good memory makes
sessions longer. Do not assume a session start or a session end comes soon. The
agent writes and refines during the session. Memory survives a compaction, and
the agent hears what changed in the memory since it last loaded.

[The test record](docs/forgetting-tests.md) holds the evidence for these steps and
its limits. The tool supports each type of memory in
[Memory types](#memory-types): archive, long-term, short-term, episodic and
semantic.

### How to judge a change

**If the developer must act, the feature is not finished.** Also:

- Setup is one step, once per project.
- The agent decides the judgment cases. A queue that a person must review is not
  a fix.
- Capture must be selective, and it must not lose what is important. Do not fix
  bad memory by turning capture off. Fix what the agent is prompted to capture,
  or fix what loads.
- Do not end a fact because of its age. Do not add a clock in another form, such
  as active days or a count of loads.
- Each agent gets the same result. A feature for only some agents is not
  finished.
- A problem in the memory must not stop unrelated work, such as a commit.
- Look for secrets at capture, because only `memory purge` can remove one.
- A rule in memory can only ask. A behavior that must never happen needs a
  check that fails, such as a git hook.

Forgetting needs no approval, because a retired fact stays in the archive and
can come back. A value that looks secret is masked at each read, and the rest of
the fact stays readable. The agent can replace that fact and purge the old record
by itself. The agent asks the developer only when a decision is consequential: a
purge of anything else,
because it deletes data for good, or overruling a stated fact in a way that
changes what an agent does. A new fact that only disagrees stays beside the
old one.

The tool cannot force a model to obey. It has four controls:

- It puts the memory in the session at the start.
- It adds news during the session, where the agent tool allows this.
- It can send the agent back once at the end.
- A git hook can refuse what a script can check.

### Where it falls short today

Each row is a defect, not a design choice. Do not use a section below to argue
that a manual step is intended. This list holds the known gaps and may not be
complete. Remove a row in the change that fixes it.

| Goal | What happens today |
|---|---|
| Setup is one step | Codex asks for its own trust step. The developer approves the hooks once with `/hooks`. `memory init` and `memory status` say so only after Codex has run a session. Codex does not record the approval in a place the tool reads, so `memory status` keeps the line while Codex is in use. |
| Setup is one step | When git tracks an adapter file, the tool writes nothing there and prints the commands to add by hand. When `core.hooksPath` names a folder outside the repo's git folder and git is older than 2.54, the git hooks do not run, and `memory check` says so. An older git ignores `hook.*` config, so a repo connected under a newer git also runs no memory hook when an older git makes the commit, and the tool cannot see that. |
| Any agent | A tool with no adapter gets the memory only when someone connects it by hand with the commands of `memory hooks install --agent generic`, or tells the agent to run `memory load`. |
| Any agent | Real-agent behavior is not tested beyond this: a real Claude Code run answered from memory, and its failure hook fired. Pi and OpenCode ran `session-start` in the real tools, but no model reply was possible because of account errors. Codex and Grok Build had no verified real run, because of the trust step and account errors. This record holds no real run for Cursor. See [Supported agents](#supported-agents). |
| Each agent gets the same result | Grok Build reads only `systemMessage` from `SessionStart`, so a hook cannot add the memory to the context there. The memory reaches the model at the first tool result. A reply before the first tool has no memory. |
| Each agent gets the same result | Cursor adds no text at a prompt. News and the one reminder wait for its next `Shell`, `Write` or `Delete` tool result. The load after a compaction waits for that result or its next stop. This comes from its public docs. No real Cursor run tested it. |
| Each agent gets the same result | A subagent gets a load at its start on Claude Code and Codex. The hook is also written for Grok Build, but nobody tested it. These stay unwired, so a subagent misses the memory unless its brief says to run `memory load`: Cursor, because its docs let `subagentStart` only allow or deny; Pi, because it has no built-in subagents; OpenCode, because its docs name child sessions and no plugin event for them. |
| Each agent gets the same result | The prompt that names new native memory notes reads only Claude Code's store. OpenCode has no per-prompt news. It hears news and the one reminder after a `bash` tool. |
| Stored text is data | The tool knows that an agent wrote a rule only from the agent tool's environment markers. An agent tool with no marker, or an agent that claims basis `told`, still writes a rule that prints as an instruction. A `told` rule from an agent names that agent. An agent can end or replace a rule that binds, because the tool cannot prove what the owner said in the session. The tool prints a line at once and names the rule once in the next load, and the agent must tell the owner. A hand-edited fact file can claim anything. |
| Capture | A fact that the agent never writes is lost. The tool names events at stop and reminds the agent once at its next prompt or tool result. A session that ends first, such as one run of `claude -p`, hears no reminder. It cannot make the agent write. This is an accepted risk in [the test record](docs/forgetting-tests.md#accepted-risks). |
| Hands-off | A stop that carries no event can still block once, to give the load to Grok Build when no tool ran, or to Cursor after a compaction when no tool ran. These tools have no other way to add it. The generic adapter has only stop, so its news and its one reminder also arrive there. A health warning blocks like a health error, once, because `--strict` fails on it. |
| Capture | Stop names a correction only when a hook sees the prompt: Claude Code, Codex, Cursor and Pi. The OpenCode plugin docs name no prompt hook, and the Grok Build hook docs name no prompt field, so these two hear only about a lost file, and a file that the owner asked to remove costs them one block. The test reads English words in the prompt. It reads a request to remove a file from one clause, and the words must match the path: `remove scratch files` covers `scratch.txt` and not `.env.local`. A request in other words, such as `remove temp files` for `tmp.txt`, costs one block. A lost file is found by comparing the disk with the session start, so each agent hears it. A file inside a folder that git does not know at all is not seen, and neither is that whole folder, because it is most often build output. |
| Forget correctly | A wrong trap that nobody corrects keeps loading. An old trap with no signal can stay out of the load. Both are accepted risks in [the test record](docs/forgetting-tests.md#accepted-risks). |
| Forget correctly | A rebase-merged or fetched branch with a local copy reads as open until that copy is deleted. A merged branch with no local copy and a remote copy reads as open until the remote copy is gone. A branch that came after its note and left before tidy saw it reads as unknown, and tidy names the note. So does an old fact whose branch is already gone. A stale note on such a branch stays. A false end would be worse. One false end remains: a memory moved to a new clone reads a branch as ended when that branch was never pushed and had no commit of its own when the note was written. |
| No clock in another form | `auto_tidy = "auto"` only reports for the first 3 session starts and 7 days, the later of the two. This is a time gate on tidy. It does not read the age of a fact. A short-term note past its end date, or with a merged branch, leaves the load at once, because a reader computes that. A repeat of the same text and a short-term note whose source file is gone keep loading until the gate opens, because only tidy ends them. |
| A repo with notes before the tool | A tracked file that teaches the old layout keeps teaching it until an agent edits it, and a hook keeps running the old checker. The tool names each line and never edits it. The worklist marks a repeat only when the words match. It does not mark the same rule in other words. |
| Forget correctly | A repeat in other words, in another case or with a plural loads twice until an agent settles the pair, because auto-tidy retires only the same text byte for byte. On the labelled set it catches 3 of 29 repeats with 0 false retires of 51, and 62 pairs go to the agent task, 24 of them repeats. The task lists at most 20 at a time and leaves out a pair with one swapped word or a change in numbers alone, so 1 labelled repeat of the 25 is not shown. A scan of a large memory gives each fact an equal share of 30000 comparisons, so it can miss a pair whose shared words are all common. See [the test record](docs/forgetting-tests.md#results-near-repeats). |
| Forget correctly | A fact that the 0.3.1 miner wrote and that a later gate run accepted stays, because nothing proves who accepted it. |
| Load | Rules past 1000 words do not load, against "rules always load". The limit fills with rules that a person stands behind, then with agent data rules, so an owner rule is never held while a data rule prints. Inside a class, a rule with no check goes first, and then the newest. The load names up to 5 held ids and the command that prints them all (`memory load --budget 0`). `memory check` warns at 500 words, and all the presets together hold 368. The limit stops a pile of rules from filling each session. |
| The load never blocks | Under a git that does not answer, a load reads the branch from the git folder. With a HEAD that names no branch, it holds back the notes of other writers and says how many. Merged state and changed files are not read, so an ended note can still show and the rank has no signal about the work. A write stays under 5 seconds. Its similar and conflict checks are skipped, and it says so. |
| The load never blocks | With `skills_auto_update = true`, an update of pstack runs inside the session start and can pass the budget. A disk that hangs on a read is not covered: the budget limits git and locks. |
| Look for secrets | A bare word after `password is`, with no quote and no digit, reads as English, so it is stored unless a `.env*` file holds it. A phrase with spaces after a label has only its first word masked, unless it is in quotes. The tool reads `.env*` files only near the checkout root. A value that only a `.env*` file makes secret prints in clear in a clone with no such file, or after the file is removed, because the tool keeps no record of a value: a stored hash of a secret is a new risk. A value with a hard catch ends at the first load that sees it, if the agent follows the load's line: write a clean fact with `--supersedes`, then purge the old one. A plain word stays, and it prints in clear there too. Under a name such as `AWS_REGION`, `APP_VERSION` or `CLIENT_ID` that says what the value is, no value counts. A secret stays on disk until `memory purge` removes it, and `memory check` says so. A plain `.env` word in a fact is a warning, because no shape tells a secret from a word, and the fact can stay masked. A hit in `notes/`, `branches/` or `<repo>.memory-old` is a warning too, and these files have no purge. Git history keeps what was committed: `memory check` says so, and the tool does not rewrite history. The tool names a value in Claude Code's own memory and never edits that store. A token cut short by a torn line matches no shape, so `memory repair` prints only plain words from a torn line. |
| Enforce what must never happen | A standing wish, such as "Every PR must attach a demo video", has no "did this still happen" check. `--enforced-by githook:pre-push` reads as enforced because of the tool's own block, which never looks at the wish. `--enforced-by test:PATH` looks only for the file, and nothing runs it. `memory check` looks for the check of a `ci:`, `lint:`, `test:` or `githook:` rule by name. It does not prove that the check fails when the rule is broken. Another type of `enforced_by` stays as written. With a Python that is gone, the hooks do nothing else, and a memory folder inside the repo at a custom path is not refused. The attribution guard installs only when the memory holds a rule against AI attribution. Plain `memory init` adds no such rule. A git hook cannot see a pull request body, so a pull request footer has no check here. `git commit --no-verify` and `git push --no-verify` skip the guard, as git does for each hook. An AI commit from before the guard goes out with a count, and a trailer that another person committed is named, because the guard must not trap a person. The tool lists known names, so a new tool passes until it has a known shape, such as a dotted version. |
| No work for the developer | A memory moved away from both the project and its old place needs `memory init --path NEW_PLACE`, because the tool does not search the disk. A memory renamed to a name that is not its recorded name or the project's name needs the same command, and so do several copies with its id, because a copy can be an old backup. The load names each one for the agent. A memory or project moved before the first load of this version has no record, so the tool can only name a likely folder beside the project. The same holds for a plain folder with no git. |
| Each project has its own memory | A copied repo uses the first repo's memory until it takes a memory of its own. It hears this once, at its first load or add, and `memory check` says it each time. With the owner's old path gone, a move and a copy look alike, so a load gives the memory to neither. Each repo that sees the other on its record hears the memory's name, and `memory init` in one of them takes it. A copy moved away from both parent folders is not seen, so such a pair hears nothing and both write there. A new clone at the owner's old path reads as the owner. |
| Each project has its own memory | A project with no record and no `origin` that names an earlier place has no proof of an earlier name, so a memory left beside it under that name is not named. |
| A personal tool the owner can roll back | Under 0.3.1 a torn line stops each commit, also after a dev repair, because a repair keeps the bytes. So does a `repair` record or a `branch_tip`-only change that an earlier dev build wrote. The owner removes the line by hand. See [docs/update.md](docs/update.md#after-a-roll-back-to-031). |
| A repo with notes before the tool | `memory migrate --yes --untrack` stages the removal only in the checkout where it runs, and all checkouts share one memory, so the move changes each. From a worktree, the main checkout shows ` D memory-bank/status.md` until you run the printed `git -C MAIN rm -r --cached memory-bank`. The plan and the run print that command. |
| No work for the developer | When a newer tool exists, the load says "Tell the owner" once per version pair, and `memory status` always says it. Nothing installs the update by itself. |

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

- `memory init` is the one setup step. It makes the memory folder `../demo.memory`
  and the link `memory-bank`, and it adds the link to `.git/info/exclude`, so git
  ignores it. It connects the agent tools that it finds and adds personal git
  hooks. It prints a short result. `--verbose` prints each step.
- `memory add` writes one fact. It prints the new fact id.
- `memory load` prints what an agent sees at session start.
- `memory search` finds facts by words or by a question. You do not need quotes
  around more than one word.
- `memory check` checks the facts and the link, and looks for common secret
  shapes in the facts, damaged lines, `config.toml`, `notes/`, `branches/`, the
  `.memory-old` copy of a migration, git history and Claude Code's own memory.
- `memory status` prints the version, the installed short commit when one is
  recorded, the install source, the channel of a git install, and the update
  lines. When a newer commit exists, it also shows what changed (subjects, or a
  GitHub compare URL).

After `memory init`, the agent loads the memory at session start and checks it at
session end. To see the plan first, run `memory init --dry-run`. To skip the
agent tools and the git hooks, run `memory init --no-hooks`.

`memory init` adds four personal git hooks: `pre-commit`, `post-checkout`,
`pre-push` and `post-merge`. They are not shared. When `core.hooksPath` names a folder
outside the repo's git folder, they live in `.git/cairnkit-hooks`, and the local git config
runs them beside that folder (git 2.54 or newer). The tool changes nothing in that folder and
leaves `core.hooksPath` as it is. `memory check` and `memory status` print the real hook state. The last two run auto-tidy after
a push or a merge. They print nothing. Git hooks work for every agent, including an
agent with no adapter.

`memory hooks install` remains for repair and for one specific agent. For example,
`memory hooks install --agent pi` writes the Pi adapter when the tool does not find
Pi by itself.

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
  - The pstack skills check (`memory status`, `memory init`,
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

`memory init` writes one untracked adapter file for each agent tool that it finds.
It finds a tool by its project folder (`.claude`, `.codex`, `.cursor`, `.grok`,
`.pi`, `.opencode`), or by its command on `PATH` (`claude`, `codex`, `cursor-agent`,
`grok`, `pi`, `opencode`). Grok Build also runs a project's Claude Code and Cursor
hooks, so the tool writes the Grok adapter only when neither of those is found.

| Agent | Adapter file | Status |
|---|---|---|
| Claude Code | `.claude/settings.local.json` | Checked against the public docs. A real run answered from memory, and its failure hook fired. |
| Codex | `.codex/hooks.json` | **Experimental.** Project hooks run only in a trusted project. No verified real run, because of the trust step and account errors. |
| Cursor | `.cursor/hooks.json` | **Experimental.** Cloud agents do not run `sessionStart`. This record holds no real run. |
| Grok Build | `.grok/hooks/cairnkit.json` | **Experimental.** No verified real run, because of account errors. |
| Pi | `.pi/extensions/cairnkit.ts` | **Experimental.** `session-start` ran in the real tool. No model reply was possible, because of account errors. |
| OpenCode | `.opencode/plugins/cairnkit.js` | **Experimental.** `session-start` ran in the real tool. No model reply was possible, because of account errors. |
| Any other agent | None. `memory hooks install --agent generic` prints the two commands to connect by hand. | Manual. |

`memory instructions --write-instructions` is optional. It writes the rules block
only to untracked files: `CLAUDE.local.md`, plus the copies
`.cursor/rules/cairnkit.mdc` and `.pi/APPEND_SYSTEM.md`, all through
`.git/info/exclude`. It never writes a cairnkit block into tracked `CLAUDE.md` or
`AGENTS.md`. Codex and OpenCode get the rules from their session-start hook.

Details: [Agent hooks](#agent-hooks) and [docs/layering.md](docs/layering.md).

## How updates work

```sh
memory update                 # check, fetch, build, install, verify
memory update --check         # only say if an update exists
memory update --dry-run       # check, then list the steps
memory update --channel dev   # follow the dev branch; --channel stable goes back
```

`memory update` installs from the place you installed it from: the GitHub URL
above, another git URL, or a local folder. For a git URL on the `stable` channel,
it takes the highest release tag, or the newest commit if there are no release
tags. On the `dev` channel, it takes the newest commit of the `dev` branch. An
install pinned to `@dev` follows that branch with no choice. A saved `--channel`
wins over a pin. For a local folder, it takes the current commit. It reads the
source from the uv receipt. It shows each step and prints the old and the new
version. A failed build leaves the installed tool as it was. When nothing is
newer, it changes nothing. One exception: the first `memory update` after a
fresh install has no record of the installed commit, so it installs once
more to write that record. A local folder must have no uncommitted changes,
and `memory update` does not pull it.

The code of v0.3.1 has no `--channel`. To go from there back to dev, run
`uv tool install --force --reinstall git+URL@dev`, then `memory update --channel dev`. With
`dev` only in a local folder, run `memory update --source FOLDER`. `memory update --source URL`
from a dev build takes the highest release tag, so it is a roll back. The version number can
stay the same: read `memory --version`. Details:
[docs/update.md](docs/update.md#from-stable-back-to-dev).

`memory status` shows one line when the source is newer. A load shows that
line once per version pair. Both show another line when this repo's hooks and rules block come
from an older version, or when the local post-merge hook holds a cairnkit
block that has no docs check. Then run `memory init --refresh`. It rewrites
them in place. Each repo catches up the next time it is used. An update
never touches memory folders. Details: [docs/update.md](docs/update.md).

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

`memory hooks uninstall` takes back what the tool wrote and nothing else: the hook files
and the hook lines in their settings, each rules block that `--write-instructions` wrote, a
file that held only that block, each tool folder that this leaves empty, and the
`.git/info/exclude` lines of those files. Your own text and files stay. It changes no tracked
file, and no folder outside the repo's git folder.

These stay, and you can remove them by hand:

- the lines `memory-bank` and `.memory-path` in `.git/info/exclude`;
- tracked hooks in `.githooks/`, a pointer line in `AGENTS.md`, or a block in a global
  `core.hooksPath` folder, that an older version wrote;
- the `memory-bank` link in each other worktree. Remove it there too;
- the files `.git/cairnkit-memory`, which records where the memory is, and
  `.git/cairnkit-copy-noted`;
- the local git settings `cairnkit.sharedmemory` and `cairnkit.notearlier`, if you set them;
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

You run one command, once per project:

```sh
memory init
```

After that, **agents do the rest**:

- At session start, a hook gives the agent the rules and the useful facts.
- During the session, the agent writes facts with `memory add` and changes them
  with `memory change`. No hook or quality gate writes a fact.
- During the session, the agent hears news where its tool allows this (see
  [Agent hooks](#agent-hooks)): facts that another branch or auto-tidy wrote or
  ended, and stored facts that match files it changed after the load. Each item is
  named once.
- At session end, a hook runs the checks of `memory check --strict`. When a check
  finds a problem, the agent must fix it before it finishes (in tools that support
  it). The hook also names events: a command that failed and then passed, a command
  that still fails, and a revert. When the agent changed the work and wrote no fact,
  the hook reminds it once. The agent may say that nothing is worth a fact.
- A git pre-commit hook refuses a commit only when it stages a private memory path:
  `memory-bank`, `.memory-path` or a path inside the memory folder. A problem in the
  memory does not stop a commit. The hook also prints a stored trap that names a staged
  file. Git output reaches every agent, including one with no adapter. The
  trap never refuses the commit.
- A git post-checkout hook links each new worktree (`git worktree add`) to
  the memory. In a worktree that still has no link, `memory load` and
  `memory check` make it and say so in one line. This needs symlink support
  (on Windows: developer mode or admin). All worktrees of a bare repository share one
  memory, named after the bare repository.

**Events are named, not stored.** The tool writes no fact for an event, so no text
from the tool can load as memory. The agent decides what the event means. A stop
message asks, for example, "`npm test` failed 3 times, then passed. What fixed it?".
After the same command fails 3 times in a row, the agent hears this: stop retrying
it, find the cause, search the memory, or ask the person.

**The agent hears about a possible contradiction.** When `memory add` writes a fact
in a named area, it looks for up to 3 active facts in that area that share at least
25 percent of their words. It names each one and prints the command that replaces
it. It ends nothing. The `general` area gets no such check, so a fact with no
`--area` gets none. For a fact with basis `told`, the prompt says to ask first.

**Clean-up needs no person.** At each session start, the hook retires what
needs no judgment:

- a repeat of a fact, byte for byte, apart from whitespace and a final `.`, `,`, `;` or `:`
  (the older fact is superseded). A change in case, a plural or a stop word is not a repeat here.
  That pair goes to the agent task, and both facts stay;
- a short-term note that has ended;
- a short-term note whose `source: file:PATH` is in no checkout.

The same step runs after a push or a merge. In a long session, the stop hook also
runs it when the last tidy is more than one day old. This timing never ends a fact
by its age. The git hooks are personal. They live in this clone's `.git/hooks`.
They are not shared, and a teammate never runs them. A push or a merge does not
count as a session start. The git hook never stops git, and it prints nothing. A shell bound of 3 seconds covers a hung
python start when `timeout`, `gtimeout`, or `perl` is available (stock macOS
has `perl`). The perl command runs in a group that discards output, so the
shell's alarm line is not printed. Without any of those the start is unbounded.
Once cairnkit runs, the same short budget stops a slow tidy. A held tidy lock can
add up to about three seconds. `git push --no-verify` skips the pre-push hook, as
git does for every pre-push hook.

Nothing is deleted. Each retire is a change record and one line in
`auto-tidy.log`, with the command that undoes it. A retire never touches a rule, a
pinned fact, or a fact that someone set back to `active`. A long-term fact with no
repeat is never retired, whatever its age and whatever its source.

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
`proposals/tidy-followups.md`. It lists at most 20 pairs, the likeliest repeats
first, so an agent can finish it. A pair with one swapped word or a change in
numbers alone, such as `port 8080` and `port 9090`, is two facts and no task.
`memory load` prints `Tidy follow-up pending: N pairs; task: <path>` until the
agent has resolved them. N is the number in the file. The file is written only
when its text changes and removed when it is empty. The scan runs at each session
start and write, with a limit of 30000 comparisons and 1 second. When the time
runs out, the file stays as it was. An agent
resolves a pair with `memory change` (supersede or end one fact) or
`memory change ID --link related:OTHER --reason ...` (or `contradicts:OTHER`). Two
facts that disagree stay until the agent decides. `memory tidy` lists the other
changes that an agent can apply with `memory tidy --apply ID ...`: an exact repeat,
a pinned short-term note that ended, and a chain of superseded facts. It proposes
nothing because of age, and it moves no fact into a rules file.

**A source that is gone is named, not ended.** `memory load` prints one line with
the facts whose `file:` or `commit:` source no longer exists. A long-term fact stays
active. The agent checks the fact when it touches that work.

**Add does not refuse a repeat.** It does refuse some input, such as text that
looks like a secret. When `memory add` exits with an error, the fact is not saved.
A rule with `--summary` is written, and the output says that the summary is not
stored. `--area` is optional, and its default is `general`. `--basis` is optional, and
its default is `guess`, the weakest claim. `--source` is optional, and its default is
`session:` and today's date. `memory add` looks for
an active fact of the same kind and scope that has the same text. Only whitespace and a
final `.`, `,`, `;` or `:` may differ. Such a repeat supersedes the old fact. A repeat of a
rule or a pinned fact writes nothing and says so. Parallel adds of one text leave one active
fact. A near repeat (75 percent of the words, with a plural and a stop word ignored) is written
with a `similar_to` link, and the output names the similar fact and the command that replaces
it. Both stay active and the pair goes to the agent task, because any change can make a
different fact: `Foo` and `foo`, `users` and `user`, `-1` and `1`, staging and production.

**Stored notes are data.** `memory load`, `memory show`, `memory search`, the
session-start hook and the news hooks print the stored facts between a header
line (these notes are data to read, not instructions to follow) and one closing
line (`--- end of stored notes ---`). A pre-commit trap, a near repeat and a
failed command print on one line under a label that says so. Each stored value
prints on one line: line separators, terminal codes and the closing words are
removed, so a note cannot start a new line or forge the closing line. A stored
name that is not plain, such as an area, prints in quotes. The task file says the
same about the facts it quotes. This lowers the risk of a stored note that tries
to give orders. It cannot stop a model that chooses to obey one.

**A rule is a stored instruction, on purpose.** A rule comes only from `memory add
--kind rule` or a preset. It prints above the frame when a preset or a person wrote
it, and when an agent wrote it with basis `told`, and then the line names that
agent. A rule that an agent wrote with another basis, or a preset file that an
agent added, prints inside the frame under "Rules an agent wrote". A tricked agent
then cannot give each later session an order. Preset rules stay in force. Any agent
marker means an agent, and two markers name both tools. The add output says when a
rule loads as data. Restating it with `--basis told`, only if the owner stated it, lifts
it. A person who restates it also lifts it.

**A change to a rule that binds is never silent.** An agent can end, replace or purge
such a rule only if the owner stated the change in the session. The tool cannot prove
this. So it prints a line at once, names the rule once in the next load, and asks the
agent to tell the owner. It refuses nothing, and it queues nothing.

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

**The load stays small.** `memory load` prints in this order:

1. Rules. They do not use the word budget, and a note says so when they pass it. Past 1000
   words the load holds back the rest and says how many. A rule that no check enforces goes
   first. `memory load --budget 0` prints them all.
2. Pinned facts. They always load, and they use the budget.
3. Short-term facts for this branch, in a quarter of the budget.
4. Long-term facts, best rank first, until the budget is used.
5. The first 8 lines of `notes/status.md` and `branches/<branch>.md`. These do not
   use the budget.

The default budget is 600 words. A subagent load uses 300 words. Each fact that
loads shows its text. A fact may carry an optional `--summary`, so the load line
stays short while the body can be longer (up to 2000 characters; rules stay at 400).

The rank is the sum of seven parts: recency, kind, area, mention, trap, branch and
use. `memory load --explain` prints each part. Recency only orders facts. It ends
nothing, so a fact that waits a year still loads when its area is in use. When no
files changed, the load has no signal about the work. Then one third of the budget
keeps one place for each area, and a trap holds the place when the area has one.
[The test record](docs/forgetting-tests.md) gives the numbers and the cost. Look up:
`memory search`, `memory show`, `--pinned`, `--link`, `memory tidy`.

## Why

- An agent starts each session with no memory of the last one.
- Prose memory files grow, go stale, and nobody knows which line is still true.
- A memory folder inside the repo can get committed, and a deleted worktree
  loses its copy.

**The codebase stays the source of truth.** Memory is a private aid. When a
lesson matters to every contributor, a person or an agent moves it into a tracked
rules file, a doc, a test or a lint check, and marks the fact `promoted`. The tool
does not do this move.

## Three layers

| Layer | What it holds | Loaded at session start? |
|---|---|---|
| **Archive** | Every fact and every change record ever written: the `facts/*.jsonl` store. Nothing in it is deleted. | No. Use `memory search --all`. |
| **Long-term** | Active facts with `scope: long`: rules, decisions, lessons, traps, preferences. This is the default. | Yes, within the word budget. Rules come first. |
| **Short-term** | Active facts with `scope: short`: working notes for one branch or task. Each ends when its branch reads as merged, or when an agent ends it. `--expires DATE` sets an end date on purpose. | Yes, for the current branch only, in a quarter of the budget. |

A short-term fact that has ended reads as `expired`. The tool computes this
when it reads, and auto-tidy writes it down later. `memory keep ID` makes a
short-term fact long-term. (`promote` is the old name of `keep`.)

A branch reads as merged when its tip is in the default branch, by a merge or by a
squash (git 2.38 or later). A branch in no ref ends the note only when a record says
that this clone held it: `memory add` and auto-tidy record its tip. With no record,
merged is unknown, the note stays, and `memory tidy` names it. A remote copy with no
local branch counts as open work. A note on the default branch itself never reads
as merged. Outside git, or on a detached HEAD, `--short` has no branch, so the note
ends only when an agent ends it. `--expires` takes effect only with `--short`.

**Forgetting is a status change.** `memory change ID --status expired` or
`--status wrong`, with a reason. The fact leaves the load, and the archive
keeps it, so an agent can answer "did we try this before?".

**The only deletion is `purge`**, for a secret or private data stored by
mistake: `memory purge ID --reason secret --yes`. It removes every line for
that id and writes a tombstone (id, date, reason, no content). The ID is a
record's id, or the `line-HASH` that `memory check` prints for a damaged line.
Purge refuses a fact with a mask that holds true text, until a new fact replaces
it with `--supersedes` or you give both `--reason secret` and `--yes`.

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
| Extract | `memory add`. The agent writes the fact. The tool writes no fact from a commit. |
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
- **Any agent tool on the same computer.** A tool with an adapter gets the memory
  at session start. Any other agent gets it only when its instructions tell it to
  run `memory load` (`memory instructions` prints that block).
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
`memory init` and `memory hooks install` add the guard by themselves when the
memory holds a rule against AI attribution. The guard is local to this clone, and
it needs only `sh`, `git` and `grep`. `commit-msg` refuses an AI attribution line, and
an author or committer that is an AI tool, such as `Cursor Agent`. A person named
Cursor Smith or Claude Monet passes. `pre-push` refuses the same in a commit that
skipped `commit-msg`, such as a rebase. It reads only commits that no remote holds and
that came after the guard was installed on this clone. An older AI commit goes out, with
one line that gives the count. A shallow clone does not read its edge. A contributor's
commit does not stop your push, and a trailer that another person committed is named. An
AI committer among new commits is refused at all times. A refused push prints a rebase that
names the pushed ref and can move nothing else, and an override config, and tests run each one
as printed. A deleted base file is not an install, so each commit that no remote holds is then
checked. A new install starts a new base. A refused trailer names the setting
that turns it off in Claude Code and Cursor. The tool does not write those settings,
because they are global. To change what counts as a tool, set `identity_patterns` under
`[commit_msg_guard]` in `config.toml`.

Once you add a preset, its rules live in memory. Every session loads them
first. Nothing is written to a tracked file. An instruction for every
contributor still belongs in hand-written `CLAUDE.md` or `AGENTS.md` (see the
next section). The cairnkit rules block itself stays local:
`memory instructions --write-instructions` writes `CLAUDE.local.md` (and
untracked harness copies). It changes no tracked file. An old block in a tracked
file stays, and the tool says so. Cloning a repo never needs cairnkit for those files. The only
committed cairnkit output is optional Nessa Docs pages under `docs/state/`, and
only when someone runs `memory docs`.

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
- `memory skills install pstack` shows the plan. `--yes` does it. With no
  `--tool`, it updates only the tools that already have pstack. A rerun with
  nothing to do says so. To add pstack to a new tool, name it: `--tool NAME`
  (`claude`, `codex`, `cursor`, `opencode`, `pi`, `grok`, or `all`). For
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
- pstack is optional and not about memory, so no session start or `memory
  check` names it. `memory status` prints one line when a tool that has pstack
  is behind. The line names the command that updates only those tools.
- `memory init` and `memory migrate` print one line at the end, once per memory
  folder. It names what is behind, and the tools with no pstack and the command
  to add one. The end of a migration does not
  depend on skills. `memory skills status` always lists every tool.
- `skills_check = false` in `config.toml` turns the line off.
  `skills_auto_update = true` makes the session-start hook update what is
  installed, and print one line that it did. It adds no tool. The default is off.

## Greenfield vs brownfield projects

- **Greenfield** (a new project, or one with no agent memory yet):
  `memory init`. Step by step: [docs/greenfield.md](docs/greenfield.md).
- **Brownfield** (a project that already has agent notes, hooks or rules):
  - A real `memory-bank` folder with files is refused by `memory init`. Use
    `memory migrate`. It shows the plan and changes nothing. Read it, then run
    `memory migrate --yes`. It moves the old folder aside, runs `init`, copies
    the notes into `notes/`, writes a worklist of candidate facts, and connects the
    hooks. It writes no fact and it edits no project doc. The lines that name the
    old layout go to a task file for an agent. A rerun reads only that task, and it
    removes the task when nothing is left. Steps and the manual fallback:
    [docs/brownfield.md](docs/brownfield.md).
  - Existing hook settings are merged, never replaced. A tracked hook config is
    left alone, and the tool prints the lines to add by hand.
  - Existing rules files keep their hand-written text.

## Commands

| Command | Who | What it does |
|---|---|---|
| `memory init [--path DIR] [--dry-run] [--no-hooks] [--verbose] [--preset NAME ...] [--no-default-rules] [--write-instructions[=local]] [--instructions-file PATH]` | you, once | The one setup step. Makes the memory folder, links it into every checkout and worktree, ignores the link, adds the preset rules, connects the agent tools it finds and adds the git hooks. `--no-hooks` skips the agent tools and the git hooks. `--verbose` prints each step. With `--write-instructions`, writes the rules block to untracked `CLAUDE.local.md` (and harness copies) and moves any cairnkit block out of tracked `CLAUDE.md` / `AGENTS.md`. `shared` is refused. |
| `memory migrate [--yes] [--from DIR] [--path DIR] [--preset NAME ...] [--no-default-rules] [--untrack]` | you, once, for a project with a prose `memory-bank` | Without `--yes`, shows the plan and changes nothing (`--dry-run` is the same; with `--yes` it is refused). With `--yes`: moves the old folder to `<repo>.memory-old`, runs `init`, copies the old files into `notes/`, writes `proposals/migrate-candidates.jsonl` (candidate facts, no fact written, with the lines that only a worktree's own old notes have, without the lines that `AGENTS.md`, `CLAUDE.md` or `CLAUDE.local.md` already hold), runs `check`, and connects the hooks. `--untrack` stages the removal of a tracked old folder; nothing is committed. Lines that name the old layout, old checker hooks and older copies go to `proposals/migrate-followups.md`, a task for an agent; `memory load` reminds the agent until it is done. The plan and the run say which checkout it acts on, what it installs, and each old check, once. A rerun reads only the task, installs nothing, and removes the task when nothing is left. |
| `memory preset list`, `memory preset show NAME [--detect]`, `memory preset add [NAME ...] [--file PATH ...] [--dry-run]` | you, sometimes | Lists the rule presets, prints their rules, adds the missing ones to a memory. `--file` adds the rules of a preset file that the project owns. |
| `memory skills status`, `memory skills install pstack [--tool NAME] [--adopt\|--all] [--yes]` | you, once; the hook, if `skills_auto_update` is on | Shows or installs the pstack skills at user level. Status includes installed/available skill counts. Plan by default; `--yes` acts. `--adopt` (or `--all`) replaces same-named folders so every pstack skill is installed. |
| `memory update [--check\|--dry-run] [--source PATH\|URL] [--channel stable\|dev]`, `memory status` | you, when a line says so | Installs the newest `memory` from its source, step by step. Shows the subjects (or a GitHub compare URL) between the installed ref and the new one. `--channel` saves the channel for a git source. `status` prints the version, the installed short commit, the source, the channel and the update lines. A release has the same version number as the dev builds after it, so `memory --version` adds the channel and commit for a dev build, a checkout or a folder build: `memory 0.3.1 (dev @85b0cd0)`. |
| `memory init --refresh [--dry-run]` | an agent, when the session start says so | Rewrites the rules block, agent hooks and git hooks that memory wrote, in place. Removes a `post-commit` block from 0.3.1, as a session start also does by itself. Never adds a second block. |
| `memory hooks install [--agent auto\|claude\|codex\|cursor\|grok\|pi\|opencode\|generic] [--dry-run] [--no-git-hook] [--commit-msg-guard[=local]]`, `memory hooks uninstall [--dry-run]` | you, for repair or for one agent | `memory init` already runs the install. It connects the agent tool and git, and it prints each step. `--no-git-hook` skips every git hook. `--commit-msg-guard` adds the guard when no rule asks for it. `memory hooks uninstall` removes only what it added. |
| `memory tidy`, `memory tidy --apply ID ...` | an agent | Lists exact repeats, pinned short-term notes that ended, and chains of superseded facts. Writes a report to `proposals/<date>.md`, and refreshes the agent task. `--apply` writes only the chosen changes. |
| `memory tidy --auto [--dry-run]`, `memory tidy --release` | the session-start and stop hooks; the personal pre-push and post-merge hooks; an agent, to look or to release a hold | Retires the clear cases now: a repeat of the same text (the older fact is superseded by the newer), a short-term fact past its end date or whose branch is merged, and a short-term fact whose `source: file:PATH` is in no checkout. Never touches a rule, a pinned fact, or a fact that someone set back to `active`. A fact with basis `told` is not superseded by a fact with another basis. One line per retire in `auto-tidy.log`, with the undo command. Deletes nothing. A push or a merge does not count as a session start. `--release` clears the hold that an undo set, after the agent has reviewed the rule. |
| `memory add [--area AREA] [--short] [--expires DATE] [--until-merged [BRANCH]] [--supersedes ID]`, `change`, `keep`, `search`, `show` | agents | Write, change and find facts. `add` does not refuse a repeat. It supersedes an exact repeat and links a near repeat with `similar_to`. It names older facts in the same area that may be stale. `search` takes one or more words with no quotes. It ranks facts by BM25: a fact that holds any word of the query is found, a rare word counts more than a common one, and filler words such as `the` and `how` and a plural ending do not matter, so a question works. When no whole word matches anywhere, it tries the words (4 letters or more) as the start of a longer word, so `deploy` finds "deployment" and `pass` finds "passed", and it says so on the first line. A short start must be a whole word with an ending: `retr` does not find "retries". A fact id is one word, so `memory search f-20261026-a053` finds that fact only. `--strict` brings back the old match, where every word must appear as a substring (also for an empty query, which is an error without it). `search` also lists up to 5 lines of `notes/`, best first, after the facts, as `memory-bank/notes/PATH:LINE: text`. It does not follow links out of `notes/`. |
| `memory load [--area AREA] [--budget N] [--explain]`, `memory check [--strict]` | hooks | Session start and session end. |
| `memory check --advisory` | you, sometimes | Also lists the rules that no check enforces. |
| `memory instructions [--write-instructions[=local\|shared]] [--instructions-file PATH]` | anyone | Prints the rules block for agents. With `--write-instructions`, writes it to the same files as `memory init`. `shared` is refused. |
| `memory docs [--dry-run] [--force] [--check]` | you, after `memory init` for a write; you or CI for `--check` | Writes a Nessa Docs atlas under `docs/state` (system map, agent session flow, fact lifecycle; plus package architecture when `src/cairnkit` is present). No model and no network. Refuses an existing atlas unless `--force`. `--force` rewrites only the atlas pages, and it removes an atlas page that no longer has a source. An atlas page is a page with the exact front matter that this command writes. All other Markdown in that folder stays and never counts as stale, and a file at an atlas path stays too, with a `keep` line. A hand-written page with that same front matter, line for line, counts as an atlas page. An atlas page whose front matter was changed counts as hand-written. No hook runs it, because the folder may be tracked. `memory status` shows one line when the pages differ from the code. `--check` compares `docs/state` to a fresh atlas and writes nothing. No `memory init` is required. Exit 0 and no output when the folder holds no atlas page or the pages match. Exit 1 and one repo-relative path per line when an atlas page differs, is missing, or has no source now. `sourceRevision` lines are ignored. Combining `--check` with `--force` or `--dry-run` is an error. Browse the folder with [Nessa Docs](https://github.com/nessalabs/nessa-docs). |
| `memory repair` | an agent, when a stop or `memory check` names it | Settles a bad line with an appended record, and the bytes stay. It prints only plain words and masks. It does not settle a value that looks secret. Drops a bad setting from `config.toml`, masks each value, and keeps a copy in the next free `config.toml.bad` name. It deletes no fact. |
| `memory purge ID --reason secret --yes` | an agent, after a clean replacement | Removes a secret for good. `ID` can be `line-HASH` for a damaged line. |

### Where the memory lives

The tool uses the first of these:

1. the `--path DIR` flag (`init` writes it to `.memory-path`);
2. the `MEMORY_DIR` environment variable;
3. the first line of `.memory-path` in the main checkout, when that folder holds a memory;
4. a `memory-bank` link that resolves to a memory;
5. the place that this repo last recorded in its git folder;
6. the default: `../<project folder>.memory/`. A nested repo or submodule uses
   `<outer repo>.<path inside it>.memory/` beside the outermost repo, so the memory
   stays out of the outer work tree.

Rename or move the project, and the memory comes along. No step is needed. Move the
memory folder beside the project or beside its old place, under its recorded name or the
project's name, and the next load finds it by its id and relinks. With another name, or with
more than one folder that has its id, the tool adopts none, because a copy can be an old
backup. The load names each folder, and `memory init --path FOLDER` picks one. For a move
farther away, the load names the old place and asks for `memory init --path NEW_PLACE`.

`memory init` never refuses because of a neighbor. It makes this project's own memory. A
folder `<name>.memory` with no folder `<name>` is named only when `<name>` is a name that this
project is known to have had: in its record, or the last part of its `origin` URL. The load and
`memory check` then keep a note with the command that adopts it, until you adopt it, until you
run the printed `git config --add cairnkit.notearlier NAME`, or until no such folder sits
there. Other memories are not named. `memory init` makes no empty memory only when this project is known to have had one
that is gone. It names what it found and exits 1. A connected project with no memory and no
such proof gets its memory at session start.

A memory has one owner. `--path` to a memory that another project uses is honored, and
`memory init` and each load say so in one line. To silence that line because you share the
memory on purpose, run `git config cairnkit.sharedmemory true` in that repo. A load never
moves the owner. Only `memory init` by a repo takes a memory, and only when its owner is gone.
A copied repo hears once which memory it uses and the command that keeps those facts in a memory
of its own. The first repo keeps its memory. `memory init` in a copy whose first repo is still
there starts an empty memory on purpose.

A memory that lands inside a work tree (an older memory, a `--path`, or no
writable folder outside) gets a line in that repo's `.git/info/exclude`. Git must then
confirm that it ignores the folder. If not, `memory init` refuses and `memory check` fails.
On a branch that tracks `memory-bank/` from before a migration, git replaces the link
with that folder. The load says so, and it still reads the real memory.

### The gitignore trap

Write `memory-bank`, **not** `memory-bank/`. A pattern with a trailing slash
matches only a directory. Git sees a link as a file, so `memory-bank/` does
not ignore it, and `git add -A` stages the link.

`memory init` writes `memory-bank` and `.memory-path` to `.git/info/exclude`.
That file is local, and it covers every worktree. Nothing in the repo changes.

## Agent hooks

`memory init` and `memory hooks install` find the agent tools for this project.
[Supported agents](#supported-agents) says how. With no match, the install uses
`generic`, which prints the commands to connect by hand.

| Agent | Session start | Session end | During the session | After a compaction | Subagent load |
|---|---|---|---|---|---|
| Claude Code | `SessionStart`: stdout goes into the context | `Stop`: `{"decision": "block"}` makes the agent continue once | `UserPromptSubmit`, `PostToolUse`, `PostToolUseFailure` | `SessionStart` with `compact` reloads | `SubagentStart`, 300 words |
| Codex | `SessionStart`: stdout goes into the context | `Stop`: JSON `{"decision": "block"}` | `UserPromptSubmit`, `PostToolUse` | `SessionStart` with `compact` reloads | `SubagentStart`, 300 words |
| Cursor | `sessionStart`: `additional_context` | `stop`: `followup_message`, `loop_limit: 1` | `beforeSubmitPrompt` reads the prompt. `postToolUse` for `Shell`, `Write` and `Delete` adds `additional_context`, and `postToolUseFailure` counts failures. | `preCompact` holds a load for the next of those tool results, or for stop | None |
| Grok Build | `SessionStart`: reads only `systemMessage`, so the load waits for the first tool result | `Stop`: `{"decision": "block"}` | `UserPromptSubmit`, `PostToolUse`, `PostToolUseFailure` | `SessionStart` with `compact`; the load waits for the next tool result | `SubagentStart` hook is written, not tested |
| Pi | `session_start`; the load goes out at `before_agent_start` | `agent_end`: a follow-up that starts a turn, once | `before_agent_start`, `tool_result` for `bash` | `session_compact`; the load goes out at the next `before_agent_start` | None |
| OpenCode | `session.created`: a prompt with `noReply` | `session.idle`: a prompt, once | `tool.execute.after` for `bash` | `session.compacted` reloads | None |
| Generic | `python -m cairnkit hook session-start` prints text | `... hook stop` exits 1 with a message on stderr | None | None | None |

**Long sessions.** News covers facts from other branches, auto-tidy changes, and
stored facts that match files changed after the load. Traps come first, and each
item is named once.

**A stop blocks only for a new event.** A block costs the owner a turn. The events are a health
problem, a command that failed at least twice and then passed, a revert, a correction, a lost
file, and a loop nudge that no tool result carried. Each is named once in a session. Plain work,
such as an edit or a commit, gets one short reminder per session, and no block. No adapter can add
text at stop without a turn (Claude Code, Codex and Cursor say so in their docs), so the reminder
and the news wait for the next prompt or tool result, which adds text with no turn. A fact written
in the session ends the reminder. In 20 ordinary turns, an agent that never writes sees no block
on a plain script and 2 on a mixed one. `tests/test_stop_replay.py` replays both on each adapter.

**Corrections and lost files.** When the owner's prompt corrects the agent, or the session deleted
a file that was here at its start, stop names it once and asks if a trap belongs in memory. The
tool writes no fact. A fact written after the correction, or one that names the file, ends the
question. So does a prompt that names the file or asks to remove it, because the owner knows
about it. A file that commits from elsewhere removed (a pull, a merge, a rebase, a branch switch)
raises no question. The HEAD reflog tells them apart. With the reflog off, only a deletion in the
worktree raises it.

**One answer.** `memory status`, `memory check` and `memory load` print the same answer line, and
stop blocks on what `--strict` fails. A healthy load prints no answer, so it spends no words.
`memory check: ok` means that nothing is open. Work outside the facts prints as `to do`. It exits 0,
also with `--strict`, because it must not stop a commit.

**Native memory.** Claude Code keeps its own per-project notes, and other agents
cannot see them. When that store has new notes, the session start names them once,
so that an agent can copy what matters with `memory add`. The tool copies nothing.
Only Claude Code has a per-project store that a file path can find.

A repeated failing command is a loop. After the same command fails 3 times, the
hook tells the agent to stop retrying it, find the cause, search the memory, or ask
the person. Claude Code, Cursor and Grok Build report a failure with
`PostToolUseFailure` or `postToolUseFailure`. Codex reports the exit code in the
text of `PostToolUse`. Pi and OpenCode report `bash` results from their adapters. The
generic adapter cannot see a command. `stop` still shows the nudge when something
else recorded the streak.

Rules for every adapter:

- It merges with the settings that are there. It never replaces them. It
  refuses a file that is not valid JSON. The Pi and OpenCode adapters are generated
  files. The tool keeps a file of that name that it did not write.
- It never writes a config file that git tracks. It prints the lines instead.
- It is safe to run again. It writes each hook once.
- The hooks call `python -m cairnkit` with the full path of the Python
  that runs the tool, so they do not depend on `PATH`.
- The session-start hook never blocks a session. It has a total budget of 7 seconds, under the
  shortest hook timeout of any adapter. Optional steps stop first and run at a later session
  start, and the load still prints the facts. A lock wait ends after 5 seconds. Then a hook goes
  on, and `memory add` says that it wrote nothing.
- The stop hook never loops: it stays quiet when the tool says it already continued the agent
  once. It blocks once for a given problem, and each line names its command.

## CI

There is no memory folder on CI. `memory check` prints
`memory: not loaded: no memory folder at <path>` and exits 0.

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
- [docs/forgetting-tests.md](docs/forgetting-tests.md): the test record behind the forgetting rules, and its limits.
- [benchmarks/README.md](benchmarks/README.md): the retrieval and forgetting benchmarks.
- [ROADMAP.md](ROADMAP.md): what may come next.
- [CONTRIBUTING.md](CONTRIBUTING.md): how to work on the tool.

## License

MIT. See [LICENSE](LICENSE).
