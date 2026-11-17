"""The report of the evaluation: what the two layouts did, question by question.

    uv run python -m hepph_paper_miner.eval.report --questions eval_data/questions_eval.jsonl \
        --runs results/runs/eval --sheet grading.csv --key runs_private/grading-key.csv \
        --out results/report.md

It reads the records of the runs that count (run.py), grades each of them with grade.py
(search, access, citation, and what the rule says of the answer), takes the verdict on
each answer from the sheet a person graded (sheet.py), and writes the tables in
Markdown. A run without an answer is wrong. Without a sheet, and for rows not graded
yet, there is no verdict, and everything else is written.

The papers are read as grade.py reads them: through the folder of downloads, asking
arXiv for one that is not in it. Every paper a run read is needed, not only the papers
of its question, because the text a run was given is counted once on the scale of each
paper.

What is counted for a run:

    chars          the characters of every tool result, as the model received them
    input tokens   all of its input: new, written to the cache, and read from it
    new text       the characters of paper text it was given, each character once
    repeat reads   calls that gave it no character it had not been given already
    cost           from the usage of every response, at the prices in PRICES

H1 is held up question by question: the median chars of the runs of each layout. The
number of questions whose staged median is the lower is tested with a one-sided sign
test, with ties left out. H2 is a table, question by question: a layout answers a
question right when more than half of its runs that count are right (two of three).
"""

from __future__ import annotations

import argparse
import math
import statistics
import sys
from collections import Counter
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from hepph_paper_miner.eval.conditions import differences
from hepph_paper_miner.eval.grade import Grade, Places, Record, _add, _covers, _reads, grade
from hepph_paper_miner.eval.questions import Question, QuestionFileError, load_questions
from hepph_paper_miner.eval.run import LAYOUTS, REPEATS, Attempt, State
from hepph_paper_miner.eval.sheet import HandGrade, SheetError, counted_attempts, read_grades
from hepph_paper_miner.sources.base import Paper, PaperSource, SourceError, parse_arxiv_id

# US dollars for a million tokens (platform.claude.com/docs/en/about-claude/pricing,
# read 2026-11-17). A cache write that lasts five minutes is what --cache asks for.
PRICES: dict[str, dict[str, float]] = {
    "claude-sonnet-5-5": {
        "input": 2.00,
        "cache_write_5m": 2.50,
        "cache_write_1h": 4.00,
        "cache_read": 0.10,
        "output": 10.00,
    },
}

RIGHT, WRONG = "right", "wrong"


def cost_of(turns: Iterable[Mapping], model: str | None) -> float | None:
    """What the responses of a run cost, from their usage; None for a model without prices."""
    price = PRICES.get(model or "")
    if price is None:
        return None
    total = 0.0
    for turn in turns:
        usage = turn.get("usage") or {}
        split = usage.get("cache_creation") or {}
        short = split.get("ephemeral_5m_input_tokens")
        long = split.get("ephemeral_1h_input_tokens")
        if short is None and long is None:  # a usage without the split: the cache --cache asks for
            short, long = usage.get("cache_creation_input_tokens") or 0, 0
        total += (
            (usage.get("input_tokens") or 0) * price["input"]
            + (short or 0) * price["cache_write_5m"]
            + (long or 0) * price["cache_write_1h"]
            + (usage.get("cache_read_input_tokens") or 0) * price["cache_read"]
            + (usage.get("output_tokens") or 0) * price["output"]
        )
    return total / 1_000_000


def text_given(record: Record, places: Mapping[str, Places]) -> tuple[int, int, bool]:
    """The characters of paper text a run was given, each once; the calls that gave nothing new.

    A stretch of a section is put on the scale of its top-level section, as grade.py puts
    it, so reading "6" after "6.3" gives only what "6" holds besides "6.3". The flat layout
    reads the whole text, on a scale of its own. The last value says whether a paper was
    missing, so that its sections were counted on their own scales and may overlap.
    """
    covered: dict[tuple[str, str | None], list[tuple[int, int]]] = {}
    repeats, rough = 0, False
    for read in _reads(record):
        start, stop, scale = read.start, read.stop, read.section_id
        if read.section_id is not None:
            place = places.get(read.arxiv_id)
            if place is None:
                rough = True
            else:
                scale, start, stop = place.read(read.section_id, read.start, read.stop)
        stretches = covered.setdefault((read.arxiv_id, scale), [])
        if stop > start and _covers(stretches, start, stop):
            repeats += 1
        _add(stretches, start, stop)
    new = sum(high - low for stretches in covered.values() for low, high in stretches)
    return new, repeats, rough


def sign_test(lower: int, higher: int) -> float:
    """One-sided p of a sign test: the chance of `lower` or more of n when either is even."""
    n = lower + higher
    return sum(math.comb(n, k) for k in range(lower, n + 1)) / 2**n


def to_find(question: Question) -> tuple[str, ...]:
    """The papers of a question that it does not name, so that a search has to find them."""
    return tuple(
        key for key in question.gold_papers if parse_arxiv_id(key).base not in question.question
    )


@dataclass(frozen=True)
class Facts:
    """What the report uses of one run that counts."""

    attempt: Attempt
    question: Question
    graded: Grade
    verdict: str | None  # RIGHT or WRONG; None: answered, and not graded by hand yet
    chars: int
    input_tokens: int
    output_tokens: int
    calls: int
    turns: int
    cost: float | None
    new_text: int
    repeat_reads: int
    rough: bool  # new_text may count a character twice (a paper was missing)
    errors: tuple[str, ...]  # the kind of every tool call that ended in an error
    papers_read: frozenset[str]

    @property
    def layout(self) -> str:
        return self.attempt.run["toolset"]

    @property
    def answered(self) -> bool:
        return bool(self.attempt.end.get("answer"))

    @property
    def failure(self) -> str | None:
        """Why a wrong run was wrong, as far as its record tells it."""
        if self.verdict != WRONG:
            return None
        if not self.answered:
            return f"no answer: {self.graded.reason}"
        if self.graded.access.met:
            return "answered wrong, the passage was given"
        if self.graded.access.met is None:
            return "answered wrong, access cannot be told"
        if set(self.question.gold_papers) - self.papers_read:
            return "answered wrong, a paper of the question was never given"
        return "answered wrong, its paper was given but not the passage"


def facts_of(
    attempt: Attempt,
    question: Question,
    papers: Mapping[str, Paper],
    places: Mapping[str, Places],
    hand: Mapping[str, HandGrade],
) -> Facts:
    record = Record(attempt.run, attempt.turns, attempt.end)
    end = attempt.end
    verdict = WRONG
    if end.get("answer"):
        given = hand.get(attempt.run["run_id"])
        verdict = given.grade if given is not None else None
    new, repeats, rough = text_given(record, places)
    return Facts(
        attempt=attempt,
        question=question,
        graded=grade(record, question, papers),
        verdict=verdict,
        chars=end.get("tool_result_chars") or 0,
        input_tokens=sum(
            end.get(name) or 0
            for name in ("input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens")
        ),
        output_tokens=end.get("output_tokens") or 0,
        calls=end.get("tool_calls") or 0,
        turns=end.get("turns") or 0,
        cost=cost_of(attempt.turns, (attempt.run.get("model") or {}).get("model")),
        new_text=new,
        repeat_reads=repeats,
        rough=rough,
        errors=tuple(
            call.get("error_kind") or "unknown"
            for turn in attempt.turns
            for call in turn.get("tools", ())
            if call.get("status") == "error"
        ),
        papers_read=frozenset(read.arxiv_id for read in _reads(record)),
    )


# --- the tables --------------------------------------------------------------------------


def _number(value: float | int | None) -> str:
    if value is None:
        return "-"
    if isinstance(value, float) and not value.is_integer():
        return f"{value:,.1f}"
    return f"{int(value):,}"


def _median(values: Sequence[float]) -> float | None:
    return statistics.median(values) if values else None


def _spread(values: Sequence[float]) -> str:
    if not values:
        return "-"
    return f"{_number(_median(values))} ({_number(min(values))} to {_number(max(values))})"


def _row(cells: Sequence[str]) -> str:
    return "| " + " | ".join(cells) + " |"


def _table(head: Sequence[str], rows: Iterable[Sequence[str]]) -> list[str]:
    return [_row(head), _row(["---"] * len(head)), *(_row(row) for row in rows)]


def _of(count: int, total: int) -> str:
    return f"{count} / {total}"


def _majority(runs: Sequence[Facts]) -> bool | None:
    """Whether more than half of the runs are right; None while one of them is not graded."""
    if not runs or any(run.verdict is None for run in runs):
        return None
    return 2 * sum(1 for run in runs if run.verdict == RIGHT) > len(runs)


def compare(
    questions: Sequence[Question],
    facts: Sequence[Facts],
    measure: Callable[[Facts], float],
) -> tuple[int, int, int, int]:
    """Questions whose staged median is lower, higher, equal; and those without both layouts."""
    lower = higher = equal = missing = 0
    for question in questions:
        medians = {}
        for layout in LAYOUTS:
            values = [
                measure(f) for f in facts if f.question.id == question.id and f.layout == layout
            ]
            medians[layout] = _median(values)
        staged, flat = medians["staged"], medians["flat"]
        if staged is None or flat is None:
            missing += 1
        elif staged < flat:
            lower += 1
        elif staged > flat:
            higher += 1
        else:
            equal += 1
    return lower, higher, equal, missing


def report(
    questions: Sequence[Question],
    facts: Sequence[Facts],
    state: State,
    header: Sequence[str],
) -> str:
    by = {layout: [f for f in facts if f.layout == layout] for layout in LAYOUTS}
    lines = ["# Report of the evaluation", "", *header, ""]

    # --- by layout
    searched = {q.id for q in questions if to_find(q)}

    def found_all(f: Facts) -> bool:
        return all(f.graded.search.first_hit.get(key) for key in to_find(f.question))

    def column(runs: list[Facts]) -> list[str]:
        answered = [f for f in runs if f.answered]
        need_search = [f for f in runs if f.question.id in searched]
        graded = [f for f in runs if f.verdict is not None]
        per_question = [_majority([f for f in runs if f.question.id == q.id]) for q in questions]
        after = [
            f.graded.access.turns_after for f in runs if f.graded.access.turns_after is not None
        ]
        costs = [f.cost for f in runs if f.cost is not None]
        return [
            str(len(runs)),
            _of(len(answered), len(runs)),
            _of(sum(1 for f in need_search if found_all(f)), len(need_search)),
            _of(sum(1 for f in runs if f.graded.access.met), len(runs)),
            f"{sum(1 for f in answered if f.graded.citation.strict)} / "
            f"{sum(1 for f in answered if f.graded.citation.loose)} of {len(answered)}",
            _of(sum(1 for f in graded if f.verdict == RIGHT), len(graded))
            + ("" if len(graded) == len(runs) else f" ({len(runs) - len(graded)} not graded)"),
            _of(sum(1 for m in per_question if m), sum(1 for m in per_question if m is not None)),
            _spread([f.chars for f in runs]),
            _spread([f.input_tokens for f in runs]),
            _spread([f.new_text for f in runs]),
            _spread([f.calls for f in runs]),
            _spread([f.turns for f in runs]),
            str(sum(f.repeat_reads for f in runs)),
            _number(_median(after)),
            str(sum(1 for f in runs if f.errors)),
            f"${sum(costs):.2f}" if costs else "-",
        ]

    names = [
        "runs that count",
        "answered",
        "1 search listed the paper (questions that do not name it)",
        "2a passage given",
        "2b cited strictly / loosely",
        "3 right, by hand (no answer is wrong)",
        "questions right in more than half of their runs",
        "tool result chars per run, median (range)",
        "input tokens per run, median (range)",
        "new paper text per run, median (range)",
        "tool calls per run, median (range)",
        "turns per run, median (range)",
        "repeat reads, all runs",
        "responses from the passage to the answer, median",
        "runs with a tool error",
        "cost, computed",
    ]
    columns = {layout: column(by[layout]) for layout in LAYOUTS}
    lines += ["## By layout", ""]
    lines += _table(
        ["", *LAYOUTS], ([name, *(columns[l][i] for l in LAYOUTS)] for i, name in enumerate(names))
    )
    rough = sum(1 for f in facts if f.rough)
    if rough:
        lines += [
            "",
            f"New paper text may count a character twice in {rough} run(s): a paper they read could not be read here.",
        ]

    # --- H1
    lower, higher, equal, missing = compare(questions, facts, lambda f: f.chars)
    lines += ["", "## H1: tool result characters, question by question", ""]
    lines += [
        f"The median of the staged runs is lower in {lower} question(s), higher in {higher}, "
        f"equal in {equal}; {missing} without runs of both layouts.",
        f"One-sided sign test, ties left out: p = {sign_test(lower, higher):.4g}"
        f" (n = {lower + higher}).",
    ]
    lower, higher, equal, missing = compare(questions, facts, lambda f: f.input_tokens)
    lines += [
        f"Input tokens, the same way: lower in {lower}, higher in {higher}, equal in {equal}; "
        f"p = {sign_test(lower, higher):.4g}.",
    ]

    # --- H2
    pairs = Counter()
    for q in questions:
        staged = _majority([f for f in by["staged"] if f.question.id == q.id])
        flat = _majority([f for f in by["flat"] if f.question.id == q.id])
        pairs[(staged, flat)] += 1
    lines += ["", "## H2: answers, question by question", ""]
    lines += _table(
        ["", "flat right", "flat wrong"],
        [
            ["staged right", str(pairs[(True, True)]), str(pairs[(True, False)])],
            ["staged wrong", str(pairs[(False, True)]), str(pairs[(False, False)])],
        ],
    )
    open_ = sum(n for (s, f), n in pairs.items() if s is None or f is None)
    if open_:
        lines += ["", f"{open_} question(s) not in the table: a run of theirs is not graded yet."]

    # --- question by question
    rows = []
    for q in questions:
        cells = [q.id, q.type]
        for layout in LAYOUTS:
            runs = [f for f in by[layout] if f.question.id == q.id]
            graded = [f for f in runs if f.verdict is not None]
            right = sum(1 for f in graded if f.verdict == RIGHT)
            cells.append(_of(right, len(runs)) + ("" if len(graded) == len(runs) else " (?)"))
        for layout in LAYOUTS:
            runs = [f for f in by[layout] if f.question.id == q.id]
            cells.append(_number(_median([f.chars for f in runs])))
        for layout in LAYOUTS:
            runs = [f for f in by[layout] if f.question.id == q.id]
            cells.append(_of(sum(1 for f in runs if f.graded.access.met), len(runs)))
        rows.append(cells)
    lines += ["", "## Question by question", ""]
    lines += _table(
        [
            "question",
            "type",
            "staged right",
            "flat right",
            "staged chars",
            "flat chars",
            "staged passage",
            "flat passage",
        ],
        rows,
    )
    lines += [
        "",
        "Chars are the median of the runs of the question; (?) marks a run not graded yet.",
    ]

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
        lines += ["No run is wrong, or none is graded yet."]
    kinds = sorted({kind for f in facts for kind in f.errors})
    if kinds:
        lines += ["", "Tool calls that ended in an error, by kind:", ""]
        lines += _table(
            ["", *LAYOUTS],
            (
                [kind, *(str(sum(f.errors.count(kind) for f in by[l])) for l in LAYOUTS)]
                for kind in kinds
            ),
        )

    # --- the rule and the hand
    lines += ["", "## The rule of grade.py and the grade by hand (answered runs)", ""]
    rules = ("right", "by_hand", "wrong")
    lines += _table(
        ["rule", *(f"{l}: {v}" for l in LAYOUTS for v in (RIGHT, WRONG, "not graded"))],
        (
            [
                rule,
                *(
                    str(
                        sum(
                            1
                            for f in by[l]
                            if f.answered and f.graded.answer.rule == rule and f.verdict == v
                        )
                    )
                    for l in LAYOUTS
                    for v in (RIGHT, WRONG, None)
                ),
            ]
            for rule in rules
        ),
    )

    # --- runs that do not count
    spoilt = Counter(
        (attempt.run.get("toolset"), attempt.spoilt)
        for cell in state.cells
        for attempt in state.spoilt(cell)
    )
    given_up = [cell for cell in state.cells if not state.done(cell) and not state.to_run(cell)]
    waiting = [cell for cell in state.cells if state.to_run(cell)]
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
    lines += [
        f"Spoilt runs kept: {sum(spoilt.values())}, cost computed ${spoilt_cost:.2f}. "
        f"Cells given up after three spoilt runs: {len(given_up)}"
        + (f" ({', '.join(str(c) for c in given_up)})" if given_up else "")
        + f". Cells still to run: {len(waiting)}.",
    ]
    return "\n".join(lines) + "\n"


# --- the command -------------------------------------------------------------------------


def main(argv: Sequence[str] | None = None, source: PaperSource | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m hepph_paper_miner.eval.report",
        description="Write the report of the evaluation from its records and the graded sheet.",
    )
    parser.add_argument("--questions", type=Path, required=True, help="the question file")
    parser.add_argument("--runs", type=Path, required=True, help="folder of the public records")
    parser.add_argument("--sheet", type=Path, help="the graded sheet (sheet.py)")
    parser.add_argument("--key", type=Path, help="the key of the sheet")
    parser.add_argument("--out", type=Path, help="write the report here (default: print it)")
    parser.add_argument(
        "--repeats",
        type=int,
        default=REPEATS,
        help="repetitions of the plan (default: %(default)s)",
    )
    arguments = parser.parse_args(argv)
    if (arguments.sheet is None) != (arguments.key is None):
        parser.error("--sheet and --key go together")

    from hepph_paper_miner.agent.origin import file_digest

    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="backslashreplace")
    try:
        questions = load_questions(arguments.questions)
    except (OSError, QuestionFileError) as error:
        print(f"cannot read the questions: {error}", file=sys.stderr)
        return 2
    digest = file_digest(arguments.questions)
    try:
        attempts, state = counted_attempts(questions, arguments.runs, digest, arguments.repeats)
        hand: dict[str, HandGrade] = {}
        if arguments.sheet is not None:
            hand = {g.run_id: g for g in read_grades(arguments.sheet, arguments.key)}
            answered = {a.run["run_id"] for a in attempts if a.end.get("answer")}
            if set(hand) != answered:
                raise SheetError(
                    f"the key holds {len(set(hand) - answered)} run(s) that do not count with an "
                    f"answer, and misses {len(answered - set(hand))} that do: a sheet of other runs"
                )
    except (SheetError, OSError) as error:
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
    facts = [facts_of(a, by_id[a.run["question_id"]], papers, places, hand) for a in attempts]

    commits = Counter((a.run.get("code") or {}).get("commit") for a in attempts)
    off = [(a, differences(a.run, a.end)) for a in attempts]
    off = [(a, found) for a, found in off if found]
    graded = sum(1 for f in facts if f.answered and f.verdict is not None)
    header = [
        f"Questions: {arguments.questions.name}, SHA-256 {digest}",
        f"Records: {arguments.runs.as_posix()}; code "
        + ", ".join(f"{str(c)[:7]} ({n} runs)" for c, n in commits.most_common()),
        "Held against the conditions (conditions.py): "
        + (
            "no record differs"
            if not off
            else f"{len(off)} record(s) differ, first {off[0][0].path.name}: {off[0][1][0]}"
        ),
        f"Answers graded by hand: {graded} of {sum(1 for f in facts if f.answered)}"
        + ("" if hand else " (no sheet given)"),
    ]
    text = report(questions, facts, state, header)
    if arguments.out:
        arguments.out.parent.mkdir(parents=True, exist_ok=True)
        arguments.out.write_text(text, encoding="utf-8", newline="\n")
        print(f"the report is {arguments.out}")
    else:
        print(text, end="")
    return 0


def _arxiv() -> PaperSource:
    """The papers as the runs read them: from arXiv, through the folder of downloads."""
    from hepph_paper_miner import __version__
    from hepph_paper_miner.http import Fetcher, default_cache_dir
    from hepph_paper_miner.server import SERVER_NAME
    from hepph_paper_miner.sources.arxiv import ArxivSource

    return ArxivSource(Fetcher(default_cache_dir(), user_agent=f"{SERVER_NAME}/{__version__}"))


if __name__ == "__main__":
    sys.exit(main())
