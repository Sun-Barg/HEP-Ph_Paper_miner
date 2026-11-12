"""The arXiv API: build the request parameters, read the Atom answer. No network.

Reference: https://info.arxiv.org/help/api/user-manual.html
"""

from __future__ import annotations

import re
from xml.etree import ElementTree

from hepph_paper_miner.sources.base import (
    PaperMeta,
    SearchQuery,
    SearchResult,
    SourceError,
    parse_arxiv_id,
)

_ATOM = "{http://www.w3.org/2005/Atom}"
_OPENSEARCH = "{http://a9.com/-/spec/opensearch/1.1/}"
_ARXIV = "{http://arxiv.org/schemas/atom}"
_ERROR_ID = "http://arxiv.org/api/errors"

_PHRASE_OR_WORD = re.compile(r'"([^"]*)"|(\S+)')
# Characters that mean something in the query language (: ( ) " [ ]) must not reach it.
_NOT_A_WORD = re.compile(r"[^\w.'-]+")
_OPERATORS = {"AND", "OR", "ANDNOT"}


class FeedError(Exception):
    """The API answered with its error feed, for example for an identifier it cannot read."""


def search_params(query: SearchQuery) -> dict[str, str] | None:
    """Turn the tool's arguments into arXiv's query language. None when nothing is left to search for.

    Every word must match (AND). A "quoted phrase" must match as a phrase. The
    words are looked up in all fields; this is a keyword search.
    """
    clauses = []
    for phrase, word in _PHRASE_OR_WORD.findall(query.query):
        words = _NOT_A_WORD.sub(" ", phrase or word).split()
        if phrase and len(words) > 1:
            clauses.append(f'all:"{" ".join(words)}"')
        else:
            # The operators of the query language are not search words.
            clauses.extend(f"all:{each}" for each in words if each not in _OPERATORS)
    if query.author:
        author = " ".join(_NOT_A_WORD.sub(" ", query.author).split())
        if author:
            clauses.append(f'au:"{author}"')
    if query.category:
        clauses.append(f"cat:{query.category}")
    if not clauses:
        return None
    if query.year_from is not None or query.year_to is not None:
        # Submission date of the first version, to the minute, in GMT.
        first, last = query.year_from or 1991, query.year_to or 2099
        clauses.append(f"submittedDate:[{first}01010000 TO {last}12312359]")
    return {
        "search_query": " AND ".join(clauses),
        "start": "0",
        "max_results": str(query.max_results),
        "sortBy": "relevance",
        "sortOrder": "descending",
    }


def lookup_params(arxiv_id: str) -> dict[str, str]:
    """Ask for one paper. With a version the API returns that version, without one the latest."""
    return {"id_list": arxiv_id, "max_results": "1"}


def parse_feed(body: bytes) -> SearchResult:
    """Read an Atom answer. Raises FeedError when it is the API's error feed."""
    feed = ElementTree.fromstring(body)
    papers = []
    for entry in feed.findall(f"{_ATOM}entry"):
        entry_id = _text(entry, f"{_ATOM}id")
        if entry_id.startswith(_ERROR_ID):
            raise FeedError(_text(entry, f"{_ATOM}summary"))
        try:
            # "http://arxiv.org/abs/2610.26648v1" or ".../abs/hep-ph/0404175v2"
            arxiv_id = str(parse_arxiv_id(entry_id.split("/abs/", 1)[-1]))
        except SourceError:
            continue  # not a paper entry
        primary = entry.find(f"{_ARXIV}primary_category")
        papers.append(
            PaperMeta(
                arxiv_id=arxiv_id,
                title=_text(entry, f"{_ATOM}title"),
                authors=tuple(
                    _text(author, f"{_ATOM}name") for author in entry.findall(f"{_ATOM}author")
                ),
                year=int(_text(entry, f"{_ATOM}published")[:4] or 0),
                primary_category="" if primary is None else primary.get("term", ""),
                abstract=_text(entry, f"{_ATOM}summary"),
            )
        )
    total = _text(feed, f"{_OPENSEARCH}totalResults")
    return SearchResult(tuple(papers), int(total) if total.isdigit() else len(papers))


def _text(parent: ElementTree.Element, tag: str) -> str:
    """Text of a child element with line breaks and repeated spaces removed; "" if it is absent."""
    return " ".join((parent.findtext(tag) or "").split())
