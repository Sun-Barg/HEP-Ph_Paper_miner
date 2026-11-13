"""The flat layout: a search that shows abstracts, and one tool that returns a whole paper."""

import re

import pytest
from conftest import (
    FAILING,
    OWN_PAPER,
    SAMPLE_META,
    call,
    failure,
    filler,
    only_text,
    sample_source,
    tar_gz,
)
from mcp import Client

from hepph_paper_miner import server
from hepph_paper_miner.result_text import END, MORE_FOLLOWS, read_first_line
from hepph_paper_miner.server import TOOLSET_VERSION, build_server, explain, full_text
from hepph_paper_miner.sources.arxiv_latex import PARSER_VERSION, parse_source
from hepph_paper_miner.sources.base import ErrorKind, Paper, PaperMeta, Section, SourceError
from hepph_paper_miner.sources.fixture import FixtureSource, paper_from_latex

MARKER = re.compile(r"=== (\S+) \| (.*) \| (\d+) chars ===")


@pytest.fixture
def source() -> FixtureSource:
    return sample_source()


@pytest.fixture
async def client(source):
    async with Client(build_server(source, "flat"), raise_exceptions=True) as connected:
        yield connected


def without_markers(text: str) -> str:
    return "\n".join(line for line in text.split("\n") if not MARKER.fullmatch(line))


@pytest.mark.anyio
async def test_two_tools_with_text_output_only(client):
    tools = {tool.name: tool for tool in (await client.list_tools()).tools}
    assert list(tools) == ["search_papers", "read_paper"]
    for tool in tools.values():
        assert tool.output_schema is None  # one channel: text
        assert tool.description
    assert tools["read_paper"].input_schema["required"] == ["arxiv_id"]

    assert client.server_info.version == TOOLSET_VERSION["flat"] == "flat-3"
    # Nothing a model reads in this layout may name a tool it does not have.
    told = client.instructions + "".join(tool.description for tool in tools.values())
    assert "read_paper" in told
    assert "get_outline" not in told and "read_section" not in told


@pytest.mark.anyio
async def test_search_takes_the_same_arguments_in_both_layouts(client, source):
    flat = {tool.name: tool for tool in (await client.list_tools()).tools}
    async with Client(build_server(source, "staged")) as other:
        staged = {tool.name: tool for tool in (await other.list_tools()).tools}
    # The comparison is about how a paper is read. How one is searched for differs in
    # one thing only: whether the answer shows abstracts.
    assert flat["search_papers"].input_schema == staged["search_papers"].input_schema


@pytest.mark.anyio
async def test_search_shows_the_abstract_under_every_hit(client):
    text = await call(client, "search_papers", query="sample", category="hep-ph", year_from=2020)
    assert text.splitlines() == [
        "search | 1 of 1 results | query='sample' category='hep-ph' year_from=2020",
        "1. 2501.00001v2 | 2025 | hep-ph | Ada Alpha, Ben Beta | A Sample Paper",
        f"   Abstract: {SAMPLE_META.abstract}",
    ]
    assert read_first_line(text)["ids"] == ["2501.00001v2"]


@pytest.mark.anyio
async def test_an_abstract_stays_on_one_line_whatever_the_listing_holds():
    # A program reads the identifiers from the lines that begin with a rank. An
    # abstract with line breaks could put such a line where no hit is.
    meta = PaperMeta(
        "2504.00002v1", "Broken", ("Ian Iota",), 2025, "hep-ph", "First\n9. 2504.99999v1 | x"
    )
    source = FixtureSource([Paper(meta, (Section("1", "Only", 1, "Text."),), PARSER_VERSION)])
    async with Client(build_server(source, "flat"), raise_exceptions=True) as connected:
        text = await call(connected, "search_papers", query="broken")
    assert text.splitlines()[2] == "   Abstract: First 9. 2504.99999v1 | x"
    assert read_first_line(text)["ids"] == ["2504.00002v1"]


@pytest.mark.anyio
async def test_a_whole_paper_comes_back_with_a_marker_in_front_of_every_section(client, source):
    paper = source.paper_by_id("2501.00001v2")
    text = await call(client, "read_paper", arxiv_id="2501.00001v2")
    head, body = text.split("\nText:\n\n", 1)

    assert head.splitlines() == [
        f"paper | 2501.00001v2 | {len(body)} chars | 8 sections | parser {PARSER_VERSION} | complete",
        "Title: A Sample Paper",
        "Authors: Ada Alpha, Ben Beta",
        "Listed: 2025 | hep-ph",
        f"Abstract: {SAMPLE_META.abstract}",
    ]
    assert body == full_text(paper)
    markers = [
        MARKER.fullmatch(line).groups() for line in body.split("\n") if MARKER.fullmatch(line)
    ]
    assert markers == [(s.section_id, s.title, str(s.chars)) for s in paper.sections]
    # A marker stands in front of the heading of its subsection.
    assert "=== 2.1 | Data | 10 chars ===\n\\subsection{Data}\nData text." in body
    assert source.calls == [("listing", "2501.00001v2"), ("paper", "2501.00001v2")]


@pytest.mark.anyio
async def test_identifier_without_version_is_answered_with_the_full_identifier(client):
    text = await call(client, "read_paper", arxiv_id="2501.00001")
    assert text.startswith("paper | 2501.00001v2 | ")


def test_markers_are_whole_lines_and_take_no_text_away(source):
    for paper in (source.paper_by_id("2501.00001v2"), source.paper_by_id("2502.00002v1")):
        whole = "\n\n".join(section.text for section in paper.sections if section.level == 1)
        assert without_markers(full_text(paper)) == whole


def test_every_section_of_the_real_paper_gets_its_marker():
    data = tar_gz({p.name: p.read_bytes() for p in OWN_PAPER.iterdir() if p.suffix != ".md"})
    meta = PaperMeta("2610.26648v1", "The kept paper", ("A",), 2026, "hep-ph", "Abstract.")
    paper = Paper(meta, parse_source(data), PARSER_VERSION)
    text = full_text(paper)

    found = [
        line.split(" | ")[0].removeprefix("=== ")
        for line in text.split("\n")
        if MARKER.fullmatch(line)
    ]
    assert found == [section.section_id for section in paper.sections]
    assert len(found) == 29
    whole = "\n\n".join(section.text for section in paper.sections if section.level == 1)
    assert without_markers(text) == whole


def test_text_under_no_section_heading_is_part_of_the_whole_paper():
    # Subsections before the first section, and what follows \appendix without a
    # section, lie in sections of their own. They used to lie in none, and the whole
    # paper, which is the text of its sections, came back without them.
    latex = (
        "\\documentclass{article}\\begin{document}\n\\maketitle\n"
        "\\subsection{Notation}\nSIGNS " + filler(100) + "\n"
        "\\section{One}\nFIRST " + filler(100) + "\n"
        "\\appendix\nLEAD-IN " + filler(100) + "\n\\subsection{Proof}\nPROOF.\n"
        "\\end{document}"
    )
    meta = PaperMeta("2504.00005v1", "T", ("A",), 2025, "hep-ph", "A.")
    paper = paper_from_latex(meta, latex)
    text = full_text(paper)

    assert [section.section_id for section in paper.sections] == ["0", "0.1", "1", "u1", "u1.1"]
    marked = [
        MARKER.fullmatch(line).group(1) for line in text.split("\n") if MARKER.fullmatch(line)
    ]
    assert marked == ["0", "0.1", "1", "u1", "u1.1"]
    for piece in ("SIGNS", "FIRST", "LEAD-IN", "PROOF."):
        assert piece in text
    whole = "\n\n".join(section.text for section in paper.sections if section.level == 1)
    assert without_markers(text) == whole and paper.chars == len(whole) - 2 * 2


def test_a_marker_stands_at_its_heading_also_when_the_same_text_stands_earlier():
    # The place of a marker used to be looked for: the first place where the text of the
    # subsection stood. Here that is the first line of the section, not the subsection.
    latex = (
        "\\documentclass{article}\\begin{document}\n"
        "\\section{Results}\nSee Table 1.\n" + filler(200) + "\n"
        "\\subsection{Summary}\nSee Table 1.\n"
        "\\subsection{Empty}\n\\subsection{Last}\nDone.\n\\end{document}"
    )
    meta = PaperMeta("2504.00006v1", "T", ("A",), 2025, "hep-ph", "A.")
    lines = full_text(paper_from_latex(meta, latex)).split("\n")

    assert lines[0].startswith("=== 1 | Results | ") and lines[1] == "See Table 1."
    assert lines[-8:] == [
        "=== 1.1 | Summary | 12 chars ===",
        "\\subsection{Summary}",
        "See Table 1.",
        # A subsection without text has its marker as well: its heading is there.
        "=== 1.2 | Empty | 0 chars ===",
        "\\subsection{Empty}",
        "=== 1.3 | Last | 5 chars ===",
        "\\subsection{Last}",
        "Done.",
    ]
    assert sum(line.startswith("=== ") for line in lines) == 4


def test_a_subsection_made_by_hand_without_a_place_gets_no_marker_and_no_text_is_lost():
    # The parser says where the heading of a subsection begins. Sections put together
    # by hand may not say it; then nothing is guessed.
    sections = (
        Section("1", "One", 1, "Own text.\n\\subsection{Empty}\n\\subsection{Odd}\nReal text."),
        Section("1.1", "Empty", 2, ""),
        Section("1.2", "Odd", 2, "Text that is not in the section."),
    )
    paper = Paper(PaperMeta("2504.00003v1", "T", ("A",), 2025, "hep-ph", "A."), sections, "3")
    assert full_text(paper) == f"=== 1 | One | {sections[0].chars} chars ===\n" + sections[0].text


@pytest.mark.anyio
async def test_a_paper_over_the_limit_is_read_in_pieces_that_add_up_to_the_whole(
    client, source, monkeypatch
):
    monkeypatch.setattr(server, "PAPER_CHAR_LIMIT", 30_000)
    whole = full_text(source.paper_by_id("2502.00002v1"))
    assert len(whole) > 30_000

    pieces, start = [], 0
    while True:
        text = await call(client, "read_paper", arxiv_id="2502.00002v1", start=start)
        said = read_first_line(text)
        body = text.split("\nText:\n\n", 1)[1]
        assert (said["start"], said["chars"], said["sections"]) == (start, len(whole), 3)
        if said["extent"] == END:
            assert text.split("\n")[0].endswith("| partial, end of paper")
            pieces.append(body)
            break
        assert said["extent"] == MORE_FOLLOWS
        piece, hint = body.rsplit("\n\n", 1)
        assert hint == (
            f"[cut at character {said['stop']} of {len(whole)}. "
            f"To continue, call read_paper with start={said['stop']}.]"
        )
        pieces.append(piece)
        start = said["stop"]

    assert len(pieces) == 2
    assert "".join(pieces) == whole


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("arxiv_id", "kind"),
    [("2503.00001v1", ErrorKind.NO_FULL_TEXT), ("2503.00002v1", ErrorKind.PARSE_ERROR)],
)
async def test_a_paper_without_readable_text_still_shows_the_abstract(client, arxiv_id, kind):
    text = await call(client, "read_paper", arxiv_id=arxiv_id)
    lines = text.splitlines()
    assert lines[0] == f"paper | {arxiv_id} | no text | {kind.value}"
    assert "Abstract: Its abstract." in lines
    assert lines[-1].startswith(f"Text: none. [{kind.value}] '{arxiv_id}': ")
    assert read_first_line(text) == {"shape": "paper", "arxiv_id": arxiv_id, "no_text": kind.value}


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("arxiv_id", "kind"),
    [
        ("2503.00003v1", ErrorKind.UPSTREAM_BUSY),
        ("2503.00004v1", ErrorKind.TIMEOUT),
        ("2412.00009v1", ErrorKind.NOT_FOUND),
        ("not an identifier", ErrorKind.INVALID_ID),
    ],
)
async def test_a_failure_carries_its_kind(client, arxiv_id, kind):
    text = await failure(client, "read_paper", arxiv_id=arxiv_id)
    assert text.startswith(f"[{kind.value}] ")


@pytest.mark.parametrize("kind", [kind for kind in ErrorKind if kind in FAILING.values()])
def test_no_sentence_of_this_layout_points_to_a_tool_it_does_not_have(kind):
    text = explain(SourceError(kind, "x"), "flat")
    assert text.startswith(f"[{kind.value}] 'x'")
    assert "get_outline" not in text and "read_section" not in text


@pytest.mark.anyio
async def test_a_start_that_breaks_the_schema_never_reaches_the_tool(client, source):
    result = await client.call_tool("read_paper", {"arxiv_id": "2501.00001v2", "start": -1})
    assert result.is_error is True
    assert "[" not in only_text(result).removeprefix("Error executing tool read_paper: ")[:1]
    assert source.calls == []
