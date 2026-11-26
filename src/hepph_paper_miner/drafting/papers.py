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
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import replace
from pathlib import Path

from hepph_paper_miner.survey.listing import Listed
from hepph_paper_miner.survey.plan import Plan
from hepph_paper_miner.survey.records import RecordError, read_lines
from hepph_paper_miner.survey.sample import Drawn, draw


def read_listed(path: Path) -> tuple[list[Listed], str]:
    """The papers of a list that the survey wrote (survey.sample --population), and its SHA-256."""
    lines, digest = read_lines(path, "population")
    papers: list[Listed] = []
    for line in lines[1:]:
        if line.get("record") != "paper":
            continue
        values = line.get("id"), line.get("primary"), line.get("published")
        if not all(isinstance(value, str) for value in values):
            raise RecordError(f"{path.name}: a paper without an identifier, a category or a date")
        papers.append(Listed(*values))
    return papers, digest


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
