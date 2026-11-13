"""The MCP server: tools for finding a paper and reading it, in one of two layouts.

    staged (the default)
        search_papers   who wrote what           -> identifiers
        get_outline     one paper                -> abstract, section identifiers and sizes
                                                    (the abstract alone when the text cannot be read)
        read_section    one section of one paper -> its text

    flat
        search_papers   who wrote what           -> identifiers and abstracts
        read_paper      one paper                -> its whole text, every section marked

The two layouts exist to be compared: does a model that sees an outline first and
then reads single sections get by with less text than one that reads whole papers,
and are its answers as good? A server offers one layout, chosen when it is started.

Each tool returns one piece of text and nothing else. Hosts differ in what they pass
to the model when a result has both text and structured data, so there is only text.
Its first line has a fixed form ("search | ...", "outline | ...", "section | ...",
"paper | ...", written in result_text.py) that a program can read; the rest is for
the model.

Start it with:  python -m hepph_paper_miner.server [--toolset flat]
"""

from __future__ import annotations

import argparse
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from typing import Annotated

import anyio.to_thread
from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from pydantic import Field

from hepph_paper_miner import __version__
from hepph_paper_miner.http import Fetcher, default_cache_dir
from hepph_paper_miner.result_text import (
    outline_line,
    outline_without_sections_line,
    paper_line,
    paper_without_text_line,
    search_line,
    section_line,
)
from hepph_paper_miner.sources.arxiv import ArxivSource
from hepph_paper_miner.sources.base import (
    ErrorKind,
    Paper,
    PaperMeta,
    PaperSource,
    SearchQuery,
    Section,
    SourceError,
    parse_arxiv_id,
)

SERVER_NAME = "hepph-paper-miner"

# One name for everything the model reads from a layout: the tool descriptions, the
# argument descriptions and the form of every result. A change to any of them changes
# what the model reads, so it is a different experiment and the name has to change.
# The server reports this name as its version, which is how a client learns it, and
# tests/test_toolset_pin.py fails when the texts change and the name does not.
# The name also goes up when a tool answers the same call differently although no text
# has changed, which no test can see: a search that sends other words to arXiv, a
# marker in the whole text of a paper that stands in another place.
TOOLSET_VERSION = {"staged": "staged-5", "flat": "flat-4"}

SECTION_CHAR_LIMIT = 20_000  # the most text one read_section call returns
# The largest paper of the evaluation has 187,527 characters, so every one of them
# comes back whole. The limit is for whatever else a search may lead to: the text of
# a paper is sent to the model again with every later turn of a conversation.
PAPER_CHAR_LIMIT = 400_000  # the most text one read_paper call returns
_CUT_WINDOW = 2_000  # how far back from a limit a line break is looked for
_ECHO_LIMIT = 80  # the most of a bad argument that is repeated back

_INSTRUCTIONS = {
    "staged": (
        "Search arXiv and read papers. Find a paper with search_papers, look at its sections "
        "with get_outline, then read only the sections you need with read_section. "
        "Pass identifiers exactly as a tool returned them."
    ),
    "flat": (
        "Search arXiv and read papers. Find a paper with search_papers, then read it with "
        "read_paper. Pass identifiers exactly as a tool returned them."
    ),
}

_NEXT_STEP = {
    ErrorKind.NOT_FOUND: (
        "arXiv has no such paper or version. Check the identifier with search_papers."
    ),
    ErrorKind.BAD_QUERY: (
        "arXiv could not read this search. Use plain words, and put a phrase in double quotes."
    ),
    ErrorKind.NO_FULL_TEXT: (
        "This paper has no TeX source, so its sections cannot be read. "
        "get_outline still shows its abstract; if the question needs more, "
        "say that the full text is unavailable."
    ),
    ErrorKind.PARSE_ERROR: (
        "The TeX source of this paper could not be split into sections, so it cannot be read. "
        "get_outline still shows its abstract; if the question needs more, "
        "say that the full text is unavailable."
    ),
    ErrorKind.UPSTREAM_BUSY: (
        "arXiv is busy or refused the request, so there is no answer. "
        "Try once more later, or use another paper."
    ),
    ErrorKind.TIMEOUT: "arXiv took too long to answer. Try once more later, or use another paper.",
}

# The flat layout has no get_outline to point to.
_NEXT_STEP_FLAT = {
    ErrorKind.NO_FULL_TEXT: (
        "This paper has no TeX source, so its text cannot be read. "
        "The abstract is all there is; if the question needs more, "
        "say that the full text is unavailable."
    ),
    ErrorKind.PARSE_ERROR: (
        "The TeX source of this paper could not be split into sections, so it cannot be read. "
        "The abstract is all there is; if the question needs more, "
        "say that the full text is unavailable."
    ),
}


def explain(error: SourceError, toolset: str = "staged") -> str:
    """Turn an expected failure into a sentence that says what went wrong and what to do next.

    The sentence starts with the error kind in brackets, so that a program can
    classify the failure without understanding the prose. The SDK puts its own
    words in front ("Error executing tool <name>: "), so a program has to look for
    the bracketed kind in the text, not at its start.
    """
    kind = error.kind.value
    if error.kind is ErrorKind.INVALID_ID:
        # The examples are identifiers no evaluation question is about: a tool text
        # that names a paper invites the model to go and read it.
        return (
            f"[{kind}] {_quoted(error.detail)} is not a valid arXiv identifier: the form is wrong, "
            "or it names a month, a number or an archive that arXiv never used. "
            "Expected forms: '2301.01234v2' or '2301.01234' (papers from 2007-04 on), "
            "'hep-ph/0404175v2' or 'hep-ph/0404175' (earlier papers). "
            "Pass the identifier only, not a URL."
        )
    steps = _NEXT_STEP if toolset == "staged" else {**_NEXT_STEP, **_NEXT_STEP_FLAT}
    return f"[{kind}] {_quoted(error.detail)}: {steps.get(error.kind, 'the request failed.')}"


def _quoted(value: str) -> str:
    """A caller's value as it is shown back: in quotes, and cut when it is long."""
    return repr(value if len(value) <= _ECHO_LIMIT else value[:_ECHO_LIMIT] + "...")


@contextmanager
def _expected_failures(toolset: str) -> Iterator[None]:
    """Inside a tool: report a SourceError to the model as an error result it can read.

    ToolError reaches the model as a result with is_error=True and this text. Any
    other exception reaches it as a bare "Error executing tool ..." and is logged.
    """
    try:
        yield
    except SourceError as error:
        raise ToolError(explain(error, toolset)) from error


async def _in_a_thread(work: Callable[..., str], *arguments: object) -> str:
    """Do the work of a tool in a thread, and stop waiting for it when the caller does.

    The work blocks: it waits for arXiv, and for its turn to ask. The SDK runs a tool
    that is a plain function in a thread too, but then waits for that thread whatever
    happens, so that a caller's time limit ends nothing (the loop's tool_seconds never
    fired). Here the call ends as soon as the caller gives up. The thread itself
    cannot be stopped: it finishes its request, keeps its turn in the queue to arXiv
    until then, and what it fetched goes into the cache.
    """
    return await anyio.to_thread.run_sync(work, *arguments, abandon_on_cancel=True)


def _find_section(paper: Paper, section_id: str) -> Section:
    wanted = section_id.strip()
    for section in paper.sections:
        if section.section_id == wanted:
            return section
    # No exact match: "a" for "A", "2.U1" for "2.u1". The answer names the real identifier.
    close = [s for s in paper.sections if s.section_id.casefold() == wanted.casefold()]
    if len(close) == 1:
        return close[0]
    known = ", ".join(section.section_id for section in paper.sections)
    raise ToolError(
        f"[{ErrorKind.NO_SUCH_SECTION.value}] {paper.meta.arxiv_id} has no section "
        f"{_quoted(section_id)}. "
        f"Its sections are: {known}."
    )


# Failures that concern the full text only. The listing of such a paper is still shown.
_NO_TEXT = (ErrorKind.NO_FULL_TEXT, ErrorKind.PARSE_ERROR)


def _listing_lines(meta: PaperMeta) -> list[str]:
    return [
        f"Title: {meta.title}",
        f"Authors: {_authors(meta.authors)}",
        f"Listed: {meta.year} | {meta.primary_category}",
        f"Abstract: {meta.abstract}",
    ]


def _authors(names: tuple[str, ...]) -> str:
    return (
        ", ".join(names) if len(names) <= 3 else f"{', '.join(names[:3])} and {len(names) - 3} more"
    )


def _stop(text: str, start: int, limit: int) -> int:
    """Where a piece that begins at `start` ends when at most `limit` characters may come back.

    Not always exactly at the limit: a cut in the middle of a number leaves a
    shorter number that reads as a complete one, and only a model that reads in
    pieces would ever see it. So the piece ends after the last line break in the
    final stretch before the limit, or after the last space when that stretch is one
    long line. The result says where it stopped, so the caller needs no arithmetic.
    """
    hard = start + limit
    if hard >= len(text):
        return len(text)
    earliest = max(start, hard - _CUT_WINDOW)
    for mark in ("\n", " "):
        found = text.rfind(mark, earliest, hard)
        if found != -1:
            return found + 1
    return hard


def _marker(section: Section) -> str:
    return f"=== {section.section_id} | {section.title} | {section.chars} chars ==="


def full_text(paper: Paper) -> str:
    """The whole paper as one text, with a marker line in front of every section and subsection.

    The marker carries the section identifier, which is what a reader needs to say
    where a fact stands.
    """
    blocks = []
    for index, section in enumerate(paper.sections):
        if section.level != 1:
            continue
        subsections = []
        for later in paper.sections[index + 1 :]:
            if later.level == 1:
                break
            subsections.append(later)
        blocks.append(f"{_marker(section)}\n{_with_subsection_markers(section.text, subsections)}")
    return "\n\n".join(blocks)


def _with_subsection_markers(text: str, subsections: list[Section]) -> str:
    """Put a marker line in front of each subsection inside the text of its section.

    The text of a section holds its subsections, their LaTeX headings included. The
    parser says where each heading begins (Section.heading_at), and the marker goes in
    front of the line with that heading. Text is only ever added: a subsection without
    such a place (one made by hand) gets no marker, and nothing is dropped or repeated.
    """
    pieces, written = [], 0
    for subsection in subsections:
        if subsection.heading_at is None:
            continue
        line_start = text.rfind("\n", 0, subsection.heading_at) + 1
        cut = max(line_start, written)
        pieces.append(text[written:cut])
        pieces.append(_marker(subsection) + "\n")
        written = cut
    pieces.append(text[written:])
    return "".join(pieces)


# The arguments of search_papers, which both layouts have. They stand at module level
# because the SDK resolves a tool's annotations by name in the module.
_Query = Annotated[
    str,
    Field(
        min_length=1,
        description='Words that must all appear. Put a phrase in double quotes: "dark matter".',
    ),
]
_Author = Annotated[
    str | None,
    Field(description="A name the author list must contain, for example 'Hooper'."),
]
_Category = Annotated[
    str | None,
    Field(
        pattern=r"^[a-z-]+(\.[A-Za-z-]+)?$",
        description="An arXiv category, for example 'hep-ph' or 'astro-ph.HE'.",
    ),
]
_YearFrom = Annotated[
    int | None, Field(ge=1991, le=2099, description="First year of submission to include.")
]
_YearTo = Annotated[
    int | None, Field(ge=1991, le=2099, description="Last year of submission to include.")
]
_MaxResults = Annotated[int, Field(ge=1, le=10)]


# The work of each tool. It blocks while it waits for arXiv, so the tools further down
# hand it to a thread (_in_a_thread) and hold only the texts that a model reads.
def _search(source: PaperSource, toolset: str, query: SearchQuery) -> str:
    if (
        query.year_from is not None
        and query.year_to is not None
        and query.year_from > query.year_to
    ):
        raise ToolError(
            f"[{ErrorKind.BAD_QUERY.value}] year_from ({query.year_from}) is later than "
            f"year_to ({query.year_to}), so no paper can match. Swap them, or drop one."
        )
    with _expected_failures(toolset):
        found = source.search(query)
    asked = f"query={query.query!r}"
    asked += "".join(
        f" {name}={value!r}"
        for name, value in (
            ("author", query.author),
            ("category", query.category),
            ("year_from", query.year_from),
            ("year_to", query.year_to),
        )
        if value is not None
    )
    lines = [search_line(len(found.papers), found.total, found.fetched_at, asked)]
    for rank, meta in enumerate(found.papers, start=1):
        lines.append(
            f"{rank}. {meta.arxiv_id} | {meta.year} | {meta.primary_category} | {_authors(meta.authors)} | {meta.title}"
        )
        if toolset == "flat":
            # On one line, whatever the listing holds: a program reads the identifiers
            # from the lines that begin with a rank.
            lines.append(f"   Abstract: {' '.join(meta.abstract.split())}")
    if not found.papers:
        lines.append(
            "No paper matched. Every word has to occur, so try fewer or different words, "
            "or drop the author, category or year filter."
        )
    return "\n".join(lines)


def _outline(source: PaperSource, arxiv_id: str) -> str:
    with _expected_failures("staged"):
        # The listing first: it names the version, and it is there even when the text is not.
        meta = source.listing(parse_arxiv_id(arxiv_id))
        try:
            paper = source.paper(parse_arxiv_id(meta.arxiv_id))
        except SourceError as error:
            if error.kind not in _NO_TEXT:
                raise
            return "\n".join(
                [
                    outline_without_sections_line(meta.arxiv_id, error.kind.value),
                    *_listing_lines(meta),
                    f"Sections: none. {explain(error)}",
                ]
            )
    lines = [
        outline_line(meta.arxiv_id, paper.chars, len(paper.sections), paper.parser_version),
        *_listing_lines(meta),
        "Sections (id | chars | title). A section's chars include its subsections.",
    ]
    for section in paper.sections:
        indent = "  " if section.level == 2 else ""
        lines.append(f"{indent}{section.section_id} | {section.chars} | {section.title}")
    return "\n".join(lines)


def _section(source: PaperSource, arxiv_id: str, section_id: str, start: int) -> str:
    with _expected_failures("staged"):
        paper = source.paper(parse_arxiv_id(arxiv_id))
    section = _find_section(paper, section_id)
    start = min(start, section.chars)
    stop = _stop(section.text, start, SECTION_CHAR_LIMIT)
    lines = [
        section_line(paper.meta.arxiv_id, section.section_id, start, stop, section.chars),
        f"Title: {section.title}",
        "",
        section.text[start:stop],
    ]
    if stop < section.chars:
        smaller = [
            other.section_id
            for other in paper.sections
            if other.level == 2 and other.section_id.startswith(section.section_id + ".")
        ]
        lines.append("")
        lines.append(
            f"[cut at character {stop} of {section.chars}. To continue, call read_section with start={stop}"
            + (f", or read its subsections one by one: {', '.join(smaller)}.]" if smaller else ".]")
        )
    return "\n".join(lines)


def _whole_paper(source: PaperSource, arxiv_id: str, start: int) -> str:
    with _expected_failures("flat"):
        # The listing first: it names the version, and it is there even when the text is not.
        meta = source.listing(parse_arxiv_id(arxiv_id))
        try:
            paper = source.paper(parse_arxiv_id(meta.arxiv_id))
        except SourceError as error:
            if error.kind not in _NO_TEXT:
                raise
            return "\n".join(
                [
                    paper_without_text_line(meta.arxiv_id, error.kind.value),
                    *_listing_lines(meta),
                    f"Text: none. {explain(error, 'flat')}",
                ]
            )
    text = full_text(paper)
    start = min(start, len(text))
    stop = _stop(text, start, PAPER_CHAR_LIMIT)
    lines = [
        paper_line(
            meta.arxiv_id, start, stop, len(text), len(paper.sections), paper.parser_version
        ),
        *_listing_lines(meta),
        "Text:",
        "",
        text[start:stop],
    ]
    if stop < len(text):
        lines.append("")
        lines.append(
            f"[cut at character {stop} of {len(text)}. To continue, call read_paper with start={stop}.]"
        )
    return "\n".join(lines)


def build_server(source: PaperSource, toolset: str = "staged") -> MCPServer:
    """Create the server and register the tools of one layout.

    The source is passed in: the real server gets arXiv, tests get papers held in memory.
    """
    if toolset not in TOOLSET_VERSION:
        raise ValueError(f"unknown toolset {toolset!r}: expected one of {sorted(TOOLSET_VERSION)}")
    mcp = MCPServer(
        SERVER_NAME, version=TOOLSET_VERSION[toolset], instructions=_INSTRUCTIONS[toolset]
    )
    if toolset == "staged":
        _add_staged_tools(mcp, source)
    else:
        _add_flat_tools(mcp, source)
    return mcp


def _add_staged_tools(mcp: MCPServer, source: PaperSource) -> None:
    @mcp.tool(structured_output=False)
    async def search_papers(
        query: _Query,
        author: _Author = None,
        category: _Category = None,
        year_from: _YearFrom = None,
        year_to: _YearTo = None,
        max_results: _MaxResults = 5,
    ) -> str:
        """Search arXiv by keyword. Returns identifiers, years, categories, authors and titles.

        The best match comes first.
        This is a keyword search, not a semantic one: every word has to occur in the
        paper's listing (title, abstract, authors, comments). Abstracts are not
        returned; get_outline shows the abstract of one paper.
        """
        asked = SearchQuery(query, author, category, year_from, year_to, max_results)
        return await _in_a_thread(_search, source, "staged", asked)

    @mcp.tool(structured_output=False)
    async def get_outline(
        arxiv_id: Annotated[
            str,
            Field(
                description=(
                    "An arXiv identifier as returned by search_papers, for example '2301.01234v2'."
                )
            ),
        ],
    ) -> str:
        """Show one paper's title, authors, abstract and its list of sections with their sizes.

        Use the sizes (in characters) to decide what to read. The size of a section
        includes its subsections. Without a version in the identifier, the latest
        version is used and its full identifier is shown on the first line.
        When the text of a paper cannot be read, the title and abstract are still
        shown, and the last line says why there are no sections.
        """
        return await _in_a_thread(_outline, source, arxiv_id)

    @mcp.tool(structured_output=False)
    async def read_section(
        arxiv_id: Annotated[
            str,
            Field(description="An arXiv identifier as returned by search_papers or get_outline."),
        ],
        section_id: Annotated[
            str,
            Field(description="A section id from get_outline, for example '3' or '3.2' or 'A'."),
        ],
        start: Annotated[
            int,
            Field(
                ge=0,
                description="Character to start from. Only needed to continue a truncated read.",
            ),
        ] = 0,
    ) -> str:
        """Read the text of one section (LaTeX source) of one paper.

        Reading a section also returns its subsections. At most 20000 characters
        come back per call; when a section is longer, the first line says so and the
        last line says how to get the rest.
        """
        return await _in_a_thread(_section, source, arxiv_id, section_id, start)


def _add_flat_tools(mcp: MCPServer, source: PaperSource) -> None:
    @mcp.tool(structured_output=False)
    async def search_papers(
        query: _Query,
        author: _Author = None,
        category: _Category = None,
        year_from: _YearFrom = None,
        year_to: _YearTo = None,
        max_results: _MaxResults = 5,
    ) -> str:
        """Search arXiv by keyword. Returns identifiers, years, categories, authors, titles and abstracts.

        The best match comes first.
        This is a keyword search, not a semantic one: every word has to occur in the
        paper's listing (title, abstract, authors, comments).
        """
        asked = SearchQuery(query, author, category, year_from, year_to, max_results)
        return await _in_a_thread(_search, source, "flat", asked)

    @mcp.tool(structured_output=False)
    async def read_paper(
        arxiv_id: Annotated[
            str,
            Field(
                description=(
                    "An arXiv identifier as returned by search_papers, for example '2301.01234v2'."
                )
            ),
        ],
        start: Annotated[
            int,
            Field(
                ge=0,
                description="Character to start from. Only needed to continue a truncated read.",
            ),
        ] = 0,
    ) -> str:
        """Read one whole paper: its title, authors and abstract, then its full text (LaTeX source).

        Every section and subsection of the text starts with a line of the form
        "=== <section id> | <title> | <size> chars ===". The size of a section
        includes its subsections. At most 400000 characters of text come back per
        call; when a paper is longer, the first line says so and the last line says
        how to get the rest. Without a version in the identifier, the latest version
        is used and its full identifier is shown on the first line. When the text of
        a paper cannot be read, the title and abstract are still shown, and the last
        line says why there is no text.
        """
        return await _in_a_thread(_whole_paper, source, arxiv_id, start)


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="hepph-paper-miner",
        description="Serve the paper tools over stdio (MCP). Without arguments: the staged layout.",
    )
    parser.add_argument(
        "--toolset",
        choices=sorted(TOOLSET_VERSION),
        default="staged",
        help="staged: outline first, then single sections. flat: whole papers at once.",
    )
    arguments = parser.parse_args(argv)
    # From here on stdout carries the protocol, so nothing may print.
    fetcher = Fetcher(default_cache_dir(), user_agent=f"{SERVER_NAME}/{__version__}")
    build_server(ArxivSource(fetcher), arguments.toolset).run()


if __name__ == "__main__":
    main()
