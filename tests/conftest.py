"""Shared test helpers: a small invented paper, and archives built in memory."""

import gzip
import io
import tarfile
from pathlib import Path

import pytest
from mcp.types import TextContent

from hepph_paper_miner.sources.base import ErrorKind, PaperMeta
from hepph_paper_miner.sources.fixture import FixtureSource, paper_from_latex

FIXTURES = Path(__file__).parent / "fixtures"
OWN_PAPER = FIXTURES / "arxiv-2610.26648v1"


@pytest.fixture
def anyio_backend() -> str:
    """Run async tests on asyncio. Tests opt in with @pytest.mark.anyio."""
    return "asyncio"


def only_text(result) -> str:
    """The text the model would read: exactly one text block, and no second channel."""
    assert len(result.content) == 1
    block = result.content[0]
    assert isinstance(block, TextContent)
    assert result.structured_content is None
    return block.text


async def call(client, tool: str, **arguments) -> str:
    """Call a tool that is expected to succeed, and return its text."""
    result = await client.call_tool(tool, arguments)
    assert result.is_error is False, only_text(result)
    return only_text(result)


async def failure(client, tool: str, **arguments) -> str:
    """Call a tool that is expected to fail, and return its text without the SDK's words in front."""
    result = await client.call_tool(tool, arguments)
    assert result.is_error is True
    text = only_text(result)
    assert text.startswith(f"Error executing tool {tool}: ")
    return text.removeprefix(f"Error executing tool {tool}: ")


def tar_gz(files: dict[str, bytes]) -> bytes:
    """A gzipped tar holding the given files, like an arXiv source download with several files."""
    return gzip.compress(plain_tar(files))


def plain_tar(files: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w") as bundle:
        for name, data in files.items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            bundle.addfile(info, io.BytesIO(data))
    return buffer.getvalue()


def filler(words: int) -> str:
    """Body text of a known size, so that an invented paper passes the minimum-length check."""
    return " ".join(f"word{index}" for index in range(words))


# An invented paper with everything the parser has to cope with.
SAMPLE_LATEX = r"""\documentclass{article}
\input{colordvi.tex}
% \section{A heading inside a comment}
\begin{document}
\title{A Sample Paper}
\begin{abstract}
The abstract.
\end{abstract}
\maketitle

\section{Introduction}\label{sec:intro}
Intro text. 100\% of it stays. % a trailing comment goes
FILLER

\section[Short]{Methods and the $\mathcal{O}(1)$ case}
Methods overview.
\subsection{Data}
Data text.
\subsection*{A side note}
Side note text.
\subsection{Fit}
Fit text.

\section*{Acknowledgements}
Thanks.

\appendix
\section{Extra tables}
Appendix text.
\subsection{More}
More text.

\bibliography{refs}
\end{document}
""".replace("FILLER", filler(300))

SAMPLE_META = PaperMeta(
    arxiv_id="2501.00001v2",
    title="A Sample Paper",
    authors=("Ada Alpha", "Ben Beta"),
    year=2025,
    primary_category="hep-ph",
    abstract="The abstract of the sample paper about galactic excess.",
)

# A paper with one section of more than 40,000 characters, to be read in pieces.
LONG_META = PaperMeta(
    "2502.00002v1",
    "A Long Paper",
    ("Cy Gamma", "Di Delta", "Ed Eps", "Flo Zeta"),
    2024,
    "astro-ph.HE",
    "Long.",
)
LONG_LATEX = (
    "\\documentclass{article}\\begin{document}\n"
    "\\section{Big}\nStart. " + filler(6000) + "\n\\subsection{Part}\nPart text.\n"
    "\\section{Small}\nSmall text.\n\\end{document}"
)

# Identifiers that fail, each in its own way.
FAILING = {
    "2503.00001v1": ErrorKind.NO_FULL_TEXT,
    "2503.00002v1": ErrorKind.PARSE_ERROR,
    "2503.00003v1": ErrorKind.UPSTREAM_BUSY,
    "2503.00004v1": ErrorKind.TIMEOUT,
}

# arXiv lists a paper also when its text cannot be read.
LISTED_ONLY = [
    PaperMeta(key, "A Paper Without Text", ("Gil Eta",), 2025, "hep-ph", "Its abstract.")
    for key, kind in FAILING.items()
    if kind in (ErrorKind.NO_FULL_TEXT, ErrorKind.PARSE_ERROR)
]


def sample_source() -> FixtureSource:
    """The two invented papers and the four failing identifiers, behind one source."""
    papers = [paper_from_latex(SAMPLE_META, SAMPLE_LATEX), paper_from_latex(LONG_META, LONG_LATEX)]
    return FixtureSource(papers, FAILING, LISTED_ONLY)
