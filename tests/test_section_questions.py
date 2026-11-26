"""The six questions about papers that the two parsers split differently. No network.

A question names the section its passage stands in, and parser 5 gives the sections of
these papers other identifiers than parser 4 did. So there are two files: one for the
runs of the code that has parser 4, one for the runs of the code that has parser 5. The
runs of the two are held beside each other (results/runs/more-sections/README.md), and
that means something only when both were asked the same questions and are graded
against the same passages. These tests hold that, and hold what the plan says of the
files and of the papers against what this repository keeps.

The sources of the six papers are not kept here, so no test can say that a passage
stands where a file says. `eval.check` says that, run by the code of each parser, on a
computer that has the papers.

The questions were asked on 2026-11-25, and what came back stands in the same file as
the plan, below it (tests/test_more_sections_results.py). The last test here holds the
plan to the commit that brought it, and with the plan the two question files, which it
names by their digests.
"""

import copy
import hashlib
import json
import re
from pathlib import Path

from hepph_paper_miner.agent.origin import file_digest
from hepph_paper_miner.eval.check import to_find
from hepph_paper_miner.eval.questions import load_questions

ROOT = Path(__file__).parent.parent
FILES = {
    "4": ROOT / "eval_data" / "questions_sections_parser4.jsonl",
    "5": ROOT / "eval_data" / "questions_sections_parser5.jsonl",
}
PLAN = ROOT / "results" / "runs" / "more-sections" / "README.md"
# The plan as the commit before the runs brought it (44bca1f): the whole file then.
PLAN_SHA256 = "036c0f609c508a4c02bb2107f1fdafd668f9af514213eb4204ae41996a776726"

# The paper of each question, and the characters parser 4 returned of it.
PAPERS = {
    "sec-01": ("2610.39042v1", 31251),
    "sec-02": ("2608.11124v1", 27811),
    "sec-03": ("2609.20949v1", 26452),
    "sec-04": ("2608.26881v1", 35197),
    "sec-05": ("2610.05980v1", 32708),
    "sec-06": ("2610.37318v1", 21542),
}
# Parser 4 did not return the letter of this paper, so its passage has no place there.
LEFT_OUT = "sec-01"


def _lines(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def _without_sections(line: dict) -> dict:
    bare = copy.deepcopy(line)
    for item in bare["gold_evidence"]["items"]:
        del item["section_id"]
    return bare


def _sections(line: dict) -> list[str]:
    return [item["section_id"] for item in line["gold_evidence"]["items"]]


def test_both_files_are_question_files_with_the_six_questions():
    for path in FILES.values():
        assert [question.id for question in load_questions(path)] == list(PAPERS)


def test_the_two_files_differ_in_the_identifiers_of_the_sections_and_in_nothing_else():
    before, after = _lines(FILES["4"]), _lines(FILES["5"])
    # Compared as the lines stand in the files, notes and all: a field that only one
    # file had would be read by the judge of one side and not of the other.
    assert [_without_sections(line) for line in before] == [
        _without_sections(line) for line in after
    ]
    differing = [
        b["id"] for b, a in zip(before, after, strict=True) if _sections(b) != _sections(a)
    ]
    assert differing == [name for name in PAPERS if name != LEFT_OUT]


def test_every_passage_of_a_question_stands_in_one_section_under_each_parser():
    for parser, path in FILES.items():
        for line in _lines(path):
            assert len(set(_sections(line))) == 1, (parser, line["id"])


def test_parser_4_has_one_section_for_each_of_the_five_letters_and_parser_5_one_made_at_a_title():
    before = {line["id"]: _sections(line)[0] for line in _lines(FILES["4"])}
    after = {line["id"]: _sections(line)[0] for line in _lines(FILES["5"])}
    for name in PAPERS:
        if name == LEFT_OUT:
            # The text in front of the first heading, under both: the letter is there
            # under parser 5, and under parser 4 the file names the place it should have.
            assert (before[name], after[name]) == ("0", "0")
        else:
            assert before[name] == "1"
            assert re.fullmatch(r"u[1-9]\d*", after[name])  # a section without a number


def test_every_question_names_its_one_paper_and_expects_an_answer_the_abstract_does_not_give():
    for path in FILES.values():
        for question in load_questions(path):
            assert question.gold_papers == (PAPERS[question.id][0],)
            assert to_find(question) == ()  # no search has to find the paper
            assert all(item.arxiv_id == question.gold_papers[0] for item in question.evidence)
            assert all(item.anchor for item in question.evidence)
            assert question.need == "all"
            assert question.expect_found is True
            assert question.abstract_sufficient is False


def test_the_papers_are_of_the_survey_and_parser_4_split_them_as_the_plan_says():
    outcomes = {
        line["id"]: line
        for line in _lines(ROOT / "results" / "survey" / "outcomes.jsonl")
        if line["record"] == "paper"
    }
    plan = PLAN.read_text(encoding="utf-8")
    for name, (paper, chars) in PAPERS.items():
        line = outcomes[paper]
        assert (line["outcome"], line["chars"]) == ("ok", chars)
        row = next(row for row in plan.splitlines() if row.startswith(f"| {name} |"))
        assert f"`{paper}`" in row and f"{chars:,} characters" in row
        if name == LEFT_OUT:
            assert (line["sections"], line["no_headings"]) == (10, False)
            assert "ten sections" in row
        else:
            assert (line["sections"], line["largest"], line["no_headings"]) == (1, chars, True)
            assert "one section" in row
    archives = sorted(outcomes[paper]["archive"] for paper, _ in PAPERS.values())
    assert archives == ["hep-ex"] * 5 + ["hep-th"]
    assert "Five are in hep-ex and one in hep-th." in plan


def test_the_plan_names_each_file_by_its_digest_where_it_describes_it_and_in_its_command():
    plan = PLAN.read_text(encoding="utf-8")
    for path in FILES.values():
        digest = file_digest(path)
        assert f"`eval_data/{path.name}` (SHA-256\n`{digest}`)" in plan
        assert f"--questions eval_data/{path.name} --questions-sha256 {digest} " in plan


def test_the_plan_stands_above_what_came_back_as_the_commit_before_the_runs_brought_it():
    # The plan was pushed before any run with parser 5. What came back was written into
    # the same file afterwards, under a heading of its own, and the plan was left as it
    # was: the file still begins with the bytes it had then. So a sentence of the plan
    # that is changed once the runs are known fails here, and so does a question file
    # that is changed, because the plan names both by their digests (the test above).
    plan, heading, came_back = PLAN.read_bytes().partition(b"\n# What came back\n")
    assert heading and came_back.strip()
    assert hashlib.sha256(plan).hexdigest() == PLAN_SHA256
    text = plan.decode("utf-8")
    assert "No run has been\nmade with it." in text
    assert "under a heading of its own, with this text left as it is." in text
    # The README of the repository says which commit that was, and where both texts are.
    readme = " ".join((ROOT / "README.md").read_text(encoding="utf-8").split())
    assert (
        "was written down before any of it (`44bca1f`), in "
        "`results/runs/more-sections/README.md`" in readme
    )
    assert "the same file goes through what came back, below the plan" in readme
