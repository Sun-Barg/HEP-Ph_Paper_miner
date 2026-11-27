"""The answers of the second evaluation that a person grades, and the verdict on each.

    uv run python -m hepph_paper_miner.eval.hand --questions eval_data/questions_archives.jsonl \
        --runs results/runs/archives --sheet runs_private/archives/answers.csv \
        --key runs_private/archives/answers-key.csv --judge runs_private/archives/judge.jsonl \
        --hand-sheet runs_private/archives/hand.csv --hand-key runs_private/archives/hand-key.csv

In the first evaluation a person graded every answer. The second has one run for a cell
and up to 160 answers, which follow the review of every question by the same person. So
an answer of it can have three grades (eval_data/PREREGISTRATION_2.md, Section 12):

    the rule     what grade.py says of it from the answer key
    the judge    the verdict of judge.py on its row of the sheet of all answers (sheet.py):
                 the one that two or three of its three requests gave
    by hand      the grade a person writes on a sheet of the answers picked for it

Picked are (a) every answer on which the rule and the judge differ, (b) every answer that
the judge calls wrong or has no verdict on, and (c) forty of the others, or all of them
where they are fewer: those with the smallest SHA-256 of "20261124:<question>:<layout>".
The others are the answers that the rule and the judge both call right. Nobody chooses
among them, and (c) says how far the two can be trusted where they agree.

The verdict on an answer is the grade by hand where there is one, and the verdict of the
judge otherwise. A run without an answer is wrong, and is on no sheet. If the grade by
hand differs from the verdict of the judge in three or more of the answers of (c), every
answer is graded by hand, and the grades by hand are the verdicts.

The command is run twice. First it writes the sheet of the picked answers and its key.
The sheet shows what the sheet of all answers shows of them, under the same numbers and
in the same order: the answer and its "found", and for each question its text, its
reference answer and its note. It does not show the layout, the run, what the rule or the
judge said, or why a row is on it. The key says those, and stays closed until every row
is graded. Then, with --rest-sheet and --rest-key, the command reads the graded sheet,
says in how many answers of (c) the grade by hand is not the judge's verdict, and writes
the sheet of the answers that are left when that count calls for it.

The files are held to each other, and one that does not fit is refused: the key has to be
the key of the runs that count, the sheet has to hold their answers as the records hold
them, and the record of the judge has to be a whole pass of the judge this code holds
over that very sheet. So the sheet of all answers is not opened and saved by a
spreadsheet: the sheet to grade is the one this command writes.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from hepph_paper_miner.agent.origin import file_digest
from hepph_paper_miner.eval import judge as judging
from hepph_paper_miner.eval.agree import AgreeError, judged
from hepph_paper_miner.eval.grade import RIGHT, Record, grade_answer
from hepph_paper_miner.eval.judge import JudgeError
from hepph_paper_miner.eval.questions import Question, QuestionFileError, load_questions
from hepph_paper_miner.eval.run import Attempt, State
from hepph_paper_miner.eval.sheet import (
    KEY_COLUMNS,
    HandGrade,
    Row,
    SheetError,
    _cell,
    counted_attempts,
    read_grades,
    read_key,
    write_sheet,
)

# The seed of the survey's plan (eval_data/survey_plan.json). The pre-registration writes
# it out in the key of the order, so it stands here as a number, and a test holds the two
# and the plan to each other.
SEED = 20261124
SAMPLE = 40  # (c): this many of the answers that the rule and the judge both call right
WIDEN_AT = 3  # this many grades of (c) against the judge, and every answer is graded by hand
REPEATS = 1  # one run for a cell, so that a question and a layout name one answer

# Why an answer is graded by hand, as the key of its sheet says it.
DIFFER = "a"  # the rule and the judge differ
DOUBTED = "b"  # the judge calls it wrong, or has no verdict on it
SAMPLED = "c"  # drawn from the answers that are neither
REST = "rest"  # left over, and graded because (c) went against the judge

NO_VERDICT = "none"  # what a key says of the judge where it has no verdict
HAND_KEY_COLUMNS = (*KEY_COLUMNS, "picked", "rule", "judge")


class HandError(ValueError):
    """Files that do not fit each other, or a sheet that is not graded yet. The message says."""


@dataclass(frozen=True)
class Answer:
    """One answer of the sheet of all answers, with what the rule and the judge said of it."""

    number: int  # its number on that sheet, and on every sheet made of it
    question: Question
    attempt: Attempt
    rule: str  # RIGHT, WRONG or BY_HAND of grade.py
    judge: str | None  # right or wrong; None when the judge has no verdict on it

    @property
    def layout(self) -> str:
        return self.attempt.run["toolset"]

    @property
    def run_id(self) -> str:
        return self.attempt.run["run_id"]


# --- which answers are graded by hand -------------------------------------------------------


def order_key(question_id: str, layout: str, seed: int = SEED) -> str:
    """What the answers that are drawn are sorted by: nothing of a run goes into it."""
    return hashlib.sha256(f"{seed}:{question_id}:{layout}".encode()).hexdigest()


def picked(answers: Sequence[Answer], sample: int = SAMPLE) -> dict[int, str]:
    """Why each answer that is graded by hand is graded by hand, by its number.

    An answer on which the judge has no verdict is (b) and not (a): there is nothing for
    the rule to differ from. An answer of (a) or (b) is not drawn for (c), so the answers
    of (c) are ones that the rule and the judge both call right.
    """
    found: dict[int, str] = {}
    for answer in answers:
        why = []
        if answer.judge is not None and answer.rule != answer.judge:
            why.append(DIFFER)
        if answer.judge != RIGHT:
            why.append(DOUBTED)
        if why:
            found[answer.number] = " ".join(why)
    others = sorted(
        (answer for answer in answers if answer.number not in found),
        key=lambda answer: order_key(answer.question.id, answer.layout),
    )
    for answer in others[:sample]:
        found[answer.number] = SAMPLED
    return found


# --- reading what the runs, the sheet and the judge hold ------------------------------------


def verdicts_of_the_judge(
    record: Path, questions: Path, sheet: Path, answers: int
) -> dict[str, str | None]:
    """The verdict of the judge on every row of the sheet, by the name the judge gives a row.

    Refused unless the record is a whole pass, with three requests for an answer, of the
    judge this code holds, over this question file and this sheet as it lies.
    """
    head, lines, end = judging.read_record(record)
    of_sheet = head.get("sheet") or {}
    version = (head.get("judge_version"), head.get("texts_sha256"))
    wrong = [
        text
        for is_wrong, text in (
            (
                version != (judging.JUDGE_VERSION, judging.texts_digest()),
                f"it is of the judge {version[0]!r}, not of {judging.JUDGE_VERSION!r} as it is now",
            ),
            (
                head.get("repeats") != judging.REPEATS,
                f"it asked every answer {head.get('repeats')} time(s), not {judging.REPEATS}",
            ),
            (end is None, "it has no last line, so not every request has its reply"),
            (head.get("only") is not None, "it asked only some of the answers"),
            (
                (head.get("questions") or {}).get("sha256") != file_digest(questions),
                "it was begun with another question file",
            ),
            (
                of_sheet.get("sha256") != file_digest(sheet),
                (
                    f"it was begun with another sheet than {sheet.name}, or with this one "
                    "before it was changed"
                ),
            ),
            (of_sheet.get("answers") != answers, f"its sheet did not have {answers} answers"),
        )
        if is_wrong
    ]
    if wrong:
        raise HandError(f"{record.name}: " + "; ".join(wrong))
    try:
        said = judged(lines, head["repeats"])
    except AgreeError as error:
        raise HandError(f"{record.name}: {error}") from error
    return {name: one.verdict for name, one in said.items()}


def read_answers(
    questions_file: Path, runs: Path, sheet: Path, key: Path, record: Path
) -> tuple[list[Answer], list[Attempt], State]:
    """Every answer of the sheet with its two grades, in the order of the sheet; and the
    runs that count with the state of the plan, for the report.

    Raises HandError, SheetError, JudgeError, QuestionFileError or OSError when the files
    cannot be read or are not of each other.
    """
    questions = load_questions(questions_file)
    by_id = {question.id: question for question in questions}
    attempts, state = counted_attempts(questions, runs, file_digest(questions_file), REPEATS)
    waiting = [cell for cell in state.cells if state.to_run(cell)]
    if waiting:
        raise HandError(
            f"{len(waiting)} cell(s) of the plan are still to run (first: {waiting[0]}); "
            "finish the runs first"
        )
    answered = {a.run["run_id"]: a for a in attempts if a.end.get("answer")}
    lines = read_key(key)
    if sorted(line["run_id"] for line in lines.values()) != sorted(answered):
        raise HandError(f"{key.name} is not the key of the runs that count and gave an answer")
    shown = {item.id: item for item in judging.sheet_items(sheet)}
    if set(shown) != {f"sheet-{number}" for number in lines}:
        raise HandError(f"{sheet.name} does not have the rows of {key.name}")
    for number, line in lines.items():
        item, answer = shown[f"sheet-{number}"], answered[line["run_id"]].end["answer"]
        # The judge was given these cells. Held against the records, they are the answers
        # of the runs, and the grades of the rule and of the judge are of the same text.
        if (item.question_id, item.found, item.answer) != (
            line["question_id"],
            answer["found"],
            _cell(answer["answer"]),
        ):
            raise HandError(f"{sheet.name} number {number}: not the answer of {line['run_id']}")
    said = verdicts_of_the_judge(record, questions_file, sheet, len(lines))
    answers = []
    for number in sorted(lines):
        attempt = answered[lines[number]["run_id"]]
        if f"sheet-{number}" not in said:
            raise HandError(f"{record.name}: no verdict on number {number} of the sheet")
        question = by_id[attempt.run["question_id"]]
        rule = grade_answer(Record(attempt.run, attempt.turns, attempt.end), question).rule
        answers.append(Answer(number, question, attempt, rule, said[f"sheet-{number}"]))
    cells = [(answer.question.id, answer.layout) for answer in answers]
    if len(set(cells)) != len(cells):
        # counted_attempts holds the runs to a plan of one repetition, so this cannot be.
        raise HandError("a question and a layout have two answers, so they name no answer")
    return answers, attempts, state


# --- the sheets -----------------------------------------------------------------------------


def write_hand(answers: Sequence[Answer], why: Mapping[int, str], sheet: Path, key: Path) -> None:
    """A sheet of some of the answers, and its key.

    The rows keep their numbers and their order, and the first row of a question shows the
    question: what sheet.py writes for these rows alone. The key is the key of that sheet
    with three more columns, which the sheet must not show.
    """
    for path in (sheet, key):
        path.parent.mkdir(parents=True, exist_ok=True)
    with key.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(HAND_KEY_COLUMNS)
        for answer in answers:
            run = answer.attempt.run
            writer.writerow(
                [
                    answer.number,
                    answer.question.id,
                    run["run_id"],
                    run["toolset"],
                    run["repeat"],
                    answer.attempt.path.name,
                    why[answer.number],
                    answer.rule,
                    answer.judge or NO_VERDICT,
                ]
            )
    write_sheet([Row(answer.number, answer.question, answer.attempt) for answer in answers], sheet)


def read_hand(
    sheet: Path, key: Path, wanted: Sequence[Answer], why: Mapping[int, str]
) -> dict[int, HandGrade]:
    """The grades of a sheet that write_hand wrote, by number; a grade is None until given.

    Refused unless the sheet is the sheet of `wanted`: a sheet that was made from another
    record of the judge holds other answers, and its grades would stand for another pick.
    """
    grades = {grade.number: grade for grade in read_grades(sheet, key)}
    lines = read_key(key)
    expected = {answer.number: answer for answer in wanted}
    if set(grades) != set(expected):
        raise HandError(
            f"{key.name} is not the key of the {len(expected)} answer(s) that the runs and "
            "the judge put on this sheet"
        )
    for number, answer in expected.items():
        line = lines[number]
        said = (grades[number].run_id, line.get("picked"), line.get("rule"), line.get("judge"))
        if said != (answer.run_id, why[number], answer.rule, answer.judge or NO_VERDICT):
            raise HandError(
                f"{key.name} number {number}: not what the runs and the judge say of that answer"
            )
    return grades


# --- the verdicts ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Graded:
    """An answer with every grade it has."""

    answer: Answer
    picked: str | None  # why it is graded by hand; None when it is not
    hand: str | None  # the grade by hand, right or wrong; None when it has none

    @property
    def verdict(self) -> str | None:
        """The grade by hand where there is one, and the verdict of the judge otherwise."""
        return self.hand if self.hand is not None else self.answer.judge


@dataclass(frozen=True)
class Grading:
    graded: tuple[Graded, ...]  # every answer of the sheet, in its order
    sampled: int  # the answers of (c)
    differing: int  # of them, those whose grade by hand is not the verdict of the judge

    @property
    def widened(self) -> bool:
        """Whether every answer is graded by hand, and the grades by hand are the verdicts."""
        return self.differing >= WIDEN_AT

    def verdicts(self) -> dict[str, str | None]:
        """The verdict on every answer, by the run that gave it."""
        return {one.answer.run_id: one.verdict for one in self.graded}


def against_the_judge(
    answers: Sequence[Answer], why: Mapping[int, str], first: Mapping[int, HandGrade]
) -> tuple[int, int]:
    """How many answers were drawn for (c), and in how many the grade by hand is not the
    verdict of the judge. Every row of the first sheet has to be graded."""
    open_ = sorted(number for number, grade in first.items() if grade.grade is None)
    if open_:
        raise HandError(f"{len(open_)} row(s) are not graded yet (the first: number {open_[0]})")
    drawn = [answer for answer in answers if why.get(answer.number) == SAMPLED]
    return len(drawn), sum(1 for answer in drawn if first[answer.number].grade != answer.judge)


def grading(
    answers: Sequence[Answer],
    why: Mapping[int, str],
    first: Mapping[int, HandGrade],
    rest: Mapping[int, HandGrade] | None,
) -> Grading:
    """Every answer with its grades, once the grading by hand is done.

    `rest` is the sheet of the answers that are left, which there is when (c) went against
    the judge and only then. Raises HandError while a grade is missing, and when a sheet
    of the answers that are left is given although the rule does not ask for it: its grades
    would be verdicts that the rule does not make.
    """
    sampled, differing = against_the_judge(answers, why, first)
    left = [answer for answer in answers if answer.number not in why]
    said = (
        f"the grade by hand differs from the verdict of the judge in {differing} of the "
        f"{sampled} answer(s) of (c)"
    )
    hand = {number: grade.grade for number, grade in first.items()}
    reasons = dict(why)
    if differing >= WIDEN_AT and left:
        if rest is None:
            raise HandError(
                f"{said}: every answer is graded by hand, and the sheet of the {len(left)} "
                "that are left is not given (--rest-sheet, --rest-key)"
            )
        open_ = sorted(number for number, grade in rest.items() if grade.grade is None)
        if open_:
            raise HandError(
                f"{len(open_)} row(s) of the answers that are left are not graded yet "
                f"(the first: number {open_[0]})"
            )
        hand |= {number: grade.grade for number, grade in rest.items()}
        reasons |= {answer.number: REST for answer in left}
    elif rest is not None:
        raise HandError(
            f"{said}, and the rule asks for a sheet of the answers that are left from "
            f"{WIDEN_AT} on, where any are left: its grades are no part of the verdicts"
        )
    return Grading(
        tuple(
            Graded(answer, reasons.get(answer.number), hand.get(answer.number))
            for answer in answers
        ),
        sampled,
        differing,
    )


def read_grading(
    questions: Path,
    runs: Path,
    sheet: Path,
    key: Path,
    record: Path,
    hand_sheet: Path,
    hand_key: Path,
    rest_sheet: Path | None = None,
    rest_key: Path | None = None,
) -> tuple[Grading, list[Attempt], State]:
    """The verdicts, from the files they are made of; and the runs that count with the state
    of the plan. Raises as read_answers and grading do."""
    answers, attempts, state = read_answers(questions, runs, sheet, key, record)
    why = picked(answers)
    first = read_hand(hand_sheet, hand_key, [a for a in answers if a.number in why], why)
    rest = None
    if rest_sheet is not None and rest_key is not None:
        left = [answer for answer in answers if answer.number not in why]
        rest = read_hand(rest_sheet, rest_key, left, {answer.number: REST for answer in left})
    return grading(answers, why, first, rest), attempts, state


# --- the command ----------------------------------------------------------------------------


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m hepph_paper_miner.eval.hand",
        description="Write the sheet of the answers that are graded by hand; then, once it is "
        "graded, say whether the answers that are left have to be graded too.",
    )
    parser.add_argument("--questions", type=Path, required=True, help="the question file")
    parser.add_argument("--runs", type=Path, required=True, help="folder of the public records")
    parser.add_argument("--sheet", type=Path, required=True, help="the sheet of all answers")
    parser.add_argument("--key", type=Path, required=True, help="the key of that sheet")
    parser.add_argument("--judge", type=Path, required=True, help="the judge's record of it")
    parser.add_argument("--hand-sheet", type=Path, required=True, help="the sheet to grade")
    parser.add_argument("--hand-key", type=Path, required=True, help="its key")
    parser.add_argument(
        "--rest-sheet",
        type=Path,
        help="with a graded sheet: where to write the sheet of the answers that are left",
    )
    parser.add_argument("--rest-key", type=Path, help="its key")
    arguments = parser.parse_args(argv)
    if (arguments.rest_sheet is None) != (arguments.rest_key is None):
        parser.error("--rest-sheet and --rest-key go together")

    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="backslashreplace")
    after = arguments.rest_sheet is not None  # the sheet is graded, and the rest is asked about
    made = (
        (arguments.rest_sheet, arguments.rest_key)
        if after
        else (arguments.hand_sheet, arguments.hand_key)
    )
    try:
        answers, _, _ = read_answers(
            arguments.questions, arguments.runs, arguments.sheet, arguments.key, arguments.judge
        )
        why = picked(answers)
        first = [answer for answer in answers if answer.number in why]
        left = [answer for answer in answers if answer.number not in why]
        if after:
            grades = read_hand(arguments.hand_sheet, arguments.hand_key, first, why)
            sampled, differing = against_the_judge(answers, why, grades)
            print(
                f"the grade by hand differs from the verdict of the judge in {differing} of "
                f"the {sampled} answer(s) of (c)"
            )
            if differing < WIDEN_AT:
                print(
                    f"fewer than {WIDEN_AT}: the {len(left)} answer(s) that were not graded by "
                    "hand keep the verdict of the judge, and no sheet was written"
                )
                return 0
            if not left:
                print(
                    f"{WIDEN_AT} or more, and every answer is graded by hand already: no sheet "
                    "was written"
                )
                return 0
        for path in made:
            if path.exists():
                print(f"{path} is there already; move it away first", file=sys.stderr)
                return 2
        if after:
            write_hand(left, {answer.number: REST for answer in left}, *made)
            print(
                f"{WIDEN_AT} or more: every answer is graded by hand. The {len(left)} that are "
                f"left are on the sheet {arguments.rest_sheet}, with the key {arguments.rest_key}"
            )
            return 0
        write_hand(first, why, *made)
    except (OSError, QuestionFileError, SheetError, JudgeError, HandError) as error:
        print(f"refused: {error}", file=sys.stderr)
        return 1
    # How many rows are of (a), (b) and (c) is in the key and in the report, and is not
    # said here: the person who grades is not to know why a row is on the sheet.
    print(
        f"{len(first)} of the {len(answers)} answer(s) are on the sheet {arguments.hand_sheet}; "
        f"the other {len(left)} keep the verdict of the judge unless the grades of this sheet "
        "say otherwise"
    )
    print(f"the key is {arguments.hand_key}: leave it closed until every row is graded")
    print(
        "once it is graded, run the command again with --rest-sheet and --rest-key: it says "
        "whether the other answers have to be graded too"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
