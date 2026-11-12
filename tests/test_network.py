"""Real requests to arXiv. Not run by default:  uv run pytest -m network

Three requests, three seconds apart, into a temporary cache. They check what the
offline tests cannot: that arXiv's answers look the way the hand-written test
data assumes, and that a real download splits like the copy kept in the repository.
"""

import pytest
from test_own_paper import EXPECTED

from hepph_paper_miner.http import Fetcher
from hepph_paper_miner.sources.arxiv import ArxivSource
from hepph_paper_miner.sources.base import SearchQuery, parse_arxiv_id

pytestmark = pytest.mark.network


@pytest.fixture(scope="module")
def source(tmp_path_factory) -> ArxivSource:
    return ArxivSource(
        Fetcher(tmp_path_factory.mktemp("cache"), user_agent="hepph-paper-miner/tests")
    )


def test_search_finds_papers_and_their_identifiers_carry_a_version(source):
    found = source.search(
        SearchQuery('"galactic center" excess "dark matter"', category="hep-ph", max_results=3)
    )
    assert found.total >= len(found.papers) == 3
    for paper in found.papers:
        assert parse_arxiv_id(paper.arxiv_id).version is not None, paper.arxiv_id
        assert paper.title and paper.authors and paper.year >= 1991


def test_real_download_of_the_kept_paper_splits_like_the_kept_copy(source):
    paper = source.paper(parse_arxiv_id("2610.26648v1"))
    assert paper.meta.title.startswith("Dark Matter Interpretations of the Galactic Center")
    assert [(s.section_id, s.chars, s.title) for s in paper.sections] == EXPECTED
