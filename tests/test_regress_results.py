"""What was run after the tool texts were changed: the records, and what is said of them.

results/runs/regress/ holds the public records of five sets of runs made on 2026-11-20,
and beside them what was made from the runs of the development questions: the sheet of
their answers, its key, the record of the judge on that sheet, and the two texts that
eval.regress wrote. These tests hold the files against each other, against the question
files and the conditions, and hold up what the README of that folder says of the runs:
that the comparison failed and by what, how the runs of dev-02 ended when it was asked
again, and what the three target questions show.

No network and no LLM. Of the papers only the maintainer's own is kept here, so where
the comparison is written again, whether the passage of dev-03 was given is left out.
"""

from collections import Counter
from datetime import datetime, timedelta
from math import comb
from pathlib import Path
from statistics import median

import pytest
from test_results import DEV_SETS, OWN, cost, input_tokens, own_paper, read_from_cache

from hepph_paper_miner.agent.origin import file_digest
from hepph_paper_miner.eval import judge, regress
from hepph_paper_miner.eval.conditions import EVALUATION, REVISED, differences
from hepph_paper_miner.eval.grade import Record, grade, parent_of
from hepph_paper_miner.eval.questions import load_questions
from hepph_paper_miner.eval.run import Attempt, Cell, attempts_in, counted, plan
from hepph_paper_miner.eval.sheet import Row, read_key, write_key, write_sheet
from hepph_paper_miner.sources.fixture import FixtureSource

ROOT = Path(__file__).parent.parent
RUNS = ROOT / "results" / "runs"
HERE = RUNS / "regress"
DEV = ROOT / "eval_data" / "questions_dev.jsonl"
TARGETS = ROOT / "eval_data" / "questions_target.jsonl"
SHEET, KEY = HERE / "regress-dev-sheet.csv", HERE / "regress-dev-key.csv"
JUDGED = HERE / "regress-dev-j2.jsonl"

CHANGE, BEFORE_IT = "1b2baa3", "e66a854"  # the commit that changed the tool texts, and its parent

# folder: the question file, the commit, its conditions, the repetitions, the questions
# asked (None: every one of the file), the records, and when they were made (UTC)
SETS = {
    "target-before": (TARGETS, BEFORE_IT, EVALUATION, 3, None, 24, ("06:00", "06:18")),
    "dev-after": (DEV, CHANGE, REVISED, 3, None, 30, ("06:54", "07:00")),
    "target-after": (TARGETS, CHANGE, REVISED, 3, None, 18, ("07:01", "07:05")),
    "dev02-before": (DEV, BEFORE_IT, EVALUATION, 10, ("dev-02",), 20, ("07:50", "07:54")),
    "dev02-after": (DEV, CHANGE, REVISED, 10, ("dev-02",), 20, ("08:01", "08:06")),
}

# Every folder of records that the repository keeps: the evaluation, the sets of
# development runs, and the five sets above. Named and not looked for, as DEV_SETS is.
KEPT = ("eval", *(f"dev/{name}" for name in DEV_SETS), *(f"regress/{name}" for name in SETS))


def records(folder: str) -> list[Attempt]:
    """Every record of a folder, oldest first (a run id begins with the time of its start)."""
    found = [attempt for tried in attempts_in(HERE / folder).values() for attempt in tried]
    return sorted(found, key=lambda attempt: attempt.run["run_id"])


def that_count(folder: Path | str) -> dict[Cell, Attempt]:
    return counted(attempts_in(HERE / folder))


def asked(attempt: Attempt) -> list[tuple]:
    """What a run asked the tools of the server for, and the text that came back, by its hash."""
    return [
        (call["name"], call["arguments"], call["status"], call.get("result_sha256"))
        for turn in attempt.turns
        for call in turn["tools"]
        if call["name"] != "submit_answer"
    ]


def reads_with_end(attempts) -> list[tuple[str, int]]:
    """Every read that named an end: the section and the end."""
    return [
        (call["arguments"]["section_id"], call["arguments"]["end"])
        for attempt in attempts
        for turn in attempt.turns
        for call in turn["tools"]
        if call["name"] == "read_section" and "end" in call["arguments"]
    ]


def own_text() -> dict[str, int]:
    """For each section of the kept paper that has subsections: where its own text ends."""
    ends: dict[str, int] = {}
    for section in own_paper().sections:
        if section.level == 2:
            ends.setdefault(parent_of(section.section_id), section.heading_at)
    return ends


def passage_given(folder: str) -> dict[Cell, bool | None]:
    """For the runs of the target questions that count: whether the passage was given."""
    questions = {question.id: question for question in load_questions(TARGETS)}
    papers = {OWN: own_paper()}
    return {
        cell: grade(Record(a.run, a.turns, a.end), questions[cell.question_id], papers).access.met
        for cell, a in that_count(folder).items()
    }


def one_sided(before: int, after: int, runs: int = 20) -> float:
    """Fisher's test of `after` of `runs` against `before` of `runs`: as many or more after.

    The chance, when the two sides do not differ, that of all the runs that ended in one
    way at least `after` stand on the second side.
    """
    both = before + after
    ways = sum(comb(runs, k) * comb(runs, both - k) for k in range(after, min(runs, both) + 1))
    return ways / comb(2 * runs, both)


# --- the records --------------------------------------------------------------------------


@pytest.mark.parametrize("folder", SETS)
def test_a_set_is_the_plan_of_its_command_made_under_the_conditions_of_its_code(folder):
    file, commit, conditions, repeats, only, number, (first, last) = SETS[folder]
    found = records(folder)
    assert len(list((HERE / folder).glob("*.jsonl"))) == len(found) == number
    assert all(a.path.name == a.run["run_id"] + ".jsonl" and a.end is not None for a in found)
    # The cells that have a run that counts are the cells the command was asked for.
    cells = plan([question.id for question in load_questions(file)], repeats)
    cells = [cell for cell in cells if only is None or cell.question_id in only]
    assert sorted(that_count(folder)) == sorted(cells)
    digest = file_digest(file)
    for attempt in found:
        run = attempt.run
        assert differences(run, attempt.end, conditions) == [], run["run_id"]
        assert (run["code"]["commit"][:7], run["code"]["modified"]) == (commit, False)
        assert run["questions"] == {"file": file.name, "sha256": digest}, run["run_id"]
    # One run at a time, on the one day.
    for one, next_one in zip(found, found[1:]):
        assert one.end["ended_at"] <= next_one.run["started_at"], next_one.run["run_id"]
    made = (found[0].run["started_at"], found[-1].end["ended_at"])
    assert all(when.startswith("2026-11-20T") for when in made)
    assert tuple(when[11:16] for when in made) == (first, last)


def test_arxiv_spoilt_six_runs_of_the_target_questions_before_the_change_and_no_other():
    spoilt = {
        folder: Counter(str(a.cell)[:13] for a in records(folder) if a.spoilt) for folder in SETS
    }
    assert spoilt.pop("target-before") == {"tgt-01 staged": 4, "tgt-03 staged": 2}
    assert not any(spoilt.values())
    # Each of the six by a search that arXiv did not answer.
    failed = Counter(
        (call["name"], call["error_kind"])
        for attempt in records("target-before")
        for turn in attempt.turns
        for call in turn["tools"]
        if call["status"] == "error"
    )
    assert failed == {("search_papers", "upstream_busy"): 5, ("search_papers", "timeout"): 2}


def test_the_cost_of_each_set_is_what_the_readme_gives():
    assert {folder: cost(records(folder)) for folder in SETS} == {
        "target-before": 1.96,
        "dev-after": 1.56,
        "target-after": 0.84,
        "dev02-before": 0.48,
        "dev02-after": 0.52,
    }


# --- the development questions again -----------------------------------------------------


def test_two_runs_of_dev_02_ended_their_turn_with_text_and_no_call():
    after = that_count("dev-after")
    assert Counter(a.end["reason"] for a in after.values()) == {"answered": 28, "no_answer": 2}
    without = sorted(str(cell) for cell, a in after.items() if not a.end["answer"])
    assert without == ["dev-02 flat 2", "dev-02 staged 3"]
    for layout, repeat in (("flat", 2), ("staged", 3)):
        runs = {n: after[Cell("dev-02", layout, n)] for n in (1, 2, 3)}
        # It asked for what the two others asked for, and the same text came back.
        assert asked(runs[1]) == asked(runs[2]) == asked(runs[3])
        last = runs[repeat].turns[-1]
        assert (last["stop_reason"], last["blocks"], last["tools"]) == ("end_turn", ["text"], [])
    # Before the change every run of the five questions had ended with an answer.
    before = counted(attempts_in(RUNS / "dev" / "diag-3-tool"))
    assert len(before) == 30 and {a.end["reason"] for a in before.values()} == {"answered"}
    assert {a.run["started_at"][:10] for a in before.values()} == {"2026-11-16"}


def without_the_paper_of_dev_03(text: str) -> list[str]:
    """The lines of a comparison that can be written with the maintainer's paper alone."""
    lines = []
    for line in text.splitlines():
        if line.startswith("- 2 ") or line.endswith(": its paper could not be read"):
            continue  # whether the passage was given, which is open here for that paper
        cells = line.split(" | ")
        if cells[0] == "| dev-03":
            cells[4] = "?"  # the column "passage given"
        lines.append(" | ".join(cells))
    return lines


def test_the_comparison_is_what_the_command_writes_from_these_files_and_it_failed(
    tmp_path, monkeypatch
):
    # Paths as the README of the folder gives them: the text names the folders.
    monkeypatch.chdir(ROOT)
    here = "results/runs/regress"
    argv = ["--questions", "eval_data/questions_dev.jsonl"]
    argv += ["--before", "results/runs/dev/diag-3-tool", "--after", f"{here}/dev-after"]
    argv += ["--sheet", f"{here}/regress-dev-sheet.csv", "--key", f"{here}/regress-dev-key.csv"]
    argv += ["--judge", f"{here}/regress-dev-j2.jsonl", "--out", str(tmp_path / "dev.md")]
    assert regress.main(argv, source=FixtureSource([own_paper()])) == 1
    kept = (HERE / "regress-dev.md").read_text("utf-8")
    written = without_the_paper_of_dev_03((tmp_path / "dev.md").read_text("utf-8"))
    assert written == without_the_paper_of_dev_03(kept)

    said = [line for line in kept.splitlines() if line.startswith(("- ", "    - "))]
    assert said == [
        "- 1 every run ended with an answer: failed",
        "    - dev-02 flat 2: ended as no_answer",
        "    - dev-02 staged 3: ended as no_answer",
        "- 2 the passage was given in every run: passed",
        "- 3 the rule calls no answer wrong: failed",
        "    - dev-02 flat 2: the rule calls the answer wrong",
        "    - dev-02 staged 3: the rule calls the answer wrong",
        "    - dev-03 flat 3: right by the rule in every run before, by_hand now",
        "- 4 no answer left to a person is wrong: passed",
        "- 5 staged was given less text than flat: passed",
    ]
    assert "The runs after, held against the runs before: failed." in kept
    assert "; 30 runs; tool texts staged-5, flat-4; code 9d8024c" in kept
    assert "; 30 runs; tool texts staged-6, flat-5; code 1b2baa3" in kept
    assert "has changed since the judge read it" not in kept


def test_the_sheet_its_key_and_the_record_of_the_judge_are_those_of_the_runs_after(tmp_path):
    questions = {question.id: question for question in load_questions(DEV)}
    by_run = {attempt.run["run_id"]: attempt for attempt in that_count("dev-after").values()}
    key = read_key(KEY)
    assert sorted(key) == list(range(1, 29))
    answered = sorted(run_id for run_id, attempt in by_run.items() if attempt.end["answer"])
    assert sorted(line["run_id"] for line in key.values()) == answered
    # Written again from the records, both files come out byte for byte: nothing was
    # changed in them, and nobody wrote a grade.
    rows = [
        Row(number, questions[line["question_id"]], by_run[line["run_id"]])
        for number, line in sorted(key.items())
    ]
    write_key(rows, tmp_path / "key.csv")
    write_sheet(rows, tmp_path / "sheet.csv")
    assert (tmp_path / "key.csv").read_bytes() == KEY.read_bytes()
    assert (tmp_path / "sheet.csv").read_bytes() == SHEET.read_bytes()

    head, lines, end = judge.read_record(JUDGED)
    assert (head["judge_version"], head["texts_sha256"]) == ("j2", judge.texts_digest())
    assert (head["code"]["commit"][:7], head["code"]["modified"]) == (CHANGE, False)
    assert head["questions"]["sha256"] == file_digest(DEV) and head["only"] is None
    # The sheet is the file the judge read: the same bytes.
    assert head["sheet"] == {"file": SHEET.name, "sha256": file_digest(SHEET), "answers": 28}
    assert head["controls"] is None
    verdicts = [line["verdict"] for line in lines if line["record"] == "verdict"]
    assert Counter(verdicts) == {"right": 84} and end["requests"] == 84
    assert round(end["cost"], 2) == 0.30


def test_the_answer_of_dev_03_left_to_a_person_has_the_four_values_and_two_of_another_channel():
    question = next(question for question in load_questions(DEV) if question.id == "dev-03")
    listed = {
        number["value"]: number["label"]
        for number in question.answer_key["wrong_numbers"]
        if number["value"] in (127.5, 125.7)
    }
    assert set(listed.values()) == {"another channel of 1601.05089v3"} and len(listed) == 2
    answer = that_count("dev-after")[Cell("dev-03", "flat", 3)].end["answer"]["answer"]
    for written in ("69.2", "35.7", "2.26×10⁻²⁶", "2.2", "127.5", "125.7", "I did not use"):
        assert written in answer
    # The judge called it right in each of its three requests.
    (number,) = [n for n, line in read_key(KEY).items() if "_dev-03_flat_1e12" in line["run_id"]]
    _, lines, _ = judge.read_record(JUDGED)
    assert [x["verdict"] for x in lines if x.get("item") == f"sheet-{number}"] == ["right"] * 3


def test_no_call_failed_after_the_change_and_end_was_used_seventeen_times():
    after = [*that_count("dev-after").values(), *that_count("target-after").values()]
    assert len(after) == 48
    assert not [
        c for a in after for turn in a.turns for c in turn["tools"] if c["status"] == "error"
    ]
    # Before, each staged run of dev-01 named the section "section", and took a response more.
    before = counted(attempts_in(RUNS / "dev" / "diag-3-tool"))
    errors = Counter(
        (str(cell)[:13], call["error_kind"], tuple(sorted(call["arguments"])))
        for cell, attempt in before.items()
        for turn in attempt.turns
        for call in turn["tools"]
        if call["status"] == "error"
    )
    assert errors == {("dev-01 staged", "invalid_arguments", ("arxiv_id", "section")): 3}
    dev_01 = [Cell("dev-01", "staged", n) for n in (1, 2, 3)]
    assert [before[cell].end["turns"] for cell in dev_01] == [4, 4, 4]
    assert [that_count("dev-after")[cell].end["turns"] for cell in dev_01] == [3, 3, 3]

    ends, own = Counter(reads_with_end(after)), own_text()
    assert sum(ends.values()) == 17
    of_own_text = {read: n for read, n in ends.items() if own.get(read[0]) == read[1]}
    assert of_own_text == {("3", 1804): 9, ("6", 926): 2, ("4", 1072): 1}
    assert sum(ends.values()) - sum(of_own_text.values()) == 5


def test_the_staged_runs_of_dev_05_read_the_own_text_of_section_3_and_two_ran_a_search():
    cells = [Cell("dev-05", "staged", n) for n in (1, 2, 3)]
    before = counted(attempts_in(RUNS / "dev" / "diag-3-tool"))
    after = that_count("dev-after")
    assert [before[cell].end["turns"] for cell in cells] == [6, 6, 5]
    assert [after[cell].end["turns"] for cell in cells] == [6, 7, 7]
    assert all(("3", 1804) in reads_with_end([after[cell]]) for cell in cells)
    searched = [
        sum(call["name"] == "search_papers" for turn in after[cell].turns for call in turn["tools"])
        for cell in cells
    ]
    assert searched == [0, 1, 1]


def test_the_flat_runs_after_the_change_cost_less_because_they_read_more_from_the_cache():
    sides = {
        "before": counted(attempts_in(RUNS / "dev" / "diag-3-tool")),
        "after": that_count("dev-after"),
    }
    flat = {
        name: [a for c, a in runs.items() if c.toolset == "flat"] for name, runs in sides.items()
    }
    assert {name: cost(runs) for name, runs in flat.items()} == {"before": 1.89, "after": 1.11}
    written = {n: sum(a.end["cache_creation_input_tokens"] for a in r) for n, r in flat.items()}
    read = {name: sum(read_from_cache(a) for a in runs) for name, runs in flat.items()}
    assert written == {"before": 702_177, "after": 376_910}
    assert read == {"before": 583_966, "after": 786_975}
    # Every flat run was given a whole paper either way: what was sent hardly differs.
    sent = {name: sum(input_tokens(a) for a in runs) for name, runs in flat.items()}
    assert abs(sent["after"] / sent["before"] - 1) < 0.1

    # The cache keeps for five minutes. After the change the second run of a question
    # came within that time of the first, and before the change it did not.
    def apart(runs: list[Attempt]) -> float:
        started = {a.cell: datetime.fromisoformat(a.run["started_at"]) for a in runs}
        gaps = [
            started[c] - started[Cell(c.question_id, "flat", 1)] for c in started if c.repeat == 2
        ]
        return median(gap / timedelta(minutes=1) for gap in gaps)

    assert apart(flat["after"]) < 5 < apart(flat["before"])


# --- dev-02 asked again -------------------------------------------------------------------


def test_asked_again_no_run_of_dev_02_ended_without_an_answer_before_or_after_the_change():
    ends = {
        folder: Counter((a.cell.toolset, a.end["reason"]) for a in records(folder))
        for folder in ("dev02-before", "dev02-after")
    }
    every_run_answered = {("staged", "answered"): 10, ("flat", "answered"): 10}
    assert ends == {"dev02-before": every_run_answered, "dev02-after": every_run_answered}
    # One set right after the other.
    done = datetime.fromisoformat(records("dev02-before")[-1].end["ended_at"])
    begun = datetime.fromisoformat(records("dev02-after")[0].run["started_at"])
    assert timedelta(0) < begun - done < timedelta(minutes=10)

    # The reading that was fixed before these runs: "more often after" only below 0.05.
    assert one_sided(0, 0) == 1.0
    assert one_sided(0, 5) < 0.05 <= one_sided(0, 4)
    assert one_sided(1, 6) < 0.05 <= one_sided(1, 5)
    # What twenty runs with an answer leave open: a third is out, a twentieth is not.
    assert round((1 - 1 / 3) ** 20 * 10_000) == 3
    assert round((1 - 1 / 20) ** 20, 2) == 0.36


def test_of_the_runs_that_hand_in_with_the_tool_one_before_the_change_ended_without_the_call():
    old, new = EVALUATION["toolset_version"].values(), REVISED["toolset_version"].values()
    ended: Counter = Counter()
    with_the_tool: Counter = Counter()
    # "Every run in this repository" is every run of the folders it keeps. Whatever else
    # lies under results/runs in a checkout is not counted.
    for folder in KEPT:
        runs = counted(attempts_in(RUNS / folder))
        assert runs, folder
        for cell, attempt in runs.items():
            if attempt.run.get("answer_channel") != "tool":
                continue
            texts = attempt.run["toolset_version"]
            assert (texts in old) != (texts in new), attempt.run["run_id"]
            with_the_tool[folder] += 1
            ended["changed" if texts in new else "evaluation", attempt.end["reason"]] += 1
            if attempt.end["reason"] == "no_answer" and texts in old:
                assert str(cell) == "eval-13 staged 3"
    # The 188 are the first four of these folders, the 68 the last three.
    assert with_the_tool == {
        "eval": 120,
        "dev/diag-3-tool": 30,
        "regress/target-before": 18,
        "regress/dev02-before": 20,
        "regress/dev-after": 30,
        "regress/target-after": 18,
        "regress/dev02-after": 20,
    }
    assert ended == {
        ("evaluation", "answered"): 186,
        ("evaluation", "no_answer"): 1,
        ("evaluation", "turn_limit"): 1,
        ("changed", "answered"): 66,
        ("changed", "no_answer"): 2,
    }


# --- the three target questions -----------------------------------------------------------


def test_the_count_of_the_target_questions_is_what_the_command_writes_and_it_is_shown(
    tmp_path, monkeypatch
):
    monkeypatch.chdir(ROOT)
    here = "results/runs/regress"
    argv = ["--questions", "eval_data/questions_target.jsonl", "--targets"]
    argv += ["--before", f"{here}/target-before", "--after", f"{here}/target-after"]
    argv += ["--out", str(tmp_path / "target.md")]
    assert regress.main(argv, source=FixtureSource([own_paper()])) == 0
    kept = (HERE / "regress-target.md").read_text("utf-8")
    assert (tmp_path / "target.md").read_text("utf-8") == kept
    assert "- tgt-01: 2 of 3 before, 3 after\n- tgt-02: 0 of 3 before, 3 after\n" in kept
    assert "- tgt-03: 2 of 3 before, 2 after\n" in kept
    assert "The effect of the change on these questions: shown." in kept
    # The responses and the characters that the README of the folder puts side by side.
    for row in (
        "| tgt-01 | staged | before | 3 / 3 | 2 / 3 | 2 right, 1 wrong | 6 9 7 | 55,943 |",
        "| tgt-01 | staged | after | 3 / 3 | 3 / 3 | 3 right | 4 4 4 | 9,337 |",
        "| tgt-02 | staged | before | 3 / 3 | 0 / 3 | 3 wrong | 8 7 7 | 41,529 |",
        "| tgt-02 | staged | after | 3 / 3 | 3 / 3 | 3 by_hand | 4 4 4 | 11,992 |",
        "| tgt-03 | staged | before | 3 / 3 | 2 / 3 | 3 by_hand | 11 5 11 | 96,229 |",
        "| tgt-03 | staged | after | 3 / 3 | 2 / 3 | 2 by_hand, 1 wrong | 4 3 10 | 21,439 |",
    ):
        assert row in kept


def test_the_passage_was_given_in_four_staged_runs_before_the_change_and_in_eight_after():
    given = {folder: passage_given(folder) for folder in ("target-before", "target-after")}
    for folder, cells in given.items():
        assert len(cells) == 18
        assert all(met for cell, met in cells.items() if cell.toolset == "flat"), folder
    staged = {
        folder: sorted(str(cell) for cell, met in cells.items() if cell.toolset == "staged" and met)
        for folder, cells in given.items()
    }
    assert staged["target-before"] == [
        "tgt-01 staged 1",
        "tgt-01 staged 3",
        "tgt-03 staged 2",
        "tgt-03 staged 3",
    ]
    assert len(staged["target-after"]) == 8
    assert "tgt-03 staged 3" not in staged["target-after"]

    section = {q.id: q.evidence[0].section_id for q in load_questions(TARGETS)}
    assert section == {"tgt-01": "3", "tgt-02": "3", "tgt-03": "6"}
    own, after = own_text(), that_count("target-after")
    for cell, attempt in after.items():
        if cell.toolset != "staged":
            continue
        its_own_text = (section[cell.question_id], own[section[cell.question_id]])
        if str(cell) in staged["target-after"]:
            # The read the outline names, and an answer with the third or fourth response.
            assert its_own_text in reads_with_end([attempt]), cell
            assert attempt.end["turns"] in (3, 4) and attempt.end["answer"]["found"], cell
    # The ninth: the subsections of 6, six other sections and the own text of 4, never
    # that of 6; then "the paper does not say", with its tenth response.
    ninth = after[Cell("tgt-03", "staged", 3)]
    read = [
        arguments["section_id"] for name, arguments, _, _ in asked(ninth) if name != "get_outline"
    ]
    assert sorted(set(read)) == ["1", "3.6", "4", "4.2", "5", "6.1", "6.2", "6.3", "7", "8"]
    assert reads_with_end([ninth]) == [("6.3", 9000), ("6.3", 20000), ("4", 1072)]
    assert (ninth.end["turns"], ninth.end["answer"]["found"]) == (10, False)

    before = that_count("target-before")
    took = [a.end["turns"] for cell, a in before.items() if cell.toolset == "staged"]
    assert (min(took), max(took)) == (5, 11)
    # Before the change, a run that was given the passage had read the section itself.
    for cell, attempt in before.items():
        if cell.toolset != "staged":
            continue
        whole = any(
            name == "read_section" and arguments["section_id"] == section[cell.question_id]
            for name, arguments, _, _ in asked(attempt)
        )
        assert whole == (str(cell) in staged["target-before"]), cell
    not_found = sorted(str(c) for c, a in before.items() if not a.end["answer"]["found"])
    assert not_found == ["tgt-01 staged 2", "tgt-02 staged 1", "tgt-02 staged 2", "tgt-02 staged 3"]
