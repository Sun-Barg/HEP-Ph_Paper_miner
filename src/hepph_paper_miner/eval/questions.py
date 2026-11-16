"""Questions with reference answers, one JSON object per line.

A question names where its answer stands: papers (identifiers with a version) and
sections in them. Section identifiers are made by the parser, so a change to the
parser can leave a question pointing at nothing. `problems_with_evidence` finds that.

The fields of one line:

    id                   a name for the question, unique in its file: letters, digits,
                         "." and "-" (it becomes part of the name of a run's files)
    question             what the model is asked, in English
    type                 what the question is meant to test, in a word or two
    gold_papers          the papers that hold the answer
    gold_evidence        where in them: {"need": "all" or "any", "items": [...]}, each
                         item {"arxiv_id", "section_id", "anchor"}. The anchor is a
                         short piece of the section's text, exactly as it stands
                         there, that marks the place of the fact. It may be left out.
    expect_found         false when the right answer is "the papers do not say"
    reference_answer     the answer a grader compares with
    answer_key           what a rule can check, each part a list that may be left out:
                         "numbers" the answer has to hold ({"label", "value"}, and if
                         wanted "unit" and "min_sig_figs": how few digits still count),
                         "phrases" ({"label", "any_of": wordings, one of which has to be
                         there}), "wrong_numbers" that send an answer to a person
                         ({"label", "value"}), and "by_hand": what only a person can judge
    accept_note          what counts as correct, in the question writer's words
    abstract_sufficient  true when the abstract alone answers the question
    notes                anything else worth keeping, by topic

Positions are not written into the file. They follow from the anchor and the parsed
paper, so they cannot go stale when the way a long section is cut changes.
"""

from __future__ import annotations

import json
import math
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from hepph_paper_miner.sources.base import Paper, SourceError, parse_arxiv_id

_REQUIRED = (
    "id",
    "question",
    "type",
    "gold_papers",
    "gold_evidence",
    "expect_found",
    "reference_answer",
    "answer_key",
    "accept_note",
    "abstract_sufficient",
)
_TEXTS = ("id", "question", "type", "reference_answer", "accept_note")
_EVIDENCE_FIELDS = ("arxiv_id", "section_id", "anchor")
# The parts of an answer key, and the fields an item of each may have. The first two
# fields of an item have to be there.
_KEY_PARTS = {
    "numbers": ("label", "value", "unit", "min_sig_figs"),
    "wrong_numbers": ("label", "value", "unit"),
    "phrases": ("label", "any_of"),
}
# An id goes into the name of a run and of its files, where "_" stands between the parts.
_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9.-]*")


@dataclass(frozen=True)
class Evidence:
    """One place that holds (part of) the answer."""

    arxiv_id: str
    section_id: str
    anchor: str | None = None


@dataclass(frozen=True)
class Question:
    id: str
    question: str
    type: str
    gold_papers: tuple[str, ...]
    need: str  # "all": every piece of evidence is needed; "any": one of them is enough
    evidence: tuple[Evidence, ...]
    expect_found: bool
    reference_answer: str
    answer_key: dict[str, Any]
    accept_note: str
    abstract_sufficient: bool
    notes: dict[str, str] = field(default_factory=dict)


class QuestionFileError(ValueError):
    """A question file that cannot be used. The message names the line."""


def load_questions(path: Path) -> tuple[Question, ...]:
    """Read a question file, and refuse it as a whole when one line is wrong.

    A question that is half right would be asked and graded like any other, and its
    result would mean nothing.
    """
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError as error:
        raise QuestionFileError(f"{path.name}: not UTF-8 text ({error})") from error
    questions: list[Question] = []
    seen: set[str] = set()
    for number, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        where = f"{path.name} line {number}"
        try:
            data = json.loads(line)
        except ValueError as error:
            raise QuestionFileError(f"{where}: not JSON ({error})") from error
        if not isinstance(data, dict):
            raise QuestionFileError(f"{where}: not a JSON object")
        question = _question(data, where)
        if question.id in seen:
            raise QuestionFileError(f"{where}: the id {question.id!r} is used twice")
        seen.add(question.id)
        questions.append(question)
    return tuple(questions)


def _question(data: dict[str, Any], where: str) -> Question:
    missing = [name for name in _REQUIRED if name not in data]
    if missing:
        raise QuestionFileError(f"{where}: missing {', '.join(missing)}")
    unknown = sorted(set(data) - set(_REQUIRED) - {"notes"})
    if unknown:
        raise QuestionFileError(f"{where}: unknown field(s) {', '.join(unknown)}")

    # Every value has to have the form its field stands for. One that has not would
    # load all the same and go wrong later, somewhere else: a number as an id, an
    # empty question, an anchor under a misspelt name, whose check is then never made.
    for name in _TEXTS:
        if not _is_text(data[name]):
            raise QuestionFileError(f"{where}: {name} has to be text, and not empty")
    if not _ID.fullmatch(data["id"]):
        raise QuestionFileError(
            f"{where}: the id {data['id']!r} has to be made of letters, digits, '.' and '-'"
        )
    for name in ("expect_found", "abstract_sufficient"):
        if not isinstance(data[name], bool):
            raise QuestionFileError(f"{where}: {name} has to be true or false")
    if not isinstance(data["answer_key"], dict):
        raise QuestionFileError(f"{where}: answer_key has to be an object")
    _check_answer_key(data["answer_key"], where)
    notes = data.get("notes", {})
    if not isinstance(notes, dict) or not all(isinstance(value, str) for value in notes.values()):
        raise QuestionFileError(f"{where}: notes has to be an object with text values")
    papers = data["gold_papers"]
    if not isinstance(papers, list) or not all(isinstance(each, str) for each in papers):
        raise QuestionFileError(f"{where}: gold_papers has to be a list of arXiv identifiers")

    gold = data["gold_evidence"]
    if (
        not isinstance(gold, dict)
        or gold.get("need") not in ("all", "any")
        or not isinstance(gold.get("items"), list)
        or not gold["items"]
    ):
        raise QuestionFileError(f"{where}: gold_evidence needs 'need' (all or any) and 'items'")
    unknown = sorted(set(gold) - {"need", "items"})
    if unknown:
        raise QuestionFileError(f"{where}: unknown field(s) in gold_evidence: {', '.join(unknown)}")
    evidence = [_evidence(item, where) for item in gold["items"]]

    for arxiv_id in (*papers, *(item.arxiv_id for item in evidence)):
        # With a version: another version of a paper may be cut into other sections.
        try:
            versioned = parse_arxiv_id(arxiv_id).version is not None
        except SourceError as error:
            raise QuestionFileError(f"{where}: {arxiv_id!r} is not an arXiv identifier") from error
        if not versioned:
            raise QuestionFileError(f"{where}: {arxiv_id!r} has no version")
    outside = sorted({item.arxiv_id for item in evidence} - set(papers))
    if outside:
        raise QuestionFileError(f"{where}: evidence in {outside}, which gold_papers does not list")

    return Question(
        id=data["id"],
        question=data["question"],
        type=data["type"],
        gold_papers=tuple(papers),
        need=gold["need"],
        evidence=tuple(evidence),
        expect_found=data["expect_found"],
        reference_answer=data["reference_answer"],
        answer_key=data["answer_key"],
        accept_note=data["accept_note"],
        abstract_sufficient=data["abstract_sufficient"],
        notes=dict(notes),
    )


def _evidence(item: Any, where: str) -> Evidence:
    if not isinstance(item, dict) or not {"arxiv_id", "section_id"} <= set(item):
        raise QuestionFileError(f"{where}: an evidence item needs arxiv_id and section_id")
    unknown = sorted(set(item) - set(_EVIDENCE_FIELDS))
    if unknown:
        raise QuestionFileError(
            f"{where}: unknown field(s) in an evidence item: {', '.join(unknown)}"
        )
    for name, value in item.items():  # an anchor that is given has to say something, too
        if not _is_text(value):
            raise QuestionFileError(
                f"{where}: {name} of an evidence item has to be text, and not empty"
            )
    return Evidence(item["arxiv_id"], item["section_id"], item.get("anchor"))


def _is_text(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _check_answer_key(key: dict[str, Any], where: str) -> None:
    """Refuse an answer key that a grader could not use, or would use for something else.

    A part under a misspelt name would never be looked at, and every answer would pass
    it. A value of the wrong kind would stop the grader at the first run it grades, long
    after the runs were paid for.
    """
    unknown = sorted(set(key) - set(_KEY_PARTS) - {"by_hand"})
    if unknown:
        raise QuestionFileError(f"{where}: unknown part(s) of answer_key: {', '.join(unknown)}")
    for part in (*_KEY_PARTS, "by_hand"):
        if not isinstance(key.get(part, []), list):
            raise QuestionFileError(f"{where}: {part} of answer_key has to be a list")
    if not all(_is_text(item) for item in key.get("by_hand", [])):
        raise QuestionFileError(f"{where}: by_hand of answer_key has to hold text, and not empty")

    for part, fields in _KEY_PARTS.items():
        for item in key.get(part, []):
            what = f"{where}: an item of {part}"
            if not isinstance(item, dict) or not set(fields[:2]) <= set(item):
                raise QuestionFileError(f"{what} needs {fields[0]} and {fields[1]}")
            unknown = sorted(set(item) - set(fields))
            if unknown:
                raise QuestionFileError(f"{what} has unknown field(s): {', '.join(unknown)}")
            if not _is_text(item["label"]):
                raise QuestionFileError(f"{what} has a label that is not text, or is empty")
            if part == "phrases":
                wordings = item["any_of"]
                if (
                    not isinstance(wordings, list)
                    or not wordings
                    or not all(map(_is_text, wordings))
                ):
                    raise QuestionFileError(
                        f"{what} ({item['label']}): any_of has to be a list of wordings, none empty"
                    )
                continue
            value = item["value"]
            # True and False are numbers to Python, and 1e999 is one to a JSON reader.
            if (
                isinstance(value, bool)
                or not isinstance(value, int | float)
                or not math.isfinite(value)
            ):
                raise QuestionFileError(f"{what} ({item['label']}): value has to be a number")
            if "unit" in item and not _is_text(item["unit"]):
                raise QuestionFileError(f"{what} ({item['label']}): unit has to be text")
            least = item.get("min_sig_figs")
            if least is not None and (
                isinstance(least, bool) or not isinstance(least, int) or least < 1
            ):
                raise QuestionFileError(
                    f"{what} ({item['label']}): min_sig_figs has to be a whole number, 1 or more"
                )


def problems_with_evidence(question: Question, papers: Mapping[str, Paper]) -> list[str]:
    """What is wrong with a question's evidence, given the parsed papers it names.

    Empty when every paper is there, has the section, and the section holds the
    anchor. Papers are looked up by their identifier with version.
    """
    problems = []
    for item in question.evidence:
        paper = papers.get(item.arxiv_id)
        if paper is None:
            problems.append(f"{question.id}: {item.arxiv_id} is not among the papers given")
            continue
        section = next((s for s in paper.sections if s.section_id == item.section_id), None)
        if section is None:
            problems.append(f"{question.id}: {item.arxiv_id} has no section {item.section_id!r}")
        elif item.anchor is not None and item.anchor not in section.text:
            problems.append(
                f"{question.id}: section {item.section_id} of {item.arxiv_id} "
                f"does not contain {item.anchor!r}"
            )
    return problems
