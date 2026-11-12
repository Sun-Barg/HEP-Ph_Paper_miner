"""The arXiv source end to end, with arXiv played by a scripted transport. No network."""

import httpx2
import pytest
from conftest import FIXTURES, SAMPLE_LATEX, plain_tar, tar_gz

from hepph_paper_miner.http import Fetcher
from hepph_paper_miner.sources.arxiv import API_URL, SOURCE_URL, ArxivSource
from hepph_paper_miner.sources.base import ErrorKind, SearchQuery, SourceError, parse_arxiv_id

FEED = (FIXTURES / "api_search.xml").read_bytes()
EMPTY = (FIXTURES / "api_empty.xml").read_bytes()
ERROR = (FIXTURES / "api_error.xml").read_bytes()
DOWNLOAD = tar_gz({"paper.tex": SAMPLE_LATEX.encode()})


class FakeArxiv:
    def __init__(self, api=(200, FEED), source=(200, DOWNLOAD)):
        self.api, self.source = api, source
        self.requests: list[httpx2.URL] = []

    def handler(self, request: httpx2.Request) -> httpx2.Response:
        self.requests.append(request.url)
        status, body = self.api if request.url.path == "/api/query" else self.source
        return httpx2.Response(status, content=body)

    def make(self, tmp_path) -> ArxivSource:
        fetcher = Fetcher(
            tmp_path, transport=httpx2.MockTransport(self.handler), sleep=lambda seconds: None
        )
        return ArxivSource(fetcher)


def test_search_sends_the_query_and_returns_the_listing(tmp_path):
    arxiv = FakeArxiv()
    found = arxiv.make(tmp_path).search(SearchQuery('galactic "dark matter"', max_results=2))

    assert [paper.arxiv_id for paper in found.papers] == ["2610.26648v1", "hep-ph/0404175v2"]
    (url,) = arxiv.requests
    assert str(url).startswith(API_URL + "?")
    assert url.params["search_query"] == 'all:galactic AND all:"dark matter"'
    assert url.params["max_results"] == "2"


def test_search_with_nothing_to_search_for_sends_no_request(tmp_path):
    arxiv = FakeArxiv()
    assert arxiv.make(tmp_path).search(SearchQuery("()")).total == 0
    assert arxiv.requests == []


def test_paper_is_looked_up_then_downloaded_then_split(tmp_path):
    arxiv = FakeArxiv()
    source = arxiv.make(tmp_path)

    paper = source.paper(parse_arxiv_id("2610.26648v1"))

    assert paper.meta.arxiv_id == "2610.26648v1"
    assert paper.meta.authors[1] == "Hae Barg Kang"
    assert [section.section_id for section in paper.sections][:3] == ["1", "2", "2.1"]
    assert paper.parser_version == "3"
    lookup, download = arxiv.requests
    assert lookup.params["id_list"] == "2610.26648v1"
    assert str(download) == SOURCE_URL.format(arxiv_id="2610.26648v1")

    source.paper(
        parse_arxiv_id("2610.26648v1")
    )  # again: the listing from the cache, the paper from memory
    assert len(arxiv.requests) == 2


def test_identifier_without_version_is_resolved_to_the_version_arxiv_names(tmp_path):
    arxiv = FakeArxiv()
    paper = arxiv.make(tmp_path).paper(parse_arxiv_id("2610.26648"))

    assert paper.meta.arxiv_id == "2610.26648v1"
    assert arxiv.requests[0].params["id_list"] == "2610.26648"
    assert (
        arxiv.requests[1].path == "/e-print/2610.26648v1"
    )  # the download is asked for with the version


@pytest.mark.parametrize(
    ("api", "source", "kind"),
    [
        ((200, EMPTY), (200, DOWNLOAD), ErrorKind.NOT_FOUND),  # arXiv lists no such paper
        ((200, ERROR), (200, DOWNLOAD), ErrorKind.NOT_FOUND),  # arXiv cannot read the identifier
        ((400, ERROR), (200, DOWNLOAD), ErrorKind.NOT_FOUND),
        ((200, FEED), (404, b""), ErrorKind.NO_FULL_TEXT),  # listed, but nothing to download
        ((200, FEED), (200, b"%PDF-1.7 ..."), ErrorKind.NO_FULL_TEXT),
        ((200, FEED), (200, b"\\documentclass{article} no document"), ErrorKind.PARSE_ERROR),
        ((503, b""), (200, DOWNLOAD), ErrorKind.UPSTREAM_BUSY),
        ((200, FEED), (429, b""), ErrorKind.UPSTREAM_BUSY),
    ],
)
def test_failures_are_reported_in_the_sources_terms(tmp_path, api, source, kind):
    with pytest.raises(SourceError) as caught:
        FakeArxiv(api, source).make(tmp_path).paper(parse_arxiv_id("2610.26648v1"))
    assert caught.value.kind is kind
    assert "2610.26648v1" in caught.value.detail


class Flaky(FakeArxiv):
    """Answers the first request of one kind with `bad` (status 200), every later one correctly."""

    def __init__(self, kind: str, bad: bytes):
        super().__init__()
        self.kind, self.bad, self.done = kind, bad, False

    def handler(self, request: httpx2.Request) -> httpx2.Response:
        response = super().handler(request)
        kind = "api" if request.url.path == "/api/query" else "source"
        if kind == self.kind and not self.done:
            self.done = True
            return httpx2.Response(200, content=self.bad)
        return response


@pytest.mark.parametrize(
    ("kind", "bad", "reported_as"),
    [
        ("api", EMPTY, ErrorKind.NOT_FOUND),  # 200, but lists nothing
        ("api", ERROR, ErrorKind.NOT_FOUND),  # 200, but the API's error feed
        ("api", b"<html><body>Rate exceeded.</body>", ErrorKind.UPSTREAM_BUSY),  # not a feed
        # What follows came in place of the paper's files. That says nothing about the
        # paper, so it is arXiv that has not answered: the model is told to try again.
        ("source", b"<html><body>Not the paper.</body></html>", ErrorKind.UPSTREAM_BUSY),
        ("source", b"", ErrorKind.UPSTREAM_BUSY),
        ("source", b"\x1f\x8b broken gzip", ErrorKind.UPSTREAM_BUSY),
        ("source", DOWNLOAD[:10] + b"\x07" + bytes(20), ErrorKind.UPSTREAM_BUSY),  # zlib.error
        ("source", plain_tar({"paper.tex": SAMPLE_LATEX.encode()})[:700], ErrorKind.UPSTREAM_BUSY),
    ],
)
def test_one_unusable_answer_is_not_served_from_the_cache_afterwards(
    tmp_path, kind, bad, reported_as
):
    # The cache never expires. Kept, a single bad answer would hide the paper for good.
    arxiv = Flaky(kind, bad)
    source = arxiv.make(tmp_path)

    with pytest.raises(SourceError) as caught:
        source.paper(parse_arxiv_id("2610.26648v1"))
    assert caught.value.kind is reported_as
    assert "2610.26648v1" in caught.value.detail

    assert source.paper(parse_arxiv_id("2610.26648v1")).meta.arxiv_id == "2610.26648v1"


def test_a_search_without_results_is_asked_again_the_next_time(tmp_path):
    arxiv = Flaky("api", EMPTY)
    source = arxiv.make(tmp_path)

    assert source.search(SearchQuery("excess")).total == 0
    assert len(source.search(SearchQuery("excess")).papers) == 2
    source.search(SearchQuery("excess"))  # a listing with papers is kept
    assert len(arxiv.requests) == 2


@pytest.mark.parametrize(
    ("download", "kind"),
    [
        (b"%PDF-1.7 ...", ErrorKind.NO_FULL_TEXT),  # no TeX source
        (
            tar_gz(
                {"paper.tex": b"\\documentclass{article}\\begin{document}Short.\\end{document}"}
            ),
            ErrorKind.PARSE_ERROR,
        ),
        # A paper in plain TeX, as one file and as an archive: no \begin{document} anywhere.
        (b"\\input harvmac\n\\Title{HUTP-91/A001}{Plain TeX}\n\\bye\n", ErrorKind.PARSE_ERROR),
        (
            tar_gz({"paper.tex": b"\\input harvmac\n\\bye\n", "fig.ps": b"%!PS"}),
            ErrorKind.PARSE_ERROR,
        ),
        # A file of the paper is read in a way that is not followed.
        (
            tar_gz({"paper.tex": SAMPLE_LATEX.replace("Thanks.", "\\import{a/}{b}").encode()}),
            ErrorKind.PARSE_ERROR,
        ),
    ],
)
def test_a_real_download_that_cannot_be_read_stays_in_the_cache(tmp_path, download, kind):
    # Asking again would bring the same bytes, so it is not asked again.
    arxiv = FakeArxiv(source=(200, download))
    for _ in range(3):
        with pytest.raises(SourceError) as caught:
            arxiv.make(tmp_path).paper(parse_arxiv_id("2610.26648v1"))
        assert caught.value.kind is kind
    assert [url.path for url in arxiv.requests] == ["/api/query", "/e-print/2610.26648v1"]


@pytest.mark.parametrize("where", ["/api/query", "/e-print/2610.26648v1"])
@pytest.mark.parametrize(
    "answer",
    [
        lambda request: httpx2.Response(302, headers={"Location": str(request.url)}),
        lambda request: httpx2.Response(
            200, headers={"Content-Encoding": "gzip"}, content=b"this is not gzip"
        ),
    ],
    ids=["a redirect that never ends", "a body that cannot be decoded"],
)
def test_an_answer_that_cannot_be_read_at_all_is_upstream_busy(tmp_path, where, answer):
    arxiv = FakeArxiv()

    def handler(request: httpx2.Request) -> httpx2.Response:
        return answer(request) if request.url.path == where else arxiv.handler(request)

    source = ArxivSource(
        Fetcher(tmp_path, transport=httpx2.MockTransport(handler), sleep=lambda seconds: None)
    )
    with pytest.raises(SourceError) as caught:
        source.paper(parse_arxiv_id("2610.26648v1"))
    assert caught.value.kind is ErrorKind.UPSTREAM_BUSY


@pytest.mark.parametrize(
    ("api", "kind"),
    [
        ((200, ERROR), ErrorKind.BAD_QUERY),  # the API's error feed
        ((400, b""), ErrorKind.BAD_QUERY),
        ((403, b""), ErrorKind.UPSTREAM_BUSY),  # arXiv refuses this client
        ((200, b"<html>Rate exceeded.</html>"), ErrorKind.UPSTREAM_BUSY),  # not a feed
        ((200, FEED.replace(b"<published>20", b"<published>soon 20")), ErrorKind.UPSTREAM_BUSY),
        ((503, b""), ErrorKind.UPSTREAM_BUSY),
    ],
)
def test_a_failed_search_is_reported_in_the_sources_terms(tmp_path, api, kind):
    with pytest.raises(SourceError) as caught:
        FakeArxiv(api=api).make(tmp_path).search(SearchQuery("dark matter"))
    assert caught.value.kind is kind
    assert caught.value.detail == "dark matter"


def test_a_refused_lookup_is_not_taken_for_a_missing_paper(tmp_path):
    with pytest.raises(SourceError) as caught:
        FakeArxiv(api=(403, b"")).make(tmp_path).paper(parse_arxiv_id("2610.26648v1"))
    assert caught.value.kind is ErrorKind.UPSTREAM_BUSY


def test_the_latest_version_is_asked_for_every_time(tmp_path):
    # "Latest" changes when the paper is replaced, and the cache never expires.
    arxiv = FakeArxiv()
    source = arxiv.make(tmp_path)

    for _ in range(2):
        assert source.listing(parse_arxiv_id("2610.26648")).arxiv_id == "2610.26648v1"
    assert [url.params["id_list"] for url in arxiv.requests] == ["2610.26648", "2610.26648"]

    for _ in range(2):
        source.listing(parse_arxiv_id("2610.26648v1"))  # a pinned version: kept as before
    assert len(arxiv.requests) == 3


def test_an_answer_about_the_latest_version_kept_by_an_older_program_is_not_used(tmp_path):
    arxiv = FakeArxiv()
    source = arxiv.make(tmp_path)
    Fetcher(tmp_path, transport=httpx2.MockTransport(arxiv.handler)).get(
        API_URL, {"id_list": "2610.26648", "max_results": "1"}
    )
    assert len(arxiv.requests) == 1  # now in the cache, as the older program left it

    source.listing(parse_arxiv_id("2610.26648"))

    assert len(arxiv.requests) == 2
    assert list(tmp_path.glob("*/*")) == []  # and it is gone from the cache


def test_timeout_is_reported_as_timeout(tmp_path):
    def handler(request):
        raise httpx2.ReadTimeout("slow")

    source = ArxivSource(
        Fetcher(tmp_path, transport=httpx2.MockTransport(handler), sleep=lambda seconds: None)
    )
    with pytest.raises(SourceError) as caught:
        source.search(SearchQuery("excess"))
    assert caught.value.kind is ErrorKind.TIMEOUT
