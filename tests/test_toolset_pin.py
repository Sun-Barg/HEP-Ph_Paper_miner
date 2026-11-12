"""TOOLSET_VERSION names what the model reads. This test fails when the two drift apart.

Whoever changes a tool description, an argument description or the form of a result
has changed the experiment, and has to raise the version of that layout in server.py.
Nothing would make them: the code runs the same. So the texts are fixed here by a
digest, under the version they belong to:

    what a client is told   the instructions, and every tool's name, description and
                            input schema, as they arrive through the protocol
    what a tool returns     the full text of one result of every form, and of one
                            error of every kind, for a paper written out by hand
                            below (so that the digest does not depend on the parser)

When this test fails:
    the texts changed on purpose  ->  raise TOOLSET_VERSION for that layout, then put
                                      the new version and the two digests printed by
                                      the failure into PINNED
    they did not                  ->  the change is the bug
"""

import hashlib
import json

import pytest
from mcp import Client

from hepph_paper_miner.result_text import error_kind, read_first_line
from hepph_paper_miner.server import (
    PAPER_CHAR_LIMIT,
    SECTION_CHAR_LIMIT,
    TOOLSET_VERSION,
    build_server,
)
from hepph_paper_miner.sources.base import ErrorKind, Paper, PaperMeta, Section
from hepph_paper_miner.sources.fixture import FixtureSource

PINNED = {
    "staged-3": (
        "2894e85cc947d591dc3e5d54e7040d0e7ccd6a997af8f6f19c3cda018d6e3a41",
        "3412b052aae5dbf8c159c78b558c66a17d646846ba0da758ca986f388bf52d4d",
    ),
    "flat-1": (
        "5ad3886f3fe1fe8dc11162c12ca5e4a73588041cef0701bffdec3bcfb57e9dc9",
        "686b64159140d06015dd5269bf0d5148882b19f4063aae41057094fd68a1d16f",
    ),
}

LINE = "A line of text that is exactly sixty characters long, here.\n"
assert len(LINE) == 60
LONG = (LINE * (SECTION_CHAR_LIMIT // 60 + 40)).strip()

PAPER = Paper(
    PaperMeta(
        "2501.00001v2",
        "A Paper Written By Hand",
        ("Ada Alpha", "Ben Beta", "Cy Gamma", "Di Delta"),
        2025,
        "hep-ph",
        "Its abstract,\nwhich has a line break.",
    ),
    (
        Section("0", "(text before the first section)", 1, "Front text."),
        Section(
            "1",
            "Methods",
            1,
            "Overview.\n\\subsection{Data}\nData text.\n\\subsection*{Aside}\nAside.",
        ),
        Section("1.1", "Data", 2, "Data text."),
        Section("1.u1", "Aside", 2, "Aside."),
        Section("2", "A Long Section", 1, LONG),
        Section("A", "Tables", 1, "Appendix text."),
    ),
    "3",
)
# Longer than one read_paper call returns. Its listing does not match the searches below.
HUGE = Paper(
    PaperMeta("2502.00002v1", "Much Text", ("Ed Eps",), 2024, "astro-ph.HE", "Very long."),
    (Section("1", "Everything", 1, (LINE * (PAPER_CHAR_LIMIT // 60 + 40)).strip()),),
    "3",
)
UNREADABLE = {
    "2503.00001v1": ErrorKind.NO_FULL_TEXT,
    "2503.00002v1": ErrorKind.PARSE_ERROR,
    "2503.00003v1": ErrorKind.UPSTREAM_BUSY,
    "2503.00004v1": ErrorKind.TIMEOUT,
}
LISTED = [
    PaperMeta(key, "A Paper Without Text", ("Gil Eta",), 2024, "astro-ph.HE", "Listed only.")
    for key in ("2503.00001v1", "2503.00002v1")
]

ID = "2501.00001v2"
CALLS = {
    "staged": [
        ("search_papers", {"query": "paper", "author": "Alpha", "year_from": 2020}),
        ("search_papers", {"query": "nothing matches this"}),
        ("search_papers", {"query": "x", "year_from": 2020, "year_to": 2010}),  # bad_query
        ("search_papers", {"query": ""}),  # refused by the schema
        ("get_outline", {"arxiv_id": "2501.00001"}),
        ("get_outline", {"arxiv_id": "2503.00001v1"}),  # no sections: no_full_text
        ("get_outline", {"arxiv_id": "2503.00002v1"}),  # no sections: parse_error
        ("get_outline", {"arxiv_id": "2503.00003v1"}),  # upstream_busy
        ("get_outline", {"arxiv_id": "2503.00004v1"}),  # timeout
        ("get_outline", {"arxiv_id": "2412.00009v1"}),  # not_found
        ("get_outline", {"arxiv_id": "https://arxiv.org/abs/2501.00001"}),  # invalid_id
        ("read_section", {"arxiv_id": ID, "section_id": "1"}),  # complete
        ("read_section", {"arxiv_id": ID, "section_id": "2"}),  # partial, more follows
        ("read_section", {"arxiv_id": ID, "section_id": "2", "start": 19980}),  # partial, end
        ("read_section", {"arxiv_id": ID, "section_id": "a"}),  # found in the other case
        ("read_section", {"arxiv_id": ID, "section_id": "9"}),  # no_such_section
        ("read_section", {"arxiv_id": "2503.00001v1", "section_id": "1"}),  # no_full_text
        ("read_section", {"arxiv_id": "2503.00002v1", "section_id": "1"}),  # parse_error
    ],
    "flat": [
        ("search_papers", {"query": "paper", "author": "Alpha", "year_from": 2020}),
        ("search_papers", {"query": "nothing matches this"}),
        ("search_papers", {"query": "x", "year_from": 2020, "year_to": 2010}),
        ("read_paper", {"arxiv_id": "2501.00001"}),  # complete
        ("read_paper", {"arxiv_id": "2502.00002v1"}),  # partial, more follows
        ("read_paper", {"arxiv_id": ID, "start": 21000}),  # partial, end of paper
        ("read_paper", {"arxiv_id": "2503.00001v1"}),  # no text: no_full_text
        ("read_paper", {"arxiv_id": "2503.00002v1"}),  # no text: parse_error
        ("read_paper", {"arxiv_id": "2503.00003v1"}),
        ("read_paper", {"arxiv_id": "2503.00004v1"}),
        ("read_paper", {"arxiv_id": "2412.00009v1"}),
        ("read_paper", {"arxiv_id": "https://arxiv.org/abs/2501.00001"}),
        ("read_paper", {"arxiv_id": ID, "start": -1}),  # refused by the schema
    ],
}


def digest(value) -> str:
    text = json.dumps(value, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


async def what_a_model_reads(toolset: str) -> tuple[str, str]:
    source = FixtureSource([PAPER, HUGE], UNREADABLE, LISTED)
    async with Client(build_server(source, toolset)) as client:
        tools = (await client.list_tools()).tools
        told = {
            "instructions": client.instructions,
            "tools": [[tool.name, tool.description, tool.input_schema] for tool in tools],
        }
        returned = []
        for name, arguments in CALLS[toolset]:
            result = await client.call_tool(name, arguments)
            (block,) = result.content
            returned.append([name, arguments, result.is_error, block.text])
    return digest(told), digest(returned)


@pytest.mark.anyio
@pytest.mark.parametrize("toolset", sorted(TOOLSET_VERSION))
async def test_the_texts_of_a_layout_are_the_ones_its_version_names(toolset):
    version = TOOLSET_VERSION[toolset]
    found = await what_a_model_reads(toolset)
    assert version in PINNED, f"no digests are pinned for {version}: {found}"
    assert found == PINNED[version], (
        f"what a model reads from the {toolset} layout changed, and its version is still "
        f"{version}. Raise it in server.py and pin {found} under the new name."
    )


def test_every_layout_is_pinned_and_nothing_else():
    assert sorted(PINNED) == sorted(TOOLSET_VERSION.values())


def form_of(facts: dict) -> str:
    if "extent" in facts:
        return f"{facts['shape']}, {facts['extent']}"
    if "no_sections" in facts or "no_text" in facts:
        return f"{facts['shape']}, without text"
    return facts["shape"]


@pytest.mark.anyio
async def test_the_fixed_results_cover_every_form_and_every_kind_of_error():
    # The digests protect what the calls above produce, and nothing else.
    forms, kinds = set(), set()
    for toolset in TOOLSET_VERSION:
        source = FixtureSource([PAPER, HUGE], UNREADABLE, LISTED)
        async with Client(build_server(source, toolset)) as client:
            for name, arguments in CALLS[toolset]:
                result = await client.call_tool(name, arguments)
                text = result.content[0].text
                if result.is_error:
                    kinds.add(error_kind(text))
                else:
                    forms.add(form_of(read_first_line(text)))
    assert kinds == {kind.value for kind in ErrorKind} | {"invalid_arguments"}
    assert forms == {
        "search",
        "outline",
        "outline, without text",
        "section, complete",
        "section, more_follows",
        "section, end",
        "paper, complete",
        "paper, more_follows",
        "paper, end",
        "paper, without text",
    }
