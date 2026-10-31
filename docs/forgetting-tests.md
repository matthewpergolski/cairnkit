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

1. A wrong trap that nobody corrects keeps loading when its area is in use. The contradiction
   prompt reduces this. It does not remove it.
2. An old trap with no signal can stay out of the load until the first commit gives a signal. A
   trap that must always load uses `--pinned`.
3. A fact that the agent never writes is lost. A pointer that holds only history is not built
   until real-agent tests show how often this happens.

## Run it

```sh
uv run python benchmarks/forgetting/harness.py --seeds 30 --out /tmp/forgetting.json
```

The result is JSON. The `summary` key holds one row for each scenario, policy and label.
