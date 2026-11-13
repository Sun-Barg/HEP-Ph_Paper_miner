"""The question files: they load, and their evidence is where they say it is."""

import json
from pathlib import Path

import pytest
from conftest import OWN_PAPER, tar_gz

from hepph_paper_miner.eval.questions import (
    QuestionFileError,
    load_questions,
    problems_with_evidence,
)
from hepph_paper_miner.sources.arxiv_latex import PARSER_VERSION, parse_source
from hepph_paper_miner.sources.base import Paper, PaperMeta, parse_arxiv_id

DEV = Path(__file__).parent.parent / "eval_data" / "questions_dev.jsonl"
OWN_ID = "2610.26648v1"

ID = "2501.00001v2"
PLACE = {"arxiv_id": ID, "section_id": "2.1"}
LINE = {
    "id": "q1",
    "question": "What?",
    "type": "single_section",
    "gold_papers": ["2501.00001v2"],
    "gold_evidence": {"need": "all", "items": [{"arxiv_id": "2501.00001v2", "section_id": "2.1"}]},
    "expect_found": True,
    "reference_answer": "That.",
    "answer_key": {},
    "accept_note": "That, or close to it.",
    "abstract_sufficient": False,
}


def own_paper() -> Paper:
    data = tar_gz({p.name: p.read_bytes() for p in OWN_PAPER.iterdir() if p.suffix != ".md"})
    meta = PaperMeta(OWN_ID, "The kept paper", ("A",), 2026, "hep-ph", "Abstract.")
    return Paper(meta, parse_source(data), PARSER_VERSION)


def write(tmp_path, *lines: dict | str) -> Path:
    path = tmp_path / "questions.jsonl"
    text = "\n".join(line if isinstance(line, str) else json.dumps(line) for line in lines)
    path.write_text(text + "\n", encoding="utf-8")
    return path


def test_the_development_questions_load():
    questions = load_questions(DEV)
    assert [question.id for question in questions] == [f"dev-0{n}" for n in range(1, 6)]
    assert [question.type for question in questions] == [
        "single_section",
        "two_sections",
        "search_then_read",
        "long_section",
        "not_in_paper",
    ]
    # One question has "the paper does not say" as its right answer.
    assert [question.expect_found for question in questions] == [True, True, True, True, False]
    # None can be answered from an abstract: both layouts have to read.
    assert not any(question.abstract_sufficient for question in questions)
    for question in questions:
        assert question.question and question.reference_answer and question.accept_note


def test_the_evidence_in_the_kept_paper_is_where_the_questions_say():
    # If this fails after a change to the parser, section identifiers or texts have
    # moved: the questions have to be looked at again, not this test.
    papers = {OWN_ID: own_paper()}
    checked = 0
    for question in load_questions(DEV):
        if question.gold_papers != (OWN_ID,):
            continue
        assert problems_with_evidence(question, papers) == []
        assert all(item.anchor for item in question.evidence)
        checked += 1
    assert checked == 4  # the fifth names another paper: see the test below


@pytest.mark.network
def test_the_evidence_in_other_papers_is_where_the_questions_say(tmp_path):
    from hepph_paper_miner.http import Fetcher, default_cache_dir
    from hepph_paper_miner.sources.arxiv import ArxivSource

    source = ArxivSource(Fetcher(default_cache_dir(), user_agent="hepph-paper-miner/tests"))
    for question in load_questions(DEV):
        others = [arxiv_id for arxiv_id in question.gold_papers if arxiv_id != OWN_ID]
        if not others:
            continue
        papers = {arxiv_id: source.paper(parse_arxiv_id(arxiv_id)) for arxiv_id in others}
        assert problems_with_evidence(question, papers) == []


def test_what_is_wrong_with_evidence_is_said_in_words():
    paper = own_paper()
    question = load_questions(DEV)[3]  # the one in section 6.3
    assert problems_with_evidence(question, {}) == [
        f"dev-04: {OWN_ID} is not among the papers given"
    ]

    moved = Paper(paper.meta, tuple(s for s in paper.sections if s.section_id != "6.3"), "3")
    assert problems_with_evidence(question, {OWN_ID: moved}) == [
        f"dev-04: {OWN_ID} has no section '6.3'"
    ]

    emptied = Paper(
        paper.meta,
        tuple(
            s if s.section_id != "6.3" else type(s)("6.3", s.title, 2, "Other text.")
            for s in paper.sections
        ),
        "3",
    )
    assert problems_with_evidence(question, {OWN_ID: emptied}) == [
        f"dev-04: section 6.3 of {OWN_ID} does not contain 'r=0.2$--$0.4'"
    ]


def test_a_good_line_loads_and_blank_lines_are_skipped(tmp_path):
    (question,) = load_questions(write(tmp_path, "", LINE, ""))
    assert (question.id, question.need, question.notes) == ("q1", "all", {})
    assert question.evidence[0].anchor is None


@pytest.mark.parametrize(
    ("change", "message"),
    [
        (
            {"reference_answer": None, "_drop": "reference_answer"},
            "line 1: missing reference_answer",
        ),
        ({"difficulty": "hard"}, r"line 1: unknown field\(s\) difficulty"),
        ({"gold_papers": ["2501.00001"]}, "'2501.00001' has no version"),
        ({"gold_papers": ["the first paper"]}, "'the first paper' is not an arXiv identifier"),
        ({"gold_evidence": {"need": "most", "items": [{}]}}, "gold_evidence needs 'need'"),
        ({"gold_evidence": {"need": "all", "items": []}}, "gold_evidence needs 'need'"),
        (
            {"gold_evidence": {"need": "all", "items": [{"arxiv_id": "2501.00001v2"}]}},
            "needs arxiv_id and section_id",
        ),
        (
            {
                "gold_evidence": {
                    "need": "any",
                    "items": [{"arxiv_id": "2502.00002v1", "section_id": "1"}],
                }
            },
            "which gold_papers does not list",
        ),
        ({"expect_found": "yes"}, "expect_found has to be true or false"),
        # A value of the wrong form. Each of these used to load, or to end in an error
        # that named no line.
        ({"id": 7}, "line 1: id has to be text, and not empty"),
        ({"id": "a/b"}, "the id 'a/b' has to be made of letters, digits"),
        ({"id": "dev_01"}, "the id 'dev_01' has to be made of letters, digits"),
        ({"question": "  "}, "question has to be text, and not empty"),
        ({"reference_answer": ""}, "reference_answer has to be text, and not empty"),
        ({"abstract_sufficient": 0}, "abstract_sufficient has to be true or false"),
        ({"answer_key": "0.79"}, "answer_key has to be an object"),
        ({"notes": ["checked by hand"]}, "notes has to be an object with text values"),
        ({"notes": {"checked": True}}, "notes has to be an object with text values"),
        ({"gold_papers": 5}, "gold_papers has to be a list of arXiv identifiers"),
        ({"gold_papers": [2501.00001]}, "gold_papers has to be a list of arXiv identifiers"),
        (
            {"gold_evidence": {"need": "all", "items": {"arxiv_id": ID}}},
            "gold_evidence needs 'need'",
        ),
        (
            {"gold_evidence": {"need": "all", "items": [{**PLACE}], "min": 1}},
            r"unknown field\(s\) in gold_evidence: min",
        ),
        # A misspelt "anchor" loaded without one, and its check was never made.
        (
            {"gold_evidence": {"need": "all", "items": [{**PLACE, "anchr": "0.7910"}]}},
            r"unknown field\(s\) in an evidence item: anchr",
        ),
        (
            {"gold_evidence": {"need": "all", "items": [{**PLACE, "anchor": ""}]}},
            "anchor of an evidence item has to be text, and not empty",
        ),
        (
            {"gold_evidence": {"need": "all", "items": [{**PLACE, "anchor": None}]}},
            "anchor of an evidence item has to be text, and not empty",
        ),
        (
            {"gold_evidence": {"need": "all", "items": [{**PLACE, "section_id": 2.1}]}},
            "section_id of an evidence item has to be text, and not empty",
        ),
        (
            {"gold_evidence": {"need": "all", "items": [{**PLACE, "arxiv_id": 2501}]}},
            "arxiv_id of an evidence item has to be text, and not empty",
        ),
    ],
)
def test_a_wrong_line_stops_the_whole_file(tmp_path, change, message):
    line = {**LINE, **change}
    line.pop(line.pop("_drop", ""), None)
    with pytest.raises(QuestionFileError, match=message):
        load_questions(write(tmp_path, line))


def test_an_anchor_and_notes_of_the_right_form_load(tmp_path):
    place = {**PLACE, "anchor": " 0.7910 "}  # kept as it stands, spaces included
    line = {**LINE, "gold_evidence": {"need": "any", "items": [place]}, "notes": {"a": "b"}}
    (question,) = load_questions(write(tmp_path, line))
    assert question.evidence[0].anchor == " 0.7910 "
    assert (question.need, question.notes) == ("any", {"a": "b"})


def test_a_file_that_is_not_utf8_is_refused_like_any_other_wrong_file(tmp_path):
    path = tmp_path / "questions.jsonl"
    path.write_bytes(json.dumps(LINE).encode("utf-8") + "\n# 질문".encode("cp949"))
    with pytest.raises(QuestionFileError, match="questions.jsonl: not UTF-8 text"):
        load_questions(path)


def test_lines_that_are_not_objects_and_repeated_ids_are_refused(tmp_path):
    with pytest.raises(QuestionFileError, match="line 2: not JSON"):
        load_questions(write(tmp_path, LINE, "{not json"))
    with pytest.raises(QuestionFileError, match="line 1: not a JSON object"):
        load_questions(write(tmp_path, "[1, 2]"))
    with pytest.raises(QuestionFileError, match="line 2: the id 'q1' is used twice"):
        load_questions(write(tmp_path, LINE, LINE))
