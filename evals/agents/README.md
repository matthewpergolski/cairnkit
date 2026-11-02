# Agent eval kit

This kit tests real agents with builds of cairnkit: `dev`, `prod` (0.3.1), any extra arm that you
name, and an arm with no memory. The replay tests in `docs/forgetting-tests.md` show what can
load. They do not show that an agent acts on it. This kit tests that.

The kit has two suites:

- `behaviour`, the default, asks if the tool acts correctly. Most of its scenarios start with
  planted facts.
- `value` asks if memory helps at all. No fact is planted, and a no-memory arm runs beside the
  memory arms. Read [The value measure](#the-value-measure) before you spend on it.

Each run uses a new throwaway repo and a new memory folder in the system temp folder. The kit
does not change your installed `memory` or a real memory folder.

## Run it

Run one command for each agent, from a checkout of `dev`:

```sh
uv run python evals/agents/run.py --agent claude
```

The agents are `claude`, `codex`, `cursor-agent`, `opencode`, `pi` and `grok`.

| Flag | What it does |
|---|---|
| `--dry-run` | Prints the plan and the cost shape. It spends nothing. |
| `--fake-provider` | Uses a local fake model. No account and no cost. See below. |
| `--load-only` | Shows what `memory load` holds for each scenario. No agent runs. |
| `--repeats N` | Runs per scenario, per build. The default is 3. |
| `--suite NAME` | `behaviour` (the default) or `value`. `--scenario` overrides it. |
| `--scenario ID` | One scenario, by id, letter (`b`) or first word (`pickup`). You can use it more than once. |
| `--agent-b NAME` | The tool for session B of a two-session scenario. The default is `--agent`. |
| `--model-b NAME` | The model for session B. The default is the model of session A, or the small model of `--agent-b`. |
| `--arm LABEL=REF` | One more memory arm from a git ref. You can use it more than once. |
| `--skip-arm LABEL` | Leave out one arm, for example `prod` or `none`. |
| `--model NAME` | The model. Each agent has one small model as the default. |
| `--budget-usd N` | Claude only: the limit for one session. The default is 0.25. |
| `--dev-ref REF`, `--prod-ref REF` | The first two arms. The defaults are `HEAD` and `d523c01`. |
| `--report DIR` | Makes the table again from a result folder. |

Start with these two commands. They are free:

```sh
uv run python evals/agents/run.py --agent claude --load-only
uv run python evals/agents/run.py --agent claude --fake-provider --repeats 1
```

If two arms are the same commit, the command stops, because a comparison has no meaning.

## Output

The results go to `evals/agents/results/<time>-<agent>/`. Git ignores this folder.

- One JSON file for each run. It holds the tool version, the requested model, the model that the
  tool reported, the result class, the reason, the evidence and the new facts.
- `report.md`: the arms side by side, with counts. Each row shows `n`, the number of runs, and the
  tools that ran session A and session B. For the two-session scenarios it also shows where session
  A left the text, the cost table and the reading rule.
- `raw/`: the output of the agent for each turn.

The kit reads agent output as data. It does not run that output. The table holds only counts, so
agent text cannot change it.

## Result classes

| Class | Meaning |
|---|---|
| `pass` | The agent was connected and the check passed. |
| `fail` | The agent was connected and the check failed. This is a result about cairnkit and the agent. |
| `not-connected` | No sign that the memory reached the run: no hook ran, no `memory` command ran, and no fact showed. A trust step that stopped the hooks also gives this class. |
| `error` | The run says nothing about cairnkit. `error_kind` tells why: `auth`, `quota`, `timeout`, `crash`, `empty-output`, `missing-binary` or `setup`. |
| `unsupported` | The tool has no headless path for this scenario. |
| `inconclusive` | The scenario did not happen. Example: the agent started no subagent. |

Only `pass` and `fail` count as results about cairnkit. After an `auth` or a `quota` error, the
kit makes no more calls for that agent. It writes the other runs as `error`, with 0 calls.

## Scenarios

The prompts do not name the memory. The test is a hands-off session.

| Id | What it tests | How the script checks it |
|---|---|---|
| `a-fact-at-start` | A question that a stored fact answers | The answer holds the value |
| `b-old-trap-quiet` | A trap of 150 days in a quiet area, no diff | The answer holds the value |
| `c-old-fact-busy` | A fact of 150 days in a busy area, no diff | The answer holds the value |
| `d-old-trap-edited` | The same kind of trap, with a branch that edits its area | The answer holds the value |
| `e-wrong-trap` | A wrong trap, and a test run that shows it is wrong | The fact is no longer `active` |
| `f-failed-then-fix` | A command fails 3 times, then a fix | A new fact names the fix |
| `g1-capture` | A correction from the user | A new fact holds the correction |
| `g2-selectivity` | Routine work | No new fact |
| `h-compaction` | A session with `/compact` | The answer after it holds the value |
| `i-other-branch` | Another branch adds a fact mid-session | The next answer holds the value |
| `j-subagent` | A subagent needs a stored fact | A subagent ran, and the answer holds the value |
| `k git-clean` | Setup and sessions leave git clean | A row in the table, from every run |

The column `In load` shows whether `memory load` printed the fact before the agent started. Use
it to separate "the agent could not see it" from "the agent saw it and did not act".

`d-old-trap-edited` uses a committed diff on a branch. 0.3.1 reads only that signal. An
uncommitted edit is a signal only in `dev`, so it would not be a fair test.

## The value measure

All other tests check correct behaviour. They do not show that memory helps. This measure does.

### The reading rule

This rule is agreed before any run. A change stays only if it clearly beats the no-memory arm and
the earlier arms on pickup and lesson-carry, without a worse cost table. Otherwise it is cut or
rethought.

Write down what "clearly" means for your run before you read the results. With 3 repeats, a gap of
one run is noise.

### The arms

| Arm | What it is |
|---|---|
| `dev` | The current checkout. |
| `prod` | 0.3.1. |
| `none` | No memory, no hooks and no rules. The kit also hides any `memory` or `cairnkit` on the agent's `PATH`, and the agent gets no memory folder. The other tools in the same folder stay reachable. |
| `LABEL` | Any ref that you give with `--arm`. |

To test a later change, build it on a branch and add an arm. This needs no change to the kit:

```sh
uv run python evals/agents/run.py --agent claude --suite value \
  --arm dev-instructions=my-instructions-branch --arm dev-enforcement=my-enforcement-branch
```

A scenario that asks about a planted fact has no run in `none`, because it says nothing there.

### The scenarios

Each scenario has two sessions. Session A does the work. Session B picks it up, in a new process
with no resume, and it can be another tool. Nothing is planted: only what session A writes, or
what git holds, can reach session B. The prompts do not name the memory. A test checks each of
these points for each scenario.

Each scenario also has a control. A model that says nothing, or does nothing, reads as
`inconclusive` and never as `pass`. The fake provider shows this: its fixed reply gives
`inconclusive` in all six scenarios in all arms.

| Id | Sessions | What it tests | Pass | Control, else `inconclusive` | Kind of check |
|---|---|---|---|---|---|
| `pickup-decision` | 3 | The owner approves merging #412 in the conversation. Session B is asked what waits on the owner. A file in the repo still says that #412 waits. | The last `WAITING:` line does not name #412. | The line names #377, which is still open. | A fixed answer line |
| `pickup-purpose` | 2 | The reason for a branch is only in the prompt. It is not in the diff or the commit subject. | The answer names the reason (`Halvorsen`). | Session A made a commit on the branch. | Word match |
| `pickup-findings` | 2 | A review gives two findings in the conversation. Session A fixes one. | The answer names the open finding (`audit`). | Session A made a commit on the branch. | Word match |
| `pickup-dirty-worktree` | 2 | Session A hears that work still runs in the worktree beside it. Session B must tidy up. | The edits, the new file and the branch head of that worktree have not changed. | Session B removed the stale worktree or the stray log. | Git state and file content |
| `lesson-carry` | 2 | `report.sh` fails until a variable is set. Later, session B runs it with no hint. | The first run of session B passes. | Session A failed and then passed, and session B ran the command. | A log that the script writes |
| `promise-at-file` | 2 | The owner promises at most 5 sends, and names no file. Session B must make deliveries survive a 10-minute outage. | `MAX_ATTEMPTS` is at most 5. | The settings cover the outage, or the send loop still reads the limit and was changed. | File content |

The count of sessions is the count of agent calls. Session A of `pickup-decision` has two turns:
one process on `claude`, and two calls with a resume on other tools.

`fake-pickup-channel` runs only with the fake provider. A fixed reply cannot write, so the kit adds
a fact after session A. A memory arm passes if the fact is in a request of session B. `none` passes
if no memory text is in a request of session B. So it proves the path with no model.

A session with an error stops the run, so session B costs nothing after a failed session A.

In a memory arm, each session must show a hook or a `memory` command. If not, the result is
`not-connected`, and it names the session. An answer does not count as a sign of a connection,
because git can carry an answer. The `none` arm needs no connection, but it can still give `error`.

### What the extra columns tell

- **In load**: for the two-session scenarios, `memory load` ran just before session B. 0 means that
  session A wrote nothing useful, or that the load did not show it. Before session A, each value is
  absent. A test checks that no fact is planted.
- **Where session A left the text**: new facts, new commits or changed files, by word match. Read
  this first when an arm passes. A pass in `none` through a file means that the tool's own habits
  were enough. A match says that a word is there. It does not say that the text is correct.

### The cost table

The table covers only the scenarios that every arm ran, so that the arms compare like with like.

| Column | Where it comes from |
|---|---|
| Memory commands | Each start of the installed command in the trace. Hooks and the tool's own wiring are left out. |
| Facts written | New fact records in the memory folder, per session. |
| Blocked stops | A `stop` hook whose output takes another turn, for each tool's format. |
| Hook words per session | The words of what each hook printed, without the JSON around them. Output that a git hook sends to `/dev/null` does not count. |
| Rules file words per session | Untracked `.md` and `.mdc` files after setup, which a tool reads at the start of each session. |

The trace reads hook output with no change to the tool's source, in all builds alike. Whether a
fact is filler is out of scope, because this needs a reader. Hook words do not include what an
agent reads with its own `memory search`.

### Cost per agent

Each repeat of the six scenarios has 13 agent calls per arm. With 3 repeats and 3 arms, a run has
117 calls. `--dry-run` prints this count, and it spends nothing.

Request sizes were measured with the fake provider, for the first request of a session. Tokens are
the characters divided by 4, which is an estimate. The request count of 4 per call is a guess, and
no real run has tested it. Measure one real scenario before you trust this table.

| Agent | Characters per request | Input tokens per request | Input tokens for 117 calls, at 4 requests | Cost note |
|---|---|---|---|---|
| `claude` | about 53,000 | about 13,000 | about 6 M | Hard limit: 0.25 USD per process, so at most 29.25 USD. Guess with no cache: 1 USD on Haiku 5.5, 8 USD on Haiku 4.5, at the list prices of 2026-10-06. |
| `grok` | about 51,000 | about 13,000 | about 6 M | No limit flag. The kit has no price for its model. |
| `codex` | about 43,000 | about 11,000 | about 5 M | No limit flag. The kit has no price for its model. |
| `opencode` | about 32,000 | about 8,000 | about 4 M | No limit flag. The kit has no price for its model. |
| `pi` | about 7,000 | about 2,000 | about 1 M | No limit flag. The kit has no price for its model. |
| `cursor-agent` | not known | not known | not known | No fake path, so the kit has no measure. |

With the fake provider, the memory arms of `codex` and `grok` read `not-connected`, because of the
trust step (see Safety). `prod` on `pi` and `opencode` also has no hook, because 0.3.1 has no adapter
for them. A real run spends on those arms and learns little. Run one repeat of one scenario first,
and use `--skip-arm` for an arm that cannot connect.

### Limits of this measure

- **One author.** One author wrote the scenarios and the checks. They come from one real cold-start
  test. They can show a gap. They cannot show that memory helps in general.
- **Small `n`.** With 3 repeats, one run moves a rate by 33 points. Read the counts.
- **Word match.** `pickup-purpose` and `pickup-findings` match one word. A model can guess it, or
  write it in a sentence that says the opposite. Read the turns in the JSON for a close result.
- **A careful model passes with no memory.** In `lesson-carry`, a model that reads `report.sh` first
  sees the variable. In `pickup-dirty-worktree`, a model that looks before it acts can leave the
  edits alone. These are correct results, and they lower the gap that memory can show.
- **Other channels stay open in all arms.** A tool's own memory and its session logs stay on, because
  a developer has them with no cairnkit. So `none` is "no cairnkit", and it is not "no memory of any
  kind". A real run keeps your real `HOME`, so tools other than `claude` also read your user
  settings. The run folder is new, so no project note from your own work applies to it.
- **Session A can change the repo in any arm.** It can edit the queue file or add a note. This is
  allowed, and the table of where session A left the text shows it.
- **`codex`** has no way to write beside the repo, so `pickup-dirty-worktree` reads `unsupported` when
  it runs session B. It may also refuse a write under `.git`. Then the commit controls and the log of
  `lesson-carry` give `inconclusive`. This is a guess from its sandbox, and no real run has tested it.
- **The tool's own timing.** A hook that outlives session A can count in session B. This moves the
  cost table by one hook at most.

## The fake provider

`--fake-provider` starts a small local server. It records each request and gives a fixed answer.
Config goes in the temp folder only. `HOME` is a temp folder too. This gives two proofs, with no
account and no cost:

- `fake-connect`: the text of a stored fact is in a request to the model.
- `fake-auth-error`: when the provider refuses the token, the result is `error`, not `fail`.

- `fake-pickup-channel`: see [The value measure](#the-value-measure).

These proofs show delivery. They do not show that a model acts on the text.

| Agent | Fake provider |
|---|---|
| `claude`, `codex`, `opencode`, `pi`, `grok` | Yes |
| `cursor-agent` | No. It uses a private protocol and an account key exchange. |

## Safety

The kit never uses a flag that skips a safety or a trust step. `FORBIDDEN_FLAGS` in
`agent_eval/agents.py` lists them, and a test checks each command. So `codex`, `grok` and
`cursor-agent` can report `not-connected` in a new throwaway repo, because each one needs a trust
step for project hooks. This is the correct result. Do not add the flag to make it pass.

Claude runs with `--setting-sources project,local`, so your user settings and user hooks do not
change the result. Its tools come from a fixed allow list.

## Limits

- **Small models.** A small model can act differently from a large model. A result for `haiku`
  is not a result for a larger model.
- **Small `n`.** With 3 repeats, one run moves the rate by 33 points. Read the counts.
- **One author.** One author wrote the scenarios and the facts. They can show a problem. They
  cannot prove that the tool is correct.
- **Word match.** A check looks for a fixed value in the answer. It does not grade the reasoning.
- **Session logs.** A real run uses your account, so the tool writes its normal session logs in
  its own folder. Those logs name a temp path.
- **`i-other-branch`** runs in one process on `claude`. Other tools start a new process for each
  turn, and a resume can load the memory again. On those tools this row cannot separate a change
  mid-session from a restart. The field `turn_mode` in each result says which one ran.
- **`h-compaction`** runs only on `claude`. Other tools have no headless compaction that the kit
  can start.
- **`j-subagent`** reads an exact subagent count on `claude` only. Other tools use tool names, so
  a missed name gives `inconclusive`, not `pass`.
- **Default models** come from each tool's own model list on 2026-10-31. Only the `claude` default
  was used in a real call. The list of `cursor-agent` needs an account, so its default `auto` is
  not checked. If a model is refused, pass `--model`.
- **The build needs the network** once, to get the build tools. The result is kept in the temp
  folder for each commit.
