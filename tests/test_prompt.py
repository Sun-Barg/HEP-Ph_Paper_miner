"""What the loop tells the model, and what it accepts as an answer."""

import hashlib
import json
from pathlib import Path

import pytest
from conftest import sample_source
from mcp import Client

from hepph_paper_miner.agent.prompt import (
    ANSWER_SCHEMA,
    ANSWER_TOOL,
    FORMAT,
    INVALID_ANSWER_TEXT,
    PROMPT_VERSION,
    SYSTEM_PROMPT,
    TEXT,
    TOOL,
    as_answer,
    read_answer,
    system_prompt,
    unknown_tool_text,
)
from hepph_paper_miner.server import TOOLSET_VERSION, build_server, explain
from hepph_paper_miner.sources.base import ErrorKind, SourceError, parse_arxiv_id

TARGETS = Path(__file__).parent.parent / "eval_data" / "target_papers.txt"
# The name of the texts of each way to hand in an answer, and the digest of those texts.
PINNED = {
    FORMAT: ("p1", "5168eaef77a8e36f9ddaadac653d6da085aa3acd7aa1c0715b54b373ce8d98b4"),
    TOOL: ("p2-tool", "11ecefd73fee6a0943d5dab1bf2941b735e8b3859e61d400b0cc6931cc0b4762"),
    TEXT: ("p2-text", "f37463bd535ed066b8b7cf5b5d895710f38930abcc662b01f9276db19008f2d1"),
}
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

    read_by_the_model = [json.dumps(texts_of(channel)) for channel in PROMPT_VERSION]
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
    # In every way to hand in an answer. The one tool these texts do name is the
    # loop's own, which is the same with both layouts and is no tool of a server.
    assert ANSWER_TOOL["name"] not in names
    for channel in PROMPT_VERSION:
        for name in names:
            assert name not in json.dumps(texts_of(channel))


def texts_of(channel: str) -> list:
    """Everything the loop itself can say to the model in a run with this way to answer."""
    unknown = unknown_tool_text("{name}", ["{tools}"])
    if channel == FORMAT:
        return [SYSTEM_PROMPT, ANSWER_SCHEMA, unknown]
    if channel == TOOL:
        return [system_prompt(TOOL), ANSWER_TOOL, unknown, INVALID_ANSWER_TEXT]
    return [system_prompt(TEXT), unknown]


@pytest.mark.parametrize("channel", [FORMAT, TOOL, TEXT])
def test_the_texts_are_the_ones_this_version_names(channel):
    # The model reads these texts, so a change to them is a different experiment.
    # When this fails: raise the name of this way in PROMPT_VERSION (agent/prompt.py),
    # then put the new name and the new digest into PINNED.
    assert set(PROMPT_VERSION) == set(PINNED)
    digest = hashlib.sha256(json.dumps(texts_of(channel)).encode("utf-8")).hexdigest()
    assert (PROMPT_VERSION[channel], digest) == PINNED[channel], digest


def test_each_way_to_hand_in_an_answer_has_a_name_of_its_own_for_its_texts():
    assert len(set(PROMPT_VERSION.values())) == len(PROMPT_VERSION) == 3


def test_the_two_other_prompts_are_the_first_one_with_something_added():
    # What differs between the ways is what they say about handing in the answer, and
    # nothing else: the five rules stand in all three, word for word.
    assert system_prompt(FORMAT) == SYSTEM_PROMPT
    assert system_prompt(TOOL) == SYSTEM_PROMPT + (
        "- Give the final answer by calling submit_answer. "
        "A reply that ends without that call is not an answer.\n"
    )
    assert system_prompt(TEXT) == SYSTEM_PROMPT + (
        "\nGive the final answer as one JSON object and nothing else: no text before or after "
        "it, and no code fence. It has to follow this JSON schema:\n"
        + json.dumps(ANSWER_SCHEMA)
        + "\n"
    )
    # The schema stands in that prompt on one line, as text that can be read back.
    assert json.loads(system_prompt(TEXT).splitlines()[-1]) == ANSWER_SCHEMA
    with pytest.raises(KeyError):
        system_prompt("letter")


def test_the_tool_for_the_answer_takes_an_answer_and_is_not_strict():
    assert ANSWER_TOOL == {
        "name": "submit_answer",
        "description": "Hand in the final answer to the question. This ends the conversation.",
        "input_schema": ANSWER_SCHEMA,
    }
    # Not strict: that would put the constraint back whose effect is to be found out.
    assert "strict" not in ANSWER_TOOL
    assert ANSWER_TOOL["name"] in INVALID_ANSWER_TEXT and ANSWER_TOOL["name"] in system_prompt(TOOL)
    assert ANSWER_TOOL["name"] not in system_prompt(TEXT) + system_prompt(FORMAT)


def test_arguments_are_an_answer_by_the_same_rule_as_a_text():
    # A text is read as JSON first. The arguments of a call arrive read already.
    assert as_answer(GOOD) is GOOD
    assert as_answer({**GOOD, "evidence": []}) == {**GOOD, "evidence": []}
    for wrong in (
        None,
        "It is 0.79.",
        [GOOD],
        {"answer": "x", "found": True},
        {**GOOD, "confidence": 0.9},
        {**GOOD, "answer": "  "},
        {**GOOD, "found": "true"},
        {**GOOD, "evidence": None},
        {**GOOD, "evidence": [{"arxiv_id": "2501.00001v2", "section_id": "2.1", "page": "3"}]},
    ):
        assert as_answer(wrong) is None
