"""Real requests to arXiv. Not run by default:  uv run pytest -m network

Seven requests, three seconds apart, into a temporary cache. They check what the
offline tests cannot: that arXiv's answers look the way the hand-written test
data assumes, and that a real download splits like the copy kept in the repository.

The last two are about the list a sample of the survey is drawn from (survey/listing.py).
A piece of that list counts only when every paper on it says that its first version
was submitted inside the window that was asked for, and the manual of the API does not
say which version `submittedDate` is about: here the API is asked.
"""

import pytest
from test_own_paper import EXPECTED

from hepph_paper_miner.http import Fetcher
from hepph_paper_miner.sources.arxiv import ArxivSource
from hepph_paper_miner.sources.base import SearchQuery, parse_arxiv_id
from hepph_paper_miner.survey.listing import list_piece
from hepph_paper_miner.survey.plan import Window

pytestmark = pytest.mark.network


@pytest.fixture(scope="module")
def fetcher(tmp_path_factory) -> Fetcher:
    # One Fetcher for the whole module: the three seconds are kept between its requests.
    return Fetcher(tmp_path_factory.mktemp("cache"), user_agent="hepph-paper-miner/tests")


@pytest.fixture(scope="module")
def source(fetcher) -> ArxivSource:
    return ArxivSource(fetcher)


def test_search_finds_papers_and_their_identifiers_carry_a_version(source):
    found = source.search(
        SearchQuery('"galactic center" excess "dark matter"', category="hep-ph", max_results=3)
    )
    assert found.total >= len(found.papers) == 3
    for paper in found.papers:
        assert parse_arxiv_id(paper.arxiv_id).version is not None, paper.arxiv_id
        assert paper.title and paper.authors and paper.year >= 1991


def test_a_title_typed_as_it_stands_finds_its_paper(source):
    # arXiv does not look up the small words of a title ("of", "the", "with", "and"),
    # so they are left out of the request. Sent along, they made this search find nothing.
    title = (
        "Dark Matter Interpretations of the Galactic Center Gamma-Ray Excess with 18 Years "
        "of Fermi-LAT Data and the FL16Y Source Catalog"
    )
    found = source.search(SearchQuery(title))
    assert "2610.26648" in [parse_arxiv_id(paper.arxiv_id).base for paper in found.papers]


def test_real_download_of_the_kept_paper_splits_like_the_kept_copy(source):
    paper = source.paper(parse_arxiv_id("2610.26648v1"))
    assert paper.meta.title.startswith("Dark Matter Interpretations of the Galactic Center")
    assert [(s.section_id, s.chars, s.title) for s in paper.sections] == EXPECTED


def test_a_piece_of_the_list_comes_whole_and_its_papers_were_first_submitted_in_the_window(fetcher):
    # A small category in one month: one page. list_piece raises when the answer is not
    # whole (the total, the versions, the primary categories) or when a paper says that
    # its first version is from outside the window, so that it returns is the check.
    piece = list_piece(fetcher, "hep-lat", Window("202608010000", "202608312359"))

    assert piece.total == len(piece.papers) >= len(piece.own) > 0
    assert piece.pages == 1 and piece.from_cache == 0
    assert all(parse_arxiv_id(paper.arxiv_id).version is not None for paper in piece.papers)
    # The answer to `cat:` holds papers that are only cross-listed to the category.
    assert {paper.primary for paper in piece.own} == {"hep-lat"}


def test_a_window_in_which_nothing_was_submitted_is_answered_with_nothing(fetcher):
    # January 1990, before arXiv had a paper: its identifiers begin in 1991. The form of
    # "no papers" is what the offline tests take it to be (a feed without entries that
    # says its total is 0), and it is asked for twice before it is believed.
    piece = list_piece(fetcher, "hep-lat", Window("199001010000", "199001312359"))
    assert (piece.total, piece.papers, piece.pages) == (0, (), 2)
