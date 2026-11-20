"""Hold the runs of a changed version against the runs of the version before it.

    uv run python -m hepph_paper_miner.eval.regress --questions eval_data/questions_dev.jsonl \
        --before results/runs/dev/diag-3-tool --after results/runs/regress/dev-after \
        --sheet sheet.csv --key key.csv --judge judge.jsonl

When a text that a model reads is changed, or what a tool answers, the questions that
were answered before are asked again, and this command says whether the runs still do
what they did. What that means was written down here before any such run was made:

    1  every cell of the plan has a run that counts, and it ended with an answer
    2  the passage a question rests on was given to the model in every run
    3  the rule (grade.py) calls no answer wrong, and where it called every answer of a
       question and layout right before, it calls every one right now
    4  no answer that the rule leaves to a person is wrong: by the grade a person wrote
       on the sheet, or without one by the judge (judge.py); an answer the judge calls
       wrong stays open until a person has read it
    5  for every question, the staged runs were given less text than the flat ones
       (the median of the characters of the tool results)

All five hold: passed. One does not: failed. One cannot be told (a paper that cannot be
read, an answer nobody graded): not decided. Responses, characters, cost and the calls
that came back as errors are shown and decide nothing; a cell whose runs took more
responses than any run of it before is marked, so that somebody reads its records.

The two sides can be compared only when they differ in the tool texts and the code and
in nothing else: the same question file, the same cells, the same prompt, model and
limits. Otherwise the command refuses.

With --targets the questions are ones written to show an effect of the change (the
passage stands where the version before did not lead a model). Then nothing passes or
fails. The command counts, for the staged layout, the runs in which the passage was
given, and says "shown" when that count went up and went down for no question, and
"not shown" otherwise: also when the version before gave the passage every time, so
that there was nothing to gain. Such questions are written by somebody who knew the
change, on few papers. What they show is that the change does what it was made for on
these cases, and nothing about questions in general.

The sheet and its key are the ones eval.sheet writes for the runs after, and the record
is the one eval.judge writes for that sheet. Grades may be written into the sheet after
the judge has read it.
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from pathlib import Path
from statistics import median
from typing import Any

from hepph_paper_miner.eval.grade import BY_HAND, RIGHT, WRONG, Record, grade
from hepph_paper_miner.eval.questions import Question, QuestionFileError, load_questions
from hepph_paper_miner.eval.report import cost_of
from hepph_paper_miner.eval.run import LAYOUTS, REPEATS, Attempt, Cell
from hepph_paper_miner.eval.sheet import SheetError, counted_attempts, read_grades
from hepph_paper_miner.sources.base import Paper, PaperSource, SourceError, parse_arxiv_id

PASSED, FAILED, OPEN = "passed", "failed", "not decided"
SHOWN, NOT_SHOWN = "shown", "not shown"

# What the first line of a record names and the two sides have to agree in. The tool
# texts and the code are what was changed, and the packages belong to the code.
_SAME = ("answer_channel", "prompt_version", "limits", "questions", "model")


class RegressError(ValueError):
    """Two sets of runs that cannot be compared, or files that do not belong to them."""


@dataclass(frozen=True)
class Facts:
    """What is asked of one run. A program reads all of it but the verdicts off the record."""

    cell: Cell
    run_id: str
    reason: str  # why the run ended
    turns: int
    chars: int  # the characters of its tool results
    cost: float | None
    passage: bool | None  # whether the passage was given; None: its paper could not be read
    rule: str  # RIGHT, WRONG or BY_HAND
    errors: tuple[str, ...] = ()  # the kind of every call that came back as an error
    by_person: str | None = None  # the grade on the sheet, when a person wrote one
    by_judge: str | None = None  # what more than half of the judge's requests said


@dataclass(frozen=True)
class Finding:
    name: str
    state: str
    lines: tuple[str, ...] = ()  # what makes it failed or open


Side = Mapping[Cell, Facts]


# --- reading the two sides ---------------------------------------------------------------


def _names(attempts: Sequence[Attempt], which: str) -> dict[str, Any]:
    """What the runs of one side name in their first lines, each thing once."""
    found: dict[str, Any] = {}

    def one(what: str, values: list[Any]) -> None:
        different = []
        for value in values:
            if value not in different:
                different.append(value)
        if len(different) != 1:
            raise RegressError(f"the runs {which} do not name one {what}: {different}")
        found[what] = different[0]

    for name in _SAME:
        values = [attempt.run.get(name) for attempt in attempts]
        if name == "model":  # the SDK that sent the requests belongs to the code
            values = [{k: v for k, v in (value or {}).items() if k != "sdk"} for value in values]
        one(name, values)
    for layout in LAYOUTS:
        of_layout = [a.run.get("toolset_version") for a in attempts if a.cell.toolset == layout]
        if of_layout:
            one(f"toolset_version of {layout}", of_layout)
    one("commit of the code", [(a.run.get("code") or {}).get("commit") for a in attempts])
    return found


def comparable(before: Sequence[Attempt], after: Sequence[Attempt]) -> tuple[dict, dict]:
    """What each side names, once it is sure that they differ in nothing they must share."""
    named = _names(before, "before"), _names(after, "after")
    for name in _SAME:
        if named[0][name] != named[1][name]:
            raise RegressError(
                f"the two sides differ in {name}: {named[0][name]!r} before, "
                f"{named[1][name]!r} after"
            )
    return named


def facts_of(attempt: Attempt, question: Question, papers: Mapping[str, Paper]) -> Facts:
    graded = grade(Record(attempt.run, attempt.turns, attempt.end), question, papers)
    return Facts(
        cell=attempt.cell,
        run_id=attempt.run["run_id"],
        reason=graded.reason,
        turns=graded.turns,
        chars=attempt.end.get("tool_result_chars") or 0,
        cost=cost_of(attempt.turns, (attempt.run.get("model") or {}).get("model")),
        passage=graded.access.met,
        rule=graded.answer.rule,
        errors=tuple(
            call.get("error_kind") or "?"
            for turn in attempt.turns
            for call in turn.get("tools", ())
            if call.get("status") == "error"
        ),
    )


def with_verdicts(
    side: Side, attempts: Sequence[Attempt], questions: Path, sheet: Path, key: Path, record: Path
) -> tuple[dict[Cell, Facts], list[str]]:
    """The runs after, each with what a person and the judge said of its answer.

    Refused when the sheet is not the sheet of these runs, or the record not the record
    of a whole pass of this judge over a sheet of as many answers.
    """
    from hepph_paper_miner.agent.origin import file_digest
    from hepph_paper_miner.eval import judge
    from hepph_paper_miner.eval.agree import AgreeError, judged
    from hepph_paper_miner.eval.sheet import _cell

    hand = read_grades(sheet, key)
    answers = {a.run["run_id"]: a.end["answer"] for a in attempts if a.end.get("answer")}
    if sorted(row.run_id for row in hand) != sorted(answers):
        raise RegressError(f"{key.name} is not the key of the runs after that gave an answer")
    shown = {item.id: item for item in judge.sheet_items(sheet)}
    for row in hand:
        item, answer = shown[f"sheet-{row.number}"], answers[row.run_id]
        if (item.found, item.answer) != (answer["found"], _cell(answer["answer"])):
            raise RegressError(f"{sheet.name} number {row.number}: not the answer of {row.run_id}")

    head, lines, end = judge.read_record(record)
    of_sheet = head.get("sheet") or {}
    version = (head.get("judge_version"), head.get("texts_sha256"))
    wrong = [
        text
        for is_wrong, text in (
            (
                version != (judge.JUDGE_VERSION, judge.texts_digest()),
                f"it is of the judge {version[0]!r}, not of {judge.JUDGE_VERSION!r} as it is now",
            ),
            (end is None, "it has no last line, so not every request has its reply"),
            (head.get("only") is not None, "it asked only some of the answers"),
            (
                (head.get("questions") or {}).get("sha256") != file_digest(questions),
                "it was begun with another question file",
            ),
            (of_sheet.get("answers") != len(hand), f"its sheet did not have {len(hand)} answers"),
        )
        if is_wrong
    ]
    if wrong:
        raise RegressError(f"{record.name}: " + "; ".join(wrong))
    try:
        said = judged(lines, head["repeats"])
    except AgreeError as error:
        raise RegressError(f"{record.name}: {error}") from error
    notes = []
    if of_sheet.get("sha256") != file_digest(sheet):
        # Grades written into the sheet change its digest. Its answers were held against
        # the records above; that the judge read these very cells is then not checked.
        notes.append(f"{sheet.name} has changed since the judge read it (grades, or more).")
    by_run = {facts.run_id: cell for cell, facts in side.items()}
    found = dict(side)
    for row in hand:
        one = said.get(f"sheet-{row.number}")
        if one is None:
            raise RegressError(f"{record.name}: no verdict on number {row.number} of the sheet")
        cell = by_run[row.run_id]
        found[cell] = replace(found[cell], by_person=row.grade, by_judge=one.verdict)
    return found, notes


# --- the criteria ------------------------------------------------------------------------


def _state(failed: Sequence[str], undecided: Sequence[str]) -> str:
    return FAILED if failed else OPEN if undecided else PASSED


def criteria(before: Side, after: Side, cells: Sequence[Cell]) -> list[Finding]:
    """The five things the runs after have to do, each passed, failed or not decided."""
    there = [after[cell] for cell in cells if cell in after]
    pairs = sorted({(cell.question_id, cell.toolset) for cell in cells})

    missing = [f"{cell}: no run that counts" for cell in cells if cell not in after]
    unanswered = [f"{f.cell}: ended as {f.reason}" for f in there if f.reason != "answered"]
    first = Finding(
        "1 every run ended with an answer",
        _state(missing + unanswered, ()),
        (*missing, *unanswered),
    )

    not_given = [f"{f.cell}: the passage was not given" for f in there if f.passage is False]
    unknown = [f"{f.cell}: its paper could not be read" for f in there if f.passage is None]
    second = Finding(
        "2 the passage was given in every run", _state(not_given, unknown), (*not_given, *unknown)
    )

    by_rule = [f"{f.cell}: the rule calls the answer wrong" for f in there if f.rule == WRONG]
    for question_id, layout in pairs:
        of_pair = [c for c in cells if (c.question_id, c.toolset) == (question_id, layout)]
        earlier = [before[cell].rule for cell in of_pair if cell in before]
        if earlier and set(earlier) == {RIGHT}:
            by_rule += [
                f"{cell}: right by the rule in every run before, {after[cell].rule} now"
                for cell in of_pair
                if cell in after and after[cell].rule == BY_HAND
            ]
    third = Finding("3 the rule calls no answer wrong", _state(by_rule, ()), tuple(by_rule))

    wrong, to_read = [], []
    for facts in there:
        if facts.rule != BY_HAND:
            continue
        if facts.by_person == WRONG:
            wrong.append(f"{facts.cell}: graded wrong by a person")
        elif facts.by_person is None and facts.by_judge == WRONG:
            to_read.append(f"{facts.cell}: the judge calls it wrong, and nobody has read it")
        elif facts.by_person is None and facts.by_judge is None:
            to_read.append(f"{facts.cell}: neither a person nor the judge has graded it")
    fourth = Finding(
        "4 no answer left to a person is wrong", _state(wrong, to_read), (*wrong, *to_read)
    )

    more, no_runs = [], []
    for question_id in dict.fromkeys(cell.question_id for cell in cells):
        middle = {
            layout: [
                f.chars
                for f in there
                if (f.cell.question_id, f.cell.toolset) == (question_id, layout)
            ]
            for layout in LAYOUTS
        }
        if not all(middle.values()):
            no_runs.append(f"{question_id}: a layout without a run")
        elif not median(middle["staged"]) < median(middle["flat"]):
            more.append(
                f"{question_id}: staged {median(middle['staged']):,.0f} characters, "
                f"flat {median(middle['flat']):,.0f}"
            )
    fifth = Finding(
        "5 staged was given less text than flat", _state(more, no_runs), (*more, *no_runs)
    )
    return [first, second, third, fourth, fifth]


def verdict(findings: Sequence[Finding]) -> str:
    states = {finding.state for finding in findings}
    return FAILED if FAILED in states else OPEN if OPEN in states else PASSED


def effect(before: Side, after: Side, cells: Sequence[Cell]) -> tuple[str, list[str]]:
    """Whether the passage was given in more staged runs than before, and in fewer of no question."""
    staged = [cell for cell in cells if cell.toolset == "staged"]
    lines, counts = [], []
    for question_id in dict.fromkeys(cell.question_id for cell in staged):
        of_question = [cell for cell in staged if cell.question_id == question_id]
        sides = []
        for side in (before, after):
            given = [side[cell].passage for cell in of_question if cell in side]
            if len(given) != len(of_question) or None in given:
                return OPEN, [f"{question_id}: a run is missing, or its paper could not be read"]
            sides.append(sum(given))
        counts.append(tuple(sides))
        lines.append(f"{question_id}: {sides[0]} of {len(of_question)} before, {sides[1]} after")
    up = sum(now for _, now in counts) > sum(then for then, _ in counts)
    down = any(now < then for then, now in counts)
    return (SHOWN if up and not down else NOT_SHOWN), lines


# --- the text ----------------------------------------------------------------------------


def _row(cells: Sequence[str]) -> str:
    return "| " + " | ".join(cells) + " |"


def _money(runs: Sequence[Facts]) -> str:
    costs = [f.cost for f in runs]
    return "?" if None in costs or not costs else f"${sum(costs):.2f}"


def _of(runs: Sequence[Facts]) -> list[str]:
    """The cells of the table for the runs of one question and layout on one side."""
    if not runs:
        return ["-"] * 6
    rules = Counter(f.rule for f in runs)
    return [
        f"{sum(1 for f in runs if f.reason == 'answered')} / {len(runs)}",
        "?"
        if any(f.passage is None for f in runs)
        else f"{sum(1 for f in runs if f.passage)} / {len(runs)}",
        ", ".join(f"{count} {rule}" for rule, count in sorted(rules.items())),
        " ".join(str(f.turns) for f in runs),
        f"{median(f.chars for f in runs):,.0f}",
        _money(runs),
    ]


def table(before: Side, after: Side, cells: Sequence[Cell]) -> list[str]:
    head = ["question", "layout", "side", "answered", "passage given", "rule", "responses"]
    head += ["characters (median)", "cost", "calls that failed", ""]
    lines = [_row(head), _row(["---"] * len(head))]
    asked = dict.fromkeys(cell.question_id for cell in cells)
    for question_id, layout in ((name, layout) for name in asked for layout in LAYOUTS):
        of_pair = [c for c in cells if (c.question_id, c.toolset) == (question_id, layout)]
        if not of_pair:
            continue
        then = [before[cell] for cell in of_pair if cell in before]
        now = [after[cell] for cell in of_pair if cell in after]
        for side, runs in (("before", then), ("after", now)):
            failed = Counter(kind for f in runs for kind in f.errors)
            mark = ""
            more = then and now and median(f.turns for f in now) > max(f.turns for f in then)
            if side == "after" and more:
                mark = "more responses than any run before: read the records"
            lines.append(
                _row(
                    [question_id, layout, side, *_of(runs)]
                    + [", ".join(f"{n} {kind}" for kind, n in sorted(failed.items())) or "-", mark]
                )
            )
    return lines


def text_of(
    header: Sequence[str],
    before: Side,
    after: Side,
    cells: Sequence[Cell],
    targets: bool,
) -> tuple[str, str]:
    """The whole text, and the one word it comes to."""
    lines = [*header, ""]
    if targets:
        said, counted = effect(before, after, cells)
        lines += ["Runs of the staged layout in which the passage was given:", ""]
        lines += [f"- {line}" for line in counted]
        lines += ["", f"The effect of the change on these questions: {said}."]
    else:
        findings = criteria(before, after, cells)
        said = verdict(findings)
        for finding in findings:
            lines.append(f"- {finding.name}: {finding.state}")
            lines += [f"    - {line}" for line in finding.lines]
        lines += ["", f"The runs after, held against the runs before: {said}."]
    lines += ["", *table(before, after, cells), ""]
    return "\n".join(lines), said


# --- the command -------------------------------------------------------------------------


def _side(
    questions: Sequence[Question],
    folder: Path,
    digest: str,
    repeats: int,
    papers: Mapping[str, Paper],
) -> tuple[list[Attempt], dict[Cell, Facts], list[Cell]]:
    attempts, state = counted_attempts(questions, folder, digest, repeats)
    by_id = {question.id: question for question in questions}
    facts = {a.cell: facts_of(a, by_id[a.run["question_id"]], papers) for a in attempts}
    return attempts, facts, state.cells


def main(argv: Sequence[str] | None = None, source: PaperSource | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m hepph_paper_miner.eval.regress",
        description="Hold the runs of a changed version against the runs of the one before.",
    )
    parser.add_argument("--questions", type=Path, required=True, help="the question file")
    parser.add_argument("--before", type=Path, required=True, help="folder of the runs before")
    parser.add_argument("--after", type=Path, required=True, help="folder of the runs after")
    parser.add_argument(
        "--repeats", type=int, default=REPEATS, help="repetitions (default: %(default)s)"
    )
    parser.add_argument("--sheet", type=Path, help="the sheet of the runs after (eval.sheet)")
    parser.add_argument("--key", type=Path, help="the key of that sheet")
    parser.add_argument("--judge", type=Path, help="the record of the judge on that sheet")
    parser.add_argument(
        "--targets",
        action="store_true",
        help="the questions were written to show an effect: count, and pass or fail nothing",
    )
    parser.add_argument("--out", type=Path, help="write the text here instead of printing it")
    arguments = parser.parse_args(argv)

    from hepph_paper_miner.agent.origin import file_digest

    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="backslashreplace")
    graded = (arguments.sheet, arguments.key, arguments.judge)
    if any(graded) and not all(graded):
        print("--sheet, --key and --judge go together", file=sys.stderr)
        return 2
    try:
        questions = load_questions(arguments.questions)
    except (OSError, QuestionFileError) as error:
        print(f"cannot read the questions: {error}", file=sys.stderr)
        return 2
    digest = file_digest(arguments.questions)

    if source is None:
        from hepph_paper_miner.eval.report import _arxiv

        source = _arxiv()
    papers: dict[str, Paper] = {}
    for key in dict.fromkeys(key for question in questions for key in question.gold_papers):
        try:
            papers[key] = source.paper(parse_arxiv_id(key))
        except SourceError as error:
            print(f"cannot read {key}: {error}", file=sys.stderr)

    try:
        sides = [
            _side(questions, folder, digest, arguments.repeats, papers)
            for folder in (arguments.before, arguments.after)
        ]
        (then, before, cells), (now, after, _) = sides
        absent = [cell for cell in cells if cell not in before]
        if absent:
            raise RegressError(f"the runs before have no run that counts of {absent[0]}")
        if not now:
            raise RegressError(f"{arguments.after} holds no run that counts")
        named = comparable(then, now)
        notes: list[str] = []
        if all(graded):
            after, notes = with_verdicts(after, now, arguments.questions, *graded)
    except (RegressError, SheetError, OSError, ValueError) as error:
        print(f"refused: {error}", file=sys.stderr)
        return 2

    header = [f"Questions: {arguments.questions.name}, SHA-256 {digest}"]
    for which, folder, names, runs in (
        ("Before", arguments.before, named[0], then),
        ("After", arguments.after, named[1], now),
    ):
        texts = ", ".join(
            str(names[f"toolset_version of {layout}"])
            for layout in LAYOUTS
            if f"toolset_version of {layout}" in names
        )
        header.append(
            f"{which}: {folder.as_posix()}; {len(runs)} runs; tool texts {texts}; "
            f"code {str(names['commit of the code'])[:7]}"
        )
    header += notes
    text, said = text_of(header, before, after, cells, arguments.targets)
    if arguments.out:
        arguments.out.parent.mkdir(parents=True, exist_ok=True)
        arguments.out.write_text(text, encoding="utf-8", newline="\n")
        print(f"{said}: the text is {arguments.out}")
    else:
        print(text, end="")
    return 0 if said in (PASSED, SHOWN, NOT_SHOWN) else 1


if __name__ == "__main__":
    sys.exit(main())
