"""The judge held against the grades by hand: the report, what it refuses, and the files of the
evaluation it will be made from.

No network and no LLM. The records of the judge are written by judge.py itself, with a judge
that answers from a script, so the report is made from the records the command writes.
"""

import csv
import dataclasses
import json
from pathlib import Path

import pytest

from hepph_paper_miner.agent.model import Reply
from hepph_paper_miner.agent.origin import file_digest
from hepph_paper_miner.eval import agree, judge, sheet
from hepph_paper_miner.eval.agree import (
    AgreeError,
    Judged,
    by_cell,
    h2,
    majority,
    make,
    read_controls,
    rule_of,
)
from hepph_paper_miner.eval.grade import BY_HAND, RIGHT, WRONG
from hepph_paper_miner.eval.questions import load_questions
from hepph_paper_miner.eval.sheet import counted_attempts, read_grades

ROOT = Path(__file__).parent.parent
PAPER = "2501.00001v2"
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
    "invented_content",
)


def question(name: str) -> dict:
    return {
        "id": name,
        "question": f"What value does the paper give for {name}?",
        "type": "single_section",
        "gold_papers": [PAPER],
        "gold_evidence": {"need": "all", "items": [{"arxiv_id": PAPER, "section_id": "2.1"}]},
        "expect_found": True,
        "reference_answer": f"The value of {name} is 1.5.",
        # A number the rule checks, and a point it leaves to a person.
        "answer_key": {
            "numbers": [{"label": "the value", "value": 1.5}],
            "by_hand": ["what the value is of"],
        },
        "accept_note": f"Right if it gives 1.5 for {name}.",
        "abstract_sufficient": False,
    }


def run_record(folder: Path, name: str, toolset: str, repeat: int, digest: str, answer: bool):
    """A finished record of a run, with only what the sheet and the report read."""
    run_id = f"2026111{repeat}T00000{len(list(folder.glob('*.jsonl')))}Z_{name}_{toolset}"
    run = {
        "record": "run",
        "run_id": run_id,
        "question_id": name,
        "toolset": toolset,
        "repeat": repeat,
        "questions": {"file": "questions.jsonl", "sha256": digest},
    }
    given = None
    if answer:
        given = {
            "answer": f"{name} by {toolset} in {repeat}",
            "found": True,
            "evidence": [{"arxiv_id": PAPER, "section_id": "2.1"}],
        }
    end = {"record": "end", "run_id": run_id, "reason": "answered" if given else "turn_limit"}
    end["answer"] = given
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"{run_id}.jsonl").write_text(
        json.dumps(run) + "\n" + json.dumps(end) + "\n", "utf-8"
    )


def control(name, of, answer, found="true", base="", why="숫자 틀림", kind="임의 오답") -> dict:
    return {
        "id": name,
        "question_id": of,
        "kind": kind,
        "found": found,
        "answer": answer,
        "grade": "wrong",
        "why_wrong": why,
        "detail": f"how {name} is wrong",
        "base_number": base,
        "invented_content": "no",
    }


def write_csv(path: Path, columns, rows: list[dict]) -> Path:
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, columns, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    return path


def read_csv(path: Path) -> list[dict]:
    with path.open(encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def reply(verdict, why="Said so.", **more) -> Reply:
    values = {
        "stop_reason": "end_turn",
        "text": json.dumps({"verdict": verdict, "why": why}),
        "tool_calls": (),
        "blocks": ("text",),
        "usage": {"input_tokens": 1000, "output_tokens": 100},
        "content": None,
        "model": "claude-sonnet-5-5",
    }
    return Reply(**{**values, **more})


class Scripted:
    """A judge that answers from a table: the answer in a request, and how often it was asked."""

    def __init__(self, table) -> None:
        self._table = table
        self._asked: dict[str, int] = {}

    @property
    def settings(self) -> dict:
        return {
            "model": "claude-sonnet-5-5",
            "thinking": {"type": "adaptive"},
            "effort": "high",
            "max_tokens": 16000,
        }

    async def ask(self, system: str, message: str, schema: dict) -> Reply:
        answer = message.split('">\n', 1)[1].rsplit("\n</answer>", 1)[0]
        self._asked[answer] = self._asked.get(answer, 0) + 1
        script, asked = self._table.get(answer, ()), self._asked[answer] - 1
        # What the table does not say is "right".
        said = script[asked] if asked < len(script) else "right"
        return said if isinstance(said, Reply) else reply(said, f"{said}: {answer}")


@pytest.fixture(autouse=True)
def committed_code(monkeypatch):
    monkeypatch.setattr(judge, "code_version", lambda: {"commit": "c0ffee", "modified": False})


@pytest.fixture
def given(tmp_path) -> dict:
    """Two questions, their twelve runs (one without an answer), a graded sheet and controls."""
    questions = tmp_path / "questions.jsonl"
    questions.write_text("".join(json.dumps(question(q)) + "\n" for q in ("q1", "q2")), "utf-8")
    digest = file_digest(questions)
    runs = tmp_path / "runs"
    for repeat in (1, 2, 3):
        for name in ("q1", "q2"):
            for toolset in ("staged", "flat"):
                answered = (name, toolset, repeat) != ("q2", "staged", 3)
                run_record(runs, name, toolset, repeat, digest, answered)
    paths = {"sheet": tmp_path / "grading.csv", "key": tmp_path / "key.csv"}
    argv = ["--questions", str(questions), "--runs", str(runs), "--seed", "1"]
    assert sheet.main([*argv, "--sheet", str(paths["sheet"]), "--key", str(paths["key"])]) == 0
    # The rows of q1 come first: 1 to 6, then q2 from 7.
    controls = write_csv(
        tmp_path / "controls.csv",
        CONTROL_COLUMNS,
        [
            control("c1", "q1", "The value is 1.5.", base="2"),
            control("c2", "q2", "The value is 2.5.", why="다른 것을 답함"),
            control(
                "c3", "q1", "The value is 1.5.", found="false", base="3", why="found 표시 틀림"
            ),
        ],
    )
    return {"questions": questions, "runs": runs, "controls": controls, **paths}


def grade(given: dict, wrong: set[str] = frozenset()) -> None:
    """Grade every row right but those of the answers named."""
    rows = read_csv(given["sheet"])
    for row in rows:
        row["grade"] = WRONG if row["answer"] in wrong else RIGHT
    write_csv(given["sheet"], sheet.SHEET_COLUMNS, rows)


def judged_by(given: dict, table: dict, *more: str) -> Path:
    out = given["questions"].parent / "judge" / "record.jsonl"
    argv = [
        "--questions",
        str(given["questions"]),
        "--sheet",
        str(given["sheet"]),
        "--controls",
        str(given["controls"]),
        "--out",
        str(out),
        *more,
    ]
    assert judge.main(argv, Scripted(table)) == 0
    return out


def argv_of(given: dict, record: Path) -> list[str]:
    return [
        "--questions",
        str(given["questions"]),
        "--record",
        str(record),
        "--sheet",
        str(given["sheet"]),
        "--key",
        str(given["key"]),
        "--controls",
        str(given["controls"]),
        "--runs",
        str(given["runs"]),
        "--out",
        str(given["questions"].parent / "report.md"),
    ]


def report_of(given: dict, record: Path) -> str:
    assert agree.main(argv_of(given, record)) == 0
    return (given["questions"].parent / "report.md").read_text("utf-8")


def section(text: str, title: str) -> str:
    """The lines of one section of the report, up to the next title of its level or above."""
    level = title.split(" ")[0]
    after = text.split(f"\n{title}\n", 1)[1]
    stops = [after.find(f"\n{'#' * n} ") for n in range(1, len(level) + 1)]
    stops = [stop for stop in stops if stop >= 0]
    return after[: min(stops)] if stops else after


# The answers of the example and what the scripted judge says of them.
WRONG_BY_HAND = "q2 by staged in 2"
TABLE = {
    "q1 by flat in 1": ["wrong", "wrong", "wrong"],  # right by hand: the two differ
    WRONG_BY_HAND: ["wrong", "wrong", "right"],  # wrong by hand, and the requests part
    "q1 by staged in 1": ["right", "right", "wrong"],  # the verdict agrees, the requests part
    # c1 and c3 are the same text with another "found". Each pass asks c1 before c3, so
    # their requests take turns: c1 is called wrong three times, c3 right three times.
    "The value is 1.5.": ["wrong", "right"] * 3,
    "The value is 2.5.": ["wrong", "right", "wrong"],  # c2
}


@pytest.fixture
def example(given) -> tuple[dict, str]:
    grade(given, {WRONG_BY_HAND})
    return given, report_of(given, judged_by(given, TABLE))


# --- the rows of the sheet -----------------------------------------------------------------


def test_the_rows_are_laid_against_the_grades_by_hand_with_what_calling_all_right_would_give(
    example,
):
    _, text = example
    rows = section(text, "## The rows of the sheet")
    assert "| right | 9 | 1 | 0 |" in rows
    assert "| wrong | 0 | 1 | 0 |" in rows
    # 11 rows; 10 of them right by hand, so a judge that calls everything right agrees on 10.
    assert "The judge's verdict is the grade by hand on 10 of 11 rows." in rows
    assert "A judge that called every answer right would agree on 10 of them." in rows
    assert "All 3 requests said the same on 9 of 11 rows." in rows
    assert "Of the 33 requests, 27 said right, 6 wrong, and 0 gave no verdict" in rows


def test_the_rows_to_read_are_listed_with_every_request_and_none_twice(example, given):
    _, text = example
    numbers = {row["answer"]: row["number"] for row in read_csv(given["sheet"])}
    wrong = section(text, "### Rows graded wrong by hand")
    differ = section(text, "### Rows where the judge's verdict is not the grade by hand")
    other = section(text, "### Other rows on which the requests did not all say the same")
    assert (
        f"Row {numbers[WRONG_BY_HAND]} (q2): wrong by hand; the judge: wrong, wrong, right" in wrong
    )
    assert f"  - 3, right: right: {WRONG_BY_HAND}" in wrong
    assert (
        f"Row {numbers['q1 by flat in 1']} (q1): right by hand; the judge: wrong, wrong, wrong"
        in differ
    )
    assert f"Row {numbers['q1 by staged in 1']} (q1)" in other
    # The row graded wrong, with requests that part, is listed once, under its own title.
    assert f"Row {numbers[WRONG_BY_HAND]} " not in differ + other


def test_an_answer_without_a_verdict_by_more_than_half_has_none_and_is_counted_apart(given):
    grade(given)
    refused = reply("right", stop_reason="refusal", text="I cannot grade this.")
    text = report_of(given, judged_by(given, {"q1 by flat in 2": ["right", "wrong", refused]}))
    rows = section(text, "## The rows of the sheet")
    assert "| right | 10 | 0 | 1 |" in rows
    assert "on 10 of 11 rows" in rows and "1 gave no verdict" in rows
    # The run of that row has no verdict, so its question is not in the table of H2.
    judge_h2 = section(text, "## H2 with the judge's verdicts").split("in place of")[1]
    assert "1 question(s) not in the table: a run of theirs has no verdict." in judge_h2


def test_the_replies_that_held_a_thinking_block_are_counted_where_they_are(given):
    grade(given)
    thought = reply("right", blocks=("thinking", "text"))
    text = report_of(
        given,
        judged_by(
            given,
            {
                "q1 by flat in 2": [thought] * 3,
                "The value is 2.5.": [reply("wrong", blocks=("thinking", "text"))],
            },
        ),
    )
    assert "replies held a thinking block" in section(text, "## The rows of the sheet")
    assert "; 3 of the replies held a thinking block." in section(text, "## The rows of the sheet")
    assert "; 1 of the replies held a thinking block." in section(text, "## The controls")
    assert "4 of the replies held a thinking block" in section(text, "## The requests")


# --- the controls --------------------------------------------------------------------------


def test_the_controls_are_counted_in_all_by_fault_by_making_by_question_and_by_the_rule(example):
    _, text = example
    controls = section(text, "## The controls")
    assert "| all | 3 | 2 | 1 | 1 | 0 |" in controls
    assert "All 3 requests said the same on 2 of 3 controls." in controls
    assert "| found 표시 틀림 | 1 | 0 | 0 | 1 | 0 |" in controls
    assert "| 다른 것을 답함 | 1 | 1 | 0 | 0 | 0 |" in controls
    assert "| from a row of the sheet | 2 | 1 | 1 | 1 | 0 |" in controls
    assert "| written anew | 1 | 1 | 0 | 0 | 0 |" in controls
    assert "| q1 | 2 | 1 | 1 | 1 | 0 |" in controls
    # c1 has the number, so the rule leaves it to a person; c2 lacks it, c3 says found false.
    rule = section(text, "### Against the rule of grade.py")
    assert "| wrong | 2 | 1 | 0 | 1 | 0 |" in rule
    assert "| by_hand | 1 | 1 | 1 | 0 | 0 |" in rule
    missed = section(text, "### Controls not called wrong in every request")
    assert "- c2 (q2, 다른 것을 답함): how c2 is wrong; the judge: wrong, right, wrong" in missed
    assert "- c3 (q1, found 표시 틀림)" in missed and "c1 " not in missed


def test_the_rule_reads_a_control_as_the_answer_of_a_run(given):
    questions = {q.id: q for q in load_questions(given["questions"])}
    found = {c.id: rule_of(questions[c.question_id], c) for c in read_controls(given["controls"])}
    assert found == {"c1": BY_HAND, "c2": WRONG, "c3": WRONG}


# --- H2 --------------------------------------------------------------------------------------


def test_h2_counts_a_run_without_an_answer_as_wrong_by_hand_and_by_the_judge(example):
    _, text = example
    h2_text = section(text, "## H2 with the judge's verdicts")
    by_hand, by_judge = h2_text.split("in place of")
    # q2: staged has one run right by hand of three (one wrong, one without an answer).
    for part in (by_hand, by_judge):
        assert "| staged right | 1 | 0 |" in part
        assert "| staged wrong | 1 | 0 |" in part
    assert "| q1 | 3 / 3 | 3 / 3 | 3 / 3 | 2 / 3 |" in h2_text
    assert "| q2 " not in h2_text


def test_more_than_half_is_more_than_half_and_a_run_without_a_verdict_leaves_it_open():
    assert majority([RIGHT, WRONG]) is False
    assert majority([RIGHT, RIGHT, WRONG]) is True
    assert majority([RIGHT, RIGHT, None]) is None
    assert majority([]) is None


def test_a_key_that_names_a_run_that_does_not_count_is_refused(given):
    grade(given)
    questions = load_questions(given["questions"])
    attempts, _ = counted_attempts(questions, given["runs"], file_digest(given["questions"]))
    hand = read_grades(given["sheet"], given["key"])
    hand.append(dataclasses.replace(hand[0], number=99, run_id="20261111T000000Z_q1_other"))
    with pytest.raises(AgreeError, match="names 20261111T000000Z_q1_other, which is not a run"):
        by_cell(attempts, hand, {g.number: g.grade for g in hand})


def test_a_run_that_handed_in_an_answer_missing_from_the_sheet_is_refused(given):
    grade(given)
    questions = load_questions(given["questions"])
    attempts, _ = counted_attempts(questions, given["runs"], file_digest(given["questions"]))
    hand = read_grades(given["sheet"], given["key"])
    with pytest.raises(AgreeError, match="the sheet lacks"):
        by_cell(attempts, hand[1:], {g.number: g.grade for g in hand[1:]})


# --- what is refused -----------------------------------------------------------------------


def refused(given: dict, record: Path, capsys) -> str:
    assert agree.main(argv_of(given, record)) == 2
    assert not (given["questions"].parent / "report.md").exists()
    return capsys.readouterr().err


def test_a_record_without_its_last_line_is_refused(given, capsys):
    grade(given)
    record = judged_by(given, {})
    lines = record.read_text("utf-8").splitlines(keepends=True)
    record.write_text("".join(lines[:-1]), "utf-8")
    assert "no last line" in refused(given, record, capsys)


def test_a_record_that_asked_only_some_answers_is_refused(given, capsys):
    grade(given)
    record = judged_by(given, {}, "--only", "c1")
    assert "only some of the answers (c1)" in refused(given, record, capsys)


@pytest.mark.parametrize("changed", ["sheet", "controls", "questions"])
def test_a_record_begun_with_other_files_is_refused(given, capsys, changed):
    grade(given)
    record = judged_by(given, {})
    with given[changed].open("a", encoding="utf-8") as stream:
        stream.write("\n")
    assert f"begun with another {changed}" in refused(given, record, capsys)


def test_a_sheet_graded_after_the_judge_was_asked_is_not_the_sheet_it_was_given(given, capsys):
    record = judged_by(given, {})
    grade(given)
    assert "begun with another sheet" in refused(given, record, capsys)


def test_a_sheet_that_is_not_graded_in_full_is_refused(given, capsys):
    record = judged_by(given, {})
    assert "not every row is graded" in refused(given, record, capsys)


def test_two_replies_to_one_request_are_refused(given, capsys):
    grade(given)
    record = judged_by(given, {})
    lines = record.read_text("utf-8").splitlines(keepends=True)
    record.write_text("".join([*lines[:2], lines[1], *lines[2:]]), "utf-8")
    assert "two replies to request 1" in refused(given, record, capsys)


def test_a_record_that_lacks_one_reply_is_refused(given, capsys):
    grade(given)
    record = judged_by(given, {})
    lines = record.read_text("utf-8").splitlines(keepends=True)
    kept = [line for line in lines if not ('"item": "c2"' in line and '"repeat": 3' in line)]
    record.write_text("".join(kept), "utf-8")
    assert "c2: replies to the requests [1, 2], not to each of 3" in refused(given, record, capsys)


def test_a_record_whose_first_line_counts_other_answers_is_refused(given, capsys):
    grade(given)
    record = judged_by(given, {})
    lines = record.read_text("utf-8").splitlines(keepends=True)
    head = json.loads(lines[0])
    head["controls"]["answers"] = 4
    record.write_text(json.dumps(head) + "\n" + "".join(lines[1:]), "utf-8")
    assert "begun with 4 answer(s) of the controls" in refused(given, record, capsys)


def test_a_record_that_lacks_every_reply_on_one_answer_is_refused(given, capsys):
    grade(given)
    record = judged_by(given, {})
    lines = record.read_text("utf-8").splitlines(keepends=True)
    record.write_text("".join(line for line in lines if '"item": "c2"' not in line), "utf-8")
    assert "the answers it holds are not those of the files (c2)" in refused(given, record, capsys)


def test_a_control_not_graded_wrong_is_refused(given, tmp_path):
    rows = read_csv(given["controls"])
    rows[1]["grade"] = "right"
    path = write_csv(tmp_path / "other.csv", CONTROL_COLUMNS, rows)
    with pytest.raises(AgreeError, match="c2: graded 'right', and a control is wrong"):
        read_controls(path)


def test_a_control_made_from_a_row_of_another_question_is_refused(given, capsys):
    rows = read_csv(given["controls"])
    rows[0]["base_number"] = "8"  # a row of q2; c1 is of q1
    write_csv(given["controls"], CONTROL_COLUMNS, rows)
    grade(given)
    record = judged_by(given, {})
    assert "c1: made from row 8, which is not a row of q1" in refused(given, record, capsys)


def test_what_the_judge_wrote_keeps_its_bars_and_stays_on_one_line():
    one = Judged(("wrong",), ("a | b\nc",), 0)
    assert agree._entry("Row 1", one)[1] == "  - 1, wrong: a \\| b c"


# --- the files of the evaluation -----------------------------------------------------------

QUESTIONS = ROOT / "eval_data" / "questions_eval.jsonl"
CONTROLS = ROOT / "eval_data" / "judge_controls_eval.csv"
SHEET = ROOT / "results" / "grading.csv"
KEY = ROOT / "results" / "grading-key.csv"
RUNS = ROOT / "results" / "runs" / "eval"
# The controls of the evaluation, as they were when the pre-registration named them.
CONTROLS_SHA256 = "dcb047f6f0b675bdde502c83ad1b86cdbb02848babd1a1ea7fe9d7e4350c65d4"


def test_h2_by_hand_from_the_sheet_and_the_runs_is_the_table_of_the_report():
    questions = load_questions(QUESTIONS)
    attempts, _ = counted_attempts(questions, RUNS, file_digest(QUESTIONS))
    hand = read_grades(SHEET, KEY)
    pairs = h2(questions, by_cell(attempts, hand, {g.number: g.grade for g in hand}))
    assert pairs == {(True, True): 19, (False, True): 1}
    report = (ROOT / "results" / "report.md").read_text("utf-8")
    assert "| staged right | 19 | 0 |\n| staged wrong | 1 | 0 |" in report


def test_the_controls_of_the_evaluation_are_the_file_the_pre_registration_names():
    assert file_digest(CONTROLS) == CONTROLS_SHA256
    # The pre-registration names this file by the beginning of its digest: the only digest
    # it gives in full is the one of the question file (tests/test_preregistration.py).
    named = (ROOT / "eval_data" / "PREREGISTRATION.md").read_text("utf-8")
    assert f"`{CONTROLS_SHA256[:16]}`" in named
    controls = read_controls(CONTROLS)
    assert len(controls) == 91 and len({c.id for c in controls}) == 91
    assert sum(1 for c in controls if c.kind == "accept_note 오답 조건") == 27
    assert sum(1 for c in controls if c.base) == 71
    assert sum(1 for c in controls if not c.found) == 5
    # Every control made from a row is made from a row of its own question.
    rows = {g.number: g.question_id for g in read_grades(SHEET, KEY)}
    assert all(rows[int(c.base)] == c.question_id for c in controls if c.base)
    each = {
        q.id: sum(1 for c in controls if c.question_id == q.id) for q in load_questions(QUESTIONS)
    }
    assert min(each.values()) >= 3 and max(each.values()) <= 6


def test_the_judge_the_pre_registration_names_is_the_judge_of_the_code():
    named = (ROOT / "eval_data" / "PREREGISTRATION.md").read_text("utf-8")
    assert f"The judge is `{judge.JUDGE_VERSION}` (its texts SHA-256 beginning" in named
    assert f"`{judge.texts_digest()[:16]}`" in named


def test_the_rule_calls_47_controls_of_the_evaluation_wrong_and_leaves_44_to_a_person():
    questions = {q.id: q for q in load_questions(QUESTIONS)}
    rules = [rule_of(questions[c.question_id], c) for c in read_controls(CONTROLS)]
    assert (rules.count(WRONG), rules.count(BY_HAND), rules.count(RIGHT)) == (47, 44, 0)


def test_the_development_record_has_no_grades_by_hand_to_be_held_against(capsys):
    argv = [
        "--questions",
        str(ROOT / "eval_data" / "questions_dev.jsonl"),
        "--record",
        str(ROOT / "results" / "judge" / "dev-j2.jsonl"),
        "--sheet",
        str(ROOT / "results" / "judge" / "dev-sheet.csv"),
        "--key",
        str(ROOT / "results" / "judge" / "dev-sheet-key.csv"),
        "--controls",
        str(ROOT / "eval_data" / "judge_controls_dev.csv"),
        "--runs",
        str(ROOT / "results" / "runs" / "dev" / "diag-3-tool"),
        "--out",
        "unused.md",
    ]
    assert agree.main(argv) == 2
    assert "not every row is graded" in capsys.readouterr().err
    assert not Path("unused.md").exists()


def test_make_reads_none_of_the_controls_a_record_was_not_given(given):
    # A record of the controls alone is not a record of these files: make() refuses it.
    grade(given)
    out = given["questions"].parent / "only-controls.jsonl"
    argv = ["--questions", str(given["questions"]), "--controls", str(given["controls"])]
    assert judge.main([*argv, "--out", str(out)], Scripted({})) == 0
    with pytest.raises(AgreeError, match="begun with another sheet"):
        make(
            given["questions"], out, given["sheet"], given["key"], given["controls"], given["runs"]
        )
