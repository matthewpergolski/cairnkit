# Value results

This file is the record of the value measure: does memory help a later session? Each run has one
entry. The method, the scenarios and the pass line are in
[evals/agents/README.md](../evals/agents/README.md). Raw results stay local in
`evals/agents/results/`, which git ignores.

A pass counts only with `pass` and `fail`. An `inconclusive` run does not count.

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
