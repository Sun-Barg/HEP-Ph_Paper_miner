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

The last tests hold what results/README.md says of the runs that went wrong, as far as
the report does not say it already: where the passage of eval-15 stands, what its runs
read and what they cost, how the run of eval-13 without an answer ended, which calls
came back as an error, and which runs took more responses than any development run.
"""

import csv
import json
from collections import Counter
from collections.abc import Iterable
from datetime import datetime
from itertools import groupby
from pathlib import Path
from statistics import median

import pytest
from conftest import OWN_PAPER, tar_gz

from hepph_paper_miner.agent.origin import file_digest
from hepph_paper_miner.eval import report
from hepph_paper_miner.eval.conditions import differences
from hepph_paper_miner.eval.grade import Record, grade, parent_of
from hepph_paper_miner.eval.questions import Question, load_questions
from hepph_paper_miner.eval.report import cost_of
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


def runs_of(records: list[Attempt], question_id: str, toolset: str) -> dict[int, Attempt]:
    """The runs of one question with one layout, by repetition."""
    cell = (question_id, toolset)
    return {a.cell.repeat: a for a in records if (a.cell.question_id, a.cell.toolset) == cell}


def results_of(attempt: Attempt) -> list[tuple[str, dict]]:
    """The calls of a run that came back with a result, in the order they were made."""
    return [
        (call["name"], call["arguments"])
        for turn in attempt.turns
        for call in turn["tools"]
        if call["status"] == "ok"
    ]


def sections_read(attempt: Attempt) -> list[str]:
    """The sections a staged run was given: one for each read that came back."""
    return [
        arguments["section_id"] for name, arguments in results_of(attempt) if name == "read_section"
    ]


def ended(attempt: Attempt) -> tuple[str, int]:
    """Why a run ended, and with which response."""
    return attempt.end["reason"], attempt.end["turns"]


def read_from_cache(attempt: Attempt) -> int:
    return attempt.end["cache_read_input_tokens"]


def input_tokens(attempt: Attempt) -> int:
    """All the input of a run, as the report counts it: new, written to the cache, read from it."""
    end = attempt.end
    return end["input_tokens"] + end["cache_creation_input_tokens"] + read_from_cache(attempt)


def cost(attempts: Iterable[Attempt]) -> float:
    """What runs cost in dollars, worked out as the report works it out, to the cent."""
    return round(sum(cost_of(a.turns, a.run["model"]["model"]) for a in attempts), 2)


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


# --- what results/README.md says of the runs that went wrong -----------------------------


def test_the_passage_of_eval_15_is_text_of_section_4_that_no_subsection_holds(questions):
    (evidence,) = next(question for question in questions if question.id == "eval-15").evidence
    sections = {section.section_id: section for section in own_paper().sections}
    # Section 4 begins with 1,072 characters of its own, before the heading of 4.1.
    assert (evidence.section_id, sections["4.1"].heading_at) == ("4", 1072)
    assert sections["4"].text.index(evidence.anchor) + len(evidence.anchor) <= 1072
    assert not any(evidence.anchor in sections[name].text for name in ("4.1", "4.2", "4.3"))
    # Every section of this paper that has subsections begins with such text: this is
    # where the heading of its first subsection stands.
    first_heading: dict[str, int] = {}
    for section in sections.values():
        if section.level == 2:
            first_heading.setdefault(parent_of(section.section_id), section.heading_at)
    assert first_heading == {"2": 292, "3": 1804, "4": 1072, "6": 926, "7": 792}


def test_one_staged_run_of_eval_15_read_section_4_itself_and_was_given_the_passage(
    questions, records
):
    question = next(question for question in questions if question.id == "eval-15")
    papers = {OWN: own_paper()}

    def passage_given(attempt: Attempt) -> bool | None:
        record = Record(attempt.run, attempt.turns, attempt.end)
        return grade(record, question, papers).access.met

    staged = runs_of(records, "eval-15", "staged")
    read = {repeat: sections_read(attempt) for repeat, attempt in staged.items()}
    # All three read the three subsections of section 4 and went on to other sections.
    # Only the first then read the section itself: its thirteenth read.
    assert all({"4.1", "4.2", "4.3"} <= set(sections) for sections in read.values())
    assert {n: "4" in sections for n, sections in read.items()} == {1: True, 2: False, 3: False}
    assert read[1].index("4") + 1 == 13
    assert {n: passage_given(a) for n, a in staged.items()} == {1: True, 2: False, 3: False}
    steps = [("answered", 10), ("answered", 12), ("turn_limit", 12)]
    assert [ended(staged[n]) for n in (1, 2, 3)] == steps
    # A flat run reads the whole paper in one call, and answers with its second response.
    flat = runs_of(records, "eval-15", "flat")
    assert {n: passage_given(a) for n, a in flat.items()} == {1: True, 2: True, 3: True}
    assert {ended(attempt) for attempt in flat.values()} == {("answered", 2)}
    # The staged runs were given fewer characters and took 3.7 times the input tokens.
    # More than two thirds of those were read from the cache, which costs little: the
    # three runs cost the same in both layouts.
    tokens = [median(map(input_tokens, runs.values())) for runs in (staged, flat)]
    assert tokens == [251330, 67581] and round(tokens[0] / tokens[1], 1) == 3.7
    assert all(read_from_cache(a) > 2 / 3 * input_tokens(a) for a in staged.values())
    assert (cost(staged.values()), cost(flat.values())) == (0.51, 0.51)


def test_the_run_of_eval_13_without_an_answer_read_what_the_others_read_and_ended_with_text(
    records,
):
    staged = runs_of(records, "eval-13", "staged")
    assert results_of(staged[3]) == results_of(staged[1]) == results_of(staged[2])
    # Its third response is text and no call: the loop reads no answer out of a text.
    last = staged[3].turns[-1]
    assert (last["stop_reason"], last["blocks"]) == ("end_turn", ["thinking", "text"])
    assert last["tools"] == [] and ended(staged[3]) == ("no_answer", 3)


def test_the_ten_calls_that_ended_in_an_error_were_asked_for_what_is_not_there(records):
    errors = [
        (str(attempt.cell), call["name"], call["error_kind"], call["arguments"])
        for attempt in records
        for turn in attempt.turns
        for call in turn["tools"]
        if call["status"] == "error"
    ]
    assert Counter(kind for _, _, kind, _ in errors) == {"invalid_arguments": 5, "not_found": 5}
    # "section" where the tool has "section_id": in every staged run of eval-08, and in
    # two of eval-15.
    refused = [
        (run, name, sorted(given)) for run, name, kind, given in errors if kind != "not_found"
    ]
    runs = ("eval-08 staged 1", "eval-08 staged 2", "eval-15 staged 2")
    runs += ("eval-08 staged 3", "eval-15 staged 3")
    assert refused == [(run, "read_section", ["arxiv_id", "section"]) for run in runs]
    # A second or third version of the paper of eval-17, where every search of its runs
    # that listed the paper listed the first.
    missing = Counter(
        (run, given["arxiv_id"]) for run, _, kind, given in errors if kind == "not_found"
    )
    assert missing == {
        ("eval-17 staged 1", "2101.11027v2"): 1,
        ("eval-17 flat 1", "2101.11027v3"): 1,
        ("eval-17 flat 1", "2101.11027v2"): 1,
        ("eval-17 flat 2", "2101.11027v2"): 1,
        ("eval-17 flat 3", "2101.11027v2"): 1,
    }
    listed = {
        paper
        for attempt in records
        for turn in attempt.turns
        for call in turn["tools"]
        if attempt.cell.question_id == "eval-17"
        for paper in (call.get("first_line") or {}).get("ids", ())
        if paper.startswith("2101.11027")
    }
    assert listed == {"2101.11027v1"}


def test_only_runs_of_eval_15_and_eval_17_took_more_than_six_responses(records):
    # Six is the most a run took on the development questions (test_conditions.py), and
    # the limit of twelve was kept from there. Here it ended one run.
    longer = {
        str(attempt.cell): attempt.end["turns"] for attempt in records if attempt.end["turns"] > 6
    }
    assert longer == {
        "eval-15 staged 1": 10,
        "eval-15 staged 2": 12,
        "eval-15 staged 3": 12,
        "eval-17 staged 1": 11,
        "eval-17 staged 2": 8,
        "eval-17 staged 3": 9,
        "eval-17 flat 2": 8,
    }
    assert [str(a.cell) for a in records if a.end["reason"] == "turn_limit"] == ["eval-15 staged 3"]


def test_four_calls_carried_an_argument_that_no_tool_had_and_two_reads_returned_more(records):
    # What the tool texts were changed for after the evaluation (README): the SDK dropped
    # an argument beyond the schema, and the call was answered as if it were not there.
    had = {
        "search_papers": {"query", "author", "category", "year_from", "year_to", "max_results"},
        "get_outline": {"arxiv_id"},
        "read_section": {"arxiv_id", "section_id", "start"},
        "read_paper": {"arxiv_id", "start"},
    }
    beyond = [
        (attempt, call, name)
        for attempt in records
        for turn in attempt.turns
        for call in turn["tools"]
        if call["name"] in had
        for name in sorted(set(call["arguments"]) - had[call["name"]])
    ]
    counted = Counter((call["name"], name, call["status"]) for _, call, name in beyond)
    assert counted == {
        ("read_section", "end", "ok"): 2,
        ("read_paper", "end", "error"): 1,  # not_found, for the version it asked for
        ("read_section", "max_results", "ok"): 1,
        # "section" for "section_id": refused all the same, because section_id was missing.
        ("read_section", "section", "error"): 5,
    }
    # The two reads that came back: asked for 5,100 and 5,200 characters, given 19,821.
    more = []
    for attempt, call, name in beyond:
        if (name, call["status"]) == ("end", "ok"):
            asked = call["arguments"]["end"] - call["arguments"]["start"]
            given = call["first_line"]["stop"] - call["first_line"]["start"]
            more.append((str(attempt.cell), asked, given, given - asked))
    assert more == [
        ("eval-04 staged 2", 5100, 19821, 14721),
        ("eval-04 staged 3", 5200, 19821, 14621),
    ]


# --- what the READMEs say of the cost, the rule and the searches -------------------------


def test_the_factor_between_the_costs_of_the_layouts_belongs_to_the_cache(records):
    layouts = {name: [a for a in records if a.cell.toolset == name] for name in ("staged", "flat")}
    assert {name: cost(runs) for name, runs in layouts.items()} == {"staged": 2.78, "flat": 10.90}
    # The same usage without the cache: every input token at the plain price.
    price = report.PRICES["claude-sonnet-5-5"]

    def plain(runs: list[Attempt]) -> float:
        tokens = sum(input_tokens(a) for a in runs), sum(a.end["output_tokens"] for a in runs)
        return round((tokens[0] * price["input"] + tokens[1] * price["output"]) / 1_000_000, 2)

    assert {name: plain(runs) for name, runs in layouts.items()} == {"staged": 5.00, "flat": 10.49}
    assert (round(10.90 / 2.78, 1), round(10.49 / 5.00, 1)) == (3.9, 2.1)
    # Why: a flat run writes much to the cache and reads little back, a staged run reads
    # back more than it writes.
    written = {n: sum(a.end["cache_creation_input_tokens"] for a in r) for n, r in layouts.items()}
    read = {name: sum(read_from_cache(a) for a in runs) for name, runs in layouts.items()}
    assert written == {"staged": 832_385, "flat": 4_147_361}
    assert read == {"staged": 1_384_589, "flat": 876_362}


def test_no_answer_of_the_evaluation_can_come_out_right_by_the_rule(questions):
    # grade.py says "right" only when the key leaves nothing to a person. Every question
    # here leaves something, so that the rule sent all 118 answers to a person says
    # nothing about the answers.
    assert len(questions) == 20
    assert all(question.answer_key.get("by_hand") for question in questions)


def test_no_search_in_the_records_was_answered_with_the_error_feed_of_arxiv():
    # Until e13cb0d the error feed in its https form was read as a search: one entry
    # counted, no paper shown. The names of the tool texts were kept through that change
    # because no recorded run met it (README, pre-registration Section 10).
    folders = [RUNS, *sorted(path for path in (RUNS.parent / "dev").iterdir() if path.is_dir())]
    lines = [
        json.loads(line)
        for folder in folders
        for path in sorted(folder.glob("*.jsonl"))
        for line in path.read_text(encoding="utf-8").splitlines()
    ]
    searches = [
        call
        for line in lines
        if line["record"] == "turn"
        for call in line["tools"]
        if call["name"] == "search_papers"
    ]
    back = [call["first_line"] for call in searches if call["status"] == "ok"]
    assert (len(searches), len(back)) == (118, 115)
    nothing_shown = [line for line in back if line["shown"] == 0]
    assert len(nothing_shown) == 41 and all(line["total"] == 0 for line in nothing_shown)
