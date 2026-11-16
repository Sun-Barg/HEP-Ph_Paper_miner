"""The check of a question file: where its evidence stands, and what is said when it does not.

The papers are the two invented ones held in memory, and for the development questions
the paper kept in this repository. No network.
"""

import json
from pathlib import Path

import pytest
from conftest import OWN_PAPER, call, sample_source, tar_gz
from mcp import Client

from hepph_paper_miner.eval import check
from hepph_paper_miner.eval.check import look_at, summary
from hepph_paper_miner.eval.questions import load_questions
from hepph_paper_miner.result_text import read_first_line
from hepph_paper_miner.server import SECTION_CHAR_LIMIT, build_server, piece_ends
from hepph_paper_miner.sources.arxiv_latex import PARSER_VERSION, parse_source
from hepph_paper_miner.sources.base import Paper, PaperMeta
from hepph_paper_miner.sources.fixture import FixtureSource

SAMPLE = "2501.00001v2"  # sections 1, 2 (2.1, 2.u1, 2.2), u1, A (A.1)
LONG = "2502.00002v1"  # section 1 has 52,925 characters and comes in pieces; 1.1 ends it
BUSY = "2503.00003v1"  # cannot be read: the source answers "upstream_busy"
OWN = "2610.26648v1"
DEV = Path(__file__).parent.parent / "eval_data" / "questions_dev.jsonl"


def papers() -> dict[str, Paper]:
    source = sample_source()
    return {key: source.paper_by_id(key) for key in (SAMPLE, LONG)}


def line(name: str, *evidence: tuple[str, str, str | None], **changes) -> dict:
    """A line of a question file whose evidence stands at the given places."""
    items = [
        {"arxiv_id": paper, "section_id": section, **({"anchor": anchor} if anchor else {})}
        for paper, section, anchor in evidence
    ]
    fields = {
        "id": name,
        "question": f"What does {evidence[0][0]} say?",
        "type": "single_section",
        "gold_papers": list(dict.fromkeys(item["arxiv_id"] for item in items)),
        "gold_evidence": {"need": "all", "items": items},
        "expect_found": True,
        "reference_answer": "That.",
        "answer_key": {},
        "accept_note": "That.",
        "abstract_sufficient": False,
    }
    return {**fields, **changes}


def written(tmp_path, *lines: dict) -> Path:
    path = tmp_path / "questions.jsonl"
    path.write_text("\n".join(json.dumps(each) for each in lines) + "\n", encoding="utf-8")
    return path


def looked(tmp_path, *evidence, **changes):
    (question,) = load_questions(written(tmp_path, line("q1", *evidence, **changes)))
    return look_at(question, papers())


# --- where a place stands, and how many calls give it ------------------------------------


def test_a_place_in_a_short_section_is_given_by_the_first_call(tmp_path):
    result = looked(tmp_path, (SAMPLE, "2.1", "Data text."))
    assert result.lines == ("   2501.00001v2 2.1 | chars 0-10 of 10 | given by call 1 of 1",)
    assert (result.problems, result.calls, result.to_find) == ((), 1, ())


def test_a_place_at_the_end_of_a_long_section_needs_every_call(tmp_path):
    text = papers()[LONG].sections[0].text
    assert len(text) == 52925 and text.endswith("Part text.")
    result = looked(tmp_path, (LONG, "1", "Part text."))
    assert result.lines == (
        "   2502.00002v1 1 | chars 52915-52925 of 52925 | given by call 3 of 3",
    )
    assert result.calls == 3
    # The same words in the subsection that holds nothing else: one call.
    assert looked(tmp_path, (LONG, "1.1", "Part text.")).calls == 1


@pytest.mark.anyio
async def test_the_calls_are_counted_at_the_cuts_the_tool_makes():
    # Read the long section as a model would, each call from where the last one stopped.
    text = papers()[LONG].sections[0].text
    stops, start = [], 0
    async with Client(build_server(sample_source())) as client:
        while not stops or stops[-1] < len(text):
            got = await call(client, "read_section", arxiv_id=LONG, section_id="1", start=start)
            start = read_first_line(got)["stop"]
            stops.append(start)
    assert piece_ends(text) == stops and len(stops) == 3
    assert all(stop - before <= SECTION_CHAR_LIMIT for before, stop in zip([0, *stops], stops))
    assert piece_ends("") == [0] and piece_ends("short") == [5]


def test_a_place_that_a_cut_runs_through_is_given_by_the_later_call(tmp_path):
    text = papers()[LONG].sections[0].text
    cut = piece_ends(text)[0]
    across = text[cut - 9 : cut + 9]
    assert text.count(across) == 1
    result = looked(tmp_path, (LONG, "1", across))
    assert result.calls == 2 and f"chars {cut - 9}-{cut + 9} of 52925" in result.lines[0]
    # Just in front of the cut it is the first call, just behind it the second.
    assert looked(tmp_path, (LONG, "1", text[cut - 18 : cut])).calls == 1
    assert looked(tmp_path, (LONG, "1", text[cut : cut + 18])).calls == 2


def test_without_an_anchor_the_whole_section_has_to_be_given(tmp_path):
    result = looked(tmp_path, (LONG, "1", None))
    assert result.lines == (
        "   2502.00002v1 1 | chars 0-52925 of 52925 | given by call 3 of 3 "
        "| no anchor: all of the section has to be given",
    )


def test_an_anchor_that_stands_more_than_once_is_said_to(tmp_path):
    # "text." ends the words of each of the three subsections of section 2.
    result = looked(tmp_path, (SAMPLE, "2", "text."))
    (shown,) = result.lines
    assert shown.endswith("| the anchor stands 3 times (the first is shown)")
    first = papers()[SAMPLE].sections[1].text.find("text.")
    assert f"| chars {first}-{first + 5} of " in shown and result.problems == ()


def test_evidence_that_is_not_there_is_a_problem_and_has_no_place(tmp_path):
    no_section = looked(tmp_path, (SAMPLE, "9", "Data text."))
    assert no_section.lines == () and no_section.calls is None
    assert no_section.problems == ("q1: 2501.00001v2 has no section '9'",)
    no_anchor = looked(tmp_path, (SAMPLE, "2.1", "Data text!"), (SAMPLE, "2.2", "Fit text."))
    assert len(no_anchor.lines) == 1 and no_anchor.calls is None  # the other place is shown
    assert no_anchor.problems == ("q1: section 2.1 of 2501.00001v2 does not contain 'Data text!'",)


@pytest.mark.parametrize(
    ("asked", "to_find"),
    [
        ("What does 2501.00001v2 say?", ()),
        ("What does arXiv:2501.00001 say?", ()),  # without the version: the paper is named
        ("What does the sample paper say about its data?", (SAMPLE,)),
        ("What does 2502.00002v1 say about the sample paper?", (SAMPLE,)),
    ],
)
def test_a_paper_the_question_does_not_name_has_to_be_found(tmp_path, asked, to_find):
    result = looked(tmp_path, (SAMPLE, "2.1", "Data text."), question=asked)
    assert result.to_find == to_find
    assert ("to be found by a search: 2501.00001v2" in check.head_of(result)) is bool(to_find)


# --- the command -------------------------------------------------------------------------


def test_the_command_lists_every_place_and_counts_what_the_file_holds(tmp_path, capsys):
    file = written(
        tmp_path,
        line("q1", (SAMPLE, "2.1", "Data text.")),
        line("q2", (SAMPLE, "2.1", "Data text."), (LONG, "1", "Part text."), type="two_papers"),
        line(
            "q3",
            (SAMPLE, "1", None),
            (SAMPLE, "A", None),
            gold_evidence={
                "need": "any",
                "items": [
                    {"arxiv_id": SAMPLE, "section_id": "1"},
                    {"arxiv_id": SAMPLE, "section_id": "A"},
                ],
            },
            question="Which section holds the tables?",
            expect_found=False,
            abstract_sufficient=True,
            type="not_in_paper",
        ),
    )

    assert check.main([str(file)], source=sample_source()) == 0

    shown = capsys.readouterr().out.splitlines()
    assert shown[0] == "q1 | single_section | an answer is expected"
    assert shown[1] == "   2501.00001v2 2.1 | chars 0-10 of 10 | given by call 1 of 1"
    assert (
        shown[2]
        == "q2 | two_papers | an answer is expected | to be found by a search: 2502.00002v1"
    )
    assert shown[5] == (
        "q3 | not_in_paper | 'not in the papers' is expected "
        "| to be found by a search: 2501.00001v2 | the abstract is enough"
    )
    assert shown[shown.index("") + 1 :] == [
        "3 question(s), about 2 paper(s)",
        "   an answer expected: 2 | 'not in the papers' expected: 1",
        "   evidence in one section: 1 | in several, all needed: 1 | in several, any is enough: 1",
        "   with a paper to be found by a search: 2",
        "   with a place that the first call of read_section does not give: 1",
        "   with an abstract that is enough: 1",
        "   by type: single_section 1, two_papers 1, not_in_paper 1",
        "   by paper: 2501.00001v2 3, 2502.00002v1 1",
        "no problem found",
    ]


def test_the_command_ends_with_a_code_that_says_a_question_has_a_problem(tmp_path, capsys):
    file = written(
        tmp_path,
        line("q1", (SAMPLE, "2.1", "Data text.")),
        line("q2", (SAMPLE, "2.1", "Something else.")),
        line("q3", (BUSY, "1", "Anything.")),
    )

    assert check.main([str(file)], source=sample_source()) == 1

    shown = capsys.readouterr()
    assert "cannot read 2503.00003v1: upstream_busy" in shown.err
    assert "   ! q2: section 2.1 of 2501.00001v2 does not contain 'Something else.'" in shown.out
    assert "   ! q3: 2503.00003v1 is not among the papers given" in shown.out
    assert shown.out.splitlines()[-1] == "2 question(s) with a problem"


def test_the_command_refuses_a_file_it_cannot_use(tmp_path, capsys):
    assert check.main([str(tmp_path / "none.jsonl")], source=sample_source()) == 2
    assert "cannot read the questions" in capsys.readouterr().err
    wrong = written(tmp_path, {**line("q1", (SAMPLE, "2.1", None)), "answer_key": {"number": []}})
    assert check.main([str(wrong)], source=sample_source()) == 2
    assert "line 1: unknown part(s) of answer_key: number" in capsys.readouterr().err
    empty = tmp_path / "empty.jsonl"
    empty.write_text("\n", encoding="utf-8")
    assert check.main([str(empty)], source=sample_source()) == 2
    assert "empty.jsonl: no question in it" in capsys.readouterr().err


def test_no_text_of_a_paper_is_printed(tmp_path, capsys):
    file = written(tmp_path, line("q1", (LONG, "1", "Part text.")), line("q2", (SAMPLE, "2", None)))
    assert check.main([str(file)], source=sample_source()) == 0
    shown = capsys.readouterr().out
    for words in ("Part text.", "Start.", "word17", "Data text.", "Methods overview."):
        assert words not in shown


# --- the development questions, against the paper kept in this repository ----------------


def own_paper() -> Paper:
    data = tar_gz({p.name: p.read_bytes() for p in OWN_PAPER.iterdir() if p.suffix != ".md"})
    meta = PaperMeta(OWN, "The kept paper", ("A",), 2026, "hep-ph", "Abstract.")
    return Paper(meta, parse_source(data), PARSER_VERSION)


def test_the_development_questions_stand_where_their_notes_say(capsys):
    assert check.main([str(DEV)], source=FixtureSource([own_paper()])) == 1  # one paper is not here

    shown = capsys.readouterr()
    assert "cannot read 1601.05089v3: not_found" in shown.err
    out = shown.out.splitlines()
    # The question about a long section: its notes say that the passage begins at 20,269
    # of 25,531 characters, and is not in the first read (0-19,837). That was found by
    # hand. The anchor stands in that passage, 73 characters on.
    at = out.index("dev-04 | long_section | an answer is expected")
    assert out[at + 1] == "   2610.26648v1 6.3 | chars 20342-20354 of 25531 | given by call 2 of 2"
    assert piece_ends(next(s for s in own_paper().sections if s.section_id == "6.3").text) == [
        19837,
        25531,
    ]
    # The question whose paper has to be found names another paper, the one that cites it.
    assert (
        "dev-03 | search_then_read | an answer is expected | to be found by a search: 1601.05089v3"
        in out
    )
    assert "   ! dev-03: 1601.05089v3 is not among the papers given" in out
    assert out[out.index("") + 1 :] == [
        "5 question(s), about 2 paper(s)",
        "   an answer expected: 4 | 'not in the papers' expected: 1",
        "   evidence in one section: 4 | in several, all needed: 1 | in several, any is enough: 0",
        "   with a paper to be found by a search: 1",
        "   with a place that the first call of read_section does not give: 1",
        "   with an abstract that is enough: 0",
        "   by type: single_section 1, two_sections 1, search_then_read 1, long_section 1, "
        "not_in_paper 1",
        "   by paper: 2610.26648v1 4, 1601.05089v3 1",
        "1 question(s) with a problem",
    ]


def test_the_summary_leaves_out_of_the_count_a_question_whose_place_is_missing(tmp_path):
    # Whether a place needs a second call cannot be told when the place is not there.
    file = written(tmp_path, line("q1", (LONG, "1", "Part text!")))
    (question,) = load_questions(file)
    lines = summary([look_at(question, papers())])
    assert "   with a place that the first call of read_section does not give: 0" in lines
