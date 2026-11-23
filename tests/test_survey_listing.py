"""The list a sample is drawn from, with arXiv played by a scripted transport. No network.

The feed is written after the example in the manual of the API and after
tests/fixtures/api_search.xml, not saved from a real answer.
"""

import json
import re
from xml.sax.saxutils import escape

import httpx2
import pytest
from test_survey_plan import a_plan

from hepph_paper_miner.http import Fetcher
from hepph_paper_miner.sources.arxiv import API_URL
from hepph_paper_miner.survey.listing import (
    MAX_LISTED,
    TRIES,
    Listed,
    ListingError,
    Piece,
    every_paper_once,
    list_piece,
    list_population,
    piece_params,
    read_page,
)
from hepph_paper_miner.survey.plan import Window, read_plan

AUGUST = Window("202608010000", "202608312359")
SEPTEMBER = Window("202609010000", "202609302359")

_OPEN = (
    '<opensearch:{0} xmlns:opensearch="http://a9.com/-/spec/opensearch/1.1/">{1}</opensearch:{0}>'
)
_QUERY = re.compile(r"cat:(\S+) AND submittedDate:\[([0-9]{12}) TO ([0-9]{12})\]")


def entry(arxiv_id: str, primary: str, published: str, others: tuple[str, ...] = ()) -> str:
    categories = "".join(
        f'<category term="{name}" scheme="http://arxiv.org/schemas/atom"/>'
        for name in (primary, *others)
    )
    return (
        f"<entry><id>http://arxiv.org/abs/{arxiv_id}</id>"
        f"<updated>{published}</updated><published>{published}</published>"
        f"<title>{escape('A title that <no> file of the survey keeps')}</title>"
        "<summary>An abstract that no file of the survey keeps.</summary>"
        "<author><name>A. Author</name></author>"
        f'<arxiv:primary_category xmlns:arxiv="http://arxiv.org/schemas/atom" term="{primary}" '
        f'scheme="http://arxiv.org/schemas/atom"/>{categories}</entry>'
    )


def feed(total: int, start: int, entries: list[str], size: int = 0) -> bytes:
    return (
        '<?xml version="1.0" encoding="UTF-8"?><feed xmlns="http://www.w3.org/2005/Atom">'
        "<title>ArXiv Query</title><id>http://arxiv.org/api/x</id>"
        + _OPEN.format("totalResults", total)
        + _OPEN.format("startIndex", start)
        + _OPEN.format("itemsPerPage", size or len(entries))
        + "".join(entries)
        + "</feed>"
    ).encode()


ERROR_FEED = feed(
    1,
    0,
    [
        "<entry><id>https://arxiv.org/api/errors#bad</id><title>Error</title>"
        "<summary>incorrect query</summary></entry>"
    ],
)


def paper(number: int, primary: str, published: str, *others: str, version: int = 1):
    """A paper of the fake arXiv: identifier, primary category, first version, cross-listings."""
    month = published[2:4] + published[5:7]
    return (f"{month}.{number:05d}v{version}", primary, published, others)


class ListingArxiv:
    """arXiv's API for `cat:` in a window: answers from papers held in memory, oldest first."""

    def __init__(self, papers):
        self.papers = list(papers)
        self.requests: list[httpx2.URL] = []

    def matching(self, category: str, first: str, last: str) -> list[str]:
        found = [
            each
            for each in sorted(self.papers, key=lambda each: (each[2], each[0]))
            if category in (each[1], *each[3])
            and first <= re.sub(r"[-T:]", "", each[2])[:12] <= last
        ]
        return [entry(*each) for each in found]

    def answer(self, request: httpx2.Request) -> tuple[int, bytes]:
        params = request.url.params
        category, first, last = _QUERY.fullmatch(params["search_query"]).groups()
        assert (params["sortBy"], params["sortOrder"]) == ("submittedDate", "ascending")
        start, size = int(params["start"]), int(params["max_results"])
        found = self.matching(category, first, last)
        return 200, feed(len(found), start, found[start : start + size], size)

    def handler(self, request: httpx2.Request) -> httpx2.Response:
        self.requests.append(request.url)
        # A listing that never comes to its end fails here, not by never ending.
        assert len(self.requests) < 200, "the listing does not end"
        status, body = self.answer(request)
        return httpx2.Response(status, content=body)

    def fetcher(self, cache_dir) -> Fetcher:
        return Fetcher(
            cache_dir, transport=httpx2.MockTransport(self.handler), sleep=lambda seconds: None
        )

    def starts(self) -> list[str]:
        return [url.params["start"] for url in self.requests]


class Spoilt(ListingArxiv):
    """Answers some requests with something else: `spoil(count, start, body)` says what."""

    def __init__(self, papers, spoil):
        super().__init__(papers)
        self.spoil = spoil

    def answer(self, request):
        status, body = super().answer(request)
        changed = self.spoil(len(self.requests), int(request.url.params["start"]), body)
        if changed is None:
            return status, body
        return changed if isinstance(changed, tuple) else (200, changed)


FIVE = [paper(n, "hep-ph", f"2026-08-0{n}T10:00:00Z") for n in range(1, 6)]


def kept(cache_dir) -> list:
    """The answers on disk."""
    return sorted(cache_dir.glob("*/*.body"))


def test_a_piece_is_asked_for_page_by_page_oldest_first(tmp_path):
    arxiv = ListingArxiv(reversed(FIVE))

    piece = list_piece(arxiv.fetcher(tmp_path), "hep-ph", AUGUST, page_size=2)

    assert [each.arxiv_id for each in piece.papers] == [each[0] for each in FIVE]
    assert (piece.total, piece.pages, piece.from_cache) == (5, 3, 0)
    assert arxiv.starts() == ["0", "2", "4"]
    assert dict(arxiv.requests[1].params) == {
        "search_query": "cat:hep-ph AND submittedDate:[202608010000 TO 202608312359]",
        "start": "2",
        "max_results": "2",
        "sortBy": "submittedDate",
        "sortOrder": "ascending",
    }
    assert str(arxiv.requests[0]).startswith(API_URL + "?")


def test_what_the_list_keeps_of_a_paper_is_identifiers_and_a_date():
    (listed,) = read_page(
        feed(1, 0, [entry("2608.00007v3", "hep-ph", "2026-08-03T17:59:59Z")])
    ).papers
    assert listed == Listed("2608.00007v3", "hep-ph", "2026-08-03T17:59:59Z")
    assert "title" not in json.dumps(listed.__dict__).lower()


def test_papers_cross_listed_to_a_category_are_counted_and_are_not_its_own(tmp_path):
    papers = [
        paper(1, "hep-ph", "2026-08-01T10:00:00Z", "astro-ph.HE"),
        paper(2, "astro-ph.HE", "2026-08-02T10:00:00Z", "hep-ph"),
        paper(3, "cs.LG", "2026-08-03T10:00:00Z", "hep-ph"),
        paper(4, "hep-th", "2026-08-04T10:00:00Z"),
    ]
    piece = list_piece(ListingArxiv(papers).fetcher(tmp_path), "hep-ph", AUGUST)

    assert piece.total == 3
    assert [each.arxiv_id for each in piece.own] == ["2608.00001v1"]


def test_a_second_run_reads_a_whole_piece_from_disk(tmp_path):
    arxiv = ListingArxiv(FIVE)
    first = list_piece(arxiv.fetcher(tmp_path), "hep-ph", AUGUST, page_size=2)
    again = list_piece(arxiv.fetcher(tmp_path), "hep-ph", AUGUST, page_size=2)

    assert len(arxiv.requests) == 3
    assert again.papers == first.papers and again.from_cache == 3
    assert again.fetched == first.fetched  # the day arXiv gave the answer, not the day it is read


def test_a_page_with_fewer_papers_than_it_should_hold_is_asked_for_again(tmp_path):
    # Status 200 and a feed, and one paper short: the hole a sample must not be drawn over.
    short = feed(5, 2, [entry(*FIVE[2])], 2)
    arxiv = Spoilt(FIVE, lambda count, start, body: short if count == 2 else None)
    said: list[str] = []

    piece = list_piece(arxiv.fetcher(tmp_path), "hep-ph", AUGUST, page_size=2, say=said.append)

    assert [each.arxiv_id for each in piece.papers] == [each[0] for each in FIVE]
    assert said == [
        "hep-ph 202608010000-202608312359 | try 1 of 3: "
        "the page from 2 on holds 1 papers, not 2 (of 5)"
    ]
    # The second try began at the first page again, and read nothing from disk.
    assert arxiv.starts() == ["0", "2", "0", "2", "4"]
    assert piece.from_cache == 0


def test_a_piece_that_stays_short_stops_the_listing_and_leaves_nothing_on_disk(tmp_path):
    short = feed(5, 2, [entry(*FIVE[2])], 2)
    arxiv = Spoilt(FIVE, lambda count, start, body: short if start == 2 else None)

    with pytest.raises(ListingError) as caught:
        list_piece(arxiv.fetcher(tmp_path), "hep-ph", AUGUST, page_size=2, say=lambda line: None)

    assert f"not whole after {TRIES} tries" in str(caught.value)
    assert "holds 1 papers, not 2" in str(caught.value)
    assert len(arxiv.requests) == 2 * TRIES
    assert kept(tmp_path) == []  # also the good first page: the next run begins anew


@pytest.mark.parametrize(
    ("spoilt", "said"),
    [
        (feed(6, 2, [entry(*each) for each in FIVE[2:4]], 2), "the total changed from 5 to 6"),
        (feed(5, 0, [entry(*each) for each in FIVE[:2]], 2), "answered from 0 on"),
        (b"<html><body>Rate exceeded.</body></html>", "not an Atom feed: <html>"),
        (b"Rate exceeded.", "not XML"),
        (
            feed(5, 2, [entry(*FIVE[2]), entry("2608.00004", "hep-ph", FIVE[3][2])], 2),
            "without a version",
        ),
        (
            feed(
                5, 2, [entry(*FIVE[2]), entry(*FIVE[3]).replace('term="hep-ph"', 'term=""', 1)], 2
            ),
            "without a primary category",
        ),
        (
            feed(
                5,
                2,
                [entry(*FIVE[2]), entry(*FIVE[3]).replace("<published>20", "<published>soon 20")],
                2,
            ),
            "without a time that can be read",
        ),
        (
            feed(
                5,
                2,
                [
                    entry(*FIVE[2]),
                    entry(*FIVE[3]).replace("10:00:00Z</published>", "10:00:00</published>"),
                ],
                2,
            ),
            "without a time that can be read",  # no zone: nobody can say which moment it is
        ),
        (
            feed(5, 2, [entry(*FIVE[2]), entry(*FIVE[3]).replace("/abs/2608.00004v1", "/abs/")], 2),
            "an entry that is not a paper",
        ),
        (
            feed(5, 2, [entry(*each) for each in FIVE[2:4]], 2).replace(b"totalResults", b"total"),
            "does not say its totalResults",
        ),
        (feed(5, 2, [entry(*FIVE[1]), entry(*FIVE[3])], 2), "2608.00002v1 is on two pages"),
    ],
)
def test_an_answer_that_cannot_be_right_is_not_trusted_and_not_kept(tmp_path, spoilt, said):
    # Once: asked for again, and the piece is whole.
    once = Spoilt(FIVE, lambda count, start, body: spoilt if count == 2 else None)
    heard: list[str] = []
    piece = list_piece(once.fetcher(tmp_path / "once"), "hep-ph", AUGUST, 2, heard.append)
    assert len(piece.papers) == 5 and said in heard[0]

    # Every time: no list.
    always = Spoilt(FIVE, lambda count, start, body: spoilt if start == 2 else None)
    with pytest.raises(ListingError, match=re.escape(said)):
        list_piece(always.fetcher(tmp_path / "always"), "hep-ph", AUGUST, 2, lambda line: None)
    assert kept(tmp_path / "always") == []


def test_a_page_kept_by_an_earlier_run_that_no_longer_fits_is_thrown_away(tmp_path):
    # The first run got one page and then no answer. Before the second run, a paper is
    # cross-listed to the category: the page on disk is of a list that is gone.
    arxiv = Spoilt(FIVE, lambda count, start, body: (503, b"") if start == 2 else None)
    with pytest.raises(ListingError) as caught:
        list_piece(arxiv.fetcher(tmp_path), "hep-ph", AUGUST, page_size=2, say=lambda line: None)
    assert "arXiv did not answer (busy, status 503)" in str(caught.value)
    assert "run the command again later" in str(caught.value)
    assert len(kept(tmp_path)) == 1  # what came is kept

    later = ListingArxiv([paper(9, "hep-th", "2026-08-01T00:30:00Z", "hep-ph"), *FIVE])
    said: list[str] = []
    piece = list_piece(later.fetcher(tmp_path), "hep-ph", AUGUST, page_size=2, say=said.append)

    assert "the total changed from 5 to 6" in said[0]
    assert [each.arxiv_id for each in piece.papers][0] == "2608.00009v1"
    assert (piece.total, len(piece.own)) == (6, 5)
    assert later.starts() == ["2", "0", "2", "4"]


def test_after_a_failed_try_nothing_more_is_read_from_disk(tmp_path):
    # A whole piece on disk from an earlier day, one page of it lost since, and a list
    # that has grown: the pages further on are of the old list too. The second try asks
    # for all of it afresh. Reading on from disk, every try would uncover one more page
    # of the old list, and three tries would not be enough.
    seven = [paper(n, "hep-ph", f"2026-08-0{n}T10:00:00Z") for n in range(1, 8)]
    arxiv = ListingArxiv(seven)
    fetcher = arxiv.fetcher(tmp_path)
    list_piece(fetcher, "hep-ph", AUGUST, page_size=2)
    fetcher.forget(API_URL, piece_params("hep-ph", AUGUST, 2, 2))
    assert len(kept(tmp_path)) == 3

    later = ListingArxiv([paper(9, "hep-th", "2026-08-01T00:30:00Z", "hep-ph"), *seven])
    said: list[str] = []
    piece = list_piece(later.fetcher(tmp_path), "hep-ph", AUGUST, page_size=2, say=said.append)

    assert piece.total == 8 and len(said) == 1
    assert later.starts() == ["2", "0", "2", "4", "6"]


def test_a_piece_without_papers_is_asked_for_twice_and_never_kept(tmp_path):
    arxiv = ListingArxiv(FIVE)
    piece = list_piece(arxiv.fetcher(tmp_path), "hep-ph", SEPTEMBER, page_size=2)

    assert (piece.total, piece.papers, piece.pages) == (0, (), 2)
    assert arxiv.starts() == ["0", "0"]
    assert kept(tmp_path) == []


def test_nothing_at_first_and_papers_when_asked_again_is_not_taken_for_nothing(tmp_path):
    # An API in trouble can answer 200 with an empty feed. Kept, the piece would be lost.
    arxiv = Spoilt(FIVE, lambda count, start, body: feed(0, 0, [], 2) if count == 1 else None)
    said: list[str] = []
    piece = list_piece(arxiv.fetcher(tmp_path), "hep-ph", AUGUST, page_size=2, say=said.append)

    assert piece.total == 5
    assert said == ["hep-ph 202608010000-202608312359 | try 1 of 3: no papers at first, then 5"]


def test_an_empty_answer_left_on_disk_by_a_run_that_was_killed_is_not_believed(tmp_path):
    arxiv = ListingArxiv(FIVE)
    arxiv.fetcher(tmp_path).get(API_URL, piece_params("hep-ph", SEPTEMBER, 0, 2))
    assert len(kept(tmp_path)) == 1  # as a process that ended between asking and reading left it

    later = ListingArxiv([*FIVE, paper(6, "hep-ph", "2026-09-05T10:00:00Z")])
    piece = list_piece(later.fetcher(tmp_path), "hep-ph", SEPTEMBER, 2, lambda line: None)
    assert [each.arxiv_id for each in piece.papers] == ["2609.00006v1"]


def test_a_paper_first_submitted_outside_the_window_stops_the_listing_at_once(tmp_path):
    # What `submittedDate` is about is not in the manual. If it were the latest version,
    # a paper of July replaced in August would come back for August, as it does here.
    old = entry("2607.00001v2", "hep-ph", "2026-07-20T10:00:00Z")
    body = feed(2, 0, [entry(*FIVE[0]), old], 2)
    arxiv = Spoilt(FIVE, lambda count, start, body_: body)

    with pytest.raises(ListingError) as caught:
        list_piece(arxiv.fetcher(tmp_path), "hep-ph", AUGUST, page_size=2)

    assert "1 of 2 papers say that their first version was submitted outside the window" in str(
        caught.value
    )
    assert "2607.00001v2, 2026-07-20T10:00:00Z" in str(caught.value)
    assert len(arxiv.requests) == 1  # asking again would bring the same


def test_the_error_feed_stops_the_listing_and_is_not_kept(tmp_path):
    arxiv = Spoilt(FIVE, lambda count, start, body: ERROR_FEED)
    with pytest.raises(ListingError, match="arXiv cannot answer the request: incorrect query"):
        list_piece(arxiv.fetcher(tmp_path), "hep-ph", AUGUST)
    assert len(arxiv.requests) == 1 and kept(tmp_path) == []


def test_a_request_that_arxiv_refuses_is_not_called_no_answer(tmp_path):
    arxiv = Spoilt(FIVE, lambda count, start, body: (400, b""))
    with pytest.raises(ListingError) as caught:
        list_piece(arxiv.fetcher(tmp_path), "hep-ph", AUGUST)
    assert "arXiv refused the request (rejected, status 400)" in str(caught.value)
    assert "again later" not in str(caught.value)


def test_more_papers_than_the_api_gives_for_one_request_stops_the_listing(tmp_path):
    arxiv = Spoilt(FIVE, lambda count, start, body: feed(MAX_LISTED + 1, 0, [entry(*FIVE[0])], 1))
    with pytest.raises(ListingError, match="the plan needs narrower windows"):
        list_piece(arxiv.fetcher(tmp_path), "hep-ph", AUGUST, page_size=1)
    assert len(arxiv.requests) == 1


@pytest.mark.parametrize("page_size", [0, -1, 2001])
def test_a_page_size_the_api_cannot_serve_is_refused_before_anything_is_asked(tmp_path, page_size):
    # A page of no papers would never bring the piece to its end: the first answer is
    # kept, and from then on the same page is read from disk again and again.
    arxiv = ListingArxiv(FIVE)
    fetcher = arxiv.fetcher(tmp_path)
    asked: list[tuple] = []
    get = fetcher.get

    def counted(*arguments, **options):
        asked.append(arguments)
        assert len(asked) < 50, "the listing does not end"
        return get(*arguments, **options)

    fetcher.get = counted
    with pytest.raises(ValueError, match="page_size: from 1 to 2000"):
        list_piece(fetcher, "hep-ph", AUGUST, page_size=page_size)
    assert asked == [] and arxiv.requests == []


PLAN = read_plan(json.dumps(a_plan()))
SEVERAL = [
    paper(3, "hep-ph", "2026-08-03T10:00:00Z", "astro-ph.CO"),
    paper(1, "hep-ph", "2026-09-01T00:00:00Z"),
    paper(2, "astro-ph.GA", "2026-08-31T23:59:59Z", "astro-ph.CO", "hep-ph"),
    paper(4, "astro-ph.CO", "2026-09-30T23:59:00Z"),
    paper(5, "astro-ph.HE", "2026-09-10T10:00:00Z", "astro-ph.GA"),  # no category of the plan
    paper(6, "hep-ph", "2026-10-01T00:00:00Z"),  # after the last window
]


def test_every_piece_of_the_plan_is_asked_for_and_every_paper_kept_once(tmp_path):
    arxiv = ListingArxiv(SEVERAL)
    said: list[str] = []
    ticks = iter(range(0, 1000, 4))

    population = list_population(
        arxiv.fetcher(tmp_path), PLAN, say=said.append, clock=lambda: next(ticks)
    )

    asked = [(piece.category, str(piece.window)) for piece in population.pieces]
    assert asked == [
        (category, window)
        for category in ("hep-ph", "astro-ph.GA", "astro-ph.CO")
        for window in ("202608010000-202608312359", "202609010000-202609302359")
    ]
    assert [(piece.total, len(piece.own)) for piece in population.pieces] == [
        (2, 1),
        (1, 1),
        (1, 1),
        (1, 0),
        (2, 0),
        (1, 1),
    ]
    assert population.papers == (
        Listed("2608.00002v1", "astro-ph.GA", "2026-08-31T23:59:59Z"),
        Listed("2608.00003v1", "hep-ph", "2026-08-03T10:00:00Z"),
        Listed("2609.00001v1", "hep-ph", "2026-09-01T00:00:00Z"),
        Listed("2609.00004v1", "astro-ph.CO", "2026-09-30T23:59:00Z"),
    )
    assert (
        said[0] == "[1/6] hep-ph 202608010000-202608312359 | 2 listed, 1 primary | 1 page(s) | 4 s"
    )
    assert len(said) == 6


def test_a_first_try_asks_for_some_categories_only(tmp_path):
    arxiv = ListingArxiv(SEVERAL)
    population = list_population(
        arxiv.fetcher(tmp_path), PLAN, say=lambda line: None, only=["astro-ph.CO"]
    )
    assert {piece.category for piece in population.pieces} == {"astro-ph.CO"}
    assert [each.arxiv_id for each in population.papers] == ["2609.00004v1"]


def test_a_paper_that_stands_in_two_pieces_as_their_own_stops_the_listing():
    # It was given another primary category while the list was being asked for, say.
    def piece(category: str, window: Window, *papers: Listed) -> Piece:
        return Piece(category, window, len(papers), papers, 1, 0, ("2026-11-24T00:00:00+00:00",))

    twice = Listed("2608.00001v1", "hep-ph", "2026-08-01T10:00:00Z")
    moved = Listed("2608.00001v2", "hep-ph", "2026-09-01T10:00:00Z")
    with pytest.raises(ListingError) as caught:
        every_paper_once([piece("hep-ph", AUGUST, twice), piece("hep-ph", SEPTEMBER, moved)])
    assert "2608.00001 is a paper of hep-ph 202608010000-202608312359 and of hep-ph 2026090" in str(
        caught.value
    )
