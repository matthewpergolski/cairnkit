# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- `memory change` takes more than one ID with one set of flags:
  `memory change ID ID ID --status promoted --held-by FILE --reason "..."`. Each ID gets every
  check of a single change (the authority check of `--superseded-by`, the secret check, the link
  and rule checks). One refusal changes no fact, and the error names the ID, so the same command
  can run again after the fix. The output prints `changed ID` for each ID. One ID works as before.
  A `--superseded-by` or `--link` target that is one of the changed IDs is refused: a fact cannot
  replace itself or link to itself.
- `memory change ID --status expired` or `--status wrong` from an agent ends a fact that a person
  stated (a confirmed told fact or the owner's rule) only when the owner's own words in this
  session hold its id: the agent's closing question that a short "yes" approved in this turn, such
  as "Shall I end ID?", or a prompt that the owner typed ("Forget ID."). The transcript must
  hold those words, as for `memory add --basis told`. `--reason` is the agent's text, so it does
  not count. The sentence with the id must have no word such as not, never, keep or unless, and a
  question that the owner typed ("Should we end ID?") does not count. The newest sentence with the
  id decides, so "Keep ID." after "Forget ID." keeps it. Each ID of a batch must be in those
  words, and one refusal changes no fact. The change record gets
  `"author": "agent:<tool>"`, `memory show` names that author, and the output prints a `told:`
  line for each ended fact with its text. The refusal says how to end it: ask "Shall I end ID?" as
  the last sentence and run the change after the yes, or the owner types the id, or the owner runs
  the command from their own shell. An agent can still mark such a fact
  `promoted --held-by FILE`, because the file keeps the rule. The owner at a terminal can change
  any fact as before.
- `memory instructions` and the session rules name the promote step:
  `memory change ID --status promoted --held-by FILE --reason "..."` when a tracked file (a skill,
  `CLAUDE.md`, a lint) now holds a fact. Before, they named only `expired` and `wrong`, so an agent
  marked a codified fact `expired`, which reads as "no longer true".
- `memory change --held-by FILE` prints a note when FILE holds none of the key words of a fact
  (the search words of four letters or more). The note names a file in the same folder, or a
  tracked file with the same name, that holds them, with the command to name it. It also prints a
  note when git does not track FILE. A note is no refusal: the change is written.
- The before-shell hook warns on Claude Code, once in a session, when a `git stash` command can
  take or lose an entry of other live work: all checkouts of a repo share one stash list. It
  speaks while another session, or a helper in another checkout, is live (the markers that
  `## Live work` reads), for `clear`, a `pop`, `apply` or `drop` of the top entry, and a push with
  no message. The warning names the live checkouts and gives `git stash push -m NAME` and
  `git stash apply stash@{n}`, or a commit on a branch. It never stops the command, so Claude Code
  adds it with the tool result. A step in `( )` or `$( )`, or after `sudo` or `env`, counts; a
  `bash -c` script and a git alias do not. A command with no `stash` in it does no more work.
- `memory init --refresh` prints one line that the repo's own hooks run as before, with their
  names and folder: the hooks in the folder that core.hooksPath names (such as `.githooks`; the
  memory hooks run beside them), or hook files in `.git/hooks` that hold more than the memory
  block. It prints nothing when every hook file is the tool's own.
- `memory tidy` proposes to end an active rule or decision that reads as the owner's yes to one
  piece of work (the same test as the note of `memory add`) and names that work in `--files`,
  when that work landed: the main branch (the default branch, `dev` or `develop`, along first
  parents) has a commit that changed each path in `files` after the fact was written or last
  changed. Every other fact never lands: a lasting policy, also one that names a file that
  changes each week such as `CHANGELOG.md`, a fact with no `files`, and a path in the text. A
  commit that deletes a path counts. A rename does not, and the new path is not followed. A
  folder never lands. The root commit and the graft root of a shallow clone count for no path.
  The first commit of work in progress counts too, so the agent checks before it ends one. The
  proposal shows the commit, its date and subject, and the exact
  `memory change ID --status expired --reason "..."` command. For a fact that a person stated (a
  told fact, or the owner's rule), the proposal gives the question to ask the owner first,
  "Shall I end ID, whose work landed?", and the command to run after the yes, with no fact text in
  either, and
  `memory tidy --apply` skips it with a line that says so; `memory change` then prints the owner
  notice. The session start names those facts in one line, and names the ones that a person
  stated. Nothing ends on its own: auto-tidy still never retires a rule or a told fact. A
  `memory change ID --status active --reason "..."` marks one as reviewed. One `git log` reads all
  facts: at most 50 paths, newest facts first, and at most 5000 commits back to the oldest of
  them (0.19 s on a repo of 30,000 commits). `<memory>/.landed.json` (format version 2, written
  whole, a bad entry ignored) keeps the answer until a main branch moves or a fact changes. A git
  that does not answer in 2 s is kept as unknown, so the next hook does not ask again, and it does
  not mark git as stuck, so the load is not partial. The prompt and shell hooks read only the
  cache and run no git for it. `memory tidy` asks again, with 10 s. `memory tidy` also
  proposes to supersede an active rule that a newer fact names by id and says it replaces.
- `memory add --kind rule` (any basis) whose text reads as approval of one piece of work prints a
  note: write it as `--kind decision --basis BASIS --supersedes ID` with `--files PATHS` (tidy
  proposes the end when each path has a commit on the main branch) or `--until-merged BRANCH`,
  and keep `rule` for a lasting policy. For a told rule the note says that the decision replaces
  the rule only when the owner's words in this turn confirm it (the told check), and else to ask
  the owner. An approval is a verb of yes with an object of work right after it: "yes to
  migration 0018", "approved the parser", "go ahead with the move", "signed off on the plan",
  "OK'd the new parser", "LGTM on the refactor", "approves the schema change", "green light for
  the move", or "for this release". "approved licenses", "approved by the owner", a bare `#123`
  or "migration 0001" are no approval. A text that opens with `only`, `never`, `always`,
  `do not`, `every` or `each`, or a negation right before the yes, is a lasting policy.
- When the rules pass the word budget of a load, or the limit of 1000 words, the load names the
  rules most likely stale in one line: rules whose work landed first, then the oldest rules that
  read as approval of one piece of work. A lasting policy is not named. The line names the rules
  that a person stated, and says to ask the owner before one ends. `memory check` prints the same
  line when the active rules pass 500 words.
- `memory add --files PATH [PATH ...]` keeps up to 10 repo paths beside the text, outside the
  400-character limit of a rule and the 2000-character limit of other facts. Paths are cleaned
  (`./`, `//` and `\\` go, an absolute path in the repo becomes relative) and checked: a path
  outside the repo, a character other than `A-Z a-z 0-9 . _ / -` or a value that looks secret is
  refused. The load line shows the first 3, but a rule that loads as an instruction above the
  frame shows none. `memory show` and `memory search` read them all, a
  change keeps them, and a supersede with no `--files` keeps the old fact's files. `memory export`
  writes them as `(files: a, b)` and `memory import` reads them back when each path passes these
  checks; else the end stays in the text. The import's "Added N" counts only the lines it wrote. The "facts that match the
  files you changed" hint and the load rank match a changed file to `files` directly, also a file
  in a folder that `files` names.
- A `told` claim that an agent makes (`memory add --basis told` with an agent marker) binds only
  when it is a near-verbatim copy of one sentence of the owner's evidence in that session: a
  prompt the owner typed, the option the owner picked in an agent question (Claude Code's
  AskUserQuestion; the picked label only), or the question that ends the agent's message when the
  owner's whole prompt is a short yes (`yes`, `go ahead`, `do it`, ...), read from the end of the
  Claude Code or Codex transcript. A message that ends in no question, or a tool step after it,
  gives no approval. The words must be the same and in the same
  order; only articles, `please`, pronouns, punctuation, case, word endings and a rule frame
  (`always`, `from now on`) may differ. A word that turns or limits the rule (`not`, `stop`,
  `skip`, `except`, `until`, `only`, `before`, `yet`, ...), a number, a path or a name may not be
  dropped or changed, and the claim must hold 80 percent of the sentence. An ellipsis in the
  claim (`...` beside a space, or the ellipsis character) marks words left out of one sentence of
  the owner, never a join of two sentences. A typed question and a
  hypothetical (`what if`, `suppose`) state no rule. A claim with a rule and a question binds
  only when it is the owner's whole prompt ("ok let's make these optimizations. how?"), with only
  case, spaces and the marks at its end changed. A question moved next to another sentence, or a
  question with other pronouns, does not bind. A condition the owner typed whole ("If you
  touch the schema, update FORMAT.md") binds whole; a claim that drops the condition does not.
  An attribution in front (`The owner said:`, `Owner (Sam) decided 2026-11-08:`, `User:`) does not
  count against the match. It must name who spoke with a verb such as `said` or the word owner or
  user, and hold no word that turns or limits the rule, so `Never:` or `Optional:` is no
  attribution; context of the agent's own does, and the add output tells the agent to save
  it as a second fact with `--basis seen` and a link, so the owner's words bind alone.
  An approval and an answer count only in their own turn. Else the fact gets `confirmed: false` and
  loads as `told (via agent, not confirmed)` data. The add output says which, and how the owner
  confirms it. The prompt hook keeps this evidence, masked as a whole and then cut, in
  `.sessions/<id>.owner.json`. A person at a terminal binds as before. For Claude Code and Codex,
  `memory add` counts a kept prompt, approval or answer only when the session's transcript holds
  it, and a prompt that names another transcript than the session's is not kept; a transcript
  that cannot be read proves nothing. A session start of the same session (a resume, a
  compaction, a clear or a fork) can name a new transcript, and the check reads the newest one and
  the one before it. `memory add` finds the session by the id in the agent's shell, or by an id
  that the hooks saw for the session. Only when no evidence of that session exists at all does it
  take the one session of the checkout with an owner prompt in the last 30 minutes, and it never
  chooses between two; a quiet session never borrows another session's words. So a claim in a
  resumed session, where the transcript can move, confirms as in a new one.
- The before-shell hook refuses an agent shell command that runs a cairnkit hook by hand, changes
  or removes an agent marker (`CLAUDECODE`, `CLAUDE_CODE_SESSION_ID`, `CODEX_THREAD_ID`, ...)
  and runs `memory`, calls cairnkit's evidence code from a script, or writes into the memory
  folder's `facts/` or `.sessions/`. Limits: a same-user process can still forge the evidence,
  the agent's Edit and Write tools are not guarded (the hook sees shell commands only), and a
  command built to hide its shape can pass the check.

- `memory export` prints the active facts of this project as `[YYYY-MM-DD] - text` lines, oldest
  first, under the headings Instructions, Decisions, Traps and lessons, Project state, Preferences
  and Other. It marks which rules the owner confirmed and which load as data, masks each secret as
  the load does, and ends with a line that says the set is complete or what it left out. `--all`
  adds ended facts with their status. `--output` refuses a path in any git work tree that does not
  ignore it and a path that is a link, writes mode 600, and replaces a file only with `--force`.
  No model and no network.
- `memory import --prompt` prints a short prompt for another assistant. It asks for this project
  only, in the export shape. `memory import FILE|-|--native` reads that answer, an export, Claude
  Code's notes of this project, or the rule-like list items of an `AGENTS.md` or `CLAUDE.md`. It
  shows the plan, and it writes only with `--yes`. It skips personal entries with a count, secrets,
  ended facts and text that the memory has. Each fact gets basis `seen`, author `import` and source
  `import:<name>:<date>`, so an imported rule loads as data until the owner states it with
  `--basis told`. A second import of the same text writes nothing. Only a list item or a dated
  line is an entry. Each other line, such as the assistant's own prose, a table row or a code
  line, is listed in the plan as not read, and the import never writes it. A heading is a `#`
  line, a bold line or a line that ends with a colon, never a list item, and headings match on
  whole words. A line in a code block that names a language, such as `bash`, is code: it is
  listed and not read. Fences follow CommonMark: a fence closes only on the same mark of at
  least the same length, so a `````` ````markdown `````` block can hold a `bash` block, and a
  fence indented 4 spaces is text. Nothing from a block that never closes is written. A fence in
  a code block is code: it cannot close an outer text block and so end the code block too. A bold or colon heading with no entry under it is listed too. The
  entries under a heading that the import does not know are skipped. A paste over 1 MB is
  refused, not cut.
- The memory keeps why each Claude Code helper started, from the moment that it starts. Before, a
  Ctrl+C while a helper worked left nothing of its aim, because no stop runs in a killed process.
  Now `PreToolUse` on the `Agent` tool records the description and the start of the prompt, masked,
  and `SubagentStart` adds the helper's worktree. The next session start (new or resumed) names each
  helper with no recorded end under `## Live work`, with what its worktree holds, also "no
  uncommitted change and no commit". An event ends a record, never a clock. These hooks print
  nothing, so they never allow or deny a call. The tool writes no fact. Only Claude Code gets them.
- The capture check at a stop also reads the worktree of each Claude Code subagent of this session
  that ran with `isolation: "worktree"`. Before, its changes and its commits in
  `.claude/worktrees/agent-*` did not block, and in a first real use 5 subagents left no fact. Work
  of another session's subagent never blocks this session. A removed worktree is no change. The eval
  scenario `pickup-helper-worktree` tests it, and runs only when `--scenario` names it.

- Before a shell command runs, a stored fact that gives a longer form of the same command stops
  that call once, with the fact as the reason. An example is `REPORT_LOCALE=C sh report.sh` for
  `sh report.sh`. Each fact stops one call in a session, and the next call runs. Claude Code and
  Codex get a `PreToolUse` deny, Pi a `tool_call` block and OpenCode an error from
  `tool.execute.before`. Cursor and Grok Build get no such hook. A fact in the load did not stop
  the short form in 6 of 6 real runs, and a context line arrives only after the command ran.
- A session start names, once, each line of `AGENTS.md`, `CLAUDE.md` or `CLAUDE.local.md` that
  teaches an older memory, and says which one wins. It edits no tracked file.
- `memory status` says how many notes Claude Code's own memory holds for this project, and where.
  It only reads that store.
- `memory load` names other live work: a checkout with uncommitted changes that this session did
  not make, with its files and the note of its branch, and a checkout where a session is in a turn.
  With nothing live, it adds no word. In `pickup-dirty-worktree` on Haiku, with no fact from session
  A, session B left the running edits in 3 of 3 runs. The no-memory arm gave 0 of 3.
- A stop blocks once to ask for a fact when the work changed, or when the owner stated a decision,
  an approval, a promise, a limit, a preference, a reason or a review, and no fact followed. An
  answer of "nothing" lets the agent finish. Plain work does not block again until a fact and 6 more
  prompts. On a labelled set of 182 ordinary prompts and 60 statements, 2 false fires and 1 miss.
- The block, the rules block and `memory instructions` hold one guide: the test, the moments, what
  a good fact is and the `memory add "TEXT"` line.
- The OpenCode plugin reads the prompt with `chat.message`, so it hears corrections and statements.
- A subagent gets no capture check. An OpenCode child session counts as a subagent.
- Stop names one failed command that then passes with a setting or a wrapper in front of it, such
  as `REPORT_LOCALE=C sh report.sh`. No other signal saw this lesson.
- Stop names a correction from the owner, or a file that was here at the session start and is gone,
  once, and asks if a trap belongs in memory. The tool writes no fact. On a labelled set of 40
  ordinary prompts and 30 corrections, 0 false nudges and 1 miss.
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
- `evals/agents`: a value measure. A no-memory arm, extra arms from a ref, two-session scenarios with
  nothing planted, a cost table per arm and a reading rule that is agreed before the run.
- `evals/agents`: a test runs each value scenario with the real tool and a scripted session, so a
  scenario that cannot pass in a build that captures fails a test.
- The branch-note gate, a test arm that is off by default. With the local git setting
  `cairnkit.branchnotegate = true`, in an agent's shell only, the first commit of a branch refuses
  until the branch has a short note, and a push refuses until that note changed. The refusal prints
  the `memory add ... --short` command. It checks only that a note exists and changed.
- `evals/agents`: `--arm-git LABEL:KEY=VALUE` sets a local git setting in one arm, so that two arms
  on one commit can differ by a switch. The hook words of the cost table now count what a hook says
  on stderr.
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

- The `told: not confirmed` note of `memory add` is two short sentences after the status. It keeps
  the commands: `--basis seen --link related:ID` (now with the new ID) for your own context, and
  `memory add "TEXT" --basis told` for the owner, or `--supersedes ID` for the words of an
  approved proposal.
- `memory change --held-by` refuses a path outside the repo, a folder, and a pipe, a device or
  another file that is not a regular file. The check uses the real path, so a link to a file
  outside the repo, a path through a folder link that leads outside, a path in `.git` and a path
  in the memory folder or its `memory-bank` link are refused too. It stores the path as a repo
  path, also when it was given as an absolute path in the repo. The word check of the note reads
  only regular files, so a pipe beside the file cannot stop the command.
- A rule that reads as the owner's yes to one piece of work (the test of the `memory add` note),
  and that no check enforces, loads under `## Rules that may be for one piece of work` below the
  lasting rules. The heading says that these rules bind and to end one when its work is done.
  They count toward the limit of 1000 words of rules, and the load holds them back first, so a
  pile of approvals cannot push out a lasting rule. The note that the rules pass the word budget
  counts only the lasting rules ("9 rules hold 372 words, outside the word budget of 299" came
  from approvals), and `memory check` gives the words of these rules on a line of their own. The
  rule stays a rule, because the test can read a lasting policy as an approval ("Merge only
  after the owner approves the PR."), and a rule must never drop out of the load.
- The "facts that match the files you changed" hint leaves out a fact, decision or event whose
  work landed (a trap, lesson or preference still shows), and shows at most 2 facts. It names the
  rest by id.
- A hook load cut to fit the hook's size limit drops stored lines in a fixed order: long-term
  facts first, then branch notes, the status note, short-term facts, pinned facts and agent rules,
  and `## Live work` last, at a startup, a resume or a compaction. Before, the cut dropped from the
  end of the frame, so the status note went before the long-term facts. When the cut drops all of
  `## Live work`, it also drops the order above the frame that points to that list.
- `memory docs` in a project that is not cairnkit writes one system page and one page for each
  component: a top-level package or folder of a source root. Before, it wrote one import graph of
  the top-level Python packages only. In a real Django and TypeScript project, it showed only the
  22 scripts in `tools/`, and it did not show `backend/` or the frontend. Now it finds Python
  source roots in subfolders (`backend/` with `manage.py`, `src/`) and resolves imports from
  them. It reads TypeScript and JavaScript imports, with `tsconfig` `paths` and `baseUrl`. It
  lists entry points (`manage.py`, console scripts, `__main__` blocks, `package.json`, and the
  scripts that `index.html` loads) and HTTP routes (Django `urlpatterns` through `include()`, and
  FastAPI, Flask and Django Ninja decorators under their mount). It reads only files that git
  does not ignore, and it skips tests, migrations, build output and generated files. On that
  project it writes 11 pages in about 0.2 seconds. The pages `architecture.md` and `modules/`
  of an older atlas have no source now, so `memory docs --force` removes them. The atlas of
  cairnkit itself keeps its pages. Only its module list names the new modules.
- The capture guide at a blocked stop is 87 words, down from 157, and it says that a commit, a
  branch or the diff is no fact. `--supersedes ID` stays in the rules of each session start. When
  the owner stated something and the work changed, the block gives one line for both. A stop that
  only names an event gives the `memory add` line and no guide. A command that passes with a
  setting in front of it is no event when an active fact names that setting and the command. In a real run on Haiku, the guide was 43 percent of all hook
  words, and session B of `lesson-carry` was blocked for a fix that it had loaded. In two new runs,
  hook words per session fell from 234 to 181 and 184 (0.3.1: 183), and blocks from 22 to 19 and 21
  (0.3.1: 9). See `docs/value-results.md`.
- A stale docs atlas prints only in `memory status`. A load and `memory check` no longer print it
  or count it as a thing to do, because nobody acted on it at each merge. `memory docs --check`
  still fails, for a project whose CI owns the atlas.
- A stop blocks only for a new event, and each event once per session: a health problem, a command
  that failed at least twice and then passed, a revert, a correction, or a lost file that no prompt
  named or asked to remove. In 20 ordinary turns, an agent that never writes sees 0 blocks on a plain
  script, where it saw 15, and 2 on a mixed one, where it saw 17.
- Plain work gets one short reminder per session, at the next prompt or tool result, with no block.
  News waits for the same hooks. The generic adapter has only stop, so it hears both there.
- A command that failed and has not passed is no longer named at stop. The loop nudge covers a
  stuck command.
- The similar-pair task lists at most 20 pairs, the likeliest repeats first. A pair with one swapped
  word or a change in numbers alone is no task. `memory load` and `memory tidy` state only that
  listed count, and the load line says nothing for a count past the limit.
- A rule that an agent saves with no `--basis` is still written. The first line of the add output
  says that it loads as data, and that the same command with `--basis told` lifts it, if the owner
  stated it. The heading of that load section says the same, and `memory instructions` shows
  the owner's rule with `--basis told`.
- A stored value that looks secret is masked, not withheld. The fact loads in its normal section
  with `[secret: NAME]` in place of the value, and an owner's rule keeps its force. Show, search,
  change, keep and supersede work on it. The load tells the agent to write a clean replacement and
  then to purge. A plain word from a `.env` file can stay masked, and a stop names each fact once.
- A clean fact that supersedes a masked fact keeps its kind, its pin and the force of an owner's rule.
- `memory purge` refuses a masked fact with true text, unless a live fact supersedes it or the call
  gives both `--reason secret` and `--yes`.
- A note line that holds a secret loads masked, not as a line number.
- A memory has one owner, in a third line of `.identity`. The repo record has a third line too.
  `--path` to a memory that another project uses is honored, and `memory init`, `memory check`
  and each load say so in one line. `git config cairnkit.sharedmemory true` states it on purpose.
- Self-repair adopts a folder with the recorded id only when it is the only one and its name is
  the recorded name or the project's name. Otherwise the load names each one with its command.
  A memory folder renamed to another name now needs `memory init --path FOLDER`.
- `memory migrate --untrack` changes the index, and writes agent files, only in the checkout
  where it ran. It prints what to run in the others.
- `memory hooks uninstall` also removes the rules blocks, the tool folders it leaves empty and
  the exclude lines of the files it removed.
- `memory status`, `memory check` and `memory load` read one health function and print one answer
  line. `memory check: ok` now means that nothing is open, and open work outside the facts prints
  as `to do`. `Repo files: current.` and `memory check: skipped` are gone.
- Stop blocks on all that `memory check --strict` fails, also a false `enforced_by`.
- Cursor uses `postToolUse` in place of `afterShellExecution`, whose output its docs do not read,
  and `beforeSubmitPrompt`. After a compaction it gets the load itself at its next tool result.
  A pass after failures now counts on Cursor. `memory init --refresh` writes the new hooks.
- The session start spends fewer words on tool text: the footer and the rules no longer overlap.
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

- A told claim whose words are only a reply that says nothing (`memory add "yes" --basis told`,
  also `Owner said: go ahead`, `ok`, `sure`, `lgtm`, `ship it`, `proceed`, `correct`, `thanks` or
  `I'll go with your rec`) is no longer confirmed, because it tells a later reader nothing. The
  add output says to save the words of the proposal that the owner approved, with `--supersedes`
  and the new id; those words confirm when they are the question that the yes answered in this
  turn. A short rule such as "Use uv." still confirms, and so does a claim with a digit, a mark
  or a word of another script (`Approved: #42.`). A prompt of a few approvals in a row
  (`yes, go ahead`, `let's do it`) now counts as a short yes.
- An owner prompt with a digit or a word of another script (`yes 2`, `yes` and a Chinese
  sentence) is no short yes, so it no longer approves the closing question of the agent. Before,
  the test read only the a-z words.
- The stop asks "What fixed it?" only for a real retry. The failed command and the pass must do
  the same work steps in the same order, and the pass puts a setting or a wrapper in front of one.
  A `cd`, `pushd`, `popd`, `echo` or `printf` step is no work, and nor is a filter after a pipe
  (`tail`, `head`, `grep`, `wc`, `tee`, `sort`, `uniq`, `less` or `cat`), so
  `pytest -q 2>&1 | tail -5` and `uv run pytest -q 2>&1 | tail -20` pair. Before, one shared
  step was enough, so `cd ...; cat spec; sed ...` that failed paired with a later
  `S=... gh ...; S=... sed ...` that did other work.
- A Claude Code helper whose own transcript had no write for 30 minutes ended, also when no
  `SubagentStop` came. TaskStop does not always fire `SubagentStop`, so a stopped helper and one
  that ended a day ago stayed on the `## Live work` list as "no end recorded", with the order to
  leave their work. Now such a helper stays on the list only while its own checkout holds
  uncommitted changes or commits since it started, as after 24 hours, and its line says "it
  ended, because its transcript had no write for 30 minutes". The `SubagentStart` hook keeps the
  path of the helper's transcript: `<parent transcript without .jsonl>/subagents/agent-<agent_id>.jsonl`,
  from the parent's `transcript_path`, or the payload's `agent_transcript_path` when that is in
  the folder of the parent's transcript. The load reads only the file time, never the file. A
  helper with no such file (another agent, or a transcript not written yet) keeps the 24-hour
  rule. A helper record with a field that this build does not know is still read.
- Commits of a helper that `main`, `master`, `dev` or `develop` (local or on `origin`) holds are
  no live work. So a helper older than 24 hours whose commits merged leaves the list. Before, each
  commit since the helper started kept it there. The helper's own branch never counts as merged,
  so a helper that works on `dev` keeps its commits. A start commit that is gone counts no commit.
  A squash merge or a rebase makes new commits, so their old commits still count. A default branch
  with another name is not checked, so its merged commits still count.
- The status note and the branch note in the load stop at 200 words, with a last line such as
  `(200 of 1180 words shown. The rest is in /path/to/memory/notes/status.md.)`. Before, only the
  first 8 lines counted, and long lines used no budget: in a real project the status used 740 of
  2,112 words, and the hook cut 106 facts to fit its size limit. `memory export` still writes the
  first 8 lines.
- A session start whose cut fit the load to the character printed one character past the hook's
  size limit, because the limit did not count the last line end. Now it does.
- A stop event that the stop asked about is not asked again in the session. What was asked is in
  `.sessions/asked-*.json`, under a lock. Before, it was only in the session state, and a helper's
  hook that saved that state from a read before the stop brought the question back on later turns.
- A Claude Code helper with no recorded end leaves the `## Live work` list 24 hours after its
  call, when its own checkout is gone or holds nothing. Before, a helper whose worktree stayed
  was named for days. A helper whose checkout still holds commits since it started or
  uncommitted changes stays on the list, because that is live work that a tidy-up must leave.
- A helper line with no recorded end now says that the helper may have been stopped: "no end
  recorded, so it may have been stopped or ended unseen", and in a compaction of the session that
  started it, "started by this session; it may still be running, or it was stopped or ended
  unseen". Claude Code 2.1.319 fires `SubagentStop` for a helper that TaskStop stops only when the
  stop cuts the helper's stream; when the stream ends first, no hook runs. The record still ends
  at the stop of a session whose load named it.
- `memory change ID --status superseded --superseded-by NEW` from an agent refuses when a person
  stated ID (a confirmed told fact or the owner's rule) and NEW has less authority (not stated, or
  a told claim that the owner's words did not confirm), as `memory add --supersedes` already kept
  such a fact. Nothing changes. The refusal, and the "not superseded" note of `memory add`, say how
  to confirm: quote the owner's words in this turn, or the owner runs the command from their own
  shell. The owner at a terminal can still supersede any fact.
- A stored path with a name of 256 or more characters (a `file:` source, a `test:` check, a
  `held_by` file, a helper checkout) no longer loses the whole load on Python 3.12, where
  `Path.exists` raises ENAMETOOLONG. Each such probe on the load path now reads as "not there".
- When two dev builds share a version number, the refresh line at session start names the build
  that wrote the repo files and the build that runs now, for example "come from memory 0.3.1
  @6b4bdf0; this is 0.3.1 @81f8499". Before, it said "come from memory 0.3.1. This is memory
  0.3.1", which read as no change. `tool-version.json` now also records the commit of the build.
- The end-of-turn capture check names the memory notes (`notes/` and `branches/`) that changed
  since the last check, at most 5 and as data, and asks whether one holds a decision or a trap that
  needs a fact. Before, it said only "no fact records it", so an agent that had edited
  `notes/status.md` and its specs read that as if the check did not see them. A note edit alone
  still does not block.
- After a compaction, the session start names the helpers that this session started under
  `## Live work`, as "started by this session; it may still be running, or it was stopped or ended unseen". Before, a compaction hid
  them, so a lead lost the work that its running helpers did. The next stop of the session does
  not end their records. A resume still names them as having no recorded end.
- Each start of the tool now uses `python -P`: the agent hooks, the Pi and OpenCode plugins, the
  git hooks (also the `import cairnkit` test of pre-commit) and the background update check.
  Before, Python put the folder of the hook first on the import path. A `cairnkit/` folder or a
  `json.py` that a pull, a merge or an agent put in the repo then ran in place of the tool. A
  repo with hooks from before this change gets the line `Run memory init --refresh now`, and the
  refresh rewrites them.
- A repo can no longer choose the memory. A `.memory-path` or a `memory-bank` link that git
  tracks does not count, and the load and `memory check` say so. A memory folder in which the
  project repo, or a repo above the project, tracks a file does not load in any hook or load,
  and `memory check` fails with the command that takes it out of the index. A memory folder in
  any other repo is the owner's private history: a git repo of its own, or one repo that backs
  up the memories of several projects. It loads, and `memory init` and `memory check` do not
  add it to the exclude file of that repo. Before, a pulled `.memory-path` could load a folder
  from the repo, and its rules with no author printed above the frame as rules of the owner. Outside
  git, a link or a `.memory-path` of another user does not count. On Windows, which has no user
  ids, that test is skipped, so the load works there. `memory init --path` does not write a
  `.memory-path` that git tracks. The test reads the index file of the checkout that holds the
  pointer, only for the pointer that the search uses, and runs git only when that file cannot
  say, so the hooks run no more git than before. A repo above the checkout, such as a home
  folder that is a git repo, does not count for a pointer. When git gives no answer, such as
  when the time of a hook runs out, the pointer still counts, because the owner wrote it: the
  load and `memory check` print no false "git tracks" line, and no hook makes a new empty memory
  and a new record that set the owner's memory aside.
- The load runs git about a helper only in a checkout that `git worktree list` names. Before, a
  helper record could name any folder, and the load ran `git status` there. Git then ran a
  command that the git config of that folder names, such as `core.fsmonitor`. The start of a
  helper records its worktree only when it is a checkout of this project.
- `memory update` runs `uv build` and `uv tool install` in the cache folder of the tool, with
  `--no-config` and your own `uv.toml` as `--config-file`. Before, uv read `uv.toml`,
  `[tool.uv]` and a `.venv` from the folder of the caller. An update from a repo then built the
  tool with the package index of that repo, and `uv build` ran its `.venv/bin/python`.
- A hook or a command changes nothing outside the memory folder through a link in it. A repo
  can bring such a link along. Before, session start removed old files where a `.sessions` or
  `.sessions/live` link went and wrote its state there, a shell result rewrote the file that a
  `.loop-breaker.json` link named, a lock file was made where a dangling link went, and
  `memory migrate --yes` removed files under a linked folder and made files where a dangling
  note link went. Now each write, removal, prune and walk in the memory folder takes its path
  from one check that refuses a link from the memory folder down to the file. The refusal says
  what to do, such as for a `facts/` link to another disk: move the whole memory folder and
  point `memory init --path` or `MEMORY_DIR` at it, or put the folder in place of the link. A
  test makes each file that a command or hook writes there, and each folder above it, a link in
  turn, and finds that nothing outside changes.
- A hook install writes no file through a link. `git ls-files -- .codex/hooks.json` prints
  nothing when `.codex` is a link that git tracks, so a repo with such a link made the install
  rewrite a tracked file or write a hook file outside the checkout, and an uninstall removed a
  file there. Now each adapter file with a link in its path is skipped with one line that says
  how to connect it, and an uninstall removes nothing behind a link. The check that asks for
  `memory init --refresh` skips the same files, so it does not ask for a refresh that cannot
  write them, again at each session. `memory init` lists under "Agents connected" only the
  agents that it connected, not one whose file it skipped. `memory instructions --write-instructions` writes no
  rules file through a link that git tracks, such as a committed `.cursor` link: before, the
  Cursor copy went where that link led. A link that the owner made stays usable.
- The folder for copies of the index, `cairnkit-index-<uid>` in the temp folder, is used only
  when it is a real folder that this user owns and that others cannot open. Another user could
  make that name first in a shared temp folder, as a link or open to all, and change the index
  that the pre-commit check reads, or make the clean remove files where the link goes. Now the
  diff uses the real index then, and the clean never follows a link.
- A value in the form of a mask, such as `[secret: AKIAIOSFODNN7EXAMPLE]`, is a secret again. The
  scan read each `[secret: X]` as a mask, so `memory add`, `memory check` and each read let such a
  value through in a tag, a source or a reason. Now only a shape name, `hidden text`, `env value`
  or the name of a `.env` variable makes a mask. `memory add`, `change`, `keep` and `purge` also
  refuse a mask in each free text that they store, not only in the text, summary and area.
- `memory add` scans `--enforced-by` and the `--until-merged` branch for secrets before the
  write, and `memory change` scans `--enforced-by` and `--held-by`. Before, a token in these fields
  went into the fact file, and a note or an error printed it.
- `memory check` shows the note about a note line with one plain word behind a secret label once
  for each line, and again only for a new line. In a real project `{"family_key": "birch"}` came
  back on each check for days. The scan itself is as strict as before.
- A secret token with a mark inside it that shows as nothing or that the load removes is found
  and masked whole. The scan reads the text without each control or format character, each
  mark that joins the letter before it, each separator and private character, and each blank
  letter such as a Hangul filler. A mask removes such marks only from the word that hides the
  secret, so the other words of the line keep their accents and joiners. Before, `memory add` stored it, and the
  load, which removes bidi marks, showed it whole.
- `memory add` says when a plain fact opens like an order ("Never", "Always", "Do not", "Must"):
  a fact can be held back from the session start, and a rule loads each time. It prints the
  command that makes it a rule. In a real project a safety lesson about a leaked key went in as a
  fact and did not load.
- Stored text no longer carries bidi control marks (U+202A to U+202E, U+2066 to U+2069) into a
  load or an export. They can make a line show in another order than an agent reads it.
- Fixes from an independent review of the load and the hooks. A load that is too big for the hook
  limit keeps its one-time notices (the update line, a rule that changed), runs at most 4 passes
  or stops near the end of the hook's time, and its cut keeps the rules and the frame and now also
  fits when the lines after the frame are long. "What fixed it?" pairs a chain only on a step that
  is more than one plain word, so `pytest -x && ls` and `FOO=1 ls` are no pair. An owner prompt
  that says "run memory check" still counts as the owner's. Temp files of a killed hook go after
  an hour, and the index copy can no longer raise or be left half written.
- One odd file no longer stops `memory docs`, `memory docs --check` or the atlas line of
  `memory status`. A sum of 5000 terms in `urlpatterns` raised RecursionError, and so did a
  `package.json`, `tsconfig.json` or `pyproject.toml` that nests 100000 deep. A line of 400000
  minus signs ran the Python parser out of memory. Now a file that cannot be read or parsed counts
  as empty, and the other files still map. The toolchain scan of the presets also reads such a
  manifest as empty, and `memory hooks install` reports such an agent settings file as not valid
  JSON. Before, it stopped with RecursionError.
- `memory docs` reads a script or an `index.html` in a time that grows with its size, not with the
  square of its size. A `web/index.js` of 50000 `import a ` words ran for more than 30 s of CPU,
  and so did a run of blank lines or of open `<script` tags. That stopped `memory docs`,
  `memory docs --check` and `memory status`. The scan still finds an import after a string on
  the same line, such as `"use strict"; import b from "./y"`.
- `memory docs` reads no file outside the repo. A tracked link to a file outside put that file's
  first line in `docs/state`. Now it skips each link, also a link to a manifest such as
  `pyproject.toml`. It also refuses a `docs/state` that is a link, and it writes or removes no page
  that is a link or is under one. Before, `--force` could write or delete outside the repo. Each
  read opens the file one folder at a time and refuses a link at each step, so a file that turns
  into a link after a check is not read either.
- A pipe or another file that is not a regular file in `docs/state` no longer hangs
  `memory docs`, `memory docs --check` or `memory status`. Before, `mkfifo docs/state/x.md` made
  each of them wait for ever. The same holds for each other file of the project or of the memory
  folder that a command reads: a pipe at `.cursor/hooks.json`, `.codex/hooks.json`,
  `.claude/settings.local.json`, `CLAUDE.md`, `AGENTS.md`, `CLAUDE.local.md` or `.memory-path`,
  or at a fact file, a note or `config.toml` in the memory folder, made `memory status`,
  `memory check`, `memory load` or `memory hooks install` wait for ever. Now each read opens the
  file without a wait and reads only a regular file. Such a file counts as one that cannot be
  read, and `memory hooks install` reports an agent settings file that is not a plain file and
  changes nothing in it. A regular file of any size is read in full, so a fact file over 64 MB
  still loads and `memory purge` still rewrites it. The same holds for each file that the tool
  writes: a pipe at `.auto-tidy-state.json`, `.auto-tidy.lock`, `.agents-seen.json`,
  `tool-version.json`, `facts/main.jsonl` or `facts/.write.lock` made the session start hook,
  `memory add`, `memory init --refresh` or `memory hooks install` wait for ever. Now each write,
  append and lock opens the file without a wait and writes only a regular file. A pipe or a
  device there counts as a file that cannot be written, and `memory export --output` refuses it.
- `memory docs` lists the same files on each machine. It uses the files that git tracks and the new
  files that git does not ignore, so a file that you did not add yet is in the map. When git cannot
  list a repo, it stops with an error and changes nothing. Before, it walked the folder and read
  ignored files. A folder with no git is walked to at most 50000 files, and a file bigger than 1 MB
  counts as empty. A global ignore of one machine can still change the list, so the help of
  `memory docs --check` and the README say to run the check in CI on a clean checkout.
- A file that starts with a UTF-8 byte order mark keeps its summary and its imports in the atlas.
- The parent id of the atlas comes only from the front matter of a hand-written
  `docs/state/README.md`. Before, an `id:` line in the body could set it.
- `memory migrate` names a repo hook that reads the old notes in more forms: a glob
  (`memory-bank/*.md`), a list of the folder (`ls memory-bank`, `ls memory-bank/`,
  `os.listdir("memory-bank")`, `.iterdir()`), a `$VAR`, a brace set,
  `Path("memory-bank") / "status.md"`, `.joinpath("status.md")`, `.glob("*.md")`,
  `notes/../status.md` and `["memory-bank", "a/b.md"]`. A path under `notes/`, `facts/`,
  `branches/`, `proposals/`, `config.toml` or `README.md` is still the new layout.
- `memory migrate` no longer names a hook for a path that is not a read of the old layout. These
  were false alarms: the files that the tool writes itself (`auto-tidy.log`, `tool-version.json`,
  `.sessions/`, `.usage/`, `.identity` and the other dot files), each choice of a brace set that
  is in the new layout (`memory-bank/{notes,facts}/x`), `./` and `//` in a path, a test of the
  folder or a step into it (`test -d memory-bank || exit 0`, `ls -d memory-bank`,
  `cd memory-bank`, `git -C memory-bank log`, `.exists()`), a recursive read (`.rglob`), and
  text that reads nothing: a comment, a docstring, a URL, or what `echo` and `printf` print. The
  folder exists in both layouts, so a test of it shows nothing.
- The task item for such a hook names the path that it reads and asks the agent to compare the hook
  with `memory load`, `memory check` and the memory hooks. It says to remove the hook only when
  they do all that it does. Before, a mention of a path was enough to say "Remove this hook
  handler". A hook that runs the old checker now gets the same item. It counts only when it runs
  a repo script named `check_memory.py` (or `check-memory.sh` and the like) that names
  `memory-bank` and reads no path of the new layout, also as `$CLAUDE_PROJECT_DIR/tools/...`
  with or without quotes or braces. A script after `$CURSOR_PROJECT_DIR/`,
  `$GROK_WORKSPACE_ROOT/`, `$PWD/` or the absolute project path is a repo script too. A script
  after any other variable, such as `$HOME/.claude/h.sh`, after `~/` or at another absolute path
  is not in the repo, so it is never read as the repo's `.claude/h.sh`. Before, each `$VAR/` was
  dropped. Before, `check_memory` anywhere in the command counted, so
  `scripts/check_memory_usage.sh`, `check-memory-leaks` and a checker that was already updated
  got "Remove this hook handler". A doc line or a script name counts as the old checker only
  for the whole name `check_memory` or `check-memory` too. The task section "The old checker"
  asks for the same comparison before the script goes. Before, it said to remove the script
  once nothing named it.
- `memory migrate` reads a long hook script, hook command or doc line in a time that grows with
  its size. Before, the time grew with the square of the size for a long word of
  `memory-bank/notes/` parts, a run of spaces after `"memory-bank"`, a long doc line that names
  the checker, and a long hook command.
- `memory change --unlink` alone writes a change that the 0.3.1 build also accepts. That build
  knew no `remove_links`, so its check reported the record as bad. Now the change also holds an
  empty `add_links`. The older build keeps the link, and this build removes it.
- The load line that names files outside `notes/` cleans each file name and cuts it at 40
  characters. A file name with a line break could put a line of its own in the load.
  `memory migrate` now cleans each file name that it prints too: a stray file in the memory
  folder, a note, a kept copy, a pointer, a moved folder, a doc that names the old checker, each
  file of the candidate count, a worktree and each checkout path. Before, a name with a line
  break, a terminal code or the end line of the stored notes printed as it was. `memory init`,
  `memory check`, `memory status`, `memory load`, `memory hooks install`,
  `memory instructions` and `memory docs` now clean each path that they print too, so a
  checkout or memory folder with a terminal code in its name cannot forge a line. So do the
  report line of `memory tidy`, the log line of `memory tidy --auto`, the Cursor and Pi lines of
  `memory instructions --write-instructions local`, `memory preset show --detect`, the lines of
  `memory export --output`, the target of `memory skills install`, the note that git tracks or
  does not ignore the memory folder, and each error that a command ends with. The clean of a
  path removes only line breaks, control characters, terminal codes and bidi marks, and keeps
  each other character: a memory folder `mem  two` (two spaces) prints as it is, not as
  `mem two`. A path in a command to copy, such as `memory init --path PATH`, is in shell quotes
  when the shell would split it.

- A helper line in the load says "no end recorded, so it may have been stopped or ended unseen". In a real project
  a review that ended two days before read as still running, because its end never reached the
  hooks.

- `memory migrate` no longer asks to remove a repo's own hook whose script reads
  `memory-bank/notes/`. It counted any mention of `memory-bank` as the old layout, but the new
  layout lives under that link too. In a real project it asked to remove two working hooks that
  also checked the push hook, secrets in notes and open worktrees. Now a hook counts only when its
  command or script names a path that the move changed, also when code builds the path from parts.

- The rules block of each session start says to add `--basis told` when the owner said it. In a
  busy-memory eval, Sonnet wrote the owner's open question before any stop asked, with no basis,
  so it ranked as a guess and the next load held it back.

- The prompt hook ends its own work after 2.5 seconds, and a cut leaves no temp file. Claude Code
  drops a prompt hook after 5 seconds, and on a busy machine one ran past that.

- The state of a session stays small in a session that runs for days. It keeps the newest 20
  failed commands, so an old failure cannot pair with a pass days later, and the newest 200 file
  names from the owner's prompts. A helper's report or a notification names no file, and `**`
  marks are no part of a name. In a real project one session held 41 failures (24 KB) and 200
  names, many of them bold words from helper reports.

- The session state calls the worktrees of this session's helpers `helper_checkouts`, not
  `helpers`. An agent read that map as the record of why each helper started. That record is
  `.sessions/helpers/open.json`.

- A session start shows the newest facts that the owner stated. In a real project it showed 16 of
  51 facts and held back all that the owner said in two days, his two open questions among them.
  A new statement has no lookups yet, so it ranked below older facts that searches keep warm, and
  one place for each of 14 areas went to old facts first. Now the five newest facts with basis
  `told` come right after the pinned facts. This orders what fits. It ends nothing. On a copy of
  that memory, all four statements of the last day now load, and 23 facts in all.

- A load that is too big for the hook limit now shrinks its word budget only as far as it needs
  (at least a tenth each time), not by half.

- A load names the files outside `notes/` in one short line. `memory check` still explains each
  file. In a real project two such notes took 849 characters of each session start.

- In a project with a hand-written `docs/state/README.md`, the pages of `memory docs` name that
  page as their parent. Before, they named a page that did not exist.

- A hook no longer writes `.git/index`. A `git diff` against the worktree refreshes the index and
  holds `.git/index.lock` while it does, whatever `GIT_OPTIONAL_LOCKS` says. A hook kills a git
  that runs past its time, and the lock it leaves stops the next `git commit` ("index.lock: File
  exists"). This happened once in a test run on a loaded machine. Now each `git diff` of a hook
  works on a copy of the index, and every other git read runs with `GIT_OPTIONAL_LOCKS=0`.

- The text of a session start and a subagent start stays under 9,000 characters. Claude Code saves
  hook text over 10,000 characters to a file, and the model sees only the first 2,000. In a real
  project the session start grew to 10,170 characters, and the agent saw the preview only. A load
  that is too big loads again with a smaller word budget. Rules, pinned facts and the status note
  do not count against that budget, so when they are too big alone, the end of the stored notes is
  cut, the frame stays whole, and a line says to run `memory load`.

- `memory add` prints `added ID` first, before any note that names an older fact. Before, the
  last line or the first ID could be an older fact, and in a real project an agent linked a lesson
  to the wrong fact.

- `memory change ID --unlink REL:ID` removes a link, for example one added by mistake. A change
  record holds it as `remove_links`.

- A new Claude Code hook line (`before-shell`, `helper-call`, `subagent-stop`) ends in `|| true`.
  An older build does not know these events and exits 2, and an exit 2 of a `PreToolUse` hook
  blocks the tool call. So a roll back of the tool would have blocked every shell command until the
  next `memory init --refresh`.

- A stop no longer asks "What fixed it?" for two commands that only share a tail. In a real
  project, a subagent's `... && echo ok` failed, and later an unrelated note that ended in
  `echo ok` passed, so the stop named them as a failure and its fix. Now a pass counts as the fix
  only when one of its steps is the same command as a failed step, with a setting or a wrapper in
  front. A heredoc body is no step.

- `memory check` knows a `held_by` file that only another checkout holds, also when no commit
  has it yet.
- `memory migrate` with no `--yes` shows the plan of tracked notes, and it says to add `--untrack`.
  The refusal with `--yes` names each folder once.
- A short-term note or rule now ends after a squash when the base changed those lines later, when
  the remote copy of the branch stays, when only `origin` has the squash, and when the work landed
  in `dev` or `develop`. A branch deleted with work that did not land now reads as unknown and
  keeps its note. It does not read as ended.

- `evals/agents`: the cost table no longer counts the import check of the pre-commit hook as a memory
  command.
- `evals/agents`: `pickup-decision` can now be answered from local files. Its prompts say that GitHub
  is not reachable and name the queue file, which still lists #412. Before, each arm read
  `inconclusive`, because session B tried `gh` and never answered.
- The pre-commit hook prints a stored trap only when the trap or its source names a staged file. An area match warned about a migration on a commit that changed a colour.
- A request to remove one path no longer hides the loss of each file that shares its folder or extension. Only the file name of that path counts.
- A pull, a merge, a rebase or a branch switch no longer reads as lost files at stop. Stop asks
  about a tracked file only when this session deleted it, in the worktree or in a commit it made
  here. With the HEAD reflog off, only a worktree deletion counts.
- `memory init --refresh` says where the list of the facts that it ended is. It names
  `memory-bank/auto-tidy.log`, whose lines hold each undo, and `memory show ID`.
- The `memory check` note about a file outside `notes/` says what `memory migrate --yes` moves and
  what stays, and it names `memory migrate`, which only prints the plan. That plan now says that
  the file leaves its place, and it no longer says `Migration finished` before the work is done.
- `memory docs --force` no longer removes or overwrites a Markdown file that it did not write. Only
  a page with the exact front matter of `render_page` is an atlas page. A hand-written page in
  `docs/state` stays and does not make the atlas stale, so `memory status` stops asking for
  `--force`. An atlas page that no longer has a source is still removed.
- A placeholder in a URL with a quote or punctuation after it, such as `` `/?k=<code>`. ``, is no
  longer a catch, and `memory add` takes it. A real token in the same place is still caught and
  masked.
- A plain word under a secret label in a note, an old copy or a worklist is one `note:` line and
  does not fail `--strict`. A fact still refuses it. Prose such as `**A bad secret:** Dahl's name`
  is no assignment.
- `memory check` reports one problem per distinct line, at the note, and names its copies in the
  `.memory-old` folder and the worklist. A value in a worklist row is judged with no JSON around it.
- The advice for a note no longer says to remove a line. It says that this may be a false catch, and
  that a real value changes where it is used and then in the file. `memory migrate` says the same.
- A stop no longer blocks for a secret warning about a file that the session did not write. The
  next prompt or tool result names these lines once, and `memory check` and `memory status` keep
  them. A secret that the session wrote into a note is still named at stop.
- `docs/update.md` and the README give the tested way from stable back to dev, by a git URL or a
  local folder. An update to a version with no `--channel` says so and prints the way back.
- A rule-change notice in a load holds no stored text above the frame. It names the id and the
  `memory show` command.
- A roll back to 0.3.1 keeps working after a dev repair or a branch tip note. `memory repair` writes
  to `repairs.jsonl` beside the fact files, and it still reads an older `repair` record. A branch
  tip record now holds a field that 0.3.1 accepts.
- The rule word limit fills with rules that a person stands behind, and then with agent data rules.
  An owner rule is never held while a data rule prints. Inside a class the newest wins a tie, and
  the warning names up to 5 held rules by id.
- `memory add` refuses text, a summary or an area that holds a mask from a load, also a mask that a
  snippet cut, because it would replace the true word for good. The note on a plain `.env` word now
  says to leave the fact, and it offers no rewrite.
- A refused push prints a fix that can move only the pushed ref. It names the branch, runs in the
  worktree that holds the branch, and returns the checkout to where it was. It has a form for a
  tag, a detached HEAD and a commit pushed by hash. Before, the rebase acted on the current branch.
- A load never moves the owner of a memory. Only `memory init` by that repo takes one whose owner
  is gone. Copy then move no longer tells the real repo that it is the copy. Each repo hears the
  memory's name, and no printed fix gives it an empty memory.
- A folder beside a project is named only under a name that the project is known to have had, so
  a clone no longer hears of an unrelated orphan. A memory made beside a likely earlier one keeps
  the note in the load and `memory check` until it is settled. `cairnkit.notearlier` denies it.
- `memory migrate --untrack` from a worktree says that the move changes each checkout.
- The short fix needs no editor. It prints only when it is enough.
- The fix step moved out of `pre-push` to `.git/cairnkit-fix-commit`, so a remote named
  `cairnkit-fix-commit` no longer skips the push check and amends HEAD.
- A deleted `.git/cairnkit-guard-base` no longer reads new AI commits as older. Each commit that no
  remote holds is checked. `memory hooks install` over a running check does not write a new base.
  An install that starts the check still does, so a first push is no trap.

- 30 facts that differ by one number made a 245 KB task, and 2000 made 113 MB and took session start
  past its 10 s hook timeout. Now they make no task, and session start takes about 1.3 s. The scan
  has a limit of 30000 comparisons and 1 second, and each fact gets an equal share. A scan that runs
  out of time keeps the last whole answer.
- An agent's change to a rule that binds is never silent. `memory change`, `--supersedes` and
  `memory purge` under an agent print a line at once, and the next load names the rule once.
  The agent must tell the owner. It stays allowed.
- A rule that an agent writes with no `told` says at once that it loads as data, with the fix.
  Restating a data rule with `--basis told`, or by a person, now lifts it.
- Any agent marker means an agent. Two markers name both tools and no longer read as a person.
- `pre-push` refuses only commits made since the guard was installed on this clone. Old history,
  tags and shallow clones push, with one line that gives the count of older AI commits. A
  contributor's commit is not refused, and a trailer that another person committed is named.
- A refused push prints an amend, a rebase and an override config, and real runs prove each one.
  The old printed rebase failed on an empty commit, a trailer and a root.
- The attribution guard refuses current tools and models by shape: `Opus 4.7`, Kiro, Qoder, Cline
  and others in each form, a dotted version in a name, and a no-reply address at an `.ai` domain.
  A person with one of these names and a personal address passes.
- A session start removes the `post-commit` block of 0.3.1 from `.git/hooks` by itself. Foreign
  text in that file stays byte for byte.
- `memory instructions` and the migrate worklist say when a rule loads as data.
- `memory repair` prints no secret: only plain words and masks of a damaged line, and only the key of
  a dropped setting. A value does not stay in `config.toml` or in a copy, and a second repair keeps
  the first `config.toml.bad`.
- `memory repair` does not close the alarm on a secret. Each damaged line is scanned. `memory check`
  names it until `memory purge line-HASH` removes it. `memory show line-HASH` reads the rest.
- `memory purge` refuses text that is no record's id, and it scans the id and the reason, so a secret
  no longer lands in a tombstone.
- A `.env` value counts under any name when its own shape is no ordinary word, and the password of a
  URL counts. `INVITE_CODE=blue-tulip-42`, `HOST_CODE=abc123xyz789` and the password in `DATABASE_URL`
  are refused at add and masked at read.
- `memory repair` keeps auto-tidy off after a mistyped `auto_tidy` line.
- `memory check` names a secret in the `.memory-old` copy of a migration, says that git history keeps
  what was committed, and names a secret in Claude Code's own memory with no value and no edit.
- `memory init` no longer refuses for a neighbor folder, and it never offers an unrelated
  memory. A connected project with no memory gets one at session start. It still refuses when
  this project is known to have had a memory that is gone.
- A copied repo hears once that it uses the first repo's memory, and the next `memory init`
  gives it its own. A stale backup no longer wins after the memory is deleted.
- A rename no longer stops each commit and branch switch under `core.hooksPath`: the stored hook
  command holds no path, and session start replaces an old one. `memory check` says what is true.
- A global `core.hooksPath` no longer takes one repo's hooks and guard to every repo. The tool
  writes only in this repo's git folder, and uninstall in one repo leaves the others alone.
- One tool's bad hook file stops only that tool. The other tools and the git hooks still install.
- `memory init` and `memory hooks install` refuse in a bare repo or a `.git` folder, where they
  wrote tool folders and said that nothing in git changes.
- `.git/info/exclude` holds one header, and an old repeat of it collapses.
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
- A purge that raced an add lost facts that were reported added, with `memory check: ok`. Each write of a
  fact file now takes one lock, and purge reads the files inside it. The audit's race scripts: 9 facts lost
  in 12 runs before, 0 after.
- 8 parallel adds of one text gave 8 active copies. They now give one, because add reads the memory again
  inside the lock.
- A load cut by git now says in one line what it could not read and how many facts it held back. A timeout
  no longer reads as "not in git" or as branch `main`. The branch comes from the git folder. When that names
  none, a note goes to `branch-unread`, which each branch loads.
- `memory add`, `change`, `keep` and `purge` have a total budget. Under a hung git, `add` took 24 seconds and
  now takes about 3. The fact is written, and the checks that need git are skipped.
- A stored name prints at most 80 characters. `--area` with 5000 characters gave a 5004-character load line.
- A small `--budget` now says that rules are outside it. Rules past 1000 words are held back with a count and
  the command that prints them.
- Text that is not UTF-8, a read-only fact folder and a bad `.memory-path` give a clean error, not a Traceback.
  `memory check` names the bad file. A load exits 0 from a deleted folder too.
- A closed stdout pipe after a successful command exits 0. It exited 120, and a retry made a repeat.
- Auto-tidy and `memory add` end a fact with no agent only for the same text, byte for byte, apart
  from whitespace and a final `.`, `,`, `;` or `:`. `-1` and `1`, `Foo` and `foo`, `users` and
  `user`, `plan A` and `plan` now keep both facts, and the agent task lists the pair. On the labelled
  set: 0 false retires of 51 (16 before), 3 repeats caught of 29 (9 before).
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
