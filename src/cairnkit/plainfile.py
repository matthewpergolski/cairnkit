"""Read or write a file of a project or of the memory folder. It can be a pipe or a device.

The open of a pipe waits for the other end, and none comes, so `mkfifo CLAUDE.md` made
`memory status` wait for ever, and a pipe at `.auto-tidy-state.json` did the same to each
session start. A read of a device such as /dev/zero never ends. So each open here uses
O_NONBLOCK, and only a regular file is read or written. A caller that must not read a big
file gives a `limit`. For a regular file the result is the same as `Path.read_text`,
`Path.read_bytes`, `Path.write_text`, `Path.write_bytes` or `Path.open`.
"""

from __future__ import annotations

import io
import os
import stat
from pathlib import Path
from typing import IO, TextIO

_NONBLOCK = getattr(os, "O_NONBLOCK", 0)
_FLAGS = os.O_RDONLY | _NONBLOCK | getattr(os, "O_BINARY", 0)
_WRITE = os.O_WRONLY | os.O_CREAT | _NONBLOCK | getattr(os, "O_BINARY", 0)
_NO_LINK = getattr(os, "O_NOFOLLOW", 0)


def through_link(root: Path | str, path: Path | str) -> bool:
    """True when the path, or a folder between root and it, is a link, or the path is not under
    root. A write or a delete there could land in a tracked file or outside root."""
    try:
        parts = Path(path).relative_to(root).parts
    except ValueError:
        return True
    return any(Path(root, *parts[:end]).is_symlink() for end in range(1, len(parts) + 1))


class NotPlain(OSError):
    """Not a regular file (a pipe, a device, a folder or a socket), or bigger than the limit."""


def open_fd(path: Path | str, follow: bool = True) -> int:
    """An open file descriptor of a regular file. With follow=False, a link is refused."""
    fd = os.open(path, _FLAGS | (0 if follow else _NO_LINK))
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            raise NotPlain(f"not a regular file: {path}")
    except BaseException:
        os.close(fd)
        raise
    return fd


def read_fd(fd: int, limit: int | None = None) -> bytes:
    """The bytes of an open regular file, at most `limit` (None: all). It closes fd."""
    with os.fdopen(fd, "rb") as fh:
        if not stat.S_ISREG(os.fstat(fh.fileno()).st_mode):
            raise NotPlain("not a regular file")
        data = fh.read(None if limit is None else limit + 1)
    if limit is not None and len(data) > limit:
        raise NotPlain(f"bigger than {limit} bytes")
    return data


def read_bytes(path: Path | str, limit: int | None = None, follow: bool = True) -> bytes:
    return read_fd(open_fd(path, follow), limit)


def read_text(
    path: Path | str,
    encoding: str | None = None,
    errors: str | None = None,
    limit: int | None = None,
    follow: bool = True,
) -> str:
    """As `Path.read_text`, with its line ends: each \\r\\n and \\r reads as \\n."""
    data = read_bytes(path, limit, follow)
    with io.TextIOWrapper(io.BytesIO(data), encoding=encoding, errors=errors) as text:
        return text.read()


def open_text(path: Path | str, encoding: str | None = None, errors: str | None = None) -> TextIO:
    """As `Path.open` for reading text."""
    return open(open_fd(path), encoding=encoding, errors=errors)


def open_write_fd(
    path: Path | str,
    append: bool = False,
    follow: bool = True,
    new: bool = False,
    perms: int = 0o666,
) -> int:
    """An open file descriptor to write a regular file, made when it is missing.

    The open does not wait: a pipe with no reader fails with ENXIO, and a pipe with a reader, a
    device or a folder is refused before a byte is written. Without append the file is emptied,
    after that check. With new=True a file that exists is refused (FileExistsError).
    """
    flags = (
        _WRITE
        | (os.O_APPEND if append else 0)
        | (0 if follow else _NO_LINK)
        | (os.O_EXCL if new else 0)
    )
    fd = os.open(path, flags, perms)
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            raise NotPlain(f"not a regular file: {path}")
        if not append:
            os.ftruncate(fd, 0)
        if _NONBLOCK:
            os.set_blocking(fd, True)
    except BaseException:
        os.close(fd)
        raise
    return fd


def open_write(
    path: Path | str,
    mode: str = "w",
    encoding: str | None = None,
    errors: str | None = None,
    follow: bool = True,
    new: bool = False,
    perms: int = 0o666,
) -> IO:
    """As `Path.open` with mode "w", "a", "wb" or "ab"."""
    fd = open_write_fd(path, "a" in mode, follow, new, perms)
    return open(fd, mode, encoding=encoding, errors=errors)


def write_text(
    path: Path | str, data: str, encoding: str | None = None, errors: str | None = None
) -> int:
    """As `Path.write_text`."""
    with open_write(path, "w", encoding=encoding, errors=errors) as fh:
        return fh.write(data)


def write_bytes(path: Path | str, data: bytes) -> int:
    """As `Path.write_bytes`."""
    with open_write(path, "wb") as fh:
        return fh.write(data)
