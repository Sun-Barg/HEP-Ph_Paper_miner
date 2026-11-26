"""Which place every paper is given: one question a paper, by a rule that no choice enters.

Every archive is to have as many drafts of each kind as the plan names. The papers of an
archive are taken in the order of the survey's walk, and a paper gets the first kind of
KINDS (the rarest first) that it has a place of and that its archive still lacks.
search_first needs a paper that a search for its title finds (`findable`), because such a
question names its paper by the title alone. Within a paper, of the places of that kind,
the one with the smallest SHA-256 of "<seed>:<paper>:<section>" is taken.

A kind that the papers of an archive cannot fill leaves what is missing to named_first:
a second pass goes through the papers that got nothing, in the same order. What cannot
be filled even so is left unfilled and can be counted from what comes back.

One question for a paper, because questions about one paper are not independent: they
share the way the paper was split and read. With one each, a count of questions is a
count of papers.
"""

from __future__ import annotations

import hashlib
from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass

from hepph_paper_miner.drafting.places import KINDS, NAMED_FIRST, SEARCH_FIRST, Place
from hepph_paper_miner.survey.sample import Drawn


@dataclass(frozen=True)
class Given:
    archive: str
    rank: int
    paper: str  # with the version that the list named
    kind: str  # of KINDS: search_first for a named_first place asked about by title
    place: Place


def place_key(seed: int, paper: str, section: str) -> str:
    """What decides between the places of one kind in one paper."""
    return hashlib.sha256(f"{seed}:{paper}:{section}".encode()).hexdigest()


def assign(
    papers: Sequence[Drawn],
    places: Mapping[str, Sequence[Place]],
    findable: Collection[str],
    seed: int,
    per_kind: int,
) -> list[Given]:
    """Kind and place for the papers that get one, in the order of the walk.

    `places` is keyed by the identifier of a paper (places.places_of): a paper that was
    not split has none. `findable` holds the papers that a search for their title finds.
    """
    archives = list(dict.fromkeys(paper.archive for paper in papers))
    given: list[Given] = []
    for archive in archives:
        own = sorted((paper for paper in papers if paper.archive == archive), key=_rank)
        need = dict.fromkeys(KINDS, per_kind)
        taken: dict[str, Given] = {}
        for paper in own:
            for kind in KINDS:
                if need[kind] == 0:
                    continue
                place = _choose(paper, kind, places, findable, seed)
                if place is not None:
                    taken[paper.arxiv_id] = Given(archive, paper.rank, paper.arxiv_id, kind, place)
                    need[kind] -= 1
                    break
        # What the other kinds could not fill goes to named_first, the kind most
        # papers have: so many drafts an archive still come, of the commonest kind.
        more = sum(count for kind, count in need.items() if kind != NAMED_FIRST)
        need = {NAMED_FIRST: need[NAMED_FIRST] + more}
        for paper in own:
            if need[NAMED_FIRST] == 0:
                break
            if paper.arxiv_id in taken:
                continue
            place = _choose(paper, NAMED_FIRST, places, findable, seed)
            if place is not None:
                taken[paper.arxiv_id] = Given(
                    archive, paper.rank, paper.arxiv_id, NAMED_FIRST, place
                )
                need[NAMED_FIRST] -= 1
        given += taken.values()
    return sorted(given, key=lambda each: (each.rank, archives.index(each.archive)))


def _rank(paper: Drawn) -> int:
    return paper.rank


def _choose(
    paper: Drawn,
    kind: str,
    places: Mapping[str, Sequence[Place]],
    findable: Collection[str],
    seed: int,
) -> Place | None:
    if kind == SEARCH_FIRST and paper.arxiv_id not in findable:
        return None
    wanted = NAMED_FIRST if kind == SEARCH_FIRST else kind
    candidates = [place for place in places.get(paper.arxiv_id, ()) if place.kind == wanted]
    if not candidates:
        return None
    return min(
        candidates,
        key=lambda place: (place_key(seed, paper.arxiv_id, place.section), place.start),
    )
