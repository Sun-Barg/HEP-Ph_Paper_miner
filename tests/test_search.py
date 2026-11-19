"""The arXiv API: request parameters out, Atom answer in. No network."""

import pytest
from conftest import FIXTURES

from hepph_paper_miner.sources.arxiv_search import (
    FeedError,
    lookup_params,
    parse_feed,
    search_params,
)
from hepph_paper_miner.sources.base import SearchQuery


def query_string(**arguments) -> str:
    return search_params(SearchQuery(**arguments))["search_query"]


def test_every_word_must_match_and_a_quoted_phrase_stays_together():
    assert (
        query_string(query='galactic "dark matter" excess')
        == 'all:galactic AND all:"dark matter" AND all:excess'
    )


def test_filters_are_added_as_further_clauses():
    built = search_params(
        SearchQuery(
            "excess",
            author="Dan Hooper",
            category="astro-ph.HE",
            year_from=2014,
            year_to=2016,
            max_results=7,
        )
    )
    assert built == {
        "search_query": 'all:excess AND au:"Dan Hooper" AND cat:astro-ph.HE AND submittedDate:[201401010000 TO 201612312359]',
        "start": "0",
        "max_results": "7",
        "sortBy": "relevance",
        "sortOrder": "descending",
    }


def test_an_open_year_range_is_closed_at_the_ends_of_arxiv():
    assert query_string(query="x", year_from=2020).endswith(
        "submittedDate:[202001010000 TO 209912312359]"
    )
    assert query_string(query="x", year_to=2010).endswith(
        "submittedDate:[199101010000 TO 201012312359]"
    )


@pytest.mark.parametrize(
    ("typed", "sent"),
    [
        (
            "ti:excess) OR (all:x",
            "all:ti AND all:excess AND all:all AND all:x",
        ),  # no query language from outside
        ("gamma-ray  Fermi's", "all:gamma-ray AND all:Fermi's"),
        ("B - L ' . -- U(1)", "all:B AND all:L AND all:U AND all:1"),  # no word without a letter
        ('"- dark . matter -"', 'all:"dark matter"'),
        ('"" ()', None),  # nothing left to search for
    ],
)
def test_characters_of_the_query_language_never_reach_arxiv(typed, sent):
    built = search_params(SearchQuery(typed))
    assert (built and built["search_query"]) == sent


@pytest.mark.parametrize(
    ("typed", "sent"),
    [
        # A title typed as it stands. With its small words sent along, arXiv found nothing.
        (
            "Dark Matter Interpretations of the Galactic Center Gamma-Ray Excess with 18 Years "
            "of Fermi-LAT Data and the FL16Y Source Catalog",
            "all:Dark AND all:Matter AND all:Interpretations AND all:Galactic AND all:Center "
            "AND all:Gamma-Ray AND all:Excess AND all:18 AND all:Years AND all:Fermi-LAT "
            "AND all:Data AND all:FL16Y AND all:Source AND all:Catalog",
        ),
        ("A Tale of Tails", "all:Tale AND all:Tails"),
        ("IN THE galaxy", "all:galaxy"),  # in capitals too
        # Only whole words: these merely contain one, or join one to another word.
        (
            "theory android often no-scale",
            "all:theory AND all:android AND all:often AND all:no-scale",
        ),
        # A phrase stays as it was typed: inside one, arXiv copes with these words.
        ('"The Fermi Bubbles" and "an excess"', 'all:"The Fermi Bubbles" AND all:"an excess"'),
        ('"the"', None),  # one word in quotes is a word
        ("of the and", None),  # nothing left to search for
    ],
)
def test_words_that_arxiv_does_not_look_up_are_left_out(typed, sent):
    built = search_params(SearchQuery(typed))
    assert (built and built["search_query"]) == sent


def test_an_author_filter_keeps_such_a_word_because_it_can_be_a_name():
    assert query_string(query="excess", author="An") == 'all:excess AND au:"An"'
    assert query_string(query="of", author="Will") == 'au:"Will"'  # the filter alone is searched


def test_an_author_filter_without_a_letter_is_dropped():
    assert query_string(query="x", author=" - . ' ") == "all:x"
    assert query_string(query="x", author="O'Brien-Smith, J.") == 'all:x AND au:"O\'Brien-Smith J."'


def test_lookup_asks_for_one_identifier():
    assert lookup_params("2610.26648v1") == {"id_list": "2610.26648v1", "max_results": "1"}


def test_feed_is_read_into_papers_in_order():
    found = parse_feed((FIXTURES / "api_search.xml").read_bytes())
    assert found.total == 37
    first, second = found.papers

    assert first.arxiv_id == "2610.26648v1"
    assert first.title.startswith(
        "Dark Matter Interpretations of the Galactic Center Gamma-Ray Excess with 18 Years"
    )
    assert "\n" not in first.title and "  " not in first.title  # line breaks of the feed are gone
    assert first.authors == ("Sang Hwan Kim", "Hae Barg Kang", "Seodong Shin")
    assert (first.year, first.primary_category) == (2026, "hep-ph")
    assert first.abstract == "An invented abstract for the test. It runs over two lines."

    assert (second.arxiv_id, second.year, len(second.authors)) == ("hep-ph/0404175v2", 2004, 5)


@pytest.mark.parametrize("scheme", [b"http", b"https"])  # arXiv has written the id both ways
def test_error_feed_raises_with_arxivs_message(scheme):
    body = (FIXTURES / "api_error.xml").read_bytes()
    body = body.replace(b"http://arxiv.org/api/errors", scheme + b"://arxiv.org/api/errors")
    with pytest.raises(FeedError, match="incorrect id format for 1234.12345"):
        parse_feed(body)


@pytest.mark.parametrize("body", [b"<html><body>Rate exceeded.</body></html>", b"<feed/>"])
def test_xml_that_is_not_an_atom_feed_is_not_an_empty_result(body):
    with pytest.raises(ValueError, match="not an Atom feed"):
        parse_feed(body)


def test_feed_without_entries_is_an_empty_result():
    found = parse_feed((FIXTURES / "api_empty.xml").read_bytes())
    assert (found.papers, found.total) == ((), 0)
