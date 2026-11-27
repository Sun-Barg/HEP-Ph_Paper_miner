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

The command writes the places to draft about, one line each, for one of two uses:

    uv run python -m hepph_paper_miner.drafting.assign --tuning eval_data/target_papers.txt \\
        --round 1 --out runs_private/drafting/round-1/places.jsonl

        The papers that the texts of the generator are written on (they are the papers of
        the first evaluation, which the owner knows well). They stand in the order of the
        survey's hash, and a round takes the next six of them: 1 to 6, then 7 to 12. The
        last round takes every paper that no round before it took (--last with round 2,
        or round 3), so that the texts are tried last on papers they were not fitted to.
        A paper gets one place of every kind it has, search_first aside: with one draft a
        paper, a round would have six drafts, and a share of six says little.

    uv run python -m hepph_paper_miner.drafting.assign --sample results/archives/sample.jsonl \\
        --outcomes results/archives/outcomes.jsonl --out results/archives/places.jsonl

        The papers of the second evaluation: `assign` above, twelve drafts for every kind
        and archive (PER_KIND), which is a place for each of the sixty papers of an
        archive. A paper with a named_first place is looked up first: whether arXiv lists
        the version of the sample as its latest one, and at which rank a search for its
        title lists it. That search is the only use of the network here.

Papers are read through the folder of downloads, as the tools read them. The file holds
identifiers, kinds, section identifiers, places and counts, and no text of a paper: no
title either, and not the words a search was made with.
"""

from __future__ import annotations

import argparse
import hashlib
import sys
from collections import Counter
from collections.abc import Callable, Collection, Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from hepph_paper_miner.agent.origin import code_version, file_digest
from hepph_paper_miner.drafting.places import (
    APPENDIX,
    KINDS,
    LATER_PIECE,
    NAMED_FIRST,
    OWN_TEXT,
    SEARCH_FIRST,
    Place,
    places_of,
)
from hepph_paper_miner.sources.arxiv_latex import PARSER_VERSION
from hepph_paper_miner.sources.base import (
    ArxivId,
    Paper,
    PaperSource,
    SearchQuery,
    SourceError,
    parse_arxiv_id,
)
from hepph_paper_miner.survey.plan import PlanError, load_plan
from hepph_paper_miner.survey.records import RecordError, now, read_lines, write_lines
from hepph_paper_miner.survey.run import OK, read_outcomes, walk
from hepph_paper_miner.survey.sample import Drawn, order_key, read_sample


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


# The drafts of each kind that an archive of the second evaluation is to have. The design
# began with six, for the forty papers of places 41 to 80. The last round of the tuning
# then left an accepted draft in 8 of its 27 places, so the plan took the papers as far as
# place 100 and has a place for every one of them: five kinds of twelve are the sixty
# papers of an archive (eval_data/PREREGISTRATION_2.md, Section 3).
PER_KIND = 12


# --- the papers the texts are written on --------------------------------------------------

PER_ROUND = 6
ROUNDS = 3
# The kinds a paper of the tuning is given a place of: every kind that is a place of its
# own. search_first is a named_first place asked about by its title (places.py), and
# whether a search finds a paper is no question of the texts.
TUNING_KINDS = (LATER_PIECE, APPENDIX, OWN_TEXT, NAMED_FIRST)


def tuning_order(papers: Sequence[str], seed: int) -> list[str]:
    """The papers of the tuning in the order of the survey's hash, smallest first."""
    return sorted(papers, key=lambda paper: (order_key(seed, paper), paper))


def round_positions(round_: int, last: bool, count: int) -> range:
    """The places in that order that a round takes, from 1.

    Round 1 takes 1 to 6 and round 2 takes 7 to 12. The last round takes every place
    that no round before it took: round 2 with `last`, or round 3. There is no fourth.
    """
    if not 1 <= round_ <= ROUNDS:
        raise ValueError(f"there are rounds 1 to {ROUNDS}, not {round_}")
    if round_ == 1 and last:
        raise ValueError("round 1 cannot be the last: the last round takes papers no round took")
    first = PER_ROUND * (round_ - 1) + 1
    final = count if (last or round_ == ROUNDS) else min(count, PER_ROUND * round_)
    return range(first, final + 1)


def one_of_each(paper: str, places: Sequence[Place], seed: int) -> list[Place]:
    """One place of every kind of TUNING_KINDS that a paper has, chosen as `assign` chooses."""
    chosen = []
    for kind in TUNING_KINDS:
        candidates = [place for place in places if place.kind == kind]
        if candidates:
            chosen.append(
                min(
                    candidates,
                    key=lambda place: (place_key(seed, paper, place.section), place.start),
                )
            )
    return chosen


# --- the file of places -------------------------------------------------------------------


@dataclass(frozen=True)
class Placed:
    """A place to draft a question about, as the file of places names it."""

    number: int  # from 1, in the order of the file
    archive: str  # "" for a paper of the tuning
    rank: int  # its place in the order the papers were taken in
    paper: str  # with the version
    kind: str  # of KINDS
    section: str
    start: int
    end: int

    @property
    def chars(self) -> int:
        return self.end - self.start

    def as_line(self) -> dict[str, Any]:
        return {
            "record": "place",
            "number": self.number,
            "archive": self.archive,
            "rank": self.rank,
            "paper": self.paper,
            "kind": self.kind,
            "section": self.section,
            "start": self.start,
            "end": self.end,
            "chars": self.chars,
        }


@dataclass(frozen=True)
class PlacesFile:
    head: dict[str, Any]
    places: tuple[Placed, ...]
    sha256: str
    name: str

    @property
    def stamp(self) -> dict[str, Any]:
        """How another record names this file."""
        return {"file": self.name, "sha256": self.sha256}


def read_places(path: Path) -> PlacesFile:
    """The places of a file that this command wrote, or RecordError."""
    lines, digest = read_lines(path, "places")
    found: list[Placed] = []
    for line in lines[1:]:
        if line.get("record") != "place":
            continue
        numbers = {name: line.get(name) for name in ("number", "rank", "start", "end")}
        texts = {name: line.get(name) for name in ("archive", "paper", "kind", "section")}
        if not all(isinstance(v, int) and not isinstance(v, bool) for v in numbers.values()):
            raise RecordError(f"{path.name}: a place without its numbers")
        if not all(isinstance(text, str) for text in texts.values()) or texts["kind"] not in KINDS:
            raise RecordError(f"{path.name}: a place without its paper, kind or section")
        found.append(Placed(**numbers, **texts))
    if [place.number for place in found] != list(range(1, len(found) + 1)):
        raise RecordError(f"{path.name}: the places are not numbered 1, 2, 3, ... in order")
    return PlacesFile(lines[0], tuple(found), digest, path.name)


def _placed(number: int, archive: str, rank: int, paper: str, kind: str, place: Place) -> Placed:
    return Placed(number, archive, rank, paper, kind, place.section, place.start, place.end)


def _counts(places: Iterable[Place]) -> dict[str, int]:
    found = Counter(place.kind for place in places)
    return {kind: found[kind] for kind in KINDS if found[kind]}


# --- whether a search for its title finds a paper -----------------------------------------


@dataclass(frozen=True)
class Lookup:
    findable: bool
    latest: bool | None  # whether arXiv lists the version of the sample as its latest one
    rank: int | None  # where the search for the title listed the paper, from 1
    problem: str | None  # what went wrong on the way, as a kind of failure


def look_up(source: PaperSource, paper: Paper, results: int = 5) -> Lookup:
    """Whether a search for the title of a paper, as arXiv lists it, finds that very paper.

    The search goes the way search_papers sends it (ArxivSource.search), with the number
    of results the tool gives by default. Only the rank is kept: the title is paper text.
    """
    wanted = parse_arxiv_id(paper.meta.arxiv_id)
    try:
        latest = source.listing(ArxivId(wanted.base, None))
    except SourceError as error:
        return Lookup(False, None, None, error.kind.value)
    if parse_arxiv_id(latest.arxiv_id) != wanted:
        # The search lists the latest version, and its title may not be the one the
        # question would name.
        return Lookup(False, False, None, None)
    try:
        found = source.search(SearchQuery(query=paper.meta.title, max_results=results))
    except SourceError as error:
        return Lookup(False, True, None, error.kind.value)
    for at, listed in enumerate(found.papers, start=1):
        if parse_arxiv_id(listed.arxiv_id).base == wanted.base:
            return Lookup(True, True, at, None)
    return Lookup(False, True, None, None)


# --- the command ---------------------------------------------------------------------------


def tuning_lines(
    source: PaperSource,
    target_file: Path,
    round_: int,
    last: bool,
    seed: int,
    code: Mapping[str, Any],
    echo: Callable[[str], None] = print,
) -> list[dict[str, Any]]:
    """The file of places of one round of the tuning."""
    named = [
        line.strip()
        for line in target_file.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]
    for each in named:
        if parse_arxiv_id(each).version is None:
            raise ValueError(f"{target_file.name}: {each} names no version")
    ordered = tuning_order(named, seed)
    positions = round_positions(round_, last, len(ordered))
    head = {
        "record": "places",
        "input": "tuning",
        "papers": {"file": target_file.name, "sha256": file_digest(target_file)},
        "round": round_,
        "last": last or round_ == ROUNDS,
        "positions": [positions.start, positions.stop - 1],
        "seed": seed,
        "parser_version": PARSER_VERSION,
        "code": dict(code),
        "made": now(),
    }
    papers, places = [], []
    for rank in positions:
        paper_id = ordered[rank - 1]
        line: dict[str, Any] = {"record": "paper", "rank": rank, "id": paper_id}
        try:
            paper = source.paper(parse_arxiv_id(paper_id))
        except SourceError as error:
            papers.append({**line, "outcome": error.kind.value})
            echo(f"  {rank} {paper_id}: {error.kind.value}")
            continue
        found = places_of(paper)
        papers.append({**line, "outcome": OK, "places": _counts(found)})
        for place in one_of_each(paper_id, found, seed):
            places.append(_placed(len(places) + 1, "", rank, paper_id, place.kind, place))
        echo(f"  {rank} {paper_id}: {', '.join(f'{k} {n}' for k, n in _counts(found).items())}")
    return [head, *papers, *(place.as_line() for place in places)]


def sample_lines(
    source: PaperSource,
    sample_file: Path,
    outcomes_file: Path,
    per_kind: int,
    code: Mapping[str, Any],
    echo: Callable[[str], None] = print,
) -> list[dict[str, Any]]:
    """The file of places of the second evaluation."""
    sample = read_sample(sample_file)
    outcomes_head, outcomes = read_outcomes(outcomes_file)
    if (outcomes_head.get("sample") or {}).get("sha256") != sample.sha256:
        raise RecordError(f"{outcomes_file.name} is not what survey.run made of {sample_file.name}")
    if outcomes_head.get("parser_version") != PARSER_VERSION:
        raise RecordError(f"{outcomes_file.name} was made by another parser")
    if outcomes_head.get("unanswered"):
        # survey.run asks again for these; no draft is made while a paper is left so.
        raise RecordError(f"{outcomes_file.name} has papers that arXiv did not answer")
    outcome = {line["id"]: line["outcome"] for line in outcomes}
    missing = [drawn.arxiv_id for drawn in sample.papers if drawn.arxiv_id not in outcome]
    if missing:
        raise RecordError(f"{outcomes_file.name} has no line for {missing[0]} of the sample")
    seed = sample.head["seed"]
    head = {
        "record": "places",
        "input": "sample",
        "sample": {"file": sample_file.name, "sha256": sample.sha256},
        "outcomes": {"file": outcomes_file.name, "sha256": file_digest(outcomes_file)},
        "seed": seed,
        "per_kind": per_kind,
        "parser_version": PARSER_VERSION,
        "code": dict(code),
        "made": now(),
    }
    order = walk(sample.papers)
    found: dict[str, list[Place]] = {}
    findable: set[str] = set()
    papers: list[dict[str, Any]] = []
    for drawn in order:
        line: dict[str, Any] = {
            "record": "paper",
            "archive": drawn.archive,
            "rank": drawn.rank,
            "id": drawn.arxiv_id,
            "outcome": outcome.get(drawn.arxiv_id),
        }
        if line["outcome"] != OK:
            papers.append(line)
            continue
        try:
            paper = source.paper(parse_arxiv_id(drawn.arxiv_id))
        except SourceError as error:
            raise RecordError(
                f"{drawn.arxiv_id} was split by survey.run and is not now: {error}"
            ) from error
        found[drawn.arxiv_id] = places_of(paper)
        line["places"] = _counts(found[drawn.arxiv_id])
        if any(place.kind == NAMED_FIRST for place in found[drawn.arxiv_id]):
            looked = look_up(source, paper)
            line["search"] = {
                "findable": looked.findable,
                "latest": looked.latest,
                "rank": looked.rank,
                "problem": looked.problem,
            }
            if looked.findable:
                findable.add(drawn.arxiv_id)
        papers.append(line)
        echo(f"  {drawn.archive} {drawn.rank}: {line['places']}")
    given = assign(order, found, findable, seed, per_kind)
    placed = [
        _placed(number, each.archive, each.rank, each.paper, each.kind, each.place)
        for number, each in enumerate(given, start=1)
    ]
    archives = []
    for archive in dict.fromkeys(drawn.archive for drawn in order):
        filled = Counter(each.kind for each in placed if each.archive == archive)
        archives.append(
            {
                "record": "archive",
                "archive": archive,
                "filled": {kind: filled[kind] for kind in KINDS},
                "missing": {kind: max(0, per_kind - filled[kind]) for kind in KINDS},
            }
        )
    return [head, *papers, *archives, *(place.as_line() for place in placed)]


def paper_source() -> PaperSource:
    """The papers as the tools read them: from arXiv, through the folder of downloads.

    A paper that a run or the survey read is on the disk, so it is read from there.
    """
    from hepph_paper_miner import __version__
    from hepph_paper_miner.http import Fetcher, default_cache_dir
    from hepph_paper_miner.server import SERVER_NAME
    from hepph_paper_miner.sources.arxiv import ArxivSource

    return ArxivSource(Fetcher(default_cache_dir(), user_agent=f"{SERVER_NAME}/{__version__}"))


def main(argv: Sequence[str] | None = None, source: PaperSource | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m hepph_paper_miner.drafting.assign",
        description="Write the places to draft questions about: for a round of the tuning, "
        "or for the papers of the second evaluation.",
    )
    parser.add_argument("--tuning", type=Path, help="the papers the texts are written on")
    parser.add_argument("--round", type=int, help=f"the round of the tuning, 1 to {ROUNDS}")
    parser.add_argument(
        "--last", action="store_true", help="the last round: every paper no round before took"
    )
    parser.add_argument(
        "--plan",
        type=Path,
        default=Path("eval_data/survey_plan.json"),
        help="the plan of the survey, for its seed (default: %(default)s)",
    )
    parser.add_argument("--sample", type=Path, help="the sample of the second evaluation")
    parser.add_argument("--outcomes", type=Path, help="what survey.run made of that sample")
    parser.add_argument(
        "--per-kind",
        type=int,
        default=PER_KIND,
        help="drafts of each kind an archive (default: %(default)s)",
    )
    parser.add_argument("--out", type=Path, required=True, help="the file of places to write")
    arguments = parser.parse_args(argv)

    tuning = arguments.tuning is not None
    if tuning == (arguments.sample is not None or arguments.outcomes is not None):
        print("give either --tuning with --round, or --sample with --outcomes", file=sys.stderr)
        return 2
    if tuning and arguments.round is None:
        print("--tuning needs --round", file=sys.stderr)
        return 2
    if not tuning and (arguments.sample is None or arguments.outcomes is None):
        print("--sample needs --outcomes, and --outcomes needs --sample", file=sys.stderr)
        return 2
    if arguments.out.exists():
        print(f"refused: {arguments.out} is there already; move it away first", file=sys.stderr)
        return 1
    code = code_version()
    if code["modified"] is not False:
        # The file names the commit that made it, as every record of the repository does.
        print(
            "refused: the code has changes that are not committed, or git cannot name it",
            file=sys.stderr,
        )
        return 1
    source = source or paper_source()
    try:
        if tuning:
            seed = load_plan(arguments.plan).seed
            lines = tuning_lines(
                source, arguments.tuning, arguments.round, arguments.last, seed, code
            )
        else:
            lines = sample_lines(
                source, arguments.sample, arguments.outcomes, arguments.per_kind, code
            )
    except (OSError, ValueError, PlanError, RecordError, SourceError) as error:
        print(f"refused: {error}", file=sys.stderr)
        return 1
    digest = write_lines(arguments.out, lines)
    placed = [line for line in lines if line["record"] == "place"]
    kinds = Counter(line["kind"] for line in placed)
    print(
        f"{len(placed)} place(s) written to {arguments.out} (SHA-256 {digest[:16]}): "
        + ", ".join(f"{kind} {kinds[kind]}" for kind in KINDS if kinds[kind])
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
