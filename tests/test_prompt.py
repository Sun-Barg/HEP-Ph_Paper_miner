"""What the loop tells the model, and what it accepts as an answer."""

import hashlib
import json
from pathlib import Path

import pytest
from conftest import sample_source
from mcp import Client

from hepph_paper_miner.agent.prompt import (
    ANSWER_SCHEMA,
    PROMPT_VERSION,
    SYSTEM_PROMPT,
    read_answer,
    unknown_tool_text,
)
from hepph_paper_miner.server import TOOLSET_VERSION, build_server, explain
from hepph_paper_miner.sources.base import ErrorKind, SourceError, parse_arxiv_id

TARGETS = Path(__file__).parent.parent / "eval_data" / "target_papers.txt"
PINNED_P1 = "5168eaef77a8e36f9ddaadac653d6da085aa3acd7aa1c0715b54b373ce8d98b4"
GOOD = {
    "answer": "It is 0.79.",
    "found": True,
    "evidence": [{"arxiv_id": "2501.00001v2", "section_id": "2.1"}],
}


def objects_in(schema: dict):
    """Every object schema inside a schema, the schema itself included."""
    if schema.get("type") == "object":
        yield schema
        for inner in schema["properties"].values():
            yield from objects_in(inner)
    elif schema.get("type") == "array":
        yield from objects_in(schema["items"])


def test_an_answer_of_the_expected_form_is_read():
    assert read_answer(json.dumps(GOOD)) == GOOD
    nothing = {"answer": "The paper does not say.", "found": False, "evidence": []}
    assert read_answer(json.dumps(nothing)) == nothing


@pytest.mark.parametrize(
    "text",
    [
        "",
        "It is 0.79.",
        "{",
        json.dumps("It is 0.79."),
        json.dumps([GOOD]),
        json.dumps({"answer": "x", "found": True}),  # a field is missing
        json.dumps({**GOOD, "confidence": 0.9}),  # a field nobody asked for
        json.dumps({**GOOD, "answer": ""}),
        json.dumps({**GOOD, "answer": 0.79}),
        json.dumps({**GOOD, "found": 1}),
        json.dumps({**GOOD, "evidence": "2501.00001v2 2.1"}),
        json.dumps({**GOOD, "evidence": ["2501.00001v2"]}),
        json.dumps({**GOOD, "evidence": [{"arxiv_id": "2501.00001v2"}]}),
        json.dumps({**GOOD, "evidence": [{"arxiv_id": "2501.00001v2", "section_id": 2}]}),
    ],
)
def test_anything_else_is_not_an_answer(text):
    assert read_answer(text) is None


def test_the_schema_is_one_the_api_can_hold_a_response_to():
    # Structured outputs need every object closed, and keep the order of the fields
    # only when all of them are required.
    for schema in objects_in(ANSWER_SCHEMA):
        assert schema["additionalProperties"] is False
        assert schema["required"] == list(schema["properties"])
    assert list(ANSWER_SCHEMA["properties"]) == ["answer", "found", "evidence"]
    # No field asks for the model's reasoning: the API may refuse a request that does.
    assert "reason" not in json.dumps(ANSWER_SCHEMA).lower()


def test_the_message_for_an_unknown_tool_names_the_tools_there_are():
    text = unknown_tool_text("read_paper", ["search_papers", "get_outline"])
    assert text == "Unknown tool: 'read_paper'. The tools are: search_papers, get_outline."


@pytest.mark.anyio
async def test_no_text_a_model_reads_names_a_paper_of_the_evaluation():
    # An identifier in a prompt, a tool description or an error sentence is a hint to
    # go and read that paper. Examples have to be identifiers no question is about.
    lines = TARGETS.read_text(encoding="utf-8").splitlines()
    targets = {
        parse_arxiv_id(line).base for line in lines if line.strip() and not line.startswith("#")
    }
    assert len(targets) == 23

    read_by_the_model = [SYSTEM_PROMPT, json.dumps(ANSWER_SCHEMA), unknown_tool_text("x", ["y"])]
    for toolset in TOOLSET_VERSION:
        async with Client(build_server(sample_source(), toolset)) as client:
            read_by_the_model.append(client.instructions)
            for tool in (await client.list_tools()).tools:
                read_by_the_model += [tool.description, json.dumps(tool.input_schema)]
        read_by_the_model += [explain(SourceError(kind, "x"), toolset) for kind in ErrorKind]

    for text in read_by_the_model:
        for target in targets:
            assert target not in text


@pytest.mark.anyio
async def test_the_prompt_is_the_same_for_both_layouts_so_it_names_no_tool():
    names = set()
    for toolset in TOOLSET_VERSION:
        async with Client(build_server(sample_source(), toolset)) as client:
            names |= {tool.name for tool in (await client.list_tools()).tools}
    assert names == {"search_papers", "get_outline", "read_section", "read_paper"}
    for name in names:
        assert name not in SYSTEM_PROMPT
        assert name not in json.dumps(ANSWER_SCHEMA)


def test_the_texts_are_the_ones_this_version_names():
    # The model reads these texts, so a change to them is a different experiment.
    # When this fails: raise PROMPT_VERSION in agent/prompt.py, then put the new
    # version and the new digest here.
    texts = json.dumps([SYSTEM_PROMPT, ANSWER_SCHEMA, unknown_tool_text("{name}", ["{tools}"])])
    digest = hashlib.sha256(texts.encode("utf-8")).hexdigest()
    assert (PROMPT_VERSION, digest) == ("p1", PINNED_P1), digest
