"""The plan of the survey: which papers it is about, and how some of them are drawn.

The plan is a file (eval_data/survey_plan.json). It is committed before the first paper
is drawn, so that the history of the repository shows that the rule came first and the
papers second: a sample chosen after a look at the papers can be made to say anything.

It names three things.

    The population. A paper belongs to it when its primary category is one of the
    categories listed, and when arXiv's API returns it for one of the windows of time
    (`submittedDate`). A window is meant as "first submitted in it", and the list is
    refused when a paper says otherwise of itself (listing.py). The categories are
    written out one by one: asked for an archive by its name alone ("astro-ph"), the
    API returns none of the papers of its categories ("astro-ph.GA"), as two searches
    on 2026-11-23 showed. The windows are written as they are sent, to the minute and
    in GMT.

    The sample. So many papers of every archive, taken from the front of an order that
    a seed fixes (sample.py).

    The check by hand. Of the papers of every archive that were split, so many from the
    front of the same order have their outline held against the paper itself (sheet.py).

A plan with a key this module does not know is refused: a number under a misspelt name
would otherwise be left out without a word, and the default used in its place.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

# The order a sample is taken from, in the words the plan has to use as well. A plan that
# names another order was written for other code, and is refused.
ORDER = "sha256 of '<seed>:<identifier without its version>', smallest first"

_STAMP = "%Y%m%d%H%M"
# "hep-ph", "astro-ph.GA", "cond-mat.mtrl-sci": what arXiv's taxonomy calls a category.
_CATEGORY = re.compile(r"[a-z]+(?:-[a-z]+)*(?:\.[A-Za-z]+(?:-[A-Za-z]+)*)?")


class PlanError(ValueError):
    """A plan that cannot be used as it is. The message says where."""


@dataclass(frozen=True)
class Window:
    """A stretch of time as it is sent to arXiv: submittedDate:[first TO last], in GMT."""

    first: str  # "202608010000"
    last: str  # "202608312359": this minute still belongs to the window

    def __str__(self) -> str:
        return f"{self.first}-{self.last}"

    @property
    def starts(self) -> datetime:
        return datetime.strptime(self.first, _STAMP).replace(tzinfo=UTC)

    @property
    def ends(self) -> datetime:
        """The first moment after the window: the end of its last minute."""
        return datetime.strptime(self.last, _STAMP).replace(tzinfo=UTC) + timedelta(minutes=1)

    def holds(self, moment: datetime) -> bool:
        return self.starts <= moment < self.ends


@dataclass(frozen=True)
class Plan:
    name: str
    archives: Mapping[str, tuple[str, ...]]  # an archive and its categories, in the plan's order
    windows: tuple[Window, ...]
    per_archive: int
    seed: int
    outline_per_archive: int
    sha256: str  # of the file, as it lies on the disk

    @property
    def categories(self) -> tuple[str, ...]:
        return tuple(each for categories in self.archives.values() for each in categories)

    def archive_of(self, category: str) -> str | None:
        """The archive a category is listed under, or None when the plan does not list it."""
        for archive, categories in self.archives.items():
            if category in categories:
                return archive
        return None


def _keys(found: Any, where: str, *known: str) -> dict[str, Any]:
    """`found` as a mapping with exactly the keys named."""
    if not isinstance(found, dict):
        raise PlanError(f"{where}: an object with the keys {', '.join(known)}")
    unknown = sorted(set(found) - set(known))
    if unknown:
        raise PlanError(f"{where}: unknown key(s) {', '.join(unknown)}")
    missing = [key for key in known if key not in found]
    if missing:
        raise PlanError(f"{where}: no {', '.join(missing)}")
    return found


def _count(found: Any, where: str) -> int:
    # bool is an int in Python, and "true" papers per archive is no number of papers.
    if isinstance(found, bool) or not isinstance(found, int) or found < 1:
        raise PlanError(f"{where}: a whole number from 1 on, not {found!r}")
    return found


def _archives(found: Any) -> dict[str, tuple[str, ...]]:
    where = "population.archives"
    if not isinstance(found, dict) or not found:
        raise PlanError(f"{where}: an object that names every archive with its categories")
    archives: dict[str, tuple[str, ...]] = {}
    seen: set[str] = set()
    for archive, categories in found.items():
        if not isinstance(categories, list) or not categories:
            raise PlanError(f"{where}.{archive}: a list of at least one category")
        for category in categories:
            if not isinstance(category, str) or not _CATEGORY.fullmatch(category):
                raise PlanError(f"{where}.{archive}: {category!r} is not the name of a category")
            # The archive of a paper is read off its primary category, so a category
            # under another archive's name would be counted for the wrong one.
            if category != archive and not category.startswith(archive + "."):
                raise PlanError(f"{where}.{archive}: {category} is not a category of {archive}")
            if category in seen:
                raise PlanError(f"{where}: {category} is there twice")
            seen.add(category)
        archives[archive] = tuple(categories)
    return archives


def _windows(found: Any) -> tuple[Window, ...]:
    where = "population.submitted"
    if not isinstance(found, list) or not found:
        raise PlanError(f"{where}: a list of at least one window [first, last]")
    windows: list[Window] = []
    for at, pair in enumerate(found, start=1):
        if (
            not isinstance(pair, list)
            or len(pair) != 2
            or not all(isinstance(each, str) and re.fullmatch(r"[0-9]{12}", each) for each in pair)
        ):
            raise PlanError(f"{where}[{at}]: two times as YYYYMMDDHHMM, not {pair!r}")
        window = Window(*pair)
        try:
            starts, ends = window.starts, window.ends
        except ValueError as error:
            raise PlanError(f"{where}[{at}]: {error}") from error
        if ends <= starts:
            raise PlanError(f"{where}[{at}]: {window.last} is before {window.first}")
        # A paper in two windows would be listed twice, and the list is refused then.
        if windows and starts < windows[-1].ends:
            raise PlanError(f"{where}[{at}]: {window} begins before {windows[-1]} has ended")
        windows.append(window)
    return tuple(windows)


def read_plan(text: str, sha256: str = "") -> Plan:
    """The plan in a piece of text, or PlanError."""
    try:
        found = json.loads(text)
    except json.JSONDecodeError as error:
        raise PlanError(f"not JSON: {error}") from error
    top = _keys(found, "the plan", "plan", "about", "population", "sample", "outline_check")
    if not isinstance(top["plan"], str) or not top["plan"]:
        raise PlanError("plan: a name")
    population = _keys(
        top["population"], "population", "archives", "categories_checked", "submitted"
    )
    checked = _keys(population["categories_checked"], "population.categories_checked", "on", "at")
    try:
        datetime.strptime(str(checked["on"]), "%Y-%m-%d")
    except ValueError:
        raise PlanError(
            f"population.categories_checked.on: a day as YYYY-MM-DD, not {checked['on']!r}"
        ) from None
    sample = _keys(top["sample"], "sample", "per_archive", "seed", "order")
    if sample["order"] != ORDER:
        raise PlanError(f"sample.order: this code draws by {ORDER!r}, not by {sample['order']!r}")
    if isinstance(sample["seed"], bool) or not isinstance(sample["seed"], int):
        raise PlanError(f"sample.seed: a whole number, not {sample['seed']!r}")
    outline = _keys(top["outline_check"], "outline_check", "per_archive")
    per_archive = _count(sample["per_archive"], "sample.per_archive")
    outline_per_archive = _count(outline["per_archive"], "outline_check.per_archive")
    if outline_per_archive > per_archive:
        raise PlanError(
            f"outline_check.per_archive: {outline_per_archive} papers of an archive are checked "
            f"and only {per_archive} are drawn"
        )
    return Plan(
        name=top["plan"],
        archives=_archives(population["archives"]),
        windows=_windows(population["submitted"]),
        per_archive=per_archive,
        seed=sample["seed"],
        outline_per_archive=outline_per_archive,
        sha256=sha256,
    )


def load_plan(path: Path) -> Plan:
    """The plan in a file, with the SHA-256 of that file. Raises OSError or PlanError."""
    data = path.read_bytes()
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as error:
        raise PlanError(f"{path.name}: not UTF-8 text ({error})") from error
    try:
        return read_plan(text, hashlib.sha256(data).hexdigest())
    except PlanError as error:
        raise PlanError(f"{path.name}: {error}") from error
