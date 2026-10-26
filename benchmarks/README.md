# Retrieval benchmarks

`retrieval_eval.py` scores `memory search` and `memory load` on probe
questions. It uses only the standard library and cairnkit. It reads a memory
folder and writes nothing.

```sh
uv run python benchmarks/retrieval_eval.py benchmarks/fixtures/coding \
  benchmarks/fixtures/coding/probes.jsonl --budget 300 --budget 600 --budget 1200
uv run python benchmarks/retrieval_eval.py benchmarks/fixtures/coding \
  benchmarks/fixtures/coding/probes_fragments.jsonl --no-load
```

A run takes about 2 seconds. `--json` prints JSON. `--seed` changes the random
baseline. `--no-load` skips the load part. The tests run the same code in
about 4 seconds (`tests/test_coding_benchmark.py`, `tests/test_retrieval_eval.py`).

## What it shows and what it does not

It is a retrieval benchmark on synthetic project notes. It is not an
end-to-end agent run. It does not ask a model anything.

The fixture is made up and small: 101 active facts, 7 superseded ones and 58
questions. Use the numbers as a regression guard and to compare rankers. Do
not read them as a claim about real notes. One author wrote the facts and the
questions, and the questions were not held out, so a change tuned on them
would look better than it is. A group of fewer than 10 questions is flagged as
unreliable, and the report says so.

## Files

- `fixtures/synthetic/`: 13 facts and 14 questions. It is the first harness
  check and it is easy.
- `fixtures/coding/`: a made-up shipment tracking web service with a job
  queue and a database. `facts/main.jsonl` holds the facts. `probes.jsonl` has
  58 questions in five kinds: `decision`, `fix`, `convention`, `preference`
  and `stale`. `probes_fragments.jsonl` has 10 lookups with the start of a word,
  such as `idempot`.

A probe line looks like this. Only `question` and `gold_note_ids` are
required.

```json
{"question": "How do we merge PRs?", "gold_note_ids": ["f-20260610-001b"], "kind": "convention", "decoy_note_ids": ["f-20260725-005a", "f-20260829-0040", "f-20260611-001e"]}
```

- A **stale** fact is an older, wrong answer that a newer gold fact replaces.
  In the coding fixture, 7 of the 13 stale facts carry a `superseded` change
  record. The other 6 are still active, as when an agent adds a new fact and
  forgets to supersede the old one.
- A **decoy** shares words with a gold fact but is not the answer.
- 26 of the 58 questions share at most one word with their answer, so a
  plain word match is not enough.

## Numbers

Search ranks the facts for each question. A rate is over the probes it can be
measured on.

- `any@1`: the top result is a gold fact.
- `any@5`: a gold fact is in the top 5. `all@5`: every gold fact is.
- `stale>gold`: a stale fact ranks above the best gold fact. `stale@5`: a stale
  fact is in the top 5. A superseded fact is not in a search over active
  facts, so only the 6 active stale facts count there. `n-stale` shows the
  count.
- `decoy@1`: the top result is a decoy.
- `empty`: probes with no result.

Systems: `cairnkit` (the search as it is, with the word-start fallback),
`cairnkit-whole-word` (without the fallback), `strict` (the old every-word
match), `keyword-count` (question words counted as written), and the floors
`random` (one seed) and `random-mean` (20 seeds). Controls prove that the
harness can tell good from bad: `oracle` must score 1.0, and `inverted` and
`mismatched-query` must score near the random floor.

Load. `memory load` does not read the question. It fills a word budget from
the same facts for every probe, so one set is loaded per budget. The report
gives `gold@load` (a gold fact is loaded), `gold-all@load`, `stale-leak` (a
stale active fact is loaded) and `decoy-loaded`, against `newest-first` and
`random-fill` with the same budget. Rules always load and do not use the
budget. Read it as: how often does the standing set already hold the answer.

The report also splits search by probe kind and by how many words the question
shares with its answer, and gives a paired bootstrap 95% interval (2000
resamples of the probes) of the difference between two systems.

## Results at the freeze (58 questions, 101 active facts, seed 0)

| System | any@1 | any@5 |
| --- | --- | --- |
| `cairnkit` | 0.53 | 0.81 |
| `keyword-count` | 0.34 | 0.67 |
| `strict` | 0.00 | 0.00 |
| `random-mean` | 0.01 | 0.05 |
| `oracle` (control) | 1.00 | 1.00 |
| `inverted` (control) | 0.00 | 0.02 |

- `cairnkit` minus `keyword-count` is +0.190 [+0.052, +0.328] on any@1 and
  +0.138 [+0.017, +0.259] on any@5.
- `strict` finds nothing for a question, because no note holds every word.
- The fallback changes nothing on these questions, because they hold whole
  words. On the 10 word fragments it lifts any@5 from 0.00 to 1.00. That is
  built in, so it checks the feature and says nothing about quality.
- A stale fact that nobody superseded ranks above the newer gold fact in 5 of
  6 cases (n=6, unreliable), about as often as for `keyword-count`. Search
  cannot tell an old fact from a new one that says almost the same thing.
- Questions that share at most one word with the answer score 0.23 on any@1,
  against 0.78 for the rest.
- `load` holds a gold fact for 0.48 of the questions at `--budget 600`, against
  0.41 for newest-first and 0.38 for a random fill. That is a small lead.
  At `--budget 300` it is 0.29 against 0.28 for newest-first and 0.23 for a
  random fill. At `--budget 1200` it is 0.74 against 0.62 and 0.69.
  It never loaded a stale fact, because the stale facts are the older ones and
  load prefers newer facts.
