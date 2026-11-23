"""The grader: what it says of a run, and that it notices a run that went wrong.

Records are made the way a run makes them: the real loop, the real tools, papers held
in memory, and a model that replies from a script. A grader that finds nothing wrong
proves nothing, so most tests here hand it a run that is wrong in one known way.
"""

import json
from decimal import Decimal
from pathlib import Path

import pytest
from conftest import OWN_PAPER, ScriptedModel, asks, sample_source, says, tar_gz
from mcp import Client

from hepph_paper_miner.agent.loop import Limits, run
from hepph_paper_miner.agent.trace import Trace
from hepph_paper_miner.eval import grade as grading
from hepph_paper_miner.eval.grade import (
    BY_HAND,
    RIGHT,
    WRONG,
    Record,
    RecordError,
    agrees,
    grade,
    grade_access,
    grade_answer,
    grade_citation,
    grade_search,
    numbers_in,
    read_record,
)
from hepph_paper_miner.eval.questions import Evidence, Question, load_questions
from hepph_paper_miner.result_text import read_first_line
from hepph_paper_miner.server import SECTION_CHAR_LIMIT, build_server, full_text
from hepph_paper_miner.sources.arxiv_latex import PARSER_VERSION, parse_source
from hepph_paper_miner.sources.base import Paper, PaperMeta

SAMPLE = "2501.00001v2"  # sections 1, 2 (2.1, 2.u1, 2.2), u1, A (A.1)
LONG = "2502.00002v1"  # section 1 has 52,925 characters and comes in pieces; 1.1 ends it
ROOT = Path(__file__).parent.parent


def papers() -> dict[str, Paper]:
    source = sample_source()
    return {key: source.paper_by_id(key) for key in (SAMPLE, LONG)}


def question(*evidence: tuple[str, str, str | None], need: str = "all", **changes) -> Question:
    """A question whose answer stands at the given places (paper, section, anchor)."""
    items = tuple(Evidence(*item) for item in evidence) or (Evidence(SAMPLE, "2.1", "Data text."),)
    fields = {
        "id": "q1",
        "question": "What?",
        "type": "single_section",
        "gold_papers": tuple(dict.fromkeys(item.arxiv_id for item in items)),
        "need": need,
        "evidence": items,
        "expect_found": True,
        "reference_answer": "That.",
        "answer_key": {},
        "accept_note": "That.",
        "abstract_sufficient": False,
    }
    return Question(**{**fields, **changes})


def answer(text: str = "That.", found: bool = True, *cited: tuple[str, str]) -> str:
    evidence = [{"arxiv_id": paper, "section_id": section} for paper, section in cited]
    return json.dumps({"answer": text, "found": found, "evidence": evidence})


async def play(
    tmp_path, toolset: str, *replies, max_turns: int = 12, channel: str = "format"
) -> Record:
    """Run the loop on scripted replies and read the record it wrote."""
    name = f"run-{len(list(tmp_path.glob('*.jsonl'))) + 1}"
    labels = {"question_id": "q1", "toolset": toolset, "repeat": 1}
    trace = Trace(name, tmp_path, None, labels=labels)
    async with Client(build_server(sample_source(), toolset)) as client:
        await run(
            "What?",
            client=client,
            model=ScriptedModel(*replies),
            trace=trace,
            limits=Limits(max_turns=max_turns),
            channel=channel,
        )
    return read_record(trace.public_path)


def section(section_id: str, paper: str = SAMPLE, **more) -> tuple[str, dict]:
    return ("read_section", {"arxiv_id": paper, "section_id": section_id, **more})


def whole(paper: str = SAMPLE, **more) -> tuple[str, dict]:
    return ("read_paper", {"arxiv_id": paper, **more})


def ended(reason: str, given: dict | None, turns: int = 1) -> Record:
    """A record with nothing but its end, for what is graded from the answer alone."""
    return Record(
        {"run_id": "r", "question_id": "q1"},
        (),
        {"reason": reason, "answer": given, "turns": turns},
    )


def said(text: str, found: bool = True) -> Record:
    return ended("answered", {"answer": text, "found": found, "evidence": []})


# --- records -----------------------------------------------------------------------------


def test_a_run_that_did_not_finish_is_not_graded(tmp_path):
    dead = tmp_path / "dead.jsonl"
    dead.write_text('{"record": "run", "run_id": "r"}\n{"record": "turn", "turn": 1}\n')
    with pytest.raises(RecordError, match="did not finish"):
        read_record(dead)
    empty = tmp_path / "empty.jsonl"
    empty.write_text("")
    with pytest.raises(RecordError, match="not the record of a run"):
        read_record(empty)


# --- access: was the passage given to the model ------------------------------------------


@pytest.mark.anyio
async def test_reading_the_section_gives_its_passage_and_the_turn_is_kept(tmp_path):
    record = await play(
        tmp_path, "staged", asks(section("1")), asks(section("2.1")), says(answer())
    )
    access, problems = grade_access(record, question(), papers())
    assert (access.met, access.turn, access.delivered_in) == (True, 2, (2,))
    assert access.turns_after == 1  # the answer came with the next response
    assert problems == []


@pytest.mark.anyio
async def test_the_section_around_a_subsection_gives_the_passage_too(tmp_path):
    record = await play(tmp_path, "staged", asks(section("2")), says(answer()))
    assert grade_access(record, question(), papers())[0].met is True


@pytest.mark.anyio
async def test_a_subsection_gives_a_passage_of_its_section_only_when_it_holds_it(tmp_path):
    in_section_2 = question((SAMPLE, "2", "Data text."))
    holds_it = await play(tmp_path, "staged", asks(section("2.1")), says(answer()))
    beside_it = await play(tmp_path, "staged", asks(section("2.2")), says(answer()))
    assert grade_access(holds_it, in_section_2, papers())[0].met is True
    assert grade_access(beside_it, in_section_2, papers())[0].met is False


@pytest.mark.anyio
async def test_another_section_or_another_paper_is_not_the_passage(tmp_path):
    wrong_section = await play(tmp_path, "staged", asks(section("1")), says(answer()))
    wrong_paper = await play(tmp_path, "staged", asks(section("2", LONG)), says(answer()))
    never_read = await play(tmp_path, "staged", says(answer()))
    for record in (wrong_section, wrong_paper, never_read):
        access, _ = grade_access(record, question(), papers())
        assert (access.met, access.turn, access.turns_after) == (False, None, None)


@pytest.mark.anyio
async def test_a_passage_beyond_the_first_piece_is_given_only_by_the_piece_that_holds_it(tmp_path):
    late = question((LONG, "1", "word2500 word2501"))  # about 21,400 characters in
    first_piece = await play(tmp_path, "staged", asks(section("1", LONG)), says(answer()))
    both = await play(
        tmp_path,
        "staged",
        asks(section("1", LONG)),
        asks(section("1", LONG, start=19000)),
        says(answer()),
    )
    assert grade_access(first_piece, late, papers())[0].met is False
    assert grade_access(both, late, papers())[0].turn == 2


@pytest.mark.anyio
async def test_a_passage_the_cut_falls_into_is_given_once_both_pieces_are(tmp_path):
    text = papers()[LONG].sections[0].text
    async with Client(build_server(sample_source(), "staged")) as client:
        first = await client.call_tool("read_section", {"arxiv_id": LONG, "section_id": "1"})
    cut = read_first_line(first.content[0].text)["stop"]
    assert 0 < cut < SECTION_CHAR_LIMIT
    across = question((LONG, "1", text[cut - 9 : cut + 9]))

    record = await play(
        tmp_path,
        "staged",
        asks(section("1", LONG)),
        asks(section("2")),
        asks(section("1", LONG, start=cut)),
        says(answer()),
    )
    access, _ = grade_access(record, across, papers())
    assert access.delivered_in == (3,)  # not in turn 1: half of it was still missing


@pytest.mark.anyio
async def test_the_whole_paper_gives_every_passage_and_a_late_piece_of_it_does_not(tmp_path):
    at = full_text(papers()[SAMPLE]).index("Data text.")
    everything = await play(tmp_path, "flat", asks(whole()), says(answer()))
    too_late = await play(tmp_path, "flat", asks(whole(start=at + 1)), says(answer()))
    just_in_time = await play(tmp_path, "flat", asks(whole(start=at)), says(answer()))
    assert grade_access(everything, question(), papers())[0].turn == 1
    assert grade_access(too_late, question(), papers())[0].met is False
    assert grade_access(just_in_time, question(), papers())[0].met is True
    # A section without an anchor is given when all of it is, its marker line included.
    whole_section = question((SAMPLE, "2.1", None))
    assert grade_access(everything, whole_section, papers())[0].met is True
    assert grade_access(just_in_time, whole_section, papers())[0].met is False


@pytest.mark.anyio
async def test_all_of_the_evidence_or_any_of_it_as_the_question_says(tmp_path):
    two = ((SAMPLE, "2.1", "Data text."), (SAMPLE, "A.1", "More text."))
    record = await play(tmp_path, "staged", asks(section("2.1")), says(answer()))
    needs_all, _ = grade_access(record, question(*two, need="all"), papers())
    needs_any, _ = grade_access(record, question(*two, need="any"), papers())
    assert (needs_all.met, needs_all.delivered_in) == (False, (1, None))
    assert (needs_any.met, needs_any.turn) == (True, 1)


@pytest.mark.anyio
async def test_without_the_paper_access_is_unknown_and_the_grade_says_why(tmp_path):
    record = await play(tmp_path, "staged", asks(section("2.1")), says(answer()))
    access, problems = grade_access(record, question(), {})
    assert access.met is None
    assert problems == [f"{SAMPLE} was not given: access cannot be told"]


@pytest.mark.anyio
async def test_evidence_that_is_not_in_the_paper_is_a_problem_and_not_a_miss(tmp_path):
    record = await play(tmp_path, "staged", asks(section("2.1")), says(answer()))
    access, problems = grade_access(record, question((SAMPLE, "2.1", "no such words")), papers())
    assert access.met is False
    assert len(problems) == 1 and "is not in the paper as it is split now" in problems[0]


# --- citation: does the answer name the right sections -----------------------------------


@pytest.mark.anyio
async def test_the_cited_section_is_compared_strictly_and_loosely(tmp_path):
    exact = await play(
        tmp_path, "staged", asks(section("2.1")), says(answer("x", True, (SAMPLE, "2.1")))
    )
    around = await play(
        tmp_path, "staged", asks(section("2")), says(answer("x", True, (SAMPLE, "2")))
    )
    beside = await play(
        tmp_path, "staged", asks(section("2.2")), says(answer("x", True, (SAMPLE, "2.2")))
    )
    nothing = await play(tmp_path, "staged", asks(section("2.1")), says(answer("x", True)))

    def told(record):
        cited = grade_citation(record, question())
        return cited.strict, cited.loose, cited.extra

    assert told(exact) == (True, True, 0)
    assert told(around) == (False, True, 0)  # the section that holds 2.1
    assert told(beside) == (False, False, 1)
    assert told(nothing) == (False, False, 0)  # the right passage was read, and not cited


@pytest.mark.anyio
async def test_an_identifier_in_another_form_is_the_same_paper_and_is_counted(tmp_path):
    record = await play(
        tmp_path,
        "staged",
        asks(section("2.1")),
        says(answer("x", True, (f"arXiv:{SAMPLE}", "2.1"))),
    )
    cited = grade_citation(record, question())
    assert (cited.strict, cited.not_as_shown) == (True, 1)
    assert cited.cited == ((f"arXiv:{SAMPLE}", "2.1"),)  # kept as the answer wrote it


@pytest.mark.anyio
@pytest.mark.parametrize("written", ["2501.00001v1", "2501.00001", "the sample paper"])
async def test_another_version_no_version_or_no_identifier_is_not_the_paper(tmp_path, written):
    record = await play(
        tmp_path, "staged", asks(section("2.1")), says(answer("x", True, (written, "2.1")))
    )
    cited = grade_citation(record, question())
    assert (cited.strict, cited.loose, cited.extra) == (False, False, 1)


@pytest.mark.anyio
async def test_more_citations_than_the_evidence_are_counted_and_so_are_unopened_ones(tmp_path):
    staged = await play(
        tmp_path,
        "staged",
        asks(section("2.1")),
        says(answer("x", True, (SAMPLE, "2.1"), (SAMPLE, "1"), (SAMPLE, "2"), (LONG, "2"))),
    )
    cited = grade_citation(staged, question())
    # "2" holds 2.1, so it is no extra one. "1" and the other paper are, and neither was opened.
    assert (cited.strict, cited.extra, cited.unread) == (True, 2, 2)

    flat = await play(
        tmp_path,
        "flat",
        asks(whole()),
        says(answer("x", True, (SAMPLE, "2.1"), (SAMPLE, "1"), (LONG, "2"))),
    )
    cited = grade_citation(flat, question())
    assert (cited.extra, cited.unread) == (2, 1)  # the whole paper was asked for, the other was not


@pytest.mark.anyio
async def test_a_run_without_an_answer_has_no_citation(tmp_path):
    record = await play(tmp_path, "staged", asks(section("2.1")), asks(section("2.1")), max_turns=2)
    assert record.end["reason"] == "turn_limit"
    assert grade_citation(record, question()) is None


# --- search ------------------------------------------------------------------------------


@pytest.mark.anyio
async def test_the_first_search_that_lists_the_paper_gives_its_turn_and_rank(tmp_path):
    record = await play(
        tmp_path,
        "staged",
        asks(("search_papers", {"query": "nothing matches this"})),
        asks(("search_papers", {"query": "paper"})),  # lists the sample paper, then the long one
        asks(("search_papers", {"query": "long"})),
        says(answer()),
    )
    about_long = question((LONG, "2", "Small text."))
    found = grade_search(record, about_long)
    assert (found.searches, found.empty) == (3, 1)
    assert found.first_hit == {LONG: (2, 2, True)}
    # A paper no search listed: the model may have had its identifier from the question.
    other = question(gold_papers=("2503.00009v1",), evidence=(Evidence("2503.00009v1", "1"),))
    assert grade_search(record, other).first_hit == {"2503.00009v1": None}


# --- answer: what a rule can check -------------------------------------------------------


@pytest.mark.parametrize(
    ("written", "value", "least", "same"),
    [
        ("0.7910", 0.791, None, True),  # more digits, the same number
        ("0.791", 0.791, None, True),
        ("0.79", 0.791, 2, True),  # rounded, as far as allowed
        ("0.79", 0.791, None, False),  # not allowed unless the key says so
        ("0.8", 0.791, 2, False),  # one digit is fewer than two
        ("0.78", 0.791, 2, False),
        ("63", 62.6, 2, True),
        ("62", 62.6, 2, False),  # 62.6 does not round to 62
        ("62.7", 62.6, None, False),
        ("0.24", 0.2, None, False),  # more digits, another number
        ("0.20", 0.2, None, True),
        ("2.26×10⁻²⁶", 2.26e-26, None, True),
        ("2.26 × 10^{-26}", 2.26e-26, None, True),
        ("2.26e-26", 2.26e-26, None, True),
        ("2.3×10^-26", 2.26e-26, 2, True),
        ("2.2×10^-26", 2.26e-26, 2, False),
        ("2.26×10⁻²⁵", 2.26e-26, None, False),  # the power is part of the number
        ("49", 49, None, True),
        ("49.0", 49, None, True),
        ("−3", -3, None, True),
        ("3", -3, None, False),
        ("19,837", 19837, None, True),
    ],
)
def test_a_number_is_the_key_when_it_is_equal_or_rounded_as_far_as_allowed(
    written, value, least, same
):
    (number,) = numbers_in(written)
    assert agrees(number, value, least) is same


def test_numbers_are_read_as_an_answer_writes_them():
    def read(text):
        return [(n.text, n.value, n.digits) for n in numbers_in(text)]

    assert read("Br(h2→bb̄) = 0.7910, about 62.6% of h2h2 decays, 0.7910² ≈ 0.626.") == [
        ("0.7910", Decimal("0.7910"), 4),
        ("62.6", Decimal("62.6"), 3),
        ("0.7910", Decimal("0.7910"), 4),  # the power on it is left alone
        ("0.626", Decimal("0.626"), 3),
    ]
    # A range is two numbers, and neither is negative. A minus sign in front of a number is one.
    assert [n.value for n in numbers_in("r = 0.2–0.4, r = 0.2-0.4, s in [−3, 3], 1–12 kpc")] == [
        Decimal(x) for x in ("0.2", "0.4", "0.2", "0.4", "-3", "3", "1", "12")
    ]
    # Digits inside a name are no number.
    assert [n.text for n in numbers_in("m_h2 and FL16Y and log10 s, but 17.7-year")] == ["17.7"]
    assert read("10^-26 and 10⁻²⁶") == [
        ("10^-26", Decimal("1E-26"), 1),
        ("10⁻²⁶", Decimal("1E-26"), 1),
    ]


KEY = {
    "numbers": [
        {"label": "mass", "value": 69.2, "unit": "GeV"},
        {"label": "share", "value": 62.6, "min_sig_figs": 2},
    ],
    "phrases": [{"label": "J-factor", "any_of": ["J-factor", "J factor"]}],
    "wrong_numbers": [{"label": "another channel", "value": 49.82}],
}


def test_an_answer_with_everything_of_the_key_is_right_by_the_rule():
    graded = grade_answer(
        said("The mass is 69.2 GeV, about 63% of decays, with the j factor rescaled."),
        question(answer_key=KEY),
    )
    assert (graded.rule, graded.why) == (RIGHT, ())
    assert graded.numbers == (("mass", "69.2"), ("share", "63"))
    assert graded.phrases == (("J-factor", True),)


@pytest.mark.parametrize(
    ("text", "found", "why"),
    [
        ("About 63%, with the J-factor rescaled.", True, "number missing: mass"),
        ("The mass is 69.2 GeV, about 63%.", True, "phrase missing: J-factor"),
        (
            "The mass is 69 GeV, about 63%, J-factor.",
            True,
            "number missing: mass",
        ),  # too few digits
        (
            "The mass is 69.2 GeV, 63%, J-factor, but I am not sure.",
            False,
            "found is False, expected True",
        ),
    ],
)
def test_an_answer_that_lacks_something_of_the_key_is_wrong(text, found, why):
    graded = grade_answer(said(text, found), question(answer_key=KEY))
    assert graded.rule == WRONG and why in graded.why


def test_found_the_wrong_way_round_is_wrong_in_both_directions():
    absent = question(
        expect_found=False, answer_key={"by_hand": ["says that the paper reports none"]}
    )
    made_up = grade_answer(said("It is 5.2σ.", found=True), absent)
    assert (made_up.rule, made_up.why) == (WRONG, ("found is True, expected False",))
    gave_up = grade_answer(said("The paper does not say.", found=False), question(answer_key=KEY))
    assert gave_up.rule == WRONG and "found is False, expected True" in gave_up.why


def test_a_listed_wrong_number_sends_the_answer_to_a_person_and_does_not_fail_it():
    text = "The mass is 69.2 GeV (not 49.82 GeV, which is another channel), 62.6%, J-factor."
    graded = grade_answer(said(text), question(answer_key=KEY))
    assert graded.rule == BY_HAND
    assert graded.wrong_numbers == (("another channel", "49.82"),)
    assert graded.why == ("a listed wrong number occurs: another channel (49.82)",)


def test_what_the_question_leaves_to_a_person_makes_the_rule_say_so():
    key = {
        "numbers": [{"label": "low end", "value": 0.2}],
        "by_hand": ["the statement is about the limits"],
    }
    graded = grade_answer(said("For r = 0.2–0.4."), question(answer_key=key))
    assert (graded.rule, graded.why) == (BY_HAND, ("by hand: the statement is about the limits",))
    assert graded.by_hand == ("the statement is about the limits",)


@pytest.mark.parametrize("reason", ["turn_limit", "no_answer", "api_error"])
def test_no_answer_is_a_wrong_answer_and_the_reason_is_kept(reason):
    graded = grade_answer(ended(reason, None), question(answer_key=KEY))
    assert (graded.rule, graded.why, graded.found) == (WRONG, (f"no answer ({reason})",), None)


# --- one run, and the command ------------------------------------------------------------


@pytest.mark.anyio
async def test_one_run_is_graded_in_all_four_ways(tmp_path):
    record = await play(
        tmp_path,
        "staged",
        asks(("search_papers", {"query": "sample"})),
        asks(section("2.1")),
        says(answer("Ten.", True, (SAMPLE, "2.1"))),
    )
    asked = question(answer_key={"phrases": [{"label": "ten", "any_of": ["ten"]}]})
    result = grade(record, asked, papers())
    assert (result.question_id, result.toolset, result.repeat) == ("q1", "staged", 1)
    assert (result.reason, result.turns, result.problems) == ("answered", 3, ())
    assert result.search.first_hit == {SAMPLE: (1, 1, True)}
    assert (result.access.turn, result.citation.strict, result.answer.rule) == (2, True, RIGHT)
    assert json.loads(json.dumps(result.as_dict()))["access"]["turn"] == 2  # it can be written down

    with pytest.raises(ValueError, match="not of 'q2'"):
        grade(record, question(id="q2"), papers())


@pytest.mark.anyio
async def test_papers_split_by_another_parser_make_the_grade_say_so(tmp_path):
    record = await play(
        tmp_path, "staged", asks(("get_outline", {"arxiv_id": SAMPLE})), says(answer())
    )
    old = {SAMPLE: Paper(papers()[SAMPLE].meta, papers()[SAMPLE].sections, "1")}
    (problem,) = grade(record, question(), old).problems
    assert f"split by parser ['{PARSER_VERSION}'], and is graded against parser ['1']" in problem


LINE = {
    "id": "q1",
    "question": "What?",
    "type": "single_section",
    "gold_papers": [SAMPLE],
    "gold_evidence": {
        "need": "all",
        "items": [{"arxiv_id": SAMPLE, "section_id": "2.1", "anchor": "Data text."}],
    },
    "expect_found": True,
    "reference_answer": "That.",
    "answer_key": {},
    "accept_note": "That.",
    "abstract_sufficient": False,
}


@pytest.mark.anyio
async def test_the_command_grades_every_finished_record_and_writes_the_grades(tmp_path, capsys):
    runs = tmp_path / "runs"
    await play(runs, "staged", asks(section("2.1")), says(answer("x", True, (SAMPLE, "2.1"))))
    await play(runs, "flat", asks(whole(LONG)), asks(whole(LONG)), max_turns=2)
    (runs / "run-9.jsonl").write_text('{"record": "run", "run_id": "run-9"}\n')  # a run that died
    questions = tmp_path / "questions.jsonl"
    questions.write_text(json.dumps(LINE) + "\n", encoding="utf-8")
    out = tmp_path / "grades.jsonl"

    code = grading.main(
        [str(runs / "*.jsonl"), "--questions", str(questions), "--out", str(out)],
        source=sample_source(),
    )

    assert code == 0
    shown = capsys.readouterr()
    assert (
        "run-1 | answered | 2 turns | search 0 (0 empty) | access turn 1 (+1) | cited strict "
        "| answer right" in shown.out
    )
    assert (
        "run-2 | turn_limit | 2 turns | search 0 (0 empty) | access no | cited - | answer wrong"
        in shown.out
    )
    assert "skipped: run-9.jsonl: the run did not finish" in shown.err
    written = [json.loads(line) for line in out.read_text(encoding="utf-8").splitlines()]
    assert [(item["run_id"], item["answer"]["rule"]) for item in written] == [
        ("run-1", "right"),
        ("run-2", "wrong"),
    ]


def test_the_command_says_when_it_has_nothing_to_grade(tmp_path, capsys):
    assert grading.main([str(tmp_path / "*.jsonl")], source=sample_source()) == 2
    assert "no record matches" in capsys.readouterr().err


@pytest.mark.anyio
async def test_a_run_is_graded_the_same_whichever_way_its_answer_came_in(tmp_path):
    # The record of a run keeps its answer in one place and in one form, so the grader
    # need not know the way. The call that handed in an answer returned no text of a
    # paper, and is no reading of one.
    given = json.loads(answer("That.", True, (SAMPLE, "2.1")))
    by_tool = await play(
        tmp_path,
        "staged",
        asks(section("2")),
        asks(("submit_answer", given)),
        channel="tool",
    )
    as_text = await play(
        tmp_path, "staged", asks(section("2")), says(json.dumps(given)), channel="text"
    )
    held = await play(tmp_path, "staged", asks(section("2")), says(json.dumps(given)))

    grades = [grade(record, question(), papers()) for record in (by_tool, as_text, held)]

    for result in grades:
        assert (result.reason, result.turns) == ("answered", 2)
        assert (result.access.met, result.access.turn, result.access.turns_after) == (True, 1, 1)
        assert (result.citation.strict, result.citation.extra, result.citation.unread) == (
            True,
            0,
            0,
        )
        assert result.answer.rule == RIGHT and result.problems == ()
    # A run that was to call the tool and ended its turn with text is asked for the call.
    # When it hands in then, it is graded like the others, with the response it took.
    asked = await play(
        tmp_path,
        "staged",
        asks(section("2")),
        says(json.dumps(given)),
        asks(("submit_answer", given)),
        channel="tool",
    )
    result = grade(asked, question(), papers())
    assert (result.reason, result.turns, result.answer.rule) == ("answered", 3, RIGHT)
    assert (result.access.met, result.access.turn, result.access.turns_after) == (True, 1, 2)
    assert asked.end["asked_again"] == 2
    # When it ends its turn with text again, it has no answer, and is wrong.
    without = await play(
        tmp_path,
        "staged",
        asks(section("2")),
        says(json.dumps(given)),
        says("As above."),
        channel="tool",
    )
    result = grade(without, question(), papers())
    assert (result.reason, result.citation, result.answer.rule) == ("no_answer", None, WRONG)
    assert result.answer.why == ("no answer (no_answer)",)


# --- the records of the development runs, kept in this repository ------------------------

DEV_RUNS = ROOT / "results" / "runs" / "dev"
OWN = "2610.26648v1"


def own_paper() -> dict[str, Paper]:
    data = tar_gz({p.name: p.read_bytes() for p in OWN_PAPER.iterdir() if p.suffix != ".md"})
    meta = PaperMeta(OWN, "The kept paper", ("A",), 2026, "hep-ph", "Abstract.")
    return {OWN: Paper(meta, parse_source(data), PARSER_VERSION)}


def graded(folder: str) -> list:
    questions = {
        item.id: item for item in load_questions(ROOT / "eval_data" / "questions_dev.jsonl")
    }
    records = [read_record(path) for path in sorted((DEV_RUNS / folder).glob("*.jsonl"))]
    return [grade(record, questions[record.run["question_id"]], own_paper()) for record in records]


def test_the_twelve_diagnosis_runs_were_all_given_their_passage_early():
    results = graded("diag-1")
    assert len(results) == 12
    # The staged runs had it in turn 3 (a long section read in two pieces, or the third
    # section they opened), the flat ones in turn 1. Seven went on to the turn limit.
    assert {(r.toolset, r.access.turn) for r in results} == {("staged", 3), ("flat", 1)}
    assert sorted(r.reason for r in results) == ["answered"] * 5 + ["turn_limit"] * 7
    assert all(r.access.turns_after >= 9 for r in results if r.reason == "turn_limit")
    assert all(r.problems == () for r in results)
    # No answer is a wrong answer. The five answers hold what the key lists, and each
    # leaves something to a person.
    assert sorted(r.answer.rule for r in results) == [BY_HAND] * 5 + [WRONG] * 7
    answered = [r for r in results if r.citation is not None]
    assert all(r.citation.strict for r in answered)
    # One run was asked with "arXiv:" in front of the identifier, and cited it that way.
    assert [r.citation.not_as_shown for r in answered].count(1) == 1


def test_the_first_runs_gave_the_answer_of_the_key():
    staged, flat = sorted(graded("first-run"), key=lambda r: r.toolset, reverse=True)
    assert (staged.access.turn, flat.access.turn) == (2, 1)
    for result in (staged, flat):
        assert (result.answer.rule, result.citation.strict, result.citation.extra) == (
            RIGHT,
            True,
            0,
        )
        assert [label for label, match in result.answer.numbers if match] == [
            "Br(h2->bb)",
            "Br(h2->cc)",
            "Br(h2->tautau)",
            "4b share of h2h2 decays",
        ]


def test_a_question_about_a_paper_that_is_not_at_hand_is_graded_as_far_as_it_goes():
    results = [r for r in graded("pilot-1") if r.question_id == "dev-03"]
    assert len(results) == 2
    for result in results:
        assert result.access.met is None  # the paper is not kept here
        assert result.problems == ("1601.05089v3 was not given: access cannot be told",)
        assert result.search.first_hit["1601.05089v3"] is not None  # a search did list it
    (answered,) = [r for r in results if r.reason == "answered"]
    assert answered.answer.rule == RIGHT  # four numbers, and none of the listed wrong ones
    assert (answered.citation.strict, answered.citation.loose, answered.citation.extra) == (
        True,
        True,
        1,
    )
