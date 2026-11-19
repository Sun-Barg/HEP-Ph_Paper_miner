"""The judge held against the grades by hand: where the two part, and what the controls show.

    uv run python -m hepph_paper_miner.eval.agree --questions eval_data/questions_eval.jsonl \
        --record results/judge/eval-j2.jsonl --sheet results/grading.csv \
        --key results/grading-key.csv --controls eval_data/judge_controls_eval.csv \
        --runs results/runs/eval --out results/judge/report.md

The verdict on an answer is the grade a person gave it (sheet.py), and nothing here
changes that. The record of a judge (judge.py) holds the judge's reply to every request
on every row of a sheet and on every control; its verdict on an answer is the one that
more than half of the requests gave. This module lays the two side by side and writes a
report in Markdown. It reads what the judge was never given: the grades of the sheet, its
key, the records of the runs, and what the file of controls says of each control.

The rows of the sheet and the controls are reported apart, and no rate of agreement
stands alone. Of the 118 rows of the evaluation the person graded one wrong, so a judge
that calls every answer right would agree on 117 of them: the report writes that number
beside the judge's own. Whether the judge can tell a wrong answer is what the controls
show, answers made to be wrong and asked like the rows.

    rows of the sheet   the grade by hand against the judge's verdict; how many rows a
                        judge that calls every answer right would agree on; the rows graded
                        wrong by hand, the rows where the two differ, and the rows on which
                        the requests did not all say the same, with what the judge wrote
    controls            how many the judge called wrong, by more than half of the requests
                        and in all of them: in all, by the kind of fault, by how they were
                        made, by question, and against what the rule of grade.py says of the
                        same text; the controls not called wrong in every request
    H2                  again, with the judge's verdicts in place of the grades by hand: a
                        layout answers a question right when more than half of its runs that
                        count are right, and a run without an answer is wrong
    requests            how many had a thinking block, and what they cost from their usage

It refuses a record that is not complete, that asked only some of the answers, or that was
begun with another question file, sheet or file of controls than the ones it is given; a
sheet that is not graded in full; and a control that is not graded wrong.
"""

from __future__ import annotations

import argparse
import csv
import sys
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from hepph_paper_miner.agent.origin import file_digest
from hepph_paper_miner.eval.grade import BY_HAND, Record, grade_answer
from hepph_paper_miner.eval.judge import RIGHT, WRONG, JudgeError, read_record, totals, verdict_of
from hepph_paper_miner.eval.questions import Question, QuestionFileError, load_questions
from hepph_paper_miner.eval.run import LAYOUTS, Attempt
from hepph_paper_miner.eval.sheet import HandGrade, SheetError, counted_attempts, read_grades

# The columns of a file of controls that are read here. The judge reads four of them
# (judge.py); the others say how a control was made and what is wrong with it.
CONTROL_COLUMNS = (
    "id",
    "question_id",
    "kind",
    "found",
    "answer",
    "grade",
    "why_wrong",
    "detail",
    "base_number",
)

Cell = tuple[str, str]  # a question and a layout


class AgreeError(ValueError):
    """Something the report cannot be made from. The message says what."""


@dataclass(frozen=True)
class Control:
    """An answer made to be wrong, with what its file says of it."""

    id: str
    question_id: str
    kind: str  # a wrong answer of a kind that the note names, or a wrong answer of another kind
    why_wrong: str  # the kind of fault
    detail: str  # what in particular is wrong
    base: str  # the number of the row of the sheet it was made from; "" if written anew
    found: bool
    answer: str


@dataclass(frozen=True)
class Judged:
    """What the judge said of one answer, request by request."""

    verdicts: tuple[str | None, ...]  # RIGHT, WRONG or None (a reply that is no verdict)
    whys: tuple[str, ...]
    thinking: int  # how many of the replies held a thinking block

    @property
    def verdict(self) -> str | None:
        """The one that more than half of the requests gave, or None."""
        return verdict_of(self.verdicts, len(self.verdicts))

    @property
    def unanimous(self) -> bool:
        return len(set(self.verdicts)) == 1


# --- reading -------------------------------------------------------------------------------


def read_controls(path: Path) -> list[Control]:
    """The controls of a file, in its order, with everything it says of them."""
    try:
        with path.open(encoding="utf-8-sig", newline="") as stream:
            reader = csv.DictReader(stream)
            lines = list(reader)
            there = reader.fieldnames or []
    except UnicodeDecodeError as error:
        raise AgreeError(
            f"{path.name}: the file of controls is not UTF-8 text ({error})"
        ) from error
    missing = [name for name in CONTROL_COLUMNS if name not in there]
    if missing:
        raise AgreeError(f"{path.name}: the file of controls has no column {', '.join(missing)}")
    controls = []
    for line in lines:
        values = {name: (line.get(name) or "").strip() for name in CONTROL_COLUMNS}
        if not any(values.values()):
            continue  # an empty line that a spreadsheet left
        where = f"{path.name} {values['id'] or '(no id)'}"
        if values["grade"].casefold() != WRONG:
            # A control is an answer made to be wrong; one graded otherwise shows nothing.
            raise AgreeError(f"{where}: graded {values['grade']!r}, and a control is wrong")
        found = values["found"].casefold()
        if found not in ("true", "false"):
            raise AgreeError(f"{where}: found is {values['found']!r}, neither true nor false")
        controls.append(
            Control(
                values["id"],
                values["question_id"],
                values["kind"],
                values["why_wrong"],
                values["detail"],
                values["base_number"],
                found == "true",
                # As the cell holds it: the text the judge was given, and the rule reads.
                line.get("answer") or "",
            )
        )
    return controls


def check_record(
    path: Path,
    head: Mapping[str, Any],
    end: Mapping[str, Any] | None,
    given: Mapping[str, tuple[Path, int | None]],
) -> None:
    """Refuse a record that does not stand for these files and every one of their answers."""
    if end is None:
        # The judge writes its last line only once every request has its reply.
        raise AgreeError(f"{path.name}: no last line, so not every request has its reply")
    if head.get("only") is not None:
        raise AgreeError(
            f"{path.name}: it asked only some of the answers ({' '.join(head['only'])})"
        )
    for name, (file, answers) in given.items():
        named = head.get(name) or {}
        if named.get("sha256") != file_digest(file):
            raise AgreeError(
                f"{path.name}: begun with another {name} than {file.name}, "
                "or with this one before it changed"
            )
        if answers is not None and named.get("answers") != answers:
            raise AgreeError(
                f"{path.name}: begun with {named.get('answers')} answer(s) of the {name}, "
                f"and {file.name} has {answers}"
            )


def judged(lines: Sequence[Mapping[str, Any]], repeats: int) -> dict[str, Judged]:
    """The replies of a record, answer by answer. Every answer has one for each request."""
    replies: dict[str, dict[int, Mapping[str, Any]]] = {}
    for line in lines:
        if line.get("record") != "verdict":
            continue  # a request the API failed was asked again, and has a line of its own
        got = replies.setdefault(line["item"], {})
        if line["repeat"] in got:
            raise AgreeError(f"{line['item']}: two replies to request {line['repeat']}")
        got[line["repeat"]] = line
    found = {}
    for item, got in replies.items():
        if sorted(got) != list(range(1, repeats + 1)):
            raise AgreeError(
                f"{item}: replies to the requests {sorted(got)}, not to each of {repeats}"
            )
        ordered = [got[repeat] for repeat in sorted(got)]
        found[item] = Judged(
            tuple(line["verdict"] for line in ordered),
            tuple(line.get("why") or "" for line in ordered),
            sum(1 for line in ordered if "thinking" in (line.get("blocks") or ())),
        )
    return found


def rule_of(question: Question, control: Control) -> str:
    """What the rule of grade.py says of the text of a control, as of an answer of a run."""
    answer = {"answer": control.answer, "found": control.found, "evidence": []}
    end = {"record": "end", "reason": "answered", "answer": answer}
    return grade_answer(Record({}, (), end), question).rule


# --- H2 --------------------------------------------------------------------------------------


def by_cell(
    attempts: Sequence[Attempt],
    hand: Sequence[HandGrade],
    verdicts: Mapping[int, str | None],
) -> dict[Cell, list[str | None]]:
    """The verdict on every run that counts, by question and layout.

    A run with an answer has the verdict given to its row of the sheet. A run without one
    is wrong, as in report.py, and is not on the sheet.
    """
    numbers = {grade.run_id: grade.number for grade in hand}
    cells: dict[Cell, list[str | None]] = {}
    seen = set()
    for attempt in attempts:
        run_id = attempt.run["run_id"]
        if run_id in numbers:
            verdict = verdicts[numbers[run_id]]
            seen.add(run_id)
        elif attempt.end and attempt.end.get("answer"):
            raise AgreeError(f"{run_id}: a run that counts handed in an answer the sheet lacks")
        else:
            verdict = WRONG
        cell = (attempt.run["question_id"], attempt.run["toolset"])
        cells.setdefault(cell, []).append(verdict)
    left = sorted(set(numbers) - seen)
    if left:
        raise AgreeError(f"the key names {left[0]}, which is not a run that counts")
    return cells


def majority(verdicts: Sequence[str | None]) -> bool | None:
    """Whether more than half of the runs are right; None if one of them has no verdict."""
    if not verdicts or any(verdict is None for verdict in verdicts):
        return None
    return 2 * sum(1 for verdict in verdicts if verdict == RIGHT) > len(verdicts)


def h2(questions: Sequence[Question], cells: Mapping[Cell, Sequence[str | None]]) -> Counter:
    """How many questions each layout answers right: (staged, flat) -> questions."""
    staged, flat = LAYOUTS
    return Counter(
        (majority(cells.get((q.id, staged), ())), majority(cells.get((q.id, flat), ())))
        for q in questions
    )


# --- the report ------------------------------------------------------------------------------


def _row(cells: Sequence[str]) -> str:
    return "| " + " | ".join(cells) + " |"


def _table(head: Sequence[str], rows: Iterable[Sequence[str]]) -> list[str]:
    return [_row(head), _row(["---"] * len(head)), *(_row(row) for row in rows)]


def _text(value: str) -> str:
    """A text of the record on one line of Markdown, its bars kept as bars."""
    return " ".join(value.split()).replace("|", "\\|")


def _said(one: Judged) -> str:
    return ", ".join(verdict or "no verdict" for verdict in one.verdicts)


def _entry(title: str, one: Judged) -> list[str]:
    lines = [f"- {title}; the judge: {_said(one)}"]
    for repeat, (verdict, why) in enumerate(zip(one.verdicts, one.whys, strict=True), start=1):
        lines.append(f"  - {repeat}, {verdict or 'no verdict'}: {_text(why) or '(nothing)'}")
    return lines


def _counts(group: Sequence[Judged]) -> list[str]:
    """Of the controls of a group: wrong by more than half, wrong in every request, right, none."""
    return [
        str(len(group)),
        str(sum(1 for one in group if one.verdict == WRONG)),
        str(sum(1 for one in group if all(verdict == WRONG for verdict in one.verdicts))),
        str(sum(1 for one in group if one.verdict == RIGHT)),
        str(sum(1 for one in group if one.verdict is None)),
    ]


CONTROL_HEAD = [
    "controls",
    "wrong by more than half",
    "wrong in every request",
    "right",
    "no verdict",
]


def _grouped(
    name: str, groups: Iterable[tuple[str, Sequence[Control]]], said: Mapping[str, Judged]
) -> list[str]:
    rows = [[label, *_counts([said[c.id] for c in members])] for label, members in groups]
    return _table([name, *CONTROL_HEAD], rows)


def _by(controls: Sequence[Control], value) -> list[tuple[str, list[Control]]]:
    """The controls grouped by a value of theirs, the largest group first."""
    groups: dict[str, list[Control]] = {}
    for control in controls:
        groups.setdefault(value(control), []).append(control)
    return sorted(groups.items(), key=lambda pair: (-len(pair[1]), pair[0]))


def _h2_table(pairs: Counter) -> list[str]:
    lines = _table(
        ["", "flat right", "flat wrong"],
        [
            ["staged right", str(pairs[(True, True)]), str(pairs[(True, False)])],
            ["staged wrong", str(pairs[(False, True)]), str(pairs[(False, False)])],
        ],
    )
    open_ = sum(n for (staged, flat), n in pairs.items() if staged is None or flat is None)
    if open_:
        lines += ["", f"{open_} question(s) not in the table: a run of theirs has no verdict."]
    return lines


def _head(
    record: Path, head: Mapping[str, Any], files: Mapping[str, Path], rows: int, controls: int
) -> list[str]:
    settings = head["settings"]
    made = (
        f"Made by `eval/agree.py` from `{record.name}`. The grades by hand are the verdicts:"
        " the judge changes none of them, and nothing in `results/report.md`."
    )
    judge = (
        f"- Judge `{head['judge_version']}`, its texts sha256 `{head['texts_sha256']}`;"
        f" code `{head['code']['commit']}`; begun {head.get('started_at', '-')}"
    )
    model = (
        f"- Model `{settings['model']}`, thinking `{settings['thinking']['type']}`,"
        f" effort `{settings['effort']}`, max_tokens {settings['max_tokens']},"
        f" {settings.get('sdk', '-')}"
    )
    rule = (
        f"- {head['repeats']} requests for every answer; the judge's verdict on an answer is"
        " the one that more than half of them gave, and an answer without one has none"
    )
    given = (
        f"- Questions `{files['questions'].name}`; sheet `{files['sheet'].name}` ({rows} rows)"
        f" with its key `{files['key'].name}`; controls `{files['controls'].name}` ({controls})"
    )
    return ["# The judge against the grades by hand", "", made, "", judge, model, rule, given]


def _sheet(hand: Sequence[HandGrade], said: Mapping[str, Judged], repeats: int) -> list[str]:
    rows = [(grade, said[f"sheet-{grade.number}"]) for grade in hand]
    table = Counter((grade.grade, one.verdict) for grade, one in rows)
    asked = [verdict for _, one in rows for verdict in one.verdicts]
    agreed = sum(1 for grade, one in rows if one.verdict == grade.grade)
    right_by_hand = sum(1 for grade, _ in rows if grade.grade == RIGHT)
    line = (
        f"The judge's verdict is the grade by hand on {agreed} of {len(rows)} rows."
        f" A judge that called every answer right would agree on {right_by_hand} of them."
    )
    requests = (
        f"All {repeats} requests said the same on"
        f" {sum(1 for _, one in rows if one.unanimous)} of {len(rows)} rows."
        f" Of the {len(asked)} requests, {asked.count(RIGHT)} said right, {asked.count(WRONG)}"
        f" wrong, and {asked.count(None)} gave no verdict;"
        f" {sum(one.thinking for _, one in rows)} of the replies held a thinking block."
    )
    cells = [
        [grade, *(str(table[(grade, verdict)]) for verdict in (RIGHT, WRONG, None))]
        for grade in (RIGHT, WRONG)
    ]
    out = ["", "## The rows of the sheet", ""]
    out += _table(["by hand", "judge right", "judge wrong", "no verdict"], cells)
    out += ["", line, "", requests]
    lists = (
        ("Rows graded wrong by hand", [(g, one) for g, one in rows if g.grade == WRONG]),
        (
            "Rows where the judge's verdict is not the grade by hand",
            [(g, one) for g, one in rows if one.verdict != g.grade],
        ),
        (
            # The rows graded wrong are listed in full above, so they are not listed again.
            "Other rows on which the requests did not all say the same",
            [
                (g, one)
                for g, one in rows
                if not one.unanimous and one.verdict == g.grade and g.grade == RIGHT
            ],
        ),
    )
    for title, chosen in lists:
        out += ["", f"### {title}", ""]
        if not chosen:
            out.append("None.")
        for grade, one in chosen:
            out += _entry(f"Row {grade.number} ({grade.question_id}): {grade.grade} by hand", one)
    return out


def _controls(
    questions: Sequence[Question],
    controls: Sequence[Control],
    said: Mapping[str, Judged],
    rules: Mapping[str, str],
    repeats: int,
) -> list[str]:
    every = [said[control.id] for control in controls]
    asked = [verdict for one in every for verdict in one.verdicts]
    requests = (
        f"All {repeats} requests said the same on"
        f" {sum(1 for one in every if one.unanimous)} of {len(every)} controls."
        f" Of the {len(asked)} requests, {asked.count(WRONG)} said wrong, {asked.count(RIGHT)}"
        f" right, and {asked.count(None)} gave no verdict;"
        f" {sum(one.thinking for one in every)} of the replies held a thinking block."
    )
    rule = (
        "What the rule says of the text of a control, read as an answer a run handed in."
        f" `{BY_HAND}`: nothing the rule checks is missing, and a person has to read it."
    )
    by_question = [
        (q.id, [c for c in controls if c.question_id == q.id])
        for q in questions
        if any(c.question_id == q.id for c in controls)
    ]
    by_rule = [
        (name, [c for c in controls if rules[c.id] == name])
        for name in (WRONG, BY_HAND, RIGHT)
        if any(rules[c.id] == name for c in controls)
    ]
    made = _by(controls, lambda c: "from a row of the sheet" if c.base else "written anew")
    out = ["", "## The controls", "", "Every control is an answer made to be wrong.", ""]
    out += _table(["", *CONTROL_HEAD], [["all", *_counts(every)]])
    out += ["", requests, "", "### By the kind of fault", ""]
    out += _grouped("fault", _by(controls, lambda c: c.why_wrong), said)
    out += ["", "### By how they were made", ""]
    out += _grouped("kind", _by(controls, lambda c: c.kind), said)
    out += [""]
    out += _grouped("made", made, said)
    out += ["", "### By question", ""]
    out += _grouped("question", by_question, said)
    out += ["", "### Against the rule of grade.py", "", rule, ""]
    out += _grouped("rule", by_rule, said)
    out += ["", "### Controls not called wrong in every request", ""]
    missed = [c for c in controls if not all(v == WRONG for v in said[c.id].verdicts)]
    if not missed:
        out.append("None.")
    for c in missed:
        out += _entry(f"{c.id} ({c.question_id}, {c.why_wrong}): {_text(c.detail)}", said[c.id])
    return out


def _h2(
    questions: Sequence[Question], cells: Mapping[str, Mapping[Cell, Sequence[str | None]]]
) -> list[str]:
    rule = (
        "A layout answers a question right when more than half of its runs that count are"
        " right, and a run without an answer is wrong. By hand, as in `results/report.md`:"
    )
    out = ["", "## H2 with the judge's verdicts", "", rule, ""]
    out += _h2_table(h2(questions, cells["hand"]))
    out += ["", "With the judge's verdict in place of the grade by hand:", ""]
    out += _h2_table(h2(questions, cells["judge"]))

    def right(name: str, q: Question, layout: str) -> str:
        runs = cells[name].get((q.id, layout), ())
        return f"{sum(1 for verdict in runs if verdict == RIGHT)} / {len(runs)}"

    moved = []
    for q in questions:
        counts = [(right("hand", q, layout), right("judge", q, layout)) for layout in LAYOUTS]
        if any(by_hand != by_judge for by_hand, by_judge in counts):
            moved.append([q.id, *(count for pair in counts for count in pair)])
    out += ["", "Questions in which the runs called right are not the same:", ""]
    if not moved:
        return [*out, "None."]
    head = [
        "question",
        *(f"{layout} {who}" for layout in LAYOUTS for who in ("by hand", "by the judge")),
    ]
    return out + _table(head, moved)


def _requests(lines: Sequence[Mapping[str, Any]]) -> list[str]:
    sums = totals(lines)
    replies = [line for line in lines if line.get("record") == "verdict"]
    thinking = sum(1 for line in replies if "thinking" in (line.get("blocks") or ()))
    usage, cost = sums["usage"], sums["cost"]
    asked = (
        f"{sums['requests']} requests, each with a reply; {thinking} of the replies held a"
        f" thinking block. Requests that failed at the API and were asked again:"
        f" {sums['failed']}."
    )
    tokens = (
        f"Input {usage.get('input_tokens', 0):,} tokens, output {usage.get('output_tokens', 0):,}"
        " tokens, thinking included."
    )
    if cost is None:
        money = "No price is known for the model of a reply."
    else:
        money = (
            f"${cost:.2f}, worked out from the usage at the prices of `eval/report.py`;"
            " not read from the Console."
        )
    return ["", "## The requests", "", asked, "", f"{tokens} {money}", ""]


def write_report(
    record: Path,
    head: Mapping[str, Any],
    lines: Sequence[Mapping[str, Any]],
    questions: Sequence[Question],
    files: Mapping[str, Path],
    hand: Sequence[HandGrade],
    controls: Sequence[Control],
    said: Mapping[str, Judged],
    cells: Mapping[str, Mapping[Cell, Sequence[str | None]]],
    rules: Mapping[str, str],
) -> str:
    out = _head(record, head, files, len(hand), len(controls))
    out += _sheet(hand, said, head["repeats"])
    out += _controls(questions, controls, said, rules, head["repeats"])
    out += _h2(questions, cells)
    out += _requests(lines)
    return "\n".join(out)


# --- the command -----------------------------------------------------------------------------


def make(
    questions_file: Path,
    record: Path,
    sheet: Path,
    key: Path,
    controls_file: Path,
    runs: Path,
) -> str:
    """The report, from the files it is made of. Raises when they do not fit together."""
    questions = load_questions(questions_file)
    by_id = {question.id: question for question in questions}
    head, lines, end = read_record(record)
    hand = read_grades(sheet, key)
    if any(grade.grade is None for grade in hand):
        open_ = [grade.number for grade in hand if grade.grade is None]
        raise AgreeError(f"{sheet.name}: not every row is graded (row {open_[0]})")
    controls = read_controls(controls_file)
    check_record(
        record,
        head,
        end,
        {
            "questions": (questions_file, None),
            "sheet": (sheet, len(hand)),
            "controls": (controls_file, len(controls)),
        },
    )
    said = judged(lines, head["repeats"])
    asked = {f"sheet-{grade.number}" for grade in hand} | {control.id for control in controls}
    if set(said) != asked:
        odd = sorted(set(said) ^ asked)
        raise AgreeError(
            f"{record.name}: the answers it holds are not those of the files ({odd[0]})"
        )
    rows = {grade.number: grade for grade in hand}
    for control in controls:
        if control.question_id not in by_id:
            raise AgreeError(
                f"{control.id}: its question {control.question_id!r} is not in the file"
            )
        if control.base:
            base = rows.get(int(control.base)) if control.base.isdigit() else None
            if base is None or base.question_id != control.question_id:
                raise AgreeError(
                    f"{control.id}: made from row {control.base}, which is not a row of"
                    f" {control.question_id} on the sheet"
                )
    attempts, _ = counted_attempts(questions, runs, file_digest(questions_file))
    cells = {
        "hand": by_cell(attempts, hand, {grade.number: grade.grade for grade in hand}),
        "judge": by_cell(
            attempts, hand, {grade.number: said[f"sheet-{grade.number}"].verdict for grade in hand}
        ),
    }
    rules = {control.id: rule_of(by_id[control.question_id], control) for control in controls}
    files = {"questions": questions_file, "sheet": sheet, "key": key, "controls": controls_file}
    return write_report(record, head, lines, questions, files, hand, controls, said, cells, rules)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m hepph_paper_miner.eval.agree",
        description="Hold the verdicts of a judge against the grades by hand, and write a report.",
    )
    parser.add_argument("--questions", type=Path, required=True, help="the question file")
    parser.add_argument("--record", type=Path, required=True, help="the record of the judge")
    parser.add_argument("--sheet", type=Path, required=True, help="the sheet graded by hand")
    parser.add_argument("--key", type=Path, required=True, help="the key of the sheet")
    parser.add_argument("--controls", type=Path, required=True, help="the file of controls")
    parser.add_argument("--runs", type=Path, required=True, help="the records of the runs")
    parser.add_argument("--out", type=Path, required=True, help="the report to write (Markdown)")
    arguments = parser.parse_args(argv)

    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="backslashreplace")
    try:
        text = make(
            arguments.questions,
            arguments.record,
            arguments.sheet,
            arguments.key,
            arguments.controls,
            arguments.runs,
        )
    except (OSError, QuestionFileError, SheetError, JudgeError, AgreeError) as error:
        print(f"refused: {error}", file=sys.stderr)
        return 2
    arguments.out.parent.mkdir(parents=True, exist_ok=True)
    arguments.out.write_text(text, encoding="utf-8", newline="\n")
    print(f"wrote {arguments.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
