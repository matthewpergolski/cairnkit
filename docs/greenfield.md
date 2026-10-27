# Greenfield: a project with no agent memory yet

Use this guide for a new project, or for a project with no memory folder,
no agent hooks and no agent rules.

## Steps

1. Install the tool once on your computer:
   `uv tool install git+https://github.com/matthewpergolski/cairnkit`.
2. Go to the project: `cd my-app`.
3. Look at the plan first: `memory init --dry-run`.
4. Make the memory: `memory init`.
   - It makes `../my-app.memory/`, links it as `memory-bank` in each checkout
     and worktree, and adds the ignore lines to `.git/info/exclude`.
   - It adds no rule facts. The rules about memory itself ship inside the
     tool. To add the commit rules (no AI co-author trailers, no "Generated
     with" footers, no claims that a model wrote a change), run
     `memory preset add commits`.
   - For a codebase, use `memory init --preset dev`. It adds the commit rules
     and rules for checks, tests, small diffs, git and lock files. It adds no
     rule for one tool. Put such rules in `CLAUDE.md` (or `AGENTS.md`, if that is
     what the repo has).
     For a folder of documents, use `--preset basic`. Look first with
     `memory preset show dev --detect`. See [presets.md](presets.md).
5. Connect the agent tool and git: `memory hooks install`.
   - Add `--agent claude`, `codex` or `cursor` when the tool is not found.
   - This also adds personal `pre-push` and `post-merge` hooks. They tidy
     the memory after a push or a merge. They stay in this clone. They are
     not committed. A teammate who does not use cairnkit never runs them.
     A teammate who does has a separate memory and separate hooks. The two
     do not conflict.
6. That is all for one person. Every session loads the memory at the start.
   Rule facts load first.
7. Check: `git status` shows nothing new. Run `memory check`. It must say `ok`.
8. Start an agent session. The agent gets the memory at the start, and it
   records facts as it works.
9. Exact duplicates and ended short-term facts leave the load by themselves at
   each session start, and also after a push or a merge (see `auto-tidy.log`).
   The first sessions only report. A push does not count as a session start.
   Similar pairs go to the agent as a task (`proposals/tidy-followups.md`). From
   time to time, run `memory tidy`, read the proposals for rule promotions and
   stale facts, and approve the ones you want with `memory tidy --apply ID ...`.

## Optional: share the rules with a team

Use this only when the team agrees to it. The memory stays the main place for
the rules.

- `memory instructions --write-instructions=shared` writes the rules block
  into the tracked `CLAUDE.md` (or the repo's `AGENTS.md`), between marker lines.
- `memory hooks install --commit-msg-guard=shared` writes tracked hooks in
  `.githooks/`. Commit them, and tell each clone to run
  `git config core.hooksPath .githooks` once. With that setting, git runs
  `.githooks/` and not `.git/hooks/`. The tracked `.githooks/pre-commit` runs
  the memory guard when the tool is installed, and does nothing when it is not.
  The tracked `.githooks/post-checkout` links a new worktree the same way.
  The tidy hooks are not in `.githooks/`. If you point `core.hooksPath` at
  `.githooks`, git does not run `.git/hooks`. Add the `pre-push` and
  `post-merge` blocks by hand if you still want tidy after a push or a merge.

## Where does each rule go

| What | Where | Who sees it |
|---|---|---|
| 1. **Personal rules for every project you work on.** Example: never add model self-attribution or AI co-author trailers to commits. | The agent tool's user-level rules file, in your home folder, outside any repo. | You, in all projects. |
| 2. **Team or project rules.** | The tracked `CLAUDE.md` (or `AGENTS.md`, if that is what the repo has), or the tool's tracked project rules file. The rules block goes here only when the team opts in. | Everyone who clones the project. |
| 3. **Personal details for this computer or this checkout.** Example: a local port, a path. | A local rules file that git ignores, for example `CLAUDE.local.md` (`memory init --write-instructions`). | You, in this project. |
| 4. **Things learned while working.** | Memory facts (`memory add`). | You and your agents, in this project. |

Durable facts from row 4 move to row 2, or into a test or a hook. They move
only through `memory tidy` proposals that you approve.

**A rule that a tool checks is better than a note anywhere.** A note can be
missed. A check cannot. Example: the commit-msg guard refuses a commit whose
message has a `Co-authored-by:` line that names an AI tool. Write a test, a
lint rule or a hook when you can, and keep the note as the reason.
Then mark the rule: `memory change ID --enforced-by TYPE:VALUE`.
`memory check --advisory` lists the rules that are still notes only.
