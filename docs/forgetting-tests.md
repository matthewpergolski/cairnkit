# Forgetting tests

This page records the tests behind [how memory must work](../README.md#how-memory-must-work).
Read the limits before you use a number.

## Question

The goal is memory that is hands-off and personal. What makes a fact stop loading, with no
person in the loop, when a vacation must not cause forgetting and a long session must still
work?

## Decision

- Nothing ends a fact because of the clock or because the agent stayed silent.
- A fact stops loading because of a recorded event, or it loses its place in the word budget
  to a more relevant fact.
- `memory add` is the capture. There is no separate capture stage, and refining is not required.

The owner accepted this on 2026-10-31 for the `dev` branch.

## Method

`benchmarks/forgetting/harness.py` replays synthetic project histories through the real
`cairnkit.load.build_output` under each policy. Only the inputs are stubbed: clock, branch,
changed paths, active set and use. It uses 30 seeds and a budget of 600 words. The score is the
share of the facts that the next task needs and whose text the load shows.

The decision rule was written before the first run. See the top of `harness.py`.

| Scenario | What it models |
|---|---|
| Vacation | 14 days with no work, then a return to the same work |
| Busy day | 12 sessions on one day across 6 branches |
| Long session | One session over 6 days, with a reload at each compaction |
| Mixed work | 8 weeks of work across areas |
| Old trap | A trap written 150 days before its area is used again |
| Wrong trap | A trap that was never true, and nobody corrects it |

## Results: the agent never refines

| Policy | Vacation | Busy day | Long session | Mixed work |
|---|---:|---:|---:|---:|
| Oracle control | 1.00 | 1.00 | 1.00 | 1.00 |
| Random control | .14 | .14 | .14 | .14 |
| 0.3.1 load, with scenario folding | .59 | .68 | .09 | .13 |
| Calendar limit, 14 days | 0 | .75 | .83 | .56 |
| Active-day limit, 14 days | .75 | .75 | .83 | .58 |
| End after 20 loads with no use | .78 | .77 | .83 | .58 |
| Rank by use, no recency | .81 | .59 | .71 | .65 |
| Budget only, no folding | .83 | .99 | .83 | .68 |
| Events and budget, no folding | .83 | .99 | .83 | .68 |
| Events, budget and a trap bonus | .83 | .99 | .83 | .68 |

All rows except the 0.3.1 row have folding off. "Events" gives the same score as "budget only"
in this table because this agent writes no events. With an agent that writes every event, its
stale share falls to 0 and the long session rises to .91.

## Results: an old trap

| Policy | With a diff in the trap's area | With no signal | Busy area, no signal, all needs |
|---|---:|---:|---:|
| 0.3.1 load | 1.00 | .37 | .57 |
| Calendar limit, 14 days | 0 | 0 | 0 |
| Active-day limit, 14 days | 0 | 0 | 0 |
| Events and budget, no folding | 1.00 | 0 | .06 |
| Events, budget and a trap bonus | 1.00 | 0 | .20 |

Both age limits lose the trap each time. **Removing folding has a cost**: with no signal, the
0.3.1 load shows some old facts because a fold gives each area one place. The newer facts crowd
them out when folding is off. Search finds the trap in the top five at .67.

## Results: one place for each area

The owner asked about the loss in the table above, so it was tested again at commit `1040bd7`.
Folding gave each area one place in the load. The same benefit can come with no hidden text: one
third of the budget keeps one place for each area, and a trap holds that place if the area has one.
These places apply only when the load has no signal about the work. With a signal, relevance
already ranks the facts, and the places cost a long session .10. The share of 1/4, 1/3 and 1/2 and
the use of places with a signal were tested, and 1/3 with no signal was chosen.

| Share of needed facts shown | No places | With places | 0.3.1 |
|---|---:|---:|---:|
| Vacation | .82 | .82 | .59 |
| Busy day | .99 | .98 | .68 |
| Long session | .83 | .83 | .09 |
| Mixed work | .68 | .67 | .13 |
| Old facts | .47 | .67 | .60 |
| Old facts, busy area | .20 | .43 | .57 |
| Old trap, no signal | 0 | .97 | .37 |
| Old trap, diff in its area | 1.00 | 1.00 | 1.00 |
| Wrong trap shown (lower is better) | .71 | .86 | .55 |

**The cost is explicit.** Old facts in a busy area are still below 0.3.1. A wrong trap that nobody
corrects shows more often, because a trap holds its area's place. Real-agent tests must include
the old-fact cases, and a trap that must always load uses `--pinned`.

A later change gave a further gain. A changed file that matches no fact is no longer a signal, so
the area places stay in use for it. The paired difference over 30 seeds is +.097 (standard error
.003) on old facts, +.080 (.007) on a busy area, and +.041 (.005) on the wrong trap, which is a
cost. This gain comes from one load in the fixture, so treat it as weak evidence.

| Share of needed facts shown | Final `dev` | 0.3.1 |
|---|---:|---:|
| Vacation | .82 | .59 |
| Busy day | .98 | .68 |
| Long session | .83 | .09 |
| Mixed work | .67 | .13 |
| Old facts | .77 | .60 |
| Old facts, busy area | .51 | .57 |
| Old trap, no signal | .97 | .37 |
| Wrong trap shown (lower is better) | .90 | .55 |

## Results: other costs

| Measure | Result |
|---|---|
| Refining required, with an agent that always refines | 101 actions per 100 facts; mixed work .66 |
| Events only, with the same agent | 1 action per 100 facts; mixed work .66 |
| A wrong trap that nobody corrects, share of loads that show it | .56 events; .71 with the trap bonus; .97 rank by use |
| Facts the agent actually wrote, 100, 50 or 25 percent | Mixed work .68, .38, .21 |
| Relevance signal present against absent, on the fixture | .84 against .51 |

## Results: the same facts, only the clock moves

`benchmarks/forgetting/clockcheck.py` measures the share of needed facts after a gap with no
writes. The 0.3.1 load falls when `STALE_DAYS = 90` removes facts from its folds. With no folding,
the score does not change. The recency term only orders facts, so it is not a hidden age limit.

| Gap in days | 14 | 30 | 60 | 90 | 120 | 365 |
|---|---:|---:|---:|---:|---:|---:|
| 0.3.1 load | .78 | .77 | .61 | .15 | .15 | .15 |
| No folding | .74 | .73 | .73 | .73 | .73 | .73 |

## Results: finding a contradiction

The coding fixture has 13 pairs where a newer fact makes an older one stale.

| Test | Pairs caught | False pairs |
|---|---:|---:|
| `similarity()`, the near-repeat test | 0 | |
| Same area, word overlap of .30 or more | 9 | 0 |
| Same area, word overlap of .25 or more | 11 | 0 |
| Same area, word overlap of .20 or more | 12 | 2 |

The fixture is hand-written, so the real rate of false pairs is not known. For this reason the
overlap only prompts the agent. It never ends a fact.

## Results: near repeats

`benchmarks/near_repeat_eval.py` runs a labelled set of 80 pairs. It holds 40 real sentence pairs
from the docs of this repo, 20 from two audits, 7 from the tests and 13 that one author wrote. A
pair is `repeat` when the newer text says all that the older one says, else `different`.

| Rule | False retires, of 51 | Repeats caught, of 29 | Pairs left for the agent task |
|---|---:|---:|---:|
| The same words in order, after case, plural, punctuation and stop words | 16 | 9 | 51 |
| The same text byte for byte, apart from whitespace and a final `.`, `,`, `;` or `:` | 0 | 3 | 62, 24 of them repeats |

The 16 false retires of the older rule are all audit rows: `-1` and `1`, `retries != 0` and
`retries = 0`, `Foo` and `foo`, `users` and `user`, `plan A` and `plan`. On the 64 older rows, which
held no such pair, the older rule made 0 false retires.

**The cost is explicit.** 26 of the 29 repeats now load twice until an agent settles them. A false
retire loses a true fact, and a repeat costs some words in the load, so this is the right side of
the trade. One author wrote the labels.

The similarity flag lost its lists of negations and opposites, and of words that look plural. A
flag only asks an agent to look, so a pair that differs by `not` or by a number now reaches the
agent task. It did not before, so the agent task can grow. On a copy of this repo's own memory (99
active facts) and on the coding and synthetic fixtures (114 facts), both versions flag 0 pairs and
retire 0, so the real memory gives no evidence for the rule, and no sign of noise.

A later change took two shapes out of the agent task, on this count: one swapped word (10 pairs, 1 a
repeat) and a change in numbers alone (1 pair, not a repeat). 62 pairs stay, which is down from 73.
A word added stays in the task, because 13 of those 19 pairs are repeats. The task shows at most 20
at a time, ranked by shared words and by the share of words. Counted pair by pair, the first 20
hold 11 repeats. With all 160 sentences in one memory they hold 7, because sentences that recur
across rows make other pairs. The rest appear as the first ones are settled.

The forgetting replay does not run auto-tidy, and `harness.py` does not import the repeat test, so
these numbers do not move it.

## Reproduced defects in 0.3.1

Each item was reproduced by hand against 0.3.1 after real agents reported it:

- A `held_by` file from another branch stopped commits on all branches.
- `--until-merged` read a branch with no local copy as merged, and it read a squash-merged branch
  with a local copy as open.
- The `post-commit` hook stored comment fragments as long-term facts, labelled as written by an
  agent.
- The secret scan missed `INVITE_CODE=`, `HOST_CODE=`, `CRON_SECRET=`, `?k=`, `MY_API_KEY=`,
  `STRIPE_KEY=rk_live_` and `Bearer` tokens. `memory check` did not read `notes/`.
- `memory add --kind rule --summary` and an unquoted multi-word `memory search` stopped the agent
  with an error.
- With 8 facts in one area, the load showed 2 texts, printed "(no active long-term facts)", and
  said "0 fact(s) shown".

## How this was checked

- A second run of the harness gave the same result in all 660 rows, in 46 seconds.
- `fixture_replay.py` and `clockcheck.py` were run again and gave the numbers on this page.
- These numbers come from commit `2326ea0`. Later commits remove folding, so the folding
  rows run only at that commit.

## Tests after this record

- **Real agents.** A real Claude Code run answered with a word that only the memory held, and its
  failure hook counted 3 failed commands. Pi and OpenCode ran `session-start` in the real tools.
- **Agent eval kit.** `evals/agents/run.py` compares `dev` with 0.3.1. With a fake local provider,
  the stored fact reached the model request from Claude Code, Pi and OpenCode. Codex and Grok read
  as `not-connected`, inferred from their trust steps. Cursor has no fake path. The scenarios for
  old facts, for a wrong trap and for capture have no real model run yet.
- **Session start.** With 2000 facts, the median wall time fell from 48.2 seconds to 1.42 seconds
  on a loaded computer. Run `benchmarks/session_start_time.py` to measure it again. With the
  near-repeat rule that needs only one group per fact, one later run gave .59 seconds before and
  .53 seconds after, in the same conditions, and 1.16 seconds at 5000 facts.
- **Slow git.** With git at 2 seconds per call, a load fell from 43 seconds to 7.1 seconds, and a
  session start from past 60 seconds to 7.1 seconds. Both still print the facts.
- **Secret scan.** A value behind a secret label is refused unless its shape says that it is no
  value. A value from an untracked `.env*` file is refused too. On the hand-written sets, 0 of 30
  ordinary lines are refused and 39 of 39 secrets are refused, the same as before. Of 8 lines that
  were stored by mistake, 7 are now refused (0 before). A bare word after `password is` still passes,
  because no shape tells it from English. `tests/test_secret_shapes.py` lists what still passes.
  A value in an untracked `.env*` file counts under any name when its own shape is no ordinary
  word: it holds a digit, it has mixed case, or it is long. The password of a URL counts too.
  `NODE_ENV=production` and `PORT=3000` stay clean. A name that says what the value is, such as
  `AWS_REGION`, stays clean with any value.
  A fact stored before the scan caught it loads in its normal section at its normal rank, with the
  value replaced by `[secret: NAME]`. An owner's rule keeps its force. Show, search, change, keep
  and supersede work on it and print only the mask. One short load line tells the agent to write a
  clean replacement with `--supersedes`, then to purge the old record. A plain word from a `.env`
  file can stay: the mask is harmless, and a stop names each fact once. A note line loads masked.
  A damaged line is scanned too, also after `memory repair`, and `memory purge line-HASH` removes
  it. The value stays on disk until a purge, and `memory check` says so. A failed command that
  holds a secret is stored and shown as a stand-in.
  The mask needs the `.env*` file. In a clone with no such file, or after the file is removed, the
  value prints in clear, because the tool keeps no record of it. A stored hash of a secret is a new
  risk. The load that first sees a hard catch tells the agent to replace and purge, and
  `tests/test_masked_copy.py` proves that this route removes the value for good. A plain word has
  no such route, so it can print in clear where the file is absent. `memory add` refuses a mask in
  its text, summary or area: stored as text, a mask takes the place of the true word for good.

## Limits

- **No real agent took part.** The harness shows what can load. It does not show that an agent
  acts on it. Testing `dev` against production with real agents must answer that.
- **The histories and the needs are synthetic**, and one author wrote them. The results can rule
  a policy out. They cannot prove that a policy is correct.
- **The benefit of refining is partly set by construction.** The agent in the harness refines
  correctly each time, so its stale share is 0 by design.
- **Short facts help.** With 44-word facts, as in the real memory of this project, only 12 facts
  fit in the budget and the differences between policies become smaller.
- The published `gold@load` of `.48` also counts facts that show only an id. With text alone, the
  fixture scores `.45`.

## Accepted risks

The owner accepted these for `dev`:

1. A wrong trap that nobody corrects keeps loading, including when its area is not in use. The
   contradiction prompt reduces this. It does not remove it.
2. An old trap with no signal can stay out of the load when its area already shows a newer trap,
   or when the areas use up their places. A trap that must always load uses `--pinned`.
3. A fact that the agent never writes is lost. A pointer that holds only history is not built
   until real-agent tests show how often this happens.

## Run it

```sh
uv run python benchmarks/forgetting/harness.py --seeds 30 --out /tmp/forgetting.json
```

The result is JSON. The `summary` key holds one row for each scenario, policy and label.
