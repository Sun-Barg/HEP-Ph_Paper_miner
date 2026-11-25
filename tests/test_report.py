"""The report of the evaluation, from records that the real command wrote.

The runner starts the command of each run in this process, with a model that replies
from a script and the papers held in memory, as in test_run.py. Then the sheet is made,
graded here, and the report is read. No network, no LLM.
"""

import csv
import json
import re
from pathlib import Path
from types import SimpleNamespace

import pytest
from conftest import asks, sample_source, says

from hepph_paper_miner.agent import __main__ as command
from hepph_paper_miner.agent import loop, origin
from hepph_paper_miner.agent.model import ClaudeModel, Reply
from hepph_paper_miner.eval import report, run, sheet
from hepph_paper_miner.eval.grade import Places, Record
from hepph_paper_miner.eval.report import cost_of, sign_test, text_given

SAMPLE = "2501.00001v2"  # sections 1, 2 (2.1, 2.u1, 2.2), u1, A (A.1)
CODE = {"commit": "c" * 40, "modified": False}
ANSWER = {"answer": "Ten.", "found": True, "evidence": [{"arxiv_id": SAMPLE, "section_id": "2.1"}]}

# What the scripted model does in the staged layout, by the first word of the question
# (in the flat layout it always reads the paper and answers):
#   good     reads the outline and section 2.1, and answers
#   astray   reads the outline and section 1, and answers
#   silent   reads the outline, and ends with text instead of an answer
#   again    reads the outline, section 2.1 twice, and answers
STAGED = {
    "good": [("get_outline", {"arxiv_id": SAMPLE}), ("read_section", "2.1")],
    "astray": [("get_outline", {"arxiv_id": SAMPLE}), ("read_section", "1")],
    "silent": [("get_outline", {"arxiv_id": SAMPLE})],
    "again": [
        ("get_outline", {"arxiv_id": SAMPLE}),
        ("read_section", "2.1"),
        ("read_section", "2.1"),
    ],
}


def question(name: str) -> dict:
    return {
        "id": name,
        "question": f"{name.split('-')[0]}: what does the paper say?",
        "type": "single_section",
        "gold_papers": [SAMPLE],
        "gold_evidence": {"need": "all", "items": [{"arxiv_id": SAMPLE, "section_id": "2.1"}]},
        "expect_found": True,
        "reference_answer": "Ten.",
        "answer_key": {"by_hand": ["that it is ten"]},
        "accept_note": "Ten.",
        "abstract_sufficient": False,
    }


@pytest.fixture
def evaluated(monkeypatch, tmp_path):
    """An evaluation of four questions, three repetitions, every run made by the command."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "not-a-real-key")
    monkeypatch.setattr(loop, "code_version", lambda: dict(CODE))
    monkeypatch.setattr(origin, "code_version", lambda: dict(CODE))

    class Scripted(ClaudeModel):
        def __init__(self, name, **settings):
            super().__init__(name, client=object(), **settings)
            self.turn = 0

        async def reply(self, system, messages, tools, answer_schema) -> Reply:
            self.turn += 1
            word = messages[0]["content"].split(":")[0]
            if "get_outline" not in [tool["name"] for tool in tools]:
                if self.turn == 1:
                    return asks(("read_paper", {"arxiv_id": SAMPLE}))
                return asks(("submit_answer", ANSWER))
            steps = STAGED[word]
            if self.turn <= len(steps):
                name, arguments = steps[self.turn - 1]
                if name == "read_section":
                    arguments = {"arxiv_id": SAMPLE, "section_id": arguments}
                return asks((name, arguments))
            if word == "silent":
                return says("The paper does not say it plainly.")
            return asks(("submit_answer", ANSWER))

    monkeypatch.setattr(command, "ClaudeModel", Scripted)
    monkeypatch.setattr(command, "Fetcher", lambda *args, **kwargs: None)
    monkeypatch.setattr(command, "ArxivSource", lambda fetcher: sample_source())
    names = ["good-1", "astray-2", "silent-3", "again-4"]
    questions = tmp_path / "questions.jsonl"
    questions.write_text("".join(json.dumps(question(n)) + "\n" for n in names), "utf-8")
    out = tmp_path / "runs"
    argv = ["--questions", str(questions), "--out", str(out), "--private", str(tmp_path / "p")]
    assert run.main(argv, launch=command.main) == 0
    return tmp_path, questions, out


def make_sheet(folder: Path, questions: Path, runs: Path, grade_of) -> tuple[Path, Path]:
    """Make the sheet and grade every row with grade_of(key line)."""
    paths = [folder / "grading.csv", folder / "p" / "key.csv"]
    argv = ["--questions", str(questions), "--runs", str(runs), "--seed", "5"]
    assert sheet.main([*argv, "--sheet", str(paths[0]), "--key", str(paths[1])]) == 0
    with paths[1].open(encoding="utf-8", newline="") as stream:
        keys = {line["number"]: line for line in csv.DictReader(stream)}
    with paths[0].open(encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.DictReader(stream))
    for row in rows:
        row["grade"] = grade_of(keys[row["number"]])
    with paths[0].open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    return paths[0], paths[1]


# The records of these tests are made by the code as it is, so they are held against the
# conditions that name its texts and its parser, not against those of the evaluation.
NOW = ["--conditions", "more-sections"]


def reported(questions: Path, runs: Path, *more: str, capsys) -> str:
    argv = ["--questions", str(questions), "--runs", str(runs), *NOW, *more]
    assert report.main(argv, source=sample_source()) == 0
    return capsys.readouterr().out


def cells(text: str, name: str) -> list[str]:
    """The cells of the row whose first cell starts with `name`."""
    for line in text.splitlines():
        if line.startswith(f"| {name}"):
            return [cell.strip() for cell in line.strip("|").split("|")][1:]
    raise AssertionError(f"no row {name!r}")


# --- the whole report --------------------------------------------------------------------


def staged_astray_is_wrong(key: dict) -> str:
    return "wrong" if key["question_id"] == "astray-2" and key["toolset"] == "staged" else "right"


def test_the_report_counts_what_each_layout_did(evaluated, capsys):
    folder, questions, runs = evaluated
    graded = make_sheet(folder, questions, runs, staged_astray_is_wrong)
    capsys.readouterr()
    text = reported(
        questions, runs, "--sheet", str(graded[0]), "--key", str(graded[1]), capsys=capsys
    )
    assert "no record differs" in text
    assert "Answers graded by hand: 21 of 21" in text
    assert cells(text, "runs that count") == ["12", "12"]
    assert cells(text, "answered") == ["9 / 12", "12 / 12"]  # silent-3 staged ends without one
    assert cells(text, "2a passage given") == ["6 / 12", "12 / 12"]  # astray and silent do not
    assert cells(text, "2b cited strictly") == ["9 / 9 of 9", "12 / 12 of 12"]
    # Wrong: astray-2 by hand (3) and silent-3 without an answer (3).
    assert cells(text, "3 right, by hand") == ["6 / 12", "12 / 12"]
    assert cells(text, "questions right in more than half") == ["2 / 4", "4 / 4"]
    assert cells(text, "repeat reads") == ["3", "0"]  # again-4 reads 2.1 twice, three times
    assert cells(text, "answered wrong, its paper was given but not the passage") == ["3", "0"]
    assert cells(text, "no answer: no_answer") == ["3", "0"]


def test_the_report_counts_the_answers_that_came_after_the_loop_had_asked_again(evaluated, capsys):
    folder, questions, runs = evaluated
    row = "of them after the loop had asked again"
    capsys.readouterr()

    def rewritten(path: Path, change) -> None:
        *lines, last = path.read_text("utf-8").splitlines()
        end = json.loads(last)
        change(end)
        path.write_text("\n".join([*lines, json.dumps(end)]) + "\n", "utf-8")

    # The loop asked in the three staged runs of silent-3, and none of them answered then.
    asked = [json.loads(p.read_text("utf-8").splitlines()[-1]) for p in runs.glob("*_silent-3_*")]
    assert sorted((end["reason"], end["asked_again"]) for end in asked) == [
        *[("answered", None)] * 3,  # the flat runs
        *[("no_answer", 2)] * 3,  # asked after the second response, and no call then either
    ]
    text = reported(questions, runs, capsys=capsys)
    assert cells(text, row) == ["0", "0"]
    assert text.index("| answered |") < text.index(f"| {row}") < text.index("| 1 search listed")
    # One answer that did come so, as the record of its run would say it.
    rewritten(next(runs.glob("*_good-1_flat_*.jsonl")), lambda end: end.update(asked_again=1))
    assert cells(reported(questions, runs, capsys=capsys), row) == ["0", "1"]
    # Records of a loop that could not ask say nothing of it, and their report has no
    # such row: the report of the evaluation stays as it was written.
    for path in runs.glob("*.jsonl"):
        rewritten(path, lambda end: end.pop("asked_again"))
    assert row not in reported(questions, runs, capsys=capsys)


def test_h1_and_h2_are_held_up_question_by_question(evaluated, capsys):
    folder, questions, runs = evaluated
    graded = make_sheet(folder, questions, runs, staged_astray_is_wrong)
    capsys.readouterr()
    text = reported(
        questions, runs, "--sheet", str(graded[0]), "--key", str(graded[1]), capsys=capsys
    )
    by_question: dict[tuple[str, str], list[int]] = {}
    for path in runs.glob("*.jsonl"):
        lines = [json.loads(line) for line in path.read_text("utf-8").splitlines()]
        key = (lines[0]["question_id"], lines[0]["toolset"])
        by_question.setdefault(key, []).append(lines[-1]["tool_result_chars"])
    names = ["good-1", "astray-2", "silent-3", "again-4"]
    medians = {key: sorted(values)[1] for key, values in by_question.items()}
    lower = sum(1 for n in names if medians[(n, "staged")] < medians[(n, "flat")])
    higher = sum(1 for n in names if medians[(n, "staged")] > medians[(n, "flat")])
    h1 = re.search(r"staged runs is lower in (\d+) question\(s\), higher in (\d+)", text)
    assert (int(h1[1]), int(h1[2])) == (lower, higher)
    assert f"p = {sign_test(lower, higher):.4g}" in text
    assert cells(text, "staged right") == ["2", "0"]
    assert cells(text, "staged wrong") == ["2", "0"]
    row = cells(text, "astray-2")
    assert row[:3] == ["single_section", "0 / 3", "3 / 3"]


def test_a_wrong_answer_after_the_passage_was_given_is_told_apart(evaluated, capsys):
    folder, questions, runs = evaluated

    def flat_good_is_wrong(key):
        return "wrong" if key["question_id"] == "good-1" and key["toolset"] == "flat" else "right"

    graded = make_sheet(folder, questions, runs, flat_good_is_wrong)
    capsys.readouterr()
    argv = ["--sheet", str(graded[0]), "--key", str(graded[1])]
    text = reported(questions, runs, *argv, capsys=capsys)
    assert cells(text, "answered wrong, the passage was given") == ["0", "3"]
    assert cells(text, "no answer: no_answer") == ["3", "0"]


def test_input_tokens_hold_what_was_written_to_the_cache_and_read_from_it(evaluated, capsys):
    _, questions, runs = evaluated
    # The scripted model has no cache: put some in, as the API would count it.
    for path in runs.glob("*_staged_*.jsonl"):
        lines = [json.loads(line) for line in path.read_text("utf-8").splitlines()]
        lines[-1]["cache_creation_input_tokens"] = 1000 * lines[-1]["turns"]
        lines[-1]["cache_read_input_tokens"] = 300
        path.write_text("".join(json.dumps(line) + "\n" for line in lines), "utf-8")
    text = reported(questions, runs, capsys=capsys)
    totals = {"staged": [], "flat": []}
    for path in runs.glob("*.jsonl"):
        lines = [json.loads(line) for line in path.read_text("utf-8").splitlines()]
        end = lines[-1]
        names = ("input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens")
        totals[lines[0]["toolset"]].append(sum(end.get(name) or 0 for name in names))
    staged = sorted(totals["staged"])
    assert cells(text, "input tokens")[0].startswith(f"{(staged[5] + staged[6]) / 2:,.0f} (")


def test_a_tie_is_neither_lower_nor_higher():
    def facts(name, layout, chars):
        return SimpleNamespace(question=SimpleNamespace(id=name), layout=layout, chars=chars)

    questions = [SimpleNamespace(id=name) for name in ("tie", "lower", "higher", "one")]
    runs = [
        *(facts("tie", layout, 5) for layout in ("staged", "flat")),
        facts("lower", "staged", 1),
        facts("lower", "flat", 9),
        facts("higher", "staged", 9),
        facts("higher", "flat", 1),
        facts("one", "staged", 1),
    ]
    assert report.compare(questions, runs, lambda f: f.chars) == (1, 1, 1, 1)


def test_without_a_sheet_everything_but_the_verdicts_is_written(evaluated, capsys):
    _, questions, runs = evaluated
    text = reported(questions, runs, capsys=capsys)
    assert "Answers graded by hand: 0 of 21 (no sheet given)" in text
    assert cells(text, "3 right, by hand") == ["0 / 3 (9 not graded)", "0 / 0 (12 not graded)"]
    assert "4 question(s) not in the table" in text
    assert cells(text, "2a passage given") == ["6 / 12", "12 / 12"]


def test_a_sheet_of_other_runs_is_refused(evaluated, capsys):
    folder, questions, runs = evaluated
    graded = make_sheet(folder, questions, runs, lambda key: "right")
    next(runs.glob("*_good-1_flat_*.jsonl")).rename(folder / "moved.jsonl")
    argv = ["--questions", str(questions), "--runs", str(runs)]
    argv += ["--sheet", str(graded[0]), "--key", str(graded[1])]
    assert report.main(argv, source=sample_source()) == 1
    assert "a sheet of other runs" in capsys.readouterr().err


def test_a_record_made_under_other_conditions_is_named(evaluated, capsys):
    _, questions, runs = evaluated
    path = next(runs.glob("*_good-1_staged_*.jsonl"))
    lines = path.read_text("utf-8").splitlines()
    first = json.loads(lines[0])
    first["model"]["effort"] = "medium"
    path.write_text("\n".join([json.dumps(first), *lines[1:]]) + "\n", "utf-8")
    text = reported(questions, runs, capsys=capsys)
    assert f"1 record(s) differ, first {path.name}: model.effort is 'medium'" in text


# --- the parts ---------------------------------------------------------------------------


def test_the_sign_test_is_one_sided_and_exact():
    assert sign_test(5, 0) == 1 / 32
    assert sign_test(3, 2) == (10 + 5 + 1) / 32
    assert sign_test(0, 0) == 1.0
    assert sign_test(15, 2) == pytest.approx(0.0011749267578125)


def test_the_cost_of_a_run_is_worked_out_from_the_usage_of_its_responses():
    # The usage of the rehearsal runs of dev-01 (11-17), as their public records hold it.
    def turn(fresh, written, read, out):
        cache = {"ephemeral_5m_input_tokens": written, "ephemeral_1h_input_tokens": 0}
        return {
            "usage": {
                "input_tokens": fresh,
                "cache_creation_input_tokens": written,
                "cache_creation": cache,
                "cache_read_input_tokens": read,
                "output_tokens": out,
            }
        }

    staged = [
        turn(4, 2136, 0, 59),
        turn(2, 1530, 2136, 81),
        turn(2, 198, 3666, 83),
        turn(2, 3483, 3864, 259),
    ]
    flat = [turn(4, 1919, 0, 59), turn(2, 63647, 1919, 279)]
    model = "claude-sonnet-5-5"
    assert cost_of(staged, model) == pytest.approx(0.0241741)
    assert cost_of(flat, model) == pytest.approx(0.1674989)
    hour = {"usage": {"cache_creation": {"ephemeral_1h_input_tokens": 1_000_000}}}
    assert cost_of([hour], model) == pytest.approx(4.0)
    no_split = {"usage": {"cache_creation_input_tokens": 1_000_000}}
    assert cost_of([no_split], model) == pytest.approx(2.5)
    assert cost_of(staged, "another-model") is None


def read(turn: int, section: str | None, start: int, stop: int) -> dict:
    first = {
        "shape": "section" if section else "paper",
        "arxiv_id": SAMPLE,
        "start": start,
        "stop": stop,
    }
    if section:
        first["section_id"] = section
    return {"turn": turn, "tools": [{"status": "ok", "first_line": first}]}


def test_text_given_counts_every_character_once_on_the_scale_of_its_section():
    paper = sample_source().paper_by_id(SAMPLE)
    places = {SAMPLE: Places(paper)}
    sections = {s.section_id: s for s in paper.sections}
    whole, part = sections["2"].chars, sections["2.1"].chars
    record = Record(
        {}, (read(1, "2.1", 0, part), read(2, "2", 0, whole), read(3, "2.1", 0, part)), {}
    )
    # "2" holds "2.1": after both, the text of "2" was given once; the third call gives nothing.
    assert text_given(record, places) == (whole, 1, False)
    record = Record(
        {}, (read(1, None, 0, 500), read(2, None, 200, 500), read(3, None, 400, 900)), {}
    )
    assert text_given(record, places) == (900, 1, False)
    # Without the paper its sections are counted on their own scales, and the report says so.
    record = Record({}, (read(1, "2.1", 0, part), read(2, "2", 0, whole)), {})
    assert text_given(record, {}) == (whole + part, 0, True)


def test_a_layout_answers_a_question_right_with_more_than_half_of_its_runs():
    def runs(*verdicts):
        return [type("F", (), {"verdict": v})() for v in verdicts]

    assert report._majority(runs("right", "right", "wrong")) is True
    assert report._majority(runs("right", "wrong", "wrong")) is False
    assert report._majority(runs("right", "wrong")) is False  # a cell given up leaves two
    assert report._majority(runs("right", None, "right")) is None
    assert report._majority([]) is None


def test_the_report_holds_records_against_the_conditions_of_the_evaluation_unless_told(
    evaluated, capsys
):
    # The report of the evaluation is written by the command without this option, and has
    # to come out as it was written (test_results.py). Records of the code as it is now
    # name other tool texts, and are named for it.
    _, questions, runs = evaluated
    assert (
        report.main(["--questions", str(questions), "--runs", str(runs)], source=sample_source())
        == 0
    )
    text = capsys.readouterr().out
    assert "Held against the conditions (conditions.py): 24 record(s) differ, first " in text
    assert "toolset_version is 'staged-6', not 'staged-5'" in text or (
        "toolset_version is 'flat-5', not 'flat-4'" in text
    )
    text = reported(questions, runs, capsys=capsys)
    assert "Held against the conditions 'more-sections' (conditions.py): no record differs" in text
