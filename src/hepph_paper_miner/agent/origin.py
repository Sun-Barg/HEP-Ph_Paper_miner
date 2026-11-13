"""Which code made a record: the commit it ran from, and whether that code had been changed.

The version names in a record (the tool texts, the prompt, the parser) say what a
model read. They say nothing about the loop, the record or the question file, and
nothing about whether the folder a command ran in was up to date. Two sets of runs,
one meant to come from changed code, carried the same names throughout, and only the
history of the repository showed that the same commit had made both. A record that
names its commit can be laid beside that history.
"""

from __future__ import annotations

import functools
import hashlib
import subprocess
from pathlib import Path
from typing import Any

_GIT_SECONDS = 10.0  # git answers these questions at once; this only ends a call that hangs
_UNKNOWN: dict[str, Any] = {"commit": None, "modified": None}


def _git(folder: Path, *arguments: str) -> bytes | None:
    """What git prints, or None when it cannot be asked or says no.

    As bytes: a file name in the answer need not be in the encoding of the console,
    and nothing here has to read one.
    """
    try:
        done = subprocess.run(
            ["git", "-C", str(folder), *arguments],
            capture_output=True,
            timeout=_GIT_SECONDS,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return done.stdout.strip() if done.returncode == 0 else None


def code_version(file: Path | None = None) -> dict[str, Any]:
    """The commit that `file` belongs to, and whether a kept file differs from that commit.

    `file` is this module unless a test says otherwise. "modified" is about the files
    the repository keeps: a run writes its public record into the folder, and a new
    file there is not a change to the code. Both values are None when there is nothing
    to ask: no git, no repository, or a copy of the code that merely lies inside some
    repository without being one of its files (an installed copy in a virtual
    environment, say).
    """
    return dict(_this_code() if file is None else _ask(file.resolve()))


@functools.cache
def _this_code() -> dict[str, Any]:
    # Asked once in a process: the code that runs is the code that was loaded, whatever
    # happens to the folder afterwards.
    return _ask(Path(__file__).resolve())


def _ask(file: Path) -> dict[str, Any]:
    folder = file.parent
    if _git(folder, "ls-files", "--error-unmatch", file.name) is None:
        return _UNKNOWN
    commit = _git(folder, "rev-parse", "HEAD")
    changed = _git(folder, "status", "--porcelain", "--untracked-files=no")
    if commit is None or changed is None:
        return _UNKNOWN
    return {"commit": commit.decode("ascii", "replace"), "modified": bool(changed)}


def file_digest(path: Path) -> str:
    """The SHA-256 of a file as it lies on the disk, for a record to name what was read."""
    return hashlib.sha256(path.read_bytes()).hexdigest()
