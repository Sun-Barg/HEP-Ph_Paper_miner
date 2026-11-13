"""What every paper source shares: identifiers, expected failures, paper data, the source protocol."""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from typing import Protocol


class ErrorKind(str, Enum):
    """Failures a source is expected to report.

    The server turns each kind into a sentence the model can act on.
    Always use `.value` when formatting: `str()` of a mixed-in enum differs
    between Python versions.
    """

    INVALID_ID = "invalid_id"
    NOT_FOUND = "not_found"
    BAD_QUERY = "bad_query"
    NO_SUCH_SECTION = "no_such_section"
    NO_FULL_TEXT = "no_full_text"
    PARSE_ERROR = "parse_error"
    UPSTREAM_BUSY = "upstream_busy"
    TIMEOUT = "timeout"


class SourceError(Exception):
    """An expected failure. `kind` says which one; `detail` carries the offending value."""

    def __init__(self, kind: ErrorKind, detail: str = "") -> None:
        # Hand both arguments to Exception. pickle and copy rebuild an exception by
        # calling its class with `args`, so `args` has to match this signature;
        # a process pool sends a worker's exception to the parent that way.
        super().__init__(kind, detail)
        self.kind = kind
        self.detail = detail

    def __str__(self) -> str:
        return f"{self.kind.value}: {self.detail}"


@dataclass(frozen=True)
class ArxivId:
    """An arXiv identifier split into its base and its version."""

    base: str  # "2610.26648" or "hep-ph/0404175"
    version: int | None  # None when the caller did not pin a version

    def __str__(self) -> str:
        return self.base if self.version is None else f"{self.base}v{self.version}"


# The rules below follow arXiv's description of its identifiers
# (https://info.arxiv.org/help/arxiv_identifier.html) and its own parser
# (github.com/arXiv/arxiv-base, arxiv/identifier). A rule belongs here only if it can
# never turn away a real paper: a wrongly accepted identifier costs one request that
# ends in NOT_FOUND, a wrongly rejected one makes a real paper unreachable.

# Digits are spelled [0-9]: in a str pattern `\d` also matches digits of other scripts.
# Versions start at v1 and arXiv names no maximum. Three digits is this project's own
# limit, the one rule here that is not arXiv's; it keeps an endless run of digits
# away from int().
_VERSION = r"(?:v([1-9][0-9]{0,2}))?"
# Since 2007-04: YYMM.NNNN through 1412, YYMM.NNNNN from 1501.
_NEW_STYLE = re.compile(r"([0-9]{2})([0-9]{2})\.([0-9]{4,5})" + _VERSION)
# Until 2007-03: archive/YYMMNNN, for example hep-ph/0404175.
_OLD_STYLE = re.compile(r"([a-z]+(?:-[a-z]+)?)/([0-9]{2})([0-9]{2})([0-9]{3})" + _VERSION)

# Archive names that old identifiers can carry: every archive in arXiv's taxonomy
# (arxiv-base, arxiv/taxonomy/definitions.py) that started before 2007-04, without
# arXiv's internal "test" archive.
OLD_SCHEME_ARCHIVES = frozenset(
    """
    acc-phys adap-org alg-geom ao-sci astro-ph atom-ph bayes-an chao-dyn chem-ph
    cmp-lg comp-gas cond-mat cs dg-ga funct-an gr-qc hep-ex hep-lat hep-ph hep-th
    math math-ph mtrl-th nlin nucl-ex nucl-th patt-sol physics plasm-ph q-alg q-bio
    quant-ph solv-int supr-con
    """.split()
)

_PREFIX = "arxiv:"


def parse_arxiv_id(text: str) -> ArxivId:
    """Parse an arXiv identifier, or raise SourceError(INVALID_ID).

    Surrounding whitespace and a leading "arXiv:" are accepted. URLs and
    everything else are rejected: a tool should be called with an identifier
    exactly as another tool returned it.

    Only the form and the limits that never move are checked: months, the first
    and last month of each scheme, sequence numbers from 1, known archive names.
    A month that has not come yet passes, as it does in arXiv's own examples
    (9912.12345v2). Whether a paper exists is for the network to answer.
    """
    candidate = text.strip()
    if candidate[: len(_PREFIX)].lower() == _PREFIX:
        candidate = candidate[len(_PREFIX) :].strip()

    match = _NEW_STYLE.fullmatch(candidate)
    if match:
        yy, mm, number, version = match.groups()
        year_month = (2000 + int(yy), int(mm))
        expected_digits = 4 if year_month <= (2014, 12) else 5
        if (
            1 <= int(mm) <= 12
            and year_month >= (2007, 4)
            and len(number) == expected_digits
            and int(number) >= 1  # sequence numbers start at 0001 / 00001
        ):
            return ArxivId(f"{yy}{mm}.{number}", _as_version(version))
        raise SourceError(ErrorKind.INVALID_ID, text)

    match = _OLD_STYLE.fullmatch(candidate)
    if match:
        archive, yy, mm, number, version = match.groups()
        # Two-digit years: 91-99 are 1991-1999, 00-07 are 2000-2007.
        year_month = ((1900 if int(yy) >= 91 else 2000) + int(yy), int(mm))
        if (
            archive in OLD_SCHEME_ARCHIVES
            and 1 <= int(mm) <= 12
            and (1991, 7) <= year_month <= (2007, 3)  # arXiv gives the range as 9107-0703
            and int(number) >= 1
        ):
            return ArxivId(f"{archive}/{yy}{mm}{number}", _as_version(version))

    raise SourceError(ErrorKind.INVALID_ID, text)


def _as_version(digits: str | None) -> int | None:
    return None if digits is None else int(digits)


@dataclass(frozen=True)
class PaperMeta:
    """What the arXiv listing says about a paper. No full text."""

    arxiv_id: str  # with the version when it is known: "2610.26648v1"
    title: str
    authors: tuple[str, ...]
    year: int  # year of the first version
    primary_category: str
    abstract: str


@dataclass(frozen=True)
class Section:
    """One section or subsection of the full text.

    The text of a section includes its subsections, so reading "3" gives all of
    "3.1", "3.2" and so on as well.
    """

    section_id: str  # "3", "3.2", "A", "u1" (unnumbered)
    title: str
    level: int  # 1 for a section, 2 for a subsection
    text: str
    # For a subsection: where its heading begins in the text of the section that holds
    # it. The parser knows the place; looking for it afterwards can find the wrong one.
    heading_at: int | None = None

    @property
    def chars(self) -> int:
        return len(self.text)


@dataclass(frozen=True)
class Paper:
    """A paper with its full text split into sections."""

    meta: PaperMeta
    sections: tuple[Section, ...]  # in document order
    parser_version: str

    @property
    def chars(self) -> int:
        """Size of the full text. Subsections are part of their section, so count level 1 only."""
        return sum(section.chars for section in self.sections if section.level == 1)


@dataclass(frozen=True)
class SearchQuery:
    query: str
    author: str | None = None
    category: str | None = None
    year_from: int | None = None
    year_to: int | None = None
    max_results: int = 5


@dataclass(frozen=True)
class SearchResult:
    papers: tuple[PaperMeta, ...]
    total: int  # how many papers matched, which can be more than were returned
    # When the source gave this answer (UTC, ISO 8601), "" when that is not known. An
    # answer that is kept is not asked for again, and what a search finds changes.
    fetched_at: str = ""


class PaperSource(Protocol):
    """Where papers come from. The server knows nothing else about a source.

    All methods report expected failures by raising SourceError.
    """

    def search(self, query: SearchQuery) -> SearchResult: ...

    def listing(self, arxiv_id: ArxivId) -> PaperMeta:
        """What the listing says about one paper; without a version, about its latest version.

        Works also for a paper whose full text cannot be read.
        """
        ...

    def paper(self, arxiv_id: ArxivId) -> Paper: ...
