"""The text of a tool result: how its first line is written, and how it is read back.

Every tool returns one piece of text. Its first line has a fixed form, so that a
program (the run record of the loop, a grader) can tell what the model was given
without understanding the prose below it:

    search | 2 of 31 results | query='dark matter'
    outline | 2610.26648v1 | 143454 chars | 29 sections | parser 3
    outline | 2503.00001v1 | no sections | no_full_text
    section | 2610.26648v1 | 7.2 | 6894 chars | complete
    section | 2610.26648v1 | 6.3 | chars 0-19837 of 25531 | partial, more follows
    section | 2610.26648v1 | 6.3 | chars 19837-25531 of 25531 | partial, end of section
    paper | 2610.26648v1 | 144711 chars | 29 sections | parser 3 | complete
    paper | 2610.26648v1 | chars 0-399960 of 612345 | 40 sections | parser 3 | partial, more follows
    paper | 2503.00001v1 | no text | no_full_text

The code that writes a line and the code that reads it stand side by side here, and a
test sends every form through both. The model reads these lines too: change a form
and TOOLSET_VERSION in server.py has to go up.
"""

from __future__ import annotations

import re
from typing import Any

COMPLETE = "complete"
MORE_FOLLOWS = "more_follows"  # written as "partial, more follows"
END = "end"  # written as "partial, end of section" (or "of paper"): the last piece


# --- writing -------------------------------------------------------------------------


def search_line(shown: int, total: int, asked: str) -> str:
    return f"search | {shown} of {total} results | {asked}"


def outline_line(arxiv_id: str, chars: int, sections: int, parser_version: str) -> str:
    return f"outline | {arxiv_id} | {chars} chars | {sections} sections | parser {parser_version}"


def outline_without_sections_line(arxiv_id: str, kind: str) -> str:
    return f"outline | {arxiv_id} | no sections | {kind}"


def section_line(arxiv_id: str, section_id: str, start: int, stop: int, chars: int) -> str:
    size, state = _extent(start, stop, chars, "section")
    return f"section | {arxiv_id} | {section_id} | {size} | {state}"


def paper_line(
    arxiv_id: str, start: int, stop: int, chars: int, sections: int, parser_version: str
) -> str:
    size, state = _extent(start, stop, chars, "paper")
    return f"paper | {arxiv_id} | {size} | {sections} sections | parser {parser_version} | {state}"


def paper_without_text_line(arxiv_id: str, kind: str) -> str:
    return f"paper | {arxiv_id} | no text | {kind}"


def _extent(start: int, stop: int, chars: int, unit: str) -> tuple[str, str]:
    """How much of a text a result holds: all of it, a piece with more to come, or the last piece.

    A piece is called partial also when it is the last one. A reader who gets
    "partial" and nothing else cannot tell "go on" from "you have reached the end".
    """
    if start == 0 and stop == chars:
        return f"{chars} chars", "complete"
    state = "more follows" if stop < chars else f"end of {unit}"
    return f"chars {start}-{stop} of {chars}", f"partial, {state}"


# --- reading -------------------------------------------------------------------------

_WHOLE = re.compile(r"(\d+) chars")
_PIECE = re.compile(r"chars (\d+)-(\d+) of (\d+)")
_COUNT = re.compile(r"(\d+) sections")
_SHOWN = re.compile(r"(\d+) of (\d+) results")
_HIT = re.compile(r"\d+\. (\S+) \| ")
_KIND = re.compile(r"\[([a-z_]+)\]")
_SDK_ERROR = re.compile(r"Error executing tool [^\s:]+")


def read_first_line(text: str) -> dict[str, Any] | None:
    """What the first line of a result says, or None when it has none of the known forms.

    For a search the identifiers that were returned are read from the lines below
    the first one, in the order shown: a grader needs them, and they are not paper text.
    """
    first, _, rest = text.partition("\n")
    try:
        if first.startswith("search | "):
            shown, asked = first.removeprefix("search | ").split(" | ", 1)
            counted = _SHOWN.fullmatch(shown)
            ids = [hit.group(1) for line in rest.split("\n") if (hit := _HIT.match(line))]
            return {
                "shape": "search",
                "shown": int(counted.group(1)),
                "total": int(counted.group(2)),
                "asked": asked,
                "ids": ids,
            }
        parts = first.split(" | ")
        if parts[0] == "outline" and len(parts) == 4 and parts[2] == "no sections":
            return {"shape": "outline", "arxiv_id": parts[1], "no_sections": parts[3]}
        if parts[0] == "outline" and len(parts) == 5:
            return {
                "shape": "outline",
                "arxiv_id": parts[1],
                "chars": int(_WHOLE.fullmatch(parts[2]).group(1)),
                "sections": int(_COUNT.fullmatch(parts[3]).group(1)),
                "parser": parts[4].removeprefix("parser "),
            }
        if parts[0] == "section" and len(parts) == 5:
            return {
                "shape": "section",
                "arxiv_id": parts[1],
                "section_id": parts[2],
                **_read_extent(parts[3], parts[4]),
            }
        if parts[0] == "paper" and len(parts) == 4 and parts[2] == "no text":
            return {"shape": "paper", "arxiv_id": parts[1], "no_text": parts[3]}
        if parts[0] == "paper" and len(parts) == 6:
            return {
                "shape": "paper",
                "arxiv_id": parts[1],
                **_read_extent(parts[2], parts[5]),
                "sections": int(_COUNT.fullmatch(parts[3]).group(1)),
                "parser": parts[4].removeprefix("parser "),
            }
    except (AttributeError, ValueError):
        # A line that begins like one of the forms and then breaks it: say "unknown"
        # so that the record shows it, and do not guess.
        return None
    return None


def _read_extent(size: str, state: str) -> dict[str, Any]:
    whole = _WHOLE.fullmatch(size)
    if whole and state == "complete":
        chars = int(whole.group(1))
        return {"start": 0, "stop": chars, "chars": chars, "extent": COMPLETE}
    piece = _PIECE.fullmatch(size)
    start, stop, chars = (int(number) for number in piece.groups())
    if state == "partial, more follows":
        return {"start": start, "stop": stop, "chars": chars, "extent": MORE_FOLLOWS}
    if state.startswith("partial, end of "):
        return {"start": start, "stop": stop, "chars": chars, "extent": END}
    raise ValueError(state)


def error_kind(text: str) -> str:
    """Classify the text of an error result.

    The server starts its own sentences with the kind in brackets, and the SDK puts
    "Error executing tool <name>: " in front. What comes back is one of:

        the bracketed kind     an expected failure, for example "not_found"
        "invalid_arguments"    the SDK refused the arguments before the tool ran
                               (they broke the schema); its text has no bracket
        "unexpected"           the tool raised something nobody planned for; the SDK
                               sends the bare "Error executing tool <name>"
        "unknown_tool"         the server has no tool of that name
        "unrecognised"         none of the above
    """
    prefix = _SDK_ERROR.match(text)
    if prefix is None:
        kind = _KIND.match(text)
        if kind:
            return kind.group(1)
        return "unknown_tool" if text.startswith("Unknown tool") else "unrecognised"
    told = text[prefix.end() :]
    if not told.strip():
        return "unexpected"
    kind = _KIND.match(told.removeprefix(": "))
    return kind.group(1) if kind else "invalid_arguments"
