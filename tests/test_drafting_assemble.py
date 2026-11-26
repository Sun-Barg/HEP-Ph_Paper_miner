"""The questions made of the accepted drafts, and the summary of every candidate
(drafting/assemble.py). No network, no model: the model is scripted and the papers are
the invented paper of drafting_paper.py under other identifiers and titles."""

import csv
import json
import re
from dataclasses import replace

import pytest
from drafting_paper import (
    META,
    SEED,
    Scripted,
    as_reply,
    draft,
    later_draft,
    nothing,
    paper,
    reply_of,
)

from hepph_paper_miner.drafting import ask, assemble, review, sift
from hepph_paper_miner.drafting import draft as drafting
from hepph_paper_miner.drafting.assemble import choose
from hepph_paper_miner.drafting.assign import Placed
from hepph_paper_miner.drafting.places import (
    APPENDIX,
    LATER_PIECE,
    NAMED_FIRST,
    OWN_TEXT,
    SEARCH_FIRST,
    places_of,
)
from hepph_paper_miner.drafting.review import SHEET_COLUMNS
from hepph_paper_miner.eval.questions import load_questions
from hepph_paper_miner.sources.arxiv_latex import PARSER_VERSION
from hepph_paper_miner.sources.base import Paper
from hepph_paper_miner.sources.fixture import FixtureSource
from hepph_paper_miner.survey.records import write_lines

# --- which accepted drafts become questions -----------------------------------------------


def at(number, archive, kind, paper_id=None):
    return Placed(number, archive, number, paper_id or f"2609.{number:05d}v1", kind, "1", 0, 1)


def picked(chosen):
    return [(each.place.number, each.kind, each.fill) for each in chosen]


def test_every_kind_and_archive_takes_its_first_accepted_drafts_in_order():
    accepted = [
        at(1, "hep-ph", LATER_PIECE),
        at(2, "hep-th", LATER_PIECE),
        at(3, "hep-ph", LATER_PIECE),
        at(4, "hep-ph", LATER_PIECE),
        at(5, "hep-ph", APPENDIX),
    ]
    found = choose(accepted, 2)
    # hep-ph has three later pieces and takes the first two; the order is that of the file.
    assert picked(found) == [
        (1, LATER_PIECE, False),
        (2, LATER_PIECE, False),
        (3, LATER_PIECE, False),
        (5, APPENDIX, False),
    ]


def test_what_a_kind_is_short_of_goes_to_the_next_named_first_of_its_archive():
    accepted = [
        at(1, "hep-ph", NAMED_FIRST),
        at(2, "hep-ph", APPENDIX),
        at(3, "hep-th", NAMED_FIRST),
        at(4, "hep-ph", NAMED_FIRST),
        at(5, "hep-th", LATER_PIECE),
        at(6, "hep-th", APPENDIX),
        at(7, "hep-th", OWN_TEXT),
        at(8, "hep-th", SEARCH_FIRST),
        at(9, "hep-ph", NAMED_FIRST),
        at(10, "hep-th", NAMED_FIRST),
    ]
    found = choose(accepted, 1)
    # hep-ph is short of later_piece, own_text and search_first, one each: its named_first
    # drafts after its own one fill two of the three, in their order. hep-th is short of
    # nothing, and its named_first draft that is left over goes to no other archive.
    assert picked(found) == [
        (1, NAMED_FIRST, False),
        (2, APPENDIX, False),
        (3, NAMED_FIRST, False),
        (4, NAMED_FIRST, True),
        (5, LATER_PIECE, False),
        (6, APPENDIX, False),
        (7, OWN_TEXT, False),
        (8, SEARCH_FIRST, False),
        (9, NAMED_FIRST, True),
    ]


def test_places_are_filled_as_far_as_there_are_drafts_and_named_first_is_filled_by_none():
    accepted = [at(1, "hep-ex", APPENDIX), at(2, "hep-ex", APPENDIX), at(3, "hep-ex", OWN_TEXT)]
    # named_first is short of four, and the other kinds of eleven: nothing fills them.
    assert picked(choose(accepted, 4)) == [
        (1, APPENDIX, False),
        (2, APPENDIX, False),
        (3, OWN_TEXT, False),
    ]
    assert choose([], 4) == []


def test_a_place_of_search_first_is_of_its_own_kind_and_fills_no_other():
    accepted = [at(1, "hep-ph", SEARCH_FIRST), at(2, "hep-ph", SEARCH_FIRST)]
    # Three kinds are short of one place each, and a second search_first draft is no
    # named_first draft: it takes none of them.
    assert picked(choose(accepted, 1)) == [(1, SEARCH_FIRST, False)]


def test_in_the_rehearsal_a_draft_of_another_kind_is_no_search_first():
    accepted = [at(1, "", LATER_PIECE), at(2, "", LATER_PIECE), at(3, "", OWN_TEXT)]
    # The second later piece finds its kind full; it does not become a question of the
    # paper named by its title, whatever the search would say.
    assert picked(choose(accepted, 1, lambda paper_id: True)) == [
        (1, LATER_PIECE, False),
        (3, OWN_TEXT, False),
    ]


def test_in_the_rehearsal_search_first_takes_findable_named_first_drafts_first():
    accepted = [
        at(1, "", NAMED_FIRST, "2609.00001v1"),
        at(2, "", NAMED_FIRST, "2609.00002v1"),
        at(3, "", LATER_PIECE, "2609.00002v1"),
        at(4, "", NAMED_FIRST, "2609.00003v1"),
        at(5, "", NAMED_FIRST, "2609.00004v1"),
        at(6, "", NAMED_FIRST, "2609.00005v1"),
    ]
    asked = []

    def findable(paper_id):
        asked.append(paper_id)
        return paper_id != "2609.00001v1"

    found = choose(accepted, 2, findable)
    # Search first: the first two findable ones (2 and 4); then named_first: 1 and 5. Of
    # the four kinds besides named_first, later_piece is one short and the rest two each:
    # 6 fills one of the seven places, and nothing is left for the others.
    assert picked(found) == [
        (1, NAMED_FIRST, False),
        (2, SEARCH_FIRST, False),
        (3, LATER_PIECE, False),
        (4, SEARCH_FIRST, False),
        (5, NAMED_FIRST, False),
        (6, NAMED_FIRST, True),
    ]
    # Asked of one paper after another until the kind was full, and of no paper after.
    assert asked == ["2609.00001v1", "2609.00002v1", "2609.00003v1"]


# --- the command --------------------------------------------------------------------------

TITLES = {
    "2609.10001v1": "Widgets at low energy",
    "2609.10002v1": "Gadgets on a lattice",
    "2609.10003v2": "Gizmos in a strong field",
    "2609.10004v1": "Sprockets of the early universe",
    "2609.10005v1": "Cogs and their decays",
    "2609.10006v1": "Levers near a horizon",
    "2609.10007v1": "Pulleys in two dimensions",
    "2609.10008v1": "Wheels on a torus",
    "2609.10009v1": "Axles out of balance",
}


def papers(titles=TITLES):
    return [paper(replace(META, arxiv_id=name, title=title)) for name, title in titles.items()]


def where(section, kind):
    wanted = NAMED_FIRST if kind == SEARCH_FIRST else kind
    (one,) = [p for p in places_of(paper()) if p.section == section and p.kind == wanted][:1]
    return one


# The places of the evaluation: two archives, papers in the order of the walk.
SAMPLE = [
    ("hep-ph", 41, "2609.10001v1", LATER_PIECE, "2.2"),
    ("hep-th", 41, "2609.10002v1", NAMED_FIRST, "2.1"),
    ("hep-ph", 42, "2609.10003v2", SEARCH_FIRST, "2.1"),
    ("hep-th", 42, "2609.10004v1", APPENDIX, "A"),
    ("hep-ph", 43, "2609.10005v1", OWN_TEXT, "2"),
    ("hep-th", 43, "2609.10006v1", NAMED_FIRST, "2.1"),
    ("hep-ph", 44, "2609.10007v1", NAMED_FIRST, "2.1"),
]


def places_of_file(folder, rows, **head):
    lines = [
        {
            "record": "places",
            "input": "sample",
            "seed": SEED,
            "per_kind": 6,
            "parser_version": PARSER_VERSION,
            **head,
        }
    ]
    for number, (archive, rank, paper_id, kind, section) in enumerate(rows, start=1):
        one = where(section, kind)
        lines.append(
            Placed(number, archive, rank, paper_id, kind, section, one.start, one.end).as_line()
        )
    path = folder / "places.jsonl"
    write_lines(path, lines)
    return path


APPENDIX_DRAFT = {
    "anchor": "The cutoff of the final fit is set to 6.6 TeV",
    "question": "In {paper}, to what value is the cutoff of the final fit set?",
    "reference_answer": "6.6 TeV.",
    "numbers": [{"label": "cutoff", "value": 6.6, "unit": "TeV", "min_sig_figs": 2}],
    "phrases": [],
    "accept_note": "The value 6.6 TeV has to be there.",
}
OWN_DRAFT = {
    "anchor": "The scan of the model uses 4096 points on a regular grid",
    "question": "How many points does the scan of the model in {paper} use?",
    "reference_answer": "4096 points.",
    "numbers": [{"label": "points", "value": 4096, "unit": "", "min_sig_figs": 4}],
    "phrases": [],
    "accept_note": "The number 4096 has to be there.",
}


def generator(system, message, schema):
    title = re.search(r"^Title: (.*)$", message, re.MULTILINE)[1]
    section = re.search(r"<part>\nSection: (\S+) ", message)[1]
    if title == "Pulleys in two dimensions":
        return reply_of(nothing())
    if title == "Wheels on a torus":
        return reply_of(as_reply(draft()), stop="max_tokens")
    if title == "Axles out of balance":
        # An anchor that the paper does not write.
        wrong = draft(anchor="The detector has an area of 99.9 square metres")
        return reply_of(as_reply(wrong))
    if section == "2.2":
        return reply_of(as_reply(later_draft()))
    if section == "A":
        return reply_of(as_reply(APPENDIX_DRAFT))
    if section == "2":
        return reply_of(as_reply(OWN_DRAFT))
    return reply_of(as_reply(draft()))


def filters(system, message, schema):
    if system == sift.WITHOUT_SYSTEM:
        return reply_of({"answer": "I would say 40."})
    return reply_of({"answer": "37.2 square metres; 0.0318; 6.6 TeV; 4096.", "found": True})


@pytest.fixture(autouse=True)
def committed_code(monkeypatch):
    monkeypatch.setattr(ask, "code_version", lambda: {"commit": "c0ffee", "modified": False})


def committed():
    return {"commit": "c0ffee", "modified": False}


def made_of(folder, places, source, verdicts):
    """The drafts, the sift and the review of a file of places; `verdicts` by paper."""
    drafts, sifted = folder / "drafts.jsonl", folder / "sift.jsonl"
    argv = ["--places", str(places), "--out", str(drafts)]
    assert drafting.main(argv, asker=Scripted(generator), source=source) == 0
    argv = ["--places", str(places), "--drafts", str(drafts), "--out", str(sifted)]
    assert sift.main(argv, asker=Scripted(filters), source=source) == 0
    sheet, key, judged = folder / "sheet.csv", folder / "key.jsonl", folder / "review.jsonl"
    argv = ["--places", str(places), "--drafts", str(drafts), "--sift", str(sifted)]
    assert review.main([*argv, "--sheet", str(sheet), "--key", str(key)], source=source) == 0
    keyed = {
        line["row"]: line["paper"]
        for line in map(json.loads, key.read_text(encoding="utf-8").splitlines())
        if line["record"] == "row"
    }
    with sheet.open(encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.DictReader(stream))
    for row in rows:
        verdict, why = verdicts.get(keyed[int(row["number"])], ("accept", ""))
        row.update(verdict=verdict, why_rejected=why, note="")
    with sheet.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, SHEET_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)
    argv = ["--read", "--sheet", str(sheet), "--key", str(key), "--out", str(judged)]
    assert review.main(argv) == 0
    return {"places": places, "drafts": drafts, "sift": sifted, "review": judged}


def argv_of(files, **more):
    argv = []
    for name in ("places", "drafts", "sift", "review"):
        argv += [f"--{name}", str(files[name])]
    for name, value in more.items():
        argv += [f"--{name}", str(value)] if value is not True else [f"--{name}"]
    return argv


@pytest.fixture
def evaluation(tmp_path):
    source = FixtureSource(papers())
    places = places_of_file(tmp_path, SAMPLE)
    files = made_of(tmp_path, places, source, {"2609.10006v1": ("reject", "ambiguous")})
    return {**files, "folder": tmp_path, "source": source}


def read_jsonl(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def test_the_accepted_drafts_become_the_questions_in_the_order_of_the_walk(evaluation, capsys):
    out, summary = evaluation["folder"] / "questions.jsonl", evaluation["folder"] / "sum.jsonl"
    argv = argv_of(evaluation, questions=out, summary=summary)
    assert assemble.main(argv, source=evaluation["source"], origin=committed) == 0
    questions = load_questions(out)
    # Five accepted drafts: the rejected one (place 6) and the part with nothing to ask
    # (place 7) make no question. They keep the order of the places.
    assert [q.id for q in questions] == [f"archives-0{n}" for n in range(1, 6)]
    assert [q.notes["candidate"] for q in questions] == ["1", "2", "3", "4", "5"]
    assert [q.type for q in questions] == [
        LATER_PIECE,
        NAMED_FIRST,
        SEARCH_FIRST,
        APPENDIX,
        OWN_TEXT,
    ]
    assert [q.notes["archive"] for q in questions] == ["hep-ph", "hep-th"] * 2 + ["hep-ph"]
    named, searched = questions[1], questions[2]
    assert named.question == "In arXiv:2609.10002v1, what is the total area of the detector?"
    assert searched.question == (
        'In the paper titled "Gizmos in a strong field", what is the total area of the detector?'
    )
    assert searched.gold_papers == ("2609.10003v2",)
    item = questions[0].evidence[0]
    assert (item.arxiv_id, item.section_id) == ("2609.10001v1", "2.2")
    assert item.anchor == "the coupling is fixed to 0.0318 at the reference scale"
    assert questions[0].notes["drafted"] == drafting.DRAFTER_VERSION
    assert all(q.expect_found and not q.answer_key.get("by_hand") for q in questions)
    said = capsys.readouterr().out
    assert "5 question(s) written to" in said and "cost of the requests, computed: $" in said


def test_the_summary_holds_every_candidate_and_no_text_of_a_paper(evaluation):
    out, summary = evaluation["folder"] / "questions.jsonl", evaluation["folder"] / "sum.jsonl"
    argv = argv_of(evaluation, questions=out, summary=summary)
    assert assemble.main(argv, source=evaluation["source"], origin=committed) == 0
    head, *lines = read_jsonl(summary)
    assert head["record"] == "candidates" and head["per_cell"] == 4
    assert head["code"] == committed()
    assert head["drafts"]["drafter_version"] == drafting.DRAFTER_VERSION
    assert head["sift"]["sift_version"] == sift.SIFT_VERSION
    questions = head["questions"]
    assert questions["questions"] == 5 and questions["file"] == "questions.jsonl"
    assert len(questions["sha256"]) == 64 and set(questions) == {"file", "sha256", "questions"}
    candidates = [line for line in lines if line["record"] == "candidate"]
    assert [line["number"] for line in candidates] == list(range(1, 8))
    first = candidates[0]
    assert (first["draft"], first["failed_checks"], first["kept"]) == ("draft", [], True)
    assert (first["without_the_paper"], first["from_the_passage"]) == ("wrong", "right")
    assert (first["verdict"], first["question"], first["asked_as"]) == (
        "accept",
        "archives-01",
        LATER_PIECE,
    )
    assert first["usage"] == {"input_tokens": 3000, "output_tokens": 600}
    assert first["cost"] == pytest.approx((3000 * 2 + 600 * 10) / 1_000_000)
    rejected, empty = candidates[5], candidates[6]
    assert (rejected["verdict"], rejected["why_rejected"], rejected["question"]) == (
        "reject",
        "ambiguous",
        None,
    )
    assert (empty["draft"], empty["failed_checks"], empty["without_the_paper"]) == (
        "nothing_to_ask",
        None,
        None,
    )
    text = summary.read_text(encoding="utf-8")
    for paper_text in ("detector", "coupling", "cutoff", "Gizmos", "37.2", "⟦", "would say"):
        assert paper_text not in text


def test_the_summary_counts_by_kind_and_archive_and_by_reason(evaluation):
    summary = evaluation["folder"] / "sum.jsonl"
    out = evaluation["folder"] / "questions.jsonl"
    argv = argv_of(evaluation, questions=out, summary=summary)
    assert assemble.main(argv, source=evaluation["source"], origin=committed) == 0
    lines = read_jsonl(summary)
    cells = {(line["archive"], line["kind"]): line for line in lines if line["record"] == "cell"}
    assert list(cells) == [
        ("hep-ph", LATER_PIECE),
        ("hep-ph", OWN_TEXT),
        ("hep-ph", SEARCH_FIRST),
        ("hep-ph", NAMED_FIRST),
        ("hep-th", APPENDIX),
        ("hep-th", NAMED_FIRST),
    ]
    named = cells[("hep-ph", NAMED_FIRST)]
    assert (named["places"], named["drafts"], named["nothing_to_ask"]) == (1, 0, 1)
    assert (named["questions"], named["fills"], named["short"]) == (0, 0, 4)
    other = cells[("hep-th", NAMED_FIRST)]
    assert (other["places"], other["kept"], other["accepted"], other["rejected"]) == (2, 2, 1, 1)
    assert (other["questions"], other["short"]) == (1, 3)
    reasons = next(line for line in lines if line["record"] == "reasons")
    assert reasons["rejected"]["ambiguous"] == 1 and reasons["no_draft"] == {}
    assert set(reasons["failed_checks"]) == set(assemble.CHECKS)
    total = lines[-1]
    assert total["record"] == "total"
    assert (total["places"], total["drafts"], total["kept"], total["questions"]) == (7, 6, 6, 5)


def test_a_round_of_the_tuning_is_summed_up_without_questions(tmp_path):
    source = FixtureSource(papers())
    rows = [
        *SAMPLE,
        ("hep-th", 44, "2609.10008v1", NAMED_FIRST, "2.1"),
        ("hep-th", 45, "2609.10009v1", NAMED_FIRST, "2.1"),
    ]
    places = places_of_file(tmp_path, rows, input="tuning", last=False)
    files = made_of(tmp_path, places, source, {})
    summary = tmp_path / "sum.jsonl"
    assert assemble.main(argv_of(files, summary=summary), origin=committed) == 0
    head, *lines = read_jsonl(summary)
    assert head["questions"] is None and head["per_cell"] is None
    cell = next(line for line in lines if line["record"] == "cell")
    assert "questions" not in cell
    assert lines[-1]["accepted"] == 6 and "questions" not in lines[-1]
    # The reply cut short is no draft, and says why in the code's words.
    *_, cut, failing = [line for line in lines if line["record"] == "candidate"]
    assert (cut["draft"], cut["problem"]) == ("no_draft", "the reply stopped with max_tokens")
    assert "anchor_once" in failing["failed_checks"] and not failing["kept"]
    assert failing["without_the_paper"] is None and failing["verdict"] is None
    reasons = next(line for line in lines if line["record"] == "reasons")
    assert reasons["no_draft"] == {"the reply stopped with max_tokens": 1}
    assert reasons["failed_checks"]["anchor_once"] == 1
    total = lines[-1]
    assert (total["places"], total["drafts"], total["no_draft"]) == (9, 7, 1)
    assert (total["passed_checks"], total["kept"]) == (6, 6)


def test_the_rehearsal_takes_two_of_every_kind_from_the_last_round(tmp_path, capsys):
    # A paper of the tuning stands under no archive. The first paper is not findable: its
    # version is not the latest that arXiv lists.
    titles = dict(TITLES)
    found = papers(titles)
    newer = paper(replace(META, arxiv_id="2609.10002v2", title=titles["2609.10002v1"]))
    source = FixtureSource([*found, newer])
    rows = [
        ("", 1, "2609.10001v1", LATER_PIECE, "2.2"),
        ("", 1, "2609.10001v1", APPENDIX, "A"),
        ("", 2, "2609.10002v1", NAMED_FIRST, "2.1"),
        ("", 3, "2609.10003v2", NAMED_FIRST, "2.1"),
        ("", 4, "2609.10004v1", NAMED_FIRST, "2.1"),
        ("", 5, "2609.10005v1", NAMED_FIRST, "2.1"),
        ("", 5, "2609.10005v1", OWN_TEXT, "2"),
        ("", 6, "2609.10006v1", NAMED_FIRST, "2.1"),
    ]
    places = places_of_file(tmp_path, rows, input="tuning", last=True)
    files = made_of(tmp_path, places, source, {})
    out, summary = tmp_path / "rehearsal.jsonl", tmp_path / "sum.jsonl"
    argv = argv_of(files, questions=out, summary=summary, rehearsal=True)
    assert assemble.main(argv, source=source, origin=committed) == 0
    questions = load_questions(out)
    assert [q.id for q in questions] == [f"rehearsal-{n:02d}" for n in range(1, 9)]
    asked = [(q.notes["candidate"], q.type) for q in questions]
    # search_first: places 4 and 5, the first named_first drafts whose paper is findable
    # (place 3's is not); named_first: places 3 and 6; then place 8 fills one of the three
    # places that later_piece, appendix and own_text were short of.
    assert asked == [
        ("1", LATER_PIECE),
        ("2", APPENDIX),
        ("3", NAMED_FIRST),
        ("4", SEARCH_FIRST),
        ("5", SEARCH_FIRST),
        ("6", NAMED_FIRST),
        ("7", OWN_TEXT),
        ("8", NAMED_FIRST),
    ]
    assert questions[3].question.startswith('In the paper titled "Gizmos in a strong field"')
    assert "archive" not in questions[0].notes
    candidates = [line for line in read_jsonl(summary) if line["record"] == "candidate"]
    assert candidates[2]["search"] == {
        "findable": False,
        "latest": False,
        "rank": None,
        "problem": None,
    }
    assert candidates[3]["search"]["findable"] and candidates[3]["search"]["rank"] == 1
    assert [line["fill"] for line in candidates] == [
        False,
        False,
        False,
        False,
        False,
        False,
        False,
        True,
    ]
    total = read_jsonl(summary)[-1]
    assert (total["questions"], total["fills"]) == (8, 1)
    assert "2609.10002v1: findable False" in capsys.readouterr().out


@pytest.mark.parametrize(("head", "says"), [({"last": False}, "last round"), ({}, "last round")])
def test_the_rehearsal_is_made_of_the_last_round_alone(tmp_path, capsys, head, says):
    source = FixtureSource(papers())
    places = places_of_file(tmp_path, SAMPLE[:2], input="tuning", **head)
    files = made_of(tmp_path, places, source, {})
    summary = tmp_path / "sum.jsonl"
    argv = argv_of(files, questions=tmp_path / "q.jsonl", summary=summary, rehearsal=True)
    assert assemble.main(argv, source=source, origin=committed) == 1
    assert says in capsys.readouterr().err
    assert not (tmp_path / "q.jsonl").exists() and not summary.exists()


def test_the_places_of_the_evaluation_make_no_rehearsal_and_the_tuning_no_evaluation(
    evaluation, tmp_path, capsys
):
    summary = tmp_path / "sum.jsonl"
    argv = argv_of(evaluation, questions=tmp_path / "q.jsonl", summary=summary, rehearsal=True)
    assert assemble.main(argv, source=evaluation["source"], origin=committed) == 1
    assert "last round" in capsys.readouterr().err
    source = FixtureSource(papers())
    folder = tmp_path / "tuning"
    folder.mkdir()
    places = places_of_file(folder, SAMPLE[:2], input="tuning", last=True)
    files = made_of(folder, places, source, {})
    argv = argv_of(files, questions=folder / "q.jsonl", summary=folder / "sum.jsonl")
    assert assemble.main(argv, source=source, origin=committed) == 1
    assert "--rehearsal" in capsys.readouterr().err


def test_records_of_other_texts_make_no_questions(evaluation, monkeypatch, capsys):
    out, summary = evaluation["folder"] / "q.jsonl", evaluation["folder"] / "sum.jsonl"
    argv = argv_of(evaluation, questions=out, summary=summary)
    monkeypatch.setattr(drafting, "DRAFTER_VERSION", "d0")
    assert assemble.main(argv, origin=committed) == 1
    assert "made by the generator d1, and this code holds d0" in capsys.readouterr().err
    monkeypatch.undo()
    monkeypatch.setattr(ask, "code_version", lambda: {"commit": "c0ffee", "modified": False})
    monkeypatch.setattr(sift, "SIFT_VERSION", "s0")
    assert assemble.main(argv, origin=committed) == 1
    assert "sifted by the filters s1, and this code holds s0" in capsys.readouterr().err
    assert not out.exists() and not summary.exists()
    # A summary does not claim what texts made its records; it names them.
    summary = evaluation["folder"] / "sum.jsonl"
    assert assemble.main(argv_of(evaluation, summary=summary), origin=committed) == 0


def test_records_that_are_not_of_each_other_are_refused(evaluation, tmp_path, capsys):
    other = tmp_path / "other"
    other.mkdir()
    source = FixtureSource(papers())
    places = places_of_file(other, SAMPLE[:3])
    files = made_of(other, places, source, {})
    for name in ("drafts", "sift", "review"):
        mixed = {**evaluation, name: files[name]}
        argv = argv_of(mixed, summary=tmp_path / f"summary-{name}.jsonl")
        assert assemble.main(argv, origin=committed) == 1
        assert "refused:" in capsys.readouterr().err
        assert not (tmp_path / f"summary-{name}.jsonl").exists()


def test_another_record_of_drafts_of_the_same_places_is_refused(evaluation, capsys):
    again = evaluation["folder"] / "drafts-again.jsonl"
    argv = ["--places", str(evaluation["places"]), "--out", str(again)]

    def other(system, message, schema):
        return reply_of(nothing())

    assert drafting.main(argv, asker=Scripted(other), source=evaluation["source"]) == 0
    argv = argv_of({**evaluation, "drafts": again}, summary=evaluation["folder"] / "sum.jsonl")
    assert assemble.main(argv, origin=committed) == 1
    assert "sift.jsonl is not a record of drafts-again.jsonl" in capsys.readouterr().err


def test_a_review_that_names_other_records_is_refused(evaluation, capsys):
    head, *lines = read_jsonl(evaluation["review"])
    write_lines(evaluation["review"], [{**head, "sift": {"sha256": "0" * 64}}, *lines])
    argv = argv_of(evaluation, summary=evaluation["folder"] / "sum.jsonl")
    assert assemble.main(argv, origin=committed) == 1
    assert "is not a review of these records" in capsys.readouterr().err


def test_a_review_of_other_drafts_than_the_kept_ones_is_refused(evaluation, capsys):
    lines = read_jsonl(evaluation["review"])
    write_lines(evaluation["review"], lines[:-1])
    # The review names the records by their digests, which hold, and lacks a verdict.
    argv = argv_of(evaluation, summary=evaluation["folder"] / "sum.jsonl")
    assert assemble.main(argv, origin=committed) == 1
    assert "does not judge the drafts that" in capsys.readouterr().err


def test_papers_split_by_another_parser_make_no_questions(evaluation, monkeypatch, capsys):
    monkeypatch.setattr(assemble, "PARSER_VERSION", "9")
    folder = evaluation["folder"]
    argv = argv_of(evaluation, questions=folder / "q.jsonl", summary=folder / "sum.jsonl")
    assert assemble.main(argv, source=evaluation["source"], origin=committed) == 1
    assert "and this code splits papers with parser 9" in capsys.readouterr().err


def changed_paper(text):
    """The first paper of the evaluation with section 2.2 of another text."""
    first = next(p for p in papers() if p.meta.arxiv_id == "2609.10001v1")
    sections = tuple(
        replace(section, text=text(section.text)) if section.section_id == "2.2" else section
        for section in first.sections
    )
    return Paper(first.meta, sections, first.parser_version)


@pytest.mark.parametrize(
    ("text", "says"),
    [
        # Cut behind the anchor: the place ends beyond the end of the section.
        (lambda text: text[: text.index("reference scale.") + 16], "is not where the file"),
        # The anchor written another way, the section as long as before.
        (lambda text: text.replace("fixed to 0.0318", "fixed to 0.0319"), "does not contain"),
    ],
)
def test_a_paper_that_is_not_now_what_the_places_say_makes_no_questions(
    evaluation, capsys, text, says
):
    others = [p for p in papers() if p.meta.arxiv_id != "2609.10001v1"]
    source = FixtureSource([changed_paper(text), *others])
    folder = evaluation["folder"]
    argv = argv_of(evaluation, questions=folder / "q.jsonl", summary=folder / "sum.jsonl")
    assert assemble.main(argv, source=source, origin=committed) == 1
    assert says in capsys.readouterr().err
    assert not (folder / "q.jsonl").exists()


def test_what_is_there_is_not_written_over_and_changed_code_is_refused(evaluation, capsys):
    summary = evaluation["folder"] / "sum.jsonl"
    summary.write_text("", encoding="utf-8")
    assert assemble.main(argv_of(evaluation, summary=summary), origin=committed) == 1
    assert "is there already" in capsys.readouterr().err
    summary.unlink()

    def changed():
        return {"commit": "c0ffee", "modified": True}

    assert assemble.main(argv_of(evaluation, summary=summary), origin=changed) == 1
    assert "changes that are not committed" in capsys.readouterr().err
    assert not summary.exists()
    # Without a summary, a question file would not say what it was made of.
    with pytest.raises(SystemExit):
        assemble.main(argv_of(evaluation, questions=evaluation["folder"] / "q.jsonl"))
