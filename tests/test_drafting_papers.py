"""Which papers the second evaluation asks about: a later stretch of the survey's order.

Drawn from the list that the survey committed, by the survey's own rule. No network.
The stretch of these tests is places 41 to 80, which the design began with. The stretch
of the plan, places 41 to 100, is held in test_archives_plan.py.
"""

import hashlib
import json
import random
import re
from pathlib import Path

import pytest

from hepph_paper_miner.drafting.papers import (
    draw_places,
    read_archives_plan,
    read_listed,
)
from hepph_paper_miner.drafting.papers import main as papers_main
from hepph_paper_miner.survey.listing import Listed
from hepph_paper_miner.survey.plan import PlanError, load_plan
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


# --- the plan of the second evaluation and the command that draws its sample ---------------


def digest_of(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def plan_data(**papers):
    return {
        "plan": "archives-test",
        "about": "Places 41 to 80 of four archives, for the tests.",
        "papers": {
            "survey_plan": {"name": "survey-1", "sha256": digest_of(SURVEY_PLAN)},
            "population": {"sha256": digest_of(POPULATION)},
            "archives": list(FOUR),
            "first": 41,
            "last": 80,
            **papers,
        },
    }


def write_plan(path, data):
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def committed(path):
    return {"commit": "c0ffee", "modified": False}


def test_the_plan_names_the_order_the_list_the_archives_and_the_places():
    plan = read_archives_plan(json.dumps(plan_data()), "f" * 64)
    assert (plan.name, plan.survey_plan, plan.archives) == ("archives-test", "survey-1", FOUR)
    assert (plan.first, plan.last, plan.per_archive, plan.sha256) == (41, 80, 40, "f" * 64)
    assert plan.population_sha256 == digest_of(POPULATION)


@pytest.mark.parametrize(
    ("change", "says"),
    [
        ({"seed": 1}, "unknown key(s) seed"),
        ({"first": 0}, "papers.first: a whole number from 1 on"),
        ({"last": True}, "papers.last: a whole number from 1 on"),
        ({"first": 81}, "papers.last: 80 is before papers.first, 81"),
        ({"archives": []}, "papers.archives: a list of the names of archives"),
        ({"archives": ["hep-ph", "hep-ph"]}, "an archive is there twice"),
        ({"population": {"sha256": "ED1A"}}, "papers.population.sha256: a SHA-256"),
        ({"survey_plan": {"name": "survey-1"}}, "papers.survey_plan: no sha256"),
    ],
)
def test_a_plan_that_is_not_of_the_form_is_refused(change, says):
    with pytest.raises(PlanError, match=re.escape(says)):
        read_archives_plan(json.dumps(plan_data(**change)))


def test_a_plan_without_its_papers_is_refused():
    with pytest.raises(PlanError, match="the plan: no papers"):
        read_archives_plan(json.dumps({"plan": "x", "about": ""}))


def test_the_command_writes_places_41_to_80_as_a_sample_that_survey_run_reads(
    tmp_path, listed, plan, capsys
):
    plan_file = write_plan(tmp_path / "archives_plan.json", plan_data())
    out = tmp_path / "sample.jsonl"
    assert papers_main(["--plan", str(plan_file), "--sample", str(out)], origin=committed) == 0
    sample = read_sample(out)
    assert sample.papers == tuple(draw_places(listed, plan, FOUR, 41, 80))
    head = sample.head
    assert (head["first"], head["per_archive"], head["seed"]) == (41, 40, plan.seed)
    assert head["plan"] == {
        "name": "archives-test",
        "sha256": digest_of(plan_file),
        "commit": "c0ffee",
    }
    assert head["survey_plan"] == {"name": "survey-1", "sha256": digest_of(SURVEY_PLAN)}
    survey = read_sample(SURVEY_SAMPLE)
    assert head["population"] == survey.head["population"]
    assert head["order"] == survey.head["order"]
    # The list counts each archive as it counted it for the survey.
    for archive in FOUR:
        counted = {name: sample.counts[archive][name] for name in ("listed", "primary")}
        assert counted == {name: survey.counts[archive][name] for name in ("listed", "primary")}
        assert sample.counts[archive]["drawn"] == 40
    said = capsys.readouterr().out
    assert "places 41 to 80: 160 paper(s) with seed 20261124" in said


@pytest.mark.parametrize(
    ("change", "says"),
    [
        ({"population": {"sha256": "0" * 64}}, "is not the list that archives-test names"),
        ({"survey_plan": {"name": "survey-1", "sha256": "0" * 64}}, "is not the plan survey-1"),
        (
            {"survey_plan": {"name": "survey-2", "sha256": digest_of(SURVEY_PLAN)}},
            "is not the plan survey-2",
        ),
        ({"archives": ["hep-ph", "hep-xx"]}, "has no archive hep-xx"),
    ],
)
def test_a_plan_that_names_other_files_or_archives_is_refused(tmp_path, capsys, change, says):
    plan_file = write_plan(tmp_path / "archives_plan.json", plan_data(**change))
    out = tmp_path / "sample.jsonl"
    assert papers_main(["--plan", str(plan_file), "--sample", str(out)], origin=committed) == 2
    assert says in capsys.readouterr().err
    assert not out.exists()


def test_a_list_that_another_plan_made_is_refused(tmp_path, capsys):
    lines = [
        {"record": "population", "plan": {"name": "survey-1", "sha256": "0" * 64}},
        {"record": "paper", "id": "2609.00001v1", "primary": "hep-ph", "published": "x"},
    ]
    population = tmp_path / "population.jsonl"
    write_lines(population, lines)
    data = plan_data(population={"sha256": digest_of(population)})
    plan_file = write_plan(tmp_path / "archives_plan.json", data)
    argv = ["--plan", str(plan_file), "--population", str(population)]
    assert papers_main([*argv, "--sample", str(tmp_path / "s.jsonl")], origin=committed) == 2
    assert "was not listed by the plan survey-1" in capsys.readouterr().err


def test_a_plan_that_no_commit_holds_or_changed_code_is_refused(tmp_path, capsys):
    plan_file = write_plan(tmp_path / "archives_plan.json", plan_data())
    out = tmp_path / "sample.jsonl"

    def loose(path):
        return {"commit": None, "modified": None} if path else committed(path)

    def changed(path):
        return {"commit": "c0ffee", "modified": True}

    argv = ["--plan", str(plan_file), "--sample", str(out)]
    assert papers_main(argv, origin=loose) == 2
    assert "the plan is not a file that a repository keeps" in capsys.readouterr().err
    assert papers_main(argv, origin=changed) == 2
    assert "files the repository keeps have been changed" in capsys.readouterr().err
    assert not out.exists()
    out.write_text("", encoding="utf-8")
    assert papers_main(argv, origin=committed) == 2
    assert "is there already" in capsys.readouterr().err
