"""The plan of the survey: the file the repository keeps, and plans that are refused. No network."""

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from hepph_paper_miner.agent.origin import file_digest
from hepph_paper_miner.survey.plan import ORDER, PlanError, Window, load_plan, read_plan

PLAN = Path(__file__).parent.parent / "eval_data" / "survey_plan.json"


def a_plan(**changes) -> dict:
    """A small plan that is in order. `changes` replace parts of it, by dotted name."""
    plan = {
        "plan": "test-1",
        "about": "A plan for the tests.",
        "population": {
            "archives": {"hep-ph": ["hep-ph"], "astro-ph": ["astro-ph.GA", "astro-ph.CO"]},
            "categories_checked": {"on": "2026-11-24", "at": "https://arxiv.org/category_taxonomy"},
            "submitted": [["202608010000", "202608312359"], ["202609010000", "202609302359"]],
        },
        "sample": {"per_archive": 3, "seed": 7, "order": ORDER},
        "outline_check": {"per_archive": 2},
    }
    for name, value in changes.items():
        *parents, last = name.split(".")
        holder = plan
        for parent in parents:
            holder = holder[parent]
        if value is ...:
            del holder[last]
        else:
            holder[last] = value
    return plan


def test_the_plan_of_the_repository_names_the_physics_archives_and_three_months():
    plan = load_plan(PLAN)

    assert plan.name == "survey-1"
    # arXiv's taxonomy on 2026-11-24: thirteen archives in the physics group, 51 categories.
    assert list(plan.archives) == [
        "astro-ph",
        "cond-mat",
        "gr-qc",
        "hep-ex",
        "hep-lat",
        "hep-ph",
        "hep-th",
        "math-ph",
        "nlin",
        "nucl-ex",
        "nucl-th",
        "physics",
        "quant-ph",
    ]
    sizes = {archive: len(categories) for archive, categories in plan.archives.items()}
    assert sizes["astro-ph"] == 6 and sizes["cond-mat"] == 9 and sizes["nlin"] == 5
    assert sizes["physics"] == 22 and len(plan.categories) == 51
    assert [str(window) for window in plan.windows] == [
        "202608010000-202608312359",
        "202609010000-202609302359",
        "202610010000-202610312359",
    ]
    assert (plan.per_archive, plan.seed, plan.outline_per_archive) == (40, 20261124, 5)
    assert plan.sha256 == file_digest(PLAN)


def test_what_the_readme_says_of_the_plan_is_what_the_plan_says():
    plan = load_plan(PLAN)
    readme = " ".join((PLAN.parent.parent / "README.md").read_text(encoding="utf-8").split())
    archives, drawn = len(plan.archives), len(plan.archives) * plan.per_archive
    pieces = len(plan.categories) * len(plan.windows)

    assert (
        f"the {len(plan.categories)} categories of the physics group ({archives} archives: "
        in readme
    )
    assert f"({archives} archives: {', '.join(plan.archives)};" in readme
    assert f"| Sample | {plan.per_archive} papers of every archive, {drawn} in all |" in readme
    assert f"The seed is {plan.seed}, the day the plan was written" in readme
    assert f"the first {plan.outline_per_archive} of the same order: " in readme
    assert f"{archives * plan.outline_per_archive} outlines held against the papers" in readme
    assert f"({pieces} requests at the least, three seconds apart)" in readme
    assert (pieces, drawn) == (153, 520)
    # Two requests for a paper, three seconds apart.
    assert f"so {drawn * 2 * 3 // 60} minutes at the least for {drawn} papers" in readme
    first, last = plan.windows[0].starts, plan.windows[-1].ends
    assert "from 2026-08-01 00:00 to 2026-10-31 23:59 GMT" in readme
    assert (first.isoformat(), last.isoformat()) == (
        "2026-08-01T00:00:00+00:00",
        "2026-11-01T00:00:00+00:00",
    )
    assert plan.windows[0].ends == plan.windows[1].starts  # the months leave no gap
    assert plan.windows[1].ends == plan.windows[2].starts
    # The widest 95% interval of a share of `per_archive` papers: near one half.
    assert (
        f"And {plan.per_archive} papers of an archive leave a share uncertain by about 15" in readme
    )
    assert 0.145 < 1.96 * (0.25 / plan.per_archive) ** 0.5 < 0.16


def test_a_category_is_looked_up_under_the_archive_that_lists_it():
    plan = read_plan(json.dumps(a_plan()))
    assert plan.archive_of("astro-ph.CO") == "astro-ph"
    assert plan.archive_of("hep-ph") == "hep-ph"
    assert plan.archive_of("cs.LG") is None  # the primary category of a cross-listed paper
    assert plan.categories == ("hep-ph", "astro-ph.GA", "astro-ph.CO")


def test_a_window_holds_its_last_minute_to_the_second_and_nothing_after():
    window = Window("202608010000", "202608312359")

    def at(text: str) -> datetime:
        return datetime.fromisoformat(text).astimezone(UTC)

    assert window.holds(at("2026-08-01T00:00:00Z"))
    assert window.holds(at("2026-08-31T23:59:59Z"))
    assert not window.holds(at("2026-07-31T23:59:59Z"))
    assert not window.holds(at("2026-09-01T00:00:00Z"))
    # A time in another zone is the moment it names, not the digits it is written with.
    assert window.holds(at("2026-08-01T02:00:00+02:00"))
    assert not window.holds(at("2026-08-01T01:59:59+02:00"))


@pytest.mark.parametrize(
    ("changes", "said"),
    [
        ({"sample.per_archve": 40}, "unknown key(s) per_archve"),
        ({"sample.seed": ...}, "sample: no seed"),
        ({"outline_check": ...}, "the plan: no outline_check"),
        ({"sample.per_archive": 0}, "sample.per_archive: a whole number from 1 on"),
        ({"sample.per_archive": True}, "sample.per_archive: a whole number from 1 on"),
        ({"sample.per_archive": "40"}, "sample.per_archive: a whole number from 1 on"),
        ({"sample.seed": "7"}, "sample.seed: a whole number"),
        ({"sample.seed": False}, "sample.seed: a whole number"),
        ({"sample.order": "random.sample"}, "sample.order: this code draws by"),
        (
            {"outline_check.per_archive": 4},
            "4 papers of an archive are checked and only 3 are drawn",
        ),
        ({"population.archives": {}}, "population.archives: an object"),
        ({"population.archives": {"hep-ph": []}}, "population.archives.hep-ph: a list"),
        # A category under the name of another archive would be counted for that one.
        (
            {"population.archives": {"hep-ph": ["hep-th"]}},
            "hep-th is not a category of hep-ph",
        ),
        (
            {"population.archives": {"astro-ph": ["astro-phX.GA"]}},
            "is not the name of a category",
        ),
        (
            {"population.archives": {"astro-ph": ["astro-ph.GA", "astro-ph.GA"]}},
            "astro-ph.GA is there twice",
        ),
        ({"population.archives": {"astro-ph": ["cat:astro-ph.GA OR all:x"]}}, "is not the name"),
        ({"population.submitted": []}, "population.submitted: a list of at least one window"),
        ({"population.submitted": [["20260801", "202608312359"]]}, "two times as YYYYMMDDHHMM"),
        ({"population.submitted": [["202608010000"]]}, "two times as YYYYMMDDHHMM"),
        ({"population.submitted": [["202613010000", "202613312359"]]}, "population.submitted[1]"),
        (
            {"population.submitted": [["202608310000", "202608010000"]]},
            "202608010000 is before 202608310000",
        ),
        # Two windows that share a minute would list the papers of that minute twice.
        (
            {
                "population.submitted": [
                    ["202608010000", "202608312359"],
                    ["202608312359", "202609302359"],
                ]
            },
            "begins before 202608010000-202608312359 has ended",
        ),
        (
            {
                "population.submitted": [
                    ["202609010000", "202609302359"],
                    ["202608010000", "202608312359"],
                ]
            },
            "begins before",
        ),
        ({"population.categories_checked.on": "yesterday"}, "a day as YYYY-MM-DD"),
        ({"plan": ""}, "plan: a name"),
    ],
)
def test_a_plan_that_is_not_in_order_is_refused_and_told_where(changes, said):
    with pytest.raises(PlanError) as caught:
        read_plan(json.dumps(a_plan(**changes)))
    assert said in str(caught.value)


def test_a_file_that_is_no_plan_is_refused_by_name(tmp_path):
    path = tmp_path / "plan.json"
    path.write_text("{ not json", encoding="utf-8")
    with pytest.raises(PlanError, match=r"plan\.json: not JSON"):
        load_plan(path)
    path.write_bytes(b"\xff\xfe")
    with pytest.raises(PlanError, match=r"plan\.json: not UTF-8"):
        load_plan(path)
    path.write_text("[1, 2]", encoding="utf-8")
    with pytest.raises(PlanError, match="an object with the keys"):
        load_plan(path)
