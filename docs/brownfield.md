# Brownfield: a project that already has agent notes, hooks or rules

Use this guide for a project that already has a memory folder, agent hook
settings or agent rules files. The tool never replaces what you have. It
refuses, merges, or adds a marked block.

## Steps

1. Install the tool:
   `uv tool install git+https://github.com/matthewpergolski/cairnkit`.
2. Go to the project and look at the plan: `memory init --dry-run`.
3. **If you have a real `memory-bank` folder**, `memory init` refuses and
   lists the files. Use `memory migrate`. It folds the old notes into the new
   memory, and it deletes nothing.
   1. Run `memory migrate` (add `--preset dev` for a codebase). **It changes
      nothing.** It shows the plan: every step, and the counts of candidate
      facts. Read it. (`--dry-run` means the same and is kept for old
      scripts. `--dry-run` with `--yes` is refused.)
   2. Then run `memory migrate --yes` (with `--fix-references` to fix the
      old paths and hooks too). It does these steps in this order:
      1. Moves the old folder out of the repo, to `../my-app.memory-old`.
         It refuses when that folder exists. A worktree with its own old
         `memory-bank/` goes to `../my-app.memory-old.<worktree>`. It is
         not merged. The command says how many of its files differ.
      2. Runs `memory init` (the memory folder, the links, the presets).
      3. Copies every old file into `memory-bank/notes/`, with the same
         relative path. It never overwrites a note.
      4. Writes `memory-bank/proposals/migrate-candidates.jsonl`: one line for
         each bullet, numbered item or dated line of the old notes, with the
         file, the line and a suggested kind. It also counts lines in and
         lines out for each file. It writes no fact and calls no model.
         For each worktree's own old notes, the lines that the main notes do
         not have are added too. They have `tier: worktree-only`, a
         `from_worktree` name, and a `source` that points at the moved-aside
         file and line. The plan and the summary say
         `N worktree-only line(s) from <worktree>`.
         A line that `AGENTS.md`, `CLAUDE.md` or `CLAUDE.local.md` already
         holds, in the same words, outside the block that `memory` writes
         there, is left out: it has a home. The summary
         counts it in `in_instruction_files`, and the plan says
         `N candidate(s) skipped`.
      5. Finds the lines of your top-level and `docs/` `*.md` files that name
         the old layout, and writes the task for them (see step 7 below).
         It edits no rules file unless you pass `--fix-references`.
      6. Runs `memory check`.
   3. Turn the candidates into facts. An agent can do this step. Each
      candidate has a `source` to pass on:
      `memory add "..." --kind decision --area AREA --basis told --source file:memory-bank/notes/decisions.md:12`.
      Start with `"tier": "likely"` (decision, trap, lesson, event and brief
      lines). Most `maybe` lines (specs, how-to, roadmap) are better left as
      notes. A candidate with `hint: superseded` or `held_by` is history:
      add it, then `memory change ID --status superseded` or `--held-by`.
   4. If git tracked the old folder, `memory migrate` refuses and tells you.
      Add `--untrack` (with `--yes`). It removes the old files from the git index
      and commits nothing. Review `git status`, then commit.
   5. A rerun is safe. After a failure, run `memory migrate --yes` again: the old
      notes are always in the `.memory-old` folder, and each step skips what
      is done. When the old folder is not called `memory-bank`, use
      `--from DIR`. `--fix-references` and the follow-up task apply only to
      the `memory-bank` folder, so the command skips them with `--from`.
      A link inside the old folder is not copied. It stays in the
      `.memory-old` folder, and the command says how many. When `memory-bank`
      is a link to another folder, the command refuses and names the target.
   6. **Fix the references with the command, not by hand.**
      `memory migrate --fix-references` shows the plan, and
      `memory migrate --fix-references --yes` applies it. It does two things:
      1. It rewrites exact old paths in top-level `*.md` and `docs/**/*.md`:
         `memory-bank/status.md` becomes `memory-bank/notes/status.md`,
         `memory-bank/howto/x.md` becomes `memory-bank/notes/howto/x.md`. A
         path counts only when the old folder held that file or folder.
         Paths in code blocks and inline code move too. A path that is
         already in the new layout, or that has no target, is left alone.
         The plan says which files git tracks. The command edits the working
         tree only and commits nothing: review `git diff`. A second run
         changes nothing. The plan marks a tracked file that already has
         changes: `tracked by git, already modified`. Its `git diff` then
         shows your changes and the rewrite together.
      2. When a hook in an agent settings file runs the old checker (for
         example a `SessionStart` hook), it runs the `memory hooks install`
         logic for that agent: it adds the memory hooks next to the old one
         and removes nothing. A settings file that git tracks is left alone.
      It does not delete the old checker. It says the checker is now unused,
      and where it is still named.
   7. **What is left goes to an agent.** The command writes
      `memory-bank/proposals/migrate-followups.md` and prints its path. It is
      a task you can give to an agent as it is. For each line that needs
      judgment (an instruction like "run the old checker at session start",
      a doc about the old folder, a tracked hook) it gives `file:line`, why it
      is stale, and a suggested replacement. It ends with the exact check:
      a `grep` of the old names that must print nothing, and `memory check`.
      Until the task is done, `memory load` shows one line:
      `Migration follow-up pending: see memory-bank/proposals/migrate-followups.md`.
      When the agent is done, run `memory migrate --yes`. It marks the file
      done, and the line goes away.

   **By hand**, if you cannot use the command:
   1. Move the old folder out of the repo, for example
      `mv memory-bank ../my-app.memory-old`.
   2. Run `memory init`. It makes the new folder `../my-app.memory/` and the link.
   3. Copy the prose files (status, specs, how-to, runbooks) into
      `memory-bank/notes/`. Keep the old folder until you are sure.
   4. For each live decision, trap or lesson in the old notes, add one fact:
      `memory add "..." --kind decision --area AREA --basis told --source file:OLD_FILE`.
      An agent can do this step. Ask it to keep one fact per line of the old
      notes, and to give you the counts in and out.
   5. Run `memory check`. It must say `ok`.
   6. If `memory-bank/` was in git, remove it from the index:
      `git rm -r --cached memory-bank`, and commit.
4. **If you have agent hook settings**, run `memory hooks install --dry-run`,
   then `memory hooks install`.
   - Your hooks stay. The tool adds its own entries next to them.
   - A config file that git tracks is left alone. The tool prints the
     commands to add by hand, so you can agree on them with your team.
   - A file that is not valid JSON is refused. Fix it first.
5. **If you have rules files** (`AGENTS.md` or the tool's rules file), they do
   not change. You can add the rules block:
   - local only: `memory init --write-instructions` (writes `CLAUDE.local.md`,
     ignored by git);
   - shared, only when the team opts in:
     `memory instructions --write-instructions=shared` (a marked block in
     `CLAUDE.md`, or in `AGENTS.md` if that is the only one; text outside the
     markers stays as it is).
   Preset rules live in memory once you add them (`memory init --preset NAME`).
   You do not need either step for them to load.
   To add a preset to a memory that exists: `memory preset add dev --dry-run`,
   then `memory preset add dev`. It adds only the missing rules. It skips a
   rule that a person ended and a rule with the same text as one you have.
6. **If you have git hooks**, the tool adds a marked block after the first
   line of a shell hook and keeps the rest. It also adds personal `pre-push`
   and `post-merge` hooks. They run auto-tidy after a push or a merge.
   They stay in this clone. They are not committed. A teammate who does not
   use cairnkit never runs them. A teammate who does has a separate memory
   and separate hooks. The two do not conflict.
   When `core.hooksPath` points into the repo, the tool changes nothing and
   prints the block to add by hand. A team that wants a shared guard can opt
   in with `--commit-msg-guard=shared` (tracked hooks in `.githooks/`).
   That set does not include the tidy hooks.
7. Check: `git status`, `memory check`, then start an agent session.
8. Durable lessons move into the shared rules file only through `memory tidy`
   proposals that you approve.

To undo: `memory hooks uninstall` removes only what the tool added. The
memory folder stays. Delete it yourself if you want it gone.

See also [Where does each rule go](greenfield.md#where-does-each-rule-go).
