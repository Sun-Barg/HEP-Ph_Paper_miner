"""What was run after the loop began to ask for the call: the records, and what is said of them.

results/runs/asking-again/ holds what was made on 2026-11-23 with the prompt p3-tool:
the record of the twenty requests that sent the two ends of dev-02 again, the public
records of the development questions run once more, the sheet of their answers, its key,
the record of the judge on that sheet, and the text that eval.regress wrote. These tests
hold the files against each other, against the question file and the conditions, and
hold up what the README of that folder and the README of the repository say of them:
that all twenty requests came back with the call, that the comparison passed, and that
the loop asked in no run.

How the twenty requests are read, and by which criteria the runs are held against the
runs before, was written in the commit that changed the loop, before any of this was
run. The tests name that reading where they apply it.

No network and no LLM. Of the papers only the maintainer's own is kept here, so where
the comparison is written again, whether the passage of dev-03 was given is left out.
"""

import hashlib
from collections import Counter
from pathlib import Path

from test_regress_results import asked, reads_with_end
from test_results import OWN, cost, own_paper, read_csv, read_from_cache

from hepph_paper_miner.agent.origin import file_digest
from hepph_paper_miner.agent.prompt import ASK_AGAIN_TEXT
from hepph_paper_miner.eval import judge, regress, replay
from hepph_paper_miner.eval.conditions import ASKING_AGAIN, REVISED, differences
from hepph_paper_miner.eval.grade import BY_HAND, RIGHT, Record, grade_answer
from hepph_paper_miner.eval.questions import load_questions
from hepph_paper_miner.eval.replay import HANDED_IN, ended_without_the_call
from hepph_paper_miner.eval.run import Attempt, Cell, attempts_in, counted, plan
from hepph_paper_miner.eval.sheet import (
    KEY_COLUMNS,
    SHEET_COLUMNS,
    Row,
    _cell,
    read_grades,
    read_key,
    write_key,
    write_sheet,
)
from hepph_paper_miner.sources.fixture import FixtureSource

ROOT = Path(__file__).parent.parent
RUNS = ROOT / "results" / "runs"
HERE = RUNS / "asking-again"
AFTER = HERE / "dev-after"
BEFORE = RUNS / "regress" / "dev-after"  # the runs of 2026-11-20 that these are held against
DEV = ROOT / "eval_data" / "questions_dev.jsonl"
SHEET, KEY = HERE / "dev-sheet.csv", HERE / "dev-key.csv"
JUDGED = HERE / "dev-j2.jsonl"
COMPARED = HERE / "regress-dev.md"
SENT_AGAIN = HERE / "replay-dev-02.jsonl"
GRADED = HERE / "replay-dev-02-sheet.csv"  # the twenty answers, graded by hand afterwards
GRADED_KEY = HERE / "replay-dev-02-key.csv"

CHANGE, BEFORE_IT = (
    "0af1c02",
    "1b2baa3",
)  # the commit that made the loop ask; that of the runs before
# Of twenty requests, the number that hand in an answer from which the message is said
# to have got it handed in: eval/replay.py says so since CHANGE, and so before any request.
ENOUGH = 18
VERDICT = "The runs after, held against the runs before: "


def records() -> list[Attempt]:
    """Every record of the folder of runs, oldest first."""
    found = [attempt for tried in attempts_in(AFTER).values() for attempt in tried]
    return sorted(found, key=lambda attempt: attempt.run["run_id"])


def sides() -> dict[str, dict[Cell, Attempt]]:
    """The runs that count, before the loop asked and after."""
    return {"before": counted(attempts_in(BEFORE)), "after": counted(attempts_in(AFTER))}


def of(runs: dict[Cell, Attempt], question_id: str, layout: str) -> list[Attempt]:
    """The runs of one question with one layout, by repetition."""
    found = [
        (c.repeat, a)
        for c, a in runs.items()
        if (c.question_id, c.toolset) == (question_id, layout)
    ]
    return [attempt for _, attempt in sorted(found, key=lambda pair: pair[0])]


def written_to_cache(attempts) -> int:
    return sum(attempt.end["cache_creation_input_tokens"] for attempt in attempts)


# --- the runs -----------------------------------------------------------------------------


def test_the_runs_are_the_plan_of_the_command_under_the_conditions_of_the_loop_that_asks():
    found = records()
    assert len(list(AFTER.glob("*.jsonl"))) == len(found) == 32
    assert all(a.path.name == a.run["run_id"] + ".jsonl" and a.end is not None for a in found)
    cells = plan([question.id for question in load_questions(DEV)], 3)
    assert sorted(sides()["after"]) == sorted(cells) and len(cells) == 30
    digest = file_digest(DEV)
    for attempt in found:
        run = attempt.run
        assert differences(run, attempt.end, ASKING_AGAIN) == [], run["run_id"]
        # The prompt is all that parts them from the conditions of the runs before.
        assert differences(run, attempt.end, REVISED) == [
            "prompt_version is 'p3-tool', not 'p2-tool'"
        ]
        assert (run["code"]["commit"][:7], run["code"]["modified"]) == (CHANGE, False)
        assert run["questions"] == {"file": DEV.name, "sha256": digest}, run["run_id"]
    # One run at a time, on the one day.
    for one, next_one in zip(found, found[1:]):
        assert one.end["ended_at"] <= next_one.run["started_at"], next_one.run["run_id"]
    made = (found[0].run["started_at"], found[-1].end["ended_at"])
    assert all(when.startswith("2026-11-23T") for when in made)
    assert tuple(when[11:16] for when in made) == ("03:43", "03:52")
    # The runs they are held against: the same tool texts, the prompt before, another commit.
    for attempt in sides()["before"].values():
        assert differences(attempt.run, attempt.end, REVISED) == []
        assert attempt.run["code"]["commit"][:7] == BEFORE_IT


def test_arxiv_spoilt_two_runs_of_one_cell_and_each_of_them_still_handed_in_an_answer():
    found = records()
    spoilt = [attempt for attempt in found if attempt.spoilt]
    assert [str(attempt.cell) for attempt in spoilt] == ["dev-05 staged 3"] * 2
    # Each by a search that arXiv did not answer, and no other call came back as an error.
    failed = [
        (attempt.run["run_id"], call["name"], call["error_kind"], round(call["seconds"]))
        for attempt in found
        for turn in attempt.turns
        for call in turn["tools"]
        if call["status"] == "error"
    ]
    assert failed == [
        (spoilt[0].run["run_id"], "search_papers", "upstream_busy", 43),
        (spoilt[1].run["run_id"], "search_papers", "upstream_busy", 59),
    ]
    # The cell was run a third time, and that run asked for no search and counts.
    third = sides()["after"][Cell("dev-05", "staged", 3)]
    assert [a.run["run_id"] for a in found if str(a.cell) == "dev-05 staged 3"] == [
        spoilt[0].run["run_id"],
        spoilt[1].run["run_id"],
        third.run["run_id"],
    ]
    assert not [name for name, _, _, _ in asked(third) if name == "search_papers"]
    # A spoilt run is left out whatever it ended with. Both went on and said what the six
    # runs of the question that count say: the paper does not give it.
    for attempt in (
        *spoilt,
        *(a for c, a in sides()["after"].items() if c.question_id == "dev-05"),
    ):
        assert attempt.end["reason"] == "answered" and attempt.end["answer"]["found"] is False


def test_every_run_ended_with_the_call_and_the_loop_asked_in_none():
    found = records()
    for attempt in found:
        assert attempt.end["reason"] == "answered", attempt.run["run_id"]
        # The record says whether the loop asked, and it did not.
        assert "asked_again" in attempt.end and attempt.end["asked_again"] is None
        assert not any("asked_again" in turn for turn in attempt.turns)
        # It had nothing to ask about: every response asked for tools, the last for the
        # tool of the loop and for that alone.
        assert {turn["stop_reason"] for turn in attempt.turns} == {"tool_use"}
        assert [call["name"] for call in attempt.turns[-1]["tools"]] == ["submit_answer"]
        assert not ended_without_the_call(attempt)
    assert sum(len(attempt.turns) for attempt in found) == 113

    # The runs before were made by a loop that could not ask, and their records do not
    # say. Two of them ended their turn without the call, both of dev-02.
    runs = sides()
    assert not any("asked_again" in attempt.end for attempt in runs["before"].values())
    ends = {
        name: Counter(a.end["reason"] for c, a in side.items() if c.question_id == "dev-02")
        for name, side in runs.items()
    }
    assert ends == {"before": {"answered": 4, "no_answer": 2}, "after": {"answered": 6}}
    assert sorted(str(c) for c, a in runs["before"].items() if ended_without_the_call(a)) == [
        "dev-02 flat 2",
        "dev-02 staged 3",
    ]
    # "Seven times in ten": thirty runs that meet no such turn, when 3 runs of 256 had one
    # (tests/test_regress_results.py counts the 256, and the 286 there are with these).
    assert round((1 - 3 / 256) ** 30, 1) == 0.7


# --- held against the runs before ---------------------------------------------------------


def lines_that_need_no_other_paper(text: str) -> list[str]:
    """The lines of a comparison that can be written with the maintainer's paper alone.

    Without the paper of dev-03 the second criterion stays open for its six runs, and
    with it the word that the comparison comes to.
    """
    lines = []
    for line in text.splitlines():
        if line.startswith(("- 2 ", VERDICT)) or line.endswith(": its paper could not be read"):
            continue
        cells = line.split(" | ")
        if cells[0] == "| dev-03":
            cells[4] = "?"  # the column "passage given"
        lines.append(" | ".join(cells))
    return lines


def written_again(folder: Path, monkeypatch, *more: str) -> tuple[int, str]:
    """The comparison as the command writes it here, with the kept paper alone."""
    # Paths as the README of the folder gives them: the text names the folders.
    monkeypatch.chdir(ROOT)
    here = "results/runs/asking-again"
    argv = ["--questions", "eval_data/questions_dev.jsonl", *more]
    argv += ["--before", "results/runs/regress/dev-after", "--after", f"{here}/dev-after"]
    argv += ["--sheet", f"{here}/dev-sheet.csv", "--key", f"{here}/dev-key.csv"]
    argv += ["--judge", f"{here}/dev-j2.jsonl", "--out", str(folder / "dev.md")]
    code = regress.main(argv, source=FixtureSource([own_paper()]))
    return code, (folder / "dev.md").read_text("utf-8")


def test_the_comparison_is_what_the_command_writes_from_these_files_and_it_passed(
    tmp_path, monkeypatch
):
    # By the second set of criteria, as CHANGE said these runs would be held.
    code, written = written_again(tmp_path, monkeypatch, "--criteria", "2")
    kept = COMPARED.read_text("utf-8")
    assert lines_that_need_no_other_paper(written) == lines_that_need_no_other_paper(kept)

    # What is open here is the six runs of dev-03, whose paper is not kept, and no more:
    # in the 24 runs about the kept paper the passage was given.
    assert code == 1 and VERDICT + "not decided." in written
    assert "- 2 the passage was given in every run: not decided" in written
    open_here = [line.strip() for line in written.splitlines() if line.startswith("    - ")]
    assert sorted(open_here) == sorted(
        f"- dev-03 {layout} {n}: its paper could not be read"
        for layout in ("staged", "flat")
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
    here = "results/runs"
    assert f"Before: {here}/regress/dev-after; 30 runs; tool texts staged-6, flat-5; " in kept
    assert "flat-5; prompt p2-tool; code 1b2baa3\n" in kept
    assert f"After: {here}/asking-again/dev-after; 30 runs; tool texts staged-6, flat-5; " in kept
    assert "flat-5; prompt p3-tool; code 0af1c02\n" in kept
    assert "has changed since the judge read it" not in kept
    assert "more responses than any run before" not in kept


def test_the_first_set_of_criteria_would_have_said_the_same(tmp_path, monkeypatch):
    (tmp_path / "1").mkdir()
    (tmp_path / "2").mkdir()
    _, first = written_again(tmp_path / "1", monkeypatch)
    _, second = written_again(tmp_path / "2", monkeypatch, "--criteria", "2")
    # The two texts differ in the line that names the set, and in nothing else.
    named = [line for line in second.splitlines() if line.startswith("Criteria: ")]
    assert len(named) == 1 and "Criteria: " not in first
    assert [line for line in second.splitlines() if line not in named] == first.splitlines()
    # What the second set leaves out: an answer left to a person where the rule had called
    # every answer of that question and layout right before. There is none.
    runs = sides()
    questions = {question.id: question for question in load_questions(DEV)}

    def rules(side: str, question_id: str, layout: str) -> list[str]:
        return [
            grade_answer(Record(a.run, a.turns, a.end), questions[question_id]).rule
            for a in of(runs[side], question_id, layout)
        ]

    pairs = [(question_id, layout) for question_id in questions for layout in ("staged", "flat")]
    all_right_before = [pair for pair in pairs if set(rules("before", *pair)) == {RIGHT}]
    assert all_right_before == [("dev-01", "staged"), ("dev-01", "flat"), ("dev-03", "staged")]
    assert all(set(rules("after", *pair)) == {RIGHT} for pair in all_right_before)
    # Twelve right and eighteen left to a person, none wrong.
    assert Counter(rule for pair in pairs for rule in rules("after", *pair)) == {
        RIGHT: 12,
        BY_HAND: 18,
    }


def test_each_run_of_dev_03_was_given_the_text_that_held_its_passage_before():
    # Whether the passage of dev-03 was given cannot be worked out here, where its paper
    # is not kept. What can be told: the passage stands in section 3.4 of that paper; the
    # comparison of 2026-11-20, written where the paper could be read, found it given in
    # all six runs; and each run of now was given the text that each of those was given.
    (question,) = [question for question in load_questions(DEV) if question.id == "dev-03"]
    (item,) = question.evidence
    assert (item.arxiv_id, item.section_id) == ("1601.05089v3", "3.4") and item.arxiv_id != OWN
    reads = {"staged": ("read_section", {"arxiv_id": "1601.05089v3", "section_id": "3.4"})}
    reads["flat"] = ("read_paper", {"arxiv_id": "1601.05089v3"})
    runs = sides()
    for layout, read in reads.items():
        given = {
            side: [
                {
                    digest
                    for name, arguments, _, digest in asked(attempt)
                    if (name, arguments) == read
                }
                for attempt in of(runs[side], "dev-03", layout)
            ]
            for side in runs
        }
        (text,) = given["before"][0]
        assert given == {"before": [{text}] * 3, "after": [{text}] * 3}, layout
        row = f"| dev-03 | {layout} | after | 3 / 3 | 3 / 3 |"
        assert row in (RUNS / "regress" / "regress-dev.md").read_text("utf-8")
        assert row in COMPARED.read_text("utf-8")


def test_the_sheet_its_key_and_the_record_of_the_judge_are_those_of_the_runs(tmp_path):
    questions = {question.id: question for question in load_questions(DEV)}
    by_run = {attempt.run["run_id"]: attempt for attempt in sides()["after"].values()}
    key = read_key(KEY)
    assert sorted(key) == list(range(1, 31))
    assert sorted(line["run_id"] for line in key.values()) == sorted(by_run)
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
    assert head["sheet"] == {"file": SHEET.name, "sha256": file_digest(SHEET), "answers": 30}
    assert head["controls"] is None
    # Each of the thirty answers was called right in each of its three requests.
    verdicts = Counter(
        (line["item"], line["verdict"]) for line in lines if line["record"] == "verdict"
    )
    assert verdicts == {(f"sheet-{number}", "right"): 3 for number in key}
    assert end["requests"] == 90 and round(end["cost"], 2) == 0.33


# --- the two ends of dev-02, sent again ---------------------------------------------------


def test_the_two_ends_of_dev_02_were_sent_ten_times_each_from_the_commit_that_says_how_to_read():
    head, requests, end = replay.read_record(SENT_AGAIN)
    assert (head["prompt_version"], head["repeats"]) == ("p3-tool", 10)
    assert head["message_sha256"] == hashlib.sha256(ASK_AGAIN_TEXT.encode("utf-8")).hexdigest()
    assert (head["code"]["commit"][:7], head["code"]["modified"]) == (CHANGE, False)

    # The runs that were sent are the two of the folder that ended without the call.
    ended = {a.run["run_id"]: a for a in sides()["before"].values() if ended_without_the_call(a)}
    assert sorted(str(attempt.cell) for attempt in ended.values()) == [
        "dev-02 flat 2",
        "dev-02 staged 3",
    ]
    assert [run["run_id"] for run in head["runs"]] == sorted(ended)
    for run in head["runs"]:
        attempt = ended[run["run_id"]].run
        for name in (
            "question_id",
            "toolset",
            "toolset_version",
            "model",
            "prompt_version",
            "code",
        ):
            assert run[name] == attempt[name], name
        assert (run["prompt_version"], run["code"]["commit"][:7]) == ("p2-tool", BEFORE_IT)
        assert run["turns"] == len(ended[run["run_id"]].turns) and run["thinking_blocks"] == 0
    assert [run["turns"] for run in head["runs"]] == [2, 4]  # the flat run, the staged run
    # Each of the two ended with a text and no more. The third such run of the records
    # is of the evaluation: it was not sent, and a thinking block stands before its text.
    assert all(attempt.turns[-1]["blocks"] == ["text"] for attempt in ended.values())
    eval_13 = counted(attempts_in(RUNS / "eval"))[Cell("eval-13", "staged", 3)]
    assert ended_without_the_call(eval_13) and eval_13.turns[-1]["blocks"] == ["thinking", "text"]
    assert eval_13.run["run_id"] not in {request["run_id"] for request in requests}

    assert [(r["run_id"], r["repeat"]) for r in requests] == [
        (run["run_id"], repeat) for run in head["runs"] for repeat in range(1, 11)
    ]
    # Made within two minutes, and before the first of the thirty runs was started.
    assert (head["started_at"][:16], end["ended_at"][:16]) == (
        "2026-11-23T03:40",
        "2026-11-23T03:42",
    )
    assert end["ended_at"] < records()[0].run["started_at"]
    # How the count is read stands in the module that CHANGE added, in these words.
    assert "eighteen or more of the twenty" in " ".join(replay.__doc__.split())
    assert '"asked on" counts against the message' in " ".join(replay.__doc__.split())


def test_all_twenty_responses_handed_in_an_answer_by_the_call():
    head, requests, end = replay.read_record(SENT_AGAIN)
    by_run = Counter((r["run_id"], r["outcome"]) for r in requests)
    assert by_run == {(run["run_id"], HANDED_IN): 10 for run in head["runs"]}
    assert end["requests"] == 20 and end["outcomes"] == {HANDED_IN: 20}
    assert end["by_run"] == {run["run_id"]: {HANDED_IN: 10} for run in head["runs"]}
    # The reading that was fixed before the requests: eighteen or more.
    assert sum(r["outcome"] == HANDED_IN for r in requests) == 20 >= ENOUGH
    for request in requests:
        # One block, the call: no text in front of it, no other tool, no thinking block.
        assert (request["stop_reason"], request["blocks"]) == ("tool_use", ["tool_use"])
        assert request["calls"] == ["submit_answer"]
        assert request["response_model"] == "claude-sonnet-5-5"
        assert request["usage"]["output_tokens_details"]["thinking_tokens"] == 0
        assert sorted(request["answer"]) == ["answer", "evidence", "found"]


def test_the_rule_finds_nothing_missing_in_the_twenty_answers_and_leaves_each_to_a_person():
    # Read after the count, which asks for the call and no more. The grades by hand came
    # later still, and the grader had been told this (the test below).
    (question,) = [question for question in load_questions(DEV) if question.id == "dev-02"]
    assert len(question.answer_key["by_hand"]) == 2
    head, requests, _ = replay.read_record(SENT_AGAIN)
    flat, _ = (run["run_id"] for run in head["runs"])
    for request in requests:
        answer = request["answer"]
        graded = grade_answer(Record({}, [], {"reason": "answered", "answer": answer}), question)
        assert (graded.rule, graded.found, graded.wrong_numbers) == (BY_HAND, True, ())
        assert [written for _, written in graded.numbers] == ["2.71", "3.84"]
        assert [there for _, there in graded.phrases] == [True, True]
        assert all(why.startswith("by hand: ") for why in graded.why)
        # The two sections in which the passages stand, and for the staged run the third
        # section that it had read.
        named = sorted(place["section_id"] for place in answer["evidence"])
        assert {place["arxiv_id"] for place in answer["evidence"]} == {OWN}
        assert named == (["4.2", "5"] if request["run_id"] == flat else ["4.2", "4.3", "5"])
    assert sorted(place.section_id for place in question.evidence) == ["4.2", "5"]
    read = [
        arguments["section_id"]
        for name, arguments, _, _ in asked(sides()["before"][Cell("dev-02", "staged", 3)])
        if name == "read_section"
    ]
    assert sorted(read) == ["4.2", "4.3", "5"]
    # Every answer to dev-02 that a run handed in is left to a person as well.
    for side in sides().values():
        rules = {
            grade_answer(Record(a.run, a.turns, a.end), question).rule
            for c, a in side.items()
            if c.question_id == "dev-02" and a.end["answer"]
        }
        assert rules == {BY_HAND}


def test_the_twenty_answers_were_graded_by_hand_afterwards_and_all_twenty_are_right():
    (question,) = [question for question in load_questions(DEV) if question.id == "dev-02"]
    head, requests, _ = replay.read_record(SENT_AGAIN)
    layout = {run["run_id"]: run["toolset"] for run in head["runs"]}
    sent = {(request["run_id"], request["repeat"]): request["answer"] for request in requests}
    assert len(sent) == 20

    # The key names each request once, and the rows are not in the order of the record.
    key = read_key(GRADED_KEY)
    assert sorted(key) == list(range(1, 21))
    assert all(list(line) == list(KEY_COLUMNS) for line in key.values())
    named = [(line["run_id"], int(line["repeat"])) for _, line in sorted(key.items())]
    assert sorted(named) == sorted(sent) and named != sorted(named)
    for line in key.values():
        assert (line["question_id"], line["record"]) == ("dev-02", SENT_AGAIN.name)
        assert line["toolset"] == layout[line["run_id"]]

    # The sheet has the form eval.sheet writes, and each row holds the answer of the
    # request that the key names: nothing of an answer was changed on the way.
    rows = read_csv(GRADED)
    assert all(list(row) == list(SHEET_COLUMNS) for row in rows)
    data = GRADED.read_bytes()
    assert data.startswith(b"\xef\xbb\xbf") and data.endswith(b"\r\n")
    for row, request in zip(rows, named, strict=True):
        assert row["question_id"] == "dev-02" and row["found"] == "true" and sent[request]["found"]
        assert row["answer"] == _cell(sent[request]["answer"])
    first, *others = rows
    assert (first["question"], first["reference_answer"], first["accept_note"]) == (
        question.question,
        question.reference_answer,
        question.accept_note,
    )
    assert all(
        not (row["question"] or row["reference_answer"] or row["accept_note"]) for row in others
    )

    # Every row is graded, and every grade is right.
    grades = read_grades(GRADED, GRADED_KEY)
    assert [grade.number for grade in grades] == list(range(1, 21))
    assert [(grade.run_id, grade.repeat) for grade in grades] == named
    assert Counter(grade.grade for grade in grades) == {"right": 20}
    assert not any(grade.why_wrong for grade in grades)
    assert Counter(grade.toolset for grade in grades) == {"flat": 10, "staged": 10}

    # The grader wrote a note on five rows and on no other: the answers that call the
    # threshold of 3.84 two-sided. The paper does not use the word.
    noted = [grade.number for grade in grades if grade.note]
    assert noted == [int(row["number"]) for row in rows if "two-sided" in row["answer"]]
    assert noted == [6, 8, 10, 11, 12]
    assert all("two-sided" in grade.note for grade in grades if grade.note)
    text = " ".join(section.text for section in own_paper().sections)
    assert "3.84" in text and "two-sided" not in text and "two sided" not in text


# --- the cost -----------------------------------------------------------------------------


def test_the_costs_are_what_the_readme_gives():
    assert cost(records()) == 2.18  # every record of the folder, the two spoilt runs too
    runs = sides()
    assert {name: cost(side.values()) for name, side in runs.items()} == {
        "before": 1.56,
        "after": 2.04,
    }
    _, requests, end = replay.read_record(SENT_AGAIN)
    assert round(end["cost"], 2) == 0.37
    # The first request of each conversation wrote it to the cache, the nine after read it.
    for run_id, size in zip(dict.fromkeys(r["run_id"] for r in requests), (66_230, 11_755)):
        mine = [r["usage"] for r in requests if r["run_id"] == run_id]
        assert [u["cache_creation_input_tokens"] for u in mine] == [size] + [0] * 9
        assert [u["cache_read_input_tokens"] for u in mine] == [0] + [size] * 9


def test_the_runs_cost_more_than_before_because_they_wrote_more_to_the_cache():
    runs = sides()
    # Most of the difference is the flat runs of dev-03.
    dev_03 = {name: of(side, "dev-03", "flat") for name, side in runs.items()}
    assert {name: cost(found) for name, found in dev_03.items()} == {"before": 0.33, "after": 0.7}
    assert {name: written_to_cache(found) for name, found in dev_03.items()} == {
        "before": 114_049,
        "after": 265_431,
    }

    def searched(attempt: Attempt) -> list[str]:
        return [a["query"] for name, a, _, _ in asked(attempt) if name == "search_papers"]

    def first_asked(attempt: Attempt) -> list[tuple]:
        return [
            (call["name"], call["arguments"].get("arxiv_id")) for call in attempt.turns[0]["tools"]
        ]

    with_the_search = [("read_paper", OWN), ("search_papers", None)]
    # After: each asked for the kept paper and a search at once, and no two searches are
    # worded alike, so each wrote both papers of the question to the cache.
    assert [first_asked(a) for a in dev_03["after"]] == [with_the_search] * 3
    assert len({query for a in dev_03["after"] for query in searched(a)}) == 3
    assert [a.end["cache_creation_input_tokens"] for a in dev_03["after"]] == [
        89_909,
        87_760,
        87_762,
    ]
    # Before: the second run worded its search as the first and wrote nothing; the third
    # did not ask for the kept paper.
    first, second, third = dev_03["before"]
    assert first_asked(first) == first_asked(second) == with_the_search
    assert searched(first) == searched(second) and asked(first) == asked(second)
    assert [a.end["cache_creation_input_tokens"] for a in dev_03["before"]] == [89_907, 0, 24_142]
    assert not [
        1 for name, a, _, _ in asked(third) if (name, a.get("arxiv_id")) == ("read_paper", OWN)
    ]
    assert read_from_cache(second) > read_from_cache(first) > read_from_cache(third)

    # The staged runs of dev-04: two read 6.3 in two parts that they cut themselves.
    dev_04 = {name: of(side, "dev-04", "staged") for name, side in runs.items()}
    assert {name: cost(found) for name, found in dev_04.items()} == {"before": 0.07, "after": 0.13}
    assert reads_with_end(dev_04["after"]) == [("6.3", 14000), ("6.3", 13000)]
    assert reads_with_end(dev_04["before"]) == []
    one, two, three = dev_04["before"]
    assert asked(one) == asked(two) == asked(three) and len(asked(one)) == 3
    assert {name: written_to_cache(found) for name, found in dev_04.items()} == {
        "before": 16_837,
        "after": 42_546,
    }
