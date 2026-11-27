"""Draw the sample of the survey from arXiv's list, and write down the list and the sample.

    uv run python -m hepph_paper_miner.survey.sample --plan eval_data/survey_plan.json \\
        --population results/survey/population.jsonl --sample results/survey/sample.jsonl

The command asks arXiv for every piece of the plan (listing.py: a request every three
seconds and 153 pieces for the plan of the repository, so eight minutes at the least
the first time, and nothing once the answers are on disk), keeps the papers that have a
category of the plan as their primary one, and draws from every archive the number of
papers the plan names.

The order of the draw. Every paper gets the SHA-256 of "<seed>:<its identifier without
the version>", and the papers of an archive are taken from the smallest value up. No
random number generator is in it, so the order does not rest on how some library is
written: with the list and the seed, anyone can work it out again, in any language. A
larger sample drawn later holds the smaller one, because both are the front of one
order. And the place of a paper does not move when its authors replace it, since the
version is not part of what is hashed.

It writes two files, and refuses to write over one that is there. The population file
names every paper the sample could have held: its identifier with the version the list
gave (the survey reads that very version), its primary category and the time of its
first version. The sample file names the papers that were drawn, each with its place in
the order and its hash, and the population file by its SHA-256. Both hold identifiers,
categories, dates and counts, and nothing of a paper's text, title or abstract.

Both name the plan and the commit it belongs to. The command does not start when the
plan is not a file of the repository, or when a file the repository keeps has been
changed: the plan has to be in a commit before the papers are drawn, or nothing shows
that the rule came first.

    --only hep-lat,nucl-ex    a first try: ask for these categories, say what came back
                              and under which primary categories, write nothing
"""

from __future__ import annotations

import argparse
import hashlib
import sys
from collections import Counter
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from hepph_paper_miner.agent.origin import code_version
from hepph_paper_miner.http import Fetcher, default_cache_dir
from hepph_paper_miner.sources.base import SourceError, parse_arxiv_id
from hepph_paper_miner.survey.listing import (
    MAX_PAGE_SIZE,
    PAGE_SIZE,
    Listed,
    ListingError,
    Population,
    list_population,
)
from hepph_paper_miner.survey.plan import ORDER, Plan, PlanError, load_plan
from hepph_paper_miner.survey.records import RecordError, now, read_lines, write_lines

USER_AGENT = "hepph-paper-miner/survey"


@dataclass(frozen=True)
class Drawn:
    """A paper of the sample."""

    archive: str
    rank: int  # its place in the order of its archive, from 1
    arxiv_id: str  # with the version the list named
    primary: str
    sha256: str  # what put it in that place


@dataclass(frozen=True)
class Sample:
    head: Mapping[str, Any]
    counts: Mapping[str, Mapping[str, Any]]  # by archive: listed, primary, drawn
    papers: tuple[Drawn, ...]  # archive by archive, each in its order
    sha256: str  # of the file


def order_key(seed: int, arxiv_id: str) -> str:
    """What a paper is ordered by: the SHA-256 of the seed and its identifier without version."""
    base = parse_arxiv_id(arxiv_id).base
    return hashlib.sha256(f"{seed}:{base}".encode()).hexdigest()


def draw(papers: Iterable[Listed], plan: Plan) -> list[Drawn]:
    """From every archive of the plan, the papers at the front of the order.

    All of them when an archive has fewer than the plan asks for. The order in which
    the papers are given makes no difference.
    """
    papers = list(papers)
    drawn: list[Drawn] = []
    for archive, categories in plan.archives.items():
        hashed = [
            (order_key(plan.seed, paper.arxiv_id), paper)
            for paper in papers
            if paper.primary in categories
        ]
        # Two papers with one hash have not been seen. They would still need an order.
        hashed.sort(key=lambda pair: (pair[0], pair[1].arxiv_id))
        for rank, (key, paper) in enumerate(hashed[: plan.per_archive], start=1):
            drawn.append(Drawn(archive, rank, paper.arxiv_id, paper.primary, key))
    return drawn


def counts_by_archive(
    population: Population, drawn: Sequence[Drawn], plan: Plan
) -> dict[str, dict[str, int]]:
    """For each archive: what the API listed for its categories (a paper once for every
    category it is listed in, cross-listings too), how many of them have their primary
    category there, and how many of those were drawn."""
    counts = {archive: {"listed": 0, "primary": 0, "drawn": 0} for archive in plan.archives}
    for piece in population.pieces:
        archive = plan.archive_of(piece.category)
        counts[archive]["listed"] += piece.total
        counts[archive]["primary"] += len(piece.own)
    for paper in drawn:
        counts[paper.archive]["drawn"] += 1
    return counts


def population_lines(
    population: Population, plan_stamp: Mapping[str, Any], code: Mapping[str, Any], page_size: int
) -> list[dict[str, Any]]:
    times = sorted(when for piece in population.pieces for when in piece.fetched)
    head = {
        "record": "population",
        "plan": dict(plan_stamp),
        "code": dict(code),
        "page_size": page_size,
        # arXiv's answers are kept on disk, so these are the days the list is of,
        # however much later it is read again.
        "asked": {"first": times[0] if times else "", "last": times[-1] if times else ""},
        "pieces": len(population.pieces),
        "papers": len(population.papers),
    }
    pieces = [
        {
            "record": "piece",
            "category": piece.category,
            "first": piece.window.first,
            "last": piece.window.last,
            "total": piece.total,
            "primary": len(piece.own),
            "pages": piece.pages,
        }
        for piece in population.pieces
    ]
    papers = [
        {
            "record": "paper",
            "id": paper.arxiv_id,
            "primary": paper.primary,
            "published": paper.published,
        }
        for paper in population.papers
    ]
    return [head, *pieces, *papers]


def sample_lines(
    drawn: Sequence[Drawn],
    counts: Mapping[str, Mapping[str, int]],
    plan: Plan,
    plan_stamp: Mapping[str, Any],
    code: Mapping[str, Any],
    population: Mapping[str, Any],
) -> list[dict[str, Any]]:
    head = {
        "record": "sample",
        "plan": dict(plan_stamp),
        "code": dict(code),
        "population": dict(population),
        "per_archive": plan.per_archive,
        "seed": plan.seed,
        "order": ORDER,
        "drawn": now(),
    }
    archives = [{"record": "archive", "archive": name, **counts[name]} for name in plan.archives]
    papers = [
        {
            "record": "paper",
            "archive": paper.archive,
            "rank": paper.rank,
            "id": paper.arxiv_id,
            "primary": paper.primary,
            "sha256": paper.sha256,
        }
        for paper in drawn
    ]
    return [head, *archives, *papers]


def read_sample(path: Path) -> Sample:
    """The sample in a file, or RecordError.

    Checked as far as the file can be checked without the list it came from: every
    paper has the hash the seed gives it, the papers of an archive stand in the order
    of their hashes and are numbered from 1, and the counts fit. A sample with a paper
    put in by hand, or moved, is refused.

    A sample can also be a later stretch of the order: its first line then says at
    which place it begins (`first`), and its papers are numbered from there. The
    second evaluation asks about places 41 to 100 (drafting/papers.py), which the
    survey's sample does not hold. A file without `first` begins at the front.
    """
    lines, digest = read_lines(path, "sample")
    head = lines[0]
    seed, per_archive = head.get("seed"), head.get("per_archive")
    if (
        isinstance(seed, bool)
        or not isinstance(seed, int)
        or isinstance(per_archive, bool)
        or not isinstance(per_archive, int)
    ):
        raise RecordError(
            f"{path.name}: its first line does not name a seed and a number of papers"
        )
    first = head.get("first", 1)
    if isinstance(first, bool) or not isinstance(first, int) or first < 1:
        raise RecordError(f"{path.name}: its first line names no place to begin at")
    counts = {line.get("archive"): line for line in lines[1:] if line.get("record") == "archive"}
    papers: list[Drawn] = []
    seen: set[str] = set()
    for line in (line for line in lines[1:] if line.get("record") == "paper"):
        name = line.get("id")
        where = f"{path.name}: {name!r}"
        try:
            arxiv_id = parse_arxiv_id(name if isinstance(name, str) else "")
        except SourceError:
            raise RecordError(f"{where} is not an arXiv identifier") from None
        if arxiv_id.version is None:
            raise RecordError(f"{where} names no version")
        if arxiv_id.base in seen:
            raise RecordError(f"{where} is there twice")
        seen.add(arxiv_id.base)
        archive, primary = line.get("archive"), line.get("primary")
        if not isinstance(archive, str) or not isinstance(primary, str):
            raise RecordError(f"{where} names no archive or no primary category")
        if primary != archive and not primary.startswith(archive + "."):
            raise RecordError(f"{where}: {primary} is not a category of {archive}")
        if line.get("sha256") != order_key(seed, name):
            raise RecordError(f"{where} does not have the hash that seed {seed} gives it")
        papers.append(Drawn(archive, line.get("rank"), name, primary, line["sha256"]))
    for archive in dict.fromkeys(paper.archive for paper in papers):
        own = [paper for paper in papers if paper.archive == archive]
        if [paper.rank for paper in own] != list(range(first, first + len(own))):
            raise RecordError(
                f"{path.name}: the papers of {archive} are not numbered from {first} on"
            )
        if own != sorted(own, key=lambda paper: (paper.sha256, paper.arxiv_id)):
            raise RecordError(
                f"{path.name}: the papers of {archive} are not in the order of their hashes"
            )
        if len(own) > per_archive:
            raise RecordError(
                f"{path.name}: {len(own)} papers of {archive}, more than {per_archive}"
            )
        if (counts.get(archive) or {}).get("drawn") != len(own):
            raise RecordError(
                f"{path.name}: the count of {archive} does not fit its {len(own)} papers"
            )
    for archive, line in counts.items():
        if line.get("drawn") != sum(1 for paper in papers if paper.archive == archive):
            raise RecordError(f"{path.name}: the count of {archive} does not fit its papers")
    return Sample(head, counts, tuple(papers), digest)


def _table(counts: Mapping[str, Mapping[str, int]], plan: Plan) -> list[str]:
    lines = [f"{'archive':<10} {'listed':>8} {'primary':>8} {'drawn':>6}"]
    for archive, count in counts.items():
        short = ""
        if count["drawn"] < plan.per_archive:
            short = f"  fewer than {plan.per_archive}: every paper of the archive was drawn"
        lines.append(
            f"{archive:<10} {count['listed']:>8} {count['primary']:>8} {count['drawn']:>6}{short}"
        )
    return lines


# The commit a file belongs to, and whether a kept file differs from it (agent/origin.py).
Origin = Callable[[Path | None], Mapping[str, Any]]


def main(
    argv: Sequence[str] | None = None,
    fetcher: Fetcher | None = None,
    origin: Origin = code_version,
) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m hepph_paper_miner.survey.sample",
        description="Ask arXiv for the papers of the plan, draw the sample, write both down.",
    )
    parser.add_argument("--plan", type=Path, required=True, help="the plan of the survey")
    parser.add_argument("--population", type=Path, help="the list to write (JSON lines)")
    parser.add_argument("--sample", type=Path, help="the sample to write (JSON lines)")
    parser.add_argument(
        "--page-size",
        type=int,
        default=PAGE_SIZE,
        help=f"papers asked for in one request, at most {MAX_PAGE_SIZE} (default: %(default)s)",
    )
    parser.add_argument(
        "--only", help="a first try: ask for these categories only (commas between), write nothing"
    )
    arguments = parser.parse_args(argv)

    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="backslashreplace")
    try:
        plan = load_plan(arguments.plan)
    except (OSError, PlanError) as error:
        print(f"cannot read the plan: {error}", file=sys.stderr)
        return 2
    if not 1 <= arguments.page_size <= MAX_PAGE_SIZE:
        print(f"--page-size: from 1 to {MAX_PAGE_SIZE}", file=sys.stderr)
        return 2

    only = None
    if arguments.only is not None:
        only = [name.strip() for name in arguments.only.split(",") if name.strip()]
        unknown = [name for name in only if name not in plan.categories]
        if unknown or not only:
            what = f"no category {', '.join(unknown)} in the plan" if unknown else "name a category"
            print(f"--only: {what}", file=sys.stderr)
            return 2
    elif arguments.population is None or arguments.sample is None:
        print("--population and --sample: where to write the list and the sample", file=sys.stderr)
        return 2

    plan_stamp: dict[str, Any] = {"name": plan.name, "sha256": plan.sha256}
    code: Mapping[str, Any] = {}
    if only is None:
        for path in (arguments.population, arguments.sample):
            if path.exists():
                print(f"{path} is there already; move it away first", file=sys.stderr)
                return 2
        code = origin(None)
        plan_stamp["commit"] = origin(arguments.plan).get("commit")
        print(f"plan      {plan.name} | sha256 {plan.sha256}")
        print(f"code      {code.get('commit')} | modified {code.get('modified')}")
        if plan_stamp["commit"] is None:
            print(
                "refused: the plan is not a file that a repository keeps, so no commit shows "
                "that it was there before the sample",
                file=sys.stderr,
            )
            return 2
        if code.get("modified") is not False:
            print(
                "refused: files the repository keeps have been changed, so no commit names "
                "this code and this plan",
                file=sys.stderr,
            )
            return 2

    if fetcher is None:
        fetcher = Fetcher(default_cache_dir(), user_agent=USER_AGENT)
    try:
        population = list_population(fetcher, plan, arguments.page_size, only=only)
    except ListingError as error:
        print(f"stopped: {error}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("stopped by hand; what was received is kept on disk", file=sys.stderr)
        return 130

    if only is not None:
        for category in only:
            # What is kept and what is passed over as cross-listed, to be looked at once:
            # a category that arXiv writes under another name would show here.
            listed = Counter(
                paper.primary
                for piece in population.pieces
                if piece.category == category
                for paper in piece.papers
            )
            named = ", ".join(f"{name} {count}" for name, count in listed.most_common(8))
            print(f"{category}: the primary categories of what was listed: {named or 'none'}")
        print(
            f"a first try with {', '.join(only)}: {len(population.papers)} paper(s) with one of "
            "them as primary category. Nothing was drawn and nothing was written."
        )
        return 0

    drawn = draw(population.papers, plan)
    counts = counts_by_archive(population, drawn, plan)
    digest = write_lines(
        arguments.population, population_lines(population, plan_stamp, code, arguments.page_size)
    )
    named = {"file": arguments.population.name, "sha256": digest, "papers": len(population.papers)}
    write_lines(arguments.sample, sample_lines(drawn, counts, plan, plan_stamp, code, named))
    for line in _table(counts, plan):
        print(line)
    print(
        f"{len(drawn)} paper(s) drawn from {len(population.papers)} with seed {plan.seed}: "
        f"{arguments.sample}"
    )
    print(f"the list they were drawn from: {arguments.population} | sha256 {digest}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
