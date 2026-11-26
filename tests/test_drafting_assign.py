"""Which place every paper is given (drafting/assign.py)."""

import hashlib
import random
from collections import Counter

from hepph_paper_miner.drafting.assign import assign, place_key
from hepph_paper_miner.drafting.places import (
    APPENDIX,
    KINDS,
    LATER_PIECE,
    NAMED_FIRST,
    OWN_TEXT,
    SEARCH_FIRST,
    Place,
)
from hepph_paper_miner.survey.sample import Drawn

SEED = 20261124
ARCHIVES = ("hep-ph", "hep-th", "hep-ex", "astro-ph")

ONE_OF_EACH = [
    Place(LATER_PIECE, "2.2", 19_950, 29_960),
    Place(APPENDIX, "A", 0, 3_500),
    Place(OWN_TEXT, "2", 0, 2_520),
    Place(NAMED_FIRST, "1", 0, 2_800),
]
NAMED = Place(NAMED_FIRST, "1", 0, 2_800)


def papers_of(archive: str, ranks) -> list[Drawn]:
    month = 2608 + ARCHIVES.index(archive)
    return [Drawn(archive, rank, f"{month}.{rank:05d}v1", archive, "") for rank in ranks]


def test_the_rarest_kind_comes_first():
    papers = papers_of("hep-ph", range(41, 46))
    places = {paper.arxiv_id: ONE_OF_EACH for paper in papers}
    findable = {paper.arxiv_id for paper in papers}
    given = assign(papers, places, findable, SEED, per_kind=1)
    # Written out, not read from KINDS: the order is the rule, so the test names it.
    rarest_first = [LATER_PIECE, APPENDIX, OWN_TEXT, SEARCH_FIRST, NAMED_FIRST]
    assert [(each.rank, each.kind) for each in given] == list(zip(range(41, 46), rarest_first))
    assert list(KINDS) == rarest_first
    assert given[3].place == NAMED  # search_first asks about a named_first place


def test_search_first_needs_a_paper_that_its_title_finds():
    papers = papers_of("hep-ph", range(41, 45))
    places = {paper.arxiv_id: [NAMED] for paper in papers}
    given = assign(papers, places, {papers[2].arxiv_id}, SEED, per_kind=1)
    # 41 cannot be found by its title and takes named_first; 43 can and takes search_first.
    # The three kinds that nobody has leave their three drafts to named_first: 42 and 44.
    assert {each.rank: each.kind for each in given} == {
        41: NAMED_FIRST,
        42: NAMED_FIRST,
        43: SEARCH_FIRST,
        44: NAMED_FIRST,
    }


def test_what_a_kind_cannot_fill_goes_to_named_first():
    papers = papers_of("hep-th", range(41, 61))
    places = {paper.arxiv_id: [NAMED] for paper in papers}
    for paper in papers[:2]:
        places[paper.arxiv_id] = [ONE_OF_EACH[0], NAMED]
    given = assign(papers, places, set(), SEED, per_kind=3)
    # Two later pieces of three, and no appendix, own text or findable title: the
    # ten drafts that are missing go to named_first, which had three of its own.
    assert Counter(each.kind for each in given) == {LATER_PIECE: 2, NAMED_FIRST: 13}
    assert [each.rank for each in given] == list(range(41, 56))


def test_what_cannot_be_filled_even_so_is_left_unfilled():
    papers = papers_of("hep-ex", range(41, 45))
    places = {paper.arxiv_id: [NAMED] for paper in papers[:3]}  # the last was not split
    given = assign(papers, places, set(), SEED, per_kind=2)
    assert [(each.rank, each.kind) for each in given] == [(r, NAMED_FIRST) for r in (41, 42, 43)]


def test_within_a_paper_the_smallest_hash_decides():
    (paper,) = papers_of("astro-ph", [41])
    candidates = [Place(NAMED_FIRST, section, 0, 2_000) for section in ("1", "2", "3.1", "u1")]
    (given,) = assign([paper], {paper.arxiv_id: candidates}, set(), SEED, per_kind=1)

    def digest(section):
        return hashlib.sha256(f"{SEED}:{paper.arxiv_id}:{section}".encode()).hexdigest()

    assert given.place == min(candidates, key=lambda place: digest(place.section))
    assert place_key(SEED, paper.arxiv_id, "3.1") == digest("3.1")
    # Another seed is another choice for some paper: the hash is what decides.
    seeds = {
        assign([paper], {paper.arxiv_id: candidates}, set(), seed, per_kind=1)[0].place
        for seed in range(20)
    }
    assert len(seeds) > 1


def test_every_archive_is_filled_for_itself_and_the_order_of_the_papers_does_not_matter():
    rng = random.Random(7)
    papers = [paper for archive in ARCHIVES for paper in papers_of(archive, range(41, 81))]
    places = {
        paper.arxiv_id: rng.sample(ONE_OF_EACH, rng.randint(1, 4)) + [NAMED] for paper in papers
    }
    findable = {paper.arxiv_id for paper in papers if rng.random() < 0.5}
    given = assign(papers, places, findable, SEED, per_kind=6)
    for archive in ARCHIVES:
        own = [each for each in given if each.archive == archive]
        assert len(own) == 30 and len({each.paper for each in own}) == 30
    shuffled = list(papers)
    rng.shuffle(shuffled)
    again = assign(shuffled, places, findable, SEED, per_kind=6)

    def key(each):
        return each.archive, each.rank

    assert sorted(again, key=key) == sorted(given, key=key)


def test_the_given_come_in_the_order_of_the_walk():
    papers = papers_of("hep-ph", range(41, 44)) + papers_of("hep-th", range(41, 44))
    places = {paper.arxiv_id: [NAMED] for paper in papers}
    given = assign(papers, places, set(), SEED, per_kind=1)
    assert [(each.rank, each.archive) for each in given] == [
        (41, "hep-ph"),
        (41, "hep-th"),
        (42, "hep-ph"),
        (42, "hep-th"),
        (43, "hep-ph"),
        (43, "hep-th"),
    ]
