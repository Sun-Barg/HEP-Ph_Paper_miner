"""The real source: arXiv's API for search and listing data, its source downloads for full text.

This module only connects the pieces. Requests go through http.Fetcher; the
answers are read by arxiv_search (Atom) and arxiv_latex (TeX source).
"""

from __future__ import annotations

from dataclasses import replace

from hepph_paper_miner.http import Fetcher, FetchError
from hepph_paper_miner.sources.arxiv_latex import PARSER_VERSION, NotASource, parse_source
from hepph_paper_miner.sources.arxiv_search import (
    FeedError,
    lookup_params,
    parse_feed,
    search_params,
)
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

# arXiv asks programs to use the export host.
API_URL = "https://export.arxiv.org/api/query"
SOURCE_URL = "https://export.arxiv.org/e-print/{arxiv_id}"

_FAILURES = {"busy": ErrorKind.UPSTREAM_BUSY, "timeout": ErrorKind.TIMEOUT}


class ArxivSource:
    def __init__(self, fetcher: Fetcher) -> None:
        self._fetcher = fetcher
        self._papers: dict[str, Paper] = {}  # parsed papers of this process, by identifier

    def search(self, query: SearchQuery) -> SearchResult:
        params = search_params(query)
        if params is None:
            return SearchResult((), 0)
        return self._feed(params, about=query.query)

    def paper(self, arxiv_id: ArxivId) -> Paper:
        meta = self._lookup(arxiv_id)
        if meta.arxiv_id not in self._papers:
            url = SOURCE_URL.format(arxiv_id=meta.arxiv_id)
            try:
                data = self._get(url, {}, about=meta.arxiv_id)
            except SourceError as error:
                if error.kind is ErrorKind.NOT_FOUND:
                    # The paper is listed, so a missing download means there is no source.
                    raise SourceError(ErrorKind.NO_FULL_TEXT, meta.arxiv_id) from error
                raise
            try:
                sections = parse_source(data)
            except SourceError as error:
                if isinstance(error, NotASource):
                    # Not the paper's files at all: perhaps a page sent in their place.
                    # Do not keep it. A source that is real but cannot be split stays
                    # in the cache: asking again would bring the same bytes.
                    self._fetcher.forget(url, {})
                raise SourceError(error.kind, f"{meta.arxiv_id}: {error.detail}") from error
            self._papers[meta.arxiv_id] = Paper(meta, sections, PARSER_VERSION)
        return self._papers[meta.arxiv_id]

    def _lookup(self, arxiv_id: ArxivId) -> PaperMeta:
        """Listing data for one paper. Without a version this names the latest one."""
        try:
            found = self._feed(lookup_params(str(arxiv_id)), about=str(arxiv_id))
        except FeedError as error:
            raise SourceError(ErrorKind.NOT_FOUND, str(arxiv_id)) from error
        if not found.papers:
            raise SourceError(ErrorKind.NOT_FOUND, str(arxiv_id))
        meta = found.papers[0]
        if arxiv_id.version is not None and parse_arxiv_id(meta.arxiv_id).version is None:
            # The answer does not say which version it is: it is the one that was asked for.
            meta = replace(meta, arxiv_id=str(arxiv_id))
        return meta

    def _feed(self, params: dict[str, str], *, about: str) -> SearchResult:
        """Ask the API and read its answer. Only an answer that lists a paper stays in the cache.

        The cache never expires, and the API can answer 200 with nothing in it: an
        empty listing, its error feed, or a body that is not a feed. Kept, such an
        answer would hide a paper on this machine for good. Not kept, it costs one
        more request the next time the same thing is asked.
        """
        body = self._get(API_URL, params, about=about)
        try:
            found = parse_feed(body)
        except Exception:
            self._fetcher.forget(API_URL, params)
            raise
        if not found.papers:
            self._fetcher.forget(API_URL, params)
        return found

    def _get(self, url: str, params: dict[str, str], *, about: str) -> bytes:
        """Fetch, and say in the source's terms why it failed."""
        try:
            return self._fetcher.get(url, params).body
        except FetchError as error:
            if error.reason in ("not_found", "rejected") and error.status in (400, 404):
                raise SourceError(ErrorKind.NOT_FOUND, about) from error
            if error.reason in _FAILURES:
                raise SourceError(_FAILURES[error.reason], about) from error
            raise  # anything else is not an expected failure
