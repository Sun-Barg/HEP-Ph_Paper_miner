"""The files of the survey: one JSON object on a line, the first line saying what the file is.

The files name each other by their SHA-256 (the sample names the list it was drawn from,
the outcomes name the sample). So a file has to be the same bytes on every system: it
is written as bytes, with "\\n" at the end of a line also on Windows.
"""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Iterable, Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


class RecordError(ValueError):
    """A file of the survey that cannot be used as it is. The message says where."""


def now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def as_bytes(lines: Iterable[Mapping[str, Any]]) -> bytes:
    return "".join(json.dumps(line, ensure_ascii=False) + "\n" for line in lines).encode("utf-8")


def write_lines(path: Path, lines: Iterable[Mapping[str, Any]]) -> str:
    """Write the lines, all or nothing, and return the SHA-256 of the file.

    Written beside the target and renamed: a command that is stopped half way leaves the
    file that was there before, not the first half of a new one.
    """
    data = as_bytes(lines)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    temporary.write_bytes(data)
    os.replace(temporary, path)
    return hashlib.sha256(data).hexdigest()


def read_lines(path: Path, record: str) -> tuple[list[dict[str, Any]], str]:
    """The lines of a file whose first line says it is a `record`, and the file's SHA-256."""
    data = path.read_bytes()
    lines: list[dict[str, Any]] = []
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as error:
        raise RecordError(f"{path.name}: not UTF-8 text ({error})") from error
    for at, each in enumerate(text.splitlines(), start=1):
        if not each.strip():
            continue
        try:
            line = json.loads(each)
        except json.JSONDecodeError as error:
            raise RecordError(f"{path.name} line {at}: not JSON ({error})") from error
        if not isinstance(line, dict):
            raise RecordError(f"{path.name} line {at}: not an object")
        lines.append(line)
    if not lines or lines[0].get("record") != record:
        raise RecordError(f"{path.name}: its first line does not say that it is a {record}")
    return lines, hashlib.sha256(data).hexdigest()
