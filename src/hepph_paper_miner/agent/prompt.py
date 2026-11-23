"""Everything the loop itself says to the model, and the form the final answer takes.

The tools speak for themselves (their texts belong to the server and to
TOOLSET_VERSION). What is written here is the rest of what the model reads: the
system prompt, the descriptions inside the answer schema, the loop's own tool, and
the messages the loop writes itself. A change to any of them is a different
experiment, so the name in PROMPT_VERSION has to go up with it.

A run hands in its answer in one of three ways. The model reads something else with
each of them, so each has its own name for its texts:

    format   The text that ends the turn is the answer, and the API holds that text
             to the schema. Nothing here asks for the form: the API adds its own
             words about it to the request.
    tool     The answer is the arguments of a call of ANSWER_TOOL, which the loop
             adds to the tools of the server. One line of the prompt says so, and a
             turn that ends without the call is asked for it once (ASK_AGAIN_TEXT).
    text     The text that ends the turn is the answer, and a paragraph of the prompt
             asks for it as JSON. Nothing holds the model to that.

There are three because of what the runs on the development questions showed
(results/runs/dev/README.md): held to the form by the API, runs went on asking for
tools long after they had been given what the question needs. The two other ways are
there to see with which of them a run ends when it could. With `tool` all thirty runs
handed in an answer, and that is the way the evaluation uses (eval/conditions.py).

p3-tool is p2-tool with the message for a turn that ends without the call. In the runs
made with p2-tool, three ended that way, each with its answer written as text
(results/README.md, results/runs/regress/README.md), and the loop called that no answer.

The same texts are used with both tool layouts, so they name no tool of the server.
They also name no paper and no fact from a paper: an example in a prompt is a hint.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Any

# The ways a run can hand in its answer (see above).
FORMAT = "format"
TOOL = "tool"
TEXT = "text"

PROMPT_VERSION = {FORMAT: "p1", TOOL: "p3-tool", TEXT: "p2-text"}

SYSTEM_PROMPT = """\
You answer questions about physics papers on arXiv. You can read papers only through the tools.

- Find the paper the question is about and read what you need.
- Base the answer only on text the tools returned in this conversation, not on what you remember about a paper.
- If the papers you read do not state what the question asks for, say so and set "found" to false. Do not guess a value.
- In "evidence", list every section the answer relies on: the arXiv identifier with its version and the section id, exactly as the tools showed them. List only sections you read.
- Keep the answer short: the facts asked for, with numbers and units as the paper gives them.
"""

# The form of an answer, the same in all three ways. The API holds a text to it
# (format), it is the input schema of the loop's tool (tool), or the prompt quotes it
# (text). There is no field for reasoning: the API may refuse a request that asks for
# the model's reasoning in its output.
ANSWER_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "answer": {
            "type": "string",
            "description": "The answer, in a few sentences.",
        },
        "found": {
            "type": "boolean",
            "description": (
                "false if the papers you read do not state what the question asks for, "
                "true otherwise."
            ),
        },
        "evidence": {
            "type": "array",
            "description": "The sections the answer relies on. Empty if there are none.",
            "items": {
                "type": "object",
                "properties": {
                    "arxiv_id": {
                        "type": "string",
                        "description": "With its version, exactly as a tool showed it.",
                    },
                    "section_id": {
                        "type": "string",
                        "description": "Exactly as a tool showed it.",
                    },
                },
                "required": ["arxiv_id", "section_id"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["answer", "found", "evidence"],
    "additionalProperties": False,
}

# The loop's own tool, for the way "tool". This model cannot be made to call a tool
# (the API rejects a forced tool choice for it), so a turn can still end without the
# call. The loop asks for it once (ASK_AGAIN_TEXT below); a run that ends without the
# call after that is a run without an answer. The tool is not marked strict either. Strict
# input is made under the same constraint as a text held to a form, and whether that
# constraint is what keeps a run from ending is the thing to find out. The loop checks
# the arguments itself (as_answer).
ANSWER_TOOL: dict[str, Any] = {
    "name": "submit_answer",
    "description": "Hand in the final answer to the question. This ends the conversation.",
    "input_schema": ANSWER_SCHEMA,
}

# What each way adds to the system prompt. Neither says when to stop reading: what
# such a sentence does is a question of its own, apart from the way an answer comes in.
_BY_TOOL = (
    f"- Give the final answer by calling {ANSWER_TOOL['name']}. "
    "A reply that ends without that call is not an answer.\n"
)
# The schema is quoted whole, so that the model is told here what the API tells it
# when it holds a text to the form, and so that the descriptions of the fields are
# written in one place for all three ways.
_AS_TEXT = (
    "\nGive the final answer as one JSON object and nothing else: no text before or after "
    "it, and no code fence. It has to follow this JSON schema:\n"
    f"{json.dumps(ANSWER_SCHEMA)}\n"
)
_ADDED = {FORMAT: "", TOOL: _BY_TOOL, TEXT: _AS_TEXT}


def system_prompt(channel: str) -> str:
    """The system prompt of a run that hands in its answer in the given way."""
    return SYSTEM_PROMPT + _ADDED[channel]


def unknown_tool_text(name: str, declared: Sequence[str]) -> str:
    """What the model is told when it calls a tool it was never given.

    The loop answers this itself and sends nothing to the server.
    """
    return f"Unknown tool: {name!r}. The tools are: {', '.join(declared)}."


# What the model is told when it calls the loop's tool with arguments that are not an
# answer. One sentence for every such case: the record keeps the arguments, so what
# was wrong with them can be read there.
INVALID_ANSWER_TEXT = (
    "The answer was not accepted. Its arguments have to be: answer (text, not empty), "
    "found (true or false) and evidence (a list, each item with arxiv_id and section_id "
    f"as text), and nothing else. Call {ANSWER_TOOL['name']} again."
)

# What the model is told, once in a run, when it ends its turn without a call of the
# loop's tool. It says what the prompt says already, in the words of the prompt, and
# nothing of the answer or of reading on: the runs that ended this way had written
# their answer as text, and the message is there to get an answer handed in, not to
# change it. It goes back as a message of the user, after the reply as it came.
ASK_AGAIN_TEXT = (
    f"That reply ended without a call of {ANSWER_TOOL['name']}, so no answer was handed in. "
    f"Give the final answer by calling {ANSWER_TOOL['name']}."
)


def as_answer(data: Any) -> dict[str, Any] | None:
    """`data` when it is an answer as the schema describes it, or None when it is not.

    An answer with nothing in it counts as no answer.
    """
    if not isinstance(data, dict) or set(data) != {"answer", "found", "evidence"}:
        return None
    answer, found, evidence = data["answer"], data["found"], data["evidence"]
    if not isinstance(answer, str) or not answer.strip():
        return None
    if not isinstance(found, bool) or not isinstance(evidence, list):
        return None
    for item in evidence:
        if not isinstance(item, dict) or set(item) != {"arxiv_id", "section_id"}:
            return None
        if not all(isinstance(value, str) for value in item.values()):
            return None
    return data


def read_answer(text: str) -> dict[str, Any] | None:
    """The final answer written as text, or None when the text is not that.

    The API holds a text to the schema, but not when a response is cut off or
    refused, and "in most cases" is the documented promise. Without the API nothing
    holds it at all. So the text is checked here: it has to be the JSON object and
    nothing else.
    """
    try:
        data = json.loads(text)
    except ValueError:
        return None
    return as_answer(data)
