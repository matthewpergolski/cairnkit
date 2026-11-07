"""Read a file of a project or of the memory folder. It can be a pipe, a device or huge.

The open of a pipe waits for a writer, and none comes, so `mkfifo CLAUDE.md` made
`memory status` wait for ever. A read of a device such as /dev/zero never ends. So each read
here opens with O_NONBLOCK, reads only a regular file, and reads at most `limit` bytes. For a
regular file the result is the same as `Path.read_text` or `Path.read_bytes`.
"""

from __future__ import annotations

import io
import os
import stat
from pathlib import Path
from typing import TextIO

MAX_BYTES = 64 * 1024 * 1024
_FLAGS = os.O_RDONLY | getattr(os, "O_NONBLOCK", 0) | getattr(os, "O_BINARY", 0)
_NO_LINK = getattr(os, "O_NOFOLLOW", 0)


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


def read_fd(fd: int, limit: int | None = MAX_BYTES) -> bytes:
    """The bytes of an open regular file, at most `limit` (None: all). It closes fd."""
    with os.fdopen(fd, "rb") as fh:
        if not stat.S_ISREG(os.fstat(fh.fileno()).st_mode):
            raise NotPlain("not a regular file")
        data = fh.read(None if limit is None else limit + 1)
    if limit is not None and len(data) > limit:
        raise NotPlain(f"bigger than {limit} bytes")
    return data


def read_bytes(path: Path | str, limit: int | None = MAX_BYTES, follow: bool = True) -> bytes:
    return read_fd(open_fd(path, follow), limit)


def read_text(
    path: Path | str,
    encoding: str | None = None,
    errors: str | None = None,
    limit: int | None = MAX_BYTES,
    follow: bool = True,
) -> str:
    """As `Path.read_text`, with its line ends: each \\r\\n and \\r reads as \\n."""
    data = read_bytes(path, limit, follow)
    with io.TextIOWrapper(io.BytesIO(data), encoding=encoding, errors=errors) as text:
        return text.read()


def open_text(path: Path | str, encoding: str | None = None, errors: str | None = None) -> TextIO:
    """As `Path.open` for reading text."""
    return open(open_fd(path), encoding=encoding, errors=errors)
