"""Which papers the second evaluation asks about: places 41 to 80 of the survey's order.

The survey drew the first forty papers of every archive from the order of its list
(survey/sample.py: the SHA-256 of "<seed>:<identifier without its version>", smallest
first), and the parser was then changed for what those papers had shown (parser 5). A
question about them would be about papers that the code was fitted to. The next forty
of the same order are papers that nobody had opened when the plan was written. They
come from the same list by the same rule, so no new request to arXiv decides which
they are, and anyone can work them out again from the files of the repository.

`draw_places` is the survey's own `draw`, asked for eighty papers an archive, with the
first forty left out: a longer stretch of one order holds the shorter one.

The command writes the sample of the second evaluation, as survey.sample writes the
survey's, from the list that the survey committed:

    uv run python -m hepph_paper_miner.drafting.papers --plan eval_data/archives_plan.json \\
        --sample results/archives/sample.jsonl

The plan of the second evaluation (eval_data/archives_plan.json) is a file of its own,
since another stretch of the order is another plan, and the survey's stays what it was.
It names the survey's plan, whose seed and categories make the order, and the list, each
by its SHA-256, and then the archives and the places. Nothing is asked of arXiv: the list
is the one on disk. The sample file is read as the survey's is (survey/sample.py
read_sample: its first line says at which place it begins), so survey.run fetches its
papers as it fetched the survey's. It names the plan and the commit the plan belongs to,
and the command does not start when the plan is not a file of the repository or when a
file the repository keeps has been changed: the plan has to be in a commit before the
papers are drawn, or nothing shows that the rule came first.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from hepph_paper_miner.agent.origin import code_version
from hepph_paper_miner.survey.listing import Listed
from hepph_paper_miner.survey.plan import ORDER, Plan, PlanError, _count, _keys, load_plan
from hepph_paper_miner.survey.records import RecordError, now, read_lines, write_lines
from hepph_paper_miner.survey.sample import Drawn, draw

_SHA256 = re.compile(r"[0-9a-f]{64}")


def read_listed(path: Path) -> tuple[list[Listed], str]:
    """The papers of a list that the survey wrote (survey.sample --population), and its SHA-256."""
    lines, digest = read_lines(path, "population")
    return _listed(lines, path.name), digest


def _listed(lines: Sequence[Mapping[str, Any]], name: str) -> list[Listed]:
    papers: list[Listed] = []
    for line in lines[1:]:
        if line.get("record") != "paper":
            continue
        values = line.get("id"), line.get("primary"), line.get("published")
        if not all(isinstance(value, str) for value in values):
            raise RecordError(f"{name}: a paper without an identifier, a category or a date")
        papers.append(Listed(*values))
    return papers


def draw_places(
    papers: Iterable[Listed], plan: Plan, archives: Sequence[str], first: int, last: int
) -> list[Drawn]:
    """Places `first` to `last` of the order of each of `archives`, archive by archive.

    `plan` is the plan of the survey: its seed, and the categories of its archives.
    Fewer papers come back from an archive whose list is shorter than `last`.
    """
    if not 1 <= first <= last:
        raise ValueError(f"places {first} to {last} are no stretch of an order")
    unknown = [name for name in archives if name not in plan.archives]
    if unknown:
        raise ValueError(f"the plan of the survey has no archive {', '.join(unknown)}")
    wider = replace(
        plan, archives={name: plan.archives[name] for name in archives}, per_archive=last
    )
    return [paper for paper in draw(papers, wider) if paper.rank >= first]


# --- the plan of the second evaluation ----------------------------------------------------


@dataclass(frozen=True)
class ArchivesPlan:
    """Which papers the second evaluation asks about, as its plan names them."""

    name: str
    survey_plan: str  # the name of the survey's plan, whose order is taken
    survey_plan_sha256: str
    population_sha256: str  # of the list the survey wrote
    archives: tuple[str, ...]
    first: int
    last: int
    sha256: str  # of the file, as it lies on the disk

    @property
    def per_archive(self) -> int:
        return self.last - self.first + 1


def _digest(found: Any, where: str) -> str:
    if not isinstance(found, str) or not _SHA256.fullmatch(found):
        raise PlanError(f"{where}: a SHA-256 in 64 small hexadecimal digits, not {found!r}")
    return found


def read_archives_plan(text: str, sha256: str = "") -> ArchivesPlan:
    """The plan in a piece of text, or PlanError. A key it does not know is refused."""
    try:
        found = json.loads(text)
    except json.JSONDecodeError as error:
        raise PlanError(f"not JSON: {error}") from error
    top = _keys(found, "the plan", "plan", "about", "papers")
    if not isinstance(top["plan"], str) or not top["plan"]:
        raise PlanError("plan: a name")
    papers = _keys(
        top["papers"], "papers", "survey_plan", "population", "archives", "first", "last"
    )
    survey = _keys(papers["survey_plan"], "papers.survey_plan", "name", "sha256")
    if not isinstance(survey["name"], str) or not survey["name"]:
        raise PlanError("papers.survey_plan.name: the name of the survey's plan")
    population = _keys(papers["population"], "papers.population", "sha256")
    archives = papers["archives"]
    if (
        not isinstance(archives, list)
        or not archives
        or not all(isinstance(name, str) and name for name in archives)
    ):
        raise PlanError("papers.archives: a list of the names of archives")
    if len(set(archives)) != len(archives):
        raise PlanError("papers.archives: an archive is there twice")
    first = _count(papers["first"], "papers.first")
    last = _count(papers["last"], "papers.last")
    if last < first:
        raise PlanError(f"papers.last: {last} is before papers.first, {first}")
    return ArchivesPlan(
        name=top["plan"],
        survey_plan=survey["name"],
        survey_plan_sha256=_digest(survey["sha256"], "papers.survey_plan.sha256"),
        population_sha256=_digest(population["sha256"], "papers.population.sha256"),
        archives=tuple(archives),
        first=first,
        last=last,
        sha256=sha256,
    )


def load_archives_plan(path: Path) -> ArchivesPlan:
    """The plan in a file, with the SHA-256 of that file. Raises OSError or PlanError."""
    data = path.read_bytes()
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as error:
        raise PlanError(f"{path.name}: not UTF-8 text ({error})") from error
    try:
        return read_archives_plan(text, hashlib.sha256(data).hexdigest())
    except PlanError as error:
        raise PlanError(f"{path.name}: {error}") from error


# --- the sample ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Drawing:
    """What the sample is drawn from, read and held to the plan."""

    survey_plan: Plan
    papers: list[Listed]
    counts: dict[str, dict[str, int]]  # by archive: listed and primary, as the list says
    population: dict[str, Any]  # how the sample names the list


def drawing_of(plan: ArchivesPlan, survey_plan_file: Path, population_file: Path) -> Drawing:
    """The survey's plan and its list, refused unless they are the files the plan names."""
    survey_plan = load_plan(survey_plan_file)
    if survey_plan.sha256 != plan.survey_plan_sha256 or survey_plan.name != plan.survey_plan:
        raise RecordError(
            f"{survey_plan_file.name} is not the plan {plan.survey_plan} that {plan.name} names"
        )
    unknown = [name for name in plan.archives if name not in survey_plan.archives]
    if unknown:
        raise RecordError(f"the plan of the survey has no archive {', '.join(unknown)}")
    lines, digest = read_lines(population_file, "population")
    if digest != plan.population_sha256:
        raise RecordError(f"{population_file.name} is not the list that {plan.name} names")
    if (lines[0].get("plan") or {}).get("sha256") != survey_plan.sha256:
        raise RecordError(f"{population_file.name} was not listed by the plan {survey_plan.name}")
    papers = _listed(lines, population_file.name)
    counts = {name: {"listed": 0, "primary": 0} for name in plan.archives}
    for line in lines[1:]:
        if line.get("record") != "piece":
            continue
        archive = survey_plan.archive_of(line.get("category", ""))
        if archive in counts:
            # As the survey's sample counts them (survey/sample.py counts_by_archive).
            counts[archive]["listed"] += line["total"]
            counts[archive]["primary"] += line["primary"]
    named = {"file": population_file.name, "sha256": digest, "papers": len(papers)}
    return Drawing(survey_plan, papers, counts, named)


def sample_lines(
    plan: ArchivesPlan,
    plan_commit: str,
    drawing: Drawing,
    drawn: Sequence[Drawn],
    code: Mapping[str, Any],
) -> list[dict[str, Any]]:
    """The sample file: the survey's form, with the place it begins at in its first line."""
    head = {
        "record": "sample",
        "plan": {"name": plan.name, "sha256": plan.sha256, "commit": plan_commit},
        "survey_plan": {"name": drawing.survey_plan.name, "sha256": drawing.survey_plan.sha256},
        "code": dict(code),
        "population": dict(drawing.population),
        "first": plan.first,
        "per_archive": plan.per_archive,
        "seed": drawing.survey_plan.seed,
        "order": ORDER,
        "drawn": now(),
    }
    archives = [
        {
            "record": "archive",
            "archive": name,
            **drawing.counts[name],
            "drawn": sum(1 for paper in drawn if paper.archive == name),
        }
        for name in plan.archives
    ]
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


# The commit a file belongs to, and whether a kept file differs from it (agent/origin.py).
Origin = Callable[[Path | None], Mapping[str, Any]]


def main(argv: Sequence[str] | None = None, origin: Origin = code_version) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m hepph_paper_miner.drafting.papers",
        description="Draw the papers of the second evaluation from the list of the survey, "
        "and write the sample.",
    )
    parser.add_argument("--plan", type=Path, required=True, help="the plan of the evaluation")
    parser.add_argument(
        "--survey-plan",
        type=Path,
        default=Path("eval_data/survey_plan.json"),
        help="the plan of the survey, whose order is taken (default: %(default)s)",
    )
    parser.add_argument(
        "--population",
        type=Path,
        default=Path("results/survey/population.jsonl"),
        help="the list of the survey (default: %(default)s)",
    )
    parser.add_argument("--sample", type=Path, required=True, help="the sample to write")
    arguments = parser.parse_args(argv)

    try:
        plan = load_archives_plan(arguments.plan)
        drawing = drawing_of(plan, arguments.survey_plan, arguments.population)
    except (OSError, PlanError, RecordError) as error:
        print(f"refused: {error}", file=sys.stderr)
        return 2
    if arguments.sample.exists():
        print(f"refused: {arguments.sample} is there already; move it away first", file=sys.stderr)
        return 2
    code = origin(None)
    plan_commit = origin(arguments.plan).get("commit")
    print(f"plan      {plan.name} | sha256 {plan.sha256}")
    print(f"code      {code.get('commit')} | modified {code.get('modified')}")
    if plan_commit is None:
        print(
            "refused: the plan is not a file that a repository keeps, so no commit shows that "
            "it was there before the sample",
            file=sys.stderr,
        )
        return 2
    if code.get("modified") is not False:
        print(
            "refused: files the repository keeps have been changed, so no commit names this "
            "code and this plan",
            file=sys.stderr,
        )
        return 2
    drawn = draw_places(drawing.papers, drawing.survey_plan, plan.archives, plan.first, plan.last)
    lines = sample_lines(plan, plan_commit, drawing, drawn, code)
    digest = write_lines(arguments.sample, lines)
    print(f"{'archive':<10} {'listed':>8} {'primary':>8} {'drawn':>6}")
    for line in lines:
        if line["record"] != "archive":
            continue
        short = ""
        if line["drawn"] < plan.per_archive:
            short = f"  fewer than {plan.per_archive}: the list ends before place {plan.last}"
        print(
            f"{line['archive']:<10} {line['listed']:>8} {line['primary']:>8} "
            f"{line['drawn']:>6}{short}"
        )
    print(
        f"places {plan.first} to {plan.last}: {len(drawn)} paper(s) with seed "
        f"{drawing.survey_plan.seed}, written to {arguments.sample} (SHA-256 {digest[:16]})"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
