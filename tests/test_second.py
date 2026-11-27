"""The report of the second evaluation (eval/second.py): what Sections 11 to 14 of its
pre-registration say is reported, from the files an evaluation leaves.

Most tests read the report of thirty questions whose records are written here by hand, so
that every count of the report can be said beforehand. One test makes the runs with the
real commands, with a model that replies from a script, as tests/test_report.py does: a
record as the loop writes it has to go through the sheet, the judge, the sheet graded by
hand and the report. No network, no LLM.
"""

import json
import math
import re
from collections import Counter
from pathlib import Path
from types import SimpleNamespace

import pytest
from conftest import asks, sample_source, says
from graded_runs import grade_sheet, judged_by, read_csv

from hepph_paper_miner.agent import __main__ as command
from hepph_paper_miner.agent import loop, origin
from hepph_paper_miner.agent.model import ClaudeModel, Reply
from hepph_paper_miner.agent.origin import file_digest
from hepph_paper_miner.drafting.places import KINDS
from hepph_paper_miner.eval import hand, judge, run, second, sheet
from hepph_paper_miner.eval.conditions import of_the_code
from hepph_paper_miner.eval.grade import RIGHT, WRONG
from hepph_paper_miner.eval.hand import DIFFER, DOUBTED, SAMPLED
from hepph_paper_miner.eval.paired import (
    NOT_SHOWN,
    NOT_WORSE,
    WORSE,
    WORSE_WITHIN,
    adjusted_wald,
    reading,
)
from hepph_paper_miner.eval.report import sign_test
from hepph_paper_miner.eval.second import (
    CONDITIONS_NAME,
    MARGIN,
    READINGS,
    h1,
    h2,
    in_order,
    left_out,
    pairs_of,
)
from hepph_paper_miner.sources.arxiv_latex import PARSER_VERSION
from hepph_paper_miner.sources.fixture import FixtureSource

ROOT = Path(__file__).resolve().parent.parent
TEXT = (ROOT / "eval_data" / "PREREGISTRATION_2.md").read_text(encoding="utf-8")
FLAT = " ".join(TEXT.split())  # a sentence is found wherever it is wrapped
SAMPLE = "2501.00001v2"  # sections 1, 2 (2.1, 2.u1, 2.2), u1, A (A.1)
OLDER = "2501.00001v1"
ARCHIVES = ("hep-ph", "hep-th", "hep-ex", "astro-ph")
SAID_BY = {"staged": "P", "flat": "Q"}
# Where the passage of a question of each kind stands in the invented paper.
EVIDENCE = {
    "later_piece": ("2.1", "Data text."),
    "appendix": ("A", "Appendix text."),
    "own_text": ("2", "Methods overview."),
    "search_first": ("2.1", "Data text."),
    "named_first": ("2.1", "Data text."),
}


@pytest.fixture(autouse=True)
def committed_code(monkeypatch):
    monkeypatch.setattr(judge, "code_version", lambda: {"commit": "c0ffee", "modified": False})


def cells(text: str, name: str) -> list[str]:
    """The cells of the row whose first cell starts with `name`, without that cell."""
    for line in text.splitlines():
        if line.startswith(f"| {name}"):
            return [cell.strip() for cell in line.strip("|").split("|")][1:]
    raise AssertionError(f"no row {name!r}")


def part(text: str, title: str) -> str:
    """One section of the report, from its heading to the next."""
    found = re.search(rf"^## {re.escape(title)}\n.*?(?=^## |\Z)", text, re.MULTILINE | re.DOTALL)
    assert found, f"no section {title!r}"
    return found.group(0)


# --- the parts ------------------------------------------------------------------------------


def run_of(name: str, layout: str, chars: int, verdict: str = RIGHT):
    return SimpleNamespace(
        question=SimpleNamespace(id=name), layout=layout, chars=chars, verdict=verdict
    )


def test_the_questions_with_a_run_of_both_layouts_are_the_pairs():
    questions = [SimpleNamespace(id=name) for name in ("q1", "q2", "q3")]
    facts = [run_of("q2", "flat", 9), run_of("q1", "staged", 1), run_of("q1", "flat", 2)]
    facts += [run_of("q3", "staged", 5)]
    pairs = pairs_of(questions, facts)
    assert [(staged.question.id, staged.layout, flat.layout) for staged, flat in pairs] == [
        ("q1", "staged", "flat")
    ]
    with pytest.raises(ValueError, match="q1 has two runs of flat"):
        pairs_of(questions, [*facts, run_of("q1", "flat", 3)])


def test_h1_counts_the_questions_whose_staged_run_was_given_fewer_more_and_as_many():
    pairs = [
        (run_of("q1", "staged", 10), run_of("q1", "flat", 90)),
        (run_of("q2", "staged", 91), run_of("q2", "flat", 90)),
        (run_of("q3", "staged", 90), run_of("q3", "flat", 90)),
        (run_of("q4", "staged", 0), run_of("q4", "flat", 1)),
    ]
    assert h1(pairs) == (2, 1, 1)
    assert (
        "the number of questions whose staged run was given fewer characters, more, and as "
        "many, and the p of a one-sided exact sign test with ties left out"
    ) in FLAT


def test_h2_is_the_paired_table_of_the_questions():
    def pair(staged, flat):
        return run_of("q", "staged", 1, staged), run_of("q", "flat", 1, flat)

    pairs = [pair(RIGHT, RIGHT)] * 5 + [pair(RIGHT, WRONG)] * 2 + [pair(WRONG, RIGHT)] * 3
    pairs += [pair(WRONG, WRONG)]
    assert h2(pairs) == (5, 2, 3, 1)
    assert "(both right, staged only, flat only, neither)" in FLAT


def test_the_interval_is_read_in_the_words_of_the_text():
    assert MARGIN == 0.10
    assert "does not answer worse than flat by more than 10 percentage points" in FLAT
    said = 'Its lower end above −10 points: "not worse by more than 10 points, on these questions".'
    assert said in FLAT
    assert 'Its upper end below 0: "worse". Neither: "not shown either way".' in FLAT
    assert "Were both to hold, both would be said" in FLAT
    assert READINGS[NOT_WORSE] == '"not worse by more than 10 points, on these questions"'
    assert READINGS[WORSE] == '"worse"'
    assert READINGS[NOT_SHOWN] == '"not shown either way"'
    assert READINGS[WORSE_WITHIN] == f"{READINGS[WORSE]}, and {READINGS[NOT_WORSE]}"
    # Every reading that paired.py can give has its words.
    assert set(READINGS) == {NOT_WORSE, WORSE, WORSE_WITHIN, NOT_SHOWN}


def test_the_records_are_held_against_the_conditions_that_the_text_names():
    assert CONDITIONS_NAME == of_the_code() == "more-sections"
    assert f"Every run is made under the conditions `{CONDITIONS_NAME}`" in FLAT


def test_the_kinds_stand_in_the_order_of_the_places():
    assert in_order(["named_first", "own_text", "named_first", "appendix"]) == [
        "appendix",
        "own_text",
        "named_first",
    ]
    assert in_order(["single_section", "named_first", "another"]) == [
        "named_first",
        "another",
        "single_section",
    ]
    assert in_order(list(reversed(KINDS))) == list(KINDS)


# --- thirty questions, their records written by hand ----------------------------------------


def kind_of(n: int) -> str:
    return KINDS[(n - 1) % len(KINDS)]


def question(n: int) -> dict:
    name, kind = f"archives-{n:02d}", kind_of(n)
    section, anchor = EVIDENCE[kind]
    named = 'the paper titled "A Sample Paper"' if kind == "search_first" else f"arXiv:{SAMPLE}"
    return {
        "id": name,
        "question": f"What value does {named} give for {name}?",
        "type": kind,
        "gold_papers": [SAMPLE],
        "gold_evidence": {
            "need": "all",
            "items": [{"arxiv_id": SAMPLE, "section_id": section, "anchor": anchor}],
        },
        "expect_found": True,
        "reference_answer": f"The value of {name} is 1.5.",
        "answer_key": {"numbers": [{"label": "the value", "value": 1.5}]},
        "accept_note": f"It has to give 1.5 for {name}.",
        "abstract_sufficient": False,
        "notes": {"kind": kind, "archive": ARCHIVES[(n - 1) % len(ARCHIVES)]},
    }


def said(n: int, layout: str, value: str = "1.5") -> str:
    return f"archives-{n:02d} {SAID_BY[layout]}: the value is {value}."


def record(
    folder: Path,
    n: int,
    layout: str,
    digest: str,
    *,
    text: str | None,
    chars: int,
    given: bool = True,
    listed: list[str] | None = None,
) -> None:
    """The record of the one run of a cell, with what the grader and the report read of it:
    a search where the question names no identifier, one call that returned text of the
    paper, and the answer."""
    name, kind = f"archives-{n:02d}", kind_of(n)
    count = len(list(folder.glob("*.jsonl")))
    run_id = f"20261201T{count:06d}Z_{name}_{layout}_ab12"
    usage = {"input_tokens": 1000, "output_tokens": 50}
    tools = []
    if kind == "search_first":
        ids = [SAMPLE] if listed is None else listed
        tools.append({"name": "search_papers", "first_line": {"shape": "search", "ids": ids}})
    if layout == "flat":
        first = {"shape": "paper", "arxiv_id": SAMPLE, "start": 0, "stop": 100_000}
        tools.append({"name": "read_paper", "first_line": first})
    else:
        section = EVIDENCE[kind][0] if given else "1"
        length = {"1": 100, "2": 115, "2.1": 10, "A": 43}[section]
        first = {"shape": "section", "arxiv_id": SAMPLE, "section_id": section}
        tools.append({"name": "read_section", "first_line": {**first, "start": 0, "stop": length}})
    turns = [
        {"record": "turn", "turn": at, "usage": usage, "tools": [{**tool, "status": "ok"}]}
        for at, tool in enumerate(tools, start=1)
    ]
    turns.append({"record": "turn", "turn": len(turns) + 1, "usage": usage, "tools": []})
    answer = None
    if text is not None:
        cited = [{"arxiv_id": SAMPLE, "section_id": EVIDENCE[kind][0]}]
        answer = {"answer": text, "found": True, "evidence": cited}
    lines = [
        {
            "record": "run",
            "run_id": run_id,
            "question_id": name,
            "toolset": layout,
            "repeat": 1,
            "questions": {"file": "questions.jsonl", "sha256": digest},
            "model": {"model": "claude-sonnet-5-5"},
            "code": {"commit": "c0ffee", "modified": False},
        },
        *turns,
        {
            "record": "end",
            "run_id": run_id,
            "reason": "answered" if answer else "turn_limit",
            "answer": answer,
            "turns": len(turns),
            "tool_calls": len(tools),
            "tool_result_chars": chars,
            "input_tokens": 1000 * len(turns),
            "output_tokens": 50 * len(turns),
            "parser_versions": [PARSER_VERSION],
        },
    ]
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"{run_id}.jsonl").write_text("".join(json.dumps(l) + "\n" for l in lines), "utf-8")


# What is not as usual in the thirty questions. Usually the staged run was given the
# anchor in 3,000 characters and the flat run in 9,000, and both answer 1.5.
NOT_GIVEN = {3, 8, 11, 15}  # staged runs that read section 1, where no anchor stands
CHARS = {(20, "staged"): 9_500, (21, "staged"): 9_000}  # more than flat, and as many
TEXTS = {
    (5, "staged"): None,  # no answer
    (5, "flat"): said(5, "flat", "2.5"),
    (6, "flat"): said(6, "flat", "2.5"),
    (9, "staged"): said(9, "staged", "2.5"),
    (15, "staged"): said(15, "staged", "2.5"),
    (16, "flat"): said(16, "flat", "2.5"),
}
# Second behind another paper; nothing listed; and listed in another version than asked.
LISTED = {(14, "staged"): ["2502.00002v1", SAMPLE], (19, "flat"): [], (24, "staged"): [OLDER]}
JUDGED = {
    said(5, "flat", "2.5"): (WRONG, WRONG, WRONG),  # the rule too: (b)
    said(6, "flat", "2.5"): (WRONG, WRONG, WRONG),  # (b)
    said(12, "staged"): (WRONG, RIGHT, WRONG),  # the rule says right: (a) and (b)
    said(15, "staged", "2.5"): (WRONG, WRONG, WRONG),  # (b)
    # The answers of 9 (staged) and 16 (flat) are right by the judge and wrong by the
    # rule: (a). By hand the first is wrong and the second right.
}
WRONG_BY_HAND = {
    said(5, "flat", "2.5"),
    said(6, "flat", "2.5"),
    said(9, "staged", "2.5"),
    said(15, "staged", "2.5"),
}


def build(folder: Path) -> dict:
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / "questions.jsonl"
    path.write_text("".join(json.dumps(question(n)) + "\n" for n in range(1, 31)), "utf-8")
    digest = file_digest(path)
    runs = folder / "runs"
    for n in range(1, 31):
        for layout in (("staged", "flat"), ("flat", "staged"))[n % 2]:
            if (n, layout) == (30, "flat"):
                continue
            record(
                runs,
                n,
                layout,
                digest,
                text=TEXTS.get((n, layout), said(n, layout)),
                chars=CHARS.get((n, layout), 3_000 if layout == "staged" else 9_000),
                given=not (layout == "staged" and n in NOT_GIVEN),
                listed=LISTED.get((n, layout)),
            )
    # The flat cell of the last question was spoilt three times, and given up.
    for at in range(3):
        run_id = f"20261201T9{at:05d}Z_archives-30_flat_dead"
        first = {"record": "run", "run_id": run_id, "question_id": "archives-30", "toolset": "flat"}
        first |= {"repeat": 1, "questions": {"file": "questions.jsonl", "sha256": digest}}
        (runs / f"{run_id}.jsonl").write_text(json.dumps(first) + "\n", "utf-8")
    files = {"folder": folder, "questions": path, "runs": runs}
    files |= {"sheet": folder / "answers.csv", "key": folder / "answers-key.csv"}
    argv = ["--questions", str(path), "--runs", str(runs), "--repeats", "1", "--seed", "3"]
    assert sheet.main([*argv, "--sheet", str(files["sheet"]), "--key", str(files["key"])]) == 0
    files["judge"] = judged_by(path, files["sheet"], folder / "judge.jsonl", JUDGED)
    files |= {"hand_sheet": folder / "hand.csv", "hand_key": folder / "hand-key.csv"}
    files |= {"rest_sheet": folder / "rest.csv", "rest_key": folder / "rest-key.csv"}
    return files


def arguments(files: dict, *, rest: bool = False) -> list[str]:
    names = ["questions", "runs", "sheet", "key", "judge", "hand_sheet", "hand_key"]
    names += ["rest_sheet", "rest_key"] if rest else []
    return [part for name in names for part in (f"--{name.replace('_', '-')}", str(files[name]))]


def by_hand(row: dict) -> str:
    return WRONG if row["answer"] in WRONG_BY_HAND else RIGHT


@pytest.fixture(scope="module")
def evaluated(tmp_path_factory):
    """The files of the thirty questions with the sheet graded, and the report of them."""
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(judge, "code_version", lambda: {"commit": "c0ffee", "modified": False})
        files = build(tmp_path_factory.mktemp("thirty"))
    assert hand.main(arguments(files)) == 0
    grade_sheet(files["hand_sheet"], by_hand)
    out = files["folder"] / "report.md"
    assert second.main([*arguments(files), "--out", str(out)], source=sample_source()) == 0
    return files, out.read_text("utf-8")


def test_the_head_says_what_the_report_is_made_of(evaluated):
    files, text = evaluated
    assert text.startswith("# Report of an evaluation with one run for a cell\n")
    assert f"Questions: questions.jsonl, SHA-256 {file_digest(files['questions'])}" in text
    assert "code c0ffee (59 runs)" in text
    assert (
        f"Judge: judge.jsonl, `{judge.JUDGE_VERSION}`, texts sha256 `{judge.texts_digest()}`"
        in text
    )
    assert "3 requests for an answer" in text
    assert "Verdicts: 46 by hand and 12 of the judge on 58 answer(s); 1 run(s) without" in text
    # Records written by hand name no conditions, and the report says so of every one.
    assert (
        "Held against the conditions 'more-sections' (conditions.py): 59 record(s) differ" in text
    )


def test_the_questions_are_counted_by_kind_and_archive(evaluated):
    _, text = evaluated
    assert "the report shows how many questions of each kind and archive there are" in FLAT
    table = part(text, "The questions")
    assert cells(table, "kind") == [*sorted(ARCHIVES), "all"]
    count = Counter((kind_of(n), ARCHIVES[(n - 1) % 4]) for n in range(1, 31))
    for kind in KINDS:
        row = [count[(kind, archive)] for archive in sorted(ARCHIVES)]
        assert cells(table, kind) == [*map(str, row), "6"]
    assert cells(table, "all") == ["7", "7", "8", "8", "30"]
    assert [line.split("|")[1].strip() for line in table.splitlines()[4:9]] == list(KINDS)


def test_the_runs_are_counted_by_layout(evaluated):
    _, text = evaluated
    table = part(text, "By layout")
    assert cells(table, "runs that count") == ["30", "29"]
    assert cells(table, "answered") == ["29 / 30", "29 / 29"]
    # Wrong: 5 without an answer, 9 and 15 by hand; and 5 and 6 of flat by hand.
    assert cells(table, "right, by the verdict") == ["27 / 30", "27 / 29"]
    assert cells(table, "the anchor was given") == ["26 / 30", "29 / 29"]
    assert cells(table, "right although the anchor was not given") == ["3", "0"]
    # A search first where the question names no identifier, so the text comes a response later.
    assert cells(table, "response in which the anchor was given")[1] == "1 (1 to 2)"
    assert cells(table, "cited strictly") == ["29 / 29 of 29", "29 / 29 of 29"]
    assert cells(table, "tool result chars per run") == [
        "3,000 (3,000 to 9,500)",
        "9,000 (9,000 to 9,000)",
    ]
    assert cells(table, "tool calls per run") == ["1 (1 to 2)", "1 (1 to 2)"]
    assert cells(table, "runs with a tool error") == ["0", "0"]
    # 2 or 3 responses of 1,000 and 50 tokens, at 2 and 10 dollars for a million.
    staged = (24 * 2 + 6 * 3) * (1000 * 2 + 50 * 10) / 1e6
    assert cells(table, "cost, computed")[0] == f"${staged:.2f}"
    assert "of them after the loop had asked again" not in table  # the records do not say


def test_the_verdicts_are_counted_by_where_they_come_from(evaluated):
    files, text = evaluated
    table = part(text, "The verdicts, and where they come from")
    keys = read_csv(files["hand_key"])
    drawn = Counter(line["toolset"] for line in keys if line["picked"] == SAMPLED)
    assert sum(drawn.values()) == 40
    assert cells(table, "answers") == ["29", "29"]
    assert cells(table, "graded by hand: (a) the rule") == ["2", "1"]  # 9 and 12; 16
    assert cells(table, "graded by hand: (b) the judge") == ["2", "2"]  # 12 and 15; 5 and 6
    assert cells(table, "graded by hand: (a) or (b)") == ["3", "3"]
    assert cells(table, "graded by hand: (c)") == [str(drawn["staged"]), str(drawn["flat"])]
    assert "left over" not in table
    assert cells(table, "the verdict is the grade by hand") == [
        str(3 + drawn["staged"]),
        str(3 + drawn["flat"]),
    ]
    assert cells(table, "the verdict is the judge's") == [
        str(26 - drawn["staged"]),
        str(26 - drawn["flat"]),
    ]
    assert cells(table, "runs without an answer: wrong") == ["1", "0"]
    # The rule and the judge on the 58 answers: 12 is right by the rule alone, 9 and 16
    # by the judge alone, and 5 and 6 of flat and 15 by neither.
    assert cells(table, "right |") == ["52", "1", "0"]
    assert cells(table, "wrong |") == ["2", "3", "0"]
    assert "differs from the verdict of the judge in 0 of the 40 answer(s) of (c)" in table
    assert "That is fewer than 3: an answer that was not graded by hand has the verdict of" in table
    # By hand: 42 right (the forty, 12 and 16) and 4 wrong, against the judge and the rule.
    by_hand_rows = {
        line.split("|")[1].strip(): [cell.strip() for cell in line.strip("|").split("|")][1:]
        for line in table.split("The grades by hand, against")[1].splitlines()
        if line.startswith(("| right", "| wrong"))
    }
    assert by_hand_rows == {
        "right": ["42", "41", "1", "0", "41", "1"],
        "wrong": ["4", "1", "3", "0", "0", "4"],
    }
    numbers = {(line["question_id"], line["toolset"]): line["number"] for line in keys}
    apart = [line for line in table.splitlines() if line.startswith("- archives-")]
    assert sorted(apart) == [
        f"- archives-09 staged (number {numbers[('archives-09', 'staged')]}, {DIFFER}): "
        "rule wrong, judge right, by hand wrong",
        f"- archives-12 staged (number {numbers[('archives-12', 'staged')]}, {DIFFER} {DOUBTED}): "
        "rule right, judge wrong, by hand right",
    ]
    assert "The judge: 174 requests with a reply; cost computed from their usage: $0.52." in table


def test_h1_is_read_question_by_question_with_a_sign_test(evaluated):
    _, text = evaluated
    table = part(text, "H1: tool result characters, question by question")
    # Thirty questions, one without its flat run; 20 was given more, 21 as many.
    assert (
        "Of the 29 question(s) with a run of both layouts, the staged run was given fewer "
        "characters in 27, more in 1, and as many in 1."
    ) in table
    assert sign_test(27, 1) == pytest.approx(29 / 2**28)
    assert f"One-sided exact sign test, ties left out: p = {29 / 2**28:.4g} (n = 28)." in table


def test_h2_is_the_paired_table_with_its_interval_and_what_it_says(evaluated):
    _, text = evaluated
    table = part(text, "H2: answers, question by question")
    # Staged wrong in 5, 9 and 15; flat wrong in 5 and 6; question 30 has no pair.
    assert cells(table, "staged right") == ["25", "1"]
    assert cells(table, "staged wrong") == ["2", "1"]
    assert "29 question(s): right in staged only 1, in flat only 2." in table
    estimate, low, high = adjusted_wald(1, 2, 29)
    # The formula as Section 13 writes it, with b = 1, c = 2 and n = 29.
    assert "(b − c)/(n + 2) ± 1.96 · √((b + c + 1) − (b − c)²/(n + 2)) / (n + 2)" in FLAT
    spread = 1.959964 * math.sqrt((1 + 2 + 1) - (1 - 2) ** 2 / 31) / 31
    assert (estimate, low, high) == pytest.approx((-1 / 31, -1 / 31 - spread, -1 / 31 + spread))
    assert (
        f"staged less flat: {estimate * 100:+.1f} points, 95% interval {low * 100:+.1f} to "
        f"{high * 100:+.1f} (adjusted Wald, `eval/paired.py`)."
    ) in table
    assert "-3.2 points, 95% interval -15.8 to +9.4" in table
    # The lower end is below ten points and above twenty: the margin decides the reading.
    assert reading(low, high, MARGIN) == NOT_SHOWN and reading(low, high, 0.20) == NOT_WORSE
    assert 'Read against the margin of 10 points: "not shown either way".' in table
    assert "1 question(s) of the file are in neither (below)." in table


def test_a_question_whose_cell_was_given_up_is_left_out_and_named(evaluated):
    _, text = evaluated
    assert (
        "it is left out of H1 and H2, and the report names it and the layout that is missing"
        in FLAT
    )
    assert part(text, "Questions left out of H1 and H2").splitlines()[2:] == [
        "- archives-30: no flat run that counts; given up after 3 spoilt runs of the cell",
        "",
    ]
    table = part(text, "Runs that do not count")
    assert cells(table, "the run did not finish") == ["0", "3"]
    assert "Spoilt runs kept: 3, cost computed $0.00." in table
    assert "Cells given up after 3 spoilt runs: 1 (archives-30 flat 1)." in table
    # Its staged run counts where runs are counted.
    assert cells(part(text, "Question by question"), "archives-30")[2:4] == ["right", "-"]


def test_the_anchor_and_the_right_answers_are_counted_by_kind_and_by_archive(evaluated):
    _, text = evaluated
    table = part(text, "By kind")
    assert cells(table, "kind") == [
        "questions",
        "staged: the anchor was given",
        "staged: right",
        "flat: the anchor was given",
        "flat: right",
    ]
    assert cells(table, "later_piece") == ["6", "5 / 6", "6 / 6", "6 / 6", "5 / 6"]
    assert cells(table, "appendix") == ["6", "6 / 6", "6 / 6", "6 / 6", "6 / 6"]
    assert cells(table, "own_text") == ["6", "4 / 6", "6 / 6", "6 / 6", "6 / 6"]
    assert cells(table, "search_first") == ["6", "6 / 6", "5 / 6", "6 / 6", "6 / 6"]
    assert cells(table, "named_first") == ["6", "5 / 6", "4 / 6", "5 / 5", "4 / 5"]
    assert (
        "Expected beforehand: the staged runs that were not given the anchor gather in "
        "`own_text` and `later_piece`."
    ) in FLAT
    assert (
        "Staged runs that were not given the anchor: 4 (later_piece 1, own_text 2, "
        "named_first 1). Expected beforehand: they gather in own_text and later_piece."
    ) in table
    table = part(text, "By archive")
    for at, archive in enumerate(ARCHIVES):
        own = [n for n in range(1, 31) if (n - 1) % 4 == at]
        staged_given = sum(1 for n in own if n not in NOT_GIVEN)
        staged_right = sum(1 for n in own if n not in (5, 9, 15))
        flat = [n for n in own if n != 30]
        flat_right = sum(1 for n in flat if n not in (5, 6))
        assert cells(table, archive) == [
            str(len(own)),
            f"{staged_given} / {len(own)}",
            f"{staged_right} / {len(own)}",
            f"{len(flat)} / {len(flat)}",
            f"{flat_right} / {len(flat)}",
        ]


def test_the_search_is_shown_for_the_questions_that_name_no_identifier(evaluated):
    _, text = evaluated
    assert (
        "For the `search_first` questions, whether a search listed the paper, beside the "
        "`named_first` questions."
    ) in FLAT
    table = part(text, "The questions that do not name their paper by its identifier")
    rows = [
        [cell.strip() for cell in line.strip("|").split("|")]
        for line in table.splitlines()
        if line.startswith(("| search_first", "| named_first"))
    ]
    assert rows == [
        # 14 was listed second, behind another paper, and 24 in an older version; the
        # flat run of 19 was listed nothing.
        ["search_first", "staged", "6", "6 / 6", "5", "1: 5, 2: 1", "6 / 6", "5 / 6"],
        ["search_first", "flat", "6", "5 / 6", "5", "1: 5", "6 / 6", "6 / 6"],
        ["named_first", "staged", "6", "-", "-", "-", "5 / 6", "4 / 6"],
        ["named_first", "flat", "5", "-", "-", "-", "5 / 5", "4 / 5"],
    ]


def test_the_answers_that_are_right_without_the_anchor_are_listed(evaluated):
    _, text = evaluated
    assert "the answers that are right although the anchor was not given" in FLAT
    listed = part(text, "Answers that are right although the anchor was not given")
    assert listed.splitlines()[2:] == [
        "- archives-03 staged (own_text): text of its paper was given",
        "- archives-08 staged (own_text): text of its paper was given",
        "- archives-11 staged (later_piece): text of its paper was given",
        "",
    ]


def test_why_the_wrong_runs_were_wrong_is_read_from_their_records(evaluated):
    _, text = evaluated
    table = part(text, "Why runs were wrong")
    assert cells(table, "no answer: turn_limit") == ["1", "0"]
    assert cells(table, "answered wrong, the passage was given") == ["1", "2"]  # 9; 5 and 6
    assert cells(table, "answered wrong, its paper was given but not the passage") == ["1", "0"]


def test_every_question_has_its_row(evaluated):
    _, text = evaluated
    table = part(text, "Question by question")
    assert len([line for line in table.splitlines() if line.startswith("| archives-")]) == 30
    assert cells(table, "question") == [
        "kind",
        "archive",
        "staged",
        "flat",
        "staged chars",
        "flat chars",
        "staged anchor",
        "flat anchor",
    ]
    assert cells(table, "archives-01") == [
        "later_piece", "hep-ph", "right", "right", "3,000", "9,000", "response 1", "response 1",
    ]  # fmt: skip
    assert cells(table, "archives-03")[6] == "no"
    assert cells(table, "archives-04")[6:] == ["response 2", "response 2"]  # after the search
    assert cells(table, "archives-05")[2:4] == ["no answer", "wrong"]
    assert cells(table, "archives-06")[2:4] == ["right", "wrong"]
    assert cells(table, "archives-30") == [
        "named_first", "hep-th", "right", "-", "3,000", "-", "response 1", "-",
    ]  # fmt: skip


def test_the_report_is_refused_while_a_grade_is_missing(tmp_path, capsys):
    files = build(tmp_path)
    assert hand.main(arguments(files)) == 0
    capsys.readouterr()
    assert second.main(arguments(files), source=sample_source()) == 1
    assert "refused: 46 row(s) are not graded yet (the first: number" in capsys.readouterr().err
    next(files["runs"].glob("*_archives-07_staged_*")).unlink()
    assert second.main(arguments(files), source=sample_source()) == 1
    assert "1 cell(s) of the plan are still to run" in capsys.readouterr().err


def test_three_grades_of_c_against_the_judge_and_the_report_is_of_grades_by_hand(tmp_path, capsys):
    files = build(tmp_path)
    assert hand.main(arguments(files)) == 0
    keys = {line["number"]: line for line in read_csv(files["hand_key"])}
    drawn = [number for number, line in keys.items() if line["picked"] == SAMPLED]
    against = set(drawn[:3])
    grade_sheet(
        files["hand_sheet"], lambda row: WRONG if row["number"] in against else by_hand(row)
    )
    capsys.readouterr()
    # The rule of three asks for the sheet of the 12 answers that are left.
    assert second.main(arguments(files), source=sample_source()) == 1
    assert "the sheet of the 12 that are left is not given" in capsys.readouterr().err
    assert hand.main(arguments(files, rest=True)) == 0
    left = read_csv(files["rest_sheet"])
    grade_sheet(
        files["rest_sheet"], lambda row: WRONG if row is left[0] or row == left[0] else RIGHT
    )
    capsys.readouterr()
    assert second.main(arguments(files, rest=True), source=sample_source()) == 0
    text = capsys.readouterr().out
    assert "Verdicts: 58 by hand and 0 of the judge on 58 answer(s)" in text
    table = part(text, "The verdicts, and where they come from")
    rest = cells(table, "graded by hand: left over, and graded after (c)")
    assert sum(map(int, rest)) == 12
    assert cells(table, "the verdict is the judge's") == ["0", "0"]
    assert (
        "in 3 of the 40 answer(s) of (c). That is 3 or more: every answer is graded by hand"
        in table
    )
    # Eight answers are wrong by hand now (four as before, the three of (c) and one of
    # the rest), and one run has no answer.
    by_layout = part(text, "By layout")
    right = [int(cell.split(" / ")[0]) for cell in cells(by_layout, "right, by the verdict")]
    assert sum(right) == 59 - 1 - 4 - 3 - 1
    # A sheet of the rest that the rule does not ask for is refused.
    grade_sheet(files["hand_sheet"], by_hand)
    assert second.main(arguments(files, rest=True), source=sample_source()) == 1
    assert "its grades are no part of the verdicts" in capsys.readouterr().err


def test_a_paper_that_cannot_be_read_leaves_the_anchor_untold(evaluated, capsys):
    files, _ = evaluated
    capsys.readouterr()
    # No paper can be read here, so nobody can tell what text a run was given.
    assert second.main(arguments(files), source=FixtureSource({})) == 0
    said = capsys.readouterr()
    assert f"cannot read {SAMPLE}" in said.err
    table = part(said.out, "By layout")
    assert cells(table, "the anchor was given") == ["0 / 30", "0 / 29"]
    assert cells(table, "right although the anchor was not given") == ["0", "0"]
    assert "Whether the anchor was given cannot be told of 59 run(s)" in table
    assert "Staged runs that were not given the anchor: 0." in part(said.out, "By kind")
    listed = part(said.out, "Answers that are right although the anchor was not given")
    assert listed.splitlines()[2] == "None."
    assert cells(part(said.out, "Question by question"), "archives-01")[6:] == ["?", "?"]
    # The verdicts need no paper.
    assert cells(table, "right, by the verdict") == ["27 / 30", "27 / 29"]


def test_a_file_of_questions_that_name_no_archive_has_no_table_by_archive(tmp_path, capsys):
    # The questions of the rehearsal are drafted for papers of the tuning, which have none.
    files = build(tmp_path)
    lines = [json.loads(line) for line in files["questions"].read_text("utf-8").splitlines()]
    for line in lines:
        del line["notes"]["archive"]
    files["questions"].write_text("".join(json.dumps(line) + "\n" for line in lines), "utf-8")
    digest = file_digest(files["questions"])
    for path in files["runs"].glob("*.jsonl"):
        records = [json.loads(line) for line in path.read_text("utf-8").splitlines()]
        records[0]["questions"]["sha256"] = digest
        path.write_text("".join(json.dumps(line) + "\n" for line in records), "utf-8")
    files["judge"] = judged_by(
        files["questions"], files["sheet"], files["folder"] / "again.jsonl", JUDGED
    )
    assert hand.main(arguments(files)) == 0
    grade_sheet(files["hand_sheet"], by_hand)
    capsys.readouterr()
    assert second.main(arguments(files), source=sample_source()) == 0
    text = capsys.readouterr().out
    assert "## By archive" not in text and "The questions name no archive." in text
    assert cells(part(text, "The questions"), "all") == ["30"]
    assert cells(part(text, "Question by question"), "archives-01")[1] == "-"


# --- the runs made by the commands ----------------------------------------------------------

CODE = {"commit": "c" * 40, "modified": False}
# What the scripted model does in the staged layout, by the first word of the question.
# In the flat layout it reads the paper and answers; "search" searches first in both.
STAGED = {
    "good": [("get_outline", None), ("read_section", "2.1")],
    "astray": [("get_outline", None), ("read_section", "1")],
    "silent": [("get_outline", None)],
    "search": [("search_papers", None), ("get_outline", None), ("read_section", "2.1")],
    "own": [("get_outline", None), ("read_section", "2")],
}
ASKED = {
    "good-1": "named_first",
    "astray-2": "named_first",
    "silent-3": "appendix",
    "search-4": "search_first",
    "own-5": "own_text",
}


def asked(name: str) -> dict:
    kind = ASKED[name]
    section, anchor = EVIDENCE[kind]
    named = 'the paper titled "A Sample Paper"' if kind == "search_first" else f"arXiv:{SAMPLE}"
    return {
        **question(1),
        "id": name,
        "question": f"{name}: what value does {named} give?",
        "type": kind,
        "gold_evidence": {
            "need": "all",
            "items": [{"arxiv_id": SAMPLE, "section_id": section, "anchor": anchor}],
        },
        "notes": {"kind": kind, "archive": "hep-ph"},
    }


def test_the_report_is_made_of_records_that_the_commands_wrote(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "not-a-real-key")
    monkeypatch.setattr(loop, "code_version", lambda: dict(CODE))
    monkeypatch.setattr(origin, "code_version", lambda: dict(CODE))

    class Scripted(ClaudeModel):
        def __init__(self, name, **settings):
            super().__init__(name, client=object(), **settings)
            self.turn = 0

        async def reply(self, system, messages, tools, answer_schema) -> Reply:
            self.turn += 1
            name = messages[0]["content"].split(":")[0]
            word = name.split("-")[0]
            flat = "get_outline" not in [tool["name"] for tool in tools]
            steps = STAGED[word]
            if flat:
                steps = [step for step in steps if step[0] == "search_papers"]
                steps = [*steps, ("read_paper", None)]
            if self.turn <= len(steps):
                tool, section = steps[self.turn - 1]
                if tool == "search_papers":
                    return asks((tool, {"query": "sample"}))
                given = {"arxiv_id": SAMPLE} | ({"section_id": section} if section else {})
                return asks((tool, given))
            if word == "silent" and not flat:
                return says("The paper does not say it plainly.")
            value = "2.5" if (word, flat) == ("own", False) else "1.5"
            text = f"{name} {SAID_BY['flat' if flat else 'staged']}: the value is {value}."
            cited = [{"arxiv_id": SAMPLE, "section_id": EVIDENCE[ASKED[name]][0]}]
            return asks(("submit_answer", {"answer": text, "found": True, "evidence": cited}))

    monkeypatch.setattr(command, "ClaudeModel", Scripted)
    monkeypatch.setattr(command, "Fetcher", lambda *args, **kwargs: None)
    monkeypatch.setattr(command, "ArxivSource", lambda fetcher: sample_source())
    questions = tmp_path / "questions.jsonl"
    questions.write_text("".join(json.dumps(asked(name)) + "\n" for name in ASKED), "utf-8")
    runs = tmp_path / "runs"
    argv = ["--questions", str(questions), "--out", str(runs), "--private", str(tmp_path / "p")]
    assert run.main([*argv, "--repeats", "1"], launch=command.main) == 0
    files = {"folder": tmp_path, "questions": questions, "runs": runs}
    files |= {"sheet": tmp_path / "answers.csv", "key": tmp_path / "p" / "answers-key.csv"}
    argv = ["--questions", str(questions), "--runs", str(runs), "--repeats", "1"]
    assert sheet.main([*argv, "--sheet", str(files["sheet"]), "--key", str(files["key"])]) == 0
    wrong = "own-5 P: the value is 2.5."
    files["judge"] = judged_by(
        questions, files["sheet"], tmp_path / "judge.jsonl", {wrong: (WRONG,) * 3}
    )
    files |= {"hand_sheet": tmp_path / "hand.csv", "hand_key": tmp_path / "p" / "hand-key.csv"}
    assert hand.main(arguments(files)) == 0
    assert len(read_csv(files["hand_sheet"])) == 9  # ten runs, and silent-3 gave no answer
    grade_sheet(files["hand_sheet"], lambda row: WRONG if row["answer"] == wrong else RIGHT)
    capsys.readouterr()
    assert second.main(arguments(files), source=sample_source()) == 0
    text = capsys.readouterr().out

    assert "Held against the conditions 'more-sections' (conditions.py): no record differs" in text
    assert "Verdicts: 9 by hand and 0 of the judge on 9 answer(s); 1 run(s) without" in text
    table = part(text, "By layout")
    assert cells(table, "runs that count") == ["5", "5"]
    assert cells(table, "answered") == ["4 / 5", "5 / 5"]
    # The loop asked the staged run of silent-3 for the call, and no answer came then either.
    assert cells(table, "of them after the loop had asked again") == ["0", "0"]
    assert cells(table, "right, by the verdict") == ["3 / 5", "5 / 5"]
    # astray-2 read section 1, and silent-3 read the outline alone.
    assert cells(table, "the anchor was given") == ["3 / 5", "5 / 5"]
    assert cells(table, "right although the anchor was not given") == ["1", "0"]
    chars = {}
    for path in runs.glob("*.jsonl"):
        lines = [json.loads(line) for line in path.read_text("utf-8").splitlines()]
        chars[(lines[0]["question_id"], lines[0]["toolset"])] = lines[-1]["tool_result_chars"]
    fewer = sum(1 for name in ASKED if chars[(name, "staged")] < chars[(name, "flat")])
    more = sum(1 for name in ASKED if chars[(name, "staged")] > chars[(name, "flat")])
    assert fewer + more == 5 and fewer >= 3
    assert f"fewer characters in {fewer}, more in {more}, and as many in 0." in text
    assert f"p = {sign_test(fewer, more):.4g} (n = 5)" in text
    table = part(text, "H2: answers, question by question")
    assert cells(table, "staged right") == ["3", "0"]
    assert cells(table, "staged wrong") == ["2", "0"]  # silent-3 and own-5
    low, high = adjusted_wald(0, 2, 5)[1:]
    assert READINGS[reading(low, high, MARGIN)] in table
    table = part(text, "The questions that do not name their paper by its identifier")
    assert "| search_first | staged | 1 | 1 / 1 | 1 | 1: 1 | 1 / 1 | 1 / 1 |" in table
    assert "| search_first | flat | 1 | 1 / 1 | 1 | 1: 1 | 1 / 1 | 1 / 1 |" in table
    assert "- astray-2 staged (named_first): text of its paper was given" in text
    table = part(text, "Why runs were wrong")
    assert cells(table, "no answer: no_answer") == ["1", "0"]
    assert cells(table, "answered wrong, the passage was given") == ["1", "0"]
    table = part(text, "Question by question")
    assert cells(table, "own-5")[:4] == ["own_text", "hep-ph", "wrong", "right"]
    assert cells(table, "silent-3")[2] == "no answer"
    assert part(text, "Questions left out of H1 and H2").splitlines()[2] == (
        "None: every question has a run of both layouts that counts."
    )


def test_a_sheet_of_the_rest_is_named_with_its_key_or_not_at_all(evaluated, capsys):
    files, _ = evaluated
    for module in (hand, second):
        for name in ("--rest-sheet", "--rest-key"):
            with pytest.raises(SystemExit) as stopped:
                module.main([*arguments(files), name, str(files["folder"] / "x.csv")])
            assert stopped.value.code == 2
            assert "--rest-sheet and --rest-key go together" in capsys.readouterr().err


def test_left_out_names_the_layouts_whose_cells_were_given_up():
    cells_ = [run.Cell("q1", "staged", 1), run.Cell("q1", "flat", 1), run.Cell("q2", "flat", 1)]
    cells_ += [run.Cell("q2", "staged", 1), run.Cell("q3", "staged", 1), run.Cell("q3", "flat", 1)]
    done = {cells_[0], cells_[1], cells_[3]}
    state = SimpleNamespace(
        cells=cells_,
        done=lambda cell: cell if cell in done else None,
        to_run=lambda cell: False,
    )
    questions = [SimpleNamespace(id=name) for name in ("q1", "q2", "q3")]
    assert left_out(questions, state) == [("q2", ["flat"]), ("q3", ["staged", "flat"])]
