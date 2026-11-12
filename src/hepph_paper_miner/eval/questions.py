"""Questions with reference answers, one JSON object per line.

A question names where its answer stands: papers (identifiers with a version) and
sections in them. Section identifiers are made by the parser, so a change to the
parser can leave a question pointing at nothing. `problems_with_evidence` finds that.

The fields of one line:

    id                   a name for the question, unique in its file
    question             what the model is asked, in English
    type                 what the question is meant to test, in a word or two
    gold_papers          the papers that hold the answer
    gold_evidence        where in them: {"need": "all" or "any", "items": [...]}, each
                         item {"arxiv_id", "section_id", "anchor"}. The anchor is a
                         short piece of the section's text, exactly as it stands
                         there, that marks the place of the fact. It may be left out.
    expect_found         false when the right answer is "the papers do not say"
    reference_answer     the answer a grader compares with
    answer_key           what a rule can check (numbers, phrases); a grader's business
    accept_note          what counts as correct, in the question writer's words
    abstract_sufficient  true when the abstract alone answers the question
    notes                anything else worth keeping, by topic

Positions are not written into the file. They follow from the anchor and the parsed
paper, so they cannot go stale when the way a long section is cut changes.
"""

from __future__ import annotations

import json
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
    questions: list[Question] = []
    seen: set[str] = set()
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
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

    gold = data["gold_evidence"]
    if (
        not isinstance(gold, dict)
        or gold.get("need") not in ("all", "any")
        or not gold.get("items")
    ):
        raise QuestionFileError(f"{where}: gold_evidence needs 'need' (all or any) and 'items'")
    evidence = []
    for item in gold["items"]:
        if not isinstance(item, dict) or not {"arxiv_id", "section_id"} <= set(item):
            raise QuestionFileError(f"{where}: an evidence item needs arxiv_id and section_id")
        evidence.append(Evidence(item["arxiv_id"], item["section_id"], item.get("anchor")))

    papers = tuple(data["gold_papers"])
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
    for name in ("expect_found", "abstract_sufficient"):
        if not isinstance(data[name], bool):
            raise QuestionFileError(f"{where}: {name} has to be true or false")

    return Question(
        id=data["id"],
        question=data["question"],
        type=data["type"],
        gold_papers=papers,
        need=gold["need"],
        evidence=tuple(evidence),
        expect_found=data["expect_found"],
        reference_answer=data["reference_answer"],
        answer_key=data["answer_key"],
        accept_note=data["accept_note"],
        abstract_sufficient=data["abstract_sufficient"],
        notes=dict(data.get("notes", {})),
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
