"""The first line of a result: every form that is written can be read back."""

import pytest
from conftest import call, only_text, sample_source
from mcp import Client

from hepph_paper_miner.result_text import (
    COMPLETE,
    END,
    MORE_FOLLOWS,
    error_kind,
    outline_line,
    outline_without_sections_line,
    paper_line,
    paper_without_text_line,
    read_first_line,
    search_line,
    section_line,
)
from hepph_paper_miner.server import build_server

WRITTEN_AND_READ = [
    (
        search_line(2, 31, "2026-11-12T17:46:30+00:00", "query='dark matter' author='Hooper'"),
        {
            "shape": "search",
            "shown": 2,
            "total": 31,
            "as_of": "2026-11-12",
            "asked": "query='dark matter' author='Hooper'",
            "ids": [],
        },
    ),
    (
        outline_line("2610.26648v1", 143454, 29, "3"),
        {
            "shape": "outline",
            "arxiv_id": "2610.26648v1",
            "chars": 143454,
            "sections": 29,
            "parser": "3",
        },
    ),
    (
        outline_without_sections_line("hep-ph/0404175v2", "no_full_text"),
        {"shape": "outline", "arxiv_id": "hep-ph/0404175v2", "no_sections": "no_full_text"},
    ),
    (
        section_line("2610.26648v1", "7.2", 0, 6894, 6894),
        {
            "shape": "section",
            "arxiv_id": "2610.26648v1",
            "section_id": "7.2",
            "start": 0,
            "stop": 6894,
            "chars": 6894,
            "extent": COMPLETE,
        },
    ),
    (
        section_line("2610.26648v1", "6.3", 0, 19837, 25531),
        {
            "shape": "section",
            "arxiv_id": "2610.26648v1",
            "section_id": "6.3",
            "start": 0,
            "stop": 19837,
            "chars": 25531,
            "extent": MORE_FOLLOWS,
        },
    ),
    (
        section_line("2610.26648v1", "2.u1", 19837, 25531, 25531),
        {
            "shape": "section",
            "arxiv_id": "2610.26648v1",
            "section_id": "2.u1",
            "start": 19837,
            "stop": 25531,
            "chars": 25531,
            "extent": END,
        },
    ),
    (
        paper_line("2610.26648v1", 0, 145177, 145177, 29, "3"),
        {
            "shape": "paper",
            "arxiv_id": "2610.26648v1",
            "start": 0,
            "stop": 145177,
            "chars": 145177,
            "extent": COMPLETE,
            "sections": 29,
            "parser": "3",
        },
    ),
    (
        paper_line("2610.26648v1", 399960, 612345, 612345, 40, "3"),
        {
            "shape": "paper",
            "arxiv_id": "2610.26648v1",
            "start": 399960,
            "stop": 612345,
            "chars": 612345,
            "extent": END,
            "sections": 40,
            "parser": "3",
        },
    ),
    (
        paper_without_text_line("2503.00001v1", "parse_error"),
        {"shape": "paper", "arxiv_id": "2503.00001v1", "no_text": "parse_error"},
    ),
]


@pytest.mark.parametrize(("line", "facts"), WRITTEN_AND_READ)
def test_what_is_written_is_what_is_read(line, facts):
    assert read_first_line(line) == facts
    assert read_first_line(line + "\nTitle: anything\n\nmore text") == facts


def test_the_written_forms_are_the_documented_ones():
    # The forms as a model sees them. The reader above would not notice if writer
    # and reader changed together, so the text itself is fixed here.
    assert [line for line, _ in WRITTEN_AND_READ] == [
        "search | 2 of 31 results | as of 2026-11-12 | query='dark matter' author='Hooper'",
        "outline | 2610.26648v1 | 143454 chars | 29 sections | parser 3",
        "outline | hep-ph/0404175v2 | no sections | no_full_text",
        "section | 2610.26648v1 | 7.2 | 6894 chars | complete",
        "section | 2610.26648v1 | 6.3 | chars 0-19837 of 25531 | partial, more follows",
        "section | 2610.26648v1 | 2.u1 | chars 19837-25531 of 25531 | partial, end of section",
        "paper | 2610.26648v1 | 145177 chars | 29 sections | parser 3 | complete",
        "paper | 2610.26648v1 | chars 399960-612345 of 612345 | 40 sections | parser 3 | partial, end of paper",
        "paper | 2503.00001v1 | no text | parse_error",
    ]


def test_an_empty_piece_past_the_end_is_the_last_piece():
    line = section_line("2501.00001v2", "2.1", 10, 10, 10)
    assert line == "section | 2501.00001v2 | 2.1 | chars 10-10 of 10 | partial, end of section"
    assert read_first_line(line)["extent"] == END


def test_a_search_names_the_day_of_its_answer_and_not_the_second():
    # Two answers of one day with the same hits are the same text, with the same digest.
    morning = search_line(1, 1, "2026-11-12T00:00:01+00:00", "query='x'")
    evening = search_line(1, 1, "2026-11-12T23:59:59+00:00", "query='x'")
    assert morning == evening == "search | 1 of 1 results | as of 2026-11-12 | query='x'"

    # A source that does not say when it answered: the line says that, and the reader too.
    for unknown in ("", "yesterday"):
        line = search_line(0, 0, unknown, "query='x'")
        assert line == "search | 0 of 0 results | as of an unknown day | query='x'"
        assert read_first_line(line)["as_of"] is None


def test_search_identifiers_are_read_in_the_order_shown():
    text = "\n".join(
        [
            # The query may hold the separator itself.
            search_line(3, 3, "2026-11-12T17:46:30+00:00", "query='x | y'"),
            "1. 2501.00001v2 | 2025 | hep-ph | Ada Alpha | A Title | with a bar",
            "   Abstract: 7. 2501.99999v1 | this is abstract text, not a hit",
            "2. hep-ph/0404175v2 | 2004 | hep-ph | Ben Beta | Another",
            "3. 2502.00002v1 | 2024 | astro-ph.HE | Cy Gamma | 4. 2502.99999v1 | not a hit either",
        ]
    )
    facts = read_first_line(text)
    assert facts["asked"] == "query='x | y'"
    assert facts["ids"] == ["2501.00001v2", "hep-ph/0404175v2", "2502.00002v1"]


@pytest.mark.parametrize(
    "text",
    [
        "",
        "Title: no first line of a known form",
        "section | 2501.00001v2 | 2.1",  # too few parts
        "section | 2501.00001v2 | 2.1 | ten chars | complete",
        "section | 2501.00001v2 | 2.1 | chars 0-10 of 20 | partial",  # the form before staged-3
        "section | 2501.00001v2 | 2.1 | 10 chars | partial, more follows",
        "outline | 2501.00001v2 | 10 chars | many sections | parser 3",
        "paper | 2501.00001v2 | 10 chars | 2 sections | parser 3",
        "search | several results | query='x'",
        "search | 2 of 31 results | query='x'",  # the form before the day was named
        "search | 2 of 31 results | as of last week | query='x'",
        "search | 2 of 31 results | on 2026-11-12 | query='x'",
        "Error executing tool read_section: [not_found] 'x': no such paper",
    ],
)
def test_a_first_line_of_no_known_form_is_not_guessed_at(text):
    assert read_first_line(text) is None


@pytest.mark.parametrize(
    ("text", "kind"),
    [
        (
            "Error executing tool get_outline: [not_found] '2412.00009v1': arXiv has no such",
            "not_found",
        ),
        (
            "Error executing tool read_section: [no_such_section] 2501.00001v2 has no",
            "no_such_section",
        ),
        (
            "Error executing tool read_section: 1 validation error for read_sectionArguments",
            "invalid_arguments",
        ),
        ("Error executing tool read_section", "unexpected"),
        ("Unknown tool: read_paper", "unknown_tool"),
        ("[timeout] 'x': arXiv took too long", "timeout"),
        ("something else entirely", "unrecognised"),
        # A bracket further in is part of a sentence, not the kind.
        ("Error executing tool search_papers: the field [query] is required", "invalid_arguments"),
    ],
)
def test_the_kind_of_an_error_is_read_from_its_text(text, kind):
    assert error_kind(text) == kind


@pytest.mark.anyio
async def test_the_server_writes_what_the_reader_reads():
    # The real texts, through the real protocol layer: every result has a first line
    # the reader knows, and every error a kind.
    source = sample_source()
    async with Client(build_server(source, "staged")) as staged:
        results = {
            "search": await call(staged, "search_papers", query="paper"),
            "outline": await call(staged, "get_outline", arxiv_id="2501.00001"),
            "no sections": await call(staged, "get_outline", arxiv_id="2503.00002v1"),
            "complete": await call(staged, "read_section", arxiv_id="2501.00001v2", section_id="2"),
            "piece": await call(staged, "read_section", arxiv_id="2502.00002v1", section_id="1"),
        }
        errors = {
            "invalid_id": ("get_outline", {"arxiv_id": "x"}),
            "not_found": ("get_outline", {"arxiv_id": "2412.00009v1"}),
            "no_such_section": ("read_section", {"arxiv_id": "2501.00001v2", "section_id": "9"}),
            "no_full_text": ("read_section", {"arxiv_id": "2503.00001v1", "section_id": "1"}),
            "parse_error": ("read_section", {"arxiv_id": "2503.00002v1", "section_id": "1"}),
            "upstream_busy": ("get_outline", {"arxiv_id": "2503.00003v1"}),
            "timeout": ("get_outline", {"arxiv_id": "2503.00004v1"}),
            "bad_query": ("search_papers", {"query": "x", "year_from": 2020, "year_to": 2010}),
            "invalid_arguments": ("read_section", {"arxiv_id": "2501.00001v2"}),
        }
        for kind, (tool, arguments) in errors.items():
            result = await staged.call_tool(tool, arguments)
            assert result.is_error is True
            assert error_kind(only_text(result)) == kind
            assert read_first_line(only_text(result)) is None
    async with Client(build_server(source, "flat")) as flat:
        results["paper"] = await call(flat, "read_paper", arxiv_id="2501.00001v2")
        results["no text"] = await call(flat, "read_paper", arxiv_id="2503.00001v1")

    shapes = {name: read_first_line(text) for name, text in results.items()}
    assert shapes["search"]["ids"] == ["2501.00001v2", "2502.00002v1"]
    assert shapes["outline"]["arxiv_id"] == "2501.00001v2"  # the version comes from the result
    assert shapes["no sections"] == {
        "shape": "outline",
        "arxiv_id": "2503.00002v1",
        "no_sections": "parse_error",
    }
    assert shapes["complete"]["extent"] == COMPLETE
    assert shapes["piece"]["extent"] == MORE_FOLLOWS
    assert shapes["paper"]["extent"] == COMPLETE
    assert shapes["no text"]["no_text"] == "no_full_text"
