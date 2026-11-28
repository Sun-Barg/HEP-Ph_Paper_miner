"""The papers of the second evaluation, how they came back, their places and their questions.

results/archives/ holds what was made of the 240 papers of the plan
(eval_data/archives_plan.json) between the commit that brought the plan and the first run:
the sample that drafting.papers drew from the list of the survey, what survey.run made of
it, the places that drafting.assign gave out, the verdicts that drafting.review read off
the sheet of the review, and the summary of every candidate that drafting.assemble wrote
beside the question file, eval_data/questions_archives.jsonl.

These tests hold the files by their SHA-256, against the plan and the list of the survey
and against each other, and hold up what the README of the folder, the README of all
results, the rules for agents (CLAUDE.md) and the entries under Deviations of the
pre-registration say of them. From here on the files are fixed (CLAUDE.md, "The second
evaluation"): a command would write its file anew with another time in the first line,
the places are given out once, and the pre-registration names the question file by its
digest.

The drafts, the replies of the filters and the sheet of the review hold paper text and are
not in the repository. What the summary says of them, their digests and their counts, is
held here against the files that are, and cannot be held against them. Who read the
sheet, and what its notes say, cannot be held against a file either.

No network and no LLM.
"""

import re
from collections import Counter
from datetime import datetime, timedelta
from functools import cache
from pathlib import Path

import pytest

from hepph_paper_miner.agent.origin import file_digest
from hepph_paper_miner.drafting.assemble import PER_CELL, choose
from hepph_paper_miner.drafting.assign import PER_KIND, Placed, assign, read_places
from hepph_paper_miner.drafting.checks import ANCHOR_CHARS, ANSWER_CHARS, CHECKS, QUESTION_CHARS
from hepph_paper_miner.drafting.draft import DRAFT, MAX_DRAFTS, NOTHING
from hepph_paper_miner.drafting.papers import draw_places, drawing_of, load_archives_plan
from hepph_paper_miner.drafting.places import (
    APPENDIX,
    KINDS,
    LATER_PIECE,
    LEAST_CHARS,
    NAMED_FIRST,
    OWN_TEXT,
    SEARCH_FIRST,
    Place,
)
from hepph_paper_miner.drafting.review import ACCEPT, REASONS, REJECT, read_review
from hepph_paper_miner.eval.grade import RIGHT
from hepph_paper_miner.eval.paired import NOT_WORSE, adjusted_wald, reading
from hepph_paper_miner.eval.questions import load_questions
from hepph_paper_miner.eval.report import PRICES
from hepph_paper_miner.server import SECTION_CHAR_LIMIT
from hepph_paper_miner.survey.plan import ORDER
from hepph_paper_miner.survey.records import read_lines
from hepph_paper_miner.survey.run import OK, branch, read_outcomes, tally, walk
from hepph_paper_miner.survey.sample import read_sample

ROOT = Path(__file__).parent.parent
EVAL_DATA = ROOT / "eval_data"
PLAN = EVAL_DATA / "archives_plan.json"
SURVEY_PLAN = EVAL_DATA / "survey_plan.json"
POPULATION = ROOT / "results" / "survey" / "population.jsonl"
PRE_REGISTRATION = EVAL_DATA / "PREREGISTRATION_2.md"
QUESTIONS = EVAL_DATA / "questions_archives.jsonl"
HERE = ROOT / "results" / "archives"
SAMPLE, OUTCOMES, PLACES = HERE / "sample.jsonl", HERE / "outcomes.jsonl", HERE / "places.jsonl"
REVIEW, CANDIDATES = HERE / "review.jsonl", HERE / "candidates.jsonl"

# The files as the commands wrote them on the maintainer's computer.
SHA256 = {
    SAMPLE: "563cd02a19808ea22d76007057efbccabb296c80e007ebc4acc943a9f67c49fd",
    OUTCOMES: "6bcb8032fa491b9d70f97a49fbd32cccbbb2af946f1271d38dd97180242717de",
    PLACES: "31086c8a7c4e9c0bf8405378bf37334f449029fc6b1b8c5a4e1216e791940f2c",
    REVIEW: "7993fc9bd070aef59e3135c1e819623f69547d4fd701afa1cdcdab375f2d9351",
    CANDIDATES: "753996728d8a6c656ba7abc62bbc6b9cb9697546ab5ffdfde2a3f1917af8d8c3",
    QUESTIONS: "09ead4c927a6a0edd13ba8d9d05440ddd7e2b9ebdc3930da949efb3e1002110c",
}

# The commit that brought the plan and the pre-registration. The sample, the outcomes and
# the places were made from it, and the files name it in full.
PLANNED = "5a45e8d"
# The commit whose code read the sheet of the review and made the questions.
ASSEMBLED = "97ba66e"
# The texts that drafted and sifted, as the pre-registration names them (Sections 4 and 6).
DRAFTER, DRAFTER_TEXTS = "d3", "2bfcb708c891ff4f"
SIFTER, SIFTER_TEXTS = "s1", "cfd6f7744121d71e"
# The parser that split the papers and that the places were cut by.
PARSER = "5"
ARCHIVES = ("hep-ph", "hep-th", "hep-ex", "astro-ph")

NO_TEX, TURNED_AWAY = "no_full_text", "parse_error"
# What a line of the outcomes holds, by how the paper came back.
PAPER = {"record", "archive", "rank", "id", "primary", "outcome"}
OUTCOME_KEYS = {
    OK: PAPER | {"sections", "subsections", "chars", "largest", "no_headings"},
    NO_TEX: PAPER | {"branch", "detail"},
    TURNED_AWAY: PAPER | {"branch", "detail"},
}
IDENTIFIER = re.compile(r"\d{4}\.\d{5}v\d+")
DIGEST = re.compile(r"[0-9a-f]{64}")
# What a line of the summary says of one place, and of one of its drafts.
CANDIDATE_KEYS = {
    "record",
    "number",
    "archive",
    "rank",
    "paper",
    "kind",
    "section",
    "start",
    "end",
    "chars",
    "draft",
    "problem",
    "drafts",
    "kept",
    "kept_draft",
    "verdict",
    "why_rejected",
    "question",
    "asked_as",
    "fill",
    "usage",
    "cost",
}
DRAFT_KEYS = {"draft", "failed_checks", "without_the_paper", "from_the_passage"}
WORDS = {2: "two", 5: "five", 7: "seven"}
USAGE_KEYS = {
    "cache_creation_input_tokens",
    "cache_read_input_tokens",
    "input_tokens",
    "output_tokens",
}


@cache
def plan():
    return load_archives_plan(PLAN)


@cache
def sample():
    return read_sample(SAMPLE)


@cache
def outcomes():
    """The first line of the outcomes and their paper lines."""
    return read_outcomes(OUTCOMES)


@cache
def places_file():
    """Every line of the file of places, and the places as the commands read them."""
    lines, _ = read_lines(PLACES, "places")
    return lines, read_places(PLACES)


def of(record: str) -> list[dict]:
    return [line for line in places_file()[0] if line["record"] == record]


def headings() -> dict[str, str]:
    """The headings of the sections of the pre-registration, by their numbers."""
    text = PRE_REGISTRATION.read_text(encoding="utf-8")
    return dict(re.findall(r"^## (\d+)\. (.+)$", text, flags=re.MULTILINE))


def section(number: int) -> str:
    """The text of one numbered section of the pre-registration."""
    text = PRE_REGISTRATION.read_text(encoding="utf-8")
    found = re.search(rf"^## {number}\. .*?(?=^## \d+\. |\Z)", text, flags=re.MULTILINE | re.DOTALL)
    return found.group(0)


@cache
def review():
    """The lines of the file of verdicts, and by place the verdict, its reason and the draft."""
    lines, _ = read_lines(REVIEW, "review")
    _, found, _ = read_review(REVIEW)
    return lines, found


@cache
def summary() -> list[dict]:
    return read_lines(CANDIDATES, "candidates")[0]


def candidates() -> list[dict]:
    return [line for line in summary() if line["record"] == "candidate"]


def passes(draft: dict) -> bool:
    """Whether a draft passed every check and both filters (Section 6 of the pre-registration)."""
    return (
        not draft["failed_checks"]
        and draft["without_the_paper"] != RIGHT
        and draft["from_the_passage"] == RIGHT
    )


def counts_of(found: list[dict]) -> dict:
    """What a line of counts says of some candidates, counted again from their lines."""
    drafts = [draft for line in found for draft in line["drafts"]]
    keeps = [line["kept_draft"] for line in found if line["kept"]]
    return {
        "places": len(found),
        "with_drafts": sum(1 for line in found if line["draft"] == DRAFT),
        "drafts": len(drafts),
        "nothing_to_ask": sum(1 for line in found if line["draft"] == NOTHING),
        "no_draft": sum(1 for line in found if line["draft"] not in (DRAFT, NOTHING)),
        "passed_checks": sum(1 for draft in drafts if not draft["failed_checks"]),
        "right_without_the_paper": sum(1 for x in drafts if x["without_the_paper"] == RIGHT),
        "right_from_the_passage": sum(1 for x in drafts if x["from_the_passage"] == RIGHT),
        "kept": len(keeps),
        "kept_by_draft": {str(at): keeps.count(at) for at in range(1, MAX_DRAFTS + 1)},
        "accepted": sum(1 for line in found if line["verdict"] == ACCEPT),
        "rejected": sum(1 for line in found if line["verdict"] == REJECT),
    }


def by_kind_and_archive(found: list[dict], kind_of: str = "kind") -> dict[str, list[int]]:
    """How many of some candidates each archive has of each kind, in the order of KINDS."""
    return {
        archive: [
            sum(1 for x in found if x["archive"] == archive and x[kind_of] == kind)
            for kind in KINDS
        ]
        for archive in ARCHIVES
    }


def flat(path: Path) -> str:
    """A text with every run of white space as one blank, as a sentence is looked for."""
    return " ".join(path.read_text(encoding="utf-8").split())


def moment(text: str) -> datetime:
    found = datetime.fromisoformat(text)
    assert found.utcoffset() == timedelta(0)
    return found


def test_the_files_are_the_bytes_that_were_written():
    # Also on Windows: each file names the one before it by this hash, and the
    # pre-registration names the question file by its own.
    for path, digest in SHA256.items():
        assert file_digest(path) == digest, path.name


# --- the papers ---------------------------------------------------------------------------


def test_the_sample_is_what_the_plan_draws_from_the_list_of_the_survey():
    drawing = drawing_of(plan(), SURVEY_PLAN, POPULATION)
    drawn = draw_places(
        drawing.papers, drawing.survey_plan, plan().archives, plan().first, plan().last
    )
    head = sample().head

    assert list(sample().papers) == drawn and len(drawn) == 240
    assert plan().archives == ARCHIVES == tuple(sample().counts)
    assert (head["first"], head["per_archive"]) == (plan().first, plan().per_archive) == (41, 60)
    assert (head["seed"], head["order"]) == (drawing.survey_plan.seed, ORDER)
    assert head["population"] == drawing.population
    assert head["survey_plan"] == {
        "name": drawing.survey_plan.name,
        "sha256": drawing.survey_plan.sha256,
    }
    for archive in ARCHIVES:
        count = sample().counts[archive]
        assert (count["listed"], count["primary"]) == (
            drawing.counts[archive]["listed"],
            drawing.counts[archive]["primary"],
        )
        ranks = [paper.rank for paper in sample().papers if paper.archive == archive]
        assert ranks == list(range(41, 101)) and count["drawn"] == 60


def test_the_sample_was_drawn_by_the_commit_that_holds_the_plan():
    head = sample().head

    # The plan was in a commit before the papers were drawn, and no file that the
    # repository keeps had been changed: so the rule came first.
    assert head["plan"]["name"] == plan().name == "archives-1"
    assert head["plan"]["sha256"] == plan().sha256
    assert head["plan"]["commit"].startswith(PLANNED)
    assert head["code"] == {"commit": head["plan"]["commit"], "modified": False}
    assert f"{moment(head['drawn']):%Y-%m-%d %H:%M}" == "2026-11-27 14:11"


# --- what came back -----------------------------------------------------------------------


def test_the_outcomes_are_of_the_sample_and_of_one_run_that_left_no_paper_unanswered():
    head, lines = outcomes()

    assert set(head) == {
        "record",
        "sample",
        "plan",
        "code",
        "parser_version",
        "section_char_limit",
        "began",
        "ended",
        "papers",
        "unanswered",
    }
    assert head["sample"] == {"file": SAMPLE.name, "sha256": sample().sha256}
    assert head["plan"] == sample().head["plan"] and head["code"] == sample().head["code"]
    assert (head["parser_version"], head["section_char_limit"]) == (PARSER, SECTION_CHAR_LIMIT)
    # `unanswered` is not an outcome: no draft is made while a paper is left with it.
    assert (head["papers"], head["unanswered"]) == (len(lines), 0) == (240, 0)
    assert tally(lines).unanswered == 0
    began, ended = moment(head["began"]), moment(head["ended"])
    assert moment(sample().head["drawn"]) <= began
    assert (f"{began:%Y-%m-%d %H:%M}", f"{ended:%H:%M}") == ("2026-11-27 14:11", "14:51")
    assert round((ended - began).total_seconds() / 60) == 40


def test_the_outcomes_have_a_line_for_every_paper_of_the_sample_in_its_order():
    drawn = [(p.archive, p.rank, p.arxiv_id, p.primary) for p in sample().papers]
    _, lines = outcomes()

    assert [(x["archive"], x["rank"], x["id"], x["primary"]) for x in lines] == drawn
    for line in lines:
        assert set(line) == OUTCOME_KEYS[line["outcome"]]
        assert IDENTIFIER.fullmatch(line["id"])
        if line["outcome"] == OK:
            for name in ("sections", "subsections", "chars", "largest"):
                assert type(line[name]) is int
            assert type(line["no_headings"]) is bool
            assert line["sections"] >= 1 and 0 < line["largest"] <= line["chars"]


def test_237_of_the_240_papers_were_split_and_three_were_not():
    _, lines = outcomes()
    found = tally(lines)

    assert {name: found.count(name) for name in (OK, TURNED_AWAY, NO_TEX)} == {
        OK: 237,
        TURNED_AWAY: 1,
        NO_TEX: 2,
    }
    assert found.count(OK) + found.count(TURNED_AWAY) + found.count(NO_TEX) == found.papers
    assert {archive: found.by_archive[archive].get(OK, 0) for archive in ARCHIVES} == {
        "hep-ph": 60,
        "hep-th": 60,
        "hep-ex": 58,
        "astro-ph": 59,
    }
    others = [line for line in lines if line["outcome"] != OK]
    assert [(x["archive"], x["rank"], x["id"], x["outcome"], x["branch"]) for x in others] == [
        ("hep-ex", 47, "2609.16276v2", TURNED_AWAY, "unfollowed_command"),
        ("hep-ex", 53, "2609.18799v1", NO_TEX, "not_tex"),
        ("astro-ph", 90, "2608.11253v1", NO_TEX, "not_tex"),
    ]
    for line in others:
        # The sentence is the source's or the parser's, and sorts into the kind it has.
        assert branch(line["outcome"], line["detail"]) == line["branch"]
    # The parser names the files it could not read, as the paper's source names them, and
    # the command that reads them: names of files, and no sentence of the paper.
    turned_away = others[0]["detail"]
    assert turned_away.startswith("text is missing, 6 file(s) could not be read: ")
    named = turned_away.partition(": ")[2].removesuffix(" ...").split(", ")
    assert len(named) == 5 and all(re.fullmatch(r"[\w/]+ \(\\import\)", each) for each in named)
    assert {line["detail"] for line in others[1:]} == {
        "the source is a PDF, PostScript or DVI file"
    }


def test_the_two_shapes_of_the_papers_that_were_split():
    _, lines = outcomes()
    split = [line for line in lines if line["outcome"] == OK]
    found = tally(lines)

    assert (found.no_headings, found.over_limit) == (7, 52)
    assert sum(1 for x in split if x["no_headings"] and x["largest"] > SECTION_CHAR_LIMIT) == 5
    by_archive = {
        archive: (
            sum(1 for x in split if x["archive"] == archive and x["no_headings"]),
            sum(1 for x in split if x["archive"] == archive and x["largest"] > SECTION_CHAR_LIMIT),
        )
        for archive in ARCHIVES
    }
    assert by_archive == {
        "hep-ph": (0, 8),
        "hep-th": (0, 16),
        "hep-ex": (5, 20),
        "astro-ph": (2, 8),
    }
    assert sum(x["chars"] for x in split) == 20_173_046
    assert max(x["chars"] for x in split) == 807_215


# --- the places ---------------------------------------------------------------------------


def test_the_places_are_of_the_sample_and_the_outcomes_and_of_the_same_commit():
    head = places_file()[0][0]

    assert set(head) == {
        "record",
        "input",
        "sample",
        "outcomes",
        "seed",
        "per_kind",
        "parser_version",
        "code",
        "made",
    }
    assert head["input"] == "sample"
    assert head["sample"] == {"file": SAMPLE.name, "sha256": sample().sha256}
    assert head["outcomes"] == {"file": OUTCOMES.name, "sha256": file_digest(OUTCOMES)}
    assert (head["seed"], head["per_kind"]) == (sample().head["seed"], PER_KIND) == (20261124, 12)
    assert head["parser_version"] == outcomes()[0]["parser_version"] == PARSER
    assert head["code"] == sample().head["code"]
    # The places were given out after the last paper had come back.
    assert moment(head["made"]) >= moment(outcomes()[0]["ended"])
    assert f"{moment(head['made']):%Y-%m-%d %H:%M}" == "2026-11-27 14:51"


def test_every_paper_that_was_split_has_one_place_and_no_other_paper_has_one():
    lines, found = places_file()
    papers, placed = of("paper"), found.places
    came_back = {line["id"]: line["outcome"] for line in outcomes()[1]}

    assert len(lines) == 1 + len(papers) + len(of("archive")) + len(placed)
    # The papers stand in the order of the walk: the first of every archive, then the second.
    assert [(x["archive"], x["rank"], x["id"]) for x in papers] == [
        (p.archive, p.rank, p.arxiv_id) for p in walk(sample().papers)
    ]
    assert {line["id"]: line["outcome"] for line in papers} == came_back
    assert sorted(place.paper for place in placed) == sorted(
        name for name, outcome in came_back.items() if outcome == OK
    )
    assert len(placed) == len({place.paper for place in placed}) == 237
    # And the places stand in that order as well, numbered from 1.
    order = {paper["id"]: at for at, paper in enumerate(papers)}
    assert [order[place.paper] for place in placed] == sorted(
        order[place.paper] for place in placed
    )
    by_paper = {paper["id"]: paper for paper in papers}
    for place in placed:
        paper = by_paper[place.paper]
        assert (place.archive, place.rank) == (paper["archive"], paper["rank"])
    for paper in papers:
        if paper["outcome"] == OK:
            assert set(paper) == {"record", "archive", "rank", "id", "outcome", "places", "search"}
        else:
            # A paper that was not split has no place, and was not looked up.
            assert set(paper) == {"record", "archive", "rank", "id", "outcome"}


def test_the_kinds_are_what_the_rule_gives_the_papers_in_the_order_of_the_walk():
    # The file says of every paper how many places of each kind it holds and whether a
    # search for its title found it. That is all the rule needs to give a paper its kind:
    # the first of the order that the paper has a place of and that its archive still
    # lacks. Which of its places of that kind a paper is given cannot be worked out again
    # here, since the sections of a paper are not in the repository.
    papers, placed = of("paper"), places_file()[1].places
    held = {
        paper["id"]: [
            Place(kind, f"{kind} {at}", 0, LEAST_CHARS)
            for kind, count in paper["places"].items()
            for at in range(count)
        ]
        for paper in papers
        if paper["outcome"] == OK
    }
    findable = {paper["id"] for paper in papers if paper.get("search", {}).get("findable")}
    given = assign(walk(sample().papers), held, findable, sample().head["seed"], PER_KIND)

    assert [(x.archive, x.rank, x.paper, x.kind) for x in given] == [
        (x.archive, x.rank, x.paper, x.kind) for x in placed
    ]
    for place in placed:
        own = NAMED_FIRST if place.kind == SEARCH_FIRST else place.kind
        assert held[place.paper] and any(each.kind == own for each in held[place.paper])
    # Every paper that was split holds a named_first place, so none was left without one.
    assert all(any(each.kind == NAMED_FIRST for each in own) for own in held.values())
    have = {
        kind: sum(1 for own in held.values() if any(each.kind == kind for each in own))
        for kind in (LATER_PIECE, APPENDIX, OWN_TEXT, NAMED_FIRST)
    }
    assert have == {LATER_PIECE: 41, APPENDIX: 122, OWN_TEXT: 115, NAMED_FIRST: 237}


def test_twelve_places_of_a_kind_for_an_archive_and_what_is_missing_goes_to_named_first():
    placed = places_file()[1].places
    filled = {
        archive: Counter(place.kind for place in placed if place.archive == archive)
        for archive in ARCHIVES
    }

    assert {archive: [filled[archive][kind] for kind in KINDS] for archive in ARCHIVES} == {
        "hep-ph": [7, 12, 12, 12, 17],
        "hep-th": [12, 12, 12, 12, 12],
        "hep-ex": [12, 12, 12, 12, 10],
        "astro-ph": [6, 12, 12, 12, 17],
    }
    assert [sum(filled[archive][kind] for archive in ARCHIVES) for kind in KINDS] == [
        37,
        48,
        48,
        48,
        56,
    ]
    split = tally(outcomes()[1]).by_archive
    for line in of("archive"):
        own = filled[line["archive"]]
        assert line["filled"] == {kind: own[kind] for kind in KINDS}
        assert line["missing"] == {kind: max(0, PER_KIND - own[kind]) for kind in KINDS}
        # What the other kinds are short of goes to named_first, as far as the archive has
        # papers left: every paper that was split holds a named_first place.
        others = sum(own[kind] for kind in KINDS if kind != NAMED_FIRST)
        short = (len(KINDS) - 1) * PER_KIND - others
        assert own[NAMED_FIRST] == min(PER_KIND + short, split[line["archive"]][OK] - others)
    assert [line["archive"] for line in of("archive")] == list(ARCHIVES)


def test_a_place_is_a_part_of_a_thousand_to_twenty_thousand_characters():
    for place in places_file()[1].places:
        assert 0 <= place.start < place.end
        assert LEAST_CHARS <= place.chars <= SECTION_CHAR_LIMIT
        # A later piece begins behind what the first call returns, and no other place does.
        assert (place.kind == LATER_PIECE) == (place.start > 0)
        if place.kind == OWN_TEXT:
            # The text of a section in front of its first subsection.
            assert "." not in place.section
    for line in of("place"):
        assert set(line) == {
            "record",
            "number",
            "archive",
            "rank",
            "paper",
            "kind",
            "section",
            "start",
            "end",
            "chars",
        }
        assert line["chars"] == line["end"] - line["start"]
        # An identifier of the parser: a number, a letter of an appendix, or "u" and a number.
        assert re.fullmatch(r"(?:u?\d+|[A-Z])(?:\.u?\d+)?", line["section"])


def test_a_search_for_its_title_found_220_of_the_237_papers():
    looked = {paper["id"]: paper["search"] for paper in of("paper") if "search" in paper}
    placed = places_file()[1].places

    assert len(looked) == 237
    for search in looked.values():
        assert set(search) == {"findable", "latest", "rank", "problem"}
        # arXiv answered every look-up.
        assert search["problem"] is None
        assert search["findable"] == (search["latest"] is True and search["rank"] is not None)
    found = [search for search in looked.values() if search["findable"]]
    assert len(found) == 220
    assert Counter(search["rank"] for search in found) == {1: 216, 2: 3, 5: 1}
    # The version of the list was no longer the latest one for 4 papers, and for 13 the
    # search did not list the paper among its first five results.
    assert sum(1 for search in looked.values() if search["latest"] is False) == 4
    assert sum(1 for x in looked.values() if x["latest"] and not x["findable"]) == 13
    archive = {paper["id"]: paper["archive"] for paper in of("paper")}
    assert Counter(archive[name] for name, x in looked.items() if x["findable"]) == {
        "hep-ph": 53,
        "hep-th": 57,
        "hep-ex": 53,
        "astro-ph": 57,
    }
    # A paper is asked about by its title only when the search found it.
    assert all(looked[place.paper]["findable"] for place in placed if place.kind == SEARCH_FIRST)


# --- the verdicts -------------------------------------------------------------------------


def test_the_verdicts_are_on_the_82_drafts_that_the_places_kept():
    lines, found = review()
    head, verdicts = lines[0], lines[1:]
    placed = {place.number: place for place in places_file()[1].places}

    assert set(head) == {
        "record",
        "places",
        "drafts",
        "sift",
        "key",
        "sheet",
        "read",
        "accepted",
        "rejected",
        "reasons",
    }
    assert head["places"] == {"file": PLACES.name, "sha256": file_digest(PLACES)}
    # The record of the generator, that of the filters, the sheet and its key hold paper
    # text and are not in the repository: the verdicts name them by name and digest.
    assert {name: head[name]["file"] for name in ("drafts", "sift", "key", "sheet")} == {
        "drafts": "drafts.jsonl",
        "sift": "sift.jsonl",
        "key": "review-key.jsonl",
        "sheet": "review-sheet.csv",
    }
    for name in ("drafts", "sift", "key", "sheet"):
        assert set(head[name]) == {"file", "sha256"} and DIGEST.fullmatch(head[name]["sha256"])
    assert (head["accepted"], head["rejected"]) == (48, 34)
    assert head["reasons"] == {
        "ambiguous": 0,
        "not_the_passage": 0,
        "key_or_note": 15,
        "not_running_text": 1,
        "other": 18,
    }
    assert list(head["reasons"]) == list(REASONS)
    # The sheet was read back after the places had been given out, the day after.
    assert f"{moment(head['read']):%Y-%m-%d %H:%M}" == "2026-11-28 06:57"
    assert moment(head["read"]) > moment(places_file()[0][0]["made"])

    assert len(verdicts) == len(found) == 82
    assert [line["number"] for line in verdicts] == sorted(found)
    for line in verdicts:
        # A place, a verdict and the kind of a reason: no question, no passage and no note.
        assert set(line) == {
            "record",
            "number",
            "draft",
            "paper",
            "kind",
            "verdict",
            "why_rejected",
        }
        place = placed[line["number"]]
        assert (line["paper"], line["kind"]) == (place.paper, place.kind)
        assert found[line["number"]] == (line["verdict"], line["why_rejected"] or "", line["draft"])
        assert (line["verdict"] == REJECT) == (line["why_rejected"] in REASONS)
        assert line["verdict"] in (ACCEPT, REJECT) and 1 <= line["draft"] <= MAX_DRAFTS
    said = Counter(line["verdict"] for line in verdicts)
    assert (said[ACCEPT], said[REJECT]) == (head["accepted"], head["rejected"])
    why = Counter(line["why_rejected"] for line in verdicts if line["verdict"] == REJECT)
    assert {name: why[name] for name in REASONS} == head["reasons"]


# --- what became of every place -----------------------------------------------------------


def test_the_summary_names_the_records_the_texts_the_verdicts_and_the_question_file():
    head, verdicts = summary()[0], review()[0][0]
    said = flat(PRE_REGISTRATION)

    assert set(head) == {
        "record",
        "places",
        "drafts",
        "sift",
        "review",
        "questions",
        "per_cell",
        "parser_version",
        "code",
        "made",
    }
    assert head["places"] == verdicts["places"]
    # The records are the ones whose drafts were reviewed, made by the texts that the
    # pre-registration names by their digests.
    assert head["drafts"] == {
        **verdicts["drafts"],
        "drafter_version": DRAFTER,
        "texts_sha256": head["drafts"]["texts_sha256"],
    }
    assert head["sift"] == {
        **verdicts["sift"],
        "sift_version": SIFTER,
        "texts_sha256": head["sift"]["texts_sha256"],
    }
    assert head["drafts"]["texts_sha256"].startswith(DRAFTER_TEXTS)
    assert head["sift"]["texts_sha256"].startswith(SIFTER_TEXTS)
    assert f"name `{DRAFTER}` (SHA-256 beginning `{DRAFTER_TEXTS}`)" in said
    assert f"name `{SIFTER}` (SHA-256 beginning `{SIFTER_TEXTS}`)" in said
    assert head["review"] == {"file": REVIEW.name, "sha256": file_digest(REVIEW)}
    assert head["questions"] == {
        "file": QUESTIONS.name,
        "sha256": file_digest(QUESTIONS),
        "questions": 42,
    }
    assert (head["per_cell"], head["parser_version"]) == (PER_CELL, PARSER) == (4, "5")
    # No file the repository keeps was changed, so the commit names the code.
    assert head["code"]["commit"].startswith(ASSEMBLED) and head["code"]["modified"] is False
    made, read = moment(head["made"]), moment(verdicts["read"])
    assert read <= made and made - read < timedelta(minutes=1)


def test_the_pre_registration_names_the_question_file_that_the_summary_names():
    # tests/test_archives_plan.py holds the two places of the digest against the file.
    # Here: the digest in the text is the one in the first line of the summary, so the
    # questions that are run are the ones this folder accounts for.
    text = PRE_REGISTRATION.read_text(encoding="utf-8")
    digest = summary()[0]["questions"]["sha256"]

    assert DIGEST.findall(text) == [digest, digest]
    assert f"before any run: `{digest}`." in text
    assert f"--out results/runs/archives --repeats 1 --questions-sha256 {digest}\n" in text


def test_the_summary_has_a_line_for_every_place_that_says_what_became_of_it():
    placed, found = places_file()[1].places, review()[1]
    lines = candidates()

    assert len(lines) == len(placed) == 237
    for line, place in zip(lines, placed, strict=True):
        assert set(line) == CANDIDATE_KEYS
        assert {name: line[name] for name in place.as_line()} == place.as_line() | {
            "record": "candidate"
        }
        drafts = line["drafts"]
        # The generator said that the part holds nothing to ask about, or drafted up to
        # three questions; no reply was neither.
        assert line["problem"] is None and line["draft"] in (DRAFT, NOTHING)
        assert (line["draft"] == NOTHING) == (not drafts) and len(drafts) <= MAX_DRAFTS
        assert [draft["draft"] for draft in drafts] == list(range(1, len(drafts) + 1))
        for draft in drafts:
            assert set(draft) == DRAFT_KEYS and set(draft["failed_checks"]) <= set(CHECKS)
            # A draft that failed a check was put to no filter, and every other to both.
            asked = not draft["failed_checks"]
            assert (draft["without_the_paper"] is not None) == asked
            assert (draft["from_the_passage"] is not None) == asked
        # The place keeps its first draft that passed everything.
        passing = [draft["draft"] for draft in drafts if passes(draft)]
        assert line["kept"] == bool(passing)
        assert line["kept_draft"] == (passing[0] if passing else None)
        # The draft that was kept is the one the review judged, and no other was judged.
        if line["kept"]:
            verdict, why, judged = found[line["number"]]
            assert (line["verdict"], line["why_rejected"] or "") == (verdict, why)
            assert judged == line["kept_draft"]
        else:
            assert line["number"] not in found
            assert line["verdict"] is None and line["why_rejected"] is None
        # Only an accepted draft became a question.
        asked_about = line["question"] is not None
        assert asked_about == (line["asked_as"] is not None) == (line["fill"] is not None)
        assert not asked_about or line["verdict"] == ACCEPT
        assert set(line["usage"]) == USAGE_KEYS and line["cost"] > 0


def test_the_counts_of_the_summary_are_those_of_its_lines():
    lines, found = summary(), candidates()
    cells = [line for line in lines if line["record"] == "cell"]
    reasons, total = lines[-2], lines[-1]

    assert len(lines) == 1 + len(found) + len(cells) + 2
    assert (reasons["record"], total["record"]) == ("reasons", "total")
    assert [(cell["archive"], cell["kind"]) for cell in cells] == [
        (archive, kind) for archive in ARCHIVES for kind in KINDS
    ]
    for cell in cells:
        own = [x for x in found if (x["archive"], x["kind"]) == (cell["archive"], cell["kind"])]
        asked = [
            x for x in found if (x["archive"], x["asked_as"]) == (cell["archive"], cell["kind"])
        ]
        fills = sum(1 for x in asked if x["fill"])
        assert {name: cell[name] for name in counts_of(own)} == counts_of(own)
        assert (cell["questions"], cell["fills"]) == (len(asked), fills)
        assert cell["short"] == max(0, PER_CELL - (len(asked) - fills))
    assert (
        {name: total[name] for name in counts_of(found)}
        == counts_of(found)
        == {
            "places": 237,
            "with_drafts": 107,
            "drafts": 211,
            "nothing_to_ask": 130,
            "no_draft": 0,
            "passed_checks": 166,
            "right_without_the_paper": 28,
            "right_from_the_passage": 163,
            "kept": 82,
            "kept_by_draft": {"1": 73, "2": 8, "3": 1},
            "accepted": 48,
            "rejected": 34,
        }
    )
    assert (total["questions"], total["fills"]) == (42, 3)

    drafts = [draft for line in found for draft in line["drafts"]]
    assert Counter(len(line["drafts"]) for line in found) == {0: 130, 1: 34, 2: 42, 3: 31}
    assert sum(1 for draft in drafts if passes(draft)) == 135
    # No draft was answered right without the paper and wrong from its passage.
    assert sum(1 for x in drafts if x["from_the_passage"] not in (RIGHT, None)) == 3
    assert not [
        1 for x in drafts if x["without_the_paper"] == RIGHT and x["from_the_passage"] != RIGHT
    ]
    assert sum(1 for line in found if line["draft"] == DRAFT and not line["kept"]) == 25
    failed = {name: sum(1 for x in drafts if name in x["failed_checks"]) for name in CHECKS}
    assert reasons["failed_checks"] == failed
    assert {name: count for name, count in failed.items() if count} == {
        "anchor_once": 1,
        "key_in_anchor": 14,
        "not_in_listing": 10,
        "not_elsewhere": 26,
        "question_clean": 5,
        "running_text": 2,
        "two_digits": 4,
    }
    assert sum(1 for x in drafts if x["failed_checks"]) == 45 and sum(failed.values()) == 62
    assert reasons["no_draft"] == {}
    assert reasons["rejected"] == review()[0][0]["reasons"]


def test_the_cost_is_what_the_usage_comes_to_at_the_list_prices():
    found, total = candidates(), summary()[-1]
    price = PRICES["claude-sonnet-5-5"]
    used = {name: sum(line["usage"][name] for line in found) for name in USAGE_KEYS}

    assert total["usage"] == used
    assert (used["input_tokens"], used["output_tokens"]) == (11_420_132, 297_201)
    # Neither the generator nor the filters ask with a cache.
    assert used["cache_creation_input_tokens"] == used["cache_read_input_tokens"] == 0
    cost = (used["input_tokens"] * price["input"] + used["output_tokens"] * price["output"]) / 1e6
    assert total["cost"] == pytest.approx(cost) == pytest.approx(sum(x["cost"] for x in found))
    assert f"{total['cost']:.2f}" == "25.81"


# --- the questions ------------------------------------------------------------------------


def test_the_questions_are_what_the_rule_makes_of_the_accepted_drafts():
    found = candidates()
    accepted = [line for line in found if line["verdict"] == ACCEPT]
    asked = [line for line in found if line["question"]]
    names = ("number", "archive", "rank", "paper", "kind", "section", "start", "end")
    chosen = choose([Placed(*(line[name] for name in names)) for line in accepted], PER_CELL)

    # For every kind and archive the first four accepted drafts in the order of the walk,
    # and then accepted drafts of named_first for the places a kind was short of.
    assert [(x.place.number, x.kind, x.fill) for x in chosen] == [
        (line["number"], line["asked_as"], line["fill"]) for line in asked
    ]
    assert [line["question"] for line in asked] == [f"archives-{at:02d}" for at in range(1, 43)]
    # A draft of the evaluation is asked as the kind of its place.
    assert all(line["asked_as"] == line["kind"] for line in asked)
    assert by_kind_and_archive(asked) == {
        "hep-ph": [2, 0, 2, 0, 2],
        "hep-th": [1, 3, 0, 0, 1],
        "hep-ex": [4, 2, 2, 3, 4],
        "astro-ph": [2, 3, 0, 4, 7],
    }
    assert by_kind_and_archive(accepted) == {
        "hep-ph": [2, 0, 2, 0, 2],
        "hep-th": [1, 3, 0, 0, 1],
        "hep-ex": [7, 2, 2, 3, 4],
        "astro-ph": [2, 3, 0, 7, 7],
    }
    # Six accepted drafts are no question: their kind and archive had four before them.
    left = Counter((x["archive"], x["kind"]) for x in accepted if not x["question"])
    assert left == {("hep-ex", LATER_PIECE): 3, ("astro-ph", SEARCH_FIRST): 3}
    # Three accepted drafts of named_first take places that other kinds were short of, all
    # in astro-ph: no other archive had an accepted named_first draft left over.
    assert [(x["archive"], x["kind"], x["question"]) for x in found if x["fill"]] == [
        ("astro-ph", NAMED_FIRST, "archives-36"),
        ("astro-ph", NAMED_FIRST, "archives-39"),
        ("astro-ph", NAMED_FIRST, "archives-40"),
    ]
    empty = [
        (archive, kind)
        for archive, row in by_kind_and_archive(asked).items()
        for kind, count in zip(KINDS, row, strict=True)
        if not count
    ]
    assert empty == [
        ("hep-ph", APPENDIX),
        ("hep-ph", SEARCH_FIRST),
        ("hep-th", OWN_TEXT),
        ("hep-th", SEARCH_FIRST),
        ("astro-ph", OWN_TEXT),
    ]


def test_a_question_is_the_line_that_its_place_makes():
    questions = load_questions(QUESTIONS)
    asked = {line["question"]: line for line in candidates() if line["question"]}

    assert [question.id for question in questions] == list(asked) and len(questions) == 42
    for question in questions:
        line = asked[question.id]
        assert question.type == line["asked_as"]
        assert question.gold_papers == (line["paper"],)
        (evidence,) = question.evidence
        assert (question.need, evidence.arxiv_id, evidence.section_id) == (
            "all",
            line["paper"],
            line["section"],
        )
        assert question.notes == {
            "kind": line["asked_as"],
            "place": f"{line['section']} {line['start']}-{line['end']}",
            "drafted": DRAFTER,
            "candidate": str(line["number"]),
            "draft": str(line["kept_draft"]),
            "archive": line["archive"],
        }
        # What the checks hold a draft to and a file can show without the paper (Section 5).
        assert ANCHOR_CHARS[0] <= len(evidence.anchor) <= ANCHOR_CHARS[1]
        assert len(question.question) <= QUESTION_CHARS
        assert len(question.reference_answer) <= ANSWER_CHARS
        assert question.expect_found is True and question.abstract_sufficient is False
        # A key of numbers and phrases alone, so the rule says right or wrong of every answer.
        assert question.answer_key and set(question.answer_key) <= {"numbers", "phrases"}
        named = re.findall(r"\d{4}\.\d{5}(?:v\d+)?", question.question)
        if question.type == SEARCH_FIRST:
            # The paper is named by its title, and the question holds no identifier.
            assert not named and 'he paper titled "' in question.question
        else:
            assert named == [line["paper"]] and f"arXiv:{line['paper']}" in question.question
    # Every question is about a paper of its own.
    assert len({question.gold_papers for question in questions}) == len(questions)
    by_draft = Counter(question.notes["draft"] for question in questions)
    assert by_draft == {"1": 38, "2": 4}


def test_what_42_questions_can_show_of_h2_is_what_the_interval_gives():
    # Section 13 of the pre-registration gives the bound for 80 to 30 questions, and the
    # count of the questions was not known then. For the 42 there are: if the layouts
    # answer alike but for some questions, half of them right in staged only and half in
    # flat only, "not worse by more than 10 points" comes out for at most four of them.
    questions = len(load_questions(QUESTIONS))

    def says_not_worse(differing):
        half = differing // 2
        return reading(*adjusted_wald(half, half, questions)[1:], 0.10) == NOT_WORSE

    assert [differing for differing in range(0, 12, 2) if says_not_worse(differing)] == [0, 2, 4]
    low, high = adjusted_wald(2, 2, questions)[1:]
    assert (round(100 * low, 1), round(100 * high, 1)) == (-10.0, 10.0) and low > -0.10


def test_what_is_listed_under_deviations_is_what_the_files_say():
    # Section 16 of the pre-registration is not held by a digest, so that it can be
    # written to. Its numbers are held here.
    text = PRE_REGISTRATION.read_text(encoding="utf-8")
    listed = " ".join(text.partition("\n## 16. Deviations\n")[2].split())
    kept = sum(1 for line in candidates() if line["kept"])
    split = [line for line in outcomes()[1] if line["outcome"] == OK]
    twice = 2 * SECTION_CHAR_LIMIT

    assert listed.count("**2026-11-28, Section") == 2 and "None so far" not in listed
    # The day is the one on which the sheet was read back and the questions were made.
    assert moment(review()[0][0]["read"]).date().isoformat() == "2026-11-28"
    # Each entry names the section it is about, and the sections it leans on.
    mentions = {
        "**2026-11-28, Section 7: who read the drafts.**": "Review by the maintainer",
        "Section 7 has the maintainer alone read the drafts": "Review by the maintainer",
        "was given the sheet as Section 7 describes it": "Review by the maintainer",
        "no specialist of all of them (Section 15)": "Known limits, stated before the runs",
        "where Section 15 says that a reviewer who has the passage alone may accept": (
            "Known limits, stated before the runs"
        ),
        "**2026-11-28, Section 3: a rule that it does not state.**": "Places and kinds",
        "Section 3 says where a `later_piece` passage stands": "Places and kinds",
    }
    for mention, heading in mentions.items():
        assert mention in listed, mention
        (number,) = re.findall(r"Section (\d+)", mention)
        assert headings()[number] == heading, mention
    assert "a reviewer who has the passage alone may accept such a draft" in flat(PRE_REGISTRATION)
    assert "is no specialist of all four archives" in flat(PRE_REGISTRATION)
    assert f"read the {kept} rows of the sheet and wrote a verdict and a note for each" in listed
    assert "it knew the text that tells the generator what to ask (Section 4)" in listed
    assert headings()["4"] == "Drafting"
    assert f"and {kept} rows are many" in listed
    assert f"every rejection names one of the {WORDS[len(REASONS)]} kinds" in listed
    # Two calls return at most twice the limit of one, so a piece that is larger has text
    # behind its second piece.
    beyond = sum(1 for line in split if line["largest"] > twice)
    assert f"from at most {twice:,} characters into a section or subsection on" in listed
    assert (
        f"Of the {len(split)} papers that were split, {beyond} have a piece of more than "
        f"{twice:,} characters" in listed
    )
    assert (len(split), beyond) == (237, 19)
    # No place reaches behind a second piece: a later piece ends within twice the limit.
    assert all(place.end <= twice for place in places_file()[1].places)


# --- no text of a paper -------------------------------------------------------------------


def test_the_files_of_the_folder_hold_no_text_of_a_paper():
    # The questions are in eval_data/, with their anchors and the titles that seven of
    # them name. Nothing of them is in a file of this folder: not a question, not an
    # anchor, not a reference answer, not a note.
    questions = load_questions(QUESTIONS)
    for path in (SAMPLE, OUTCOMES, PLACES, REVIEW, CANDIDATES):
        text = path.read_text(encoding="utf-8")
        for question in questions:
            assert question.question not in text and question.reference_answer not in text
            assert question.accept_note not in text
            assert all(evidence.anchor not in text for evidence in question.evidence)
    # A line of the summary holds names of the code and numbers, and no free text.
    for line in candidates():
        assert IDENTIFIER.fullmatch(line["paper"]) and line["kind"] in KINDS
        assert line["archive"] in ARCHIVES
        assert line["verdict"] in (ACCEPT, REJECT, None)
        assert line["why_rejected"] in (*REASONS, None)
        assert line["asked_as"] in (*KINDS, None) and line["fill"] in (True, False, None)
        assert line["question"] is None or re.fullmatch(r"archives-\d\d", line["question"])
        for draft in line["drafts"]:
            assert draft["without_the_paper"] in ("right", "wrong", None)
            assert draft["from_the_passage"] in ("right", "wrong", None)
    lines, _ = read_lines(SAMPLE, "sample")
    for line in lines[1:]:
        if line["record"] == "paper":
            assert set(line) == {"record", "archive", "rank", "id", "primary", "sha256"}
            assert IDENTIFIER.fullmatch(line["id"]) and DIGEST.fullmatch(line["sha256"])
        else:
            assert set(line) == {"record", "archive", "listed", "primary", "drawn"}


# --- what is said of the files ------------------------------------------------------------

README = HERE / "README.md"


def part(heading: str) -> str:
    """One part of the README of the folder, from its heading to the next."""
    text = README.read_text(encoding="utf-8")
    found = re.search(
        rf"^## {re.escape(heading)}\n.*?(?=^## |\Z)", text, flags=re.MULTILINE | re.DOTALL
    )
    assert found, heading
    return found.group(0)


def said_in(heading: str) -> str:
    """That part with every run of white space as one blank."""
    return " ".join(part(heading).split())


def rows(heading: str) -> list[str]:
    """The rows of the tables of a part."""
    return [line.strip() for line in part(heading).splitlines() if line.lstrip().startswith("|")]


def row(*cells) -> str:
    return "| " + " | ".join(str(cell) for cell in cells) + " |"


def hour(text: str) -> str:
    return f"{moment(text):%H:%M}"


def test_the_readme_of_the_folder_says_what_the_files_are():
    text = README.read_text(encoding="utf-8")
    head = " ".join(text.partition("\n## ")[0].split())
    found = tally(outcomes()[1])

    # Every file of the folder has its row, and no row names a file that is not there.
    listed = re.findall(r"^\| `([a-z0-9-]+\.jsonl)` \|", text, flags=re.MULTILINE)
    assert sorted(listed) == sorted(path.name for path in HERE.glob("*.jsonl"))
    archives = ", ".join(ARCHIVES[:-1]) + f" and {ARCHIVES[-1]}"
    assert (
        f"the {found.papers} papers of the plan `{plan().name}`: places {plan().first} to "
        f"{plan().last} of {archives} in the order of the survey" in head
    )
    assert f"what came back for each of the {found.papers} papers when `survey.run`" in head
    assert f"each of the {found.count(OK)} papers that were split" in head
    kept = sum(1 for line in candidates() if line["kept"])
    assert f"the verdicts on the {kept} drafts that the checks and the filters left" in head
    assert f"what became of every one of the {len(candidates())} places" in head
    asked = len(load_questions(QUESTIONS))
    assert f"The questions are in `eval_data/{QUESTIONS.name}`, {asked} of them." in head
    # The days of the files are those of their first lines.
    assert {moment(sample().head["drawn"]).date().isoformat()} == {"2026-11-27"}
    assert {moment(review()[0][0]["read"]).date(), moment(summary()[0]["made"]).date()} == {
        moment("2026-11-28T00:00:00+00:00").date()
    }
    assert "worked them out from `../survey/population.jsonl` on 2026-11-27" in head
    assert "read them off the sheet on 2026-11-28" in head
    assert "written by `drafting.assemble` on 2026-11-28 beside the question file" in head
    assert "No file here holds a title, an abstract or text of a paper." in head
    assert "Nothing here is a result: no question has been put to the server yet." in head
    assert "All times are UTC." in head


def test_the_readme_says_how_the_papers_came_back():
    heading = "The papers, and how they came back"
    said, table = said_in(heading), rows(heading)
    head, lines = outcomes()
    found = tally(lines)
    split = [line for line in lines if line["outcome"] == OK]

    assert (
        "The sample, the outcomes and the places were made on the maintainer's computer on "
        f"2026-11-27 by `{PLANNED}`, the commit that brought the plan and the pre-registration, "
        "with no file of the repository changed" in said
    )
    assert f"drew the sample at {hour(sample().head['drawn'])} from the list on disk" in said
    minutes = round((moment(head["ended"]) - moment(head["began"])).total_seconds() / 60)
    assert (
        f"then went through the {found.papers} papers once, from {hour(head['began'])} to "
        f"{hour(head['ended'])}, {minutes} minutes, and left no paper unanswered" in said
    )
    assert found.unanswered == 0
    for archive in (*ARCHIVES, "all"):
        own = [line for line in lines if archive in (line["archive"], "all")]
        counts = [sum(1 for x in own if x["outcome"] == name) for name in (OK, TURNED_AWAY, NO_TEX)]
        assert row(archive, len(own), *counts) in table
        assert len(own) == sum(counts)
        shaped = [x for x in own if x["outcome"] == OK]
        assert (
            row(
                archive,
                len(shaped),
                sum(1 for x in shaped if x["no_headings"]),
                sum(1 for x in shaped if x["largest"] > SECTION_CHAR_LIMIT),
            )
            in table
        )
    assert len(table) == 2 * (2 + len(ARCHIVES) + 1)
    assert f"| With a piece of more than {SECTION_CHAR_LIMIT:,} characters |" in part(heading)
    away, *no_tex = [line for line in lines if line["outcome"] != OK]
    assert (
        f"The paper that the parser turned away is `{away['id']}` of {away['archive']}: its "
        "text is read with `\\import`, a command the parser does not follow "
        f"(`{away['branch']}`). The line keeps the sentence of the parser, which names five of "
        "the six files it could not read." in said
    )
    assert (
        "The two papers without a TeX source, "
        + " and ".join(f"`{x['id']}` of {x['archive']}" for x in no_tex)
        + ", are a PDF, PostScript or DVI file at arXiv (`not_tex`)."
        in said
    )
    assert {x["branch"] for x in no_tex} == {"not_tex"} and len(no_tex) == 2
    assert found.count("not_found") == found.count("unexpected") == 0
    assert "No paper was missing from arXiv (`not_found`), and none came back in a way" in said
    both = sum(1 for x in split if x["no_headings"] and x["largest"] > SECTION_CHAR_LIMIT)
    assert both == 5 and "Five papers are both." in said
    assert f"split by parser `{head['parser_version']}`" in said


def test_the_readme_says_which_places_were_given_out():
    heading = "The places"
    said, table = said_in(heading), rows(heading)
    papers, placed = of("paper"), places_file()[1].places
    made = places_file()[0][0]["made"]

    assert (
        f"`drafting.assign` began at {hour(made)}, after the last paper had come back, and gave "
        f"out {len(placed)} places: one for each paper that was split" in said
    )
    counts = by_kind_and_archive([place.as_line() for place in placed])
    for archive in ARCHIVES:
        assert row(archive, *counts[archive], sum(counts[archive])) in table
    sums = [sum(counts[archive][at] for archive in ARCHIVES) for at in range(len(KINDS))]
    assert row("all", *sums, len(placed)) in table
    assert table[0] == row("Archive", *(f"`{kind}`" for kind in KINDS), "All")
    assert len(table) == 2 + len(ARCHIVES) + 1
    later = KINDS.index(LATER_PIECE)
    assert (
        f"The papers of hep-ph hold {counts['hep-ph'][later]} places of `later_piece` and those "
        f"of astro-ph {counts['astro-ph'][later]}, so {PER_KIND - counts['hep-ph'][later]} and "
        f"{PER_KIND - counts['astro-ph'][later]} more went to `named_first` there; in hep-ex, "
        f"{sum(counts['hep-ex'])} papers were split, which left {counts['hep-ex'][-1]} for "
        "`named_first`." in said
    )
    # Where every paper that holds a later piece was given it: what the papers of hep-ph and
    # of astro-ph hold is what they were given.
    held = {
        archive: sum(
            1 for x in papers if x["archive"] == archive and LATER_PIECE in x.get("places", {})
        )
        for archive in ARCHIVES
    }
    assert (held["hep-ph"], held["astro-ph"]) == (
        counts["hep-ph"][later],
        counts["astro-ph"][later],
    )
    have = {
        kind: sum(1 for paper in papers if kind in paper.get("places", {}))
        for kind in (NAMED_FIRST, APPENDIX, OWN_TEXT, LATER_PIECE)
    }
    assert have[NAMED_FIRST] == len(placed)
    assert (
        f"Of the {len(placed)} papers, every one holds a `named_first` place, {have[APPENDIX]} "
        f"an `appendix` place, {have[OWN_TEXT]} an `own_text` place and {have[LATER_PIECE]} a "
        "`later_piece` place." in said
    )
    looked = [paper["search"] for paper in papers if "search" in paper]
    stale = sum(1 for search in looked if search["latest"] is False)
    ranks = Counter(search["rank"] for search in looked if search["findable"])
    missed = sum(1 for search in looked if search["latest"] and not search["findable"])
    assert all(search["problem"] is None for search in looked)
    assert (
        f"arXiv answered the look-up of every paper. For {stale} papers the version of the list "
        f"was no longer the latest one. Of the other {len(looked) - stale}, a search for the "
        f"title listed {sum(ranks.values())} among its first five results ({ranks[1]} as the "
        f"first, {ranks[2]} as the second and {ranks[5]} as the fifth) and {missed} not." in said
    )
    assert set(ranks) == {1, 2, 5}
    assert "The places are given out once (Section 3 of the pre-registration)" in said


def test_the_readme_says_what_the_checks_and_the_filters_left():
    heading = "The drafts, the checks and the filters"
    said, table = said_in(heading), rows(heading)
    found, total = candidates(), summary()[-1]
    drafts = [draft for line in found for draft in line["drafts"]]
    with_drafts = Counter(len(line["drafts"]) for line in found)

    assert (
        f"{total['nothing_to_ask']} replies said that the part holds nothing to ask about. "
        f"{total['with_drafts']} held drafts, {total['drafts']} in all ({with_drafts[1]} places "
        f"with one, {with_drafts[2]} with two and {with_drafts[3]} with three). No reply was "
        "anything else." in said
    )
    assert total["no_draft"] == 0
    failing = sum(1 for draft in drafts if draft["failed_checks"])
    failures = sum(len(draft["failed_checks"]) for draft in drafts)
    assert (
        f"{total['passed_checks']} of the {total['drafts']} drafts passed every check of a "
        f"program. The {failing} others failed {failures} checks between them" in said
    )
    # A row for every check that a draft failed, under the number that Section 5 gives it.
    failed = {name: sum(1 for x in drafts if name in x["failed_checks"]) for name in CHECKS}
    shown = {}
    for line in table[2:]:
        number, name, count = re.fullmatch(r"\| (\d+): .* \(`(\w+)`\) \| (\d+) \|", line).groups()
        assert CHECKS[int(number) - 1] == name
        shown[name] = int(count)
    assert shown == {name: count for name, count in failed.items() if count}
    assert list(shown.values()) == sorted(shown.values(), reverse=True)
    wrong = sum(1 for draft in drafts if draft["from_the_passage"] not in (RIGHT, None))
    assert (
        f"Each of the {total['passed_checks']} was put to the model twice. "
        f"{total['right_without_the_paper']} were answered right without the paper, and {wrong} "
        "were not answered right from their passage; no draft was both. "
        f"{sum(1 for draft in drafts if passes(draft))} drafts passed everything." in said
    )
    keeps = total["kept_by_draft"]
    none = sum(1 for line in found if line["draft"] == DRAFT and not line["kept"])
    assert (
        f"{total['kept']} places keep a draft, the first of their reply that passed everything: "
        f"for {keeps['1']} places that is their first draft, for {keeps['2']} their second and "
        f"for {keeps['3']} their third. {none} places had drafts and keep none." in said
    )
    used = total["usage"]
    assert (
        f"come to {used['input_tokens']:,} input tokens and {used['output_tokens']:,} output "
        f"tokens: ${total['cost']:.2f}, worked out at the list prices of `eval/report.py`" in said
    )


def test_the_readme_says_how_the_review_went():
    heading = "The review"
    said, table = said_in(heading), rows(heading)
    found, head = candidates(), review()[0][0]
    kept = [line for line in found if line["kept"]]

    assert f"The {len(kept)} drafts that were kept were put on a sheet" in said
    # Who did what cannot be held against a file. The numbers of the sentences can.
    assert (
        "was given the sheet, without the papers and without the file that "
        "says of which kind a place is, and wrote a verdict and a note for every row as a "
        "draft. It knew the text that tells the generator what to ask. "
        f"The maintainer then held each of the {len(kept)} rows against its passage and "
        "settled the verdict" in said
    )
    assert "so this is listed there under Deviations, with its reason" in said
    assert f"read the sheet back at {hour(head['read'])} on 2026-11-28" in said
    for archive in (*ARCHIVES, "all"):
        own = [line for line in found if archive in (line["archive"], "all")]
        assert (
            row(
                archive,
                len(own),
                sum(1 for x in own if x["draft"] == DRAFT),
                sum(1 for x in own if x["kept"]),
                sum(1 for x in own if x["verdict"] == ACCEPT),
                sum(1 for x in own if x["verdict"] == REJECT),
            )
            in table
        )
    assert len(table) == 2 + len(ARCHIVES) + 1
    why = head["reasons"]
    assert (
        f"Of the {head['rejected']} rejections, {why['key_or_note']} say that the key or the "
        "note does not fit the reference answer (`key_or_note`), "
        f"{why['not_running_text']} that the passage is no running text (`not_running_text`), "
        f"and {why['other']} give another reason in a note (`other`). None says that the "
        "question reads more than one way, or that the reference answer is not what the "
        "passage says." in said
    )
    assert why["ambiguous"] == why["not_the_passage"] == 0
    # The notes are with the sheet, outside the repository: what is said of them is not
    # held against anything here but the count of the rejections they belong to.
    assert f"Each of the {why['other']} notes under `other` names a line of the text" in said
    by_kind = [
        (
            sum(1 for x in kept if x["kind"] == kind and x["verdict"] == ACCEPT),
            sum(1 for x in kept if x["kind"] == kind),
        )
        for kind in KINDS
    ]
    assert KINDS == (LATER_PIECE, APPENDIX, OWN_TEXT, SEARCH_FIRST, NAMED_FIRST)
    assert (
        "By kind, {} of the {} drafts of `later_piece` were accepted, {} of the {} of "
        "`appendix`, {} of the {} of `own_text`, {} of the {} of `search_first` and {} of the "
        "{} of `named_first`.".format(*(count for pair in by_kind for count in pair))
        in said
    )
    # What the pre-registration had worked out from the last round of the tuning.
    places, accepted = len(found), head["accepted"]
    assert "240 about 71" in flat(PRE_REGISTRATION)
    assert (
        "Section 3 of the pre-registration had worked out about 71 accepted drafts for 240 "
        "places" in said
    )
    assert f"Here {accepted} of the {places} places have an accepted draft." in said
    assert "The draft of the verdicts was a model's, and the check of it one person's" in said


def test_the_readme_says_which_questions_there_are():
    heading = "The questions"
    said, table = said_in(heading), rows(heading)
    found, head = candidates(), summary()[0]
    asked = [line for line in found if line["question"]]
    questions = load_questions(QUESTIONS)

    assert (
        f"`drafting.assemble` made the question file at {hour(head['made'])} on 2026-11-28, by "
        f"`{ASSEMBLED}` with no file of the repository changed" in said
    )
    counts = by_kind_and_archive(asked, "asked_as")
    for archive in ARCHIVES:
        assert row(archive, *counts[archive], sum(counts[archive])) in table
    sums = [sum(counts[archive][at] for archive in ARCHIVES) for at in range(len(KINDS))]
    assert row("all", *sums, len(asked)) in table and len(table) == 2 + len(ARCHIVES) + 1
    by_title = sum(1 for question in questions if question.type == SEARCH_FIRST)
    by_draft = Counter(line["kept_draft"] for line in asked)
    assert (
        f"There are {len(questions)} questions, where 80 were planned at most, each about a "
        f"paper of its own: {len(questions) - by_title} name their paper by its identifier and "
        f"{by_title} by its title. Of the {len(questions)}, {by_draft[1]} are the first draft "
        f"of their place and {by_draft[2]} the second." in said
    )
    assert set(by_draft) == {1, 2}
    left = Counter(
        (x["archive"], x["kind"]) for x in found if x["verdict"] == ACCEPT and not x["question"]
    )
    assert (
        "Six accepted drafts are no question, because their kind and archive had four before "
        f"them: {left['hep-ex', LATER_PIECE]} of `later_piece` in hep-ex and "
        f"{left['astro-ph', SEARCH_FIRST]} of `search_first` in astro-ph." in said
    )
    assert sum(left.values()) == 6 and len(left) == 2
    fills = [line for line in asked if line["fill"]]
    assert {line["archive"] for line in fills} == {"astro-ph"} and len(fills) == 3
    assert counts["astro-ph"][KINDS.index(NAMED_FIRST)] == 7
    assert (
        "Three of the seven `named_first` questions of astro-ph take places that other kinds "
        "of that archive were short of." in said
    )
    empty = sum(1 for archive in ARCHIVES for count in counts[archive] if not count)
    assert empty == 5 and len(ARCHIVES) * len(KINDS) == 20
    assert (
        "Five of the twenty pairs of a kind and an archive have no question: `appendix` and "
        "`search_first` in hep-ph, `own_text` and `search_first` in hep-th, and `own_text` in "
        "astro-ph." in said
    )
    assert f"The SHA-256 of the file is `{file_digest(QUESTIONS)}`." in said

    def most_that_may_differ(count):
        return max(
            differing
            for differing in range(0, count + 1, 2)
            if reading(*adjusted_wald(differing // 2, differing // 2, count)[1:], 0.10) == NOT_WORSE
        )

    assert (
        f"comes out for at most {most_that_may_differ(len(questions))} such questions of "
        f"{len(questions)}. The table of that section has {most_that_may_differ(40)} for 40 "
        f"questions and {most_that_may_differ(50)} for 50." in said
    )
    # The reading is the pre-registration's, word for word, with its margin.
    assert '"not worse by more than 10 points, on these questions"' in flat(PRE_REGISTRATION)
    assert 'the reading "not worse by more than 10 points" comes out' in said
    assert "| questions | 80 | 70 | 60 | 50 | 40 | 30 |" in PRE_REGISTRATION.read_text(
        encoding="utf-8"
    )


def test_the_sections_that_the_readme_names_are_the_ones_it_means():
    # A number of a section says little by itself: each mention is held to the heading
    # that the pre-registration has under that number.
    said = flat(README)
    mentions = {
        "The places are given out once (Section 3 of the pre-registration)": "Places and kinds",
        "Section 3 of the pre-registration had worked out about 71": "Places and kinds",
        "what to ask (Section 4 of the pre-registration)": "Drafting",
        "by its number in Section 5 of the pre-registration": "Checks by a program",
        "each beside its passage (Section 7 of the pre-registration)": "Review by the maintainer",
        "Section 7 has the maintainer alone read the drafts": "Review by the maintainer",
        "was short of (Section 9 of the pre-registration)": "The question file",
        "(Section 13 of the pre-registration): the margin of ten points stays": (
            "Hypotheses, and how each is read"
        ),
        "Section 15 says that a reviewer who has the passage alone": (
            "Known limits, stated before the runs"
        ),
    }
    for mention, heading in mentions.items():
        assert mention in said, mention
        (number,) = re.findall(r"Section (\d+)", mention)
        assert headings()[number] == heading, mention
    assert "names the file by it in Sections 9 and 10" in said
    assert (headings()["9"], headings()["10"]) == ("The question file", "Conditions and runs")
    # No other section is named than these.
    named = set(re.findall(r"Sections? (\d+)", said)) | {"10"}
    assert named == {"3", "4", "5", "7", "9", "10", "13", "15"}


def test_the_readme_of_all_results_points_here():
    said = flat(ROOT / "results" / "README.md")
    found = tally(outcomes()[1])

    assert (
        f"what the second evaluation left behind before its first run: its {found.papers} "
        "papers of four archives and how they came back on 2026-11-27, the place that each of "
        f"the {found.count(OK)} that were split was given" in said
    )
    assert (
        f"Its {len(load_questions(QUESTIONS))} questions are in `eval_data/{QUESTIONS.name}`"
        in said
    )
    assert "No run of it has been made, and nothing there is a result" in said
    day = moment(review()[0][0]["read"]).date().isoformat()
    assert f"and the verdicts of the review of {day}, with a README of their own" in said


def test_the_rules_for_agents_say_what_is_fixed_and_who_reviewed():
    rules = flat(ROOT / "CLAUDE.md")
    kept = sum(1 for line in candidates() if line["kept"])

    assert (
        "The papers were fetched and the places given out on 2026-11-27 UTC, by the commit that "
        "holds the plan. `results/archives/sample.jsonl`, `outcomes.jsonl` and `places.jsonl` "
        "are fixed: `tests/test_archives_results.py` holds each by its SHA-256." in rules
    )
    assert "and the places are given out once" in rules
    assert (
        f"The {kept} drafts that were left were reviewed on a sheet in `runs_private/`: a first "
        "reader, a Claude session, drafted the verdicts and notes, and the owner checked each against its "
        "passage. `results/archives/review.jsonl` holds the verdicts as they were read off the "
        "sheet on 2026-11-28 UTC, and is fixed as well. An agent does not change a verdict in "
        "it." in rules
    )
    assert (
        f"`eval_data/{QUESTIONS.name}` holds the {len(load_questions(QUESTIONS))} questions that "
        "`drafting.assemble` made of the accepted drafts that day, and "
        "`results/archives/candidates.jsonl` what became of every candidate. Both are fixed"
        in rules
    )
    assert "do not run `drafting.assemble` over them again" in rules
    # The words that stood for the digest are named once more, as what was replaced: in
    # the two sections that hold the digest now.
    assert "One thing was put into Sections 9 and 10 afterwards" in rules
    assert "in the place of the words `<SHA-256 of the question file>`" in rules
    digest = file_digest(QUESTIONS)
    assert [number for number in range(1, 17) if digest in section(number)] == [9, 10]
    assert "No question is left out after the file has its digest (Section 14)" in rules
    assert headings()["14"] == "Exclusions"
    assert "No question is left out after the question file has its digest" in " ".join(
        section(14).split()
    )
