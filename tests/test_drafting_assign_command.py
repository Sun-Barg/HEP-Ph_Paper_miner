"""The command that writes the places to draft about (drafting/assign.py): the rounds of the
tuning, the file of places, the search for a title, and the papers of the evaluation.

No network: the papers come from a source in memory.
"""

import json
from dataclasses import replace
from pathlib import Path

import pytest
from drafting_paper import ID, META, SEED, TITLE, another, filler, paper, source

from hepph_paper_miner.drafting import assign
from hepph_paper_miner.drafting.assign import (
    PER_ROUND,
    ROUNDS,
    TUNING_KINDS,
    Placed,
    look_up,
    one_of_each,
    read_places,
    round_positions,
    tuning_order,
)
from hepph_paper_miner.drafting.places import (
    APPENDIX,
    KINDS,
    LATER_PIECE,
    NAMED_FIRST,
    OWN_TEXT,
    SEARCH_FIRST,
    places_of,
)
from hepph_paper_miner.sources.arxiv_latex import PARSER_VERSION
from hepph_paper_miner.sources.base import ErrorKind, Paper, SearchResult, Section, SourceError
from hepph_paper_miner.sources.fixture import FixtureSource
from hepph_paper_miner.survey.records import RecordError, write_lines
from hepph_paper_miner.survey.sample import order_key

ROOT = Path(__file__).parent.parent
PLAN = ROOT / "eval_data" / "survey_plan.json"


@pytest.fixture(autouse=True)
def committed_code(monkeypatch):
    monkeypatch.setattr(assign, "code_version", lambda: {"commit": "c0ffee", "modified": False})


# --- the rounds of the tuning ---------------------------------------------------------------


def test_the_papers_of_the_tuning_stand_in_the_order_of_the_survey_hash():
    named = [
        line.strip()
        for line in (ROOT / "eval_data" / "target_papers.txt")
        .read_text(encoding="utf-8")
        .splitlines()
        if line.strip() and not line.startswith("#")
    ]
    ordered = tuning_order(named, SEED)
    assert len(ordered) == 23
    # Written out, as the design names them (DESIGN file 15, 21-15-1, 8).
    assert ordered[:6] == [
        "1202.4039v2",
        "1202.3665v4",
        "1402.6703v2",
        "1407.7905v1",
        "1003.0904v2",
        "1710.05137v1",
    ]
    assert ordered[-1] == "2610.26648v1"
    assert ordered == sorted(named, key=lambda paper_id: order_key(SEED, paper_id))


@pytest.mark.parametrize(
    ("round_", "last", "positions"),
    [
        (1, False, (1, 6)),
        (2, False, (7, 12)),
        (2, True, (7, 23)),
        (3, False, (13, 23)),
        (3, True, (13, 23)),
    ],
)
def test_a_round_takes_the_next_six_and_the_last_takes_the_rest(round_, last, positions):
    taken = round_positions(round_, last, 23)
    assert (taken.start, taken.stop - 1) == positions
    assert PER_ROUND == 6 and ROUNDS == 3


@pytest.mark.parametrize(("round_", "last"), [(1, True), (0, False), (4, False)])
def test_there_is_no_such_round(round_, last):
    with pytest.raises(ValueError):
        round_positions(round_, last, 23)


def test_a_paper_of_the_tuning_gets_one_place_of_every_kind_it_has():
    found = one_of_each(ID, places_of(paper()), SEED)
    assert [place.kind for place in found] == list(TUNING_KINDS)
    assert TUNING_KINDS == (LATER_PIECE, APPENDIX, OWN_TEXT, NAMED_FIRST)
    named = [place for place in places_of(paper()) if place.kind == NAMED_FIRST]
    chosen = min(named, key=lambda place: (assign.place_key(SEED, ID, place.section), place.start))
    assert found[-1] == chosen


def test_the_command_writes_the_places_of_a_round(tmp_path, capsys):
    target = tmp_path / "targets.txt"
    target.write_text(f"# a comment\n{ID}\n2609.07777v2\n", encoding="utf-8")
    papers = FixtureSource([paper(), another("2609.07777v2")])
    out = tmp_path / "places.jsonl"
    argv = ["--tuning", str(target), "--round", "1", "--plan", str(PLAN), "--out", str(out)]
    assert assign.main(argv, source=papers) == 0
    lines = [json.loads(line) for line in out.read_text(encoding="utf-8").splitlines()]
    head = lines[0]
    assert head["record"] == "places" and head["input"] == "tuning"
    assert (head["round"], head["last"], head["positions"], head["seed"]) == (
        1,
        False,
        [1, 2],
        SEED,
    )
    assert head["parser_version"] == PARSER_VERSION and head["code"]["commit"] == "c0ffee"
    papers_lines = [line for line in lines if line["record"] == "paper"]
    assert [line["id"] for line in papers_lines] == tuning_order([ID, "2609.07777v2"], SEED)
    assert papers_lines[0]["places"] == {LATER_PIECE: 1, APPENDIX: 1, OWN_TEXT: 1, NAMED_FIRST: 4}
    found = read_places(out)
    assert [place.number for place in found.places] == list(range(1, 9))
    assert [place.kind for place in found.places] == list(TUNING_KINDS) * 2
    # No text of a paper: neither its title nor a word of a section.
    assert TITLE not in out.read_text(encoding="utf-8") and "Detector" not in out.read_text(
        encoding="utf-8"
    )
    assert "8 place(s) written" in capsys.readouterr().out


def test_a_paper_that_cannot_be_read_is_written_down_and_gets_no_place(tmp_path):
    target = tmp_path / "targets.txt"
    target.write_text(f"{ID}\n2503.00002v1\n", encoding="utf-8")
    papers = FixtureSource([paper()], {"2503.00002v1": ErrorKind.PARSE_ERROR})
    out = tmp_path / "places.jsonl"
    argv = ["--tuning", str(target), "--round", "1", "--plan", str(PLAN), "--out", str(out)]
    assert assign.main(argv, source=papers) == 0
    lines = [json.loads(line) for line in out.read_text(encoding="utf-8").splitlines()]
    outcome = {line["id"]: line["outcome"] for line in lines if line["record"] == "paper"}
    assert outcome == {ID: "ok", "2503.00002v1": "parse_error"}
    assert {place.paper for place in read_places(out).places} == {ID}


@pytest.mark.parametrize(
    ("argv", "says"),
    [
        (["--round", "1"], "give either --tuning with --round, or --sample with --outcomes"),
        (["--tuning", "t.txt"], "--tuning needs --round"),
        (["--sample", "s.jsonl"], "--sample needs --outcomes"),
        (["--tuning", "t.txt", "--round", "1", "--sample", "s.jsonl"], "give either"),
    ],
)
def test_it_refuses_arguments_it_cannot_start_with(tmp_path, capsys, argv, says):
    assert assign.main([*argv, "--out", str(tmp_path / "out.jsonl")], source=source()) == 2
    assert says in capsys.readouterr().err


def test_a_file_that_is_there_is_not_written_over(tmp_path, capsys):
    out = tmp_path / "places.jsonl"
    out.write_text("{}\n", encoding="utf-8")
    argv = ["--tuning", "t.txt", "--round", "1", "--out", str(out)]
    assert assign.main(argv, source=source()) == 1
    assert "is there already" in capsys.readouterr().err


def test_changed_code_writes_nothing(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(assign, "code_version", lambda: {"commit": "c0ffee", "modified": True})
    target = tmp_path / "targets.txt"
    target.write_text(f"{ID}\n", encoding="utf-8")
    out = tmp_path / "places.jsonl"
    argv = ["--tuning", str(target), "--round", "1", "--plan", str(PLAN), "--out", str(out)]
    assert assign.main(argv, source=source()) == 1
    assert not out.exists()


# --- the file of places ---------------------------------------------------------------------


def test_a_file_of_places_reads_back_as_it_was_written(tmp_path):
    written = [
        Placed(1, "hep-ph", 41, ID, SEARCH_FIRST, "2.1", 0, 1586),
        Placed(2, "hep-th", 41, "2609.07777v2", LATER_PIECE, "2.2", 19972, 23597),
    ]
    path = tmp_path / "places.jsonl"
    write_lines(path, [{"record": "places"}, *(place.as_line() for place in written)])
    assert read_places(path).places == tuple(written)
    assert written[1].as_line()["chars"] == 23597 - 19972


@pytest.mark.parametrize(
    "change",
    [{"number": 3}, {"kind": "whatever"}, {"start": "0"}, {"paper": None}],
)
def test_a_file_of_places_that_was_changed_by_hand_is_refused(tmp_path, change):
    line = Placed(1, "", 1, ID, NAMED_FIRST, "2.1", 0, 1586).as_line() | change
    path = tmp_path / "places.jsonl"
    write_lines(path, [{"record": "places"}, line])
    with pytest.raises(RecordError):
        read_places(path)


# --- the search for a title -----------------------------------------------------------------


class Searches(FixtureSource):
    """A source whose search answers as it is told."""

    def __init__(self, papers, answer):
        super().__init__(papers)
        self._answer = answer
        self.searched: list[str] = []

    def search(self, query):
        self.searched.append(query.query)
        if isinstance(self._answer, Exception):
            raise self._answer
        return self._answer(query)


def test_a_paper_is_findable_when_a_search_for_its_title_lists_it():
    # Another paper whose title holds every word of this one's is listed first.
    papers = [another("2609.00001v1", f"{TITLE}, again"), paper()]
    found = look_up(FixtureSource(papers), paper())
    assert (found.findable, found.latest, found.rank) == (True, True, 2)


def test_the_search_is_made_with_the_title_as_arxiv_lists_it_and_five_results():
    asked = []

    def answer(query):
        asked.append((query.query, query.max_results))
        return SearchResult((META,), 1)

    assert look_up(Searches([paper()], answer), paper()).findable
    assert asked == [(TITLE, 5)]


def test_a_paper_whose_latest_version_is_another_is_not_findable():
    newer = paper(replace(META, arxiv_id="2609.01234v2"))
    found = look_up(FixtureSource([paper(), newer]), paper())
    assert (found.findable, found.latest, found.rank) == (False, False, None)


def test_a_search_that_misses_or_fails_makes_a_paper_not_findable():
    missing = look_up(Searches([paper()], lambda query: SearchResult((), 0)), paper())
    assert (missing.findable, missing.latest, missing.problem) == (False, True, None)
    failing = look_up(Searches([paper()], SourceError(ErrorKind.UPSTREAM_BUSY, "x")), paper())
    assert (failing.findable, failing.problem) == (False, "upstream_busy")


# --- the papers of the evaluation -----------------------------------------------------------


def sample_and_outcomes(folder, papers, outcome=None, unanswered=0):
    """A sample of places 41 on, as survey.sample writes it, and survey.run's outcomes of it."""
    by_archive = {}
    for archive, paper_id in papers:
        by_archive.setdefault(archive, []).append(paper_id)
    head = {"record": "sample", "seed": SEED, "per_archive": 80, "first": 41}
    lines, ranks = [head], {}
    for archive, ids in by_archive.items():
        lines.append({"record": "archive", "archive": archive, "drawn": len(ids)})
    for archive, ids in by_archive.items():
        for rank, paper_id in enumerate(sorted(ids, key=lambda each: order_key(SEED, each)), 41):
            ranks[paper_id] = (archive, rank)
            lines.append(
                {
                    "record": "paper",
                    "archive": archive,
                    "rank": rank,
                    "id": paper_id,
                    "primary": archive,
                    "sha256": order_key(SEED, paper_id),
                }
            )
    sample = folder / "sample.jsonl"
    digest = write_lines(sample, lines)
    outcomes = folder / "outcomes.jsonl"
    head = {
        "record": "outcomes",
        "sample": {"file": sample.name, "sha256": digest},
        "parser_version": PARSER_VERSION,
        "unanswered": unanswered,
    }
    found = [
        {
            "record": "paper",
            "archive": archive,
            "rank": rank,
            "id": paper_id,
            "outcome": (outcome or {}).get(paper_id, "ok"),
        }
        for paper_id, (archive, rank) in ranks.items()
    ]
    write_lines(outcomes, [head, *found])
    return sample, outcomes


def test_the_places_of_the_evaluation_are_given_out_by_the_rule(tmp_path, capsys):
    ids = ["2609.00001v1", "2609.00002v1", "2609.00003v1"]
    papers = [another(paper_id) for paper_id in ids]
    sample, outcomes = sample_and_outcomes(
        tmp_path,
        [("hep-ph", ids[0]), ("hep-ph", ids[1]), ("hep-th", ids[2])],
        {ids[1]: "parse_error"},
    )
    out = tmp_path / "places.jsonl"
    argv = [
        "--sample",
        str(sample),
        "--outcomes",
        str(outcomes),
        "--per-kind",
        "1",
        "--out",
        str(out),
    ]
    assert assign.main(argv, source=FixtureSource(papers)) == 0
    lines = [json.loads(line) for line in out.read_text(encoding="utf-8").splitlines()]
    head = lines[0]
    assert head["input"] == "sample" and head["per_kind"] == 1 and head["seed"] == SEED
    by_id = {line["id"]: line for line in lines if line["record"] == "paper"}
    assert by_id[ids[1]]["outcome"] == "parse_error" and "places" not in by_id[ids[1]]
    # A search for the title was made for the papers with a named_first place; only its rank is kept.
    assert by_id[ids[0]]["search"]["findable"] is True and isinstance(
        by_id[ids[0]]["search"]["rank"], int
    )
    archives = {line["archive"]: line for line in lines if line["record"] == "archive"}
    # One split paper an archive: it takes the rarest kind it has, a later piece.
    assert archives["hep-ph"]["filled"][LATER_PIECE] == 1
    assert sum(archives["hep-ph"]["missing"].values()) == len(KINDS) - 1
    placed = read_places(out).places
    assert [(place.archive, place.kind) for place in placed] == [
        ("hep-ph", LATER_PIECE),
        ("hep-th", LATER_PIECE),
    ]
    assert TITLE not in out.read_text(encoding="utf-8")


def test_outcomes_of_another_sample_or_with_papers_left_unanswered_are_refused(tmp_path, capsys):
    ids = ["2609.00001v1"]
    sample, outcomes = sample_and_outcomes(tmp_path, [("hep-ph", ids[0])], unanswered=1)
    out = tmp_path / "places.jsonl"
    argv = ["--sample", str(sample), "--outcomes", str(outcomes), "--out", str(out)]
    assert assign.main(argv, source=FixtureSource([another(ids[0])])) == 1
    assert "did not answer" in capsys.readouterr().err
    other = tmp_path / "other"
    other.mkdir()
    sample2, _ = sample_and_outcomes(other, [("hep-ph", "2609.00009v1")])
    argv = ["--sample", str(sample2), "--outcomes", str(outcomes), "--out", str(out)]
    assert assign.main(argv, source=FixtureSource([another(ids[0])])) == 1
    assert "is not what survey.run made of" in capsys.readouterr().err


def test_search_first_goes_only_to_a_paper_that_its_title_finds(tmp_path):
    # Papers with one section: named_first places alone, so search_first is the rarest
    # kind they can have. The second has a newer version, which the search would list.
    def plain(arxiv_id):
        meta = replace(META, arxiv_id=arxiv_id)
        return Paper(meta, (Section("1", "Only", 1, filler(1_500)),), PARSER_VERSION)

    ids = ["2609.00011v1", "2609.00012v1"]
    papers = [plain(ids[0]), plain(ids[1]), plain("2609.00012v2")]
    sample, outcomes = sample_and_outcomes(tmp_path, [("hep-ph", ids[0]), ("hep-th", ids[1])])
    out = tmp_path / "places.jsonl"
    argv = [
        "--sample",
        str(sample),
        "--outcomes",
        str(outcomes),
        "--per-kind",
        "1",
        "--out",
        str(out),
    ]
    assert assign.main(argv, source=FixtureSource(papers)) == 0
    kinds = {place.paper: place.kind for place in read_places(out).places}
    assert kinds == {ids[0]: SEARCH_FIRST, ids[1]: NAMED_FIRST}


def test_outcomes_without_a_paper_of_the_sample_are_refused(tmp_path, capsys):
    ids = ["2609.00001v1", "2609.00002v1"]
    sample, outcomes = sample_and_outcomes(tmp_path, [("hep-ph", ids[0]), ("hep-ph", ids[1])])
    lines = outcomes.read_text(encoding="utf-8").splitlines()
    outcomes.write_text("\n".join(lines[:-1]) + "\n", encoding="utf-8")
    out = tmp_path / "places.jsonl"
    argv = ["--sample", str(sample), "--outcomes", str(outcomes), "--out", str(out)]
    assert assign.main(argv, source=FixtureSource([another(each) for each in ids])) == 1
    assert "has no line for" in capsys.readouterr().err
