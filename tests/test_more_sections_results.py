"""What was run with parser 5: the records, and what is said of them.

results/runs/more-sections/README.md is two texts. The first is a plan, pushed in 44bca1f
before any run with parser 5: six questions about papers that the two parsers split
differently, asked by the last commit with parser 4 and by the code with parser 5; the
development questions again; and the sample of the survey split again. The second,
below it, says what came back on 2026-11-25. The folder holds the public records of the
three sets of runs and what was made from them the day after: for each set the sheet of
its answers, its key and the record of the judge on that sheet; for the two sides of
the six questions a report each; for the development runs the text of eval.regress.

These tests hold the files against each other, against the question files and the
conditions, and hold up what the second text and the README of the repository say of
them. How each count is read was fixed in the plan, and a test names the reading where
it applies it. tests/test_section_questions.py holds the plan to the commit that brought
it, and tests/test_survey_parser5.py the sample that was split again.

No network and no LLM. The six papers are not kept here. So in which runs a passage was
given cannot be worked out again: those counts are held against the two reports, which
were written on the computer that has the papers, and everything else against the
records.
"""

import hashlib
import json
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path
from statistics import median

import pytest
from test_asking_again_results import VERDICT, lines_that_need_no_other_paper
from test_results import cost, own_paper, read_csv
from test_section_questions import LEFT_OUT, PAPERS

from hepph_paper_miner.agent.origin import file_digest
from hepph_paper_miner.eval import judge, regress, report
from hepph_paper_miner.eval.agree import judged
from hepph_paper_miner.eval.conditions import (
    ASKING_AGAIN,
    CONDITIONS,
    EVALUATION,
    MORE_SECTIONS,
    differences,
)
from hepph_paper_miner.eval.grade import BY_HAND, RIGHT, Record, grade_answer
from hepph_paper_miner.eval.questions import load_questions
from hepph_paper_miner.eval.run import LAYOUTS, Attempt, Cell, attempts_in, counted, plan
from hepph_paper_miner.eval.sheet import Row, read_grades, read_key, write_key, write_sheet
from hepph_paper_miner.sources.fixture import FixtureSource
from hepph_paper_miner.survey.run import OK, read_outcomes, tally

ROOT = Path(__file__).parent.parent
RUNS = ROOT / "results" / "runs"
HERE = RUNS / "more-sections"
README = HERE / "README.md"
DEV = ROOT / "eval_data" / "questions_dev.jsonl"
SECTIONS = {
    "before": ROOT / "eval_data" / "questions_sections_parser4.jsonl",
    "after": ROOT / "eval_data" / "questions_sections_parser5.jsonl",
}
DEV_BEFORE = RUNS / "asking-again" / "dev-after"  # the thirty runs of 2026-11-23
SPLIT_AGAIN = ROOT / "results" / "survey" / "outcomes-parser5.jsonl"

# The commit that brought the plan, whose code has parser 5; the last commit with parser 4;
# and the commit that made the development runs of 2026-11-23.
PLANNED, LAST_OF_4, DEV_BEFORE_CODE = "44bca1f", "e7e9576", "0af1c02"

# folder: the question file, the commit, the conditions of its code, the other of the two
# sets and what a record says held against it, the records, and when they were made (UTC)
_OF_4 = (ASKING_AGAIN, MORE_SECTIONS, "a result came from parser '4', not '5'")
_OF_5 = (MORE_SECTIONS, ASKING_AGAIN, "a result came from parser '5', not '4'")
SETS = {
    "sections-before": (SECTIONS["before"], LAST_OF_4, *_OF_4, 36, ("10:28", "10:34")),
    "sections-after": (SECTIONS["after"], PLANNED, *_OF_5, 36, ("10:34", "10:40")),
    "dev-after": (DEV, PLANNED, *_OF_5, 30, ("10:40", "10:46")),
}
# The files made from a folder of records begin with these words.
STEM = {
    "sections-before": "sections-before",
    "sections-after": "sections-after",
    "dev-after": "dev",
}

SIDES = ("before", "after")
QUESTIONS = tuple(PAPERS)
LETTERS = tuple(name for name in QUESTIONS if name != LEFT_OUT)  # the five cut at their titles

# Rows of the table "By layout" of a report that are counted over the text of the papers.
OVER_THE_PAPERS = (
    "2a passage given",
    "new paper text per run",
    "repeat reads",
    "responses from the passage to the answer",
)


def records(folder: str) -> list[Attempt]:
    """Every record of a folder, oldest first (a run id begins with the time of its start)."""
    found = [attempt for tried in attempts_in(HERE / folder).values() for attempt in tried]
    return sorted(found, key=lambda attempt: attempt.run["run_id"])


def that_count(folder: str | Path) -> dict[Cell, Attempt]:
    return counted(attempts_in(HERE / folder))


def side(name: str) -> dict[Cell, Attempt]:
    """The runs of the six questions on one side."""
    return that_count(f"sections-{name}")


def of(runs: dict[Cell, Attempt], question_id: str, layout: str) -> list[Attempt]:
    """The runs of one question with one layout, by repetition."""
    found = [
        (cell.repeat, attempt)
        for cell, attempt in runs.items()
        if (cell.question_id, cell.toolset) == (question_id, layout)
    ]
    return [attempt for _, attempt in sorted(found, key=lambda pair: pair[0])]


def results(attempt: Attempt, tool: str | None = None) -> list[dict]:
    """What a record keeps of the calls to the tools of the server, in the order they were made."""
    return [
        call
        for turn in attempt.turns
        for call in turn["tools"]
        if call["name"] != "submit_answer" and tool in (None, call["name"])
    ]


def reads(attempt: Attempt) -> list[tuple[str, int, int, int]]:
    """Every read of a section that came back: the section, where it began and ended, its size."""
    lines = [call["first_line"] for call in results(attempt, "read_section")]
    return [(line["section_id"], line["start"], line["stop"], line["chars"]) for line in lines]


def chars(attempts: list[Attempt]) -> float:
    return median(attempt.end["tool_result_chars"] for attempt in attempts)


def section_of(name: str) -> dict[str, str]:
    """For each of the six questions: the section its passage stands in on one side."""
    found = {}
    for question in load_questions(SECTIONS[name]):
        (found[question.id],) = {item.section_id for item in question.evidence}
    return found


def flat(text: str) -> str:
    """A text with every run of white space as one blank, as a sentence is looked for."""
    return " ".join(text.split())


def plan_text() -> str:
    """The first text of the README of the folder: the plan, as it is typed."""
    text, heading, _ = README.read_text(encoding="utf-8").partition("\n# What came back\n")
    assert heading
    return text


def came_back() -> str:
    """The second text of that README: what came back, as it is typed."""
    _, heading, text = README.read_text(encoding="utf-8").partition("\n# What came back\n")
    assert heading
    return text


def table_rows(text: str, after: str, first_cell: str = "sec-") -> list[str]:
    """The rows of the first table that follows a line of a text."""
    rest = text[text.index(after) :]
    rows = []
    for line in rest.splitlines()[1:]:
        if line.startswith("|"):
            rows.append(line)
        elif rows:
            break
    return [row for row in rows if row.startswith(f"| {first_cell}")]


def report_of(name: str) -> dict[str, list[str]]:
    """The table "Question by question" of the report of one side, row by row.

    A row is the question, its type, the answers right with each layout, the characters
    with each layout, and the runs in which the passage was given with each layout.
    """
    text = (HERE / f"sections-{name}-report.md").read_text(encoding="utf-8")
    rows = {}
    for line in text.splitlines():
        cells = [cell.strip() for cell in line.strip("|").split("|")]
        if cells[0] in QUESTIONS:
            rows[cells[0]] = cells
    assert list(rows) == list(QUESTIONS)
    return rows


def given(name: str, layout: str) -> dict[str, int]:
    """For each question: the runs of a layout in which the passage was given, by the report."""
    column = {"staged": 6, "flat": 7}[layout]
    found = {}
    for question_id, cells in report_of(name).items():
        count, _, runs = cells[column].partition(" / ")
        assert runs == "3"
        found[question_id] = int(count)
    return found


def by_the_judge(stem: str) -> dict[int, tuple[str, ...]]:
    """What the judge said of each row of a sheet, request by request."""
    head, lines, _ = judge.read_record(HERE / f"{stem}-j2.jsonl")
    said = judged(lines, head["repeats"])
    return {int(item.removeprefix("sheet-")): one.verdicts for item, one in said.items()}


def verdicts(name: str) -> dict[Cell, str]:
    """The verdict on every answer of a side, as the plan has it.

    The grade the maintainer wrote on the sheet where there is one, and elsewhere what
    more than half of the three requests of the judge said.
    """
    stem = f"sections-{name}"
    said = by_the_judge(stem)
    found = {}
    for row in read_grades(HERE / f"{stem}-sheet.csv", HERE / f"{stem}-key.csv"):
        cell = Cell(row.question_id, row.toolset, row.repeat)
        found[cell] = row.grade or judge.verdict_of(said[row.number])
    return found


def without_the_papers(text: str) -> list[str]:
    """The lines of a report that can be written without any of the six papers."""
    lines = []
    for line in text.splitlines():
        cells = [cell.strip() for cell in line.strip("|").split("|")]
        if not line or cells[0].startswith(OVER_THE_PAPERS):
            continue
        if line.startswith("New paper text may count a character twice"):
            continue  # the note that a paper was missing, which is the case here only
        if cells[0] in QUESTIONS:
            line = " | ".join(cells[:-2])  # without "staged passage" and "flat passage"
        lines.append(line)
    return lines


# --- the records --------------------------------------------------------------------------


@pytest.mark.parametrize("folder", SETS)
def test_a_set_is_the_plan_of_its_command_under_the_conditions_of_its_code(folder):
    file, commit, conditions, other, parted_by, number, (first, last) = SETS[folder]
    found = records(folder)
    assert len(list((HERE / folder).glob("*.jsonl"))) == len(found) == number
    assert all(a.path.name == a.run["run_id"] + ".jsonl" and a.end is not None for a in found)
    # Nothing spoilt a run, so the records are the cells of the plan, each once, in its order.
    cells = plan([question.id for question in load_questions(file)])
    assert [attempt.cell for attempt in found] == cells == list(that_count(folder))
    digest = file_digest(file)
    for attempt in found:
        run = attempt.run
        assert differences(run, attempt.end, conditions) == [], run["run_id"]
        # The two sets name the same texts. The parser is all that parts them.
        assert differences(run, attempt.end, other) == [parted_by], run["run_id"]
        assert attempt.end["parser_versions"] == [conditions["parser"]]
        assert (run["code"]["commit"][:7], run["code"]["modified"]) == (commit, False)
        assert run["questions"] == {"file": file.name, "sha256": digest}, run["run_id"]
    # One run at a time, on the one day.
    for one, next_one in zip(found, found[1:]):
        assert one.end["ended_at"] <= next_one.run["started_at"], next_one.run["run_id"]
    made = (found[0].run["started_at"], found[-1].end["ended_at"])
    assert all(when.startswith("2026-11-25T") for when in made)
    assert tuple(when[11:16] for when in made) == (first, last)


def test_the_side_before_was_run_first_and_everything_else_right_behind_it():
    # The plan: "The side before is run first and the side after right behind it, on one
    # day." The development runs and the sample of the survey followed in the same way.
    begun = [datetime.fromisoformat(records(folder)[0].run["started_at"]) for folder in SETS]
    done = [datetime.fromisoformat(records(folder)[-1].end["ended_at"]) for folder in SETS]
    assert list(SETS) == ["sections-before", "sections-after", "dev-after"]
    head, _ = read_outcomes(SPLIT_AGAIN)
    begun.append(datetime.fromisoformat(head["began"]))
    for ended, started in zip(done, begun[1:], strict=True):
        assert timedelta(0) < started - ended < timedelta(seconds=10)
    # The judge read the three sheets the day after, in the same order.
    asked = [judge.read_record(HERE / f"{stem}-j2.jsonl")[0] for stem in STEM.values()]
    times = [head["started_at"] for head in asked]
    assert times == sorted(times) and all(when.startswith("2026-11-26T03:") for when in times)


def test_nothing_spoilt_a_run_no_call_failed_and_the_loop_asked_in_none():
    every = [attempt for folder in SETS for attempt in records(folder)]
    assert len(every) == 102
    for attempt in every:
        assert attempt.spoilt is None and attempt.end["reason"] == "answered"
        # The record says whether the loop asked for the call, and it did not.
        assert "asked_again" in attempt.end and attempt.end["asked_again"] is None
        assert {turn["stop_reason"] for turn in attempt.turns} == {"tool_use"}
        assert [call["name"] for call in attempt.turns[-1]["tools"]] == ["submit_answer"]
        assert not [call for call in results(attempt) if call["status"] != "ok"]
        # The characters in the last line of a record are those of its tool results.
        given_it = sum(call["result_chars"] for call in results(attempt))
        assert attempt.end["tool_result_chars"] == given_it, attempt.run["run_id"]
        assert attempt.end["turns"] == len(attempt.turns)


def test_the_cost_of_each_set_is_what_the_readme_gives():
    assert {folder: cost(records(folder)) for folder in SETS} == {
        "sections-before": 0.66,
        "sections-after": 0.50,
        "dev-after": 1.90,
    }
    by_layout = {
        (name, layout): cost(a for cell, a in side(name).items() if cell.toolset == layout)
        for name in SIDES
        for layout in LAYOUTS
    }
    assert by_layout == {
        ("before", "staged"): 0.34,
        ("before", "flat"): 0.33,
        ("after", "staged"): 0.19,
        ("after", "flat"): 0.31,
    }
    said = flat(came_back())
    assert "The 36 runs before cost $0.66, and the 36 after $0.50." in said
    assert "cost $0.34 before and $0.19 after, the flat runs $0.33 and $0.31." in said
    rows = table_rows(came_back(), "| here | holds |", "`")
    assert [row.split(" | ")[-1] for row in rows[:3]] == ["$0.66 |", "$0.50 |", "$1.90 |"]
    assert [row.split(" | ")[2] for row in rows] == [
        "10:28 to 10:34",
        "10:34 to 10:40",
        "10:40 to 10:46",
        "10:46 to 10:47",
    ]
    assert [row.split(" | ")[3:5] for row in rows] == [
        [f"`{LAST_OF_4}`", "`4`"],
        *([[f"`{PLANNED}`", "`5`"]] * 3),
    ]


# --- what each parser made of the six papers, as the records name it -----------------------


def first_line(runs: dict[Cell, Attempt], question_id: str, layout: str, tool: str) -> dict:
    """What a tool said of a paper to the three runs of a question: the same line each time."""
    lines = [
        call["first_line"]
        for attempt in of(runs, question_id, layout)
        for call in results(attempt, tool)
    ]
    assert len(lines) == 3 and all(line == lines[0] for line in lines)
    return lines[0]


def size_of(runs: dict[Cell, Attempt], question_id: str, section: str) -> int:
    """The size of a section, as every read of it by a staged run of a question names it."""
    (size,) = {
        size
        for attempt in of(runs, question_id, "staged")
        for name, _, _, size in reads(attempt)
        if name == section
    }
    return size


def test_each_parser_made_of_the_six_papers_what_the_plan_and_the_survey_say():
    # The plan gave the sizes from the code of each parser, and said that no file of this
    # repository held those of parser 5. The first line of a result names what it holds,
    # and a record keeps what the line names. Every staged run asked for the outline of
    # its paper, and every flat run for its whole text.
    _, lines = read_outcomes(SPLIT_AGAIN)
    split_again = {line["id"]: line for line in lines}
    whole = {}
    for name, parser in zip(SIDES, ("4", "5"), strict=True):
        runs = side(name)
        for question_id, (paper, chars_of_4) in PAPERS.items():
            outline = first_line(runs, question_id, "staged", "get_outline")
            text = first_line(runs, question_id, "flat", "read_paper")
            assert (outline["arxiv_id"], outline["parser"]) == (paper, parser)
            assert (text["arxiv_id"], text["parser"], text["extent"]) == (paper, parser, "complete")
            assert outline["sections"] == text["sections"]
            whole[name, question_id] = text["chars"]
            if name == "before":
                # As in the survey, which was made with parser 4 (test_section_questions.py).
                assert outline["chars"] == chars_of_4
                assert outline["sections"] == (10 if question_id == LEFT_OUT else 1)
            else:
                # And as in the sample that parser 5 split again.
                line = split_again[paper]
                assert (outline["chars"], outline["sections"]) == (line["chars"], line["sections"])

    # The whole text, which a flat run is given: what the plan says under "How it is read".
    plan = flat(plan_text())
    assert (whole["before", LEFT_OUT], whole["after", LEFT_OUT]) == (31_825, 59_146)
    assert (
        "For sec-01 it is 31,825 characters under parser `4` and 59,146 under parser `5`." in plan
    )
    letters = [whole["before", name] for name in LETTERS]
    assert (min(letters), max(letters)) == (21_604, 35_259)
    assert all(abs(whole["after", name] - whole["before", name]) <= 150 for name in LETTERS)
    assert (
        "(21,604 to 35,259 characters under parser `4`, and within 150 of that under parser `5`)"
        in plan
    )
    said = flat(came_back())
    assert (
        "The flat runs were given a text of 31,825 characters in 10 sections, the supplemental "
        "material" in said
    )
    assert first_line(side("after"), LEFT_OUT, "flat", "read_paper")["sections"] == 11
    assert "whose text now has 59,146 characters in 11 sections" in said
    assert "are those of its line in `../../survey/outcomes-parser5.jsonl`" in said


def test_the_section_of_each_question_has_the_size_that_the_plan_gave_for_it():
    rows = {
        name: next(row for row in plan_text().splitlines() if row.startswith(f"| {name} |"))
        for name in QUESTIONS
    }
    before, after, where = side("before"), side("after"), section_of("after")
    assert section_of("before") == {LEFT_OUT: "0", **dict.fromkeys(LETTERS, "1")}
    sizes = {}
    for name in LETTERS:
        # Under parser 4 the one section is the paper, and under parser 5 a section made
        # at a title holds the passage.
        assert size_of(before, name, "1") == PAPERS[name][1]
        sizes[name] = size_of(after, name, where[name])
        assert f"section `{where[name]}` ({sizes[name]:,} characters)" in rows[name]
    assert sizes == {
        "sec-02": 1_290,
        "sec-03": 1_818,
        "sec-04": 1_811,
        "sec-05": 8_043,
        "sec-06": 502,
    }
    # sec-01: section "0" is 669 characters of the supplemental material under parser 4,
    # and the letter under parser 5.
    assert (size_of(before, LEFT_OUT, "0"), size_of(after, LEFT_OUT, "0")) == (669, 24_532)
    assert "section `0` (no heading, 24,532 characters)" in rows[LEFT_OUT]
    # The first piece of the one section, where a staged run before read it from its
    # beginning: three of the five that the plan speaks of.
    first_pieces = {
        name: stop
        for name in LETTERS
        for attempt in of(before, name, "staged")
        for _, start, stop, _ in reads(attempt)
        if start == 0
    }
    assert first_pieces == {"sec-02": 19_100, "sec-03": 19_228, "sec-06": 19_966}
    assert "ends after 19,100 to 19,966 characters" in flat(plan_text())
    said = flat(came_back())
    assert "whole (502 to 8,043 characters)" in said
    one_section = [PAPERS[name][1] for name in LETTERS]
    assert (min(one_section), max(one_section)) == (21_542, 35_197)
    assert "in one section of 21,542 to 35,197 characters every time" in said


# --- the six questions: the two sides beside each other -----------------------------------


def test_the_table_of_the_two_sides_is_what_the_reports_the_records_and_the_verdicts_say():
    runs = {name: side(name) for name in SIDES}
    right = {name: verdicts(name) for name in SIDES}
    for layout in LAYOUTS:
        passage = {name: given(name, layout) for name in SIDES}
        rows = []
        for question_id in QUESTIONS:
            cells = [question_id]
            cells += [f"{passage[name][question_id]} / 3" for name in SIDES]
            cells += [f"{chars(of(runs[name], question_id, layout)):,.0f}" for name in SIDES]
            cells += [
                " ".join(str(a.end["turns"]) for a in of(runs[name], question_id, layout))
                for name in SIDES
            ]
            for name in SIDES:
                own = [
                    verdict
                    for cell, verdict in right[name].items()
                    if (cell.question_id, cell.toolset) == (question_id, layout)
                ]
                assert len(own) == 3
                cells.append(f"{own.count(RIGHT)} / 3")
            rows.append("| " + " | ".join(cells) + " |")
        assert table_rows(came_back(), f"The {layout} layout:") == rows
    # The characters of a report are those of the records.
    for name in SIDES:
        for question_id, cells in report_of(name).items():
            assert cells[4:6] == [
                f"{chars(of(runs[name], question_id, layout)):,.0f}" for layout in LAYOUTS
            ]
    # "Here the three requests said the same of every answer."
    for name in SIDES:
        assert all(len(set(said)) == 1 for said in by_the_judge(f"sections-{name}").values())


@pytest.mark.parametrize("name", SIDES)
def test_each_report_is_what_the_command_writes_but_for_what_needs_the_papers(
    name, tmp_path, monkeypatch
):
    # eval/report.py is the same file in both commits, so the code of now writes the
    # report of the side before as well, where no paper is read. Paths as the README of
    # the folder gives them: the report names the folder of the records.
    monkeypatch.chdir(ROOT)
    conditions = {"before": "asking-again", "after": "more-sections"}[name]
    folder = f"results/runs/more-sections/sections-{name}"
    argv = ["--questions", f"eval_data/{SECTIONS[name].name}", "--runs", folder]
    argv += ["--conditions", conditions, "--out", str(tmp_path / "report.md")]
    assert report.main(argv, source=FixtureSource([own_paper()])) == 0
    kept = (HERE / f"sections-{name}-report.md").read_text(encoding="utf-8")
    written = (tmp_path / "report.md").read_text(encoding="utf-8")
    if name == "before":
        # It was written in the second working tree, which stands beside the repository.
        there = f"Records: ../HEP-Ph_Paper_miner/{folder}; code {LAST_OF_4} (36 runs)\n"
        assert there in kept
        kept = kept.replace(there, f"Records: {folder}; code {LAST_OF_4} (36 runs)\n")
    assert without_the_papers(written) == without_the_papers(kept)
    # What is compared holds the conditions, the answers and the characters of every question.
    compared = without_the_papers(kept)
    assert (
        f"Held against the conditions {conditions!r} (conditions.py): no record differs" in compared
    )
    assert f"Questions: {SECTIONS[name].name}, SHA-256 {file_digest(SECTIONS[name])}" in compared
    assert "Answers graded by hand: 0 of 36 (no sheet given)" in compared
    assert "| answered | 18 / 18 | 18 / 18 |" in compared
    assert "| of them after the loop had asked again for the call | 0 | 0 |" in compared
    assert "| runs with a tool error | 0 | 0 |" in compared
    # And what is left out is what the README of the folder says a report says without them.
    assert "| 2a passage given | 0 / 18 | 0 / 18 |" in written
    assert "New paper text may count a character twice in 18 run(s)" in written
    assert "counts no run as given the passage and says in a note that a paper was missing" in flat(
        came_back()
    )
    by_layout = {
        "before": "| 2a passage given | 15 / 18 | 15 / 18 |",
        "after": "| 2a passage given | 18 / 18 | 18 / 18 |",
    }
    assert by_layout[name] in kept
    assert (
        sum(given(name, "staged").values())
        == sum(given(name, "flat").values())
        == int(by_layout[name].split(" | ")[1].split(" / ")[0])
    )


def test_the_passage_reads_shown_over_the_six_questions_and_not_shown_over_the_five_letters():
    # The first reading of the plan: as eval.regress --targets reads it, said twice. A
    # report says in how many runs of a question the passage was given, not in which, and
    # the reading asks no more.
    def staged(name: str, questions: tuple[str, ...]) -> dict[Cell, regress.Facts]:
        count = given(name, "staged")
        return {
            (cell := Cell(question_id, "staged", n)): regress.Facts(
                cell, "", "answered", 3, 0, None, n <= count[question_id], RIGHT
            )
            for question_id in questions
            for n in (1, 2, 3)
        }

    said = flat(came_back())
    for questions, word, counts in (
        (QUESTIONS, regress.SHOWN, (15, 18)),
        (LETTERS, regress.NOT_SHOWN, (15, 15)),
    ):
        before, after = staged("before", questions), staged("after", questions)
        assert regress.effect(before, after, list(before))[0] == word
        assert (
            sum(f.passage for f in before.values()),
            sum(f.passage for f in after.values()),
        ) == counts
    _, lines = regress.effect(
        staged("before", QUESTIONS), staged("after", QUESTIONS), list(staged("before", QUESTIONS))
    )
    assert lines == [
        "sec-01: 0 of 3 before, 3 after",
        *(f"{name}: 3 of 3 before, 3 after" for name in LETTERS),
    ]
    assert (
        "the passage was given in 15 of the 18 staged runs before and in 18 of 18 after, and in "
        'fewer runs of no question: "shown", as `eval.regress --targets` reads it. All of that '
        "is sec-01." in said
    )
    assert (
        'it was given in 15 of 15 staged runs before and in 15 of 15 after: "not shown". The side '
        "before was given the passage every time, so there was nothing to gain." in said
    )
    # The flat layout, which decides nothing: as the split has it.
    assert given("before", "flat") == {LEFT_OUT: 0, **dict.fromkeys(LETTERS, 3)}
    assert given("after", "flat") == dict.fromkeys(QUESTIONS, 3)
    assert given("before", "staged") == given("before", "flat")
    assert (
        "The passage of sec-01 was given in 0 of 3 flat runs before and in 3 of 3 after, and "
        "that of each of the five others in 3 of 3 on both sides" in said
    )


def test_the_staged_runs_were_given_fewer_characters_in_each_of_the_five_letters():
    # The second reading: the questions in which the median after is lower are counted.
    runs = {name: side(name) for name in SIDES}
    middle = {
        (name, layout): {q: chars(of(runs[name], q, layout)) for q in QUESTIONS}
        for name in SIDES
        for layout in LAYOUTS
    }
    staged = [(middle["before", "staged"][q], middle["after", "staged"][q]) for q in LETTERS]
    assert staged == [
        (29_105, 2_658),
        (20_754, 11_864),
        (9_862, 7_572),
        (16_645, 9_397),
        (21_196, 1_922),
    ]
    assert sum(1 for before, after in staged if after < before) == len(LETTERS) == 5
    said = flat(came_back())
    assert "The median after is lower than the median before in 5 of the 5 questions." in said
    # For sec-01 the staged runs were given more after: the letter is there to be read.
    assert middle["before", "staged"][LEFT_OUT] < middle["after", "staged"][LEFT_OUT]
    # The flat layout is given the whole text on either side: nearly the same characters.
    apart = [abs(middle["after", "flat"][q] - middle["before", "flat"][q]) for q in LETTERS]
    assert (min(apart), max(apart)) == (5, 151)
    assert "where the two medians are 5 to 151 characters apart" in said


def test_before_the_staged_runs_got_to_the_passage_of_the_five_letters_in_three_ways():
    before = side("before")
    read = {name: [reads(attempt) for attempt in of(before, name, "staged")] for name in QUESTIONS}
    size = {name: PAPERS[name][1] for name in LETTERS}
    # Every read of a letter is of its one section.
    assert all(
        section == "1" and chars == size[name]
        for name in LETTERS
        for run in read[name]
        for section, _, _, chars in run
    )
    # sec-03 and sec-06: the first piece and no more. Their passage lies in it.
    for name, stop in (("sec-03", 19_228), ("sec-06", 19_966)):
        assert read[name] == [[("1", 0, stop, size[name])]] * 3
    # sec-02: the first piece, and the rest with the next response.
    assert read["sec-02"] == [[("1", 0, 19_100, 27_811), ("1", 19_100, 27_811, 27_811)]] * 3
    assert [a.end["turns"] for a in of(before, "sec-02", "staged")] == [4, 4, 4]
    # sec-04: one read, which begins far behind the first piece and goes to the end.
    assert [[(start, stop) for _, start, stop, _ in run] for run in read["sec-04"]] == [
        [(26_000, 35_197)],
        [(27_000, 35_197)],
        [(27_000, 35_197)],
    ]
    # sec-05: two reads, the first from 17,000 to 30,000.
    assert [len(run) for run in read["sec-05"]] == [2, 2, 2]
    assert {run[0][1:3] for run in read["sec-05"]} == {(17_000, 30_000)}
    assert sorted(run[1][1] for run in read["sec-05"]) == [29_800, 29_800, 29_900]
    # So no run of these two read the section from its beginning, and the passage was
    # given in every one of the nine runs whose passage lies behind the first piece.
    assert not [
        1
        for name in ("sec-04", "sec-05")
        for run in read[name]
        for _, start, _, _ in run
        if start == 0
    ]
    behind = [
        q.id for q in load_questions(SECTIONS["before"]) if q.type == "one_block_second_piece"
    ]
    assert behind == ["sec-02", "sec-04", "sec-05"]
    assert [given("before", "staged")[name] for name in behind] == [3, 3, 3]
    # sec-01: five or six of the ten sections of the supplemental material.
    assert [len(run) for run in read[LEFT_OUT]] == [5, 6, 5]
    assert all(
        {section for section, _, _, _ in run} <= {str(n) for n in range(10)}
        for run in read[LEFT_OUT]
    )
    middle = {name: chars(of(before, name, "staged")) for name in ("sec-04", "sec-05")}
    after = {name: chars(of(side("after"), name, "staged")) for name in ("sec-04", "sec-05")}
    assert middle == {"sec-04": 9_862, "sec-05": 16_645}
    assert {name: middle[name] - after[name] for name in middle} == {
        "sec-04": 2_290,
        "sec-05": 7_248,
    }
    said = flat(came_back())
    assert (
        "Each run of sec-04 made one read of section `1`, from 26,000 or 27,000 characters to its "
        "end, and each run of sec-05 two, the first from 17,000 to 30,000. So their medians "
        "before are 9,862 and 16,645 characters, below the 19,000 of that reason, and the "
        "medians after are 2,290 and 7,248 characters lower." in said
    )
    assert "and the staged runs read five or six of those sections" in said
    assert "All nine runs did." in said


def test_after_each_staged_run_read_the_section_of_its_question_whole_with_its_second_response():
    after, where = side("after"), section_of("after")
    for name in LETTERS:
        for attempt in of(after, name, "staged"):
            first, second, third = attempt.turns
            assert [call["name"] for call in first["tools"]] == ["get_outline"]
            assert {call["name"] for call in second["tools"]} == {"read_section"}
            assert [call["name"] for call in third["tools"]] == ["submit_answer"]
            (own,) = [read for read in reads(attempt) if read[0] == where[name]]
            assert own[1] == 0 and own[2] == own[3]  # from its beginning to its end
    # Two questions were given a second section in that response.
    others = {
        name: [
            [read[0::3] for read in reads(a) if read[0] != where[name]]
            for a in of(after, name, "staged")
        ]
        for name in LETTERS
    }
    assert others == {
        "sec-02": [[], [], []],
        "sec-03": [[("u6", 8_323)]] * 3,
        "sec-04": [[("u1", 3_886)], [("u1", 3_886)], []],
        "sec-05": [[], [], []],
        "sec-06": [[], [], []],
    }
    # sec-01: each read section "0", which is the letter now, in two ways.
    zero = [[read for read in reads(a) if read[0] == "0"] for a in of(after, LEFT_OUT, "staged")]
    assert zero == [
        [("0", 0, 20_000, 24_532)],
        [("0", 6_000, 16_000, 24_532)],
        [("0", 0, 20_000, 24_532)],
    ]
    assert given("after", "staged")[LEFT_OUT] == 3
    # Responses: three for each of the 18 staged runs after; three to six before.
    turns = {
        name: {cell: a.end["turns"] for cell, a in side(name).items() if cell.toolset == "staged"}
        for name in SIDES
    }
    assert set(turns["after"].values()) == {3} and len(turns["after"]) == 18
    assert {t for cell, t in turns["before"].items() if cell.question_id in LETTERS} == {3, 4}
    assert {t for cell, t in turns["before"].items() if cell.question_id == LEFT_OUT} == {5, 6}
    said = flat(came_back())
    assert (
        "In each of the 15 staged runs of sec-02 to sec-06 the model asked for the outline, read "
        "the section that holds the passage with its second response, whole (502 to 8,043 "
        "characters), and answered with its third. All three runs of sec-03 asked for `u6` in "
        "that same response (8,323 characters), and two of the three of sec-04 for `u1` (3,886)"
        in said
    )
    assert "two from its beginning to 20,000 characters, one from 6,000 to 16,000" in said
    assert "five or six for sec-01. After, each of the 18 staged runs took three." in said


def test_four_runs_of_sec_01_searched_and_no_other_run_of_the_six_questions():
    searched = {
        (name, str(cell)): [
            call["first_line"]["shown"] for call in results(attempt, "search_papers")
        ]
        for name in SIDES
        for cell, attempt in side(name).items()
        if results(attempt, "search_papers")
    }
    assert searched == {
        ("before", "sec-01 flat 1"): [1],
        ("before", "sec-01 flat 2"): [1],
        ("after", "sec-01 staged 1"): [0],
        ("after", "sec-01 staged 3"): [0],
    }
    assert (
        "Two flat runs before and two staged runs after of sec-01 searched all the same; the two "
        "searches after listed nothing." in flat(came_back())
    )


# --- the sheets, their keys and the judge ---------------------------------------------------


@pytest.mark.parametrize("folder", SETS)
def test_a_sheet_and_its_key_are_what_is_written_for_the_runs_and_the_judge_read_that_sheet(
    folder, tmp_path
):
    file, commit, _, _, _, number, _ = SETS[folder]
    stem = STEM[folder]
    sheet, key = HERE / f"{stem}-sheet.csv", HERE / f"{stem}-key.csv"
    questions = {question.id: question for question in load_questions(file)}
    by_run = {attempt.run["run_id"]: attempt for attempt in that_count(folder).values()}
    numbered = read_key(key)
    assert sorted(numbered) == list(range(1, number + 1))
    assert sorted(line["run_id"] for line in numbered.values()) == sorted(by_run)
    # The rows of a question stand together, the questions in the order of their file.
    assert list(dict.fromkeys(line["question_id"] for _, line in sorted(numbered.items()))) == list(
        questions
    )
    rows = [
        Row(n, questions[line["question_id"]], by_run[line["run_id"]])
        for n, line in sorted(numbered.items())
    ]
    write_key(rows, tmp_path / "key.csv")
    write_sheet(rows, tmp_path / "sheet.csv")
    assert (tmp_path / "key.csv").read_bytes() == key.read_bytes()
    written = (tmp_path / "sheet.csv").read_bytes()

    head, lines, end = judge.read_record(HERE / f"{stem}-j2.jsonl")
    assert (head["judge_version"], head["texts_sha256"]) == ("j2", judge.texts_digest())
    # Each sheet was made and read where its runs were made: the side before in the
    # second working tree, by the code of parser 4.
    assert (head["code"]["commit"][:7], head["code"]["modified"]) == (commit, False)
    assert head["questions"] == {"file": file.name, "sha256": file_digest(file)}
    assert (head["controls"], head["only"], head["repeats"]) == (None, None, 3)
    # Written again from the records, the sheet is the file the judge read: the same bytes.
    digest = hashlib.sha256(written).hexdigest()
    assert head["sheet"] == {"file": sheet.name, "sha256": digest, "answers": number}
    assert end["requests"] == 3 * number and end["failed"] == 0
    if folder == "sections-before":
        # The maintainer wrote grades into six rows afterwards, and nothing else is other.
        graded = read_csv(sheet)
        blank = dict.fromkeys(("grade", "why_wrong", "note"), "")
        assert [{**row, **blank} for row in graded] == read_csv(tmp_path / "sheet.csv")
        assert [row["number"] for row in graded if row["grade"]] == [str(n) for n in range(1, 7)]
        assert not [row for row in graded[6:] if row["grade"] or row["why_wrong"] or row["note"]]
    else:
        # Nobody wrote a grade.
        assert sheet.read_bytes() == written


def test_the_judge_called_the_six_answers_before_to_sec_01_wrong_and_every_other_answer_right():
    said = {stem: by_the_judge(stem) for stem in STEM.values()}
    assert {
        stem: Counter(v for row in rows.values() for v in row) for stem, rows in said.items()
    } == {
        "sections-before": {"right": 90, "wrong": 18},
        "sections-after": {"right": 108},
        "dev": {"right": 90},
    }
    wrong = sorted(number for number, row in said["sections-before"].items() if "wrong" in row)
    assert wrong == [1, 2, 3, 4, 5, 6]
    assert all(said["sections-before"][number] == ("wrong",) * 3 for number in wrong)
    # They are the six answers to sec-01, three of each layout.
    key = read_key(HERE / "sections-before-key.csv")
    assert Counter((key[n]["question_id"], key[n]["toolset"]) for n in wrong) == {
        (LEFT_OUT, "staged"): 3,
        (LEFT_OUT, "flat"): 3,
    }
    costs = {
        stem: round(judge.read_record(HERE / f"{stem}-j2.jsonl")[2]["cost"], 2)
        for stem in STEM.values()
    }
    assert costs == {"sections-before": 0.36, "sections-after": 0.35, "dev": 0.32}
    text = came_back()
    assert "108 requests, of which 90 said `right` and 18 `wrong` ($0.36)" in text
    assert "108 requests, each of which said `right` ($0.35)" in text
    assert "90 requests, each of which said `right` ($0.32)" in text

    # What the six say, and what the note of the question says of such answers.
    (question,) = [q for q in load_questions(SECTIONS["before"]) if q.id == LEFT_OUT]
    assert question.expect_found is True
    assert "found = false" in question.accept_note and "len50" in question.accept_note
    before = side("before")
    six = [a.end["answer"] for cell, a in before.items() if cell.question_id == LEFT_OUT]
    assert len(six) == 6
    for answer in six:
        assert answer["found"] is False
        assert "Supplemental Material" in answer["answer"] and "len50" in answer["answer"]
        assert "20%" not in answer["answer"] and "20 %" not in answer["answer"]
    # And every other answer of both sides says that the paper states it.
    others = [
        a.end["answer"]["found"] for cell, a in before.items() if cell.question_id != LEFT_OUT
    ]
    others += [a.end["answer"]["found"] for a in side("after").values()]
    assert others == [True] * 66
    # The rule of grade.py, which the plan gives no part: it calls the six wrong as well.
    assert {
        grade_answer(Record(a.run, a.turns, a.end), question).rule
        for a in of(before, LEFT_OUT, "staged") + of(before, LEFT_OUT, "flat")
    } == {"wrong"}
    said_here = flat(text)
    assert (
        "The judge called six answers wrong, each in all three of its requests: the six answers "
        "of the side before to sec-01, three of each layout. Every one says that the paper does "
        "not state what is asked (`found` is false), and that the text it was given is the "
        "supplemental material. Each also names a figure file of that material whose name holds "
        "`len50`" in said_here
    )


def test_the_maintainer_graded_those_six_wrong_and_no_other_answer_was_graded():
    # The plan: "An answer that the judge calls wrong in a request is read by the
    # maintainer, and a grade the maintainer writes on a sheet is the verdict."
    grades = read_grades(HERE / "sections-before-sheet.csv", HERE / "sections-before-key.csv")
    graded = [grade for grade in grades if grade.grade is not None]
    assert [grade.number for grade in graded] == [1, 2, 3, 4, 5, 6]
    assert Counter((g.question_id, g.toolset, g.grade) for g in graded) == {
        (LEFT_OUT, "staged", "wrong"): 3,
        (LEFT_OUT, "flat", "wrong"): 3,
    }
    assert all(grade.why_wrong for grade in graded)  # each row says why
    # One reason and one note for the six, in the maintainer's words: what the answer
    # lacks, where the values were looked up, and the note of the question.
    ((_, note),) = {(grade.why_wrong, grade.note) for grade in graded}
    assert all(word in note for word in ("found=false", "PDF", "accept_note"))
    for stem in ("sections-after", "dev"):
        rows = read_grades(HERE / f"{stem}-sheet.csv", HERE / f"{stem}-key.csv")
        assert not [row for row in rows if row.grade or row.why_wrong or row.note]
    # So the verdicts: before 15 of 18 right with each layout, after 18 of 18.
    right = {
        (name, layout): sum(
            1 for cell, v in verdicts(name).items() if cell.toolset == layout and v == RIGHT
        )
        for name in SIDES
        for layout in LAYOUTS
    }
    assert right == {
        ("before", "staged"): 15,
        ("before", "flat"): 15,
        ("after", "staged"): 18,
        ("after", "flat"): 18,
    }
    assert all(
        v == "wrong" for cell, v in verdicts("before").items() if cell.question_id == LEFT_OUT
    )
    said = flat(came_back())
    assert (
        "The maintainer read the six on 2026-11-26 and graded each wrong, in rows 1 to 6 of "
        "`sections-before-sheet.csv`." in said
    )
    assert (
        "The six rows have one note, in Korean: the answer gives neither value, the two values "
        "stand in the letter and not in the supplemental material (looked up in the PDF of the "
        "paper), and by the note of the question an answer that says the paper does not state "
        "them is wrong whatever the tool had returned." in said
    )
    assert (
        "Before, 15 of the 18 answers are right with each layout, and the three that are not are "
        "those to sec-01. After, 18 of 18 are right with each layout." in said
    )
    assert "Nobody graded the other 66 answers of the two sides." in said
    assert "Of the 72 answers a person graded six." in said
    assert "were expected to be right, and none is." in said


# --- the development questions again ------------------------------------------------------


def dev_sides() -> dict[str, dict[Cell, Attempt]]:
    return {"before": counted(attempts_in(DEV_BEFORE)), "after": that_count("dev-after")}


def test_the_comparison_is_what_the_command_writes_from_these_files_and_it_passed(
    tmp_path, monkeypatch
):
    # Paths as the plan gives them: the text names the folders.
    monkeypatch.chdir(ROOT)
    here = "results/runs/more-sections"
    argv = ["--questions", "eval_data/questions_dev.jsonl", "--criteria", "2"]
    argv += ["--before", "results/runs/asking-again/dev-after", "--after", f"{here}/dev-after"]
    argv += ["--sheet", f"{here}/dev-sheet.csv", "--key", f"{here}/dev-key.csv"]
    argv += ["--judge", f"{here}/dev-j2.jsonl", "--out", str(tmp_path / "dev.md")]
    code = regress.main(argv, source=FixtureSource([own_paper()]))
    written = (tmp_path / "dev.md").read_text("utf-8")
    kept = (HERE / "regress-dev.md").read_text("utf-8")
    assert lines_that_need_no_other_paper(written) == lines_that_need_no_other_paper(kept)
    # What is open here is the six runs of dev-03, whose paper is not kept, and no more.
    assert code == 1 and VERDICT + "not decided." in written
    open_here = [line.strip() for line in written.splitlines() if line.startswith("    - ")]
    assert sorted(open_here) == sorted(
        f"- dev-03 {layout} {n}: its paper could not be read"
        for layout in LAYOUTS
        for n in (1, 2, 3)
    )

    said = [line for line in kept.splitlines() if line.startswith(("- ", "    - "))]
    assert said == [
        "- 1 every run ended with an answer: passed",
        "- 2 the passage was given in every run: passed",
        "- 3 the rule calls no answer wrong: passed",
        "- 4 no answer left to a person is wrong: passed",
        "- 5 staged was given less text than flat: passed",
    ]
    assert VERDICT + "passed." in kept
    assert "Criteria: the second set (3 asks only that the rule calls no answer wrong)" in kept
    assert "No run after was asked again for the call." in kept
    texts = "30 runs; tool texts staged-6, flat-5; code"
    assert f"Before: results/runs/asking-again/dev-after; {texts} {DEV_BEFORE_CODE}\n" in kept
    assert f"After: {here}/dev-after; {texts} {PLANNED}\n" in kept
    # The two sides have one prompt, so the text names none; and no cell is marked.
    assert "prompt" not in kept
    assert "has changed since the judge read it" not in kept
    assert "more responses than any run before" not in kept

    # Twelve right by the rule and eighteen left to a person, none wrong.
    questions = {question.id: question for question in load_questions(DEV)}
    rules = Counter(
        grade_answer(Record(a.run, a.turns, a.end), questions[cell.question_id]).rule
        for cell, a in dev_sides()["after"].items()
    )
    assert rules == {RIGHT: 12, BY_HAND: 18}
    in_the_folder = flat(came_back())
    assert "It calls twelve right and leaves eighteen to a person." in in_the_folder
    assert "## 2. The development questions again: passed" in came_back()


def test_the_two_sides_of_the_development_runs_were_given_the_same_but_for_the_name_of_the_parser():
    # The plan said that the two sides differ "in nothing a model reads". They differ in
    # one thing, and what came back says so.
    assert "and in nothing a model reads" in flat(plan_text())
    runs = dev_sides()
    for attempt in runs["before"].values():
        assert differences(attempt.run, attempt.end, ASKING_AGAIN) == []
        assert attempt.run["code"]["commit"][:7] == DEV_BEFORE_CODE
        assert attempt.end["parser_versions"] == ["4"]

    def came(name: str) -> dict[tuple, set[tuple]]:
        """For every call of a side, by layout, tool and arguments: the texts that came back.

        By layout as well: a search comes back with abstracts in the flat layout and
        without them in the staged one.
        """
        found: dict[tuple, set[tuple]] = {}
        for cell, attempt in runs[name].items():
            for call in results(attempt):
                arguments = tuple(sorted(call["arguments"].items()))
                asked = (call["name"], cell.toolset, arguments)
                line = json.dumps(call["first_line"], sort_keys=True)
                found.setdefault(asked, set()).add(
                    (call["result_chars"], call["result_sha256"], line)
                )
        return found

    before, after = came("before"), came("after")
    # The same call came back with one text on a side, whenever it was made.
    assert all(len(texts) == 1 for texts in (*before.values(), *after.values()))
    both = sorted(set(before) & set(after))
    same, other = Counter(), Counter()
    for asked in both:
        ((chars_1, digest_1, line_1),) = before[asked]
        ((chars_2, digest_2, line_2),) = after[asked]
        if digest_1 == digest_2:
            same[asked[0]] += 1
            continue
        other[asked[0]] += 1
        # The same length, and of the first line only the name of the parser is another.
        assert chars_1 == chars_2
        line_1, line_2 = json.loads(line_1), json.loads(line_2)
        assert [name for name in line_1 if line_1[name] != line_2[name]] == ["parser"]
        assert (line_1["parser"], line_2["parser"]) == ("4", "5") and set(line_1) == set(line_2)
    assert same == {"read_section": 14, "search_papers": 3}
    assert other == {"get_outline": 2, "read_paper": 2}
    papers = sorted({dict(asked[2])["arxiv_id"] for asked in both if asked[0] in other})
    assert papers == ["1601.05089v3", "2610.26648v1"]
    said = flat(came_back())
    assert (
        "Each of these four results has the same length on both sides and another SHA-256, and "
        "what a record keeps of its first line differs in the parser, `4` or `5`, and in nothing "
        "else. Seventeen other calls were made on both sides with the same layout and the same "
        "arguments, fourteen reads of a section and three searches, and each came back with the "
        "same SHA-256." in said
    )


def test_the_development_runs_cost_a_little_less_and_one_flat_run_of_dev_01_searched():
    runs = dev_sides()
    assert {name: cost(found.values()) for name, found in runs.items()} == {
        "before": 2.04,
        "after": 1.90,
    }
    dev_01 = {name: of(found, "dev-01", "flat") for name, found in runs.items()}
    assert {name: cost(found) for name, found in dev_01.items()} == {"before": 0.19, "after": 0.34}

    def first_asked(attempt: Attempt) -> list[str]:
        return [call["name"] for call in attempt.turns[0]["tools"]]

    assert [first_asked(a) for a in dev_01["before"]] == [["read_paper"]] * 3
    assert [first_asked(a) for a in dev_01["after"]] == [["read_paper"]] * 2 + [
        ["read_paper", "search_papers"]
    ]
    (search,) = results(dev_01["after"][2], "search_papers")
    assert search["first_line"]["shown"] == 0
    # The third run wrote the paper to the cache again, where the second had read it from there.
    assert [a.end["cache_creation_input_tokens"] for a in dev_01["after"]] == [65_721, 0, 63_857]
    assert [a.end["cache_creation_input_tokens"] for a in dev_01["before"]] == [65_721, 0, 0]
    said = flat(came_back())
    assert "The thirty runs cost $1.90, and the thirty before $2.04." in said
    assert "so the three flat runs of dev-01 cost $0.34, where the three before cost $0.19" in said


# --- what the README of the repository says -----------------------------------------------


def test_what_the_readme_of_the_repository_says_of_the_six_questions_is_what_the_files_say():
    readme = flat((ROOT / "README.md").read_text(encoding="utf-8"))
    assert "- [x] Parser `5` held beside parser `4`, as written down before the runs" in readme
    assert sum(len(side(name)) for name in SIDES) == 72
    assert (
        f"by the last commit with parser `4` (`{LAST_OF_4}`) and by the code with parser `5`: "
        "72 runs, each side graded by its own code" in readme
    )
    assert (
        "All of it was run on 2026-11-25, with the model and the settings of the evaluation"
        in readme
    )

    # The letter that was left out: both layouts together.
    passage = {name: {layout: given(name, layout) for layout in LAYOUTS} for name in SIDES}
    assert [sum(passage[name][layout][LEFT_OUT] for layout in LAYOUTS) for name in SIDES] == [0, 6]
    right = [
        sum(1 for cell, v in verdicts(name).items() if cell.question_id == LEFT_OUT and v == RIGHT)
        for name in SIDES
    ]
    assert right == [0, 6]
    assert (
        "with parser `4` its passage was given in none of the six runs, and all six answers say "
        "that the paper does not state what is asked. With parser `5` it was given in all six, "
        "and all six answers are right." in readme
    )
    assert (
        "its passage was given in 0 of 6 runs with parser `4` and in 6 of 6 with parser `5`, and "
        "0 and then 6 of the answers are right" in readme
    )

    # The five letters: the passage, and the characters of the staged runs.
    assert [sum(passage[name]["staged"][q] for q in LETTERS) for name in SIDES] == [15, 15]
    assert "the passage was given in all 15 staged runs with either parser" in readme
    assert (
        "not shown: the passage was given in 15 of 15 staged runs before and in 15 of 15 after"
        in readme
    )
    middle = {name: [chars(of(side(name), q, "staged")) for q in LETTERS] for name in SIDES}
    assert (min(middle["before"]), max(middle["before"])) == (9_862, 29_105)
    assert (min(middle["after"]), max(middle["after"])) == (1_922, 11_864)
    assert "medians of 9,862 to 29,105 before, and of 1,922 to 11,864 after" in readme
    assert "counted: the median is lower in 5 of 5 questions. No test is made of five" in readme
    # Every answer about the five letters is right on both sides.
    assert all(
        verdict == RIGHT
        for name in SIDES
        for cell, verdict in verdicts(name).items()
        if cell.question_id in LETTERS
    )
    assert "Every answer was right on both sides" in readme
    assert (
        "The questions about the five letters were answered right before the change as well."
        in readme
    )

    # The development questions, and where everything is.
    assert (
        "Thirty runs, held against the thirty of 2026-11-23 by `eval.regress --criteria 2`. "
        "**All five criteria held.**" in readme
    )
    assert "shown: the comparison passed, by the five criteria of the second set" in readme
    results = flat((ROOT / "results" / "README.md").read_text(encoding="utf-8"))
    assert (
        "what was run on 2026-11-25 with parser `5`, which begins a section in more places"
        in results
    )
    assert (
        "Its README is the plan that was written before any of it and, below the plan, what "
        "came back." in results
    )
    development = flat((RUNS / "dev" / "README.md").read_text(encoding="utf-8"))
    assert (
        "(2026-11-25, parser `5`) are in `../more-sections/`, with a README of their own. They "
        "are held against the runs of `../asking-again/dev-after/`." in development
    )


def test_the_pre_registration_lists_the_change_of_the_parser_and_what_was_run_with_it():
    # Section 10 of the pre-registration lists what was done after the evaluation that its
    # sections had not foreseen. Its last entry is the change of the parser. Every number
    # that entry gives is counted here again from the files.
    text = (ROOT / "eval_data" / "PREREGISTRATION.md").read_text(encoding="utf-8")
    opening = "\n- **2026-11-25, the parser was changed after the runs, under a new name.**"
    _, found, entry = text.partition(opening)
    assert found and "\n- **20" not in entry  # no dated entry follows it
    entry = flat(entry)

    # What stays: the evaluation was run under parser 4, and its conditions say so.
    assert (EVALUATION["parser"], MORE_SECTIONS["parser"]) == ("4", "5")
    assert "stay held against the conditions of Section 2, which name parser `4`" in entry
    assert len(CONDITIONS) == 4
    assert "names a fourth set of conditions beside the three there were" in entry
    # The commit of the change is the one the plan names, and the plan is of the next.
    assert "`6aaf20f`). No run has been" in flat(plan_text()) and "Commit `6aaf20f`" in entry
    assert (
        f"was written down before any of it (`{PLANNED}`, `results/runs/more-sections/README.md`)"
        in entry
    )

    # The six questions.
    passage = {name: {layout: given(name, layout) for layout in LAYOUTS} for name in SIDES}
    assert [sum(passage[name][layout][LEFT_OUT] for layout in LAYOUTS) for name in SIDES] == [0, 6]
    assert "the passage was given in 0 of 6 runs before and in 6 of 6 after" in entry
    assert [sum(passage[name]["staged"][q] for q in LETTERS) for name in SIDES] == [15, 15]
    assert "the passage was given in 15 of 15 staged runs on both sides" in entry
    assert all(
        chars(of(side("after"), q, "staged")) < chars(of(side("before"), q, "staged"))
        for q in LETTERS
    )
    assert (
        "the median of the characters that the staged runs were given is lower after in each "
        "of the five" in entry
    )

    # The development questions: the comparison that is kept says passed.
    assert VERDICT + "passed." in (HERE / "regress-dev.md").read_text("utf-8")
    assert [len(runs) for runs in dev_sides().values()] == [30, 30]
    assert (
        "The thirty runs of the development questions passed by the five criteria of the "
        "second set, held against the thirty of 2026-11-23" in entry
    )

    # The sample of the survey: the papers left unanswered stand beside the number.
    files = (SPLIT_AGAIN.with_name("outcomes.jsonl"), SPLIT_AGAIN)
    lines = [read_outcomes(path)[1] for path in files]
    split = [[line["id"] for line in found if line["outcome"] == OK] for found in lines]
    old, new = (tally(found) for found in lines)
    assert split[0] == split[1] and (len(split[1]), new.papers, new.unanswered) == (494, 520, 0)
    assert (old.over_limit, new.over_limit) == (125, 108)
    assert (
        "No paper of the survey's sample was left unanswered: the same 494 of its 520 papers "
        "were split, and 108 of them have a piece of more than 20,000 characters, where 125 had "
        "one." in entry
    )


def test_the_loop_that_asks_has_made_132_runs_by_now_and_asked_in_none():
    # The README of the repository says that no run with the model behind it has been
    # asked by the loop yet. The 102 runs of 2026-11-25 leave it so.
    folders = ("asking-again/dev-after", *(f"more-sections/{folder}" for folder in SETS))
    made = [a for folder in folders for a in counted(attempts_in(RUNS / folder)).values()]
    assert len(made) == 132
    assert all("asked_again" in a.end and a.end["asked_again"] is None for a in made)
    readme = flat((ROOT / "README.md").read_text(encoding="utf-8"))
    assert "No run with the model behind it has been asked by the loop yet." in readme
    assert "the loop asked for the call in none of the 102 runs" in flat(came_back())
