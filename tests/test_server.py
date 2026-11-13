"""The server through the SDK's in-memory client: real protocol layer, no process, no network."""

import threading
import time

import pytest
from conftest import (
    FAILING,
    SAMPLE_LATEX,
    SAMPLE_META,
    call,
    failure,
    only_text,
    sample_source,
)
from mcp import Client, MCPError
from mcp.types import REQUEST_TIMEOUT

from hepph_paper_miner.result_text import END, MORE_FOLLOWS, read_first_line
from hepph_paper_miner.server import (
    SECTION_CHAR_LIMIT,
    SERVER_NAME,
    TOOLSET_VERSION,
    _stop,
    build_server,
    explain,
)
from hepph_paper_miner.sources.base import ErrorKind, PaperMeta, SourceError
from hepph_paper_miner.sources.fixture import FixtureSource, paper_from_latex


@pytest.fixture
def source() -> FixtureSource:
    return sample_source()


@pytest.fixture
async def client(source):
    # raise_exceptions=True: a failure outside a tool body shows its real message in the test.
    async with Client(build_server(source), raise_exceptions=True) as connected:
        yield connected


@pytest.mark.anyio
async def test_server_reports_its_name_and_the_name_of_its_tool_texts(client):
    # The version a client sees is the name of what the model reads, not of the package:
    # a run record has to say which tool texts were in front of the model.
    assert client.server_info.name == SERVER_NAME
    assert client.server_info.version == TOOLSET_VERSION["staged"] == "staged-4"


def test_a_layout_that_does_not_exist_is_refused():
    with pytest.raises(ValueError, match="unknown toolset 'nested'"):
        build_server(FixtureSource([]), "nested")


@pytest.mark.anyio
async def test_three_tools_with_text_output_only(client):
    tools = {tool.name: tool for tool in (await client.list_tools()).tools}
    assert list(tools) == ["search_papers", "get_outline", "read_section"]
    for tool in tools.values():
        assert tool.output_schema is None  # one channel: text
        assert tool.description

    search = tools["search_papers"].input_schema
    assert search["required"] == ["query"]
    assert search["properties"]["max_results"]["maximum"] == 10
    assert tools["read_section"].input_schema["required"] == ["arxiv_id", "section_id"]


@pytest.mark.anyio
async def test_a_caller_that_stops_waiting_is_not_held_by_a_tool_that_hangs():
    # A request to arXiv that does not come back, played by a source that waits. The
    # work of a tool runs in a thread, and the call ends when the caller's time is up.
    release = threading.Event()

    class Hanging(FixtureSource):
        def listing(self, arxiv_id):
            release.wait(30)
            return super().listing(arxiv_id)

    began = time.monotonic()
    try:
        async with Client(build_server(Hanging([]))) as connected:
            with pytest.raises(MCPError) as caught:
                await connected.call_tool(
                    "get_outline", {"arxiv_id": "2501.00001v2"}, read_timeout_seconds=0.2
                )
            waited = time.monotonic() - began
            # The server goes on answering while that thread is still out.
            text = await failure(connected, "get_outline", arxiv_id="not an identifier")
    finally:
        release.set()  # the thread was let go, not stopped: let it end

    assert caught.value.code == REQUEST_TIMEOUT
    assert waited < 10  # and not the 30 s that the source would have taken
    assert text.startswith("[invalid_id] ")


# --- search_papers ---------------------------------------------------------------------


@pytest.mark.anyio
async def test_search_lists_identifiers_but_no_abstracts(client):
    text = await call(client, "search_papers", query="sample", category="hep-ph", year_from=2020)
    assert text.splitlines() == [
        "search | 1 of 1 results | query='sample' category='hep-ph' year_from=2020",
        "1. 2501.00001v2 | 2025 | hep-ph | Ada Alpha, Ben Beta | A Sample Paper",
    ]
    assert SAMPLE_META.abstract not in text


@pytest.mark.anyio
async def test_search_shortens_a_long_author_list_and_respects_max_results(client):
    text = await call(client, "search_papers", query="paper", max_results=1)
    assert text.splitlines()[0] == "search | 1 of 2 results | query='paper'"

    text = await call(client, "search_papers", query="long")
    assert (
        text.splitlines()[1]
        == "1. 2502.00002v1 | 2024 | astro-ph.HE | Cy Gamma, Di Delta, Ed Eps and 1 more | A Long Paper"
    )


@pytest.mark.anyio
async def test_search_without_matches_is_a_result_that_says_what_to_change(client):
    text = await call(client, "search_papers", query="nothing-like-this")
    first, advice = text.splitlines()
    assert first == "search | 0 of 0 results | query='nothing-like-this'"
    assert "fewer or different words" in advice


@pytest.mark.anyio
async def test_a_year_range_that_ends_before_it_starts_is_answered_without_a_search(client, source):
    text = await failure(client, "search_papers", query="sample", year_from=2026, year_to=2020)
    assert text.startswith("[bad_query] year_from (2026) is later than year_to (2020)")
    assert source.calls == []

    await call(client, "search_papers", query="sample", year_from=2025, year_to=2025)


@pytest.mark.anyio
async def test_a_search_that_arxiv_cannot_read_says_how_to_write_one():
    class Refusing(FixtureSource):
        def search(self, query):
            raise SourceError(ErrorKind.BAD_QUERY, query.query)

    async with Client(build_server(Refusing([])), raise_exceptions=True) as connected:
        text = await failure(connected, "search_papers", query="dark matter")
    assert text.startswith("[bad_query] 'dark matter': arXiv could not read this search.")


# --- get_outline -------------------------------------------------------------------------


@pytest.mark.anyio
async def test_outline_shows_abstract_and_every_section_with_its_size(client, source):
    text = await call(client, "get_outline", arxiv_id=" arXiv:2501.00001v2 ")
    lines = text.splitlines()
    paper = source.paper_by_id("2501.00001v2")

    assert lines[0] == f"outline | 2501.00001v2 | {paper.chars} chars | 8 sections | parser 4"
    assert lines[1:5] == [
        "Title: A Sample Paper",
        "Authors: Ada Alpha, Ben Beta",
        "Listed: 2025 | hep-ph",
        f"Abstract: {SAMPLE_META.abstract}",
    ]
    assert lines[5].startswith("Sections (id | chars | title).")
    assert lines[6] == f"1 | {paper.sections[0].chars} | Introduction"
    assert "  2.1 | 10 | Data" in lines  # subsections are indented
    assert lines[-1] == "  A.1 | 10 | More"


@pytest.mark.anyio
async def test_identifier_without_version_is_answered_with_the_full_identifier(client):
    text = await call(client, "get_outline", arxiv_id="2501.00001")
    assert text.startswith("outline | 2501.00001v2 | ")


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("arxiv_id", "kind"), [("2503.00001v1", "no_full_text"), ("2503.00002v1", "parse_error")]
)
async def test_outline_of_a_paper_without_readable_text_still_shows_the_abstract(
    client, arxiv_id, kind
):
    # A result, not an error: the listing was found, and it is all there is to show.
    lines = (await call(client, "get_outline", arxiv_id=arxiv_id)).splitlines()

    assert lines[0] == f"outline | {arxiv_id} | no sections | {kind}"
    assert lines[1:5] == [
        "Title: A Paper Without Text",
        "Authors: Gil Eta",
        "Listed: 2025 | hep-ph",
        "Abstract: Its abstract.",
    ]
    assert lines[5].startswith(f"Sections: none. [{kind}] {arxiv_id!r}: ")
    assert "full text is unavailable" in lines[5]
    assert len(lines) == 6


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("arxiv_id", "kind"), [("2503.00003v1", "upstream_busy"), ("2503.00004v1", "timeout")]
)
async def test_outline_fails_when_arxiv_itself_does_not_answer(client, arxiv_id, kind):
    text = await failure(client, "get_outline", arxiv_id=arxiv_id)
    assert text.startswith(f"[{kind}] {arxiv_id!r}: ")


@pytest.mark.anyio
@pytest.mark.parametrize("kind", [ErrorKind.UPSTREAM_BUSY, ErrorKind.TIMEOUT])
async def test_outline_is_an_error_when_the_paper_is_listed_but_its_text_does_not_arrive(kind):
    # The listing answers, the download does not. The abstract must not be passed off
    # as all there is to read: the text may well be there on the next try.
    class DownloadFails(FixtureSource):
        def paper(self, arxiv_id):
            raise SourceError(kind, str(arxiv_id))

    source = DownloadFails([paper_from_latex(SAMPLE_META, SAMPLE_LATEX)])
    async with Client(build_server(source), raise_exceptions=True) as connected:
        text = await failure(connected, "get_outline", arxiv_id="2501.00001v2")

    assert text.startswith(f"[{kind.value}] '2501.00001v2': ")
    assert "Abstract" not in text and SAMPLE_META.abstract not in text
    assert source.calls == [("listing", "2501.00001v2")]  # the listing was asked, and it answered


# --- read_section ------------------------------------------------------------------------


@pytest.mark.anyio
async def test_short_section_comes_back_whole(client):
    text = await call(client, "read_section", arxiv_id="2501.00001v2", section_id="2.1")
    assert text == "section | 2501.00001v2 | 2.1 | 10 chars | complete\nTitle: Data\n\nData text."


@pytest.mark.anyio
async def test_long_section_is_read_in_pieces_that_add_up_to_the_whole(client, source):
    section = source.paper_by_id("2502.00002v1").sections[0]
    assert section.chars > 2 * SECTION_CHAR_LIMIT

    pieces, start = [], 0
    while True:
        text = await call(
            client, "read_section", arxiv_id="2502.00002v1", section_id="1", start=start
        )
        header, _title, _blank, *rest = text.split("\n")
        said = read_first_line(text)
        stop = said["stop"]
        assert (said["start"], said["chars"]) == (start, section.chars)
        assert start < stop <= start + SECTION_CHAR_LIMIT
        if stop == section.chars:
            # The last piece is partial too, and says that nothing follows it.
            assert said["extent"] == END
            assert header.endswith(
                f"chars {start}-{stop} of {section.chars} | partial, end of section"
            )
            pieces.append("\n".join(rest))
            break
        assert said["extent"] == MORE_FOLLOWS
        assert header.endswith(f"chars {start}-{stop} of {section.chars} | partial, more follows")
        # This text is one long line, so a piece ends after a space: no word is cut in two.
        assert section.text[stop - 1] == " "
        # The last line says how to go on, and names the subsections as the other way.
        assert rest[-1] == (
            f"[cut at character {stop} of {section.chars}. To continue, call read_section with start={stop}, "
            "or read its subsections one by one: 1.1.]"
        )
        pieces.append("\n".join(rest[:-2]))
        start = stop

    assert len(pieces) == 3
    assert "".join(pieces) == section.text


@pytest.mark.anyio
async def test_a_piece_ends_at_a_line_break_and_never_inside_a_number():
    # 400 lines of 61 characters, line break included. A cut at exactly 20000 would fall
    # inside "0.7910" on line 328 and leave "0.79" at the end of the first piece: a number
    # that reads as complete.
    line = "The branching fraction into b quarks is measured ".ljust(49) + "0.7910" + " here"
    assert len(line) == 60
    latex = (
        "\\documentclass{article}\\begin{document}\n\\section{Lines}\n"
        + "\n".join([line] * 400)
        + "\n\\end{document}"
    )
    meta = PaperMeta("2504.00001v1", "Lines", ("Hal Theta",), 2025, "hep-ph", "Lines.")
    source = FixtureSource([paper_from_latex(meta, latex)])
    section = source.paper_by_id("2504.00001v1").sections[0]
    assert section.text == "\n".join([line] * 400)
    assert section.text[SECTION_CHAR_LIMIT - 4 : SECTION_CHAR_LIMIT + 2] == "0.7910"

    async with Client(build_server(source), raise_exceptions=True) as client:
        text = await call(client, "read_section", arxiv_id="2504.00001v1", section_id="1")

    said = read_first_line(text)
    assert said["stop"] == 327 * 61 < SECTION_CHAR_LIMIT  # after the line break of line 327
    body = text.split("\n", 3)[3].rsplit("\n\n", 1)[0]
    assert body == section.text[: said["stop"]]
    assert body.endswith("0.7910 here\n")


def test_where_a_piece_ends():
    assert _stop("x" * 50, 0, 100) == 50  # all of it fits
    assert _stop("x" * 50, 40, 100) == 50
    assert _stop("ab\ncd ef" + "x" * 100, 0, 10) == 3  # after the line break, not the later space
    assert _stop("ab cd ef" + "x" * 100, 0, 10) == 6  # no line break: after the last space
    assert _stop("x" * 300, 0, 100) == 100  # nowhere to break: exactly at the limit
    assert _stop("ab\ncd" + "x" * 100, 3, 10) == 13  # counted from where the piece begins
    # Only the last stretch before the limit is searched, so a piece is never much
    # shorter than the limit: the break near the start of these texts is not used.
    assert _stop("a\nb" + "x" * 30000, 0, 20000) == 20000
    assert _stop("a b" + "x" * 30000, 0, 20000) == 20000


@pytest.mark.anyio
async def test_start_past_the_end_returns_an_empty_piece(client):
    text = await call(client, "read_section", arxiv_id="2501.00001v2", section_id="2.1", start=999)
    assert (
        text.splitlines()[0]
        == "section | 2501.00001v2 | 2.1 | chars 10-10 of 10 | partial, end of section"
    )


@pytest.mark.anyio
@pytest.mark.parametrize(("typed", "real"), [("a", "A"), ("2.U1", "2.u1"), (" U1 ", "u1")])
async def test_section_identifier_in_the_wrong_case_is_understood(client, typed, real):
    text = await call(client, "read_section", arxiv_id="2501.00001v2", section_id=typed)
    assert text.splitlines()[0].startswith(f"section | 2501.00001v2 | {real} | ")


# --- errors ------------------------------------------------------------------------------


@pytest.mark.anyio
async def test_invalid_identifier_is_an_error_result_the_model_can_read(client, source):
    bad = "https://arxiv.org/abs/2610.26648"
    text = await failure(client, "get_outline", arxiv_id=bad)

    assert text.startswith(f"[invalid_id] {bad!r} is not a valid arXiv identifier")
    assert "'2301.01234v2'" in text  # what to pass instead
    assert source.calls == []  # the source was never asked


@pytest.mark.anyio
async def test_a_long_bad_argument_is_not_repeated_in_full(client):
    text = await failure(client, "get_outline", arxiv_id="2610.26648v" + "9" * 5000)
    assert len(text) < 500
    assert "999...'" in text


@pytest.mark.anyio
async def test_unknown_paper_points_back_to_search(client):
    text = await failure(client, "read_section", arxiv_id="2501.99999v1", section_id="1")
    assert text.startswith("[not_found] '2501.99999v1': ")
    assert "search_papers" in text


@pytest.mark.anyio
async def test_unknown_section_lists_the_sections_that_exist(client):
    text = await failure(client, "read_section", arxiv_id="2501.00001v2", section_id="9")
    assert (
        text
        == "[no_such_section] 2501.00001v2 has no section '9'. Its sections are: 1, 2, 2.1, 2.u1, 2.2, u1, A, A.1."
    )


@pytest.mark.anyio
@pytest.mark.parametrize(("arxiv_id", "kind"), [(key, kind.value) for key, kind in FAILING.items()])
async def test_every_source_failure_carries_its_kind_and_a_next_step(client, arxiv_id, kind):
    text = await failure(client, "read_section", arxiv_id=arxiv_id, section_id="1")
    assert text.startswith(f"[{kind}] {arxiv_id!r}: ")
    assert len(text) > len(f"[{kind}] {arxiv_id!r}: ") + 40  # a sentence follows, not just the kind


@pytest.mark.parametrize(
    "kind", [kind for kind in ErrorKind if kind is not ErrorKind.NO_SUCH_SECTION]
)
def test_every_kind_a_source_can_raise_has_its_own_sentence(kind):
    # NO_SUCH_SECTION is not raised by a source: the server writes that sentence itself.
    text = explain(SourceError(kind, "x"))
    assert text.startswith(f"[{kind.value}] 'x'")
    assert "the request failed" not in text  # the fallback for a kind nobody wrote a sentence for


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("tool", "arguments"),
    [
        ("search_papers", {}),
        ("search_papers", {"query": ""}),
        ("search_papers", {"query": "x", "max_results": 50}),
        ("search_papers", {"query": "x", "category": "hep ph) OR all:x"}),
        ("get_outline", {"arxiv_id": 2610}),
        ("read_section", {"arxiv_id": "2501.00001v2", "section_id": "1", "start": -1}),
    ],
)
async def test_arguments_that_break_the_schema_never_reach_the_tool(
    client, source, tool, arguments
):
    result = await client.call_tool(tool, arguments)

    # The SDK rejects these before calling the function. Still an error result,
    # but without our bracketed kind: a client must tell the two apart.
    assert result.is_error is True
    text = only_text(result)
    assert text.startswith(f"Error executing tool {tool}: ")
    assert "[" not in text.removeprefix(f"Error executing tool {tool}: ")[:1]
    assert source.calls == []
