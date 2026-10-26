# Retrieval eval

`retrieval_eval.py` scores `memory search` on probe questions. It uses only
the standard library and cairnkit.

```sh
uv run python benchmarks/retrieval_eval.py benchmarks/fixtures/synthetic \
  benchmarks/fixtures/synthetic/probes.jsonl
```

The first argument is a memory folder with `facts/*.jsonl`. The second is a
JSONL file with one probe per line:

```json
{"question": "Who has to approve a production deploy?", "gold_note_ids": ["f-20261001-0007"]}
```

The report has three numbers per system: `any@1` (the top result is a gold
fact), `any@5` (a gold fact is in the top 5) and `all@5` (every gold fact is
in the top 5). The systems are `cairnkit` (the search as it is), `strict` (the
match before BM25, now `--strict`), `keyword-count` and `random`. The last two
are floors. Use `--seed` to change the random order and `--json` for JSON.

The fixture is a made-up project with 13 active facts, one superseded fact
and 14 probes. The test suite runs it and checks the floors. With only 13
facts, any@5 is easy for every system. Read any@1 first.
