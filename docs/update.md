# Updating memory

`memory update` installs the newest `memory` from the place you installed it
from. You do not reinstall by hand.

## What it does

It runs five steps and shows each one in the terminal:

1. **Check.** It finds the source and reads its newest commit and version.
2. **Fetch.** It makes a fixed copy of the checked commit in a temporary
   folder. A local git folder uses `git archive`. A git URL fetches that
   commit by id. When the server refuses a commit by its id and the check
   chose a release tag, it fetches `refs/tags/<name>`. When the server still
   refuses, it fetches the last 100 commits of each branch. Any other fetch
   error stops it.
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

It prints the old and the new version. When the source moved on, it also
prints the commit subjects between the installed ref and the new one (for a
local git folder), or a GitHub compare URL (for a GitHub git URL). On a
failure it stops, exits 1 and says how to fix it. When nothing is newer, it
says "Already up to date" and changes nothing. So it is safe to run twice.

- `memory update --check` only says whether an update exists.
- `memory update --dry-run` runs the check and lists the other steps.
- `memory update --source PATH|URL` sets the source, for example on the first
  run when uv has no record of it.
- `memory update --channel stable|dev` chooses what a git install follows. See
  [Channels](#channels).
- `memory status` prints the version, the installed short commit (when known),
  the source, the channel of a git install, and the update lines. When a newer
  commit exists, it also lists the commit subjects between the installed ref and the
  new one, or a GitHub compare URL when subjects are not available locally.

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

## Channels

A git install follows one channel.

- `stable` takes the highest release tag. This is the default.
- `dev` takes the newest commit of the `dev` branch.

`memory update --channel dev` saves the choice in `~/.config/cairnkit/channel`
(`$XDG_CONFIG_HOME/cairnkit/channel` when that is set), and then it installs from
that channel. The install can be a lower version. `memory update --channel stable`
goes back in the same way. A change of channel clears the recorded commit and the
cached check. With `--check` or `--dry-run`, the command does not save the channel.

An install pinned to `@dev` (`uv tool install git+URL@dev`) follows the `dev` branch
with no saved choice. A saved choice wins over a pin. A local folder has no channel:
it takes the current commit of that folder.

### From stable back to dev

The highest release tag can be older than `--channel`. The code of v0.3.1 has no
`--channel`, so after `memory update --channel stable` lands there,
`memory update --channel dev` stops with `unrecognized arguments: --channel dev`. A
dev build says this when it installs such a version. Use one of these two ways:

```sh
# dev is on the remote
uv tool install --force --reinstall git+URL@dev
memory update --channel dev

# dev is only in a local folder: a clean checkout of dev
memory update --source FOLDER
```

The first way needs the second command too, because a saved `stable` wins over the pin.
Until the `dev` branch is on GitHub, only the local folder way works from a GitHub
install. After the folder way, `memory update --source URL --channel dev` follows the
remote again.

`memory update --source URL` from a dev build also takes the highest release tag. This
is a roll back, and the version number can stay the same: `memory updated: 0.3.1 ->
0.3.1 (d523c01)`. To see what you run, read `memory --version`. It prints `memory 0.3.1`
for a release, `memory 0.3.1 (dev @e1bd5b2)` on dev, and `memory 0.3.1 (folder @1941435)`
for a local folder.

### After a roll back to 0.3.1

Run `memory init --refresh` and `memory hooks install` in each repo with the older tool.
Each of these from a dev build reads and commits under 0.3.1, and each works when you return
to dev: `repairs.jsonl`, `author`, `branch_tip`, `.identity`, `.write.lock`, a masked word,
and the tombstone of `memory purge line-HASH`.

Two things stop a commit under 0.3.1, because 0.3.1 cannot read them. Dev cannot change this,
because only `memory purge` may rewrite a fact file:

- A torn line stops each commit under 0.3.1, with or without a repair. `memory repair` settles
  it for dev only. Remove the line by hand to commit under 0.3.1.
- A dev build from before `repairs.jsonl` wrote a `repair` record, and one from before the fix
  wrote a change with only a `branch_tip`. Each stops a commit under 0.3.1. Neither holds a fact,
  so remove the line by hand. Dev no longer writes them.

## How it knows a newer version exists

On the `dev` channel, a commit of the `dev` branch that is not the recorded commit is
newer. The rest of this section describes the `stable` channel and a local folder.

The source is newer when its version is higher. It is also newer when its
commit is not the recorded commit: for a local git folder, the recorded
commit must come before the new one. A folder without git has no commit. A hash of
its files stands in for it. Links that stay inside the folder count. Links
that leave it, dot files, caches, builds and logs do not. It does not read
`.gitignore`.
For a git URL, `ls-remote --tags` chooses the highest strict `vX.Y.Z` or
`X.Y.Z` release (not `v1`, not `2024`, not four-part tags). That tag's
commit is the commit that gets installed, even when `HEAD` has moved on.
The install record stores `git+<url>@<tag>`. When the remote has no release
tag, `ls-remote HEAD` supplies the commit and the record stores `git+<url>`
with no tag. A uv receipt can pin the installed rev with `?rev=`,
`#<commit>`, or `@ref`. The check strips that pin and talks to the clean
remote. The `Source:` line still shows the old pin. A trailing `.git` on
the record or the receipt does not clear the recorded commit.
Without a recorded commit, only the version compare counts. With a recorded
commit, a different commit still counts as newer when the version matches.
An older release tag is not an update. Without a record, only the version
counts. The first `memory update` then installs again, to write the record.

A tag-pinned `uv tool install` of 0.3.0 stores `?rev=v0.3.0` in the receipt.
That build of `memory update` cannot strip the pin, so the check exits 1.
`uv tool upgrade` also leaves the pin. Install the fixed release by hand:

```text
uv tool install --force --reinstall git+https://github.com/matthewpergolski/cairnkit@v0.3.1
```

Use the next release tag once it exists. After that, `memory update` works.

`memory status` shows one line when the source is newer. A load shows it once per
version pair. The answer is cached for a day. A local folder is read with local git
only. A git URL is checked in the background, so the session start never
waits. Offline, the line does not show.

## Repo files

`memory` writes some files into a repo: the rules block, the agent hooks and
the git hooks. It records its version in the memory folder
(`tool-version.json`) when it writes them.

When the tool is newer than that version, `memory status` and the session
start show one line: run `memory init --refresh`. They show the same line
when the local post-merge hook holds a cairnkit block that either lacks
`# cairnkit:docs-check` or lacks `docs --check`, even when the recorded
version matches. The agent runs the refresh. That command rewrites these
files in place. It replaces the rules block between its markers and never
adds a second block. It only touches files that already hold memory's text.

The line compares version numbers, and it also reads that post-merge block.
A release that changes these files raises the version in `__init__.py`.
`pyproject.toml` reads that file. The docs-check stanza does not raise the
version. Refresh reads `# cairnkit:docs-check` in the hook instead. A test
checks that `pyproject.toml` reads the version from `__init__.py`, and that
`docs/FORMAT.md` names that same version.

`memory init --refresh` rewrites a hook that is already there. It writes every event
of a connected agent again, so a new event arrives by itself. It does not add a
missing git hook, and it does not connect a new agent tool. `memory init` does both,
and a second run changes nothing.

## From 0.3.1

An install on 0.3.1 catches up by itself. These steps need no person:

- `memory init --refresh`, which the session start asks the agent to run, removes
  the `post-commit` block. `memory init` and `memory hooks install` remove it too.
- The next session start ends each fact that the 0.3.1 commit miner wrote, as
  `expired`, with a line in `auto-tidy.log`. It keeps a pinned fact, a rule, and a
  fact with basis `told`. The archive keeps each ended fact. It also removes
  `proposals/auto-candidates.jsonl`, `proposals/stale-pending.md` and the lock files
  of the miner.
- A short-term note with an `expires_at` that the old 14-day default wrote still ends
  on that date. A new `--short` note has no date.

These stay, because the tool writes no tracked file and removes none:

- tracked hooks in `.githooks/` that `--commit-msg-guard=shared` wrote;
- a pointer line in `AGENTS.md` that `--write-instructions` wrote;
- lines in a tracked `.gitignore` that `--gitignore` wrote.

Remove them by hand if you do not want them. With `core.hooksPath` set to `.githooks`,
the tool writes no file there. Git 2.54 or newer runs the personal hooks beside that folder.

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
- The user cache moves from `~/.cache/project-memory/` to `~/.cache/cairnkit/`.
  Delete the old folder after you remove the old tool.

## What it never does

- It never updates every repo at once. Each repo catches up the next time
  it is used.
- It never changes the source folder.
- It never installs during a session start. The session start only shows the
  line.
- It never installs when the build fails.
