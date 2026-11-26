"""The sheet of the drafts that are kept, and the verdicts read back from it (drafting/review.py)."""

import csv
import hashlib
import json
import re

import pytest
from drafting_paper import (
    ID,
    SEED,
    Scripted,
    as_reply,
    draft,
    later_draft,
    places_file,
    reply_of,
    source,
)

from hepph_paper_miner.drafting import ask, review, sift
from hepph_paper_miner.drafting import draft as drafting
from hepph_paper_miner.drafting.assign import read_places
from hepph_paper_miner.drafting.draft import Draft
from hepph_paper_miner.drafting.places import LATER_PIECE, NAMED_FIRST
from hepph_paper_miner.drafting.review import (
    REACH,
    REASONS,
    SHEET_COLUMNS,
    ReviewError,
    key_text,
    passage_of,
    read_verdicts,
)


def test_a_passage_is_the_paragraph_of_its_anchor_inside_the_part():
    text = "before\n\nthe first line\nthe anchor here\nand on\n\nafter"
    at = text.index("the anchor")
    assert passage_of(text, 0, len(text), at, "the anchor") == (
        "the first line\n⟦the anchor⟧ here\nand on"
    )
    # Not past the part: here the part ends in the paragraph.
    end = text.index("and on")
    assert passage_of(text, 0, end, at, "the anchor") == "the first line\n⟦the anchor⟧ here"


def test_a_passage_reaches_so_far_at_most():
    assert REACH == 2_000
    text = "x" * 2_500 + "the anchor" + "y" * 2_500
    at = text.index("the anchor")
    found = passage_of(text, 0, len(text), at, "the anchor")
    assert found == "x" * 2_000 + "⟦the anchor⟧" + "y" * 2_000


def test_the_key_is_shown_as_a_reader_reads_it():
    found = Draft.from_dict(
        draft(
            numbers=[
                {"label": "area", "value": 37.2, "unit": "square metres", "min_sig_figs": 3},
                {"label": "count", "value": 4096, "unit": "", "min_sig_figs": 4},
            ],
            phrases=[{"label": "unit", "any_of": ["square metres", "m^2"]}],
        )
    )
    assert key_text(found) == (
        "area: 37.2 square metres (≥ 3 digit(s)); count: 4096 (≥ 4 digit(s)); "
        'unit: one of "square metres" / "m^2"'
    )


def test_the_reasons_of_a_rejection_are_these():
    assert list(REASONS) == [
        "ambiguous",
        "not_the_passage",
        "key_or_note",
        "not_running_text",
        "other",
    ]


# --- the command ----------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def committed_code(monkeypatch):
    monkeypatch.setattr(ask, "code_version", lambda: {"commit": "c0ffee", "modified": False})


def generator(system, message, schema):
    part = re.search(r"<part>\nSection: (\S+)", message)[1]
    return reply_of(as_reply(draft() if part == "2.1" else later_draft()))


def filters(system, message, schema):
    if system == sift.WITHOUT_SYSTEM:
        return reply_of({"answer": "I would say 40."})
    return reply_of({"answer": "37.2 square metres; 0.0318.", "found": True})


@pytest.fixture
def made(tmp_path):
    """A sheet of two kept drafts, and its key."""
    places = places_file(tmp_path, ("2.1", NAMED_FIRST), ("2.2", LATER_PIECE))
    drafts, out = tmp_path / "drafts.jsonl", tmp_path / "sift.jsonl"
    assert (
        drafting.main(
            ["--places", str(places), "--out", str(drafts)],
            asker=Scripted(generator),
            source=source(),
        )
        == 0
    )
    argv = ["--places", str(places), "--drafts", str(drafts), "--out", str(out)]
    assert sift.main(argv, asker=Scripted(filters), source=source()) == 0
    sheet, key = tmp_path / "sheet.csv", tmp_path / "key.jsonl"
    argv = ["--places", str(places), "--drafts", str(drafts), "--sift", str(out)]
    assert review.main([*argv, "--sheet", str(sheet), "--key", str(key)], source=source()) == 0
    return {"sheet": sheet, "key": key, "places": places, "folder": tmp_path}


def rows_of(sheet):
    with sheet.open(encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def write(sheet, rows):
    with sheet.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, SHEET_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)


def test_the_sheet_shows_what_a_draft_is_judged_by_and_nothing_else(made):
    rows = rows_of(made["sheet"])
    assert list(rows[0]) == list(SHEET_COLUMNS)
    assert len(rows) == 2
    shown = " ".join(" ".join(row.values()) for row in rows)
    for hidden in ("named_first", "later_piece", "hep-ph", "kind", "archive"):
        assert hidden not in shown
    area = next(row for row in rows if "area" in row["question"])
    assert area["question"] == f"In arXiv:{ID}, what is the total area of the detector?"
    assert area["section"] == "2.1 | Detector setup"
    assert "⟦The detector has an area of 37.2 square metres⟧ in total." in area["passage"]
    assert area["verdict"] == area["why_rejected"] == area["note"] == ""


def test_the_rows_stand_in_the_order_of_the_hash(made):
    lines = [json.loads(line) for line in made["key"].read_text(encoding="utf-8").splitlines()]
    head, *keyed = lines
    assert head["record"] == "review-key" and head["seed"] == SEED

    def drawn(row):
        place = f"{SEED}:{row['paper']}:{row['section']}:{row['start']}"
        return hashlib.sha256(place.encode()).hexdigest()

    order = sorted(keyed, key=drawn)
    assert [row["row"] for row in order] == [1, 2]
    assert [row["row"] for row in keyed] == [1, 2]
    # The seed is part of what decides.
    place = read_places(made["places"]).places[0]
    expected = f"{SEED}:{place.paper}:{place.section}:{place.start}"
    assert review.order_key(SEED, place) == hashlib.sha256(expected.encode()).hexdigest()


def judged(made, verdicts):
    rows = rows_of(made["sheet"])
    for row, (verdict, why, note) in zip(rows, verdicts):
        row.update(verdict=verdict, why_rejected=why, note=note)
    write(made["sheet"], rows)


def test_the_verdicts_are_read_back_without_the_notes(made, capsys):
    judged(made, [("accept", "", "fine"), ("Reject", "ambiguous", "which coupling?")])
    out = made["folder"] / "verdicts.jsonl"
    argv = ["--read", "--sheet", str(made["sheet"]), "--key", str(made["key"]), "--out", str(out)]
    assert review.main(argv) == 0
    head, *lines = [json.loads(line) for line in out.read_text(encoding="utf-8").splitlines()]
    assert head["record"] == "review" and head["accepted"] == 1 and head["rejected"] == 1
    assert head["reasons"]["ambiguous"] == 1
    assert {line["verdict"] for line in lines} == {"accept", "reject"}
    for line in lines:
        assert set(line) == {"record", "number", "paper", "kind", "verdict", "why_rejected"}
    text = out.read_text(encoding="utf-8")
    for paper_text in ("which coupling", "fine", "detector", "⟦"):
        assert paper_text not in text
    assert "2 verdict(s): 1 accepted, 1 rejected" in capsys.readouterr().out


@pytest.mark.parametrize(
    ("verdicts", "says"),
    [
        ([("accept", "", ""), ("", "", "")], "the verdict is ''"),
        ([("accept", "", ""), ("reject", "", "")], "a rejection needs one of"),
        ([("accept", "", ""), ("reject", "too long", "")], "a rejection needs one of"),
        ([("accept", "", ""), ("reject", "other", "")], "says which in the note"),
        ([("accept", "ambiguous", ""), ("accept", "", "")], "an accepted draft has a reason"),
    ],
)
def test_a_sheet_that_is_not_judged_through_is_refused(made, verdicts, says):
    judged(made, verdicts)
    with pytest.raises(ReviewError, match=re.escape(says)):
        read_verdicts(made["sheet"], made["key"])


def test_a_row_put_next_to_another_question_is_refused(made):
    judged(made, [("accept", "", ""), ("accept", "", "")])
    rows = rows_of(made["sheet"])
    rows[0]["question"], rows[1]["question"] = rows[1]["question"], rows[0]["question"]
    write(made["sheet"], rows)
    with pytest.raises(ReviewError, match="has another question than the key says"):
        read_verdicts(made["sheet"], made["key"])


def test_a_sheet_without_a_row_of_the_key_is_refused(made):
    judged(made, [("accept", "", ""), ("accept", "", "")])
    write(made["sheet"], rows_of(made["sheet"])[:1])
    with pytest.raises(ReviewError, match="no row for number"):
        read_verdicts(made["sheet"], made["key"])


def test_a_sheet_or_key_that_is_there_is_not_written_over(made, capsys):
    folder = made["folder"]
    argv = [
        "--places",
        str(made["places"]),
        "--drafts",
        str(folder / "drafts.jsonl"),
        "--sift",
        str(folder / "sift.jsonl"),
        "--sheet",
        str(made["sheet"]),
        "--key",
        str(folder / "other-key.jsonl"),
    ]
    assert review.main(argv, source=source()) == 1
    assert "is there already" in capsys.readouterr().err
