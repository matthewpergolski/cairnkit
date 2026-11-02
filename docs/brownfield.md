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
      nothing.** It shows the plan: which checkout it acts on, every step, the
      counts of candidate facts, each check of the old tooling, and what the
      install step reaches. Read it. (`--dry-run` means the same and is kept for
      old scripts. `--dry-run` with `--yes` is refused.)
   2. Then run `memory migrate --yes`. It does these steps in this order:
      1. Moves the old folder out of the repo, to `../my-app.memory-old`.
         It refuses when that folder exists. A worktree with its own old
         `memory-bank/` goes to `../my-app.memory-old.<worktree>`. It is
         not merged. The command says how many of its files differ.
      2. Runs `memory init` (the memory folder, the links, the presets).
      3. Copies every old file into `memory-bank/notes/`, with the same
         relative path. It never overwrites a note. An old `notes/REL` stays
         `notes/REL`, and it wins over an old `REL`. A copy that lost goes to
         `memory-bank/proposals/old-copies/`, with a task item to compare them.
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
         A line that says what an earlier line or a stored fact says gets
         `tier: repeat` and `repeat_of`, by the test that `memory add` uses. The
         same words pass that test. Other words for the same rule do not.
      5. Finds the lines of your top-level and `docs/` `*.md` files that name
         the old layout, and writes the task for them (see step 6 below).
         It edits no project doc. An old path that a doc names, such as
         `memory-bank/status.md`, holds only a pointer to the note until no doc
         names it. A later text file outside `notes/` moves the same way, and
         `memory check` names it.
      6. Lists each check of the old checker, by name, once. It says what happens
         to each check now. It reads the script's text and does not run it.
      7. Runs `memory check`, then connects the agent tools and the git hooks, as
         `memory init` does, in the checkout where you ran it. It names that checkout,
         the checkouts it leaves alone, and the hook folder. With `--untrack`, it
         changes the index of that checkout only, and it prints the command for each other.
   3. Turn the candidates into facts, if you want them. This step is optional. It
      is not part of the end of the migration. An agent can do it. Each
      candidate has a `source` to pass on:
      `memory add "..." --kind decision --area AREA --basis told --source file:memory-bank/notes/decisions.md:12`.
      Start with `"tier": "likely"` (decision, trap, lesson, event and brief
      lines). Most `maybe` lines (specs, how-to, roadmap) are better left as
      notes. A candidate with `hint: superseded` or `held_by` is history:
      add it, then `memory change ID --status superseded` or `--held-by`.
   4. If git tracked the old folder, `memory migrate` refuses and tells you.
      Add `--untrack` (with `--yes`). It removes the old files from the git index
      and commits nothing. Review `git status`, then commit. The pre-commit hook lets a
      staged removal through. It still refuses a private path that is added or changed.
   5. A rerun is safe. After a failure, run `memory migrate --yes` again: the old
      notes are always in the `.memory-old` folder, and each step skips what
      is done. After the worklist exists, a rerun does not copy, scan or install.
      It reads the task again and prints what is left. When the old folder is not
      called `memory-bank`, use `--from DIR`. The references to the old folder apply
      only to `memory-bank`, so the command skips them with `--from`.
      A link inside the old folder is not copied. It stays in the
      `.memory-old` folder, and the command says how many. When `memory-bank`
      is a link to another folder, the command refuses and names the target.
   6. **An agent fixes the references.** The tool edits no project doc, because that
      would write a tracked file. The command writes
      `memory-bank/proposals/migrate-followups.md` and prints its path. It is
      a task you can give to an agent as it is. For each line it gives `file:line`,
      why it is stale, and a suggested replacement:
      - An old path, such as `memory-bank/status.md`. The suggestion is the same line
        with `memory-bank/notes/status.md`. A path counts only when the old folder
        held that file or folder.
      - A line that needs judgment, such as "run the old checker at session start", or
        a doc about the old folder.
      - A hook in an agent settings file that runs the old checker, or any other hook
        whose command or repo script names the old notes folder, such as a word search
        that runs at each prompt. The memory hooks are already next to it. The task says
        to remove the old handler, with the file and the line.
      - An older copy in `proposals/old-copies/`. The agent compares it with the note,
        carries over what is still true, and deletes the copy.

      `memory check` also names a text file that appears outside `notes/` later. A
      rerun of `memory migrate --yes` moves it into `notes/`. If `notes/` already holds
      other text at that path, the note stays and the file goes to
      `proposals/old-copies/`, with a task item. No text is lost. `memory migrate`
      prints the plan and changes nothing.

      The command does not delete the old checker. It says where the checker is still
      named. When the old checker and `memory check` disagree, believe `memory check`.
      Where a repo doc and `memory instructions` disagree about the memory,
      `memory instructions` wins. The rest of that doc still stands.
      While the task is open, `memory load` shows one line with the count, and
      `memory check` counts the open task as `to do`, and it does not say `ok`.

      **The migration has one end.** The agent runs `memory migrate --yes`. It reads each
      item again, in the checkout where it runs. A fix on a branch counts when the agent
      runs it there. With nothing left it prints `Migration finished.` and removes the
      task. The load then says nothing about it. If a line must stay, because the agent
      may not change a shared file or the line is history, the agent deletes the task.
      That also ends the migration, and a rerun does not bring it back.

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
4. **If you have agent hook settings**, `memory init` merges with them. To see the
   plan first, run `memory hooks install --dry-run`.
   - Your hooks stay. The tool adds its own entries next to them.
   - A config file that git tracks is left alone. The tool prints the
     commands to add by hand.
   - A file that is not valid JSON is refused. Fix it first.
5. **If you have rules files** (`AGENTS.md` or the tool's rules file), hand-
   written text stays. You can add the rules block with
   `memory init --write-instructions` (writes untracked `CLAUDE.local.md` and
   harness copies; it changes no tracked file, and it says so when a tracked file
   holds an old block).
   Preset rules live in memory once you add them (`memory init --preset NAME`).
   You do not need that step for them to load.
   To add a preset to a memory that exists: `memory preset add dev --dry-run`,
   then `memory preset add dev`. It adds only the missing rules. It skips a
   rule that a person ended and a rule with the same text as one you have.
6. **If you have git hooks**, the tool adds a marked block after the first
   line of a shell hook and keeps the rest. It also adds personal `pre-push`
   and `post-merge` hooks. They run auto-tidy after a push or a merge.
   They stay in this clone. They are not committed. A teammate never runs them.
   When `core.hooksPath` names a folder outside the repo's git folder, the local git
   config runs the hooks beside that folder (git 2.54 or newer). The tool writes no
   tracked hook, and nothing in a folder that other repos use.
7. Check: `git status`, `memory check`, then start an agent session.

To undo: `memory hooks uninstall` removes only what the tool added. The
memory folder stays. Delete it yourself if you want it gone.

See also [Where does each rule go](greenfield.md#where-does-each-rule-go).
