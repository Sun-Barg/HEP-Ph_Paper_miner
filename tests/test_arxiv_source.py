"""The arXiv source end to end, with arXiv played by a scripted transport. No network."""

import httpx2
import pytest
from conftest import FIXTURES, SAMPLE_LATEX, tar_gz

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
    assert paper.parser_version == "1"
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


def test_timeout_is_reported_as_timeout(tmp_path):
    def handler(request):
        raise httpx2.ReadTimeout("slow")

    source = ArxivSource(
        Fetcher(tmp_path, transport=httpx2.MockTransport(handler), sleep=lambda seconds: None)
    )
    with pytest.raises(SourceError) as caught:
        source.search(SearchQuery("excess"))
    assert caught.value.kind is ErrorKind.TIMEOUT
