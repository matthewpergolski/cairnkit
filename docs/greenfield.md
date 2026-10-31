# Greenfield: a project with no agent memory yet

Use this guide for a new project, or for a project with no memory folder,
no agent hooks and no agent rules.

## Steps

1. Install the tool once on your computer:
   `uv tool install git+https://github.com/matthewpergolski/cairnkit`.
2. Go to the project: `cd my-app`.
3. Optional: look at the plan first with `memory init --dry-run`.
4. Run the one setup step: `memory init`.
   - It makes `../my-app.memory/`, links it as `memory-bank` in each checkout
     and worktree, and adds the ignore lines to `.git/info/exclude`.
   - It connects each agent tool that it finds. The adapter files stay untracked.
   - It adds personal git hooks: `pre-commit`, `post-checkout`, `pre-push` and
     `post-merge`. They stay in this clone. They are not committed. A teammate never
     runs them.
   - It prints a short result. `--verbose` prints each step. `--no-hooks` skips the
     agent tools and the git hooks.
   - It adds no rule facts. The rules about memory itself ship inside the
     tool. To add the commit rules (no AI co-author trailers, no "Generated
     with" footers, no claims that a model wrote a change), run
     `memory init --preset commits`. That also installs the commit-msg guard.
   - For a codebase, use `memory init --preset dev`. It adds the commit rules
     and rules for checks, tests, small diffs, git and lock files. It adds no
     rule for one tool. Put such rules in `CLAUDE.md` (or `AGENTS.md`, if that is
     what the repo has).
     For a folder of documents, use `--preset basic`. Look first with
     `memory preset show dev --detect`. See [presets.md](presets.md).
5. If you use Codex, approve the hooks once with `/hooks`. Codex asks for this trust
   step itself, and `memory init` says so. Other agents need no step.
6. If the tool does not find your agent, run `memory hooks install --agent NAME`.
   `NAME` is `claude`, `codex`, `cursor`, `grok`, `pi` or `opencode`. For any other
   agent, `memory hooks install --agent generic` prints the commands to connect by
   hand.
7. Check: `git status` shows nothing new. Run `memory check`. It must say `ok`.
8. Start an agent session. The agent gets the memory at the start, and it
   records facts as it works.

You have nothing more to do. Rule facts load first in every session. Auto-tidy
retires exact and near repeats and ended short-term notes at each session start, and
also after a push or a merge (see `auto-tidy.log`). The first sessions only report. A
push does not count as a session start. Similar pairs and other judgment cases go to
the agent as a task (`proposals/tidy-followups.md`).

Run `memory init` again after you install a new agent tool or add a worktree. It
connects what is new, and a second run changes nothing else. These are
[known gaps](../README.md#where-it-falls-short-today).

## Where does each rule go

| What | Where | Who sees it |
|---|---|---|
| 1. **Personal rules for every project you work on.** Example: never add model self-attribution or AI co-author trailers to commits. | The agent tool's user-level rules file, in your home folder, outside any repo. | You, in all projects. |
| 2. **Team or project rules.** | Hand-written tracked `CLAUDE.md` (or `AGENTS.md`), or the tool's tracked project rules file. cairnkit never puts its marked block here. | Everyone who clones the project. |
| 3. **cairnkit rules block and local details for this checkout.** | `CLAUDE.local.md` and untracked harness copies (`memory init --write-instructions`), kept out of git. | You, in this project. |
| 4. **Things learned while working.** | Memory facts (`memory add`). A fact that must load in each session uses `--pinned`. | You and your agents, in this project. |

The tool moves no fact from row 4 into a rules file. A person or an agent can write a
test, a hook or a line in a rules file, and then mark the fact `promoted`.

**A rule that a tool checks is better than a note anywhere.** A note can be
missed. A check cannot. Example: the commit-msg guard refuses a commit whose
message has a `Co-authored-by:` line that names an AI tool. Write a test, a
lint rule or a hook when you can, and keep the note as the reason.
Then mark the rule: `memory change ID --enforced-by TYPE:VALUE`.
`memory check --advisory` lists the rules that are still notes only.
