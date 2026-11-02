# Value results

This file is the record of the value measure: does memory help a later session? Each run has one
entry. The method, the scenarios and the pass line are in
[evals/agents/README.md](../evals/agents/README.md). Raw results stay local in
`evals/agents/results/`, which git ignores.

A pass counts only with `pass` and `fail`. An `inconclusive` run does not count.

## 2026-11-02: a stored fact stops the short command once, on Haiku

This is a small run of 3 scenarios for one change. It is no comparison with `prod`, and it does not
replace a run of the whole suite.

- Commit: `6b89226` for `dev`, and no memory for `none`. The change: before a shell command runs,
  a fact that holds the same command behind a setting or a wrapper stops that call once
  (`PreToolUse` deny), with the fact as the reason.
- Model: `claude-haiku-5-5`, 3 repeats. A result on Haiku is not a result on a larger model.
- Sessions: 36. The session results report 0.10 USD in total.
- Local results: `evals/agents/results/20261102T081417Z-claude` in the worktree of the change.

| Scenario | dev | none |
|---|---|---|
| `lesson-carry` | 3 of 3 | 0 of 2, 1 inconclusive |
| `promise-at-file` | 3 of 3 | 0 of 3 |
| `pickup-purpose` | 3 of 3 | 0 of 3 |

| Arm | Sessions | Memory commands | Facts written | Blocked stops | Hook words per session |
|---|---|---|---|---|---|
| dev | 18 | 19 | 19 | 10 | 226 |
| none | 18 | 0 | 0 | 0 | 0 |

### What the transcripts show

- **The deny changes the first run.** In each `lesson-carry` session B, the agent ran
  `sh report.sh; echo "exit=$?"` first, as in all 6 runs of the last full run. The hook stopped
  that call. The agent then ran `REPORT_LOCALE=C sh report.sh`, which passed, and its answer named
  the memory hook. The script log shows `pass` as the first run of session B in 3 of 3.
- **It fired only where it should.** The hook ran before 51 shell calls in `dev`. It denied 3, one in
  each `lesson-carry` session B, and each was right. The other denials in the transcripts come from
  the tool list of the eval, which refuses a command with `echo` in a chain.
- **One block fewer.** A session B of `lesson-carry` no longer fails first, so its stop has no event
  to ask about. Session B had 0 blocked stops and 190 to 228 hook words, against 1 block and 291 to
  332 words in each of the 6 runs of the last full run. The deny text is about 35 words with the
  fact line.
- **Claude Code shows the reason as a hook error.** The tool result reads `PreToolUse:Bash hook
  error:` and then the reason. Haiku acted on it in 3 of 3.
- **The other two scenarios saw no deny.** No stored fact there holds a command, so the result is the
  same as without the change, which the 3 of 3 in each shows.

### False fires on real data

Read-only, before the run: the active facts of two real memories (61 facts) and 19617 shell
commands from the real Claude Code transcripts on this machine. The match fired 0 times, also over
all 227 facts that are not purged and over the commands of other projects. A first build split a
command at a `|` inside quotes, and fired 8 times on a grep pattern that held `manage.py`, each one
wrong. The steps now split outside quotes only. A wider match, a fact that names the file that the
command runs, fired 33 times in 12934 commands of the same projects. I read 25 of them, and none was right.
No real fact holds a longer form of a command yet, so this measures false fires and not recall.

### Limits

- One scenario has a fact that the hook can match, and its author also wrote the hook.
- Cursor and Grok Build have no such hook. Codex, Pi and OpenCode have it, with no real run.

## 2026-11-02: the live work list on Claude Code

This is a small run of 1 scenario for one change, in two runs. It is no comparison with `prod`.

- Commits: `51fab40` for `dev` (the list and the capture check), `d20185c` for `base` (only the
  capture check), and `f16ae08` for `list-only`. `f16ae08` is `dev` with the capture check turned off
  for this test. It is on no branch.
- Model: `claude-haiku-5-5`, 3 repeats. A result on Haiku is not a result on a larger model.
- Sessions: 24. I did not total the cost.
- Local results: `evals/agents/results/20261102T064719Z-claude` and `20261102T065146Z-claude`.

| Arm | `pickup-dirty-worktree` | Facts from session A | Blocked stops | Hook words per session | Hook words, session B |
|---|---|---|---|---|---|
| `dev` | 3 of 3 | 3 | 3 | 250 | 179 to 196 |
| `base` | 3 of 3 | 3 | 3 | 195 | 120 to 134 |
| `list-only` | 3 of 3 | 0 | 0 | 142 | 142 |
| `none` | 0 of 3 | 0 | 0 | 0 | 0 |

The baseline below gave 0 of 3 with neither the list nor the capture check, at 89 hook words.

### What the transcripts show

- **The first run alone proved nothing about the list.** Each session A in `dev` got the capture
  block and wrote a fact, so session B had two signals. Hence `base` and `list-only`.
- **Each signal is enough here.** In `list-only`, no fact existed, and each session B cited the list:
  "live work this session didn't start, and you didn't name it". In `base`, each session B cited the
  fact.
- **Session B did not obey the words "commit, discard or remove" for that worktree in 9 of 9 runs
  with a signal.** It removed the clean worktree, left the dirty one, and said so. In `none`, it
  committed the running work in 3 of 3 runs.
- **Session B did not finish the tidy-up in any arm with a signal.** The tool held its `rm` of the
  log for a permission, so the control passed through the removed clean worktree.

### Cost

The list adds 52 words when one checkout is dirty (141 against 89, measured on one throwaway repo),
and 0 words in a clean project. The order line is about 40 of these words.

### Limits

- One author wrote the scenario and the line, and the line says "a general tidy-up" because of it.
  The list is not tested on a task that is not a tidy-up.
- The owner's general words lost to the line here. That is the aim for running work, but an owner who
  wants their own old edits committed must now name them.
- No session in this scenario was at work during session B, so the marker part had no real test. Only
  unit tests with hook payloads cover it.
- A commit that takes the files of another session in the same checkout has no scenario.

### Decisions

- Keep the list. It carries the running work with no fact, where the capture check depends on session
  A being told.
- No warning at pre-commit, for now. In 9 runs with a signal, no commit reached that worktree, so the
  moment did not occur. A git hook also cannot tell its own session from another on
  each tool, and no record says which session changed which file when a shell made the change. A
  warning that cannot tell would fire on the session's own files, as the trap line in the field
  feedback did.
## 2026-11-02: full run with the capture check and the gate, on Haiku

- Commit: `d20185c` for `dev` (capture check, gate off) and `gate` (capture check, gate on),
  `d523c01` (0.3.1) for `prod`, and no memory for `none`.
- Model: `claude-haiku-5-5`, 3 repeats. A result on Haiku is not a result on a larger model.
- Sessions: 156. The session results report 0.46 USD in total.
- Local results: `evals/agents/results/20261102T062630Z-claude`.
- The scenarios changed after the baseline. `pickup-decision` now has an answer in local files, and
  `promise-at-file` also reads a backoff list. Both changes apply to each arm. The second came from
  `dev` runs that kept the limit and scored inconclusive.

| Scenario | dev | gate | prod | none |
|---|---|---|---|---|
| `pickup-decision` | 1 of 3 | 2 of 3 | 0 of 3 | 0 of 3 |
| `pickup-purpose` | 3 of 3 | 3 of 3 | 3 of 3 | 0 of 3 |
| `pickup-findings` | 3 of 3 | 3 of 3 | 3 of 3 | 0 of 3 |
| `pickup-dirty-worktree` | 3 of 3 | 2 of 2, 1 inconclusive | 1 of 3 | 0 of 3 |
| `lesson-carry` | 0 of 3 | 0 of 3 | 0 of 3 | 0 of 3 |
| `promise-at-file` | 3 of 3 | 3 of 3 | 0 of 3 | 0 of 3 |
| **Total** | **13 of 18** | **13 of 17** | **7 of 18** | **0 of 18** |

| Arm | Sessions | Memory commands | Facts written | Blocked stops | Hook words per session |
|---|---|---|---|---|---|
| dev | 36 | 33 | 33 | 23 | 231 |
| gate | 36 | 24 | 24 | 18 | 201 |
| prod | 36 | 29 | 9 | 9 | 183 |
| none | 36 | 0 | 0 | 0 | 0 |

### Against the pass line

- `dev` beats `none` by 13 passes in 5 scenarios, and is worse in none. It clears the line.
- `dev` beats `prod` by 6 passes in 3 scenarios (`pickup-decision`, `pickup-dirty-worktree`,
  `promise-at-file`), and is worse in none. It clears the line on Haiku, by the smallest margin that
  can. One changed run moves it.
- `gate` against `dev` is 13 of 17 against 13 of 18. That gives no proof either way. It costs fewer
  blocks (18 against 23) and fewer words (201 against 231). No scenario tests its push refusal.
- The reading rule also asks for no worse cost table. `dev` does not meet this: 231 hook words and
  23 blocks against 183 and 9 for `prod`. The guide is the largest part, at 157 words.
- The keep or cut decision needs a run on a larger model.

### What the transcripts show

- **Capture now works.** Facts written rose from 9 in `prod` to 33 in `dev`. The fact in session A now
  changes the file in session B: every `dev` and `gate` run of `promise-at-file` kept the limit at 5.
  Every `prod` and `none` run broke it, with values from 21 to 300.
- **A loaded fact does not make the agent act on it.** In all 6 `lesson-carry` runs of `dev` and `gate`,
  session A stored the fix and session B had it in its load. Session B still ran the plain command
  first and failed. This is now the largest open gap, and it is on the read side.
- **Two fails of `pickup-decision` read as fair answers.** Each session B listed #412 from the queue
  file, and then said that a stored note says the owner approved it. The check fails any answer that
  reports #412 as waiting. I did not change it, because that would help the build under test.
- **The word match undercounts.** The table of where text was left shows `memory 1 of 3` for
  `pickup-dirty-worktree` in `dev`, but all 3 runs wrote a fact about the running work in other words.
- **Some facts are weak.** I read the first 230 characters of each `dev` fact. About 9 of 33 restate
  what git or the diff shows, for example `Branch tune-retry-window holds one commit`. This count is
  one reader's judgement.

### Limits

- One author wrote the scenarios, and these results also led to the changes that they measure.
- `claude -p` runs one prompt in a session, so this does not measure a long session. Blocks per turn
  there come only from tests, not from real use.
- This is one tool and one small model.

## 2026-11-02: the capture check on Claude Code

This is a small run of 3 scenarios for one change. It is no comparison with `prod`, and it does not
replace a run of the whole suite.

- Commit: `7e83f11` for `dev`, and no memory for `none`. The guide changed after two earlier runs of
  the same size, at `a9481bc` and `9b6bcf7`.
- Model: `claude-haiku-5-5`, 2 repeats. A result on Haiku is not a result on a larger model.
- Sessions: 24 for each run. The 3 runs report 0.20 USD in total.
- Local results: `evals/agents/results/20261102T051625Z-claude`.

| Scenario | dev | none | Reading |
|---|---|---|---|
| `pickup-purpose` | 2 of 2 | 0 of 2 | The block gave the reason as a fact, and session B answered from it |
| `promise-at-file` | 0 of 0, 2 inconclusive | 0 of 2 | Both session As wrote the promise. Both session Bs replaced the backoff number with a list, so the check cannot read the file. Their facts say 5 attempts. `a9481bc` gave 2 of 2 |
| `lesson-carry` | 0 of 1, 1 inconclusive | 0 of 2 | One session A wrote the fix. Session B loaded it and still ran the command that its prompt names, and failed first. The other session A read the script first, so it had no failure |

| Arm | Sessions | Memory commands | Facts written | Blocked stops | Hook words per session |
|---|---|---|---|---|---|
| dev | 12 | 13 | 11 | 8 | 229 |
| none | 12 | 0 | 0 | 0 | 0 |

### What the transcripts show

- **The check gets the facts.** Session A of each `pickup-purpose` and `promise-at-file` run wrote the
  reason or the promise in all 12 runs of `dev`. The baseline `dev` wrote 0.
- **Lesson-carry needed its own signal.** Session A failed once and passed with a setting, and it
  changed no file. No check fired at `a9481bc`. The new event for a command that passes behind a
  prefix fires.
- **The first guide let a decline through.** An agent said that a doc holds the fix, and the guide
  said that a doc is enough. The next session failed the same way. The guide now says that a doc
  that the next agent reads only after it fails is no record.
- **A plain `memory add` gave each fact twice.** It prints a note about its basis, and agents wrote
  the fact again with `--basis told`. The guide now names the flag. Memory commands fell from 19 to
  13, and 3 runs are too few to be sure of this.
- **Capture is not the limit in `lesson-carry`.** Session B had the fact and failed first, because
  its prompt names the command. The block then costs it one more turn, because the event does not
  look at the stored facts.

### Limits

- The hook words per session are above the 182 of 0.3.1 in the baseline, on other scenarios. The
  guide has 157 words.
- Some facts are weak. Example: `Commit has no body by owner request.` A later full run must count these.

## 2026-11-02: baseline on Claude Code

- Commit: `9e9b04c` for `dev`, `d523c01` (0.3.1) for `prod`, and no memory for `none`.
- Model: `claude-haiku-5-5`, 3 repeats. A result on Haiku is not a result on a larger model.
- Sessions: 117. The session results report 0.36 USD in total.
- Local results: `evals/agents/results/20261102T041124Z-claude`.

| Scenario | dev | prod | none | Reading |
|---|---|---|---|---|
| `pickup-decision` | 3 inconclusive | 3 inconclusive | 3 inconclusive | The scenario failed: session B needs `gh`, and the tool denied it |
| `pickup-purpose` | 0 of 3 | 3 of 3 | 0 of 3 | Blocked stop gave a fact |
| `pickup-findings` | 0 of 3 | 3 of 3 | 0 of 3 | Blocked stop gave a fact |
| `pickup-dirty-worktree` | 0 of 3 | 0 of 3 | 0 of 3 | Session A only replied, so no arm wrote. Session B committed the running work |
| `lesson-carry` | 0 of 3 | 0 of 3 | 0 of 3 | Session A changed no file, so no arm wrote |
| `promise-at-file` | 0 of 2, 1 inconclusive | 0 of 3 | 0 of 3 | Session A replied "Noted", so no arm wrote |
| **Total** | **0 of 14** | **6 of 15** | **0 of 15** | |

| Arm | Sessions | Memory commands | Facts written | Blocked stops | Hook words per session |
|---|---|---|---|---|---|
| dev | 36 | 9 | 0 | 0 | 90 |
| prod | 36 | 29 | 9 | 9 | 182 |
| none | 36 | 0 | 0 | 0 | 0 |

Against the pass line, `prod` beats `none` by 6 passes, but in only 2 scenarios, so it does not
clear the line. `dev` is not better than `none`.

### What the transcripts show

- **The blocked stop of 0.3.1 caused the facts.** In `pickup-purpose`, the stop said that the work
  changed and no fact was written. The agent wrote the reason, which only the conversation held.
  Session B read it and answered from it. In `dev` the same model wrote nothing.
- **`dev` lost this when it moved the reminder to the next prompt.** A session that ends has no next
  prompt, so the reminder never arrives at the end of a session. This is a regression.
- **Neither build catches what only the conversation holds.** When session A changes no file, 0.3.1
  does not fire. The agent replies "Noted", and the promise or the decision is gone.
- **A fact from a block can be good.** The sampled facts state the real reason. This run does not
  measure how often a block gives filler.

### Decisions

- Bring back one blocking write check at stop, and add the case where only the conversation changed.
  Test it as a new arm before it stays.
- Fix `pickup-decision`, so that session B can answer from local files. Done: the prompts now say
  that GitHub is not reachable and name the queue file. So an earlier `inconclusive` of this
  scenario does not compare with a later `pass` or `fail`.
- `pickup-dirty-worktree` and `lesson-carry` need no fix. A scripted session with the real tool
  passes each of them when session A writes the fact, and these two failed because no arm wrote.

### Limits

- One author wrote the scenarios, and two of them match one word.
- `claude -p` runs one prompt in a session, so a reminder at the next prompt cannot arrive in most
  of these sessions. In a long interactive session it can arrive, but not after the last turn.
- This is one tool and one small model.
- The column "Memory commands" also counted the check that the pre-commit hook runs for each commit
  (`python -c 'import cairnkit'`). The kit no longer counts it, so this column does not compare with
  a later run.

## 2026-11-02: the branch-note gate, two scenarios

This is a first look at one arm. It is not a keep or cut decision: it covers 2 of the 6 scenarios,
and the reading rule needs at least 3.

- Commit: `6135ec2` for `dev` (gate off) and `gate` (gate on), `d523c01` for `prod`, and no memory
  for `none`. The switch is the only difference between `dev` and `gate`.
- Model: `claude-haiku-5-5`, 2 repeats.
- Sessions: 32. The session results report 0.086 USD in total, of which `gate` is 0.021 USD.

```sh
uv run python evals/agents/run.py --agent claude --dev-ref HEAD \
  --arm gate=HEAD --arm-git gate:cairnkit.branchnotegate=true \
  --scenario pickup-purpose --scenario pickup-findings --repeats 2
```

| Scenario | dev | prod | gate | none |
|---|---|---|---|---|
| `pickup-purpose` | 0 of 2 | 2 of 2 | 2 of 2 | 0 of 2 |
| `pickup-findings` | 0 of 2 | 2 of 2 | 2 of 2 | 0 of 2 |

| Arm | Sessions | Facts written | Blocked stops | Hook words per session |
|---|---|---|---|---|
| dev | 8 | 0 | 0 | 89 |
| prod | 8 | 4 | 4 | 216 |
| gate | 8 | 4 | 0 | 124 |
| none | 8 | 0 | 0 | 0 |

The extra words of `gate` have two causes. Session A hears the refusal, which is 34 words. Session B
reads the note in its load, which is 32 to 39 words.

### What the transcripts show

- Each `gate` run refused one commit, and the agent ran one `memory add` and committed again. The
  agent replaced each placeholder.
- All four notes state the real text: the Halvorsen restart, or the open audit finding. The prompts of
  these two scenarios state that text, and the refusal asks for what the branch is for, the next step
  and any open finding. So these scenarios suit this gate. This run does not show how often a note
  is filler in other work.

### What this run does not test

- No scenario pushes, so a real model has not met the push refusal. Real git runs in throwaway repos
  and the tests prove that path.
- The gate cannot help a scenario with no commit on a branch: `pickup-decision`, `lesson-carry`,
  `pickup-dirty-worktree` and `promise-at-file` have none in session A.
- It ran on one tool and one small model. The hook of another tool was not run with a real model.

### What one commit and push run costs an agent

Measured with real git in a throwaway repo, for two commits and two pushes.

| | Tool calls | Words the gate prints |
|---|---|---|
| Gate off | 4 | 0 |
| Gate on | 8: two refused calls and two `memory add` | 74, and git adds 7 for its refused push |
