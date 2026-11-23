"""The list and the sample of the survey, as they were drawn.

results/survey/population.jsonl is what arXiv listed for the plan on 2026-11-23 (UTC),
and results/survey/sample.jsonl the 520 papers drawn from it. These tests hold the two
files against each other and against the plan: the plan is the file the sample was drawn
under, the list is whole as far as it says of itself, the sample is what the rule of the
plan draws from the list, and the README says of the two what they say.

From here on the plan is fixed (CLAUDE.md, "The survey"). A change to
eval_data/survey_plan.json fails here, and so does a paper put into the sample by hand:
the sample file alone cannot always show one (test_survey_sample.py), the list beside it
can.

No network and no LLM. The files hold identifiers, categories and times, and nothing of
the text of a paper; one of the tests says so.
"""

import re
from collections import Counter
from datetime import datetime, timedelta
from functools import cache
from pathlib import Path

from hepph_paper_miner.sources.base import parse_arxiv_id
from hepph_paper_miner.survey.listing import PAGE_SIZE, Listed
from hepph_paper_miner.survey.plan import ORDER, load_plan
from hepph_paper_miner.survey.records import read_lines
from hepph_paper_miner.survey.sample import draw, read_sample

ROOT = Path(__file__).parent.parent
PLAN = ROOT / "eval_data" / "survey_plan.json"
HERE = ROOT / "results" / "survey"
POPULATION, SAMPLE = HERE / "population.jsonl", HERE / "sample.jsonl"

# The commit that brought the plan and the commands. The files name it in full.
DREW = "a3ddd0b"

# The two files as the command wrote them. It printed the SHA-256 of the list when it
# drew; the one of the sample was taken from the file on that computer afterwards.
LIST_SHA256 = "ed1a8e897f69011cd166fda8405483e7c693c2a1c4102356be1b7a85ab866760"
SAMPLE_SHA256 = "9378ba085e235347c4347ad6ea23c56d645ecc5a38acfad318d0e3703d10c9e4"


@cache
def the_list():
    """The first line, the pieces and the papers of the list, and the SHA-256 of its file."""
    lines, digest = read_lines(POPULATION, "population")
    pieces = [line for line in lines[1:] if line["record"] == "piece"]
    papers = [line for line in lines[1:] if line["record"] == "paper"]
    assert len(lines) == 1 + len(pieces) + len(papers)
    return lines[0], pieces, papers, digest


def test_the_two_files_are_the_bytes_that_were_written():
    # Also on Windows: a checkout that turned the line ends would make them other files,
    # and the outcomes of the survey name the sample by this hash.
    assert the_list()[3] == LIST_SHA256
    assert read_sample(SAMPLE).sha256 == SAMPLE_SHA256


def test_the_plan_is_the_file_the_sample_was_drawn_under():
    plan, sample = load_plan(PLAN), read_sample(SAMPLE)
    head, _, _, _ = the_list()
    stamp = sample.head["plan"]

    assert (stamp["name"], stamp["sha256"]) == (plan.name, plan.sha256)
    assert head["plan"] == stamp
    assert (sample.head["seed"], sample.head["per_archive"], sample.head["order"]) == (
        plan.seed,
        plan.per_archive,
        ORDER,
    )
    # One commit holds the plan and the code that drew, and no file it keeps was changed.
    assert stamp["commit"].startswith(DREW)
    assert sample.head["code"] == head["code"] == {"commit": stamp["commit"], "modified": False}


def test_the_sample_names_the_list_it_was_drawn_from():
    _, _, papers, digest = the_list()

    assert read_sample(SAMPLE).head["population"] == {
        "file": POPULATION.name,
        "sha256": digest,
        "papers": len(papers),
    }


def test_the_list_holds_every_piece_of_the_plan_and_every_paper_once():
    plan = load_plan(PLAN)
    head, pieces, papers, _ = the_list()

    assert [(piece["category"], piece["first"], piece["last"]) for piece in pieces] == [
        (category, window.first, window.last)
        for category in plan.categories
        for window in plan.windows
    ]
    assert (head["pieces"], head["papers"]) == (len(pieces), len(papers)) == (153, 29_285)
    assert head["page_size"] == PAGE_SIZE

    named = [parse_arxiv_id(paper["id"]) for paper in papers]
    assert all(each.version is not None for each in named)
    assert len({each.base for each in named}) == len(papers)
    # A category that arXiv wrote under another name would have no paper of its own here.
    assert {paper["primary"] for paper in papers} == set(plan.categories)

    # Every paper belongs to one piece: its primary category, the month of its first version.
    found: Counter[tuple[str, str]] = Counter()
    for paper in papers:
        moment = datetime.fromisoformat(paper["published"])
        (window,) = [each for each in plan.windows if each.holds(moment)]
        found[paper["primary"], window.first] += 1
    for piece in pieces:
        assert piece["primary"] == found[piece["category"], piece["first"]]
        assert 0 < piece["primary"] <= piece["total"]
        assert piece["pages"] == -(-piece["total"] // head["page_size"])
    assert sum(found.values()) == len(papers)
    # Five pieces were larger than a page, so the pages were put together for real.
    assert sorted(piece["pages"] for piece in pieces if piece["pages"] > 1) == [2, 2, 2, 3, 3]


def test_the_sample_is_what_the_rule_draws_from_the_list():
    plan, sample = load_plan(PLAN), read_sample(SAMPLE)
    _, _, papers, _ = the_list()
    listed = [Listed(paper["id"], paper["primary"], paper["published"]) for paper in papers]

    assert draw(listed, plan) == list(sample.papers)
    assert len(sample.papers) == len(plan.archives) * plan.per_archive == 520


def test_the_counts_of_the_archives_are_those_of_the_list():
    plan, sample = load_plan(PLAN), read_sample(SAMPLE)
    _, pieces, papers, _ = the_list()

    assert list(sample.counts) == list(plan.archives)
    for archive, categories in plan.archives.items():
        count = sample.counts[archive]
        assert count["listed"] == sum(
            piece["total"] for piece in pieces if piece["category"] in categories
        )
        assert count["primary"] == sum(1 for paper in papers if paper["primary"] in categories)
        # No archive had fewer papers than the plan asks for.
        assert count["drawn"] == plan.per_archive < count["primary"]


def test_the_two_files_hold_nothing_of_the_text_of_a_paper():
    plan = load_plan(PLAN)
    head, pieces, papers, _ = the_list()
    lines, _ = read_lines(SAMPLE, "sample")
    archives = [line for line in lines if line["record"] == "archive"]
    drawn = [line for line in lines if line["record"] == "paper"]
    assert len(lines) == 1 + len(archives) + len(drawn)

    def keys(some):
        return {frozenset(line) for line in some}

    assert keys([head]) == {
        frozenset({"record", "plan", "code", "page_size", "asked", "pieces", "papers"})
    }
    assert keys(pieces) == {
        frozenset({"record", "category", "first", "last", "total", "primary", "pages"})
    }
    assert keys(papers) == {frozenset({"record", "id", "primary", "published"})}
    assert keys(lines[:1]) == {
        frozenset({"record", "plan", "code", "population", "per_archive", "seed", "order", "drawn"})
    }
    assert keys(archives) == {frozenset({"record", "archive", "listed", "primary", "drawn"})}
    assert keys(drawn) == {frozenset({"record", "archive", "rank", "id", "primary", "sha256"})}

    # What a line of a paper holds is an identifier, a category of the plan and a time or
    # a hash: no room for a title.
    identifier = re.compile(r"\d{4}\.\d{5}v\d+")
    for paper in papers:
        assert identifier.fullmatch(paper["id"])
        assert paper["primary"] in plan.categories
        assert re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ", paper["published"])
    for paper in drawn:
        assert identifier.fullmatch(paper["id"])
        assert paper["primary"] in plan.categories and paper["archive"] in plan.archives
        assert isinstance(paper["rank"], int) and re.fullmatch(r"[0-9a-f]{64}", paper["sha256"])


def test_what_the_readme_says_of_the_sample_is_what_the_files_say():
    plan, sample = load_plan(PLAN), read_sample(SAMPLE)
    head, pieces, papers, _ = the_list()
    readme = " ".join((ROOT / "README.md").read_text(encoding="utf-8").split())

    assert (
        "the rule is fixed and the 520 papers are drawn, the survey has not been run yet" in readme
    )
    # The outcomes come in a later commit, and then this sentence has to go.
    assert ("**It has not been run.**" in readme) == (not (HERE / "outcomes.jsonl").exists())

    # When the commit was made is in the history, not in a file: the README's "16:52 UTC"
    # is not held against anything here.
    first, last = (datetime.fromisoformat(head["asked"][end]) for end in ("first", "last"))
    assert first.utcoffset() == last.utcoffset() == timedelta(0)
    drawn = datetime.fromisoformat(sample.head["drawn"])
    assert first.date() == last.date() == drawn.date() and last <= drawn
    assert (
        f"The command was run on {drawn:%Y-%m-%d} by `{DREW}`, the commit that brought the plan"
        in readme
    )
    assert (
        f"arXiv gave the answers the list is made of from {first:%H:%M} to {last:%H:%M} UTC."
        in readme
    )
    listed = sum(piece["total"] for piece in pieces)
    assert f"It listed {listed:,} entries in the {len(pieces)} pieces" in readme
    assert (
        f"{len(papers):,} papers have one of the {len(plan.categories)} categories as their "
        f"primary category, and {len(sample.papers)} of them were drawn." in readme
    )
    for archive in plan.archives:
        count = sample.counts[archive]
        assert (
            f"| {archive} | {count['listed']:,} | {count['primary']:,} | {count['drawn']} |"
            in readme
        )

    size = {archive: sample.counts[archive]["primary"] for archive in plan.archives}
    small, large = min(size, key=size.get), max(size, key=size.get)
    assert (
        f"Forty papers are almost a third of one archive ({small}, {size[small]:,} papers) "
        f"and less than a hundredth of another ({large}, {size[large]:,})" in readme
    )
    assert plan.per_archive == 40
    assert 0.30 < plan.per_archive / size[small] < 1 / 3
    assert plan.per_archive / size[large] < 0.01
    with_a_paper = {paper.primary for paper in sample.papers}
    assert (
        f"{len(with_a_paper)} of the {len(plan.categories)} categories have a paper among them"
        in readme
    )
    # The first try reads the first four papers of every archive.
    assert "What it showed of 52 papers could not change the sample" in readme
    assert 4 * len(plan.archives) == 52
