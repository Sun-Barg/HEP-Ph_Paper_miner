"""Check a question file against the papers it names, before a run is paid for.

    uv run python -m hepph_paper_miner.eval.check eval_data/questions_dev.jsonl

Reading the file already refuses a line of the wrong form (questions.py). This goes
on to the papers: every piece of evidence has to name a section the parser made, and
its anchor has to stand in that section. For each piece it says where the place is and
how many calls of read_section it takes, from the start of the section, until the
place has been given whole. It ends with counts over the file, to hold against the mix
of questions that was planned.

The papers are read through the folder of downloads, and arXiv is asked for one that is
not in it. Nothing of a paper is printed: places, sizes and counts only.
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from hepph_paper_miner.eval.questions import (
    Question,
    QuestionFileError,
    load_questions,
    problems_with_evidence,
)
from hepph_paper_miner.server import piece_ends
from hepph_paper_miner.sources.base import Paper, PaperSource, SourceError, parse_arxiv_id


@dataclass(frozen=True)
class Looked:
    """What was found out about one question."""

    question: Question
    lines: tuple[str, ...]  # one for each piece of evidence that is where the question says
    problems: tuple[str, ...]
    to_find: tuple[str, ...]  # papers that the question does not name by identifier
    calls: int | None  # the most calls any of its places takes; None when a place is missing


def look_at(question: Question, papers: Mapping[str, Paper]) -> Looked:
    """Where the evidence of a question stands in the parsed papers."""
    lines, most = [], 0
    for item in question.evidence:
        paper = papers.get(item.arxiv_id)
        sections = {section.section_id: section for section in paper.sections} if paper else {}
        section = sections.get(item.section_id)
        if section is None:
            continue  # problems_with_evidence says so
        text = section.text
        ends = piece_ends(text)
        if item.anchor is None:
            start, stop, note = 0, len(text), " | no anchor: all of the section has to be given"
        else:
            start = text.find(item.anchor)
            if start == -1:
                continue
            stop = start + len(item.anchor)
            # Counted the way the grader looks for them, so "aa" stands twice in "aaa".
            times = sum(1 for at in range(len(text)) if text.startswith(item.anchor, at))
            note = "" if times == 1 else f" | the anchor stands {times} times (the first is shown)"
        calls = next(number for number, end in enumerate(ends, start=1) if end >= stop)
        most = max(most, calls)
        lines.append(
            f"   {item.arxiv_id} {item.section_id} | chars {start}-{stop} of {len(text)} "
            f"| given by call {calls} of {len(ends)}{note}"
        )
    problems = problems_with_evidence(question, papers)
    # Named with or without its version, or with "arXiv:" in front: the digits are there.
    to_find = tuple(
        key for key in question.gold_papers if parse_arxiv_id(key).base not in question.question
    )
    complete = len(lines) == len(question.evidence)
    return Looked(question, tuple(lines), tuple(problems), to_find, most if complete else None)


def head_of(looked: Looked) -> str:
    question = looked.question
    parts = [
        question.id,
        question.type,
        "an answer is expected" if question.expect_found else "'not in the papers' is expected",
    ]
    if looked.to_find:
        parts.append(f"to be found by a search: {', '.join(looked.to_find)}")
    if question.abstract_sufficient:
        parts.append("the abstract is enough")
    return " | ".join(parts)


def summary(all_looked: Sequence[Looked]) -> list[str]:
    """Counts over the file. They say what is there, not what should be."""
    questions = [looked.question for looked in all_looked]
    places = [{(item.arxiv_id, item.section_id) for item in q.evidence} for q in questions]
    one = sum(1 for where in places if len(where) == 1)
    all_needed = sum(1 for q, where in zip(questions, places) if len(where) > 1 and q.need == "all")
    any_enough = sum(1 for q, where in zip(questions, places) if len(where) > 1 and q.need == "any")
    by_type = Counter(question.type for question in questions)
    by_paper = Counter(key for question in questions for key in question.gold_papers)
    return [
        f"{len(questions)} question(s), about {len(by_paper)} paper(s)",
        f"   an answer expected: {sum(1 for q in questions if q.expect_found)}"
        f" | 'not in the papers' expected: {sum(1 for q in questions if not q.expect_found)}",
        f"   evidence in one section: {one} | in several, all needed: {all_needed}"
        f" | in several, any is enough: {any_enough}",
        f"   with a paper to be found by a search: {sum(1 for x in all_looked if x.to_find)}",
        "   with a place that the first call of read_section does not give: "
        f"{sum(1 for x in all_looked if (x.calls or 0) > 1)}",
        f"   with an abstract that is enough: {sum(1 for q in questions if q.abstract_sufficient)}",
        f"   by type: {_counted(by_type)}",
        f"   by paper: {_counted(by_paper)}",
    ]


def _counted(counts: Counter) -> str:
    return ", ".join(f"{name} {number}" for name, number in counts.most_common())


def main(argv: Sequence[str] | None = None, source: PaperSource | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m hepph_paper_miner.eval.check",
        description="Check a question file against the papers it names.",
    )
    parser.add_argument("questions", type=Path, help="the question file")
    arguments = parser.parse_args(argv)

    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="backslashreplace")
    try:
        questions = load_questions(arguments.questions)
    except (OSError, QuestionFileError) as error:
        print(f"cannot read the questions: {error}", file=sys.stderr)
        return 2
    if not questions:
        print(f"{arguments.questions.name}: no question in it", file=sys.stderr)
        return 2
    if source is None:
        source = _arxiv()

    papers: dict[str, Paper] = {}
    for key in dict.fromkeys(key for question in questions for key in question.gold_papers):
        try:
            papers[key] = source.paper(parse_arxiv_id(key))
        except SourceError as error:
            print(f"cannot read {key}: {error}", file=sys.stderr)

    all_looked = [look_at(question, papers) for question in questions]
    for looked in all_looked:
        print(head_of(looked))
        for line in looked.lines:
            print(line)
        for problem in looked.problems:
            print(f"   ! {problem}")
    print()
    for line in summary(all_looked):
        print(line)
    wrong = sum(1 for looked in all_looked if looked.problems)
    print(f"{wrong} question(s) with a problem" if wrong else "no problem found")
    return 1 if wrong else 0


def _arxiv() -> PaperSource:
    """The papers as a run reads them: from arXiv, through the folder of downloads."""
    from hepph_paper_miner import __version__
    from hepph_paper_miner.http import Fetcher, default_cache_dir
    from hepph_paper_miner.server import SERVER_NAME
    from hepph_paper_miner.sources.arxiv import ArxivSource

    return ArxivSource(Fetcher(default_cache_dir(), user_agent=f"{SERVER_NAME}/{__version__}"))


if __name__ == "__main__":
    sys.exit(main())
