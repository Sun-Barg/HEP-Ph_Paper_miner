"""Which papers the second evaluation asks about: places 41 to 80 of the survey's order.

Drawn from the list that the survey committed, by the survey's own rule. No network.
"""

import random
from pathlib import Path

import pytest

from hepph_paper_miner.drafting.papers import draw_places, read_listed
from hepph_paper_miner.survey.listing import Listed
from hepph_paper_miner.survey.plan import load_plan
from hepph_paper_miner.survey.records import RecordError, write_lines
from hepph_paper_miner.survey.sample import order_key, read_sample

ROOT = Path(__file__).resolve().parent.parent
POPULATION = ROOT / "results" / "survey" / "population.jsonl"
SURVEY_PLAN = ROOT / "eval_data" / "survey_plan.json"
SURVEY_SAMPLE = ROOT / "results" / "survey" / "sample.jsonl"
FOUR = ("hep-ph", "hep-th", "hep-ex", "astro-ph")


@pytest.fixture(scope="module")
def listed():
    return read_listed(POPULATION)[0]


@pytest.fixture(scope="module")
def plan():
    return load_plan(SURVEY_PLAN)


def by_place(paper):
    return paper.archive, paper.rank


def test_the_list_is_the_one_the_survey_drew_from(listed):
    named = read_sample(SURVEY_SAMPLE).head["population"]
    assert read_listed(POPULATION)[1] == named["sha256"]
    assert len(listed) == named["papers"]


def test_places_1_to_40_are_the_sample_of_the_survey(listed, plan):
    # The same rule, asked for the front of the order, gives what the survey drew: so
    # places 41 to 80 are the next papers of that very order.
    front = draw_places(listed, plan, FOUR, 1, 40)
    survey = [paper for paper in read_sample(SURVEY_SAMPLE).papers if paper.archive in FOUR]
    assert sorted(front, key=by_place) == sorted(survey, key=by_place)


def test_places_41_to_80_are_forty_papers_of_each_archive_that_the_survey_did_not_draw(
    listed, plan
):
    later = draw_places(listed, plan, FOUR, 41, 80)
    assert len(later) == 160
    for archive in FOUR:
        own = [paper for paper in later if paper.archive == archive]
        assert [paper.rank for paper in own] == list(range(41, 81))
        assert own == sorted(own, key=lambda paper: (paper.sha256, paper.arxiv_id))
        assert all(
            paper.primary == archive or paper.primary.startswith(archive + ".") for paper in own
        )
    assert all(paper.sha256 == order_key(plan.seed, paper.arxiv_id) for paper in later)
    surveyed = {paper.arxiv_id for paper in read_sample(SURVEY_SAMPLE).papers}
    assert not surveyed & {paper.arxiv_id for paper in later}


def test_the_order_of_the_list_makes_no_difference(listed, plan):
    shuffled = list(listed)
    random.Random(20261126).shuffle(shuffled)
    assert draw_places(shuffled, plan, FOUR, 41, 80) == draw_places(listed, plan, FOUR, 41, 80)


def test_a_longer_stretch_holds_a_shorter_one(listed, plan):
    longer = draw_places(listed, plan, FOUR, 41, 80)
    assert draw_places(listed, plan, FOUR, 41, 60) == [p for p in longer if p.rank <= 60]
    assert draw_places(listed, plan, FOUR, 61, 80) == [p for p in longer if p.rank >= 61]


def test_what_is_no_stretch_or_no_archive_is_refused(listed, plan):
    for first, last in ((0, 40), (41, 40)):
        with pytest.raises(ValueError, match="no stretch"):
            draw_places(listed, plan, FOUR, first, last)
    with pytest.raises(ValueError, match="no archive hep-xx"):
        draw_places(listed, plan, ("hep-ph", "hep-xx"), 41, 80)


def test_an_archive_with_a_shorter_list_gives_fewer(plan):
    few = [Listed(f"2609.{n:05d}v1", "hep-ex", "2026-09-01T00:00:00Z") for n in range(1, 51)]
    drawn = draw_places(few, plan, ("hep-ex",), 41, 80)
    assert [paper.rank for paper in drawn] == list(range(41, 51))


def sample_file(path, papers, plan, **head):
    archives = dict.fromkeys(paper.archive for paper in papers)
    lines = [
        {"record": "sample", "seed": plan.seed, "per_archive": 40, **head},
        *(
            {"record": "archive", "archive": name, "drawn": sum(p.archive == name for p in papers)}
            for name in archives
        ),
        *(
            {
                "record": "paper",
                "archive": paper.archive,
                "rank": paper.rank,
                "id": paper.arxiv_id,
                "primary": paper.primary,
                "sha256": paper.sha256,
            }
            for paper in papers
        ),
    ]
    write_lines(path, lines)
    return path


def test_a_sample_that_begins_further_down_the_order_is_read(tmp_path, listed, plan):
    later = draw_places(listed, plan, FOUR, 41, 80)
    sample = read_sample(sample_file(tmp_path / "sample.jsonl", later, plan, first=41))
    assert sample.papers == tuple(later)


def test_a_sample_numbered_from_another_place_than_it_says_is_refused(tmp_path, listed, plan):
    later = draw_places(listed, plan, FOUR, 41, 80)
    # Without `first`, a sample begins at the front: these papers stand at wrong places.
    with pytest.raises(RecordError, match="are not numbered from 1 on"):
        read_sample(sample_file(tmp_path / "a.jsonl", later, plan))
    with pytest.raises(RecordError, match="are not numbered from 42 on"):
        read_sample(sample_file(tmp_path / "b.jsonl", later, plan, first=42))
    for bad in (0, -1, True, "41"):
        with pytest.raises(RecordError, match="names no place to begin at"):
            read_sample(sample_file(tmp_path / "c.jsonl", later, plan, first=bad))
