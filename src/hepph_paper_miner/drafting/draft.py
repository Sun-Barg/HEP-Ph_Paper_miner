"""The generator: a model drafts one question for every place of a file of places.

    uv run python -m hepph_paper_miner.drafting.draft \\
        --places runs_private/drafting/round-1/places.jsonl \\
        --out runs_private/drafting/round-1/drafts.jsonl

One request for every place. It holds the whole paper as the tools return it (the four
lines of its listing, and its text with a marker line in front of every section, not cut
at the limit of read_paper), and then the part that was given out, once more on its own:
its section, its title, where it begins and ends, and its text. Marking the part inside
the whole text would put the marks among the characters an anchor is copied from. The
kind of the place is not given: the five kinds share one text, and the name of a kind
would find its way into the words of a question ("in the appendix").

The reply is held to a form (DRAFT_SCHEMA): a question with the mark {paper} where it
names the paper, an anchor copied from the part, a reference answer, an answer key of
numbers and phrases, and a note on what is accepted; or that the part holds nothing to
ask about, and why. Every field is required. The API writes the required fields first
and the others after them, so a form with optional fields would change the order in
which the model writes (platform.claude.com/docs/en/build-with-claude/structured-outputs,
read 2026-11-26). The order is the order of work: whether there is something to ask,
the passage, then the question, the answer, the key and the note. The limits that a form
cannot hold (the length of a text, the least value of a number) are checked by a program
afterwards (checks.py).

The texts the generator reads have a name, DRAFTER_VERSION, and tests/test_draft.py holds
them to it: a change to them is another generator. The settings are the judge's, with
one difference: the thinking of the generator comes back as a summary. The model thinks
and is billed the same either way, and the summary is the one place where a round of the
tuning can see why a part was turned down or a fact was taken
(platform.claude.com/docs/build-with-claude/thinking, read 2026-11-26). The summary is
written by another model than the one that thought, so it is a hint and not the reason.

The record holds paper text (the drafts, and summaries that can quote the paper), so it
is written into runs_private/ and never committed. The command refuses a path that git
would not ignore.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from hepph_paper_miner.agent.model import Reply
from hepph_paper_miner.agent.origin import file_digest
from hepph_paper_miner.drafting import ask
from hepph_paper_miner.drafting.assign import Placed, PlacesFile, paper_source, read_places
from hepph_paper_miner.drafting.places import SEARCH_FIRST
from hepph_paper_miner.eval.judge import JUDGE
from hepph_paper_miner.server import _listing_lines, full_text
from hepph_paper_miner.sources.arxiv_latex import PARSER_VERSION
from hepph_paper_miner.sources.base import Paper, PaperSource, SourceError, parse_arxiv_id
from hepph_paper_miner.survey.records import RecordError

# The name of everything the generator reads beside the paper: the system prompt, the
# layout of a request and the form of a draft. Raise it with any of them.
DRAFTER_VERSION = "d1"

# Where a question names its paper. It becomes the identifier or the title (fill_paper).
PAPER_MARK = "{paper}"

# The judge's settings (eval/judge.py), with the thinking shown as a summary.
DRAFTING: dict[str, Any] = {**JUDGE, "thinking": {"type": "adaptive", "display": "summarized"}}

# The same text for every place, so it names no paper and no fact of one. Its rules are
# the ones the checks of checks.py hold a draft to, so that a draft is not made only to
# be dropped. Its last line is the judge's: the sentence the API documentation gives to
# encourage thinking, word for word, since steering is sensitive to the wording
# (platform.claude.com/docs/en/build-with-claude/thinking-steering-and-cost, read again
# 2026-11-26).
SYSTEM_PROMPT = """\
You write one question about a physics paper. The question tests whether a model that reads papers through tools finds a fact in a paper. You are given the whole paper, and one part of it. The question has to be about a fact that this part states.

What to ask
- One fact that a sentence of the running text of the part states: a number of two or more digits, or a name. The paper writes its value in this part and nowhere else.
- Not a fact of a table, a figure or its caption, an equation, a footnote, a list of authors or the references.
- Not a value that the title or the abstract states.
- A fact the paper states, not a judgment, a summary or a reason.
- The question has to read one way in the whole paper. If the same quantity stands elsewhere in the paper under other conditions, say in the question which conditions are meant.

How to write it
- Write {paper} once in the question, where it names the paper, as a noun phrase: "In {paper}, which ..." or "{paper} fits ...; what ...". It is replaced by the identifier or by the title of the paper.
- Do not name the section, its number or its title, and do not write "appendix", "Section 3", "Eq. (5)", "Fig. 2", "Table 1" or the like. Do not write the value that is asked for.
- The anchor is a piece of one line of the part, copied character for character as it stands there, TeX and all, 20 to 120 characters long. It holds every number and every name of the answer key.
- The reference answer is short: the fact, with numbers and units as the paper gives them.
- The answer key is what a program looks for in an answer. "numbers": each value as a number, its unit as the paper gives it ("" when there is none), and the fewest significant digits an answer may round it to and still be right. "phrases": each name, with the wordings an answer may use, as plain text.
- The note says what an answer has to contain, what it may leave out, and which answers are wrong (another value of the same passage, for example).
- Write in English.

If the part states no fact of this kind, set "nothing_to_ask" to true, say why in one sentence in "why_nothing", and leave every other field empty: empty texts and empty lists.

This task involves multistep reasoning. Think carefully before responding.
"""

# One request: the paper as the tools return it, then the part on its own.
MESSAGE = """\
<paper>
{listing}

{text}
</paper>

<part>
Section: {section} | {title}
Characters {start} to {end} of {chars}

{part}
</part>
"""

_NUMBER_ITEM: dict[str, Any] = {
    "type": "object",
    "properties": {
        "label": {"type": "string", "description": "What the number is, in a few words."},
        "value": {"type": "number", "description": "The number as the paper gives it."},
        "unit": {
            "type": "string",
            "description": "Its unit as the paper gives it, or an empty text.",
        },
        "min_sig_figs": {
            "type": "integer",
            "description": (
                "The fewest significant digits an answer may round the value to and still be right."
            ),
        },
    },
    "required": ["label", "value", "unit", "min_sig_figs"],
    "additionalProperties": False,
}

_PHRASE_ITEM: dict[str, Any] = {
    "type": "object",
    "properties": {
        "label": {"type": "string", "description": "What the name is, in a few words."},
        "any_of": {
            "type": "array",
            "items": {"type": "string"},
            "minItems": 1,
            "description": (
                "Wordings an answer may use, as plain text; one of them has to be there."
            ),
        },
    },
    "required": ["label", "any_of"],
    "additionalProperties": False,
}

# The form of a draft. Every field is required, in the order of the work (see above), and
# no field asks for reasoning: the reasoning has its own place before the reply.
DRAFT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "nothing_to_ask": {
            "type": "boolean",
            "description": ("true when the part states no fact to ask about; false for a draft."),
        },
        "why_nothing": {
            "type": "string",
            "description": "Why there is nothing to ask, in one sentence. Empty for a draft.",
        },
        "anchor": {
            "type": "string",
            "description": "Copied exactly from one line of the part, 20 to 120 characters.",
        },
        "question": {
            "type": "string",
            "description": "The question, with {paper} once where it names the paper.",
        },
        "reference_answer": {
            "type": "string",
            "description": (
                "A short complete answer, with numbers and units as the paper gives them."
            ),
        },
        "numbers": {
            "type": "array",
            "items": _NUMBER_ITEM,
            "description": "The numbers an answer has to hold. Empty when there are none.",
        },
        "phrases": {
            "type": "array",
            "items": _PHRASE_ITEM,
            "description": "The names an answer has to hold. Empty when there are none.",
        },
        "accept_note": {
            "type": "string",
            "description": (
                "What an answer has to contain, what it may leave out, and which answers are wrong."
            ),
        },
    },
    "required": [
        "nothing_to_ask",
        "why_nothing",
        "anchor",
        "question",
        "reference_answer",
        "numbers",
        "phrases",
        "accept_note",
    ],
    "additionalProperties": False,
}

DRAFT = "draft"
NOTHING = "nothing_to_ask"
NO_DRAFT = "no_draft"  # the reply is no draft: cut short, refused, or of another form


def texts_digest() -> str:
    """The digest of everything the generator reads beside a paper."""
    texts = [SYSTEM_PROMPT, MESSAGE, DRAFT_SCHEMA]
    return hashlib.sha256(json.dumps(texts).encode("utf-8")).hexdigest()


def section_of(paper: Paper, section_id: str):
    """The section of a paper with this identifier, or None."""
    return next((s for s in paper.sections if s.section_id == section_id), None)


def message_for(paper: Paper, place: Placed) -> str:
    """The request for one place: the whole paper, then the part."""
    section = section_of(paper, place.section)
    if section is None:
        raise RecordError(f"{place.paper} has no section {place.section}")
    return MESSAGE.format(
        listing="\n".join(_listing_lines(paper.meta)),
        text=full_text(paper),
        section=section.section_id,
        title=section.title,
        start=place.start,
        end=place.end,
        chars=section.chars,
        part=section.text[place.start : place.end],
    )


# --- a draft -------------------------------------------------------------------------------


@dataclass(frozen=True)
class Draft:
    """A question as the generator wrote it, before any check."""

    anchor: str
    question: str  # with PAPER_MARK
    reference_answer: str
    numbers: tuple[dict[str, Any], ...]  # label, value, unit, min_sig_figs
    phrases: tuple[dict[str, Any], ...]  # label, any_of
    accept_note: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "anchor": self.anchor,
            "question": self.question,
            "reference_answer": self.reference_answer,
            "numbers": [dict(item) for item in self.numbers],
            "phrases": [dict(item) for item in self.phrases],
            "accept_note": self.accept_note,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> Draft:
        return cls(
            data["anchor"],
            data["question"],
            data["reference_answer"],
            tuple(dict(item) for item in data["numbers"]),
            tuple(dict(item) for item in data["phrases"]),
            data["accept_note"],
        )


@dataclass(frozen=True)
class Read:
    outcome: str  # DRAFT, NOTHING or NO_DRAFT
    draft: Draft | None
    why_nothing: str | None
    problem: str | None  # what keeps a reply from being a draft


def _is_number(value: Any) -> bool:
    return isinstance(value, int | float) and not isinstance(value, bool) and math.isfinite(value)


def read_draft(reply: Reply) -> Read:
    """The draft in a reply, or that there is nothing to ask, or what keeps it from being either."""
    if reply.stop_reason != "end_turn":
        # A refusal or a text cut short need not have the form, whatever it looks like.
        return Read(NO_DRAFT, None, None, f"the reply stopped with {reply.stop_reason}")
    try:
        data = json.loads(reply.text)
    except ValueError:
        return Read(NO_DRAFT, None, None, "the reply is not JSON")
    if not isinstance(data, dict) or set(data) != set(DRAFT_SCHEMA["required"]):
        return Read(NO_DRAFT, None, None, "the reply does not have the fields of a draft")
    texts = ("why_nothing", "anchor", "question", "reference_answer", "accept_note")
    if not isinstance(data["nothing_to_ask"], bool) or not all(
        isinstance(data[name], str) for name in texts
    ):
        return Read(NO_DRAFT, None, None, "a field of the reply is not of its kind")
    if data["nothing_to_ask"]:
        return Read(NOTHING, None, data["why_nothing"], None)
    numbers, phrases = data["numbers"], data["phrases"]
    if not isinstance(numbers, list) or not isinstance(phrases, list):
        return Read(NO_DRAFT, None, None, "numbers or phrases is not a list")
    for item in numbers:
        if (
            not isinstance(item, dict)
            or set(item) != {"label", "value", "unit", "min_sig_figs"}
            or not isinstance(item["label"], str)
            or not _is_number(item["value"])
            or not isinstance(item["unit"], str)
            or not isinstance(item["min_sig_figs"], int)
            or isinstance(item["min_sig_figs"], bool)
        ):
            return Read(NO_DRAFT, None, None, "an item of numbers is not of the form")
    for item in phrases:
        if (
            not isinstance(item, dict)
            or set(item) != {"label", "any_of"}
            or not isinstance(item["label"], str)
            or not isinstance(item["any_of"], list)
            or not all(isinstance(wording, str) for wording in item["any_of"])
        ):
            return Read(NO_DRAFT, None, None, "an item of phrases is not of the form")
    draft = Draft(
        data["anchor"],
        data["question"],
        data["reference_answer"],
        tuple(numbers),
        tuple(phrases),
        data["accept_note"],
    )
    return Read(DRAFT, draft, None, None)


# --- from a draft to a line of a question file --------------------------------------------


def fill_paper(question: str, kind: str, paper_id: str, title: str) -> str:
    """The question with its paper named: by the title for search_first, else by the identifier.

    Only the title form is given a capital at the head of a sentence ("The paper titled").
    The identifier keeps its own spelling: the questions of the first evaluation begin
    with "arXiv:2610.26648v1 studies ...".
    """
    if kind == SEARCH_FIRST:
        named = question.replace(PAPER_MARK, f'the paper titled "{title}"', 1)
        return "T" + named[1:] if question.startswith(PAPER_MARK) else named
    return question.replace(PAPER_MARK, f"arXiv:{paper_id}", 1)


def key_of(draft: Draft) -> dict[str, Any]:
    """The answer key of a question file, from the key of a draft: an empty unit is left out."""
    key: dict[str, Any] = {}
    if draft.numbers:
        key["numbers"] = [
            {
                "label": item["label"],
                "value": item["value"],
                **({"unit": item["unit"]} if item["unit"].strip() else {}),
                "min_sig_figs": item["min_sig_figs"],
            }
            for item in draft.numbers
        ]
    if draft.phrases:
        key["phrases"] = [
            {"label": item["label"], "any_of": list(item["any_of"])} for item in draft.phrases
        ]
    return key


def line_of(
    draft: Draft, place: Placed, kind: str, title: str, anchor: str, question_id: str
) -> dict[str, Any]:
    """The line of a question file that a draft becomes, with the anchor as the paper writes it.

    `kind` is the kind the question is asked as: search_first for a named_first place
    that the question names by its title.
    """
    return {
        "id": question_id,
        "question": fill_paper(draft.question, kind, place.paper, title),
        "type": kind,
        "gold_papers": [place.paper],
        "gold_evidence": {
            "need": "all",
            "items": [{"arxiv_id": place.paper, "section_id": place.section, "anchor": anchor}],
        },
        "expect_found": True,
        "reference_answer": draft.reference_answer,
        "answer_key": key_of(draft),
        "accept_note": draft.accept_note,
        "abstract_sufficient": False,
        "notes": {
            "kind": kind,
            "place": f"{place.section} {place.start}-{place.end}",
            "drafted": DRAFTER_VERSION,
        },
    }


# --- the record ----------------------------------------------------------------------------


def papers_of(places: PlacesFile, source: PaperSource) -> dict[str, Paper]:
    """The papers the places are in, read as the tools read them, and checked against the file."""
    if places.head.get("parser_version") != PARSER_VERSION:
        raise RecordError(
            f"{places.name} was made by parser {places.head.get('parser_version')}, "
            f"and this code splits papers with parser {PARSER_VERSION}"
        )
    papers: dict[str, Paper] = {}
    for place in places.places:
        if place.paper not in papers:
            papers[place.paper] = source.paper(parse_arxiv_id(place.paper))
        section = section_of(papers[place.paper], place.section)
        if section is None or not 0 <= place.start < place.end <= section.chars:
            raise RecordError(f"place {place.number} is not where {places.name} says it is")
    return papers


def head_of(asker: ask.Asker, code: Mapping[str, Any], places: PlacesFile) -> dict[str, Any]:
    return {
        "record": "drafts",
        "drafter_version": DRAFTER_VERSION,
        "texts_sha256": texts_digest(),
        "settings": asker.settings,
        "code": dict(code),
        "places": places.stamp,
        "parser_version": PARSER_VERSION,
    }


def jobs_of(places: PlacesFile, papers: Mapping[str, Paper]) -> list[ask.Job]:
    return [
        ask.Job(
            str(place.number), SYSTEM_PROMPT, message_for(papers[place.paper], place), DRAFT_SCHEMA
        )
        for place in places.places
    ]


def on_reply(places: PlacesFile):
    by_number = {str(place.number): place for place in places.places}

    def line(job: ask.Job, reply: Reply) -> dict[str, Any]:
        place = by_number[job.id]
        read = read_draft(reply)
        found: dict[str, Any] = {
            "number": place.number,
            "paper": place.paper,
            "kind": place.kind,
            "outcome": read.outcome,
            "draft": read.draft.as_dict() if read.draft else None,
            "why_nothing": read.why_nothing,
            "problem": read.problem,
            "thinking": ask.thoughts(reply),
        }
        if read.problem is not None:
            # What the generator wrote in place of a draft, for the private record.
            found["text"] = reply.text[:4000]
        return found

    return line


def totals(lines: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """The last line of a record, from its other lines."""
    replies = [line for line in lines if line.get("record") == ask.REPLY]
    outcomes = Counter(line.get("outcome") for line in replies)
    return {
        "record": ask.END,
        "requests": len(replies),
        "outcomes": {name: outcomes[name] for name in (DRAFT, NOTHING, NO_DRAFT)},
        "failed": sum(1 for line in lines if line.get("record") == ask.FAILED),
        **ask.usage_totals(replies),
    }


def read_drafts(path: Path) -> tuple[dict[str, Any], dict[int, dict[str, Any]], str]:
    """A finished record of drafts: its first line, its reply lines by place, and its SHA-256."""
    head, lines, end = ask.read_record(path, "drafts")
    if end is None:
        raise RecordError(f"{path.name}: the generator has not finished (no last line)")
    by_place = {line["number"]: line for line in lines if line.get("record") == ask.REPLY}
    return head, by_place, file_digest(path)


def main(
    argv: Sequence[str] | None = None,
    asker: ask.Asker | None = None,
    source: PaperSource | None = None,
) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m hepph_paper_miner.drafting.draft",
        description="Ask the generator for a draft of a question about every place of a file.",
    )
    parser.add_argument("--places", type=Path, required=True, help="the file of places")
    parser.add_argument(
        "--out", type=Path, required=True, help="the record to write, in runs_private/"
    )
    parser.add_argument(
        "--parallel", type=int, default=1, help="requests at a time (default: %(default)s)"
    )
    parser.add_argument("--plan", action="store_true", help="say what would be asked, and stop")
    arguments = parser.parse_args(argv)

    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="backslashreplace")
    problem = ask.private_path_problem(arguments.out)
    if problem:
        print(f"refused: {problem}", file=sys.stderr)
        return 2
    try:
        places = read_places(arguments.places)
        papers = papers_of(places, source or paper_source())
        jobs = jobs_of(places, papers)
    except (OSError, RecordError, SourceError) as error:
        print(f"refused: {error}", file=sys.stderr)
        return 2
    given = asker is not None
    asker = asker or ask.ClaudeAsker(DRAFTING)
    head = head_of(asker, ask.checked_code(), places)
    runner = ask.Runner(asker, jobs, arguments.out, on_reply(places), arguments.parallel)
    status, lines = ask.run_command(
        out=arguments.out,
        record="drafts",
        head=head,
        runner=runner,
        totals=totals,
        plan_only=arguments.plan,
        given=given,
        what="the generator",
    )
    if status == 0 and not arguments.plan:
        summed = totals(lines)
        counts = ", ".join(f"{name} {count}" for name, count in summed["outcomes"].items())
        print(f"{summed['requests']} reply(ies): {counts}")
        if summed["cost"] is not None:
            print(f"cost, computed: ${summed['cost']:.2f}")
    return status


if __name__ == "__main__":
    sys.exit(main())
