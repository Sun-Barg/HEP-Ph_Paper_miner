"""The real source: arXiv's API for search and listing data, its source downloads for full text.

This module only connects the pieces. Requests go through http.Fetcher; the
answers are read by arxiv_search (Atom) and arxiv_latex (TeX source).
"""

from __future__ import annotations

from dataclasses import replace
from xml.etree import ElementTree

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
        try:
            return self._feed(params, about=query.query)
        except FeedError as error:
            # The API read the request and says it cannot answer it.
            raise SourceError(ErrorKind.BAD_QUERY, query.query) from error
        except SourceError as error:
            if error.kind is ErrorKind.NOT_FOUND:  # status 400: for a search, a bad request
                raise SourceError(ErrorKind.BAD_QUERY, query.query) from error
            raise

    def paper(self, arxiv_id: ArxivId) -> Paper:
        meta = self.listing(arxiv_id)
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
            except NotASource as error:
                # Damaged, or not the paper's files at all (a page sent in their place):
                # arXiv has not answered properly, which says nothing about the paper.
                # Not kept, so that the next call asks again.
                self._fetcher.forget(url, {})
                raise SourceError(
                    ErrorKind.UPSTREAM_BUSY, f"{meta.arxiv_id}: {error.detail}"
                ) from error
            except SourceError as error:
                # A real source that cannot be read stays in the cache: asking again
                # would bring the same bytes.
                raise SourceError(error.kind, f"{meta.arxiv_id}: {error.detail}") from error
            self._papers[meta.arxiv_id] = Paper(meta, sections, PARSER_VERSION)
        return self._papers[meta.arxiv_id]

    def listing(self, arxiv_id: ArxivId) -> PaperMeta:
        """Listing data for one paper. Without a version this names the latest one.

        "The latest version" changes when the authors replace the paper, and the cache
        never expires. So an answer to a request without a version is not kept, and
        one that an earlier program version kept is not used. A request with a
        version always has the same answer and is kept as usual.
        """
        try:
            found = self._feed(
                lookup_params(str(arxiv_id)), about=str(arxiv_id), keep=arxiv_id.version is not None
            )
        except FeedError as error:
            raise SourceError(ErrorKind.NOT_FOUND, str(arxiv_id)) from error
        if not found.papers:
            raise SourceError(ErrorKind.NOT_FOUND, str(arxiv_id))
        meta = found.papers[0]
        if arxiv_id.version is not None and parse_arxiv_id(meta.arxiv_id).version is None:
            # The answer does not say which version it is: it is the one that was asked for.
            meta = replace(meta, arxiv_id=str(arxiv_id))
        return meta

    def _feed(self, params: dict[str, str], *, about: str, keep: bool = True) -> SearchResult:
        """Ask the API and read its answer. Only an answer that lists a paper stays in the cache.

        The cache never expires, and the API can answer 200 with nothing in it: an
        empty listing, its error feed, or a body that is not a feed. Kept, such an
        answer would hide a paper on this machine for good. Not kept, it costs one
        more request the next time the same thing is asked.

        keep=False: ask arXiv even when an answer is in the cache, and do not keep the new one.
        """
        body = self._get(API_URL, params, about=about, refresh=not keep)
        try:
            found = parse_feed(body)
        except FeedError:
            self._fetcher.forget(API_URL, params)
            raise
        except (ElementTree.ParseError, ValueError) as error:
            # Status 200, but not a feed that can be read: arXiv is not answering properly.
            self._fetcher.forget(API_URL, params)
            raise SourceError(ErrorKind.UPSTREAM_BUSY, about) from error
        if not (keep and found.papers):
            self._fetcher.forget(API_URL, params)
        return found

    def _get(self, url: str, params: dict[str, str], *, about: str, refresh: bool = False) -> bytes:
        """Fetch, and say in the source's terms why it failed."""
        try:
            return self._fetcher.get(url, params, refresh=refresh).body
        except FetchError as error:
            if error.reason in _FAILURES:
                raise SourceError(_FAILURES[error.reason], about) from error
            if error.status in (400, 404):
                raise SourceError(ErrorKind.NOT_FOUND, about) from error
            # Any other refusal (403 when arXiv blocks a client, for example) says
            # nothing about the paper: arXiv is not answering this program now.
            raise SourceError(ErrorKind.UPSTREAM_BUSY, about) from error
