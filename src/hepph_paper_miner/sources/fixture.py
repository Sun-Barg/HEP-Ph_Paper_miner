"""A source made of papers held in memory. For tests: no network, no files."""

from __future__ import annotations

from collections.abc import Iterable, Mapping

from hepph_paper_miner.sources.arxiv_latex import PARSER_VERSION, parse_source
from hepph_paper_miner.sources.base import (
    ArxivId,
    ErrorKind,
    Paper,
    PaperMeta,
    SearchQuery,
    SearchResult,
    SourceError,
    parse_arxiv_id,
)


def paper_from_latex(meta: PaperMeta, latex: str) -> Paper:
    """Build a paper the way the real source does, from one LaTeX file."""
    return Paper(meta, parse_source(latex.encode("utf-8")), PARSER_VERSION)


class FixtureSource:
    """Serves the given papers. `failures` makes chosen identifiers fail in a chosen way."""

    def __init__(
        self, papers: Iterable[Paper], failures: Mapping[str, ErrorKind] | None = None
    ) -> None:
        self._papers = {paper.meta.arxiv_id: paper for paper in papers}
        self._failures = dict(failures or {})
        self.calls: list[tuple[str, str]] = []  # what was asked, for tests to inspect

    def paper_by_id(self, arxiv_id: str) -> Paper:
        """Direct access for tests; not recorded in `calls`."""
        return self._papers[arxiv_id]

    def search(self, query: SearchQuery) -> SearchResult:
        """Papers whose title or abstract contains every word of the query, in the order given."""
        self.calls.append(("search", query.query))
        words = query.query.lower().split()
        matches = []
        for paper in self._papers.values():
            meta = paper.meta
            text = f"{meta.title} {meta.abstract}".lower()
            if not all(word in text for word in words):
                continue
            if query.author and query.author.lower() not in " ".join(meta.authors).lower():
                continue
            if query.category and query.category != meta.primary_category:
                continue
            if not (query.year_from or 0) <= meta.year <= (query.year_to or 9999):
                continue
            matches.append(meta)
        return SearchResult(tuple(matches[: query.max_results]), len(matches))

    def paper(self, arxiv_id: ArxivId) -> Paper:
        self.calls.append(("paper", str(arxiv_id)))
        if str(arxiv_id) in self._failures:
            raise SourceError(self._failures[str(arxiv_id)], str(arxiv_id))
        # Without a version: the latest one, as arXiv does.
        versions = [
            (parse_arxiv_id(key).version or 0, paper)
            for key, paper in self._papers.items()
            if parse_arxiv_id(key).base == arxiv_id.base
            and arxiv_id.version in (None, parse_arxiv_id(key).version)
        ]
        found = max(versions, key=lambda pair: pair[0])[1] if versions else None
        if found is None:
            raise SourceError(ErrorKind.NOT_FOUND, str(arxiv_id))
        return found
