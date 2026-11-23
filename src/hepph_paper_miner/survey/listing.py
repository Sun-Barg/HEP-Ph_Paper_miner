"""The list a sample is drawn from: every paper of a category that arXiv returns for a window.

A piece of the list is one category in one window of the plan. It is asked for page by
page, oldest paper first, through the same Fetcher as everything else: three seconds
between requests, and an answer that was received is kept on disk.

A sample is only as good as the list it comes from, and the API can answer with status
200 and less than it was asked for. So a piece counts only when it is whole:

    every page says the same total, and begins where it was asked to begin;
    the pages together hold exactly that many papers, and none of them twice;
    every paper carries a version, a primary category and the time of its first version;
    a piece that is said to hold nothing says so a second time, asked afresh.

A piece that fails one of these is thrown away, pages on disk included, and asked for
again from its first page; after three tries the command stops. Nothing is drawn from a
list with a hole in it: the sample would look like any other, and nobody could tell.

One more thing is checked, and it stops the command at once, because asking again would
not change it: every paper has to say that its first version was submitted inside the
window. The plan means "first submitted in the window" by a window, and the manual of
the API (read on 2026-11-24) does not say which version `submittedDate` is about. If it
is about another one, this is where it shows.

The answer to `cat:` holds the papers that are cross-listed to the category as well.
They are counted (`total`) and then left out: a paper belongs to the category it has as
its primary one, and so it is kept once, in the piece of that category.

Reference: https://info.arxiv.org/help/api/user-manual.html
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime
from time import monotonic
from xml.etree import ElementTree

from hepph_paper_miner.http import Fetcher, FetchError
from hepph_paper_miner.sources.arxiv import API_URL
from hepph_paper_miner.sources.base import SourceError, parse_arxiv_id
from hepph_paper_miner.survey.plan import Plan, Window

# The manual: "in slices of at most 2000 at a time", and no more than 30000 for a query.
MAX_PAGE_SIZE = 2000
MAX_LISTED = 30_000
# The manual asks that a query with more than 1,000 results be taken in smaller slices.
# With this size most pieces of the plan are one page, and a piece of one page cannot
# have pages that do not fit each other. How long the API takes over such a page has
# not been measured here (a request may take thirty seconds): the first try shows it.
PAGE_SIZE = 1000
TRIES = 3  # how often a piece is asked for before the command gives up

_ATOM = "{http://www.w3.org/2005/Atom}"
_OPENSEARCH = "{http://a9.com/-/spec/opensearch/1.1/}"
_ARXIV = "{http://arxiv.org/schemas/atom}"
_ERROR_ID = "arxiv.org/api/errors"  # the id of the entry in the API's error feed, without scheme


class ListingError(Exception):
    """The list could not be had whole. No sample is drawn from what there is."""


class _Unsteady(Exception):
    """An answer that cannot be right as it stands, and that asking again may mend."""


@dataclass(frozen=True)
class Listed:
    """What the list keeps of a paper: identifiers and a date, nothing of its text."""

    arxiv_id: str  # with the version the list names, its latest: "2608.01234v2"
    primary: str
    published: str  # when the first version was submitted, as the feed writes it


@dataclass(frozen=True)
class Page:
    total: int  # how many papers the API has for the request, on however many pages
    start: int  # the place of this page's first paper among them
    papers: tuple[Listed, ...]


@dataclass(frozen=True)
class Piece:
    """One category in one window: everything the API returned for it."""

    category: str
    window: Window
    total: int  # with the papers cross-listed to the category
    papers: tuple[Listed, ...]  # all `total` of them
    pages: int  # how many answers were read for it: two for a piece that holds nothing
    from_cache: int  # how many of them were on disk already
    fetched: tuple[str, ...]  # when arXiv gave each page (UTC)

    @property
    def own(self) -> tuple[Listed, ...]:
        """The papers that have this category as their primary one."""
        return tuple(paper for paper in self.papers if paper.primary == self.category)


@dataclass(frozen=True)
class Population:
    pieces: tuple[Piece, ...]
    papers: tuple[Listed, ...]  # every paper once, by identifier


def piece_params(category: str, window: Window, start: int, page_size: int) -> dict[str, str]:
    """The request for one page. Oldest first: a paper that joins the list later (a new
    cross-listing) then moves the pages that follow it, not the ones already read."""
    return {
        "search_query": f"cat:{category} AND submittedDate:[{window.first} TO {window.last}]",
        "start": str(start),
        "max_results": str(page_size),
        "sortBy": "submittedDate",
        "sortOrder": "ascending",
    }


def _text(parent: ElementTree.Element, tag: str) -> str:
    return " ".join((parent.findtext(tag) or "").split())


def _number(feed: ElementTree.Element, name: str) -> int:
    text = _text(feed, f"{_OPENSEARCH}{name}")
    if not text.isdigit():
        # Without it nobody can say whether the pages are all there.
        raise _Unsteady(f"the answer does not say its {name}")
    return int(text)


def read_page(body: bytes) -> Page:
    """Read one page of a piece, and take nothing on trust.

    The reader of the search tool (arxiv_search.parse_feed) passes over an entry it
    cannot read and counts the entries when the total is missing. That suits a search.
    Here either would hide a hole in the list.
    """
    try:
        feed = ElementTree.fromstring(body)
    except ElementTree.ParseError as error:
        raise _Unsteady(f"the answer is not XML ({error})") from error
    if feed.tag != f"{_ATOM}feed":
        raise _Unsteady(f"the answer is not an Atom feed: <{feed.tag}>")
    papers = []
    for entry in feed.findall(f"{_ATOM}entry"):
        entry_id = _text(entry, f"{_ATOM}id")
        if entry_id.partition("://")[2].startswith(_ERROR_ID):
            # The API read the request and refuses it. Asking again changes nothing.
            raise ListingError(
                f"arXiv cannot answer the request: {_text(entry, f'{_ATOM}summary')}"
            )
        try:
            arxiv_id = parse_arxiv_id(entry_id.split("/abs/", 1)[-1])
        except SourceError:
            raise _Unsteady(f"an entry that is not a paper: {entry_id!r}") from None
        if arxiv_id.version is None:
            # The survey reads the very version the list named. Without one, "the
            # paper" would be whatever version is the latest on the day it is read.
            raise _Unsteady(f"{arxiv_id} is listed without a version")
        primary = entry.find(f"{_ARXIV}primary_category")
        category = "" if primary is None else primary.get("term", "")
        if not category:
            raise _Unsteady(f"{arxiv_id} is listed without a primary category")
        published = _text(entry, f"{_ATOM}published")
        try:
            aware = datetime.fromisoformat(published).tzinfo is not None
        except ValueError:
            aware = False
        if not aware:
            raise _Unsteady(f"{arxiv_id} is listed without a time that can be read: {published!r}")
        papers.append(Listed(str(arxiv_id), category, published))
    return Page(_number(feed, "totalResults"), _number(feed, "startIndex"), tuple(papers))


def _ask(fetcher: Fetcher, category: str, window: Window, page_size: int, fresh: bool) -> Piece:
    """Ask for a piece once. When it raises _Unsteady or ListingError, nothing of the
    piece is left on disk; after a FetchError the pages that did come are kept."""
    asked: list[dict[str, str]] = []

    def page_at(start: int, refresh: bool) -> tuple[Page, bool, str]:
        params = piece_params(category, window, start, page_size)
        asked.append(params)
        fetched = fetcher.get(API_URL, params, refresh=refresh)
        page = read_page(fetched.body)
        if page.start != start:
            raise _Unsteady(f"asked for the papers from {start} on, answered from {page.start} on")
        return page, fetched.from_cache, fetched.fetched_at

    try:
        papers: list[Listed] = []
        total: int | None = None
        from_cache, fetched_at = 0, []
        while total is None or len(papers) < total:
            page, cached, when = page_at(len(papers), fresh)
            if total is None:
                total = page.total
                if total > MAX_LISTED:
                    raise ListingError(
                        f"{category} {window}: {total} papers, and the API gives no more than "
                        f"{MAX_LISTED} for one request; the plan needs narrower windows"
                    )
            elif page.total != total:
                raise _Unsteady(f"the total changed from {total} to {page.total} between pages")
            expected = min(page_size, total - len(papers))
            if len(page.papers) != expected:
                raise _Unsteady(
                    f"the page from {len(papers)} on holds {len(page.papers)} papers, "
                    f"not {expected} (of {total})"
                )
            papers += page.papers
            from_cache += cached
            fetched_at.append(when)
        if total == 0:
            # Nothing at all may be the truth, and it is also what an API in trouble
            # says. Asked a second time, afresh; and "nothing" is never kept on disk.
            again, _, when = page_at(0, True)
            if again.total != 0 or again.papers:
                raise _Unsteady(f"no papers at first, then {again.total}")
            fetched_at.append(when)
            for params in asked:
                fetcher.forget(API_URL, params)
        names = [paper.arxiv_id for paper in papers]
        if len(set(names)) != len(names):
            twice = next(name for name in names if names.count(name) > 1)
            raise _Unsteady(f"{twice} is on two pages")
    except (_Unsteady, ListingError):
        # Status 200, so every one of these answers was kept before anyone had read it.
        # Left there, the next run would read the same bad page from disk.
        for params in asked:
            fetcher.forget(API_URL, params)
        raise
    return Piece(
        category, window, total, tuple(papers), len(fetched_at), from_cache, tuple(fetched_at)
    )


def _outside(piece: Piece) -> list[Listed]:
    return [
        paper
        for paper in piece.papers
        if not piece.window.holds(datetime.fromisoformat(paper.published))
    ]


def list_piece(
    fetcher: Fetcher,
    category: str,
    window: Window,
    page_size: int = PAGE_SIZE,
    say: Callable[[str], None] = print,
) -> Piece:
    """One category in one window, whole, or ListingError."""
    if not 1 <= page_size <= MAX_PAGE_SIZE:
        # A page of no papers would be asked for again and again, without end.
        raise ValueError(f"page_size: from 1 to {MAX_PAGE_SIZE}, not {page_size}")
    where = f"{category} {window}"
    why = ""
    for attempt in range(1, TRIES + 1):
        try:
            # After a failed try nothing is read from disk: a page kept by an earlier
            # run may be the very one that no longer fits the others.
            piece = _ask(fetcher, category, window, page_size, fresh=attempt > 1)
        except _Unsteady as error:
            why = str(error)
            say(f"{where} | try {attempt} of {TRIES}: {why}")
            continue
        except FetchError as error:
            status = "" if error.status is None else f", status {error.status}"
            if error.reason in ("busy", "timeout"):
                # The Fetcher has tried again already. The pages that came stay on disk.
                raise ListingError(
                    f"{where}: arXiv did not answer ({error.reason}{status}). What was received "
                    "before is kept on disk: run the command again later."
                ) from error
            raise ListingError(
                f"{where}: arXiv refused the request ({error.reason}{status})"
            ) from error
        outside = _outside(piece)
        if outside:
            first = outside[0]
            raise ListingError(
                f"{where}: {len(outside)} of {piece.total} papers say that their first version "
                f"was submitted outside the window (the first of them: {first.arxiv_id}, "
                f"{first.published}). The windows of the plan do not mean what the plan "
                "takes them to mean."
            )
        return piece
    raise ListingError(f"{where}: not whole after {TRIES} tries ({why})")


def list_population(
    fetcher: Fetcher,
    plan: Plan,
    page_size: int = PAGE_SIZE,
    say: Callable[[str], None] = print,
    only: Sequence[str] | None = None,
    clock: Callable[[], float] = monotonic,
) -> Population:
    """Every piece of the plan, and from them every paper once. Raises ListingError.

    `only` asks for some categories and leaves the rest out: for a first try, never
    for a sample.
    """
    wanted = [category for category in plan.categories if only is None or category in only]
    todo = [(category, window) for category in wanted for window in plan.windows]
    pieces = []
    for at, (category, window) in enumerate(todo, start=1):
        began = clock()
        piece = list_piece(fetcher, category, window, page_size, say)
        pieces.append(piece)
        cached = f", {piece.from_cache} from disk" if piece.from_cache else ""
        say(
            f"[{at}/{len(todo)}] {category} {window} | {piece.total} listed, "
            f"{len(piece.own)} primary | {piece.pages} page(s){cached} | "
            f"{clock() - began:.0f} s"
        )
    return Population(tuple(pieces), every_paper_once(pieces))


def every_paper_once(pieces: Iterable[Piece]) -> tuple[Listed, ...]:
    """The papers of the pieces, each under its own category, by identifier.

    A paper has one primary category and one first version, so it can stand in one
    piece only. Found in two, something moved while the list was being asked for (a
    paper given another primary category, say), and the list is not one list.
    """
    found: dict[str, tuple[Listed, Piece]] = {}
    for piece in pieces:
        for paper in piece.own:
            base = parse_arxiv_id(paper.arxiv_id).base
            if base in found:
                other = found[base][1]
                raise ListingError(
                    f"{base} is a paper of {other.category} {other.window} "
                    f"and of {piece.category} {piece.window}"
                )
            found[base] = (paper, piece)
    return tuple(found[base][0] for base in sorted(found))
