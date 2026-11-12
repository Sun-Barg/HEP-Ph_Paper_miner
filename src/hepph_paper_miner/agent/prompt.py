"""Everything the loop itself says to the model, and the form the final answer takes.

The tools speak for themselves (their texts belong to the server and to
TOOLSET_VERSION). What is written here is the rest of what the model reads: the
system prompt, the descriptions inside the answer schema, and the one error message
the loop writes itself. A change to any of them is a different experiment, so
PROMPT_VERSION has to go up with it.

The same texts are used with both tool layouts, so they name no tool. They also name
no paper and no fact from a paper: an example in a prompt is a hint.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Any

PROMPT_VERSION = "p1"

SYSTEM_PROMPT = """\
You answer questions about physics papers on arXiv. You can read papers only through the tools.

- Find the paper the question is about and read what you need.
- Base the answer only on text the tools returned in this conversation, not on what you remember about a paper.
- If the papers you read do not state what the question asks for, say so and set "found" to false. Do not guess a value.
- In "evidence", list every section the answer relies on: the arXiv identifier with its version and the section id, exactly as the tools showed them. List only sections you read.
- Keep the answer short: the facts asked for, with numbers and units as the paper gives them.
"""

# The final answer is the text of the response that ends the turn, held to this schema
# by the API (output_config.format). There is no "answer" tool: this model cannot be
# forced to call one, and a run that ended without the call would have no answer at
# all. There is no field for reasoning either: the API may refuse a request that asks
# for the model's reasoning in its output.
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


def unknown_tool_text(name: str, declared: Sequence[str]) -> str:
    """What the model is told when it calls a tool the server never declared.

    The loop answers this itself and sends nothing to the server.
    """
    return f"Unknown tool: {name!r}. The tools are: {', '.join(declared)}."


def read_answer(text: str) -> dict[str, Any] | None:
    """The final answer as the schema describes it, or None when the text is not that.

    The API holds the text to the schema, but not when a response is cut off or
    refused, and "in most cases" is the documented promise. So the text is checked
    here, and an answer with nothing in it counts as no answer.
    """
    try:
        data = json.loads(text)
    except ValueError:
        return None
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
