"""The sheet on which a person grades the answers, without seeing which layout gave them.

    uv run python -m hepph_paper_miner.eval.sheet --questions eval_data/questions_eval.jsonl \
        --runs results/runs/eval --sheet grading.csv --key runs_private/grading-key.csv

It writes two files once the evaluation is done. The sheet has a row for every run that
counts (the first run of a cell that arXiv and the API did not spoil, see run.py) and
that handed in an answer. A run without an answer is wrong whatever it would have said,
so it is not on the sheet. The rows of a question stand together, the questions in the
order of their file, and within a question in an order drawn at random; they are
numbered down the sheet.

A row shows the answer and whether it says that the papers hold one. The first row of a
question also shows the question, its reference answer and what is accepted. Nothing
else of the run is on the sheet: not the layout, the repetition or the run, not the
sections the answer cites, and not what the rule of grade.py said. The grader writes
"right" or "wrong" under `grade`, why under `why_wrong` when it is wrong, and anything
else under `note`. There is no partial credit.

Which run a number stands for is in the key, a file of its own. It goes in runs_private/,
which is never committed, and stays closed until every row is graded. Then the graded
sheet and the key are committed together under results/: the verdicts are a part of the
results. The report (report.py) reads the two together.

The sheet is CSV in UTF-8 with a byte-order mark, so that Excel reads its letters right;
it has to be saved as "CSV UTF-8" again.
"""

from __future__ import annotations

import argparse
import csv
import random
import secrets
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from hepph_paper_miner.eval.questions import Question, QuestionFileError, load_questions
from hepph_paper_miner.eval.run import REPEATS, Attempt, State, attempts_in, counted, plan

SHEET_COLUMNS = (
    "number",
    "question_id",
    "question",
    "reference_answer",
    "accept_note",
    "found",
    "answer",
    "grade",
    "why_wrong",
    "note",
)
KEY_COLUMNS = ("number", "question_id", "run_id", "toolset", "repeat", "record")
GRADES = ("right", "wrong")


class SheetError(ValueError):
    """A sheet or a key that cannot be used as it is. The message says where."""


@dataclass(frozen=True)
class Row:
    number: int
    question: Question
    attempt: Attempt


@dataclass(frozen=True)
class HandGrade:
    number: int
    question_id: str
    run_id: str
    toolset: str
    repeat: int
    grade: str | None  # "right" or "wrong"; None while the row is not graded
    why_wrong: str
    note: str


def rows_of(questions: Sequence[Question], attempts: Sequence[Attempt], seed: int) -> list[Row]:
    """The rows of the sheet: question by question, in an order drawn within each."""
    draw = random.Random(seed)
    rows: list[Row] = []
    for question in questions:
        answered = sorted(
            (
                attempt
                for attempt in attempts
                if attempt.run.get("question_id") == question.id
                and (attempt.end or {}).get("answer")
            ),
            key=lambda attempt: attempt.run["run_id"],
        )
        draw.shuffle(answered)
        for attempt in answered:
            rows.append(Row(len(rows) + 1, question, attempt))
    return rows


def _cell(text: str) -> str:
    """Text as a spreadsheet shows it: one that begins like a formula is kept as text."""
    return " " + text if text[:1] in ("=", "+", "-", "@", "\t", "\r") else text


def write_sheet(rows: Sequence[Row], path: Path) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(SHEET_COLUMNS)
        shown: set[str] = set()
        for row in rows:
            question, answer = row.question, row.attempt.end["answer"]
            first = question.id not in shown
            shown.add(question.id)
            writer.writerow(
                [
                    row.number,
                    question.id,
                    _cell(question.question) if first else "",
                    _cell(question.reference_answer) if first else "",
                    _cell(question.accept_note) if first else "",
                    "true" if answer["found"] else "false",
                    _cell(answer["answer"]),
                    "",
                    "",
                    "",
                ]
            )


def write_key(rows: Sequence[Row], path: Path) -> None:
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(KEY_COLUMNS)
        for row in rows:
            run = row.attempt.run
            writer.writerow(
                [
                    row.number,
                    row.question.id,
                    run["run_id"],
                    run["toolset"],
                    run["repeat"],
                    row.attempt.path.name,
                ]
            )


def _read_csv(path: Path, what: str) -> list[dict[str, str]]:
    try:
        with path.open(encoding="utf-8-sig", newline="") as stream:
            return list(csv.DictReader(stream))
    except UnicodeDecodeError as error:
        raise SheetError(
            f'{path.name}: the {what} is not UTF-8 text; save it as "CSV UTF-8" ({error})'
        ) from error


def read_key(path: Path) -> dict[int, dict[str, str]]:
    found: dict[int, dict[str, str]] = {}
    for line in _read_csv(path, "key"):
        number = int(line["number"])
        found[number] = line
    return found


def read_grades(sheet: Path, key: Path) -> list[HandGrade]:
    """The grades of a sheet, each with the run it is of, in the order of the numbers.

    Refused as a whole when a row cannot be matched to the key: a grade put next to the
    wrong run would be counted for the wrong layout without anyone seeing it.
    """
    runs = read_key(key)
    lines = _read_csv(sheet, "sheet")
    if lines and not {"number", "question_id", "grade", "why_wrong", "note"} <= set(lines[0]):
        raise SheetError(f"{sheet.name}: the columns number, question_id, grade, why_wrong, note")
    grades: dict[int, HandGrade] = {}
    for at, line in enumerate(lines, start=2):  # the first line of the file is the header
        values = {name: (value or "").strip() for name, value in line.items() if name}
        if not any(values.values()):
            continue  # an empty line that a spreadsheet left
        where = f"{sheet.name} line {at}"
        try:
            number = int(values.get("number", ""))
        except ValueError:
            raise SheetError(f"{where}: number {values.get('number')!r} is not a number") from None
        if number in grades:
            raise SheetError(f"{where}: number {number} is there twice")
        run = runs.get(number)
        if run is None:
            raise SheetError(f"{where}: number {number} is not in the key {key.name}")
        if values.get("question_id") != run["question_id"]:
            raise SheetError(
                f"{where}: number {number} is of {run['question_id']} in the key, "
                f"not of {values.get('question_id')!r}"
            )
        grade = values.get("grade", "").casefold() or None
        if grade is not None and grade not in GRADES:
            raise SheetError(f"{where}: grade {values['grade']!r} is neither right nor wrong")
        grades[number] = HandGrade(
            number,
            run["question_id"],
            run["run_id"],
            run["toolset"],
            int(run["repeat"]),
            grade,
            values.get("why_wrong", ""),
            values.get("note", ""),
        )
    missing = sorted(set(runs) - set(grades))
    if missing:
        shown = ", ".join(str(number) for number in missing[:10])
        raise SheetError(f"{sheet.name}: no row for number(s) {shown} of the key")
    return [grades[number] for number in sorted(grades)]


def counted_attempts(
    questions: Sequence[Question], folder: Path, digest: str, repeats: int = REPEATS
) -> tuple[list[Attempt], State]:
    """The runs that count, refusing a folder that is not the evaluation of this file."""
    attempts = attempts_in(folder)
    ids = {question.id for question in questions}
    for tried in attempts.values():
        for attempt in tried:
            named = (attempt.run.get("questions") or {}).get("sha256")
            if named != digest:
                raise SheetError(f"{attempt.path.name}: a run of another question file")
            if attempt.run.get("question_id") not in ids:
                raise SheetError(f"{attempt.path.name}: its question is not in the file")
    state = State(plan([question.id for question in questions], repeats), attempts)
    outside = sorted(set(attempts) - set(state.cells))
    if outside:
        raise SheetError(f"a run of {outside[0]} is outside the plan of {repeats} repetition(s)")
    found = counted(attempts)
    return [found[cell] for cell in state.cells if cell in found], state


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m hepph_paper_miner.eval.sheet",
        description="Write the sheet for grading the answers by hand, and its key.",
    )
    parser.add_argument("--questions", type=Path, required=True, help="the question file")
    parser.add_argument("--runs", type=Path, required=True, help="folder of the public records")
    parser.add_argument("--sheet", type=Path, required=True, help="the sheet to write (CSV)")
    parser.add_argument("--key", type=Path, required=True, help="the key to write (CSV)")
    parser.add_argument(
        "--repeats",
        type=int,
        default=REPEATS,
        help="repetitions of the plan (default: %(default)s)",
    )
    parser.add_argument("--seed", type=int, help="seed of the order within a question (tests)")
    arguments = parser.parse_args(argv)

    from hepph_paper_miner.agent.origin import file_digest

    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="backslashreplace")
    try:
        questions = load_questions(arguments.questions)
    except (OSError, QuestionFileError) as error:
        print(f"cannot read the questions: {error}", file=sys.stderr)
        return 2
    for path in (arguments.sheet, arguments.key):
        if path.exists():
            print(f"{path} is there already; move it away first", file=sys.stderr)
            return 2
    digest = file_digest(arguments.questions)
    try:
        attempts, state = counted_attempts(questions, arguments.runs, digest, arguments.repeats)
    except SheetError as error:
        print(f"refused: {error}", file=sys.stderr)
        return 1
    waiting = [cell for cell in state.cells if state.to_run(cell)]
    if waiting:
        print(
            f"refused: {len(waiting)} cell(s) of the plan are still to run "
            f"(first: {waiting[0]}); finish the evaluation first",
            file=sys.stderr,
        )
        return 1
    seed = arguments.seed if arguments.seed is not None else secrets.randbits(64)
    rows = rows_of(questions, attempts, seed)
    arguments.key.parent.mkdir(parents=True, exist_ok=True)
    write_key(rows, arguments.key)
    write_sheet(rows, arguments.sheet)
    unanswered = len(attempts) - len(rows)
    print(
        f"{len(rows)} answer(s) on the sheet {arguments.sheet}, from {len(attempts)} run(s) "
        f"that count ({unanswered} without an answer are wrong and not on it)"
    )
    print(f"the key is {arguments.key}: leave it closed until every row is graded")
    return 0


if __name__ == "__main__":
    sys.exit(main())
