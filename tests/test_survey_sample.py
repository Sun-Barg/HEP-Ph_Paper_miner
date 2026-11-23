"""Drawing the sample of the survey: the order, the two files, and what the command refuses.

arXiv is played by the scripted transport of test_survey_listing.py. No network.
"""

import hashlib
import json
import random
from pathlib import Path

import pytest
from test_survey_listing import SEVERAL, ListingArxiv, Spoilt, paper
from test_survey_plan import a_plan

from hepph_paper_miner.agent.origin import file_digest
from hepph_paper_miner.survey import sample
from hepph_paper_miner.survey.listing import Listed, Piece, Population
from hepph_paper_miner.survey.plan import ORDER, read_plan
from hepph_paper_miner.survey.records import RecordError
from hepph_paper_miner.survey.sample import draw, order_key, population_lines, read_sample

COMMIT = "0123456789abcdef0123456789abcdef01234567"
PLAN = read_plan(json.dumps(a_plan()))


def committed(file: Path | None = None) -> dict:
    """What agent/origin.py says of a file of a commit, with nothing changed since."""
    return {"commit": COMMIT, "modified": False}


def listed(count: int, primary: str, first: int = 1) -> list[Listed]:
    return [
        Listed(f"2608.{number:05d}v1", primary, "2026-08-01T10:00:00Z")
        for number in range(first, first + count)
    ]


POPULATION = [
    *listed(30, "hep-ph"),
    *listed(12, "astro-ph.GA", 101),
    *listed(8, "astro-ph.CO", 201),
    *listed(5, "hep-th", 301),  # no category of the plan
]


def test_a_paper_is_ordered_by_the_sha256_of_the_seed_and_its_identifier_without_version():
    expected = hashlib.sha256(b"20261124:2608.01234").hexdigest()
    assert order_key(20261124, "2608.01234v1") == expected
    # A paper keeps its place when its authors replace it.
    assert order_key(20261124, "2608.01234v7") == expected
    assert order_key(20261125, "2608.01234v1") != expected
    assert order_key(7, "hep-ph/0404175v2") == hashlib.sha256(b"7:hep-ph/0404175").hexdigest()
    assert ORDER == "sha256 of '<seed>:<identifier without its version>', smallest first"


def test_the_papers_of_every_archive_are_taken_from_the_front_of_the_order():
    drawn = draw(POPULATION, PLAN)

    assert [each.archive for each in drawn] == ["hep-ph"] * 3 + ["astro-ph"] * 3
    assert [each.rank for each in drawn] == [1, 2, 3, 1, 2, 3]
    for archive, categories in (
        ("hep-ph", {"hep-ph"}),
        ("astro-ph", {"astro-ph.GA", "astro-ph.CO"}),
    ):
        own = sorted(
            (hashlib.sha256(f"7:{each.arxiv_id[:-2]}".encode()).hexdigest(), each.arxiv_id)
            for each in POPULATION
            if each.primary in categories
        )
        assert [(each.sha256, each.arxiv_id) for each in drawn if each.archive == archive] == own[
            :3
        ]
    # An archive is one population: its categories are not drawn from one by one.
    assert {each.primary for each in drawn if each.archive == "astro-ph"} <= {
        "astro-ph.GA",
        "astro-ph.CO",
    }


def test_the_order_in_which_the_papers_are_given_makes_no_difference():
    shuffled = list(POPULATION)
    random.Random(0).shuffle(shuffled)
    assert shuffled != POPULATION
    assert draw(shuffled, PLAN) == draw(POPULATION, PLAN) == draw(reversed(POPULATION), PLAN)


def test_a_larger_sample_holds_the_smaller_one():
    larger = read_plan(json.dumps(a_plan(**{"sample.per_archive": 10})))
    small, large = draw(POPULATION, PLAN), draw(POPULATION, larger)
    for archive in ("hep-ph", "astro-ph"):
        few = [each for each in small if each.archive == archive]
        many = [each for each in large if each.archive == archive]
        assert len(many) == 10 and many[:3] == few


def test_another_seed_gives_another_order():
    other = read_plan(json.dumps(a_plan(**{"sample.seed": 8})))
    assert [each.arxiv_id for each in draw(POPULATION, other)] != [
        each.arxiv_id for each in draw(POPULATION, PLAN)
    ]


def test_an_archive_with_fewer_papers_than_asked_for_gives_all_of_them():
    drawn = draw([*listed(2, "hep-ph"), *listed(9, "astro-ph.GA", 101)], PLAN)
    assert [each.rank for each in drawn if each.archive == "hep-ph"] == [1, 2]
    assert len([each for each in drawn if each.archive == "astro-ph"]) == 3


# --- the command ---------------------------------------------------------------------------

MANY = [
    *(paper(n, "hep-ph", f"2026-08-{1 + n % 28:02d}T10:00:00Z") for n in range(1, 8)),
    *(
        paper(n, "astro-ph.GA", f"2026-09-{1 + n % 28:02d}T10:00:00Z", "hep-ph")
        for n in range(11, 16)
    ),
    paper(21, "astro-ph.CO", "2026-08-05T10:00:00Z"),
    paper(22, "hep-th", "2026-08-06T10:00:00Z", "hep-ph", "astro-ph.CO"),
    paper(23, "hep-ph", "2026-08-07T10:00:00Z", version=3),
]


def run(tmp_path, arxiv=None, origin=committed, extra=(), plan=None):
    """Run the command in a folder of its own. Returns (exit code, list file, sample file)."""
    tmp_path.mkdir(parents=True, exist_ok=True)
    plan_file = tmp_path / "plan.json"
    plan_file.write_text(json.dumps(plan or a_plan()), encoding="utf-8")
    population, drawn = tmp_path / "out" / "population.jsonl", tmp_path / "out" / "sample.jsonl"
    arxiv = arxiv or ListingArxiv(MANY)
    argv = ["--plan", str(plan_file), "--population", str(population), "--sample", str(drawn)]
    code = sample.main([*argv, *extra], fetcher=arxiv.fetcher(tmp_path / "cache"), origin=origin)
    return code, population, drawn


def lines_of(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def test_the_command_writes_the_list_and_the_sample_drawn_from_it(tmp_path, capsys):
    code, population, drawn = run(tmp_path)
    assert code == 0

    head, *rest = lines_of(population)
    plan_digest = file_digest(tmp_path / "plan.json")
    assert head["record"] == "population"
    assert head["plan"] == {"name": "test-1", "sha256": plan_digest, "commit": COMMIT}
    assert head["code"] == {"commit": COMMIT, "modified": False}
    assert (head["pieces"], head["papers"], head["page_size"]) == (6, 14, 1000)
    assert head["asked"]["first"] <= head["asked"]["last"] and head["asked"]["first"][:2] == "20"
    pieces = [line for line in rest if line["record"] == "piece"]
    assert pieces[0] == {
        "record": "piece",
        "category": "hep-ph",
        "first": "202608010000",
        "last": "202608312359",
        "total": 9,
        "primary": 8,
        "pages": 1,
    }
    papers = [line for line in rest if line["record"] == "paper"]
    assert [line["id"] for line in papers] == sorted(line["id"] for line in papers)
    assert {
        "record": "paper",
        "id": "2608.00023v3",
        "primary": "hep-ph",
        "published": "2026-08-07T10:00:00Z",
    } in papers
    assert not any(line["primary"] == "hep-th" for line in papers)

    found = read_sample(drawn)
    assert found.head["population"] == {
        "file": "population.jsonl",
        "sha256": file_digest(population),
        "papers": 14,
    }
    assert found.head["plan"] == head["plan"] and found.head["code"] == head["code"]
    assert (found.head["seed"], found.head["per_archive"], found.head["order"]) == (7, 3, ORDER)
    assert found.sha256 == file_digest(drawn)
    assert found.counts["hep-ph"] == {
        "record": "archive",
        "archive": "hep-ph",
        "listed": 14,  # 8 of its own, 5 of astro-ph.GA and 1 of hep-th cross-listed to it
        "primary": 8,
        "drawn": 3,
    }
    assert found.counts["astro-ph"]["primary"] == 6 and found.counts["astro-ph"]["drawn"] == 3
    # The sample is the front of the order of the list the command wrote beside it.
    kept = [Listed(line["id"], line["primary"], line["published"]) for line in papers]
    assert list(found.papers) == draw(kept, PLAN)

    printed = capsys.readouterr().out
    assert "6 paper(s) drawn from 14 with seed 7" in printed
    assert f"sha256 {file_digest(population)}" in printed


def test_an_archive_with_fewer_papers_than_the_plan_asks_for_is_pointed_out(tmp_path, capsys):
    code, _, drawn = run(tmp_path, plan=a_plan(**{"sample.per_archive": 7}))
    assert code == 0
    rows = [line.split(maxsplit=4) for line in capsys.readouterr().out.splitlines()]
    assert ["archive", "listed", "primary", "drawn"] in rows
    # hep-ph has eight papers and gives seven. astro-ph has six, and every one is drawn.
    assert ["hep-ph", "14", "8", "7"] in rows
    assert ["astro-ph", "7", "6", "6", "fewer than 7: every paper of the archive was drawn"] in rows
    found = read_sample(drawn)
    assert (found.counts["hep-ph"]["drawn"], found.counts["astro-ph"]["drawn"]) == (7, 6)


def test_the_files_hold_no_title_and_no_abstract_and_end_their_lines_the_same_everywhere(tmp_path):
    _, population, drawn = run(tmp_path)
    for path in (population, drawn):
        data = path.read_bytes()
        assert b"title" not in data.lower() and b"abstract" not in data.lower()
        assert b"A. Author" not in data
        assert b"\r" not in data and data.endswith(b"\n")
        assert set().union(*(line.keys() for line in lines_of(path))) <= {
            "record",
            "plan",
            "code",
            "page_size",
            "asked",
            "pieces",
            "papers",
            "category",
            "first",
            "last",
            "total",
            "primary",
            "pages",
            "id",
            "published",
            "population",
            "per_archive",
            "seed",
            "order",
            "drawn",
            "archive",
            "listed",
            "rank",
            "sha256",
        }


def test_the_same_list_gives_the_same_sample_on_a_second_computer(tmp_path):
    # The second run reads nothing from the first: another folder, another cache.
    _, _, first = run(tmp_path / "one")
    _, _, second = run(tmp_path / "two", arxiv=ListingArxiv(reversed(MANY)))
    assert read_sample(first).papers == read_sample(second).papers


def test_the_command_does_not_write_over_a_file_that_is_there(tmp_path, capsys):
    (tmp_path / "out").mkdir()
    (tmp_path / "out" / "sample.jsonl").write_text("drawn before\n", encoding="utf-8")
    arxiv = ListingArxiv(MANY)

    code, population, drawn = run(tmp_path, arxiv=arxiv)

    assert code == 2 and "is there already; move it away first" in capsys.readouterr().err
    assert drawn.read_text(encoding="utf-8") == "drawn before\n" and not population.exists()
    assert arxiv.requests == []


@pytest.mark.parametrize(
    ("origin", "said"),
    [
        (
            lambda file=None: {"commit": None, "modified": None},
            "the plan is not a file that a repository keeps",
        ),
        (
            lambda file=None: {"commit": COMMIT, "modified": True},
            "files the repository keeps have been changed",
        ),
        # The code is in a commit, the plan is a file that lies beside it and is in none.
        (
            lambda file=None: {
                "commit": None if file else COMMIT,
                "modified": None if file else False,
            },
            "the plan is not a file that a repository keeps",
        ),
    ],
)
def test_the_command_does_not_start_unless_a_commit_holds_the_plan_and_the_code(
    tmp_path, capsys, origin, said
):
    arxiv = ListingArxiv(MANY)
    code, population, drawn = run(tmp_path, arxiv=arxiv, origin=origin)

    assert code == 2 and said in capsys.readouterr().err
    assert arxiv.requests == [] and not population.exists() and not drawn.exists()


def test_a_plan_that_is_not_in_order_ends_the_command_before_any_request(tmp_path, capsys):
    arxiv = ListingArxiv(MANY)
    code, _, _ = run(tmp_path, arxiv=arxiv, plan=a_plan(**{"sample.per_archive": 0}))
    assert (
        code == 2
        and "cannot read the plan: plan.json: sample.per_archive" in capsys.readouterr().err
    )
    assert arxiv.requests == []


@pytest.mark.parametrize(
    ("extra", "said"),
    [
        (["--page-size", "0"], "--page-size: from 1 to 2000"),
        (["--page-size", "2001"], "--page-size: from 1 to 2000"),
        (["--only", "hep-ex"], "--only: no category hep-ex in the plan"),
        (["--only", " , "], "--only: name a category"),
    ],
)
def test_arguments_that_cannot_be_used_end_the_command_before_any_request(
    tmp_path, capsys, extra, said
):
    arxiv = ListingArxiv(MANY)
    code, _, _ = run(tmp_path, arxiv=arxiv, extra=extra)
    assert code == 2 and said in capsys.readouterr().err
    assert arxiv.requests == []


def test_without_a_place_to_write_to_the_command_does_not_start(tmp_path, capsys):
    plan_file = tmp_path / "plan.json"
    plan_file.write_text(json.dumps(a_plan()), encoding="utf-8")
    assert sample.main(["--plan", str(plan_file)], origin=committed) == 2
    assert "--population and --sample" in capsys.readouterr().err
    assert sample.main(["--plan", str(tmp_path / "none.json")], origin=committed) == 2


def no_commit(file: Path | None = None) -> dict:
    """What agent/origin.py says of a file that is in no repository."""
    return {"commit": None, "modified": None}


def test_a_first_try_asks_for_some_categories_and_writes_nothing(tmp_path, capsys):
    arxiv = ListingArxiv(MANY)

    # Not in a commit, and that is no matter: a first try leaves no file behind.
    code, population, drawn = run(
        tmp_path, arxiv=arxiv, origin=no_commit, extra=["--only", "hep-ph, astro-ph.CO"]
    )

    assert code == 0 and not population.exists() and not drawn.exists()
    assert {url.params["search_query"].split()[0] for url in arxiv.requests} == {
        "cat:hep-ph",
        "cat:astro-ph.CO",
    }
    printed = capsys.readouterr().out
    assert "[1/4] hep-ph 202608010000-202608312359 | 9 listed, 8 primary" in printed
    # What is kept (the first of each) and what is passed over as cross-listed.
    assert (
        "hep-ph: the primary categories of what was listed: hep-ph 8, astro-ph.GA 5, hep-th 1"
        in printed
    )
    assert (
        "astro-ph.CO: the primary categories of what was listed: astro-ph.CO 1, hep-th 1" in printed
    )
    assert "a first try with hep-ph, astro-ph.CO: 9 paper(s)" in printed
    assert "Nothing was drawn and nothing was written." in printed


def test_a_list_that_is_not_whole_leaves_no_file(tmp_path, capsys):
    arxiv = Spoilt(MANY, lambda count, start, body: (503, b"") if count > 2 else None)
    code, population, drawn = run(tmp_path, arxiv=arxiv)

    assert code == 1 and "stopped: astro-ph.GA 202608010000-202608312359: arXiv did not answer" in (
        capsys.readouterr().err
    )
    assert not population.exists() and not drawn.exists()


def test_stopping_the_listing_by_hand_leaves_no_file(tmp_path, capsys):
    def stop(count, start, body):
        if count == 3:
            raise KeyboardInterrupt
        return None

    code, population, drawn = run(tmp_path, arxiv=Spoilt(MANY, stop))

    assert (
        code == 130
        and "stopped by hand; what was received is kept on disk" in capsys.readouterr().err
    )
    assert not population.exists() and not drawn.exists()
    assert len(list((tmp_path / "cache").glob("*/*.body"))) == 2


def test_the_list_says_between_which_moments_arxiv_gave_it():
    # The answers of an earlier day are read from disk, so the list can be older than the run.
    def piece(category: str, *fetched: str) -> Piece:
        return Piece(category, PLAN.windows[0], 0, (), len(fetched), 0, fetched)

    pieces = (
        piece("hep-ph", "2026-11-25T09:00:00+00:00", "2026-11-25T09:00:03+00:00"),
        piece("astro-ph.GA", "2026-11-24T23:59:57+00:00"),
    )
    head = population_lines(Population(pieces, ()), {"name": "test-1"}, committed(), 1000)[0]
    assert head["asked"] == {
        "first": "2026-11-24T23:59:57+00:00",
        "last": "2026-11-25T09:00:03+00:00",
    }
    assert (head["pieces"], head["papers"]) == (2, 0)


def test_the_page_size_changes_the_requests_and_not_the_sample(tmp_path):
    small = ListingArxiv(MANY)
    _, _, one = run(tmp_path / "one", arxiv=small, extra=["--page-size", "2"])
    large = ListingArxiv(MANY)
    _, _, two = run(tmp_path / "two", arxiv=large)
    assert len(small.requests) > len(large.requests)
    assert read_sample(one).papers == read_sample(two).papers


# --- reading a sample back -------------------------------------------------------------------


def changed(path: Path, change) -> Path:
    """The sample with one thing done to its lines."""
    lines = lines_of(path)
    change(lines)
    path.write_text("".join(json.dumps(line) + "\n" for line in lines), encoding="utf-8")
    return path


def papers_at(lines: list[dict]) -> list[int]:
    return [at for at, line in enumerate(lines) if line["record"] == "paper"]


def swap(lines: list[dict]) -> None:
    first, second = papers_at(lines)[:2]
    lines[first], lines[second] = lines[second], lines[first]


def swap_with_ranks(lines: list[dict]) -> None:
    first, second = papers_at(lines)[:2]
    lines[first]["rank"], lines[second]["rank"] = lines[second]["rank"], lines[first]["rank"]
    swap(lines)


def put_in(lines: list[dict]) -> None:
    # A paper chosen by hand and put in with care: the hash that is truly its own, which
    # happens to come after the last one, and the next number.
    last = [at for at in papers_at(lines) if lines[at]["archive"] == "hep-ph"][-1]
    name = next(
        name
        for name in (f"2608.{number:05d}v1" for number in range(9000, 9999))
        if order_key(7, name) > lines[last]["sha256"]
    )
    line = dict(lines[last], id=name, rank=4, sha256=order_key(7, name))
    lines.insert(last + 1, line)
    next(each for each in lines if each.get("archive") == "hep-ph" and each["record"] == "archive")[
        "drawn"
    ] = 4


@pytest.mark.parametrize(
    ("change", "said"),
    [
        (
            lambda lines: lines[papers_at(lines)[0]].update(id="2608.00001v1"),
            "does not have the hash that seed 7 gives it",
        ),
        (lambda lines: lines[0].update(seed=8), "does not have the hash that seed 8 gives it"),
        (swap, "are not numbered from 1 on"),
        (swap_with_ranks, "are not in the order of their hashes"),
        (put_in, "4 papers of hep-ph, more than 3"),
        (lambda lines: lines.pop(papers_at(lines)[0]), "are not numbered from 1 on"),
        (
            lambda lines: lines.pop(papers_at(lines)[2]),
            "the count of hep-ph does not fit its 2 papers",
        ),
        (lambda lines: lines.append(dict(lines[papers_at(lines)[0]])), "is there twice"),
        (lambda lines: lines[papers_at(lines)[0]].update(id="2608.00001"), "names no version"),
        (
            lambda lines: lines[papers_at(lines)[0]].update(id="the first one"),
            "is not an arXiv identifier",
        ),
        (
            lambda lines: lines[papers_at(lines)[0]].update(primary="hep-th"),
            "hep-th is not a category of hep-ph",
        ),
        (
            lambda lines: lines[papers_at(lines)[0]].update(archive="hep"),
            "is not a category of hep",
        ),
        (lambda lines: lines[0].update(seed="7"), "does not name a seed"),
        (lambda lines: lines[0].update(record="population"), "does not say that it is a sample"),
        (
            lambda lines: [
                lines.pop(at)
                for at in reversed(papers_at(lines))
                if lines[at]["archive"] == "astro-ph"
            ],
            "the count of astro-ph does not fit its papers",
        ),
    ],
)
def test_a_sample_that_was_changed_by_hand_is_refused(tmp_path, change, said):
    _, _, drawn = run(tmp_path)
    assert read_sample(drawn).papers  # as the command wrote it, it is read
    with pytest.raises(RecordError) as caught:
        read_sample(changed(drawn, change))
    assert said in str(caught.value)


def test_a_file_that_is_no_record_is_refused_by_name(tmp_path):
    path = tmp_path / "sample.jsonl"
    path.write_text('{"record": "sample", "seed": 7, "per_archive": 3}\n[1]\n', encoding="utf-8")
    with pytest.raises(RecordError, match=r"sample\.jsonl line 2: not an object"):
        read_sample(path)
    path.write_text('{"record": "sample"}\nnot json\n', encoding="utf-8")
    with pytest.raises(RecordError, match=r"sample\.jsonl line 2: not JSON"):
        read_sample(path)
    path.write_text("", encoding="utf-8")
    with pytest.raises(RecordError, match="does not say that it is a sample"):
        read_sample(path)


def test_the_papers_the_several_pieces_share_are_listed_once(tmp_path):
    # The same small arXiv as in the tests of the list, through the command.
    code, population, drawn = run(tmp_path, arxiv=ListingArxiv(SEVERAL))
    assert code == 0
    assert [line["id"] for line in lines_of(population) if line["record"] == "paper"] == [
        "2608.00002v1",
        "2608.00003v1",
        "2609.00001v1",
        "2609.00004v1",
    ]
    assert {each.arxiv_id for each in read_sample(drawn).papers} == {
        "2608.00002v1",
        "2608.00003v1",
        "2609.00001v1",
        "2609.00004v1",
    }


def test_left_to_itself_the_command_asks_arxiv_under_its_own_name(tmp_path, monkeypatch):
    arxiv = ListingArxiv(MANY)
    built: list = []

    def fetcher(folder, user_agent):
        built.append((folder, user_agent))
        return arxiv.fetcher(folder)

    monkeypatch.setenv("HEPPH_PAPER_MINER_CACHE", str(tmp_path / "downloads"))
    monkeypatch.setattr(sample, "Fetcher", fetcher)
    plan_file = tmp_path / "plan.json"
    plan_file.write_text(json.dumps(a_plan()), encoding="utf-8")
    argv = ["--plan", str(plan_file), "--population", str(tmp_path / "p.jsonl")]

    assert sample.main([*argv, "--sample", str(tmp_path / "s.jsonl")], origin=committed) == 0

    assert built == [(tmp_path / "downloads", "hepph-paper-miner/survey")]
    assert len(read_sample(tmp_path / "s.jsonl").papers) == 6
    assert len(list((tmp_path / "downloads").glob("*/*.body"))) == 4  # the pieces with papers
