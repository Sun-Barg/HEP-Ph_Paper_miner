"""Shared test helpers: a small invented paper, and archives built in memory."""

import gzip
import io
import tarfile
from pathlib import Path

import pytest

from hepph_paper_miner.sources.base import PaperMeta

FIXTURES = Path(__file__).parent / "fixtures"
OWN_PAPER = FIXTURES / "arxiv-2610.26648v1"


@pytest.fixture
def anyio_backend() -> str:
    """Run async tests on asyncio. Tests opt in with @pytest.mark.anyio."""
    return "asyncio"


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
