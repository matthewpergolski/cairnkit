"""A hook's git reads never write the index.

`git status` and `git diff` refresh the index when a file's stat data changed, and they take
`.git/index.lock` to do it. A hook kills a git call that runs past its time, and a killed git leaves
that lock, so the developer's next `git commit` fails. In one test run on a loaded machine, a commit
right after a session start failed with "index.lock: File exists".
"""

from __future__ import annotations

import os
import time

from conftest import git

from cairnkit.cli import main


def test_hooks_read_git_without_writing_the_index(repo, mem, capsys):
    (repo / "app.py").write_text("print(1)\n")
    git(repo, "add", "app.py")
    git(repo, "commit", "-q", "-m", "app")
    index = repo / ".git" / "index"
    # The same content with a new mtime: a status with optional locks rewrites the index.
    later = time.time() + 5
    os.utime(repo / "app.py", (later, later))
    before = index.stat().st_mtime_ns
    assert main(["hook", "session-start", "--agent", "generic"]) == 0
    assert main(["hook", "stop", "--agent", "generic"]) == 0
    assert index.stat().st_mtime_ns == before
