# Roadmap

These items are not built. The order is not a promise. Each item starts with a
short spec and failing tests. What is built is in the [README](README.md) and
in [docs/](docs/).

## Agent tools

- Hook adapters for OpenCode and Pi. Today they get only the rules block in
  `AGENTS.md` and the generic commands.
- Check whether other agent tools run the hooks that `memory` writes for
  Cursor or Claude Code. Add an adapter only after a check against the tool's
  public docs.
- Cover a bare git repository. The worktree link does not work there yet.
- Test Windows. Links need developer mode or admin, and the update lock does
  nothing there.

## Names and places

- Add `memory where`. It prints the memory folder and every checkout linked
  to it.
- Clearer names for the memory folder (`<repo>.memory`) and the link
  (`memory-bank`). A rename comes with a migration, and the old names stay as
  aliases until the rename is checked. Nothing is deleted.
- Open choice: a central folder (for example `~/.local/share/cairnkit/<repo>/`)
  keeps the projects folder tidy, but it is less visible.
- Drop the `project-memory` names (markers, receipt and record) a few releases
  after the rename to cairnkit.

## Clean-up

`memory tidy` and `memory tidy --auto` are built. Git-event tidy is built
too: personal `pre-push` and `post-merge` hooks run the same step after a
push or a merge. Still to build, with no model:

- `superseded_by` chains that end in a fact that is not active;
- `promoted` facts whose `held_by` file is gone;
- active facts with `basis: guess` older than 60 days: propose a check;
- active facts that name a file that is gone.

**Optional small-model step, off by default.** Group the active facts by area.
Send each group with one fixed prompt. The model returns JSON only: duplicates
to merge, pairs to link, contradictions, and facts to promote to a rule, doc,
test or lint. The provider and model come from `config.toml`, with a fixed
call budget and a cost log. The output is a proposals file. A person accepts
or rejects each proposal. A change applies by itself only when it can be
undone. A contradiction always waits for a person.

## Migration

`memory migrate` is built. Still to build:

- `memory migrate --facts`: turn clearly dated lines of the worklist into
  facts, with no model. Counts in and out must match. It shows the plan first
  and acts only with `--yes`.
- Table rows and wrapped paragraphs in old notes as candidates.
- `--fix-references` for files other than top-level and `docs/` Markdown.

## Many developers and many agents (design)

Today one memory folder serves one person and their agents. The design:

- A developer and an agent are both an identity. Each fact records the
  identity that wrote it.
- A session loads layers: the identity's own scope, the project's shared
  scope, and the agent scope. They merge under the word budget. The more
  specific scope wins a tie.
- Shared facts live in a sync layer, not in git. A git-tracked team folder was
  rejected: it gets messy. The simplest layer is a shared folder or a small
  remote store that takes appended records.
- Records are append-only, with unique ids. Two identities never cause a merge
  conflict.
- A fact moves into the shared scope only on purpose.
- When two identities disagree, both facts stay. The tool flags the pair. A
  person decides.

Later: a store for in-app agents, an SDK, and a thin MCP wrapper.

## Repeated mistakes become checks (design)

When an agent breaks the same rule again and again, a prose rule is not
enough. Memory should notice the repeat and point to a check that makes the
mistake impossible. The order to try: change the code, then a type, then a
lint whose message names the fix, then a test, and docs last.

- **Record a repeat** as a `lesson` fact with the tag `hit` and a `related`
  link to the rule. `memory hit RULE_ID "what happened"` is a short form. No
  schema change, no edit in place.
- **Find repeats with no model:** a new fact that repeats a rule; a refused
  commit message (count days, not tries); `memory check --rules`, which scans
  `git log` for the commit rules; a hook or CI line that names a rule id; a
  rule whose `enforced_by` check is gone.
- **Propose a check.** A rule with 3 hits on 3 days and no `enforced_by` gets a
  `memory tidy` proposal. It names a layer from what the project has (a lint,
  a test folder, a hook). It never picks the check. When the check exists, a
  second proposal sets `enforced_by`.
- **Filler in a diff is not solved.** Only plain signals count: a diff that
  changes only comments, `TODO` and placeholder markers in added lines, and
  what Ruff or Biome report.

The measure: for each rule, hits per week fall after its check lands.

## Evaluation

Built, in [benchmarks/](benchmarks/README.md):

- `benchmarks/retrieval_eval.py` scores `memory search` (any@1, any@5, all@5,
  stale and decoy rates) and `memory load` (is the answer inside the word
  budget, and do stale facts leak in). It compares against the old strict
  match, a keyword count, newest-first and random baselines, with control
  rankers that prove the harness can tell good from bad, splits by probe kind,
  and a paired bootstrap interval.
- A made-up coding project with 101 active facts, 58 questions and 10 word
  fragments, hand-labelled, with stale and decoy facts. It runs in a few
  seconds, in the test suite.

Not covered:

- Raw-source baseline for the retrieval benchmark. A recent paper (arXiv
  2610.34073, "memory tax") reports that many agent-memory systems score
  below plain retrieval over the raw history on LongMemEval, PersonaMem and
  MINT-Eval, because building the memory drops or distorts facts. Retrieving
  from the raw history alongside the memory and reranking both together cut
  the tax. We have not checked that cairnkit fact search beats searching the
  raw sources. Plan, later: extend `benchmarks/retrieval_eval.py` with a
  plain keyword/BM25 baseline over the repo docs, git log and PR text;
  compare it with fact search and with the two merged. If the baseline wins,
  add an "also search the sources" fallback to `memory search`. The paper's
  benchmarks are chat-history recall, so the result may not transfer, and
  the numbers here are from the paper's summary, not checked by us.
- End-to-end agent runs, with and without `memory load`. The benchmark never
  asks a model anything, so it does not show that an agent does better work.
- A per-prompt recall hook (inject a few notes for each prompt). `memory load`
  ignores the question, so the load numbers only say whether the standing set
  already holds the answer.
- Real project notes. The fixture is synthetic, small and written by one
  author, and the questions are not held out.
- Stale facts. A stale fact that nobody superseded ranks above its newer
  replacement in most cases on the fixture (5 of 6). It needs a design, for
  example to demote a fact that a newer `similar_to` fact replaces.
- Word endings such as `-ed` and `-ing` (`retried`, `retry`), and questions
  that share no word with the answer (`rollout`, `rolling`). Try a change only
  with questions that were not used to build it.
- Rule adherence, from git history and hooks.
- Hygiene: active count, duplicates, stale facts, load size against the
  budget, and the accept rate of tidy proposals.
- Use: facts loaded, searched, never used, and marked wrong.

## Trust of stored notes

- Rules written by an agent load outside the data frame. List each one that
  has no basis `told` for review, and end it when it does not hold. This needs
  a way to mark a rule as reviewed.
- `told` is claimed by the writer, so an agent can claim it. Real proof needs
  the hook to record the person's own words.
- `memory change --status wrong` by an agent on a `told` fact is not guarded.

## Rule presets

- Presets of your own that the tool finds by itself, for example in
  `~/.config/cairnkit/presets/*.toml`.
- Mark a preset rule enforced or advisory again when a hook or CI job is added
  or removed later. Today only the commit-msg guard does this.
- More toolchains for detection, for example pytest, Go and Rust.
- Tool-neutral skill files in a preset, in plain steps that any agent can
  follow. Copy no third-party text unless its license allows it (no AGPL or
  GPL, no revenue cap). Credit any copied text in
  [THIRD-PARTY.md](THIRD-PARTY.md).

## Known limits of `memory update`

None of these breaks a normal update by one person on one computer.

- Two updates that overlap and find the same new commit: the second one waits,
  then installs the same commit again.
- An `ssh` URL can still ask for a key passphrase. A key in `ssh-agent` or the
  keychain works.
- The fallback fetch for a server that refuses a commit id goes 100 commits
  deep.

## Other ideas

- Generated views: `views/active.md` and `views/history.md`.
- A merge check: fail while `branches/<branch>.md` exists for a merged branch.
- A `--json` output for `load` and `search`.
- Embeddings, only if a test shows that word search is not enough.
- Model setup per agent, written to an ignored file such as `CLAUDE.local.md`.
