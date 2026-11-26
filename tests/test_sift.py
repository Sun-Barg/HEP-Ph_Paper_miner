"""The two filters: what each reads, how its answer is graded, which drafts are kept.

No network and no LLM: the commands are given models that answer from a script.
"""

import hashlib
import json
import re

import pytest
from drafting_paper import (
    ID,
    TITLE,
    Scripted,
    as_reply,
    draft,
    later_draft,
    paper,
    placed,
    places_file,
    reply_of,
    source,
)

from hepph_paper_miner.agent.prompt import ANSWER_SCHEMA
from hepph_paper_miner.agent.prompt import SYSTEM_PROMPT as RUN_PROMPT
from hepph_paper_miner.drafting import ask, sift
from hepph_paper_miner.drafting import draft as drafting
from hepph_paper_miner.drafting.draft import Draft
from hepph_paper_miner.drafting.places import LATER_PIECE, NAMED_FIRST, OWN_TEXT, SEARCH_FIRST
from hepph_paper_miner.drafting.sift import (
    PASSAGE,
    PASSAGE_MESSAGE,
    PASSAGE_SCHEMA,
    PASSAGE_SYSTEM,
    SIFT_VERSION,
    SIFTING,
    WITHOUT,
    WITHOUT_MESSAGE,
    WITHOUT_SCHEMA,
    WITHOUT_SYSTEM,
    graded,
    kept,
    piece_of,
    question_of,
    read_answer,
    texts_digest,
)
from hepph_paper_miner.eval.judge import JUDGE
from hepph_paper_miner.server import _section

# The name of the texts the filters read, and the digest of those texts.
PINNED = ("s1", "cfd6f7744121d71e70e98037f453643aecd94194779983662e624089b4b6a2c3")


# --- the texts ------------------------------------------------------------------------------


def test_the_texts_are_the_ones_this_version_names():
    # The filters read these texts, so a change to them is another filter. When this fails:
    # raise SIFT_VERSION (drafting/sift.py), then put the new name and digest here.
    texts = [
        WITHOUT_SYSTEM,
        WITHOUT_MESSAGE,
        WITHOUT_SCHEMA,
        PASSAGE_SYSTEM,
        PASSAGE_MESSAGE,
        PASSAGE_SCHEMA,
    ]
    digest = hashlib.sha256(json.dumps(texts).encode("utf-8")).hexdigest()
    assert (SIFT_VERSION, digest) == PINNED, digest
    assert texts_digest() == digest


def test_the_filters_ask_as_the_judge_does():
    assert SIFTING == JUDGE


def test_the_passage_filter_reads_the_lines_of_the_runs_prompt():
    # Said of a piece of a paper in place of the tools, and nothing else changed.
    run = RUN_PROMPT.splitlines()
    assert (
        "- Keep the answer short: the facts asked for, with numbers and units as the paper gives them."
        in run
    )
    assert PASSAGE_SYSTEM.splitlines()[-1] == run[-1]
    assert "Do not guess a value." in PASSAGE_SYSTEM and "Do not guess a value." in RUN_PROMPT
    # The form of its answer is two fields of the runs' answer, described as there.
    for name in ("answer", "found"):
        assert PASSAGE_SCHEMA["properties"][name] == ANSWER_SCHEMA["properties"][name]
    assert WITHOUT_SCHEMA["properties"] == {"answer": ANSWER_SCHEMA["properties"]["answer"]}


def test_the_texts_name_no_paper():
    for text in (WITHOUT_SYSTEM, WITHOUT_MESSAGE, PASSAGE_SYSTEM, PASSAGE_MESSAGE):
        assert not re.search(r"\d{4}\.\d{4,5}", text)


# --- the piece a filter is given ------------------------------------------------------------


class OnePaper:
    def paper(self, arxiv_id):
        return paper()


def test_the_piece_of_a_place_is_what_read_section_returns_of_it():
    first = placed("2.1")
    assert piece_of(paper(), first) == _section(OnePaper(), ID, "2.1", 0, None)
    later = placed("2.2", LATER_PIECE)
    piece = piece_of(paper(), later)
    assert piece == _section(OnePaper(), ID, "2.2", later.start, None)
    assert "0.0318" in piece and piece.startswith(f"section | {ID} | 2.2 |")


def test_the_own_text_of_a_section_is_read_with_its_end():
    own = placed("2", OWN_TEXT)
    piece = piece_of(paper(), own)
    assert piece == _section(OnePaper(), ID, "2", 0, own.end)
    assert piece.endswith(f"as asked with end={own.end}.]")
    assert "37.2" not in piece  # the subsections are not part of it


# --- grading an answer ----------------------------------------------------------------------


def question(found=None, kind=None):
    place = placed("2.1", kind)
    return question_of(
        Draft.from_dict(found or draft()),
        place,
        paper(),
        "The detector has an area of 37.2 square metres",
    )


def test_the_question_names_its_paper_as_a_run_would_be_asked():
    assert question().question.startswith(f"In arXiv:{ID}, ")
    assert question(kind=SEARCH_FIRST).question.startswith(f'In the paper titled "{TITLE}", ')


@pytest.mark.parametrize(
    ("answer", "found", "rule"),
    [
        ("It is 37.2 square metres.", True, "right"),
        ("About 37 square metres.", True, "wrong"),  # three digits are needed
        ("It is 37.2 square metres.", False, "wrong"),
        ("The text does not say.", False, "wrong"),
    ],
)
def test_an_answer_is_graded_by_the_rule(answer, found, rule):
    assert graded(question(), {"answer": answer, "found": found, "evidence": []})[0] == rule


def test_an_answer_without_the_paper_is_graded_as_one_that_says_found():
    reply = reply_of({"answer": "Perhaps 37.2 square metres."})
    answer, problem = read_answer(reply, with_found=False)
    assert problem is None and answer["found"] is True
    assert graded(question(), answer)[0] == "right"


@pytest.mark.parametrize(
    ("data", "with_found", "stop", "problem"),
    [
        ({"answer": "x"}, True, "end_turn", "the reply does not have the fields of an answer"),
        (
            {"answer": "x", "found": True},
            False,
            "end_turn",
            "the reply does not have the fields of an answer",
        ),
        ({"answer": " ", "found": True}, True, "end_turn", "the answer is not a text, or is empty"),
        ({"answer": "x", "found": "yes"}, True, "end_turn", "found is neither true nor false"),
        ({"answer": "x", "found": True}, True, "max_tokens", "the reply stopped with max_tokens"),
    ],
)
def test_a_reply_that_is_no_answer_is_not_read_as_one(data, with_found, stop, problem):
    assert read_answer(reply_of(data, stop=stop), with_found) == (None, problem)


def test_a_draft_is_kept_only_when_it_passes_everything():
    lines = [
        {"record": "checked", "number": 1, "passed": True},
        {"record": "checked", "number": 2, "passed": True},
        {"record": "checked", "number": 3, "passed": True},
        {"record": "checked", "number": 4, "passed": False},
        {"record": "checked", "number": 5, "passed": True},
    ]
    said = {
        (1, WITHOUT): "wrong",
        (1, PASSAGE): "right",
        (2, WITHOUT): "right",  # it can be guessed
        (2, PASSAGE): "right",
        (3, WITHOUT): "wrong",
        (3, PASSAGE): "wrong",  # the passage does not answer it
        (5, WITHOUT): None,  # no answer without the paper: nothing was guessed
        (5, PASSAGE): "right",
    }
    lines += [
        {"record": "reply", "id": f"{n}:{kind}", "number": n, "filter": kind, "rule": rule}
        for (n, kind), rule in said.items()
    ]
    assert kept(lines) == [1, 5]


# --- the command ----------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def committed_code(monkeypatch):
    monkeypatch.setattr(ask, "code_version", lambda: {"commit": "c0ffee", "modified": False})


def generator(system, message, schema):
    part = re.search(r"<part>\nSection: (\S+) \| [^\n]*\nCharacters (\d+)", message)
    if part[1] == "2.1":
        return reply_of(as_reply(draft()))
    if part[1] == "2.2":
        return reply_of(as_reply(later_draft()))
    # The own text of 2, with the anchor of 2.1: it fails its checks.
    return reply_of(as_reply(draft()))


def filters(system, message, schema):
    if system == sift.WITHOUT_SYSTEM:
        # The coupling can be guessed; the area cannot.
        guess = "0.0318" if "coupling" in message else "About 40 square metres."
        return reply_of({"answer": guess})
    return reply_of({"answer": "37.2 square metres; 0.0318.", "found": True})


@pytest.fixture
def records(tmp_path):
    places = places_file(tmp_path, ("2.1", NAMED_FIRST), ("2.2", LATER_PIECE), ("2", OWN_TEXT))
    drafts = tmp_path / "drafts.jsonl"
    argv = ["--places", str(places), "--out", str(drafts)]
    assert drafting.main(argv, asker=Scripted(generator), source=source()) == 0
    return places, drafts, tmp_path / "sift.jsonl"


def test_the_command_checks_then_asks_the_drafts_that_pass(records, capsys):
    places, drafts, out = records
    model = Scripted(filters)
    argv = ["--places", str(places), "--drafts", str(drafts), "--out", str(out)]
    assert sift.main(argv, asker=model, source=source()) == 0
    lines = [json.loads(line) for line in out.read_text(encoding="utf-8").splitlines()]
    head, *middle, end = lines
    assert head["record"] == "sift" and head["sift_version"] == SIFT_VERSION
    assert head["drafts"]["sha256"] == hashlib.sha256(drafts.read_bytes()).hexdigest()
    checks = [line for line in middle if line["record"] == "checked"]
    # The checks stand right after the first line, before any reply.
    assert [line["record"] for line in middle[:3]] == ["checked"] * 3
    assert [(line["number"], line["passed"]) for line in checks] == [
        (1, True),
        (2, True),
        (3, False),
    ]
    assert "anchor_once" in checks[2]["failed"]
    # Two requests for each draft that passed, none for the one that did not.
    assert len(model.asked) == 4
    asked = {line["id"]: line for line in middle if line["record"] == "reply"}
    assert asked["1:without"]["rule"] == "wrong" and asked["1:passage"]["rule"] == "right"
    assert asked["2:without"]["rule"] == "right"
    assert kept(lines) == [1]
    assert (
        end["kept"] == 1 and end["passed_checks"] == 2 and end["failed_checks"]["anchor_once"] == 1
    )
    said = capsys.readouterr().out
    assert (
        "3 draft(s): 2 passed the checks, 1 right without the paper, 2 right from the passage, 1 kept"
        in said
    )


def test_the_passage_filter_is_given_the_piece_and_the_question_alone(records):
    places, drafts, out = records
    model = Scripted(filters)
    argv = ["--places", str(places), "--drafts", str(drafts), "--out", str(out)]
    assert sift.main(argv, asker=model, source=source()) == 0
    without = [message for system, message, _ in model.asked if system == sift.WITHOUT_SYSTEM]
    passage = [message for system, message, _ in model.asked if system == sift.PASSAGE_SYSTEM]
    question = f"In arXiv:{ID}, what is the total area of the detector?"
    assert without[0] == WITHOUT_MESSAGE.format(question=question)
    assert passage[0] == PASSAGE_MESSAGE.format(
        piece=piece_of(paper(), placed("2.1")), question=question
    )


def test_a_record_of_other_places_is_refused(records, tmp_path, capsys):
    places, drafts, out = records
    other = places_file(tmp_path / "other", ("2.1", NAMED_FIRST))
    argv = ["--places", str(other), "--drafts", str(drafts), "--out", str(out)]
    assert sift.main(argv, asker=Scripted(filters), source=source()) == 2
    assert "is not a record of" in capsys.readouterr().err


def test_an_unfinished_record_of_drafts_is_refused(records, capsys):
    places, drafts, out = records
    lines = drafts.read_text(encoding="utf-8").splitlines()
    drafts.write_text("\n".join(lines[:-1]) + "\n", encoding="utf-8")
    argv = ["--places", str(places), "--drafts", str(drafts), "--out", str(out)]
    assert sift.main(argv, asker=Scripted(filters), source=source()) == 2
    assert "has not finished" in capsys.readouterr().err


def test_started_again_it_asks_only_what_is_left(records):
    places, drafts, out = records
    argv = ["--places", str(places), "--drafts", str(drafts), "--out", str(out)]
    calls = []

    def flaky(system, message, schema):
        calls.append(1)
        if len(calls) == 3:
            from hepph_paper_miner.agent.model import ModelError

            return ModelError("APIConnectionError", "lost", None)
        return filters(system, message, schema)

    assert sift.main(argv, asker=Scripted(flaky), source=source()) == 1
    again = Scripted(filters)
    assert sift.main(argv, asker=again, source=source()) == 0
    assert len(again.asked) == 1
    lines = [json.loads(line) for line in out.read_text(encoding="utf-8").splitlines()]
    # The checks were written once, when the record was begun.
    assert [line["record"] for line in lines].count("checked") == 3
    assert kept(lines) == [1]
