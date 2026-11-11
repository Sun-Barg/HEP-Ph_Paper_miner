"""What every paper source shares: identifiers and expected failures.

This first version holds only what the placeholder tool needs. The paper data
types and the source protocol are added together with the first real source.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum


class ErrorKind(str, Enum):
    """Failures a source is expected to report.

    The server turns each kind into a sentence the model can act on.
    Always use `.value` when formatting: `str()` of a mixed-in enum differs
    between Python versions.
    """

    INVALID_ID = "invalid_id"
    NOT_FOUND = "not_found"
    NO_SUCH_SECTION = "no_such_section"
    NO_FULL_TEXT = "no_full_text"
    PARSE_ERROR = "parse_error"
    UPSTREAM_BUSY = "upstream_busy"
    TIMEOUT = "timeout"


class SourceError(Exception):
    """An expected failure. `kind` says which one; `detail` carries the offending value."""

    def __init__(self, kind: ErrorKind, detail: str = "") -> None:
        super().__init__(f"{kind.value}: {detail}")
        self.kind = kind
        self.detail = detail


@dataclass(frozen=True)
class ArxivId:
    """An arXiv identifier split into its base and its version."""

    base: str  # "2610.26648" or "hep-ph/0404175"
    version: int | None  # None when the caller did not pin a version

    def __str__(self) -> str:
        return self.base if self.version is None else f"{self.base}v{self.version}"


# Since 2007-04: YYMM.NNNN through 1412, YYMM.NNNNN from 1501.
_NEW_STYLE = re.compile(r"(\d{2})(\d{2})\.(\d{4,5})(?:v([1-9]\d*))?")
# Until 2007-03: archive/YYMMNNN, for example hep-ph/0404175.
_OLD_STYLE = re.compile(r"([a-z]+(?:-[a-z]+)?)/(\d{2})(\d{2})(\d{3})(?:v([1-9]\d*))?")

_PREFIX = "arxiv:"


def parse_arxiv_id(text: str) -> ArxivId:
    """Parse an arXiv identifier, or raise SourceError(INVALID_ID).

    Surrounding whitespace and a leading "arXiv:" are accepted. URLs and
    everything else are rejected: a tool should be called with an identifier
    exactly as another tool returned it.
    """
    candidate = text.strip()
    if candidate[: len(_PREFIX)].lower() == _PREFIX:
        candidate = candidate[len(_PREFIX) :].strip()

    match = _NEW_STYLE.fullmatch(candidate)
    if match:
        yy, mm, number, version = match.groups()
        year_month = (2000 + int(yy), int(mm))
        expected_digits = 4 if year_month <= (2014, 12) else 5
        if 1 <= int(mm) <= 12 and year_month >= (2007, 4) and len(number) == expected_digits:
            return ArxivId(f"{yy}{mm}.{number}", _as_version(version))
        raise SourceError(ErrorKind.INVALID_ID, text)

    match = _OLD_STYLE.fullmatch(candidate)
    if match:
        archive, yy, mm, number, version = match.groups()
        # Two-digit years: 91-99 are 1991-1999, 00-07 are 2000-2007.
        year_month = ((1900 if int(yy) >= 91 else 2000) + int(yy), int(mm))
        if 1 <= int(mm) <= 12 and year_month <= (2007, 3):
            return ArxivId(f"{archive}/{yy}{mm}{number}", _as_version(version))

    raise SourceError(ErrorKind.INVALID_ID, text)


def _as_version(digits: str | None) -> int | None:
    return None if digits is None else int(digits)
