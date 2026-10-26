"""`memory update`: install the newest memory from its source, step by step.

Steps: check, fetch, build, install, verify. Fetch makes a fixed copy of the
checked commit. Install takes the wheel built from that copy, so the installed
code is the code that was checked. A failed build leaves the installed tool as
it was. When nothing is newer, it changes nothing.
"""

from __future__ import annotations

import contextlib
import hashlib
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
from pathlib import Path

from cairnkit import install_source as src
from cairnkit.install_source import Latest, SourceError
from cairnkit.progress import Progress
from cairnkit.skills import cache_dir

try:
    import fcntl
except ImportError:  # Windows: no lock, like store.locked
    fcntl = None

# What git prints when a server will not give a commit by its id.
REFUSED = (
    "not our ref",
    "unadvertised object",
    "couldn't find remote ref",
    "does not allow request",
)
FALLBACK_DEPTH = 100  # commits per branch; the checked commit was a tip minutes ago
BRANCHES = "+refs/heads/*:refs/remotes/origin/*"
LOCK_WAIT = 300.0  # seconds to wait for another update
LOCK_POLL = 0.2
AFTER = "Each repo catches up when it is next used. Its session start says what to run."


def _run(argv: list[str], timeout: float = 900) -> tuple[int, str]:
    """Run a command with no input. git gets an environment where it cannot prompt."""
    env = src.git_env() if argv[0] == "git" else None
    try:
        done = subprocess.run(
            argv,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
            stdin=subprocess.DEVNULL,
            env=env,
        )
    except subprocess.TimeoutExpired:
        return 1, f"{' '.join(argv)} took longer than {int(timeout)} s"
    except OSError as exc:
        return 1, str(exc)
    return done.returncode, (done.stdout + done.stderr).strip()


def _tail(text: str, lines: int = 15) -> str:
    shown = text.splitlines()[-lines:]
    return "".join(f"\n  {line}" for line in shown)


def run_update(flag: str | None, check: bool = False, dry_run: bool = False) -> int:
    bar = Progress()
    try:
        return _update(bar, flag, check, dry_run)
    except SourceError as exc:
        bar.fail()
        bar.close()
        sys.stdout.flush()
        print(f"error: {exc}\nFix: {exc.fix}", file=sys.stderr)
        return 1
    finally:
        bar.close()


def _update(bar: Progress, flag: str | None, check: bool, dry_run: bool) -> int:
    source, _ = src.installed(flag)
    if source is None:
        raise SourceError(
            "memory does not know where it was installed from.",
            "Run `memory update --source PATH` once. PATH is the folder or git URL "
            "you installed memory from.",
        )
    if source.editable:
        bar.say(f"memory runs in editable mode from {source.spec}. It runs that code already.")
        bar.say("Nothing to do.")
        return 0
    bar.say(f"Source: {source.label}")
    # A real update holds the lock from the check on: another update may install a
    # commit while this one waits, so this one must check after it gets the lock.
    # A check or a dry run changes nothing and never waits.
    with contextlib.nullcontext() if check or dry_run else _locked(bar):
        return _checked_update(bar, flag, check, dry_run)


def _checked_update(bar: Progress, flag: str | None, check: bool, dry_run: bool) -> int:
    source, commit = src.installed(flag)  # read again: an update may have just run
    old = src.current_version()
    bar.start("Check")
    found = src.latest(source)
    if source.kind == "folder" and src.dirty(Path(source.spec)):
        raise SourceError(
            f"{source.spec} has uncommitted changes.",
            "Commit or stash them in that folder. Then run `memory update` again.",
        )
    newer = src.is_newer(source, old, commit, found)
    bar.done()
    if not dry_run:  # a dry run changes no state, not even the cache
        src.save_check(source, old, commit, found, newer)
    before, after = src.describe(old, commit), src.describe(found.version, found.commit)

    if check:
        if newer:
            bar.say(f"Update available: {before} -> {after}. Run `memory update`.")
        elif commit:
            bar.say(f"Up to date ({old}).")
        else:
            bar.say(
                f"No newer version ({old}). No commit is recorded yet, so only the version counts."
            )
        return 0
    if not newer and commit:
        bar.say(f"Already up to date ({old}).")
        return 0

    uv = shutil.which("uv")
    if uv is None:
        raise SourceError(
            "uv is not on PATH.",
            "Install uv (https://docs.astral.sh/uv/). Then run `memory update` again.",
        )
    if dry_run:
        bar.say("Dry run: nothing will change.")
        bar.say(f"Update available: {before} -> {after}." if newer else "No newer version.")
        if source.kind == "git":
            fetch = f"git fetch {found.commit[:7]} from {source.spec}"
        elif src.is_git_folder(Path(source.spec)):
            fetch = f"git archive {found.commit[:7]} from {source.spec}"
        else:
            fetch = f"copy {source.spec}"
        bar.say(f"would fetch: {fetch}")
        bar.say("would build: uv build --wheel --out-dir TEMP the copy")
        bar.say("would install: uv tool install --force --reinstall the built wheel")
        bar.say("would verify: memory --version")
        return 0
    if not newer:
        bar.say("No commit is recorded yet. Installing again to record it.")

    with tempfile.TemporaryDirectory(prefix="memory-update-") as tmp:
        folder, found = _fetch(bar, source, found, Path(tmp))
        wheel = _build(bar, uv, folder, Path(tmp))
        _install(bar, uv, source, wheel)
        new = _verify(bar, source, found)
        src.write_record(source, found.commit, new)
        src.save_check(source, new, found.commit, found, False)
    arrow = "→" if bar.live else "->"
    short = f" ({found.commit[:7]})" if found.commit else ""
    bar.finish(f"memory updated: {old} {arrow} {new}{short}.")
    bar.say(AFTER)
    if src.tool_env().name == src.OLD_PACKAGE:
        # Old agent and git hooks call the old environment's Python, so each repo must
        # refresh before the old tool goes. The uninstall also removes the `memory` link.
        bar.say(
            f"The old tool {src.OLD_PACKAGE} is still installed. The hooks of repos that used "
            "it still run it. In each such repo, run `memory init --refresh` first. Then "
            f"remove the old tool: `uv tool uninstall {src.OLD_PACKAGE}`, then "
            f"`uv tool install --force --reinstall {source.install_spec}`."
        )
    return 0


def refuses_commit_id(output: str) -> bool:
    """True when git says the server will not give a commit by its id."""
    text = output.lower()
    return any(sign in text for sign in REFUSED)


def lock_path() -> Path:
    """The lock for every update that uses this wheel cache."""
    return cache_dir() / "wheels" / "update.lock"


@contextlib.contextmanager
def _locked(bar: Progress):
    """Hold an exclusive lock for the whole update. Wait for another update.

    Without fcntl (Windows) there is no lock, as in store.locked.
    """
    if fcntl is None:
        yield
        return
    path = lock_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as handle:
        deadline = time.monotonic() + LOCK_WAIT
        waiting = False
        while True:
            try:
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if not waiting:
                    bar.say("Another memory update is running. Waiting for it.")
                    waiting = True
                if time.monotonic() >= deadline:
                    raise SourceError(
                        "Another memory update still runs. Nothing was installed.",
                        "Wait for it to finish. Then run `memory update` again. "
                        f"The lock is {path}.",
                    ) from None
                time.sleep(LOCK_POLL)
            except OSError as exc:
                raise SourceError(
                    f"Could not lock {path}: {exc}.",
                    "Check that the cache folder can be written. Then run `memory update` again.",
                ) from exc
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def _fetch(bar: Progress, source, found: Latest, tmp: Path) -> tuple[Path, Latest]:
    """A fixed copy of the source to build from, and its commit and version."""
    bar.start("Fetch")
    folder = tmp / "source"
    if source.kind == "git":
        # Fetch just the checked commit. Only a server that refuses a fetch by commit
        # id gets a bounded fetch of its branches; any other failure stops here.
        code, out = _run(["git", "init", "--quiet", str(folder)], 60)
        fetch = ["git", "-C", str(folder), "fetch", "--quiet"]
        bounded = False
        if not code:
            code, out = _run([*fetch, "--depth", "1", source.spec, str(found.commit)], 300)
            if code and refuses_commit_id(out):
                bounded = True
                depth = ["--depth", str(FALLBACK_DEPTH)]
                code, out = _run([*fetch, *depth, source.spec, BRANCHES], 300)
        if code:
            raise SourceError(
                f"Could not fetch {source.spec}.{_tail(out)}",
                "Check the network and the URL. Then run `memory update` again.",
            )
        checkout = ["git", "-C", str(folder), "checkout", "--quiet", "--detach", str(found.commit)]
        code, _ = _run(checkout, 60)
        if code or src.git(["-C", str(folder), "rev-parse", "HEAD"]) != found.commit:
            short = str(found.commit)[:7]
            if bounded:
                # The server would not give the commit by its id, and the bounded
                # fetch of its branches did not reach it.
                what = (
                    f"The checked commit {short} could not be fetched from {source.spec}. "
                    "The server does not give a commit by its id, and it is not in the last "
                    f"{FALLBACK_DEPTH} commits of any branch. The remote moved on, or it "
                    "dropped the commit. Nothing was installed."
                )
            else:
                what = f"The checked commit {short} is no longer on {source.spec}. "
                what += "Nothing was installed."
            raise SourceError(
                what,
                "Run `memory update` again. It checks the remote again and installs its "
                "newest commit.",
            )
    elif src.is_git_folder(Path(source.spec)):
        archive = tmp / "source.tar"
        argv = ["git", "-C", source.spec, "archive", "--format=tar", "-o", str(archive)]
        code, out = _run([*argv, found.commit], 300)
        if code:
            raise SourceError(
                f"Could not copy commit {found.commit[:7]} from {source.spec}.{_tail(out)}",
                "Check that the folder is a git checkout. Then run `memory update` again.",
            )
        with tarfile.open(archive) as tar:
            tar.extractall(folder, filter="data")
    else:
        # No git: copy the files, and hash the copy, so the record matches the build.
        for rel in src.source_files(Path(source.spec)):
            (folder / rel).parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(Path(source.spec) / rel, folder / rel)
        found = Latest(src.content_id(folder), None)
    bar.done()
    return folder, Latest(found.commit, src.folder_version(folder))


def _build(bar: Progress, uv: str, folder: Path, tmp: Path) -> Path:
    bar.start("Build")
    dist = tmp / "dist"
    code, out = _run([uv, "build", "--wheel", "--out-dir", str(dist), str(folder)])
    wheels = sorted(dist.glob("*.whl")) if code == 0 else []
    if len(wheels) != 1:
        what = "The source did not build." if code else f"The build made {len(wheels)} wheels."
        raise SourceError(
            f"{what} The installed memory did not change.{_tail(out)}",
            "Fix the build in the source. Then run `memory update` again.",
        )
    bar.done()
    return wheels[0]


def wheels_dir() -> Path:
    """The kept wheels of this uv tool environment. Each environment has its own."""
    env = hashlib.sha256(str(src.target_env().resolve()).encode()).hexdigest()[:12]
    return cache_dir() / "wheels" / env


def _in_use(folder: Path) -> bool:
    """True when the uv receipt, read now, names a wheel in folder."""
    try:
        text = (src.target_env() / src.RECEIPT).read_text(encoding="utf-8")
    except OSError:
        return False
    return str(folder) in text or folder.as_uri() in text


def _install(bar: Progress, uv: str, source, wheel: Path) -> None:
    """Install the built wheel. Keep it, so that the uv receipt points to a file.

    Each try gets its own folder. The wheel of the current install stays until
    the new install works. A failed try leaves nothing behind.
    """
    bar.start("Install")
    kept_dir = wheels_dir()
    kept_dir.mkdir(parents=True, exist_ok=True)
    attempt = Path(tempfile.mkdtemp(prefix="install-", dir=kept_dir))
    kept = attempt / wheel.name
    shutil.copyfile(wheel, kept)
    install = [uv, "tool", "install", "--force", "--reinstall", f"{src.PACKAGE} @ {kept.as_uri()}"]
    code, out = _run(install)
    if code:
        shutil.rmtree(attempt, ignore_errors=True)
        raise SourceError(
            f"uv could not install memory.{_tail(out)}",
            f"Run `uv tool install --force --reinstall {source.install_spec}` to see the whole "
            "error.",
        )
    for old in kept_dir.iterdir():
        # Another update may have finished in between: keep what the receipt names.
        if old == attempt or _in_use(old):
            continue
        if old.is_dir() and not old.is_symlink():
            shutil.rmtree(old, ignore_errors=True)
        else:
            old.unlink(missing_ok=True)
    bar.done()


def _verify(bar: Progress, source, found: Latest) -> str:
    bar.start("Verify")
    entry = src.entrypoint()
    reinstall = f"uv tool install --force --reinstall {source.install_spec}"
    if entry is None:
        raise SourceError(
            "The new memory command was not found.",
            "Put the uv tool bin folder on PATH. `uv tool dir --bin` prints it.",
        )
    code, out = _run([entry, "--version"], 60)
    new = out.strip().removeprefix("memory").strip() if code == 0 else ""
    if not new or (found.version and new != found.version):
        expected = found.version or "its version"
        raise SourceError(
            f"The new memory did not report {expected}. It said: {out.strip() or 'nothing'}.",
            f"Run `{entry} --version` to see why. Then run `{reinstall}`.",
        )
    bar.done()
    return new


def run_status(project, flag: str | None) -> int:
    """The version, the source, and one line for each update that is due."""
    from cairnkit.refresh import repo_line

    source, _ = src.installed(None)
    print(f"memory {src.current_version()}")
    if source is None:
        print("Source: unknown. `memory update --source PATH` sets it.")
    else:
        print(f"Source: {source.label}" + (", editable" if source.editable else ""))
    print(src.update_line(background=False) or "No update found.")
    print(repo_line(project, flag) or "Repo files: current.")
    return 0
