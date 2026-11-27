"""The report of the second evaluation: one run for a cell, and a verdict from three graders.

    uv run python -m hepph_paper_miner.eval.second --questions eval_data/questions_archives.jsonl \
        --runs results/runs/archives --sheet runs_private/archives/answers.csv \
        --key runs_private/archives/answers-key.csv --judge runs_private/archives/judge.jsonl \
        --hand-sheet runs_private/archives/hand.csv --hand-key runs_private/archives/hand-key.csv \
        --out results/archives/report.md

report.py writes the report of the first evaluation: three runs for a cell, every answer
graded by a person, and a question right in a layout when more than half of its runs are.
The second evaluation is set up otherwise (eval_data/PREREGISTRATION_2.md), and this
module writes what its Sections 11 to 14 say is reported. It counts a run as report.py
does (grade.py, and the text a run was given), and it changes nothing in report.py: the
report of the first evaluation comes out as it was written.

    the verdicts   on an answer, the grade by hand where there is one and the verdict of
                   the judge otherwise; a run without an answer is wrong (hand.py). The
                   report says how many verdicts came from where, and holds the grades by
                   hand against the rule and the judge.
    H1             the questions whose staged run was given fewer characters of tool
                   results than their flat run, more, and as many, with a one-sided exact
                   sign test, ties left out
    H2             the paired table of the questions, and the 95% interval of the
                   difference of the two rates of right answers (paired.py), read against
                   a margin of ten points
    by kind, by    the runs in which the anchor was given and the answers that are right;
    archive        the questions that name their paper by its title, with whether a search
                   listed it, beside those that name it by its identifier; the answers
                   that are right although the anchor was not given

The unit of H1 and H2 is the question. A question one of whose cells was given up, after
three runs that arXiv or the API spoilt, has no pair of runs: it is left out of both, and
the report names it. Its other run counts wherever runs are counted.

The kind of a question is its `type`, and its archive is in its notes, as assemble.py
writes them. The command refuses while a cell is still to run and while a grade by hand
is missing: a report with some of the verdicts would be read as the report.
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter
from collections.abc import Mapping, Sequence
from pathlib import Path
from types import SimpleNamespace

from hepph_paper_miner.drafting.places import KINDS, NAMED_FIRST
from hepph_paper_miner.eval import hand as grading_by_hand
from hepph_paper_miner.eval import judge as judging
from hepph_paper_miner.eval.check import to_find
from hepph_paper_miner.eval.conditions import CONDITIONS, differences
from hepph_paper_miner.eval.grade import BY_HAND, Places, Record, _reads
from hepph_paper_miner.eval.hand import DIFFER, DOUBTED, REST, SAMPLED, WIDEN_AT, Grading, HandError
from hepph_paper_miner.eval.judge import JudgeError
from hepph_paper_miner.eval.paired import (
    NOT_SHOWN,
    NOT_WORSE,
    WORSE,
    WORSE_WITHIN,
    adjusted_wald,
    reading,
)
from hepph_paper_miner.eval.questions import Question, QuestionFileError, load_questions
from hepph_paper_miner.eval.report import (
    RIGHT,
    WRONG,
    Facts,
    _arxiv,
    _median,
    _number,
    _of,
    _spread,
    _table,
    cost_of,
    facts_of,
    sign_test,
)
from hepph_paper_miner.eval.run import LAYOUTS, TRIES, State
from hepph_paper_miner.eval.sheet import SheetError
from hepph_paper_miner.sources.base import Paper, PaperSource, SourceError, parse_arxiv_id

MARGIN = 0.10  # what H2 is read against: ten points of the rate of right answers
CONDITIONS_NAME = "more-sections"  # what every run is made under (Section 10)

# What an interval says, in the words of Section 13. Were both to hold, both are said.
_NOT_WORSE = f'"not worse by more than {MARGIN * 100:.0f} points, on these questions"'
READINGS = {
    NOT_WORSE: _NOT_WORSE,
    WORSE: '"worse"',
    WORSE_WITHIN: f'"worse", and {_NOT_WORSE}',
    NOT_SHOWN: '"not shown either way"',
}

STAGED, FLAT = LAYOUTS


def archive_of(question: Question) -> str | None:
    """The archive of the paper of a question, where its file says one (assemble.py)."""
    return question.notes.get("archive")


def in_order(kinds: Sequence[str]) -> list[str]:
    """The kinds of a file in the order of drafting/places.py, and any others after them."""
    there = set(kinds)
    return [kind for kind in KINDS if kind in there] + sorted(there - set(KINDS))


# --- the questions in pairs -----------------------------------------------------------------

Pair = tuple[Facts, Facts]  # the staged run and the flat run of one question


def by_question(facts: Sequence[Facts]) -> dict[tuple[str, str], Facts]:
    """The run that counts of every cell that has one: one run for a cell."""
    found: dict[tuple[str, str], Facts] = {}
    for run in facts:
        cell = (run.question.id, run.layout)
        if cell in found:
            raise ValueError(f"{cell[0]} has two runs of {cell[1]} that count")
        found[cell] = run
    return found


def pairs_of(questions: Sequence[Question], facts: Sequence[Facts]) -> list[Pair]:
    """The questions that have a run of both layouts, in the order of the file."""
    runs = by_question(facts)
    return [
        (runs[(q.id, STAGED)], runs[(q.id, FLAT)])
        for q in questions
        if (q.id, STAGED) in runs and (q.id, FLAT) in runs
    ]


def h1(pairs: Sequence[Pair]) -> tuple[int, int, int]:
    """The questions whose staged run was given fewer characters, more, and as many."""
    fewer = sum(1 for staged, flat in pairs if staged.chars < flat.chars)
    more = sum(1 for staged, flat in pairs if staged.chars > flat.chars)
    return fewer, more, len(pairs) - fewer - more


def h2(pairs: Sequence[Pair]) -> tuple[int, int, int, int]:
    """The questions right in both layouts, in staged only, in flat only, and in neither."""
    table = Counter((staged.verdict == RIGHT, flat.verdict == RIGHT) for staged, flat in pairs)
    return table[(True, True)], table[(True, False)], table[(False, True)], table[(False, False)]


def left_out(questions: Sequence[Question], state: State) -> list[tuple[str, list[str]]]:
    """The questions without a pair of runs, each with the layouts whose cell was given up."""
    missing: dict[str, list[str]] = {}
    for cell in state.cells:
        if not state.done(cell) and not state.to_run(cell):
            missing.setdefault(cell.question_id, []).append(cell.toolset)
    return [(q.id, missing[q.id]) for q in questions if q.id in missing]


# --- the text -------------------------------------------------------------------------------


def _points(value: float) -> str:
    return f"{value * 100:+.1f}"


def _given(run: Facts) -> bool:
    return run.graded.access.met is True


def _right_without(run: Facts) -> bool:
    return run.verdict == RIGHT and run.graded.access.met is False


def _questions_table(questions: Sequence[Question]) -> list[str]:
    kinds = in_order([q.type for q in questions])
    archives = sorted({archive_of(q) for q in questions} - {None})
    count = Counter((q.type, archive_of(q)) for q in questions)
    if not archives:
        rows = [[kind, str(sum(1 for q in questions if q.type == kind))] for kind in kinds]
        return [
            *_table(["kind", "questions"], [*rows, ["all", str(len(questions))]]),
            "",
            "The questions name no archive.",
        ]
    rows = [
        [
            kind,
            *(str(count[(kind, a)]) for a in archives),
            str(sum(count[(kind, a)] for a in archives)),
        ]
        for kind in kinds
    ]
    last = [
        "all",
        *(str(sum(count[(kind, a)] for kind in kinds)) for a in archives),
        str(sum(count[(kind, a)] for kind in kinds for a in archives)),
    ]
    lines = _table(["kind", *archives, "all"], [*rows, last])
    unnamed = sum(1 for q in questions if archive_of(q) is None)
    if unnamed:
        lines += ["", f"{unnamed} question(s) name no archive, and are in no column."]
    return lines


def _by_layout(by: Mapping[str, list[Facts]]) -> list[str]:
    def column(runs: list[Facts]) -> list[str]:
        answered = [f for f in runs if f.answered]
        when = [f.graded.access.turn for f in runs if f.graded.access.turn is not None]
        after = [
            f.graded.access.turns_after for f in runs if f.graded.access.turns_after is not None
        ]
        costs = [f.cost for f in runs if f.cost is not None]
        return [
            str(len(runs)),
            _of(len(answered), len(runs)),
            _of(sum(1 for f in runs if f.verdict == RIGHT), len(runs)),
            _of(sum(1 for f in runs if _given(f)), len(runs)),
            str(sum(1 for f in runs if _right_without(f))),
            _spread(when),
            _number(_median(after)),
            f"{sum(1 for f in answered if f.graded.citation.strict)} / "
            f"{sum(1 for f in answered if f.graded.citation.loose)} of {len(answered)}",
            _spread([f.chars for f in runs]),
            _spread([f.input_tokens for f in runs]),
            _spread([f.new_text for f in runs]),
            _spread([f.calls for f in runs]),
            _spread([f.turns for f in runs]),
            str(sum(f.repeat_reads for f in runs)),
            str(sum(1 for f in runs if f.errors)),
            f"${sum(costs):.2f}" if costs else "-",
        ]

    names = [
        "runs that count",
        "answered",
        "right, by the verdict (no answer is wrong)",
        "the anchor was given",
        "right although the anchor was not given",
        "response in which the anchor was given, median (range)",
        "responses from the anchor to the answer, median",
        "cited strictly / loosely",
        "tool result chars per run, median (range)",
        "input tokens per run, median (range)",
        "new paper text per run, median (range)",
        "tool calls per run, median (range)",
        "responses per run, median (range)",
        "repeat reads, all runs",
        "runs with a tool error",
        "cost, computed",
    ]
    columns = {layout: column(by[layout]) for layout in LAYOUTS}
    if any("asked_again" in f.attempt.end for runs in by.values() for f in runs):
        # As in report.py: said where the records can say it (agent/loop.py, since p3-tool).
        names.insert(2, "of them after the loop had asked again for the call")
        for layout in LAYOUTS:
            asked = [f for f in by[layout] if f.answered and f.attempt.end.get("asked_again")]
            columns[layout].insert(2, str(len(asked)))
    lines = _table(
        ["", *LAYOUTS], ([name, *(columns[l][i] for l in LAYOUTS)] for i, name in enumerate(names))
    )
    untold = sum(1 for runs in by.values() for f in runs if f.graded.access.met is None)
    if untold:
        lines += [
            "",
            f"Whether the anchor was given cannot be told of {untold} run(s): a paper of their "
            "question could not be read here. They are not among the runs that were given it, "
            "nor among the answers that are right although it was not given.",
        ]
    rough = sum(1 for runs in by.values() for f in runs if f.rough)
    if rough:
        lines += [
            "",
            f"New paper text may count a character twice in {rough} run(s): a paper they read "
            "could not be read here.",
        ]
    return lines


def _verdicts(grading: Grading, by: Mapping[str, list[Facts]], judge_lines: Sequence) -> list[str]:
    graded = grading.graded

    def of(layout: str, test) -> str:
        return str(sum(1 for one in graded if one.answer.layout == layout and test(one)))

    def has(mark: str):
        return lambda one: one.picked is not None and mark in one.picked.split()

    rows = [
        ("answers", lambda one: True),
        ("graded by hand: (a) the rule and the judge differ", has(DIFFER)),
        ("graded by hand: (b) the judge says wrong, or has no verdict", has(DOUBTED)),
        ("graded by hand: (a) or (b)", lambda one: has(DIFFER)(one) or has(DOUBTED)(one)),
        ("graded by hand: (c) drawn from the others", has(SAMPLED)),
        ("graded by hand: left over, and graded after (c)", has(REST)),
        ("the verdict is the grade by hand", lambda one: one.hand is not None),
        ("the verdict is the judge's", lambda one: one.hand is None),
    ]
    if not any(has(REST)(one) for one in graded):
        rows = [row for row in rows if "left over" not in row[0]]
    cells = [[name, *(of(layout, test) for layout in LAYOUTS)] for name, test in rows]
    # A run without an answer is on no sheet, and wrong whatever it would have said.
    without = [str(sum(1 for f in by[layout] if not f.answered)) for layout in LAYOUTS]
    lines = _table(["", *LAYOUTS], [*cells, ["runs without an answer: wrong", *without]])

    # --- the rule and the judge, on every answer
    said = Counter((one.answer.rule, one.answer.judge) for one in graded)
    rules = [rule for rule in (RIGHT, WRONG, BY_HAND) if any(r == rule for r, _ in said)]
    lines += ["", "The rule of `eval/grade.py` and the judge, on every answer:", ""]
    lines += _table(
        ["rule", "judge right", "judge wrong", "no verdict"],
        (
            [rule, *(str(said[(rule, verdict)]) for verdict in (RIGHT, WRONG, None))]
            for rule in rules
        ),
    )

    # --- (c), and the rule of three
    lines += [
        "",
        f"The grade by hand differs from the verdict of the judge in {grading.differing} of the "
        f"{grading.sampled} answer(s) of (c). "
        + (
            f"That is {WIDEN_AT} or more: every answer is graded by hand, and the grades by "
            "hand are the verdicts."
            if grading.widened
            else f"That is fewer than {WIDEN_AT}: an answer that was not graded by hand has the "
            "verdict of the judge."
        ),
    ]

    # --- the grades by hand against the two others
    by_hand = [one for one in graded if one.hand is not None]
    lines += ["", "The grades by hand, against the judge and against the rule:", ""]
    head = ["by hand", "answers", "judge right", "judge wrong", "no verdict"]
    head += [f"rule {rule}" for rule in rules]
    lines += _table(
        head,
        (
            [
                grade,
                str(sum(1 for one in by_hand if one.hand == grade)),
                *(
                    str(sum(1 for one in by_hand if one.hand == grade and one.answer.judge == v))
                    for v in (RIGHT, WRONG, None)
                ),
                *(
                    str(sum(1 for one in by_hand if one.hand == grade and one.answer.rule == r))
                    for r in rules
                ),
            ]
            for grade in (RIGHT, WRONG)
        ),
    )
    apart = [one for one in by_hand if one.hand != one.answer.judge]
    lines += ["", "Answers whose grade by hand is not the verdict of the judge:", ""]
    if not apart:
        lines += ["None."]
    for one in apart:
        answer = one.answer
        lines.append(
            f"- {answer.question.id} {answer.layout} (number {answer.number}, {one.picked}): "
            f"rule {answer.rule}, judge {answer.judge or 'no verdict'}, by hand {one.hand}"
        )

    sums = judging.totals(judge_lines)
    money = "no price is known for its model" if sums["cost"] is None else f"${sums['cost']:.2f}"
    lines += [
        "",
        f"The judge: {sums['requests']} requests with a reply; cost computed from their usage: "
        f"{money}.",
    ]
    return lines


def _hypotheses(pairs: Sequence[Pair], questions: int) -> list[str]:
    fewer, more, equal = h1(pairs)
    lines = ["## H1: tool result characters, question by question", ""]
    lines += [
        f"Of the {len(pairs)} question(s) with a run of both layouts, the staged run was given "
        f"fewer characters in {fewer}, more in {more}, and as many in {equal}.",
        f"One-sided exact sign test, ties left out: p = {sign_test(fewer, more):.4g}"
        f" (n = {fewer + more}).",
    ]
    both, staged_only, flat_only, neither = h2(pairs)
    estimate, low, high = adjusted_wald(staged_only, flat_only, len(pairs))
    lines += ["", "## H2: answers, question by question", ""]
    lines += _table(
        ["", "flat right", "flat wrong"],
        [
            ["staged right", str(both), str(staged_only)],
            ["staged wrong", str(flat_only), str(neither)],
        ],
    )
    lines += [
        "",
        f"{len(pairs)} question(s): right in staged only {staged_only}, in flat only {flat_only}.",
        f"Difference of the rates of right answers, staged less flat: {_points(estimate)} points, "
        f"95% interval {_points(low)} to {_points(high)} (adjusted Wald, `eval/paired.py`).",
        f"Read against the margin of {MARGIN * 100:.0f} points: {READINGS[reading(low, high, MARGIN)]}.",
    ]
    if len(pairs) != questions:
        lines += ["", f"{questions - len(pairs)} question(s) of the file are in neither (below)."]
    return lines


def _grouped(
    name: str, groups: Sequence[tuple[str, list[Facts]]], count: Mapping[str, int]
) -> list[str]:
    """The runs in which the anchor was given and the answers that are right, group by group."""
    head = [name, "questions"]
    for layout in LAYOUTS:
        head += [f"{layout}: the anchor was given", f"{layout}: right"]
    rows = []
    for label, runs in groups:
        row = [label, str(count[label])]
        for layout in LAYOUTS:
            own = [f for f in runs if f.layout == layout]
            row += [
                _of(sum(1 for f in own if _given(f)), len(own)),
                _of(sum(1 for f in own if f.verdict == RIGHT), len(own)),
            ]
        rows.append(row)
    return _table(head, rows)


def _ranks(runs: Sequence[Facts]) -> str:
    """The ranks at which a search first listed the paper, as "rank: runs"."""
    ranks = Counter(
        hit[1]
        for f in runs
        for key in to_find(f.question)
        if (hit := f.graded.search.first_hit.get(key))
    )
    return ", ".join(f"{rank}: {ranks[rank]}" for rank in sorted(ranks)) or "-"


def _searched(questions: Sequence[Question], facts: Sequence[Facts]) -> list[str]:
    """The questions that a search has to find the paper of, beside those of named_first."""
    kinds = in_order([q.type for q in questions if to_find(q) or q.type == NAMED_FIRST])
    rows = []
    for kind in kinds:
        for layout in LAYOUTS:
            runs = [f for f in facts if f.question.type == kind and f.layout == layout]
            need = [f for f in runs if to_find(f.question)]
            listed = [
                f
                for f in need
                if all(f.graded.search.first_hit.get(key) for key in to_find(f.question))
            ]
            same = [
                f
                for f in listed
                if all(f.graded.search.first_hit[key][2] for key in to_find(f.question))
            ]
            rows.append(
                [
                    kind,
                    layout,
                    str(len(runs)),
                    _of(len(listed), len(need)) if need else "-",
                    str(len(same)) if need else "-",
                    _ranks(need) if need else "-",
                    _of(sum(1 for f in runs if _given(f)), len(runs)),
                    _of(sum(1 for f in runs if f.verdict == RIGHT), len(runs)),
                ]
            )
    head = [
        "kind",
        "layout",
        "runs",
        "a search listed the paper",
        "in the version of the question",
        "at rank: runs",
        "the anchor was given",
        "right",
    ]
    return _table(head, rows)


def report(
    questions: Sequence[Question],
    facts: Sequence[Facts],
    state: State,
    grading: Grading,
    judge_lines: Sequence,
    header: Sequence[str],
) -> str:
    by = {layout: [f for f in facts if f.layout == layout] for layout in LAYOUTS}
    pairs = pairs_of(questions, facts)
    lines = ["# Report of an evaluation with one run for a cell", "", *header, ""]

    lines += ["## The questions", "", *_questions_table(questions)]
    lines += ["", "## By layout", "", *_by_layout(by)]
    lines += ["", "## The verdicts, and where they come from", ""]
    lines += _verdicts(grading, by, judge_lines)
    lines += ["", *_hypotheses(pairs, len(questions))]

    # --- the questions that are in neither
    lines += ["", "## Questions left out of H1 and H2", ""]
    out = left_out(questions, state)
    if not out:
        lines += ["None: every question has a run of both layouts that counts."]
    for name, layouts in out:
        lines.append(
            f"- {name}: no {' and no '.join(layouts)} run that counts; given up after {TRIES} "
            "spoilt runs of the cell"
        )

    # --- by kind and by archive
    kinds = in_order([q.type for q in questions])
    count = Counter(q.type for q in questions)
    lines += ["", "## By kind", ""]
    lines += _grouped(
        "kind", [(k, [f for f in facts if f.question.type == k]) for k in kinds], count
    )
    missed = Counter(f.question.type for f in by[STAGED] if f.graded.access.met is False)
    lines += [
        "",
        f"Staged runs that were not given the anchor: {sum(missed.values())}"
        + (
            " (" + ", ".join(f"{kind} {missed[kind]}" for kind in kinds if missed[kind]) + ")"
            if missed
            else ""
        )
        + ". Expected beforehand: they gather in own_text and later_piece.",
    ]
    archives = sorted({archive_of(q) for q in questions} - {None})
    if archives:
        count = Counter(archive_of(q) for q in questions)
        groups = [(a, [f for f in facts if archive_of(f.question) == a]) for a in archives]
        lines += ["", "## By archive", "", *_grouped("archive", groups, count)]

    if any(to_find(q) for q in questions):
        lines += ["", "## The questions that do not name their paper by its identifier", ""]
        lines += _searched(questions, facts)

    lines += ["", "## Answers that are right although the anchor was not given", ""]
    without = [f for f in facts if _right_without(f)]
    if not without:
        lines += ["None."]
    for f in without:
        had = "was" if not set(f.question.gold_papers) - f.papers_read else "was not"
        lines.append(
            f"- {f.question.id} {f.layout} ({f.question.type}): text of its paper {had} given"
        )

    # --- why wrong
    classes = sorted({f.failure for f in facts if f.failure})
    lines += ["", "## Why runs were wrong", ""]
    if classes:
        lines += _table(
            ["", *LAYOUTS],
            (
                [name, *(str(sum(1 for f in by[l] if f.failure == name)) for l in LAYOUTS)]
                for name in classes
            ),
        )
    else:
        lines += ["No run is wrong."]
    errors = sorted({kind for f in facts for kind in f.errors})
    if errors:
        lines += ["", "Tool calls that ended in an error, by kind:", ""]
        lines += _table(
            ["", *LAYOUTS],
            (
                [kind, *(str(sum(f.errors.count(kind) for f in by[l])) for l in LAYOUTS)]
                for kind in errors
            ),
        )

    # --- question by question
    runs = by_question(facts)

    def verdict(run: Facts | None) -> str:
        if run is None:
            return "-"
        return run.verdict if run.answered else "no answer"

    def anchor(run: Facts | None) -> str:
        if run is None:
            return "-"
        met = run.graded.access.met
        return "?" if met is None else f"response {run.graded.access.turn}" if met else "no"

    rows = []
    for q in questions:
        both = [runs.get((q.id, layout)) for layout in LAYOUTS]
        rows.append(
            [
                q.id,
                q.type,
                archive_of(q) or "-",
                *(verdict(run) for run in both),
                *("-" if run is None else _number(run.chars) for run in both),
                *(anchor(run) for run in both),
            ]
        )
    lines += ["", "## Question by question", ""]
    lines += _table(
        [
            "question",
            "kind",
            "archive",
            *(f"{layout}" for layout in LAYOUTS),
            *(f"{layout} chars" for layout in LAYOUTS),
            *(f"{layout} anchor" for layout in LAYOUTS),
        ],
        rows,
    )
    lines += ["", '"-" marks a cell without a run that counts.']

    # --- runs that do not count
    spoilt = Counter(
        (attempt.run.get("toolset"), attempt.spoilt)
        for cell in state.cells
        for attempt in state.spoilt(cell)
    )
    lines += ["", "## Runs that do not count", ""]
    if spoilt:
        lines += _table(
            ["spoilt because", *LAYOUTS],
            (
                [why, *(str(spoilt[(l, why)]) for l in LAYOUTS)]
                for why in sorted({why for _, why in spoilt})
            ),
        )
        lines += [""]
    spoilt_cost = sum(
        cost_of(a.turns, (a.run.get("model") or {}).get("model")) or 0.0
        for cell in state.cells
        for a in state.spoilt(cell)
    )
    given_up = [cell for cell in state.cells if not state.done(cell) and not state.to_run(cell)]
    lines += [
        f"Spoilt runs kept: {sum(spoilt.values())}, cost computed ${spoilt_cost:.2f}. "
        f"Cells given up after {TRIES} spoilt runs: {len(given_up)}"
        + (f" ({', '.join(str(c) for c in given_up)})" if given_up else "")
        + ".",
    ]
    return "\n".join(lines) + "\n"


# --- the command ----------------------------------------------------------------------------


def main(argv: Sequence[str] | None = None, source: PaperSource | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m hepph_paper_miner.eval.second",
        description="Write the report of an evaluation with one run for a cell, from its "
        "records, the judge's record and the sheets graded by hand.",
    )
    parser.add_argument("--questions", type=Path, required=True, help="the question file")
    parser.add_argument("--runs", type=Path, required=True, help="folder of the public records")
    parser.add_argument("--sheet", type=Path, required=True, help="the sheet of all answers")
    parser.add_argument("--key", type=Path, required=True, help="the key of that sheet")
    parser.add_argument("--judge", type=Path, required=True, help="the judge's record of it")
    parser.add_argument("--hand-sheet", type=Path, required=True, help="the sheet graded by hand")
    parser.add_argument("--hand-key", type=Path, required=True, help="its key")
    parser.add_argument("--rest-sheet", type=Path, help="the sheet of the answers that were left")
    parser.add_argument("--rest-key", type=Path, help="its key")
    parser.add_argument("--out", type=Path, help="write the report here (default: print it)")
    parser.add_argument(
        "--conditions",
        choices=sorted(CONDITIONS),
        default=CONDITIONS_NAME,
        help="what the records are held against (default: %(default)s)",
    )
    arguments = parser.parse_args(argv)
    if (arguments.rest_sheet is None) != (arguments.rest_key is None):
        parser.error("--rest-sheet and --rest-key go together")

    from hepph_paper_miner.agent.origin import file_digest

    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="backslashreplace")
    try:
        questions = load_questions(arguments.questions)
    except (OSError, QuestionFileError) as error:
        print(f"cannot read the questions: {error}", file=sys.stderr)
        return 2
    try:
        grading, attempts, state = grading_by_hand.read_grading(
            arguments.questions,
            arguments.runs,
            arguments.sheet,
            arguments.key,
            arguments.judge,
            arguments.hand_sheet,
            arguments.hand_key,
            arguments.rest_sheet,
            arguments.rest_key,
        )
        judge_head, judge_lines, _ = judging.read_record(arguments.judge)
    except (OSError, QuestionFileError, SheetError, JudgeError, HandError) as error:
        print(f"refused: {error}", file=sys.stderr)
        return 1

    if source is None:
        source = _arxiv()
    by_id = {q.id: q for q in questions}
    wanted = dict.fromkeys(
        [key for a in attempts for key in by_id[a.run["question_id"]].gold_papers]
        + [read.arxiv_id for a in attempts for read in _reads(Record(a.run, a.turns, a.end))]
    )
    papers: dict[str, Paper] = {}
    for key in wanted:
        try:
            papers[key] = source.paper(parse_arxiv_id(key))
        except SourceError as error:
            print(f"cannot read {key}: {error}", file=sys.stderr)
    places = {key: Places(paper) for key, paper in papers.items()}
    # facts_of takes the verdict on an answer from what it is given as the grades by hand.
    verdicts = {run_id: SimpleNamespace(grade=v) for run_id, v in grading.verdicts().items()}
    facts = [facts_of(a, by_id[a.run["question_id"]], papers, places, verdicts) for a in attempts]

    commits = Counter((a.run.get("code") or {}).get("commit") for a in attempts)
    held = CONDITIONS[arguments.conditions]
    off = [(a, found) for a in attempts if (found := differences(a.run, a.end, held))]
    by_hand = sum(1 for one in grading.graded if one.hand is not None)
    header = [
        f"Questions: {arguments.questions.name}, SHA-256 {file_digest(arguments.questions)}",
        f"Records: {arguments.runs.as_posix()}; code "
        + ", ".join(f"{str(c)[:7]} ({n} runs)" for c, n in commits.most_common()),
        f"Held against the conditions {arguments.conditions!r} (conditions.py): "
        + (
            "no record differs"
            if not off
            else f"{len(off)} record(s) differ, first {off[0][0].path.name}: {off[0][1][0]}"
        ),
        f"Judge: {arguments.judge.name}, `{judge_head['judge_version']}`, texts sha256 "
        f"`{judge_head['texts_sha256']}`, {judge_head['repeats']} requests for an answer",
        f"Verdicts: {by_hand} by hand and {len(grading.graded) - by_hand} of the judge on "
        f"{len(grading.graded)} answer(s); {len(attempts) - len(grading.graded)} run(s) without "
        "an answer are wrong",
    ]
    text = report(questions, facts, state, grading, judge_lines, header)
    if arguments.out:
        arguments.out.parent.mkdir(parents=True, exist_ok=True)
        arguments.out.write_text(text, encoding="utf-8", newline="\n")
        print(f"the report is {arguments.out}")
    else:
        print(text, end="")
    return 0


if __name__ == "__main__":
    sys.exit(main())
