"""The MCP server: three tools for finding a paper and reading it one section at a time.

    search_papers   who wrote what           -> identifiers
    get_outline     one paper                -> abstract, section identifiers and sizes
    read_section    one section of one paper -> its text

Each tool returns one piece of text and nothing else. Hosts differ in what they pass
to the model when a result has both text and structured data, so there is only text.
Its first line has a fixed form ("search | ...", "outline | ...", "section | ...")
that a program can read; the rest is for the model.

Start it with:  python -m hepph_paper_miner.server
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Annotated

from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from pydantic import Field

from hepph_paper_miner import __version__
from hepph_paper_miner.http import Fetcher, default_cache_dir
from hepph_paper_miner.sources.arxiv import ArxivSource
from hepph_paper_miner.sources.base import (
    ErrorKind,
    Paper,
    PaperSource,
    SearchQuery,
    Section,
    SourceError,
    parse_arxiv_id,
)

SERVER_NAME = "hepph-paper-miner"

# Names the tool descriptions, the argument descriptions and the form of every result.
# A change to any of them changes what the model reads, so it is a different experiment.
TOOLSET_VERSION = "staged-1"

SECTION_CHAR_LIMIT = 20_000  # the most text one read_section call returns
_ECHO_LIMIT = 80  # the most of a bad argument that is repeated back

_INSTRUCTIONS = (
    "Search arXiv and read papers. Find a paper with search_papers, look at its sections "
    "with get_outline, then read only the sections you need with read_section. "
    "Pass identifiers exactly as a tool returned them."
)

_NEXT_STEP = {
    ErrorKind.NOT_FOUND: (
        "arXiv has no such paper or version. Check the identifier with search_papers."
    ),
    ErrorKind.NO_FULL_TEXT: (
        "This paper has no TeX source, so its sections cannot be read. "
        "search_papers gives its title and authors; if that is not enough, "
        "say that the full text is unavailable."
    ),
    ErrorKind.PARSE_ERROR: (
        "The TeX source of this paper could not be split into sections, so it cannot be read. "
        "If the question needs its full text, say that it is unavailable."
    ),
    ErrorKind.UPSTREAM_BUSY: (
        "arXiv did not answer after several tries. Try once more later, or use another paper."
    ),
    ErrorKind.TIMEOUT: "arXiv took too long to answer. Try once more later, or use another paper.",
}


def explain(error: SourceError) -> str:
    """Turn an expected failure into a sentence that says what went wrong and what to do next.

    The sentence starts with the error kind in brackets, so that a client can
    classify the failure without understanding the prose.
    """
    kind = error.kind.value
    if error.kind is ErrorKind.INVALID_ID:
        return (
            f"[{kind}] {_quoted(error.detail)} is not a valid arXiv identifier: the form is wrong, "
            "or it names a month, a number or an archive that arXiv never used. "
            "Expected forms: '2610.26648v1' or '2610.26648' (papers from 2007-04 on), "
            "'hep-ph/0404175v2' or 'hep-ph/0404175' (earlier papers). "
            "Pass the identifier only, not a URL."
        )
    return f"[{kind}] {_quoted(error.detail)}: {_NEXT_STEP.get(error.kind, 'the request failed.')}"


def _quoted(value: str) -> str:
    """A caller's value as it is shown back: in quotes, and cut when it is long."""
    return repr(value if len(value) <= _ECHO_LIMIT else value[:_ECHO_LIMIT] + "...")


@contextmanager
def _expected_failures() -> Iterator[None]:
    """Inside a tool: report a SourceError to the model as an error result it can read.

    ToolError reaches the model as a result with is_error=True and this text. Any
    other exception reaches it as a bare "Error executing tool ..." and is logged.
    """
    try:
        yield
    except SourceError as error:
        raise ToolError(explain(error)) from error


def _find_section(paper: Paper, section_id: str) -> Section:
    wanted = section_id.strip()
    for section in paper.sections:
        if section.section_id == wanted:
            return section
    known = ", ".join(section.section_id for section in paper.sections)
    raise ToolError(
        f"[{ErrorKind.NO_SUCH_SECTION.value}] {paper.meta.arxiv_id} has no section "
        f"{_quoted(section_id)}. "
        f"Its sections are: {known}."
    )


def _authors(names: tuple[str, ...]) -> str:
    return (
        ", ".join(names) if len(names) <= 3 else f"{', '.join(names[:3])} and {len(names) - 3} more"
    )


def build_server(source: PaperSource) -> MCPServer:
    """Create the server and register its tools.

    The source is passed in: the real server gets arXiv, tests get papers held in memory.
    """
    mcp = MCPServer(SERVER_NAME, version=__version__, instructions=_INSTRUCTIONS)

    @mcp.tool(structured_output=False)
    def search_papers(
        query: Annotated[
            str,
            Field(
                min_length=1,
                description=(
                    'Words that must all appear. Put a phrase in double quotes: "dark matter".'
                ),
            ),
        ],
        author: Annotated[
            str | None,
            Field(description="A name the author list must contain, for example 'Hooper'."),
        ] = None,
        category: Annotated[
            str | None,
            Field(
                pattern=r"^[a-z-]+(\.[A-Za-z-]+)?$",
                description="An arXiv category, for example 'hep-ph' or 'astro-ph.HE'.",
            ),
        ] = None,
        year_from: Annotated[
            int | None, Field(ge=1991, le=2099, description="First year of submission to include.")
        ] = None,
        year_to: Annotated[
            int | None, Field(ge=1991, le=2099, description="Last year of submission to include.")
        ] = None,
        max_results: Annotated[int, Field(ge=1, le=10)] = 5,
    ) -> str:
        """Search arXiv by keyword. Returns identifiers, years, categories, authors and titles.

        The best match comes first.
        This is a keyword search, not a semantic one: every word has to occur in the
        paper's listing (title, abstract, authors, comments). Abstracts are not
        returned; get_outline shows the abstract of one paper.
        """
        with _expected_failures():
            found = source.search(
                SearchQuery(query, author, category, year_from, year_to, max_results)
            )
        asked = f"query={query!r}"
        asked += "".join(
            f" {name}={value!r}"
            for name, value in (
                ("author", author),
                ("category", category),
                ("year_from", year_from),
                ("year_to", year_to),
            )
            if value is not None
        )
        lines = [f"search | {len(found.papers)} of {found.total} results | {asked}"]
        for rank, meta in enumerate(found.papers, start=1):
            lines.append(
                f"{rank}. {meta.arxiv_id} | {meta.year} | {meta.primary_category} | {_authors(meta.authors)} | {meta.title}"
            )
        if not found.papers:
            lines.append(
                "No paper matched. Every word has to occur, so try fewer or different words, "
                "or drop the author, category or year filter."
            )
        return "\n".join(lines)

    @mcp.tool(structured_output=False)
    def get_outline(
        arxiv_id: Annotated[
            str,
            Field(
                description=(
                    "An arXiv identifier as returned by search_papers, for example '2610.26648v1'."
                )
            ),
        ],
    ) -> str:
        """Show one paper's title, authors, abstract and its list of sections with their sizes.

        Use the sizes (in characters) to decide what to read. The size of a section
        includes its subsections. Without a version in the identifier, the latest
        version is used and its full identifier is shown on the first line.
        """
        with _expected_failures():
            paper = source.paper(parse_arxiv_id(arxiv_id))
        meta = paper.meta
        lines = [
            f"outline | {meta.arxiv_id} | {paper.chars} chars | {len(paper.sections)} sections | parser {paper.parser_version}",
            f"Title: {meta.title}",
            f"Authors: {_authors(meta.authors)}",
            f"Listed: {meta.year} | {meta.primary_category}",
            f"Abstract: {meta.abstract}",
            "Sections (id | chars | title). A section's chars include its subsections.",
        ]
        for section in paper.sections:
            indent = "  " if section.level == 2 else ""
            lines.append(f"{indent}{section.section_id} | {section.chars} | {section.title}")
        return "\n".join(lines)

    @mcp.tool(structured_output=False)
    def read_section(
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
        with _expected_failures():
            paper = source.paper(parse_arxiv_id(arxiv_id))
        section = _find_section(paper, section_id)
        start = min(start, section.chars)
        stop = min(start + SECTION_CHAR_LIMIT, section.chars)
        text = section.text[start:stop]
        whole = start == 0 and stop == section.chars
        extent = (
            f"{section.chars} chars | complete"
            if whole
            else f"chars {start}-{stop} of {section.chars} | partial"
        )
        lines = [
            f"section | {paper.meta.arxiv_id} | {section.section_id} | {extent}",
            f"Title: {section.title}",
            "",
            text,
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
                + (
                    f", or read its subsections one by one: {', '.join(smaller)}.]"
                    if smaller
                    else ".]"
                )
            )
        return "\n".join(lines)

    return mcp


def main() -> None:
    # No arguments: serve over stdio. stdout carries the protocol, so nothing here may print.
    fetcher = Fetcher(default_cache_dir(), user_agent=f"{SERVER_NAME}/{__version__}")
    build_server(ArxivSource(fetcher)).run()


if __name__ == "__main__":
    main()
