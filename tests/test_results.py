"""The results of the evaluation: the records, the graded sheet, its key and the report.

results/ holds what the evaluation left behind:

    runs/eval/         the public records of its 120 runs, as the runner wrote them
    grading.csv        the sheet on which the maintainer graded every answer by hand
    grading-key.csv    which run each row of the sheet stands for
    report.md          the report that eval.report wrote from the three

The sheet and the key were committed once the last row was graded. These tests hold the
four files against each other, and against the question file, the plan of the runner,
the conditions and the commit that pre-registered the evaluation. Whoever edits one of
them, or adds a record, is told here: what the report says would then stand on files
that no longer say it.

No network and no LLM. Some lines of the report need the text of the papers: whether a
passage was given to a run, and how much paper text a run read. Of the thirteen papers
only the maintainer's own is kept here (tests/fixtures, CC0), so those lines are held up
for the questions about that paper and left out for the others.
"""

import csv
from collections import Counter
from datetime import datetime
from itertools import groupby
from pathlib import Path

import pytest
from conftest import OWN_PAPER, tar_gz

from hepph_paper_miner.agent.origin import file_digest
from hepph_paper_miner.eval import report
from hepph_paper_miner.eval.conditions import differences
from hepph_paper_miner.eval.questions import Question, load_questions
from hepph_paper_miner.eval.run import Attempt, attempts_in, plan
from hepph_paper_miner.eval.sheet import Row, read_grades, read_key, write_key, write_sheet
from hepph_paper_miner.sources.arxiv_latex import PARSER_VERSION, parse_source
from hepph_paper_miner.sources.base import Paper, PaperMeta
from hepph_paper_miner.sources.fixture import FixtureSource

ROOT = Path(__file__).parent.parent
QUESTIONS = ROOT / "eval_data" / "questions_eval.jsonl"
RUNS = ROOT / "results" / "runs" / "eval"
SHEET = ROOT / "results" / "grading.csv"
KEY = ROOT / "results" / "grading-key.csv"
REPORT = ROOT / "results" / "report.md"

OWN = "2610.26648v1"  # the maintainer's paper: the one whose text is in this repository


@pytest.fixture(scope="module")
def questions() -> tuple[Question, ...]:
    return load_questions(QUESTIONS)


@pytest.fixture(scope="module")
def records() -> list[Attempt]:
    """Every record of the folder, oldest first (a run id begins with the time of its start)."""
    found = [attempt for tried in attempts_in(RUNS).values() for attempt in tried]
    return sorted(found, key=lambda attempt: attempt.run["run_id"])


@pytest.fixture(scope="module")
def rows(questions, records) -> list[Row]:
    """The rows of the sheet as the key numbers them, each with its question and its run."""
    by_id = {question.id: question for question in questions}
    by_run = {attempt.run["run_id"]: attempt for attempt in records}
    return [
        Row(number, by_id[line["question_id"]], by_run[line["run_id"]])
        for number, line in sorted(read_key(KEY).items())
    ]


def own_paper() -> Paper:
    data = tar_gz({p.name: p.read_bytes() for p in OWN_PAPER.iterdir() if p.suffix != ".md"})
    meta = PaperMeta(OWN, "The kept paper", ("A",), 2026, "hep-ph", "Abstract.")
    return Paper(meta, parse_source(data), PARSER_VERSION)


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


# --- the records --------------------------------------------------------------------------


def test_the_records_are_the_cells_of_the_plan_each_run_once_and_in_its_order(questions, records):
    cells = plan([question.id for question in questions])
    assert len(cells) == 120
    # One record for each cell and none besides: no run was spoilt, so none was made again.
    assert len(list(RUNS.glob("*.jsonl"))) == len(records) == 120
    assert all(attempt.end is not None and attempt.spoilt is None for attempt in records)
    assert [attempt.cell for attempt in records] == cells
    assert all(attempt.path.name == attempt.run["run_id"] + ".jsonl" for attempt in records)
    # One run at a time: each began when the one before it had ended.
    for before, after in zip(records, records[1:]):
        done = datetime.fromisoformat(before.end["ended_at"])
        assert done <= datetime.fromisoformat(after.run["started_at"]), after.run["run_id"]


def test_every_record_names_the_conditions_the_code_and_the_question_file(questions, records):
    digest = file_digest(QUESTIONS)
    asked = {question.id: question.question for question in questions}
    for attempt in records:
        run = attempt.run
        assert differences(run, attempt.end) == [], run["run_id"]
        assert run["questions"] == {"file": QUESTIONS.name, "sha256": digest}, run["run_id"]
        assert run["question"] == asked[run["question_id"]], run["run_id"]
    # All were made by the commit that pre-registered the evaluation, with no file changed.
    code = {(a.run["code"]["commit"][:7], a.run["code"]["modified"]) for a in records}
    assert code == {("70c7384", False)}


def test_two_runs_handed_in_no_answer_and_both_are_staged(records):
    ends = Counter((attempt.cell.toolset, attempt.end["reason"]) for attempt in records)
    assert ends == {
        ("flat", "answered"): 60,
        ("staged", "answered"): 58,
        ("staged", "no_answer"): 1,
        ("staged", "turn_limit"): 1,
    }
    without = {str(a.cell): a.end["reason"] for a in records if not a.end["answer"]}
    assert without == {"eval-13 staged 3": "no_answer", "eval-15 staged 3": "turn_limit"}


# --- the sheet and its key ---------------------------------------------------------------


def test_the_key_names_every_run_with_an_answer_once(questions, records, rows):
    assert [row.number for row in rows] == list(range(1, 119))
    answered = [attempt.run["run_id"] for attempt in records if attempt.end["answer"]]
    assert sorted(row.attempt.run["run_id"] for row in rows) == sorted(answered)
    # The rows of a question stand together, and the questions in the order of their file.
    together = [name for name, _ in groupby(row.question.id for row in rows)]
    assert together == [question.id for question in questions]


def test_the_key_and_the_sheet_are_what_is_written_for_these_runs(tmp_path, rows):
    # Written again from the records, in the order of the key, the key comes out as it is,
    # and the sheet as it is but for the three columns the grader filled in. So the key
    # says of each run what its record says, and the sheet shows the answers of these runs
    # beside the questions of the file, with nothing changed in either.
    write_key(rows, tmp_path / "key.csv")
    write_sheet(rows, tmp_path / "sheet.csv")
    assert read_csv(tmp_path / "key.csv") == read_csv(KEY)
    filled = dict.fromkeys(("grade", "why_wrong", "note"), "")
    assert read_csv(tmp_path / "sheet.csv") == [{**row, **filled} for row in read_csv(SHEET)]


def test_every_row_is_graded_and_one_answer_is_wrong():
    # read_grades refuses a row that the key does not name, and a grade that is neither.
    verdicts = read_grades(SHEET, KEY)
    assert len(verdicts) == 118
    assert Counter((verdict.toolset, verdict.grade) for verdict in verdicts) == {
        ("staged", "right"): 57,
        ("staged", "wrong"): 1,
        ("flat", "right"): 60,
    }
    (wrong,) = [verdict for verdict in verdicts if verdict.grade == "wrong"]
    run = (wrong.question_id, wrong.toolset, wrong.repeat)
    assert (wrong.number, run) == (86, ("eval-15", "staged", 2))
    assert wrong.why_wrong  # the row says why


# --- the report --------------------------------------------------------------------------

# Rows of the table "By layout" that are counted over the text of every paper a run read.
OVER_EVERY_PAPER = (
    "2a passage given",
    "new paper text per run",
    "repeat reads",
    "responses from the passage to the answer",
)


def without_other_papers(text: str, kept_here: set[str]) -> list[str]:
    """The lines of a report that can be written with the maintainer's paper alone."""
    lines = []
    for line in text.splitlines():
        cells = [cell.strip() for cell in line.strip("|").split("|")]
        if not line or cells[0].startswith(OVER_EVERY_PAPER):
            continue
        if line.startswith("New paper text may count a character twice"):
            continue  # the note that a paper was missing, which is the case here only
        if cells[0].startswith("eval-") and cells[0] not in kept_here:
            line = " | ".join(cells[:-2])  # without "staged passage" and "flat passage"
        lines.append(line)
    return lines


def test_the_report_is_what_the_command_writes_from_these_files(tmp_path, monkeypatch, questions):
    # Paths as the README gives them: the report names the folder of the records.
    monkeypatch.chdir(ROOT)
    argv = ["--questions", "eval_data/questions_eval.jsonl", "--runs", "results/runs/eval"]
    argv += ["--sheet", "results/grading.csv", "--key", "results/grading-key.csv"]
    out = tmp_path / "report.md"
    assert report.main([*argv, "--out", str(out)], source=FixtureSource([own_paper()])) == 0

    kept_here = {question.id for question in questions if set(question.gold_papers) == {OWN}}
    assert kept_here == {"eval-01", "eval-02", "eval-09", "eval-15", "eval-18"}
    written = without_other_papers(out.read_text("utf-8"), kept_here)
    assert written == without_other_papers(REPORT.read_text("utf-8"), kept_here)
    # What is compared holds the question that the layouts answered differently, and the
    # table of why runs were wrong: the one answer graded wrong is about the paper kept here.
    eval_15 = "| eval-15 | not_in_paper | 1 / 3 | 3 / 3 | 109,279 | 147,086 | 1 / 3 | 3 / 3 |"
    assert eval_15 in written
    assert "| answered wrong, its paper was given but not the passage | 1 | 0 |" in written
