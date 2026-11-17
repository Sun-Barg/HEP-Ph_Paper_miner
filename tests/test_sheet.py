"""The sheet for grading answers by hand: what is on it, what is not, and reading it back.

The records are written here by hand: the sheet reads only their first and last lines.
No network, no LLM.
"""

import csv
import json
from pathlib import Path

import pytest

from hepph_paper_miner.agent.origin import file_digest
from hepph_paper_miner.eval import sheet
from hepph_paper_miner.eval.questions import load_questions
from hepph_paper_miner.eval.run import Attempt
from hepph_paper_miner.eval.sheet import (
    SHEET_COLUMNS,
    SheetError,
    read_grades,
    rows_of,
    write_key,
    write_sheet,
)

PAPER = "2501.00001v2"


def question(name: str) -> dict:
    return {
        "id": name,
        "question": f"What does the paper say about {name}?",
        "type": "single_section",
        "gold_papers": [PAPER],
        "gold_evidence": {"need": "all", "items": [{"arxiv_id": PAPER, "section_id": "2.1"}]},
        "expect_found": True,
        "reference_answer": f"The reference of {name}.",
        "answer_key": {},
        "accept_note": f"What is accepted for {name}.",
        "abstract_sufficient": False,
    }


def questions_file(folder: Path, *names: str) -> Path:
    path = folder / "questions.jsonl"
    path.write_text("".join(json.dumps(question(name)) + "\n" for name in names), "utf-8")
    return path


def record(folder: Path, name: str, toolset: str, repeat: int, digest: str, answer=True) -> Path:
    """A finished record of a run, with only what the sheet reads."""
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
        text = answer if isinstance(answer, str) else f"{name} by {toolset} in {repeat}"
        given = {
            "answer": text,
            "found": True,
            "evidence": [{"arxiv_id": PAPER, "section_id": "2.1"}],
        }
    end = {"record": "end", "run_id": run_id, "reason": "answered" if given else "turn_limit"}
    end["answer"] = given
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{run_id}.jsonl"
    path.write_text(json.dumps(run) + "\n" + json.dumps(end) + "\n", "utf-8")
    return path


def all_runs(tmp_path, names=("q1", "q2"), unanswered=()) -> tuple[Path, Path]:
    tmp_path.mkdir(parents=True, exist_ok=True)
    questions = questions_file(tmp_path, *names)
    digest = file_digest(questions)
    folder = tmp_path / "runs"
    for repeat in (1, 2, 3):
        for name in names:
            for toolset in ("staged", "flat"):
                answer = (name, toolset, repeat) not in unanswered
                record(folder, name, toolset, repeat, digest, answer)
    return questions, folder


def made(tmp_path, *more: str, **kwargs) -> tuple[list[dict], list[dict], list[str]]:
    """Run the command; the rows of the sheet, the rows of the key, and what it printed."""
    questions, folder = all_runs(tmp_path, **kwargs)
    paths = ["--sheet", str(tmp_path / "grading.csv"), "--key", str(tmp_path / "private/key.csv")]
    code = sheet.main(["--questions", str(questions), "--runs", str(folder), *paths, *more])
    assert code == 0
    with (tmp_path / "grading.csv").open(encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.DictReader(stream))
    with (tmp_path / "private/key.csv").open(encoding="utf-8", newline="") as stream:
        keys = list(csv.DictReader(stream))
    return rows, keys, []


# --- what is on the sheet ----------------------------------------------------------------


def test_every_answer_that_counts_is_a_row_and_a_run_without_one_is_not(tmp_path, capsys):
    rows, keys, _ = made(tmp_path, "--seed", "1", unanswered={("q2", "flat", 2)})
    assert [row["number"] for row in rows] == [str(n) for n in range(1, 12)]
    assert [row["question_id"] for row in rows] == ["q1"] * 6 + ["q2"] * 5
    assert [key["number"] for key in keys] == [row["number"] for row in rows]
    assert all(row["question_id"] == key["question_id"] for row, key in zip(rows, keys))
    said = capsys.readouterr().out
    assert "11 answer(s) on the sheet" in said and "(1 without an answer" in said


def test_the_sheet_does_not_say_which_layout_repetition_or_run_a_row_is(tmp_path):
    rows, keys, _ = made(tmp_path, "--seed", "1")
    assert tuple(rows[0]) == SHEET_COLUMNS
    shown = json.dumps(rows)
    for key in keys:
        assert key["run_id"] not in shown
    assert not {"toolset", "repeat", "run_id", "evidence", "rule"} & set(rows[0])
    # The answers here name their layout only so that this test can find them.
    assert {row["answer"] for row in rows} == {
        f"{key['question_id']} by {key['toolset']} in {key['repeat']}" for key in keys
    }


def test_the_question_its_reference_and_what_is_accepted_stand_on_its_first_row(tmp_path):
    rows, _, _ = made(tmp_path, "--seed", "1")
    firsts = [row for row in rows if row["question"]]
    assert [row["number"] for row in firsts] == ["1", "7"]
    assert firsts[1]["reference_answer"] == "The reference of q2."
    assert firsts[1]["accept_note"] == "What is accepted for q2."
    assert all(not row["reference_answer"] for row in rows if not row["question"])
    assert {row["found"] for row in rows} == {"true"}


def test_the_order_within_a_question_is_drawn_and_the_seed_gives_it(tmp_path):
    first, _, _ = made(tmp_path / "a", "--seed", "1")
    again, _, _ = made(tmp_path / "b", "--seed", "1")
    other, _, _ = made(tmp_path / "c", "--seed", "2")
    answers = [[row["answer"] for row in rows] for rows in (first, again, other)]
    assert answers[0] == answers[1] != answers[2]
    assert sorted(answers[0][:6]) == sorted(answers[2][:6])  # the same rows, in another order


def test_an_answer_that_begins_like_a_formula_stays_text(tmp_path):
    questions = questions_file(tmp_path, "q1")
    (q,) = load_questions(questions)
    path = record(tmp_path / "runs", "q1", "flat", 1, file_digest(questions), "=1+1 is two")
    attempt = Attempt(path, *_lines(path))
    write_sheet(rows_of([q], [attempt], 0), tmp_path / "grading.csv")
    with (tmp_path / "grading.csv").open(encoding="utf-8-sig", newline="") as stream:
        (row,) = list(csv.DictReader(stream))
    assert row["answer"] == " =1+1 is two"


def _lines(path: Path) -> tuple[dict, tuple, dict]:
    run, end = [json.loads(line) for line in path.read_text("utf-8").splitlines()]
    return run, (), end


# --- when it does not write the sheet ----------------------------------------------------


def test_it_refuses_before_every_cell_is_done(tmp_path, capsys):
    questions, folder = all_runs(tmp_path)
    next(folder.glob("*_q2_flat.jsonl")).unlink()
    paths = ["--sheet", str(tmp_path / "s.csv"), "--key", str(tmp_path / "k.csv")]
    assert sheet.main(["--questions", str(questions), "--runs", str(folder), *paths]) == 1
    assert "still to run" in capsys.readouterr().err
    assert not (tmp_path / "s.csv").exists() and not (tmp_path / "k.csv").exists()


def test_it_does_not_write_over_a_sheet_or_a_key(tmp_path, capsys):
    questions, folder = all_runs(tmp_path)
    (tmp_path / "k.csv").write_text("graded already")
    paths = ["--sheet", str(tmp_path / "s.csv"), "--key", str(tmp_path / "k.csv")]
    assert sheet.main(["--questions", str(questions), "--runs", str(folder), *paths]) == 2
    assert "there already" in capsys.readouterr().err
    assert (tmp_path / "k.csv").read_text() == "graded already"


def test_it_refuses_runs_of_another_question_file_or_outside_the_plan(tmp_path, capsys):
    questions, folder = all_runs(tmp_path)
    paths = ["--sheet", str(tmp_path / "s.csv"), "--key", str(tmp_path / "k.csv")]
    extra = record(folder, "q1", "flat", 4, file_digest(questions))
    assert sheet.main(["--questions", str(questions), "--runs", str(folder), *paths]) == 1
    assert "outside the plan" in capsys.readouterr().err
    extra.unlink()
    record(folder, "q1", "flat", 1, "another digest")
    assert sheet.main(["--questions", str(questions), "--runs", str(folder), *paths]) == 1
    assert "another question file" in capsys.readouterr().err


# --- reading the graded sheet ------------------------------------------------------------


def graded(tmp_path, change) -> tuple[Path, Path]:
    """Make the sheet, then grade it as a spreadsheet would save it, with `change` applied."""
    made(tmp_path, "--seed", "3")
    path = tmp_path / "grading.csv"
    with path.open(encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.DictReader(stream))
    for row in rows:
        row["grade"] = "Right " if int(row["number"]) % 2 else "wrong"
        row["why_wrong"] = "" if int(row["number"]) % 2 else "misses the second number"
    rows = change(rows)
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
        stream.write(",,,,,,,,,\r\n")  # a spreadsheet may leave an empty line at the end
    return path, tmp_path / "private/key.csv"


def test_grades_are_read_with_the_run_each_is_of(tmp_path):
    path, key = graded(tmp_path, lambda rows: rows)
    grades = read_grades(path, key)
    with key.open(encoding="utf-8", newline="") as stream:
        keys = {int(line["number"]): line for line in csv.DictReader(stream)}
    assert [g.number for g in grades] == list(range(1, 13))
    assert all(g.run_id == keys[g.number]["run_id"] for g in grades)
    assert all(g.toolset == keys[g.number]["toolset"] for g in grades)
    assert [g.grade for g in grades[:2]] == ["right", "wrong"]
    assert grades[1].why_wrong == "misses the second number"


def test_a_row_not_graded_yet_has_no_grade(tmp_path):
    def blank(rows):
        rows[4]["grade"] = " "
        return rows

    assert read_grades(*graded(tmp_path, blank))[4].grade is None


@pytest.mark.parametrize(
    "change, says",
    [
        (lambda rows: rows[:-1], r"no row for number\(s\) 12"),
        (lambda rows: rows + [dict(rows[0])], "there twice"),
        (lambda rows: [*rows[:-1], {**rows[-1], "number": "13"}], "not in the key"),
        (lambda rows: [{**rows[0], "number": "one"}, *rows[1:]], "is not a number"),
        (lambda rows: [{**rows[0], "question_id": "q2"}, *rows[1:]], "not of 'q2'"),
        (lambda rows: [{**rows[0], "grade": "half"}, *rows[1:]], "neither right nor wrong"),
    ],
)
def test_a_sheet_that_does_not_fit_its_key_is_refused(tmp_path, change, says):
    with pytest.raises(SheetError, match=says):
        read_grades(*graded(tmp_path, change))


def test_a_sheet_saved_in_another_encoding_is_refused(tmp_path):
    path, key = graded(tmp_path, lambda rows: rows)
    text = path.read_text(encoding="utf-8-sig").replace("misses", "빠짐")
    path.write_bytes(text.encode("cp949"))
    with pytest.raises(SheetError, match="CSV UTF-8"):
        read_grades(path, key)


def test_the_key_goes_with_its_rows(tmp_path):
    questions = questions_file(tmp_path, "q1")
    (q,) = load_questions(questions)
    path = record(tmp_path / "runs", "q1", "staged", 2, file_digest(questions))
    write_key(rows_of([q], [Attempt(path, *_lines(path))], 0), tmp_path / "key.csv")
    with (tmp_path / "key.csv").open(encoding="utf-8", newline="") as stream:
        (line,) = list(csv.DictReader(stream))
    assert line == {
        "number": "1",
        "question_id": "q1",
        "run_id": path.stem,
        "toolset": "staged",
        "repeat": "2",
        "record": path.name,
    }
