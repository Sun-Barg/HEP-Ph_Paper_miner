"""The runs of a changed version held against the runs before: the criteria, what is
refused, and the questions written to show the effect of a change.

No network and no LLM. The criteria are tried on runs written out by hand, one thing
changed at a time. The command is tried on the records of the repository: the thirty
runs the conditions were fixed with stand in for both sides, with the sheet and the
record of the judge that were made for them. Of their papers only the maintainer's own
is kept here, so the passage of dev-03 cannot be told, and the command says so.
"""

import csv
import json
from dataclasses import replace
from pathlib import Path

import pytest
from test_results import OWN, OWN_PAPER, own_paper

from hepph_paper_miner.eval import regress
from hepph_paper_miner.eval.grade import BY_HAND, RIGHT, WRONG, parent_of
from hepph_paper_miner.eval.questions import load_questions, problems_with_evidence
from hepph_paper_miner.eval.regress import (
    FAILED,
    NOT_SHOWN,
    OPEN,
    PASSED,
    SHOWN,
    Facts,
    RegressError,
    comparable,
    criteria,
    effect,
    table,
    text_of,
    verdict,
)
from hepph_paper_miner.eval.run import Cell, attempts_in, plan
from hepph_paper_miner.server import full_text
from hepph_paper_miner.sources.fixture import FixtureSource

ROOT = Path(__file__).parent.parent
DEV = ROOT / "eval_data" / "questions_dev.jsonl"
TARGETS = ROOT / "eval_data" / "questions_target.jsonl"
RUNS = ROOT / "results" / "runs" / "dev"
JUDGED = ROOT / "results" / "judge"

CELLS = plan(["q-1", "q-2"])


def a_side(**changed: dict) -> dict[Cell, Facts]:
    """Twelve runs that do everything asked: q-1 right by the rule, q-2 left to a person.

    `changed` names runs as "q-2 staged 3" does, with what is different about each.
    """
    side = {}
    for cell in CELLS:
        by_hand = cell.question_id == "q-2"
        side[cell] = Facts(
            cell=cell,
            run_id=f"run of {cell}",
            reason="answered",
            turns=4 if cell.toolset == "staged" else 2,
            chars=10_000 if cell.toolset == "staged" else 100_000,
            cost=0.05,
            passage=True,
            rule=BY_HAND if by_hand else RIGHT,
            by_judge=RIGHT if by_hand else None,
        )
    for name, changes in changed.items():
        question_id, layout, repeat = name.split()
        cell = Cell(question_id, layout, int(repeat))
        side[cell] = replace(side[cell], **changes)
    return side


def states(after: dict[Cell, Facts], before: dict[Cell, Facts] | None = None) -> list[str]:
    return [finding.state for finding in criteria(before or a_side(), after, CELLS)]


# --- the criteria ------------------------------------------------------------------------


def test_runs_that_do_what_the_runs_before_did_pass():
    findings = criteria(a_side(), a_side(), CELLS)
    assert [finding.name[0] for finding in findings] == list("12345")
    assert [finding.state for finding in findings] == [PASSED] * 5
    assert verdict(findings) == PASSED


@pytest.mark.parametrize(
    ("changes", "number", "state", "says"),
    [
        ({"reason": "turn_limit"}, 1, FAILED, "q-2 staged 3: ended as turn_limit"),
        ({"passage": False}, 2, FAILED, "q-2 staged 3: the passage was not given"),
        ({"passage": None}, 2, OPEN, "q-2 staged 3: its paper could not be read"),
        ({"rule": WRONG}, 3, FAILED, "q-2 staged 3: the rule calls the answer wrong"),
        ({"by_person": WRONG}, 4, FAILED, "q-2 staged 3: graded wrong by a person"),
        # A person outranks the judge, both ways.
        ({"by_person": WRONG, "by_judge": RIGHT}, 4, FAILED, "graded wrong by a person"),
        ({"by_judge": WRONG}, 4, OPEN, "the judge calls it wrong, and nobody has read it"),
        ({"by_judge": None}, 4, OPEN, "neither a person nor the judge has graded it"),
    ],
)
def test_one_run_that_does_not_is_named_under_its_criterion(changes, number, state, says):
    findings = criteria(a_side(), a_side(**{"q-2 staged 3": changes}), CELLS)
    assert [f.state for f in findings] == [state if n == number else PASSED for n in range(1, 6)]
    (line,) = findings[number - 1].lines
    assert says in line
    assert verdict(findings) == state


def test_a_person_who_calls_an_answer_right_settles_what_the_judge_called_wrong():
    after = a_side(**{"q-2 staged 3": {"by_judge": WRONG, "by_person": RIGHT}})
    assert states(after) == [PASSED] * 5


def test_a_cell_without_a_run_fails_the_first_criterion():
    after = a_side()
    del after[Cell("q-1", "flat", 2)]
    findings = criteria(a_side(), after, CELLS)
    assert findings[0].state == FAILED
    assert findings[0].lines == ("q-1 flat 2: no run that counts",)


def test_an_answer_the_rule_called_right_before_has_to_be_right_by_the_rule_now():
    # q-1 was right by the rule in all three runs of each layout. Left to a person now,
    # it has lost something a rule could check.
    after = a_side(**{"q-1 flat 1": {"rule": BY_HAND, "by_judge": RIGHT}})
    findings = criteria(a_side(), after, CELLS)
    assert findings[2].state == FAILED
    assert findings[2].lines == ("q-1 flat 1: right by the rule in every run before, by_hand now",)
    # Where one run before was left to a person already, nothing is asked of the rule.
    before = a_side(**{"q-1 flat 3": {"rule": BY_HAND, "by_judge": RIGHT}})
    assert criteria(before, after, CELLS)[2].state == PASSED


def test_the_second_set_asks_of_the_rule_only_that_it_calls_no_answer_wrong():
    # What failed the third criterion on 2026-11-20 beside the two runs without an
    # answer: an answer the rule had called right in every run before and leaves to a
    # person now. Whether such an answer is wrong is what the fourth criterion asks.
    after = a_side(**{"q-1 flat 1": {"rule": BY_HAND, "by_judge": RIGHT}})
    assert criteria(a_side(), after, CELLS)[2].state == FAILED
    assert criteria(a_side(), after, CELLS, "1")[2].state == FAILED
    assert [finding.state for finding in criteria(a_side(), after, CELLS, "2")] == [PASSED] * 5
    # An answer the rule calls wrong fails it in the second set as in the first,
    wrong = a_side(**{"q-1 flat 1": {"rule": WRONG}})
    for which in regress.SETS:
        third = criteria(a_side(), wrong, CELLS, which)[2]
        assert (third.state, third.lines) == (
            FAILED,
            ("q-1 flat 1: the rule calls the answer wrong",),
        )
    # and one left to a person that the judge calls wrong waits for a person, as before.
    waits = a_side(**{"q-1 flat 1": {"rule": BY_HAND, "by_judge": WRONG}})
    states = [finding.state for finding in criteria(a_side(), waits, CELLS, "2")]
    assert states == [PASSED, PASSED, PASSED, OPEN, PASSED]
    assert regress.SETS == ("1", "2")


def test_the_fifth_criterion_holds_the_medians_of_the_two_layouts_against_each_other():
    # One staged run that was given more than a flat one does not move the median.
    assert states(a_side(**{"q-1 staged 1": {"chars": 200_000}}))[4] == PASSED
    two = {"q-1 staged 1": {"chars": 200_000}, "q-1 staged 2": {"chars": 200_000}}
    findings = criteria(a_side(), a_side(**two), CELLS)
    assert findings[4].state == FAILED
    assert findings[4].lines == ("q-1: staged 200,000 characters, flat 100,000",)
    # The same text for both is not less.
    same = {f"q-1 staged {n}": {"chars": 100_000} for n in (1, 2, 3)}
    assert states(a_side(**same))[4] == FAILED
    after = {cell: facts for cell, facts in a_side().items() if cell.toolset == "staged"}
    assert criteria(a_side(), after, CELLS)[4].state == OPEN


def test_failed_outranks_not_decided():
    after = a_side(**{"q-2 staged 3": {"passage": None}, "q-2 flat 1": {"reason": "no_answer"}})
    findings = criteria(a_side(), after, CELLS)
    assert [finding.state for finding in findings] == [FAILED, OPEN, PASSED, PASSED, PASSED]
    assert verdict(findings) == FAILED


# --- questions written to show an effect -------------------------------------------------


def never(*questions: str) -> dict:
    return {f"{q} staged {n}": {"passage": False} for q in questions for n in (1, 2, 3)}


def test_the_effect_is_shown_when_the_passage_was_given_more_often_and_nowhere_less():
    before = a_side(**never("q-1", "q-2"))
    after = a_side(**never("q-2"))
    assert effect(before, after, CELLS) == (
        SHOWN,
        ["q-1: 0 of 3 before, 3 after", "q-2: 0 of 3 before, 0 after"],
    )
    # The flat layout is not counted: its runs are a check on the question.
    flat = {f"q-1 flat {n}": {"passage": False} for n in (1, 2, 3)}
    assert effect(a_side(**never("q-1"), **flat), a_side(**flat), CELLS)[0] == SHOWN


def test_it_is_not_shown_when_nothing_could_be_gained_or_a_question_lost():
    # The version before gave the passage every time.
    assert effect(a_side(), a_side(), CELLS)[0] == NOT_SHOWN
    assert effect(a_side(**never("q-1")), a_side(**never("q-1")), CELLS)[0] == NOT_SHOWN
    # More in all, but one question fell.
    before = a_side(**never("q-1"), **{"q-2 staged 1": {"passage": True}})
    after = a_side(**{"q-2 staged 1": {"passage": False}})
    assert effect(before, after, CELLS) == (
        NOT_SHOWN,
        ["q-1: 0 of 3 before, 3 after", "q-2: 3 of 3 before, 2 after"],
    )
    assert effect(a_side(), a_side(**never("q-1")), CELLS)[0] == NOT_SHOWN


def test_the_effect_cannot_be_told_without_every_run_and_its_paper():
    unread = a_side(**{"q-1 staged 2": {"passage": None}})
    assert effect(a_side(), unread, CELLS)[0] == OPEN
    fewer = a_side()
    del fewer[Cell("q-2", "staged", 1)]
    assert effect(fewer, a_side(), CELLS)[0] == OPEN


# --- the text ----------------------------------------------------------------------------


def test_the_table_marks_a_cell_that_took_more_responses_than_any_run_before():
    after = a_side(**{f"q-2 staged {n}": {"turns": 7} for n in (2, 3)})
    lines = table(a_side(), after, CELLS)
    marked = [line for line in lines if "read the records" in line]
    assert len(marked) == 1 and marked[0].startswith("| q-2 | staged | after | 3 / 3 | 3 / 3 |")
    assert "| 4 7 7 | 10,000 | $0.15 | - | - |" in marked[0]
    # Where a run searched, the rank at which its paper was listed is shown, or that it was not.
    searched = {"q-1 flat 1": {"searches": 2, "rank": 3}, "q-1 flat 2": {"searches": 1}}
    (line,) = [x for x in table(a_side(), a_side(**searched), CELLS) if "| q-1 | flat | after" in x]
    assert "| $0.15 | 3 none none | - |" in line
    # One long run is not the median.
    one = table(a_side(), a_side(**{"q-2 staged 2": {"turns": 7}}), CELLS)
    assert not [line for line in one if "read the records" in line]


def test_the_text_ends_in_one_word_for_each_way_of_reading():
    text, said = text_of(["Head."], a_side(), a_side(), CELLS, targets=False)
    assert said == PASSED and "The runs after, held against the runs before: passed." in text
    assert text.startswith("Head.\n\n- 1 every run ended with an answer: passed\n")
    text, said = text_of(["Head."], a_side(**never("q-1")), a_side(), CELLS, targets=True)
    assert said == SHOWN and "The effect of the change on these questions: shown." in text
    assert "- q-1: 0 of 3 before, 3 after" in text and "passed" not in text


def test_the_text_names_the_runs_that_the_loop_asked_again_for_the_call():
    # Records of a loop that could not ask say nothing of it, and neither does the text.
    text, _ = text_of(["Head."], a_side(), a_side(), CELLS, targets=False)
    assert "asked again" not in text
    # Records that say whether it asked: here it asked in none,
    said_so = {str(cell): {"asks": True} for cell in CELLS}
    text, said = text_of(["Head."], a_side(), a_side(**said_so), CELLS, targets=False)
    assert said == PASSED
    assert "held against the runs before: passed.\n\nNo run after was asked again" in text
    # and here in two. An answer that was handed in then is an answer: it fails nothing.
    said_so["q-2 flat 2"] = {"asks": True, "asked_again": 2}
    text, said = text_of(["Head."], a_side(), a_side(**said_so), CELLS, targets=False)
    assert said == PASSED
    assert "\n\nAsked again for the call, after: q-2 flat 2 (then answered).\n" in text
    # A run that ended without the call a second time is a run without an answer.
    said_so["q-1 staged 3"] = {
        "asks": True,
        "asked_again": 4,
        "reason": "no_answer",
        "rule": WRONG,
    }
    text, said = text_of(["Head."], a_side(), a_side(**said_so), CELLS, targets=False)
    assert said == FAILED and "    - q-1 staged 3: ended as no_answer\n" in text
    assert (
        "Asked again for the call, after: "
        "q-2 flat 2 (then answered), q-1 staged 3 (then no_answer).\n"
    ) in text
    # Read as target questions the text says it too, and nothing passes or fails.
    text, said = text_of(["Head."], a_side(), a_side(**said_so), CELLS, targets=True)
    assert said == NOT_SHOWN and "Asked again for the call, after: q-2 flat 2" in text


# --- the two sides -----------------------------------------------------------------------


def runs_in(folder: str) -> list:
    return [attempt for tried in attempts_in(RUNS / folder).values() for attempt in tried]


def test_two_sides_can_be_compared_when_only_tool_texts_and_code_differ():
    tool = runs_in("diag-3-tool")
    before, after = comparable(tool, tool)
    assert before == after
    assert before["toolset_version of staged"] == "staged-5"
    assert before["commit of the code"].startswith("9d8024c")
    # Another way to hand in the answer is another prompt: no comparison.
    with pytest.raises(RegressError, match="differ in answer_channel: 'tool' before, 'text'"):
        comparable(tool, runs_in("diag-3-text"))
    with pytest.raises(RegressError, match="the runs after do not name one answer_channel"):
        comparable(tool, tool + runs_in("diag-3-text"))
    # Runs of two commits on one side are runs of two versions.
    other = {"commit": "f" * 40, "modified": False}
    mixed = [replace(a, run={**a.run, "code": other}) for a in tool[:15]] + tool[15:]
    with pytest.raises(RegressError, match="the runs before do not name one commit of the code"):
        comparable(mixed, tool)
    # The SDK that sent the requests belongs to the code, and may differ.
    newer = [replace(a, run={**a.run, "model": {**a.run["model"], "sdk": "x"}}) for a in tool]
    assert comparable(tool, newer)[0] == before
    slower = [replace(a, run={**a.run, "model": {**a.run["model"], "effort": "low"}}) for a in tool]
    with pytest.raises(RegressError, match="the two sides differ in model"):
        comparable(tool, slower)


def test_two_sides_may_differ_in_the_prompt_of_the_loop_as_in_the_tool_texts():
    # The prompt holds the message of the loop, and a changed message is a change like
    # one to a tool text: the runs after are held against the runs before it.
    tool = runs_in("diag-3-tool")
    asking = [replace(a, run={**a.run, "prompt_version": "p3-tool"}) for a in tool]
    before, after = comparable(tool, asking)
    assert (before["prompt_version"], after["prompt_version"]) == ("p2-tool", "p3-tool")
    # Each side still has one prompt: runs of two are runs of two versions.
    with pytest.raises(RegressError, match="the runs after do not name one prompt_version"):
        comparable(tool, asking[:15] + tool[15:])


# --- the command, on the records of the repository ---------------------------------------

SIDES = ["--questions", str(DEV), "--before", str(RUNS / "diag-3-tool")]
SIDES += ["--after", str(RUNS / "diag-3-tool")]
GRADED = ["--sheet", str(JUDGED / "dev-sheet.csv"), "--key", str(JUDGED / "dev-sheet-key.csv")]
GRADED += ["--judge", str(JUDGED / "dev-j2.jsonl")]


def run(capsys, *argv: str) -> tuple[int, str, str]:
    code = regress.main([*argv], source=FixtureSource([own_paper()]))
    out = capsys.readouterr()
    return code, out.out, out.err


def criterion_lines(text: str) -> list[str]:
    return [line for line in text.splitlines() if line[:3] in ("- 1", "- 2", "- 3", "- 4", "- 5")]


def test_the_runs_the_conditions_rest_on_held_against_themselves(capsys):
    code, text, _ = run(capsys, *SIDES, *GRADED)
    assert criterion_lines(text) == [
        "- 1 every run ended with an answer: passed",
        "- 2 the passage was given in every run: not decided",
        "- 3 the rule calls no answer wrong: passed",
        "- 4 no answer left to a person is wrong: passed",
        "- 5 staged was given less text than flat: passed",
    ]
    # All that is open is the paper that is not kept here.
    opened = [line.strip() for line in text.splitlines() if line.startswith("    - ")]
    assert len(opened) == 6 and all(line.startswith("- dev-03 ") for line in opened)
    assert code == 1 and "held against the runs before: not decided." in text
    assert "tool texts staged-5, flat-4; code 9d8024c" in text
    assert (
        "| dev-05 | staged | after | 3 / 3 | 3 / 3 | 3 by_hand | 6 6 5 | 46,717 | $0.19 |" in text
    )
    assert "| dev-01 | staged | before | 3 / 3 | 3 / 3 | 3 right | 4 4 4 | 10,566 |" in text
    # A cell whose paper is missing shows that, not a count.
    assert (
        "| dev-03 | staged | before | 3 / 3 | ? | 3 right | 4 5 4 | 9,758 | $0.11 | 1 1 1 |" in text
    )
    assert "3 invalid_arguments" in text and "has changed since" not in text


def with_another_prompt(tmp_path, asked: str) -> Path:
    """The thirty runs again, as a loop that can ask would have recorded them.

    Every record names the prompt p3-tool and says in its last line whether the loop
    asked again. It did in the runs whose file name holds `asked`, after the first response.
    """
    folder = tmp_path / "after"
    folder.mkdir()
    for path in sorted((RUNS / "diag-3-tool").glob("*.jsonl")):
        first, *turns, end = (json.loads(line) for line in path.read_text("utf-8").splitlines())
        first["prompt_version"] = "p3-tool"
        end = {**end, "asked_again": 1 if asked in path.name else None}
        lines = [json.dumps(line) for line in (first, *turns, end)]
        (folder / path.name).write_text("\n".join(lines) + "\n", "utf-8")
    return folder


def test_runs_with_another_prompt_are_held_against_the_runs_before_it(capsys, tmp_path):
    after = with_another_prompt(tmp_path, asked="_dev-02_flat_")
    sides = [*SIDES[:4], "--after", str(after)]
    code, text, _ = run(capsys, *sides, *GRADED, "--criteria", "2")
    head = text.splitlines()[1:4]
    # The prompt is named, because the sides differ in it, and so is the set of criteria.
    assert head[0].endswith("; 30 runs; tool texts staged-5, flat-4; prompt p2-tool; code 9d8024c")
    assert head[1].endswith("; 30 runs; tool texts staged-5, flat-4; prompt p3-tool; code 9d8024c")
    assert head[2] == "Criteria: the second set (3 asks only that the rule calls no answer wrong)"
    assert code == 1 and "held against the runs before: not decided." in text  # dev-03's paper
    # Three runs of dev-02 with the flat layout were made in that folder.
    said = "Asked again for the call, after: " + ", ".join(
        f"dev-02 flat {n} (then answered)" for n in (1, 2, 3)
    )
    assert f"\n\n{said}.\n\n| question |" in text
    # With the first set, which is the default, the text does not name a set.
    code, text, _ = run(capsys, *sides, *GRADED)
    assert "Criteria:" not in text and "prompt p3-tool; code" in text
    # Read as target questions there are no criteria to name.
    _, text, _ = run(capsys, *sides, "--targets", "--criteria", "2")
    assert "Criteria:" not in text


def test_without_a_judge_the_answers_left_to_a_person_are_open(capsys):
    code, text, _ = run(capsys, *SIDES)
    assert "- 4 no answer left to a person is wrong: not decided" in text
    assert text.count("neither a person nor the judge has graded it") == 18
    assert code == 1


def a_copy(tmp_path, change) -> list[str]:
    """The sheet with one thing changed in its rows, beside the key and the record as they are."""
    with (JUDGED / "dev-sheet.csv").open(encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.DictReader(stream))
    change(rows)
    sheet = tmp_path / "sheet.csv"
    with sheet.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    return ["--sheet", str(sheet), *GRADED[2:]]


def by_hand_row(rows: list[dict]) -> dict:
    return next(row for row in rows if row["question_id"] == "dev-02")


def test_a_grade_written_on_the_sheet_decides(capsys, tmp_path):
    def grade_wrong(rows):
        by_hand_row(rows)["grade"] = "wrong"

    code, text, _ = run(capsys, *SIDES, *a_copy(tmp_path, grade_wrong))
    assert "- 4 no answer left to a person is wrong: failed" in text
    assert text.count("graded wrong by a person") == 1
    assert code == 1 and "held against the runs before: failed." in text
    assert "sheet.csv has changed since the judge read it (grades, or more)." in text


def test_an_answer_the_judge_calls_wrong_waits_for_a_person(capsys, tmp_path):
    number = by_hand_row(
        list(csv.DictReader((JUDGED / "dev-sheet.csv").open(encoding="utf-8-sig")))
    )["number"]
    lines = (JUDGED / "dev-j2.jsonl").read_text(encoding="utf-8").splitlines()
    changed = []
    for line in map(json.loads, lines):
        if line.get("item") == f"sheet-{number}" and line["repeat"] in (1, 3):
            line["verdict"] = "wrong"
        changed.append(json.dumps(line, ensure_ascii=False))
    record = tmp_path / "judge.jsonl"
    record.write_text("\n".join(changed) + "\n", encoding="utf-8")
    code, text, _ = run(capsys, *SIDES, *GRADED[:4], "--judge", str(record))
    assert "- 4 no answer left to a person is wrong: not decided" in text
    assert text.count("the judge calls it wrong, and nobody has read it") == 1

    def grade_right(rows):
        by_hand_row(rows)["grade"] = "right"

    code, text, _ = run(capsys, *SIDES, *a_copy(tmp_path, grade_right)[:4], "--judge", str(record))
    assert "- 4 no answer left to a person is wrong: passed" in text


def test_files_that_do_not_belong_to_the_runs_are_refused(capsys, tmp_path):
    # The record of another judge.
    code, _, err = run(capsys, *SIDES, *GRADED[:4], "--judge", str(JUDGED / "dev-j1.jsonl"))
    assert code == 2 and "dev-j1.jsonl: it is of the judge 'j1', not of 'j2' as it is now" in err

    # A sheet that shows another answer than the run gave.
    def other_answer(rows):
        by_hand_row(rows)["answer"] += " And more."

    code, _, err = run(capsys, *SIDES, *a_copy(tmp_path, other_answer))
    assert code == 2 and "sheet.csv number" in err and "not the answer of" in err

    # The sheet of the other half of that diagnosis.
    after = [*SIDES[:-1], str(RUNS / "diag-3-text")]
    code, _, err = run(capsys, *after, *GRADED)
    assert code == 2 and "differ in answer_channel" in err
    # A part of the three files.
    code, _, err = run(capsys, *SIDES, *GRADED[:2])
    assert code == 2 and "--sheet, --key and --judge go together" in err
    # Sides of another question file.
    code, _, err = run(capsys, "--questions", str(TARGETS), *SIDES[2:])
    assert code == 2 and "a run of another question file" in err


def test_a_key_of_other_runs_is_refused(capsys, tmp_path):
    key = tmp_path / "key.csv"
    text = (JUDGED / "dev-sheet-key.csv").read_text(encoding="utf-8")
    key.write_text(text.replace("_dev-01_staged_68b3", "_dev-01_staged_0000"), encoding="utf-8")
    code, _, err = run(capsys, *SIDES, GRADED[0], GRADED[1], "--key", str(key), *GRADED[4:])
    assert code == 2 and "key.csv is not the key of the runs after that gave an answer" in err


def test_sides_that_are_not_whole_are_refused(capsys, tmp_path):
    some = tmp_path / "some"
    some.mkdir()
    for path in sorted((RUNS / "diag-3-tool").glob("*.jsonl"))[1:]:
        (some / path.name).write_bytes(path.read_bytes())
    code, _, err = run(capsys, SIDES[0], SIDES[1], "--before", str(some), *SIDES[4:])
    assert code == 2 and "the runs before have no run that counts of dev-01 staged 1" in err
    (tmp_path / "none").mkdir()
    code, _, err = run(capsys, *SIDES[:4], "--after", str(tmp_path / "none"))
    assert code == 2 and "holds no run that counts" in err
    # A side with a run missing can stand after: that is what the first criterion is for.
    code, text, _ = run(capsys, *SIDES[:4], "--after", str(some))
    assert code == 1 and "- 1 every run ended with an answer: failed" in text
    assert "    - dev-01 staged 1: no run that counts" in text


def test_read_as_targets_the_same_runs_cannot_be_told_for_the_paper_that_is_missing(capsys):
    code, text, _ = run(capsys, *SIDES, "--targets")
    assert code == 1 and "The effect of the change on these questions: not decided." in text
    assert "- dev-03: a run is missing, or its paper could not be read" in text
    assert not criterion_lines(text)


# --- the questions written to show the effect of a changed outline -----------------------


def own_text_ends() -> dict[str, int]:
    """For each section of the kept paper that has subsections: where its own text ends."""
    ends: dict[str, int] = {}
    for section in own_paper().sections:
        if section.level == 2:
            ends.setdefault(parent_of(section.section_id), section.heading_at)
    return ends


def test_the_target_questions_rest_on_text_that_no_subsection_holds():
    questions = load_questions(TARGETS)
    assert [question.id for question in questions] == ["tgt-01", "tgt-02", "tgt-03"]
    paper = own_paper()
    sections = {section.section_id: section for section in paper.sections}
    ends, whole = own_text_ends(), full_text(paper)
    tex = (OWN_PAPER / "FermiLAT-main.tex").read_text(encoding="utf-8")
    abstract = tex[tex.index("\\begin{abstract}") : tex.index("\\end{abstract}")]
    where = {}
    for question in questions:
        assert question.type == "section_own_text" and question.expect_found
        assert question.gold_papers == (OWN,) and not question.abstract_sufficient
        assert problems_with_evidence(question, {OWN: paper}) == []
        (evidence,) = question.evidence
        at = sections[evidence.section_id].text.index(evidence.anchor)
        # Before the heading of the first subsection, so that only a read of the section
        # itself returns it, and nowhere else in the paper.
        assert at + len(evidence.anchor) <= ends[evidence.section_id]
        assert whole.count(evidence.anchor) == 1 and evidence.anchor not in abstract
        where[question.id] = (evidence.section_id, at)
    assert where == {"tgt-01": ("3", 1139), "tgt-02": ("3", 1238), "tgt-03": ("6", 366)}


def test_no_development_question_rests_on_such_text():
    # Why the five development questions cannot show what a changed outline does.
    paper, ends = own_paper(), own_text_ends()
    sections = {section.section_id: section for section in paper.sections}
    for question in load_questions(DEV):
        for evidence in question.evidence:
            if evidence.arxiv_id != OWN or evidence.section_id not in ends:
                continue  # a subsection, or a section without subsections: all of it is its own
            at = sections[evidence.section_id].text.index(evidence.anchor)
            assert at >= ends[evidence.section_id], question.id
