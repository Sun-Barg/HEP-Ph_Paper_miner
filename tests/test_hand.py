"""The answers that are graded by hand, and the verdict on each (eval/hand.py).

The records of the runs are written here by hand, with only what the sheet and the rule
read. The sheet of all answers is made by eval.sheet and the record of the judge by
eval.judge, with a judge that answers from a script. No network, no LLM.

The numbers and the sentences of Section 12 of the second pre-registration are read off
the text and held to the code, as tests/test_archives_plan.py does for the rest.
"""

import csv
import hashlib
import json
from pathlib import Path

import pytest
from graded_runs import grade_sheet, judged_by, read_csv, reply, write_csv

from hepph_paper_miner.agent.origin import file_digest
from hepph_paper_miner.eval import hand, judge, sheet
from hepph_paper_miner.eval.grade import BY_HAND, RIGHT, WRONG
from hepph_paper_miner.eval.hand import (
    DIFFER,
    DOUBTED,
    HAND_KEY_COLUMNS,
    REST,
    SAMPLE,
    SAMPLED,
    SEED,
    WIDEN_AT,
    Answer,
    HandError,
    grading,
    order_key,
    picked,
    read_answers,
    read_grading,
    read_hand,
)
from hepph_paper_miner.eval.questions import load_questions
from hepph_paper_miner.eval.sheet import SHEET_COLUMNS, HandGrade
from hepph_paper_miner.survey.plan import load_plan

ROOT = Path(__file__).resolve().parent.parent
TEXT = (ROOT / "eval_data" / "PREREGISTRATION_2.md").read_text(encoding="utf-8")
FLAT = " ".join(TEXT.split())  # a sentence is found wherever it is wrapped
PAPER = "2501.00001v2"
# What an answer of these tests calls its layout, so that the name of a layout on a sheet
# can only have come from the code.
SAID_BY = {"staged": "P", "flat": "Q"}


# --- answers made by hand, for the rules ----------------------------------------------------


def answer(number, question_id, layout, rule=RIGHT, judged=RIGHT) -> Answer:
    """An answer with the two grades it is picked by. The rules read nothing else of it."""
    from types import SimpleNamespace

    attempt = SimpleNamespace(run={"toolset": layout, "run_id": f"run-{number}"})
    return Answer(number, SimpleNamespace(id=question_id), attempt, rule, judged)


def answers_of(count: int, **grades) -> list[Answer]:
    """`count` answers that the rule and the judge both call right, two for a question."""
    return [
        answer(n, f"archives-{(n + 1) // 2:02d}", ("staged", "flat")[n % 2], **grades)
        for n in range(1, count + 1)
    ]


def test_an_answer_on_which_the_rule_and_the_judge_differ_is_graded_by_hand():
    found = picked(
        [
            answer(1, "q1", "staged", rule=WRONG, judged=RIGHT),
            answer(2, "q1", "flat", rule=RIGHT, judged=WRONG),
            answer(3, "q2", "staged", rule=BY_HAND, judged=RIGHT),
        ]
    )
    # The second is (b) as well: the judge calls it wrong.
    assert found == {1: DIFFER, 2: f"{DIFFER} {DOUBTED}", 3: DIFFER}


def test_an_answer_that_the_judge_calls_wrong_or_has_no_verdict_on_is_graded_by_hand():
    found = picked(
        [
            answer(1, "q1", "staged", rule=WRONG, judged=WRONG),
            answer(2, "q1", "flat", rule=RIGHT, judged=None),
            answer(3, "q2", "staged", rule=WRONG, judged=None),
        ]
    )
    # Where both say wrong they do not differ, and where the judge says nothing there is
    # nothing for the rule to differ from: (b) alone.
    assert found == {1: DOUBTED, 2: DOUBTED, 3: DOUBTED}


def test_forty_of_the_others_are_drawn_by_the_hash_of_their_question_and_layout():
    answers = answers_of(100)
    found = picked(answers)
    assert set(found.values()) == {SAMPLED} and len(found) == SAMPLE == 40

    def digest(one: Answer) -> str:
        return hashlib.sha256(f"20261124:{one.question.id}:{one.layout}".encode()).hexdigest()

    smallest = sorted(answers, key=digest)[:40]
    assert set(found) == {one.number for one in smallest}
    # Neither the number of an answer on the sheet nor its run goes into the order.
    moved = [answer(1000 - one.number, one.question.id, one.layout) for one in answers]
    assert {(one.question.id, one.layout) for one in moved if one.number in picked(moved)} == {
        (one.question.id, one.layout) for one in smallest
    }


def test_all_of_the_others_are_drawn_where_they_are_fewer_than_forty():
    assert picked(answers_of(14)) == dict.fromkeys(range(1, 15), SAMPLED)
    assert picked(answers_of(40)) == dict.fromkeys(range(1, 41), SAMPLED)
    assert len(picked(answers_of(41))) == 40


def test_an_answer_of_a_or_b_is_not_drawn_and_takes_none_of_the_forty():
    answers = answers_of(50)
    doubted = {3: (WRONG, RIGHT), 8: (RIGHT, WRONG), 21: (RIGHT, None), 34: (WRONG, WRONG)}
    answers = [
        answer(one.number, one.question.id, one.layout, *doubted.get(one.number, (RIGHT, RIGHT)))
        for one in answers
    ]
    found = picked(answers)
    assert {number: found[number] for number in doubted} == {
        3: DIFFER,
        8: f"{DIFFER} {DOUBTED}",
        21: DOUBTED,
        34: DOUBTED,
    }
    drawn = [number for number, why in found.items() if why == SAMPLED]
    # 46 others, of which forty are drawn: every answer of (c) is right by both.
    assert len(drawn) == 40 and not set(drawn) & set(doubted)
    by_number = {one.number: one for one in answers}
    assert all((by_number[n].rule, by_number[n].judge) == (RIGHT, RIGHT) for n in drawn)


def test_the_order_is_the_one_the_text_writes_out():
    assert order_key("archives-07", "flat") == (
        hashlib.sha256(b"20261124:archives-07:flat").hexdigest()
    )
    assert order_key("archives-07", "flat") != order_key("archives-07", "staged")
    assert SEED == load_plan(ROOT / "eval_data" / "survey_plan.json").seed == 20261124
    assert (
        "(c) forty of the others, or all of them where they are fewer: those with the "
        f"smallest SHA-256 of `{SEED}:<question>:<layout>`"
    ) in FLAT
    assert (
        "(a) every answer on which the rule and the judge differ, (b) every answer that the "
        "judge calls wrong or has no verdict on"
    ) in FLAT


def test_three_requests_of_the_judge_and_the_verdict_of_two_or_three_of_them():
    assert "three requests for every answer of the sheet that `eval.sheet` writes" in FLAT
    assert "its verdict is the one that two or three of them gave" in FLAT
    assert judge.REPEATS == 3
    assert judge.verdict_of([RIGHT, WRONG, RIGHT], 3) == RIGHT
    assert judge.verdict_of([WRONG, WRONG, RIGHT], 3) == WRONG
    assert judge.verdict_of([RIGHT, WRONG, None], 3) is None


# --- the verdict, and the rule of three -----------------------------------------------------


def graded(number: int, grade: str | None) -> HandGrade:
    return HandGrade(number, "q", f"run-{number}", "staged", 1, grade, "", "")


def test_the_verdict_is_the_grade_by_hand_where_there_is_one_and_the_judges_otherwise():
    assert (
        "The verdict on an answer is the grade by hand where there is one, and the verdict "
        "of the judge otherwise. A run without an answer is wrong."
    ) in FLAT
    answers = answers_of(50)
    answers[2] = answer(3, "archives-02", "flat", rule=RIGHT, judged=WRONG)
    why = picked(answers)
    first = {number: graded(number, RIGHT) for number in why}
    # Two answers of (c) against the judge: fewer than three, so the rest keeps the judge's.
    drawn = [number for number, mark in why.items() if mark == SAMPLED]
    for number in drawn[:2]:
        first[number] = graded(number, WRONG)
    made = grading(answers, why, first, None)
    assert (made.sampled, made.differing, made.widened) == (40, 2, False)
    by_number = {one.answer.number: one for one in made.graded}
    assert by_number[3].verdict == RIGHT and by_number[3].answer.judge == WRONG  # by hand
    assert by_number[drawn[0]].verdict == WRONG and by_number[drawn[2]].verdict == RIGHT
    left = [one for one in made.graded if one.picked is None]
    assert len(left) == 9 and all((one.hand, one.verdict) == (None, RIGHT) for one in left)
    assert made.verdicts() == {f"run-{n}": by_number[n].verdict for n in by_number}


def test_three_grades_of_c_against_the_judge_and_every_answer_is_graded_by_hand():
    assert (
        "If the grade by hand differs from the verdict of the judge in three or more of the "
        "answers of (c), every answer is graded by hand, and the grades by hand are the "
        "verdicts."
    ) in FLAT
    assert WIDEN_AT == 3
    answers = answers_of(50)
    why = picked(answers)
    first = {number: graded(number, RIGHT) for number in why}
    for number in list(why)[:3]:
        first[number] = graded(number, WRONG)
    left = [one.number for one in answers if one.number not in why]
    with pytest.raises(HandError, match=r"in 3 of the 40 answer\(s\) of \(c\): every answer"):
        grading(answers, why, first, None)
    rest = {number: graded(number, None) for number in left}
    with pytest.raises(HandError, match=r"10 row\(s\) of the answers that are left"):
        grading(answers, why, first, rest)
    rest = {number: graded(number, WRONG if number == left[0] else RIGHT) for number in left}
    made = grading(answers, why, first, rest)
    assert made.widened and all(one.hand is not None for one in made.graded)
    by_number = {one.answer.number: one for one in made.graded}
    assert by_number[left[0]].verdict == WRONG and by_number[left[0]].picked == REST
    assert sum(1 for one in made.graded if one.verdict == WRONG) == 4


def test_a_sheet_of_the_rest_is_no_part_of_the_verdicts_unless_the_rule_asks_for_it():
    answers = answers_of(50)
    why = picked(answers)
    first = {number: graded(number, RIGHT) for number in why}
    left = [one.number for one in answers if one.number not in why]
    rest = {number: graded(number, WRONG) for number in left}
    with pytest.raises(HandError, match="its grades are no part of the verdicts"):
        grading(answers, why, first, rest)
    # Nor where no answer is left: fourteen answers are all on the first sheet.
    few = answers_of(14)
    all_wrong = {number: graded(number, WRONG) for number in range(1, 15)}
    made = grading(few, picked(few), all_wrong, None)
    assert (made.differing, made.widened) == (14, True)
    assert all(one.verdict == WRONG for one in made.graded)


def test_a_row_that_is_not_graded_stops_everything():
    answers = answers_of(6)
    why = picked(answers)
    first = {number: graded(number, None if number in (2, 5) else RIGHT) for number in why}
    with pytest.raises(HandError, match=r"2 row\(s\) are not graded yet \(the first: number 2\)"):
        grading(answers, why, first, None)


# --- the files ------------------------------------------------------------------------------


def question(name: str) -> dict:
    return {
        "id": name,
        "question": f"What value does arXiv:{PAPER} give for {name}?",
        "type": "named_first",
        "gold_papers": [PAPER],
        "gold_evidence": {"need": "all", "items": [{"arxiv_id": PAPER, "section_id": "2.1"}]},
        "expect_found": True,
        "reference_answer": f"The value of {name} is 1.5.",
        # Numbers alone, as a question of the second evaluation has them: the rule says
        # right or wrong of every answer.
        "answer_key": {"numbers": [{"label": "the value", "value": 1.5}]},
        "accept_note": f"It has to give 1.5 for {name}.",
        "abstract_sufficient": False,
    }


def run_record(folder: Path, name: str, toolset: str, digest: str, text: str | None) -> Path:
    """A finished record of the one run of a cell, with only what is read of it here."""
    run_id = f"20261201T0000{len(list(folder.glob('*.jsonl'))):02d}Z_{name}_{toolset}"
    run = {
        "record": "run",
        "run_id": run_id,
        "question_id": name,
        "toolset": toolset,
        "repeat": 1,
        "questions": {"file": "questions.jsonl", "sha256": digest},
    }
    given = None
    if text is not None:
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


def said(name: str, toolset: str, value: str = "1.5") -> str:
    """The answer of a cell in these tests: one text for every cell."""
    return f"{name} {SAID_BY[toolset]}: the value is {value}."


@pytest.fixture(autouse=True)
def committed_code(monkeypatch):
    monkeypatch.setattr(judge, "code_version", lambda: {"commit": "c0ffee", "modified": False})


def build(folder: Path, questions: int, answers: dict | None = None, table: dict | None = None):
    """The files of an evaluation of `questions` questions: the records, the sheet of all
    answers with its key, and the record of the judge.

    `answers` names the text of a cell where it is not `said` of it, and None where its run
    handed in no answer. `table` is what the judge says, by the text of an answer.
    """
    folder.mkdir(parents=True, exist_ok=True)
    names = [f"archives-{n:02d}" for n in range(1, questions + 1)]
    path = folder / "questions.jsonl"
    path.write_text("".join(json.dumps(question(name)) + "\n" for name in names), "utf-8")
    digest = file_digest(path)
    runs = folder / "runs"
    for at, name in enumerate(names):
        for toolset in (("staged", "flat"), ("flat", "staged"))[at % 2]:
            text = (answers or {}).get((name, toolset), said(name, toolset))
            run_record(runs, name, toolset, digest, text)
    files = {"folder": folder, "questions": path, "runs": runs}
    files |= {"sheet": folder / "answers.csv", "key": folder / "answers-key.csv"}
    argv = ["--questions", str(path), "--runs", str(runs), "--repeats", "1", "--seed", "7"]
    assert sheet.main([*argv, "--sheet", str(files["sheet"]), "--key", str(files["key"])]) == 0
    files["judge"] = judged_by(path, files["sheet"], folder / "judge.jsonl", table or {})
    files |= {"hand_sheet": folder / "hand.csv", "hand_key": folder / "private" / "hand-key.csv"}
    files |= {"rest_sheet": folder / "rest.csv", "rest_key": folder / "private" / "rest-key.csv"}
    return files


def again(files: dict, table: dict) -> Path:
    """Another pass of the judge over the sheet as it lies now."""
    return judged_by(files["questions"], files["sheet"], files["folder"] / "again.jsonl", table)


def arguments(files: dict, *, rest: bool = False) -> list[str]:
    names = ["questions", "runs", "sheet", "key", "judge", "hand_sheet", "hand_key"]
    names += ["rest_sheet", "rest_key"] if rest else []
    return [part for name in names for part in (f"--{name.replace('_', '-')}", str(files[name]))]


# What the judge says in these tests, and what the answers are: thirty questions and sixty
# cells, one of them without an answer.
ODD = {
    ("archives-02", "staged"): said("archives-02", "staged", "2.5"),  # the rule: wrong
    ("archives-03", "flat"): said("archives-03", "flat", "2.5"),  # the rule: wrong
    ("archives-05", "staged"): None,  # no answer
}
JUDGED = {
    said("archives-03", "flat", "2.5"): (WRONG, WRONG, WRONG),  # both wrong: (b)
    said("archives-04", "staged"): (WRONG, RIGHT, WRONG),  # the rule right: (a) and (b)
    said("archives-06", "flat"): (RIGHT, WRONG, RIGHT),  # right by two of three
    said("archives-07", "flat"): (reply(RIGHT, stop_reason="refusal"), WRONG, RIGHT),  # none
}


@pytest.fixture
def files(tmp_path) -> dict:
    return build(tmp_path, 30, ODD, JUDGED)


def test_the_answers_are_read_with_what_the_rule_and_the_judge_say(files):
    answers, attempts, state = read_answers(
        *(files[n] for n in ("questions", "runs")), *(files[n] for n in ("sheet", "key", "judge"))
    )
    assert len(attempts) == 60 and len(answers) == 59
    assert [one.number for one in answers] == list(range(1, 60))
    by_cell = {(one.question.id, one.layout): one for one in answers}
    assert ("archives-05", "staged") not in by_cell
    grades = {cell: (one.rule, one.judge) for cell, one in by_cell.items()}
    assert grades[("archives-02", "staged")] == (WRONG, RIGHT)
    assert grades[("archives-03", "flat")] == (WRONG, WRONG)
    assert grades[("archives-04", "staged")] == (RIGHT, WRONG)
    assert grades[("archives-06", "flat")] == (RIGHT, RIGHT)
    assert grades[("archives-07", "flat")] == (RIGHT, None)
    assert sum(1 for pair in grades.values() if pair == (RIGHT, RIGHT)) == 55
    # The key of the sheet says which run a number is.
    keys = {int(line["number"]): line["run_id"] for line in read_csv(files["key"])}
    assert all(keys[one.number] == one.run_id for one in answers)


def test_the_command_writes_the_sheet_of_the_picked_answers_and_its_key(files, capsys):
    assert hand.main(arguments(files)) == 0
    out = capsys.readouterr().out
    # 4 answers of (a) or (b), and forty of the other 55.
    assert "44 of the 59 answer(s) are on the sheet" in out and "the other 15 keep" in out
    # Why a row is on the sheet is not said to the person who grades it.
    assert "(a)" not in out and "(b)" not in out and "(c)" not in out
    rows, keys = read_csv(files["hand_sheet"]), read_csv(files["hand_key"])
    assert list(rows[0]) == list(SHEET_COLUMNS) and list(keys[0]) == list(HAND_KEY_COLUMNS)
    assert len(rows) == len(keys) == 44
    assert [row["number"] for row in rows] == [line["number"] for line in keys]
    # The rows are rows of the sheet of all answers: the same numbers, in its order.
    full = {row["number"]: row for row in read_csv(files["sheet"])}
    numbers = [int(row["number"]) for row in rows]
    assert numbers == sorted(numbers)
    for row in rows:
        assert (row["question_id"], row["found"], row["answer"]) == tuple(
            full[row["number"]][name] for name in ("question_id", "found", "answer")
        )
        assert (row["grade"], row["why_wrong"], row["note"]) == ("", "", "")
    marks = {line["question_id"] + " " + line["toolset"]: line for line in keys}
    assert marks["archives-02 staged"]["picked"] == DIFFER
    assert marks["archives-03 flat"]["picked"] == DOUBTED
    assert marks["archives-04 staged"]["picked"] == f"{DIFFER} {DOUBTED}"
    assert marks["archives-07 flat"]["picked"] == DOUBTED
    assert (marks["archives-07 flat"]["rule"], marks["archives-07 flat"]["judge"]) == (
        RIGHT,
        "none",
    )
    assert sum(1 for line in keys if line["picked"] == SAMPLED) == 40
    assert all(
        (line["rule"], line["judge"]) == (RIGHT, RIGHT)
        for line in keys
        if line["picked"] == SAMPLED
    )
    # The forty are those with the smallest hash of the question and the layout.
    others = [
        (q["id"], layout)
        for q in map(json.loads, files["questions"].read_text("utf-8").splitlines())
        for layout in ("staged", "flat")
        if f"{q['id']} {layout}" not in marks or marks[f"{q['id']} {layout}"]["picked"] == SAMPLED
    ]
    others.remove(("archives-05", "staged"))  # it gave no answer
    drawn = sorted(
        others, key=lambda c: hashlib.sha256(f"20261124:{c[0]}:{c[1]}".encode()).hexdigest()
    )[:40]
    assert {f"{name} {layout}" for name, layout in drawn} == {
        cell for cell, line in marks.items() if line["picked"] == SAMPLED
    }


def test_the_sheet_shows_the_question_once_and_nothing_of_why_a_row_is_on_it(files):
    assert (
        "on a sheet that shows the answer and its `found`, and for each question its text, "
        "reference answer and note; not the layout, the run, the rule, the judge, or why "
        "the row is on the sheet"
    ) in FLAT
    assert hand.main(arguments(files)) == 0
    rows = read_csv(files["hand_sheet"])
    shown = [row["question_id"] for row in rows if row["question"]]
    assert shown == list(dict.fromkeys(row["question_id"] for row in rows))
    for row in rows:
        first = bool(row["question"])
        assert bool(row["reference_answer"]) == bool(row["accept_note"]) == first
    text = files["hand_sheet"].read_text("utf-8-sig")
    for hidden in ("staged", "flat", "2026120", "picked", "rule", "judge", SAMPLED + "\n"):
        assert hidden not in text
    # The key says them, and is a file of its own.
    assert files["hand_key"].parent != files["hand_sheet"].parent


def test_a_sheet_that_is_there_is_not_written_over(files, capsys):
    assert hand.main(arguments(files)) == 0
    before = files["hand_sheet"].read_bytes()
    assert hand.main(arguments(files)) == 2
    assert "is there already; move it away first" in capsys.readouterr().err
    assert files["hand_sheet"].read_bytes() == before


def test_the_graded_sheet_is_read_back_and_held_to_the_picks(files):
    assert hand.main(arguments(files)) == 0
    grade_sheet(files["hand_sheet"])
    made, attempts, _ = read_grading(
        *(files[n] for n in ("questions", "runs", "sheet", "key")),
        *(files[n] for n in ("judge", "hand_sheet", "hand_key")),
    )
    assert (made.sampled, made.differing, made.widened) == (40, 0, False)
    assert len(made.graded) == 59 and len(attempts) == 60
    by_cell = {(one.answer.question.id, one.answer.layout): one for one in made.graded}
    # By hand right, whatever the two others said; and the judge's where no hand graded.
    assert by_cell[("archives-03", "flat")].verdict == RIGHT
    assert by_cell[("archives-07", "flat")].verdict == RIGHT
    assert sum(1 for one in made.graded if one.hand is None and one.verdict == RIGHT) == 15


def test_the_second_run_says_that_the_rest_keeps_the_judges_verdict(files, capsys):
    assert hand.main(arguments(files)) == 0
    keys = {line["number"]: line for line in read_csv(files["hand_key"])}
    drawn = [number for number, line in keys.items() if line["picked"] == SAMPLED]
    # Two answers of (c) are wrong by hand, and one of (b), which is no answer of (c).
    wrong = {*drawn[:2], next(n for n, line in keys.items() if line["picked"] == DOUBTED)}
    grade_sheet(files["hand_sheet"], lambda row: WRONG if row["number"] in wrong else RIGHT)
    capsys.readouterr()
    assert hand.main(arguments(files, rest=True)) == 0
    out = capsys.readouterr().out
    assert "differs from the verdict of the judge in 2 of the 40 answer(s) of (c)" in out
    assert "fewer than 3: the 15 answer(s) that were not graded by hand keep the verdict" in out
    assert not files["rest_sheet"].exists() and not files["rest_key"].exists()


def test_the_second_run_writes_the_sheet_of_the_answers_that_are_left(files, capsys):
    assert hand.main(arguments(files)) == 0
    keys = {line["number"]: line for line in read_csv(files["hand_key"])}
    drawn = [number for number, line in keys.items() if line["picked"] == SAMPLED]
    grade_sheet(files["hand_sheet"], lambda row: WRONG if row["number"] in drawn[:3] else RIGHT)
    capsys.readouterr()
    assert hand.main(arguments(files, rest=True)) == 0
    out = capsys.readouterr().out
    assert "in 3 of the 40 answer(s) of (c)" in out
    assert "3 or more: every answer is graded by hand. The 15 that are left are on the sheet" in out
    rest, rest_keys = read_csv(files["rest_sheet"]), read_csv(files["rest_key"])
    assert len(rest) == len(rest_keys) == 15
    assert not {row["number"] for row in rest} & set(keys)
    assert {line["picked"] for line in rest_keys} == {REST}
    assert {(line["rule"], line["judge"]) for line in rest_keys} == {(RIGHT, RIGHT)}
    # Until that sheet is graded there are no verdicts, and then they are all by hand.
    paths = [files[n] for n in ("questions", "runs", "sheet", "key", "judge")]
    paths += [files[n] for n in ("hand_sheet", "hand_key")]
    with pytest.raises(HandError, match="the sheet of the 15 that are left is not given"):
        read_grading(*paths)
    with pytest.raises(HandError, match=r"15 row\(s\) of the answers that are left"):
        read_grading(*paths, files["rest_sheet"], files["rest_key"])
    one = rest[0]["number"]
    grade_sheet(files["rest_sheet"], lambda row: WRONG if row["number"] == one else RIGHT)
    made, _, _ = read_grading(*paths, files["rest_sheet"], files["rest_key"])
    assert made.widened and all(each.hand is not None for each in made.graded)
    assert sum(1 for each in made.graded if each.verdict == WRONG) == 4
    assert sum(1 for each in made.graded if each.picked == REST) == 15
    # The sheet of the rest is not written a second time.
    assert hand.main(arguments(files, rest=True)) == 2
    assert "is there already" in capsys.readouterr().err


def test_the_second_run_refuses_a_sheet_that_is_not_graded(files, capsys):
    assert hand.main(arguments(files)) == 0
    rows = read_csv(files["hand_sheet"])
    grade_sheet(files["hand_sheet"], lambda row: "" if row is rows[4] or row == rows[4] else RIGHT)
    capsys.readouterr()
    assert hand.main(arguments(files, rest=True)) == 1
    assert "1 row(s) are not graded yet" in capsys.readouterr().err
    assert not files["rest_sheet"].exists()


def test_fourteen_answers_are_all_graded_by_hand_and_none_is_left(tmp_path, capsys):
    # The rehearsal: seven questions, fourteen answers, all of them "the others".
    files = build(tmp_path, 7)
    assert hand.main(arguments(files)) == 0
    assert "14 of the 14 answer(s) are on the sheet" in capsys.readouterr().out
    grade_sheet(files["hand_sheet"], lambda row: WRONG)
    assert hand.main(arguments(files, rest=True)) == 0
    out = capsys.readouterr().out
    assert "in 14 of the 14 answer(s) of (c)" in out
    assert "every answer is graded by hand already: no sheet was written" in out
    assert not files["rest_sheet"].exists()


# --- what is refused ------------------------------------------------------------------------


def refused(files: dict, capsys, *, rest: bool = False) -> str:
    capsys.readouterr()
    assert hand.main(arguments(files, rest=rest)) == 1
    assert not files["rest_sheet" if rest else "hand_sheet"].exists()
    return capsys.readouterr().err


def test_a_cell_that_is_still_to_run_is_refused(files, capsys):
    next(files["runs"].glob("*_archives-09_flat.jsonl")).unlink()
    assert "1 cell(s) of the plan are still to run (first: archives-09 flat 1)" in refused(
        files, capsys
    )


def test_a_key_of_other_runs_is_refused(files, capsys):
    path = next(files["runs"].glob("*_archives-05_staged.jsonl"))
    run, end = map(json.loads, path.read_text("utf-8").splitlines())
    end |= {"reason": "answered", "answer": {"answer": "1.5", "found": True, "evidence": []}}
    path.write_text(json.dumps(run) + "\n" + json.dumps(end) + "\n", "utf-8")
    assert "is not the key of the runs that count and gave an answer" in refused(files, capsys)


@pytest.mark.parametrize(
    "change",
    [
        lambda row: row.update(answer=row["answer"].replace("1.5", "1.50")),
        lambda row: row.update(found="false"),
        lambda row: row.update(question_id="archives-30"),
    ],
)
def test_a_sheet_that_does_not_hold_the_answer_of_its_run_is_refused(files, capsys, change):
    # Changed before the judge read it: the judge and the rule would grade two answers.
    rows = read_csv(files["sheet"])
    assert rows[10]["question_id"] != "archives-30" and rows[10]["found"] == "true"
    change(rows[10])
    write_csv(files["sheet"], rows)
    files["judge"] = again(files, JUDGED)
    assert f"answers.csv number {rows[10]['number']}: not the answer of" in refused(files, capsys)


def test_a_sheet_that_changed_after_the_judge_read_it_is_refused(files, capsys):
    rows = read_csv(files["sheet"])
    rows[0]["note"] = "opened and saved"
    write_csv(files["sheet"], rows)
    assert "or with this one before it was changed" in refused(files, capsys)


@pytest.mark.parametrize(
    ("change", "said"),
    [
        (lambda head: head.update(judge_version="j1"), "it is of the judge 'j1', not of 'j2'"),
        (lambda head: head.update(texts_sha256="0" * 64), "it is of the judge 'j2', not of 'j2'"),
        (lambda head: head.update(repeats=1), "it asked every answer 1 time(s), not 3"),
        (lambda head: head.update(only=["sheet-1"]), "it asked only some of the answers"),
        (
            lambda head: head["questions"].update(sha256="0" * 64),
            "it was begun with another question file",
        ),
        (lambda head: head["sheet"].update(answers=58), "its sheet did not have 59 answers"),
    ],
)
def test_a_record_of_the_judge_that_is_not_of_these_files_is_refused(files, capsys, change, said):
    lines = [json.loads(line) for line in files["judge"].read_text("utf-8").splitlines()]
    change(lines[0])
    files["judge"].write_text("".join(json.dumps(line) + "\n" for line in lines), "utf-8")
    assert said in refused(files, capsys)


def test_a_record_of_the_judge_that_is_not_whole_is_refused(files, capsys):
    lines = files["judge"].read_text("utf-8").splitlines()
    files["judge"].write_text("\n".join(lines[:-1]) + "\n", "utf-8")
    assert "it has no last line, so not every request has its reply" in refused(files, capsys)
    # With its last line, and a reply too few.
    kept = [
        line
        for line in lines
        if '"item": "sheet-7", "question_id"' not in line or '"repeat": 3' not in line
    ]
    assert len(kept) == len(lines) - 1
    files["judge"].write_text("\n".join(kept) + "\n", "utf-8")
    assert "sheet-7: replies to the requests [1, 2], not to each of 3" in refused(files, capsys)


def test_a_graded_sheet_of_another_pick_is_refused(files, capsys):
    assert hand.main(arguments(files)) == 0
    grade_sheet(files["hand_sheet"])
    # Another pass of the judge calls one more answer wrong, so other answers are picked:
    # five of (a) or (b), and forty of the other 54.
    files["judge"] = again(files, {**JUDGED, said("archives-20", "staged"): (WRONG,) * 3})
    assert "is not the key of the 45 answer(s)" in refused(files, capsys, rest=True)


def test_a_key_that_says_otherwise_than_the_runs_and_the_judge_is_refused(files):
    assert hand.main(arguments(files)) == 0
    grade_sheet(files["hand_sheet"])
    answers, _, _ = read_answers(
        *(files[n] for n in ("questions", "runs", "sheet", "key", "judge"))
    )
    why = picked(answers)
    first = [one for one in answers if one.number in why]
    assert len(read_hand(files["hand_sheet"], files["hand_key"], first, why)) == 44
    for column, value in (("picked", DIFFER), ("rule", WRONG), ("judge", WRONG)):
        keys = read_csv(files["hand_key"])
        line = next(line for line in keys if line["picked"] == SAMPLED)
        line[column] = value
        changed = files["folder"] / f"key-{column}.csv"
        with changed.open("w", encoding="utf-8", newline="") as stream:
            writer = csv.DictWriter(stream, list(keys[0]))
            writer.writeheader()
            writer.writerows(keys)
        with pytest.raises(HandError, match=f"number {line['number']}: not what the runs"):
            read_hand(files["hand_sheet"], changed, first, why)


def test_the_rule_says_right_or_wrong_of_every_answer_of_these_tests(files):
    # A key of numbers and phrases alone leaves nothing to a person, as the questions of
    # the second evaluation are made: so "the others" are right by the rule and the judge.
    assert "says right or wrong of every answer when a key holds numbers and phrases alone" in FLAT
    assert all(set(q.answer_key) == {"numbers"} for q in load_questions(files["questions"]))
    names = ("questions", "runs", "sheet", "key", "judge")
    answers, _, _ = read_answers(*(files[name] for name in names))
    assert {one.rule for one in answers} == {RIGHT, WRONG}
