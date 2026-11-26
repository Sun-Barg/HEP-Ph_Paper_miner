"""The checks of a program and the two filters of a model, for every draft of a record.

    uv run python -m hepph_paper_miner.drafting.sift \\
        --places runs_private/drafting/round-1/places.jsonl \\
        --drafts runs_private/drafting/round-1/drafts.jsonl \\
        --out runs_private/drafting/round-1/sift.jsonl

First the checks of checks.py, for every draft of every place: their result stands in the
record right after its first line, a line for each draft. A draft that passes them is put
to the model twice, each time once, and the answer is graded by the rule of
eval/grade.py, which says right or wrong of every answer when a key holds numbers and
phrases alone:

    without   the question alone: no paper, no tool. A draft answered right is dropped,
              since its fact can be known or guessed. The form of this answer has no
              "found": with it, a model that is not sure says false, and the rule calls
              that wrong whatever the value, so a fact that it guessed right would pass.
              The rule grades it as if "found" were true.
    passage   the question and the piece of the paper that holds the anchor, as
              read_section returns that piece to a run. A draft is kept only when it is
              answered right: the passage answers the question, and the key fits an
              answer as this model writes one. The prompt is the lines of the runs'
              prompt (agent/prompt.py), with the tools left out, and the form is two
              fields of the runs' answer.

The question either filter sees is the one a run would see: the mark of its paper filled
in with the identifier, or with the title for search_first. Both filters ask with the
judge's settings. Their texts have a name, SIFT_VERSION, and tests/test_sift.py holds
them to it: a change to them is another filter.

A draft passes when it passes every check, is not answered right without the paper, and
is answered right from the passage. Of every place, the first draft in the generator's
order that passes is kept, and its place's others are not: a place makes one question at
most. Every draft that passes the checks is put to both filters, the later ones too, so
that the record says how many drafts of each place could have been kept (the requests
cost little beside those of the generator). The record holds anchors and answers, which
are paper text, so it goes into runs_private/.

A record of the generator d1 has one draft a place, and it is read as a place's first
and only draft (draft.drafts_in): such a round is checked and sifted again by this code.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from hepph_paper_miner.agent.model import Reply
from hepph_paper_miner.agent.origin import file_digest
from hepph_paper_miner.agent.prompt import ANSWER_SCHEMA
from hepph_paper_miner.drafting import ask
from hepph_paper_miner.drafting.assign import Placed, PlacesFile, paper_source, read_places
from hepph_paper_miner.drafting.checks import CHECKS, Checked, check
from hepph_paper_miner.drafting.draft import (
    DRAFT,
    MAX_DRAFTS,
    Draft,
    drafts_in,
    line_of,
    papers_of,
    read_drafts,
    section_of,
)
from hepph_paper_miner.eval.grade import RIGHT, Record, grade_answer
from hepph_paper_miner.eval.judge import JUDGE
from hepph_paper_miner.eval.questions import Question, _question
from hepph_paper_miner.server import SECTION_CHAR_LIMIT, _section, _stop_at
from hepph_paper_miner.sources.arxiv_latex import PARSER_VERSION
from hepph_paper_miner.sources.base import ArxivId, Paper, PaperSource, SourceError
from hepph_paper_miner.survey.records import RecordError

# The name of everything the two filters read beside a question and a piece of a paper:
# their system prompts, the layouts of their requests and the forms of their answers.
SIFT_VERSION = "s1"

WITHOUT = "without"
PASSAGE = "passage"
FILTERS = (WITHOUT, PASSAGE)

# Asked as the judge asks (eval/judge.py): the settings of the runs, as far as they apply.
SIFTING: dict[str, Any] = dict(JUDGE)

WITHOUT_SYSTEM = """\
You answer a question about a physics paper on arXiv. You do not have the paper and you have no tools: answer from what you know about the paper and its field.

- If you are not sure, give the value or the name you find most likely. Do not leave the answer without one.
- Keep the answer short: the facts asked for, with numbers and units.
"""

WITHOUT_MESSAGE = """\
<question>
{question}
</question>
"""

WITHOUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {"answer": dict(ANSWER_SCHEMA["properties"]["answer"])},
    "required": ["answer"],
    "additionalProperties": False,
}

# The lines of the runs' prompt (agent/prompt.py), said of a piece of a paper in place of
# the tools. Not the line on evidence: there is one section, and the rule does not read it.
PASSAGE_SYSTEM = """\
You answer a question about a physics paper on arXiv. You are given one piece of the paper, as a tool returned it.

- Base the answer only on the text given here, not on what you remember about a paper.
- If the text given here does not state what the question asks for, say so and set "found" to false. Do not guess a value.
- Keep the answer short: the facts asked for, with numbers and units as the paper gives them.
"""

PASSAGE_MESSAGE = """\
<text>
{piece}
</text>

<question>
{question}
</question>
"""

PASSAGE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "answer": dict(ANSWER_SCHEMA["properties"]["answer"]),
        "found": dict(ANSWER_SCHEMA["properties"]["found"]),
    },
    "required": ["answer", "found"],
    "additionalProperties": False,
}


def texts_digest() -> str:
    """The digest of everything the two filters read beside a question and a piece."""
    texts = [
        WITHOUT_SYSTEM,
        WITHOUT_MESSAGE,
        WITHOUT_SCHEMA,
        PASSAGE_SYSTEM,
        PASSAGE_MESSAGE,
        PASSAGE_SCHEMA,
    ]
    return hashlib.sha256(json.dumps(texts).encode("utf-8")).hexdigest()


class _OnePaper:
    """A source with one paper, for read_section's own code to cut the piece from."""

    def __init__(self, paper: Paper) -> None:
        self._paper = paper

    def paper(self, arxiv_id: ArxivId) -> Paper:
        return self._paper


def piece_of(paper: Paper, place: Placed) -> str:
    """What read_section returns of the part of a place.

    It begins where the part begins. It is given an end only where the part does not end
    where the tool cuts on its own: the text a section has in front of its subsections,
    which the outline offers to read on its own.
    """
    section = section_of(paper, place.section)
    if section is None:
        raise RecordError(f"{place.paper} has no section {place.section}")
    natural, _ = _stop_at(section.text, place.start, None, SECTION_CHAR_LIMIT)
    end = None if natural == place.end else place.end
    return _section(_OnePaper(paper), place.paper, place.section, place.start, end)


def question_of(draft: Draft, place: Placed, paper: Paper, anchor: str, index: int = 1) -> Question:
    """The question a draft becomes, as a question file would hold it."""
    name = f"draft-{place.number}.{index}"
    line = line_of(draft, place, place.kind, paper.meta.title, anchor, name)
    return _question(line, f"draft {place.number}.{index}")


def draft_of(line: Mapping[str, Any]) -> int:
    """Which draft of its place a line of the record is about: 1 for the first.

    A record made before a place could have more than one draft has no such field, and its
    one draft is the first.
    """
    return line.get("draft", 1)


# --- the checks ----------------------------------------------------------------------------


def checked_line(place: Placed, index: int, checked: Checked) -> dict[str, Any]:
    return {
        "record": "checked",
        "number": place.number,
        "draft": index,
        "paper": place.paper,
        "kind": place.kind,
        "passed": checked.passed,
        "failed": list(checked.failed),
        "why": list(checked.why),
        "anchor": checked.anchor,
        "at": checked.at,
    }


def checks_of(
    places: PlacesFile, drafts: Mapping[int, Mapping[str, Any]], papers: Mapping[str, Paper]
) -> list[dict[str, Any]]:
    """The checks of every draft of a record, in the order of the places and of the drafts."""
    lines = []
    for place in places.places:
        reply = drafts.get(place.number)
        if reply is None or reply.get("outcome") != DRAFT:
            continue
        for index, found in enumerate(drafts_in(reply), start=1):
            draft = Draft.from_dict(found)
            checked = check(draft, papers[place.paper], place, place.kind)
            lines.append(checked_line(place, index, checked))
    return lines


# --- the two filters -----------------------------------------------------------------------


def read_answer(reply: Reply, with_found: bool) -> tuple[dict[str, Any] | None, str | None]:
    """The answer in a reply of a filter, or what keeps it from being one."""
    if reply.stop_reason != "end_turn":
        return None, f"the reply stopped with {reply.stop_reason}"
    try:
        data = json.loads(reply.text)
    except ValueError:
        return None, "the reply is not JSON"
    fields = {"answer", "found"} if with_found else {"answer"}
    if not isinstance(data, dict) or set(data) != fields:
        return None, "the reply does not have the fields of an answer"
    if not isinstance(data["answer"], str) or not data["answer"].strip():
        return None, "the answer is not a text, or is empty"
    if with_found and not isinstance(data["found"], bool):
        return None, "found is neither true nor false"
    # The rule reads "found" from every answer; the answer without the paper is graded as
    # one that says the paper states what was asked.
    return {"answer": data["answer"], "found": data.get("found", True), "evidence": []}, None


def graded(question: Question, answer: Mapping[str, Any]) -> tuple[str, list[str]]:
    """What the rule of eval/grade.py says of an answer: right or wrong, and why."""
    record = Record({}, (), {"answer": dict(answer), "reason": "answered"})
    grade = grade_answer(record, question)
    return grade.rule, list(grade.why)


def jobs_of(
    places: PlacesFile,
    drafts: Mapping[int, Mapping[str, Any]],
    checks: Sequence[Mapping[str, Any]],
    papers: Mapping[str, Paper],
) -> tuple[list[ask.Job], dict[str, tuple[Placed, int, Question, str]]]:
    """Two requests for every draft that passed the checks, and what grades each."""
    by_number = {place.number: place for place in places.places}
    jobs, grading = [], {}
    for line in checks:
        if not line["passed"]:
            continue
        place, index = by_number[line["number"]], draft_of(line)
        paper = papers[place.paper]
        draft = Draft.from_dict(drafts_in(drafts[place.number])[index - 1])
        question = question_of(draft, place, paper, line["anchor"], index)
        name = f"{place.number}.{index}:{WITHOUT}"
        jobs.append(
            ask.Job(
                name,
                WITHOUT_SYSTEM,
                WITHOUT_MESSAGE.format(question=question.question),
                WITHOUT_SCHEMA,
            )
        )
        grading[name] = (place, index, question, WITHOUT)
        name = f"{place.number}.{index}:{PASSAGE}"
        message = PASSAGE_MESSAGE.format(piece=piece_of(paper, place), question=question.question)
        jobs.append(ask.Job(name, PASSAGE_SYSTEM, message, PASSAGE_SCHEMA))
        grading[name] = (place, index, question, PASSAGE)
    return jobs, grading


def on_reply(grading: Mapping[str, tuple[Placed, int, Question, str]]):
    def line(job: ask.Job, reply: Reply) -> dict[str, Any]:
        place, index, question, kind = grading[job.id]
        answer, problem = read_answer(reply, with_found=kind == PASSAGE)
        rule, why = graded(question, answer) if answer is not None else (None, [])
        return {
            "number": place.number,
            "draft": index,
            "filter": kind,
            "outcome": rule or "no_answer",
            "rule": rule,
            "why": why,
            "answer": answer["answer"] if answer else None,
            "found": answer["found"] if answer and kind == PASSAGE else None,
            "problem": problem,
            **({"text": reply.text[:2000]} if problem else {}),
        }

    return line


def filter_replies(lines: Sequence[Mapping[str, Any]]) -> dict[tuple[int, int, str], dict]:
    """The reply line of every filter, by its place, its draft and the filter."""
    return {
        (line["number"], draft_of(line), line["filter"]): dict(line)
        for line in lines
        if line.get("record") == ask.REPLY
    }


def passing(lines: Sequence[Mapping[str, Any]]) -> list[tuple[int, int]]:
    """Every draft that passes, as (place, draft) in the order of the places and the drafts:
    every check passed, not right without the paper, right from the passage."""
    said = filter_replies(lines)
    found = []
    for line in lines:
        if line.get("record") != "checked" or not line["passed"]:
            continue
        number, index = line["number"], draft_of(line)
        without = said.get((number, index, WITHOUT)) or {}
        passage = said.get((number, index, PASSAGE)) or {}
        if without.get("rule") != RIGHT and passage.get("rule") == RIGHT:
            found.append((number, index))
    return sorted(found)


def kept(lines: Sequence[Mapping[str, Any]]) -> dict[int, int]:
    """The draft every place keeps, by place: its first draft that passes, in the
    generator's order. A place none of whose drafts passes is not there."""
    found: dict[int, int] = {}
    for number, index in passing(lines):
        found.setdefault(number, index)
    return found


def totals(lines: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """The last line of a record, from its other lines."""
    checks = [line for line in lines if line.get("record") == "checked"]
    said = [line for line in lines if line.get("record") == ask.REPLY]
    keep = kept(lines)

    def right(kind: str) -> int:
        return sum(1 for line in said if line["filter"] == kind and line["rule"] == RIGHT)

    return {
        "record": ask.END,
        "places": len({line["number"] for line in checks}),
        "drafts": len(checks),
        "passed_checks": sum(1 for line in checks if line["passed"]),
        "failed_checks": {
            name: sum(1 for line in checks if name in line["failed"]) for name in CHECKS
        },
        "right_without_the_paper": right(WITHOUT),
        "right_from_the_passage": right(PASSAGE),
        "no_answer": sum(1 for line in said if line["rule"] is None),
        "passed": len(passing(lines)),
        "kept": len(keep),
        "kept_by_draft": {
            str(index): sum(1 for each in keep.values() if each == index)
            for index in range(1, MAX_DRAFTS + 1)
        },
        "failed": sum(1 for line in lines if line.get("record") == ask.FAILED),
        **ask.usage_totals(said),
    }


def read_sift(path: Path) -> tuple[dict[str, Any], list[dict[str, Any]], str]:
    """A finished record of the filters: its first line, its lines, and its SHA-256."""
    head, lines, end = ask.read_record(path, "sift")
    if end is None:
        raise RecordError(f"{path.name}: the filters have not finished (no last line)")
    return head, lines, file_digest(path)


def head_of(
    asker: ask.Asker,
    code: Mapping[str, Any],
    places: PlacesFile,
    drafts_head: Mapping[str, Any],
    drafts: Path,
) -> dict[str, Any]:
    return {
        "record": "sift",
        "sift_version": SIFT_VERSION,
        "texts_sha256": texts_digest(),
        "settings": asker.settings,
        "code": dict(code),
        "places": places.stamp,
        "drafts": {
            "file": drafts.name,
            "sha256": file_digest(drafts),
            "drafter_version": drafts_head.get("drafter_version"),
            "texts_sha256": drafts_head.get("texts_sha256"),
        },
        "checks": list(CHECKS),
        "parser_version": PARSER_VERSION,
    }


def main(
    argv: Sequence[str] | None = None,
    asker: ask.Asker | None = None,
    source: PaperSource | None = None,
) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m hepph_paper_miner.drafting.sift",
        description="Check every draft of a record, and put the drafts that pass to the "
        "two filters.",
    )
    parser.add_argument("--places", type=Path, required=True, help="the file of places")
    parser.add_argument("--drafts", type=Path, required=True, help="the record of the generator")
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
        drafts_head, drafts, _ = read_drafts(arguments.drafts)
        if drafts_head.get("places") != places.stamp:
            raise RecordError(f"{arguments.drafts.name} is not a record of {places.name}")
        papers = papers_of(places, source or paper_source())
        checks = checks_of(places, drafts, papers)
        jobs, grading = jobs_of(places, drafts, checks, papers)
    except (OSError, RecordError, SourceError, ask.AskError) as error:
        print(f"refused: {error}", file=sys.stderr)
        return 2
    passed = sum(1 for line in checks if line["passed"])
    placed = len({line["number"] for line in checks})
    print(f"{len(checks)} draft(s) of {placed} place(s): {passed} pass the checks")
    given = asker is not None
    asker = asker or ask.ClaudeAsker(SIFTING)
    head = head_of(asker, ask.checked_code(), places, drafts_head, arguments.drafts)
    runner = ask.Runner(asker, jobs, arguments.out, on_reply(grading), arguments.parallel)
    status, lines = ask.run_command(
        out=arguments.out,
        record="sift",
        head=head,
        runner=runner,
        totals=totals,
        plan_only=arguments.plan,
        given=given,
        what="the filters",
        after_head=checks,
    )
    if status == 0 and not arguments.plan:
        summed = totals(lines)
        print(
            f"{summed['drafts']} draft(s) of {summed['places']} place(s): "
            f"{summed['passed_checks']} passed the checks, "
            f"{summed['right_without_the_paper']} right without the paper, "
            f"{summed['right_from_the_passage']} right from the passage, "
            f"{summed['passed']} passed everything"
        )
        by_draft = ", ".join(f"draft {name}: {n}" for name, n in summed["kept_by_draft"].items())
        print(f"{summed['kept']} place(s) keep a draft ({by_draft})")
        failed = ", ".join(f"{name} {n}" for name, n in summed["failed_checks"].items() if n)
        if failed:
            print(f"checks failed (a draft counts under each it failed): {failed}")
        if summed["cost"] is not None:
            print(f"cost, computed: ${summed['cost']:.2f}")
    return status


if __name__ == "__main__":
    sys.exit(main())
