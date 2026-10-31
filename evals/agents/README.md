# Agent eval kit

This kit tests real agents with two builds of cairnkit: `dev` and `prod` (0.3.1). The replay
tests in `docs/forgetting-tests.md` show what can load. They do not show that an agent acts on
it. This kit tests that.

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
| `--scenario ID` | One scenario, by id or letter (`b`). You can use it more than once. |
| `--model NAME` | The model. Each agent has one small model as the default. |
| `--budget-usd N` | Claude only: the limit for one session. The default is 0.25. |
| `--dev-ref REF`, `--prod-ref REF` | The builds. The defaults are `HEAD` and `d523c01`. |
| `--report DIR` | Makes the table again from a result folder. |

Start with these two commands. They are free:

```sh
uv run python evals/agents/run.py --agent claude --load-only
uv run python evals/agents/run.py --agent claude --fake-provider --repeats 1
```

If `dev` and `prod` are the same commit, the command stops, because a comparison has no meaning.

## Output

The results go to `evals/agents/results/<time>-<agent>/`. Git ignores this folder.

- One JSON file for each run. It holds the tool version, the requested model, the model that the
  tool reported, the result class, the reason, the evidence and the new facts.
- `report.md`: one table of dev against prod, with counts. Each row shows `n`, the number of runs.
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

## The fake provider

`--fake-provider` starts a small local server. It records each request and gives a fixed answer.
Config goes in the temp folder only. `HOME` is a temp folder too. This gives two proofs, with no
account and no cost:

- `fake-connect`: the text of a stored fact is in a request to the model.
- `fake-auth-error`: when the provider refuses the token, the result is `error`, not `fail`.

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
