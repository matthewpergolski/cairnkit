# Updating memory

`memory update` installs the newest `memory` from the place you installed it
from. You do not reinstall by hand.

## What it does

It runs five steps and shows each one in the terminal:

1. **Check.** It finds the source and reads its newest commit and version.
2. **Fetch.** It makes a fixed copy of the checked commit in a temporary
   folder: `git archive` for a local git folder. For a git URL it fetches
   only that commit. When the server refuses a commit by its id, it fetches
   the last 100 commits of each branch. Any other fetch error stops it.
   When it cannot get the commit, it stops, says why, and installs nothing.
   Run `memory update` again: it checks the remote again.
3. **Build.** It builds a wheel from that copy. When the build fails, the
   installed tool does not change.
4. **Install.** It installs that wheel with `uv tool install --force
   --reinstall`. So the installed code is the checked commit, even when the
   source changes during the update. The wheel stays in the user cache
   (`~/.cache/cairnkit/wheels/`, one folder per uv tool environment),
   because the uv receipt points to it. Cleanup never removes the wheel that
   the receipt names.
5. **Verify.** It runs the new `memory --version`.

Only one update runs at a time. An update holds a lock
(`~/.cache/cairnkit/wheels/update.lock`) from the check to the end. A
second update says that it waits. Then it checks the source itself, so it
never installs an older commit last. After 5 minutes it stops and installs
nothing. `--check` and `--dry-run` take no lock. Windows has no lock.

It prints the old and the new version. On a failure it stops, exits 1 and
says how to fix it. When nothing is newer, it says "Already up to date" and
changes nothing. So it is safe to run twice.

- `memory update --check` only says whether an update exists.
- `memory update --dry-run` runs the check and lists the other steps.
- `memory update --source PATH|URL` sets the source, for example on the first
  run when uv has no record of it.
- `memory status` prints the version, the source and the update lines.

On a terminal the steps show as one progress bar. Piped output shows one
plain line per step. `NO_COLOR` turns off color.

## Where it is installed from

The source is a local folder or a git URL. The usual source is the GitHub
URL from the README: `git+https://github.com/matthewpergolski/cairnkit`.

`memory update` finds the source in this order:

1. `--source`.
2. The uv receipt, `uv-receipt.toml` in the tool's uv environment. uv writes
   it at `uv tool install`. After `memory update`, the receipt points to the
   built wheel, not to a source. Then the record gives the source.
3. Its own install record, `cairnkit-install.json` in the same
   environment. `memory update` writes it after each install. It holds the
   source, the commit and the version. A record for another source or
   another version does not count.

A local folder must have no uncommitted changes. `memory update` never
changes the source folder. To get newer commits, update that folder first,
for example with `git pull`.

## How it knows a newer version exists

The source is newer when its version is higher. It is also newer when its
commit is not the recorded commit: for a local git folder, the recorded
commit must come before the new one. A folder without git has no commit. A hash of
its files stands in for it. Links that stay inside the folder count. Links
that leave it, dot files, caches, builds and logs do not. It does not read
`.gitignore`.
Without a record, only the version counts. The
first `memory update` then installs again, to write the record.

`memory status` and the session start show one line when the source is
newer. The answer is cached for a day. A local folder is read with local git
only. A git URL is checked in the background, so the session start never
waits. Offline, the line does not show.

## Repo files

`memory` writes some files into a repo: the rules block, the agent hooks and
the git hooks. It records its version in the memory folder
(`tool-version.json`) when it writes them.

When the tool is newer than that version, `memory status` and the session
start show one line: run `memory init --refresh`. The agent runs it. That
command rewrites these files in place. It replaces the rules block between its markers and never
adds a second block. It only touches files that already hold memory's text.

This line compares version numbers. So a release that changes these files
must raise the version in `pyproject.toml` and `__init__.py`. A test checks
that the two match.

`memory init --refresh` rewrites a hook that is already there. It does not
add a missing hook. `pre-push` and `post-merge` are new. After you update,
run `memory hooks install` in each repo. That adds the new hooks. A second
run changes nothing.

## From project-memory to cairnkit

The tool was named `project-memory`. Its Python package was `project_memory`.
The memory folder (`<repo>.memory`), the `memory-bank` link and the `memory`
command keep their names.

- An install from before the rename cannot update itself: its old
  `memory update` asks uv for the old package name, and uv refuses the new
  wheel. It stops and installs nothing. Its message names the old source:
  do not use an old git URL, because that installs the old package.
- The agent hooks and git hooks that the old tool wrote call the old uv
  environment's Python with `-m project_memory`. That old code never prints
  the refresh line. So these repos do not catch up by themselves.

Move to cairnkit in this order:

1. Install cairnkit:
   `uv tool install --force --reinstall git+https://github.com/matthewpergolski/cairnkit`.
   It goes into a new uv environment beside the old one, and the `memory`
   link now runs cairnkit. (A local folder works too, if it holds the
   cairnkit source.)
2. In each repo that used the old tool, run `memory init --refresh`. It
   rewrites the agent hooks and git hooks to call the new tool. Until then,
   those hooks still run the old tool.
3. Then remove the old tool: `uv tool uninstall project-memory`. The
   uninstall also removes the `memory` link, so run the install command of
   step 1 again. A repo that you did not refresh now has hooks that point to
   a deleted Python: run step 2 there.

A newer `memory update` that runs in the old uv environment reads the old
receipt and the old install record. It installs `cairnkit` in a new uv
environment and prints steps 2 and 3.

What changes in the repo files and the cache:

- `memory init --refresh` finds the blocks and hooks of the old name and
  replaces them in place: the rules block (`<!-- project-memory:start -->`),
  the git hook block (`# >>> project-memory >>>`) and agent hooks that run
  `-m project_memory hook`. It never adds a second block. An old block and a
  new block in one file are refused: fix that file by hand.
- `memory init --refresh` does not touch the tidy rules block
  (`<!-- project-memory:rules:start -->`). The next `memory tidy --apply`
  that adds a rule to it gives it the new markers in place.
- The user cache moves from `~/.cache/project-memory/` to `~/.cache/cairnkit/`.
  Delete the old folder after you remove the old tool.

## What it never does

- It never updates every repo at once. Each repo catches up the next time
  it is used.
- It never changes the source folder.
- It never installs during a session start. The session start only shows the
  line.
- It never installs when the build fails.
