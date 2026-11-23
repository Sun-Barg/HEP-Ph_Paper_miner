"""The sheet on which a person holds outlines against the papers themselves.

    uv run python -m hepph_paper_miner.survey.sheet --plan eval_data/survey_plan.json \\
        --sample results/survey/sample.jsonl --outcomes results/survey/outcomes.jsonl \\
        --sheet runs_private/outline-sheet.csv

"Split into sections" (run.py) says that the parser returned sections. It does not say
that they are the sections of the paper. For that somebody has to look, and this
writes the sheet to look with: of the papers of every archive that were split, the
first few of the order the sample was drawn in (the plan says how many), each with its
outline as the server gives it. The papers were fixed by the seed before anyone saw
an outline, so nobody picks the ones that look right.

The sheet holds section titles, which are text of the papers. It belongs in
runs_private/, which is never committed. It is CSV in UTF-8 with a byte-order mark, so
that Excel reads its letters right; it has to be saved as "CSV UTF-8" again.

Every paper has one row of its own (with its identifier and a link to its abstract
page) and under it a row for every line of its outline. The person who checks opens the
paper, as PDF or as HTML, and writes on the row of the paper:

    sections      "same" when the headings the paper has at the level of a section
                  (numbered or not, those of an appendix too) are the titles of the
                  rows that are not indented: as many, in the same order, each the
                  same heading. "differ" otherwise.
    subsections   the same one level down: every subsection of the paper is an indented
                  row under the section that holds it, and every indented row is one.
                  "same" also when the paper has none and the outline has none.
    note          what differs, in the checker's own words. It goes into the
                  repository, so it describes ("an unnumbered heading at the end of the
                  paper has no row") and does not copy headings out of the paper.

    No difference: a title that reads differently only because the sheet shows TeX as
    it was typed and the paper shows it typeset; the numbers and letters in front of a
    heading (the identifiers on the sheet are the server's own); the list of
    references, which the parser leaves out on purpose; the title, the authors and
    the abstract, which are no sections; anything below a subsection, which the parser
    does not cut at and the sheet does not show. A row whose title stands in
    parentheses is not a heading: it says that the paper has text there under no
    heading of its own, and it is left out of the comparison.

    A difference: a heading of the paper without a row; a row that is no heading of
    the paper; another order; a title that is another title; a subsection under another
    section than in the paper.

These rules are written here before the first outline is looked at, and they are the
same for every paper. With the sheet filled in,

    ... --sheet runs_private/outline-sheet.csv --checks results/survey/outline-check.jsonl

reads it back and writes what the repository keeps: for every paper its identifier, the
two verdicts and the note. No title of a paper or of a section is in that file.

A paper that is still unanswered could turn out to be split and to stand in front of a
paper on the sheet. So the sheet is refused while such a paper is left, unless
--pass-over-unanswered says that it is to be taken as it is: not split.
"""

from __future__ import annotations

import argparse
import csv
import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from hepph_paper_miner.agent.origin import code_version, file_digest
from hepph_paper_miner.http import Fetcher, default_cache_dir
from hepph_paper_miner.sources.arxiv import ArxivSource
from hepph_paper_miner.sources.arxiv_latex import PARSER_VERSION
from hepph_paper_miner.sources.base import Paper, PaperSource, SourceError, parse_arxiv_id
from hepph_paper_miner.survey.plan import PlanError, load_plan
from hepph_paper_miner.survey.records import RecordError, now, write_lines
from hepph_paper_miner.survey.run import OK, UNANSWERED, read_outcomes, shape
from hepph_paper_miner.survey.sample import USER_AGENT, read_sample

COLUMNS = (
    "number",
    "archive",
    "arxiv_id",
    "link",
    "section_id",
    "chars",
    "title",
    "sections",
    "subsections",
    "note",
)
VERDICTS = ("same", "differ")
ABSTRACT_PAGE = "https://arxiv.org/abs/{arxiv_id}"


class SheetError(ValueError):
    """A sheet that cannot be written, or cannot be used as it is. The message says why."""


@dataclass(frozen=True)
class Check:
    """What a person found for one paper."""

    archive: str
    rank: int
    arxiv_id: str
    sections: str  # "same" or "differ"
    subsections: str
    note: str


def to_check(
    papers: Sequence[Mapping[str, Any]], per_archive: int
) -> tuple[list[Mapping[str, Any]], list[Mapping[str, Any]]]:
    """The papers whose outline is checked, and the unanswered papers that could displace one.

    From every archive the first `per_archive` papers that were split, in the order of
    the sample. An unanswered paper in front of the last of them, or in an archive
    that has not got its number, could still turn out to be split and to belong there.
    """
    chosen: list[Mapping[str, Any]] = []
    waiting: list[Mapping[str, Any]] = []
    for archive in dict.fromkeys(line["archive"] for line in papers):
        own = sorted(
            (line for line in papers if line["archive"] == archive), key=lambda line: line["rank"]
        )
        split = [line for line in own if line["outcome"] == OK][:per_archive]
        chosen += split
        last = split[-1]["rank"] if len(split) == per_archive else float("inf")
        waiting += [line for line in own if line["outcome"] == UNANSWERED and line["rank"] < last]
    return chosen, waiting


def _cell(text: str) -> str:
    """Text as a spreadsheet shows it: one that begins like a formula is kept as text."""
    return " " + text if text[:1] in ("=", "+", "-", "@", "\t", "\r") else text


def sheet_rows(chosen: Sequence[tuple[Mapping[str, Any], Paper]]) -> list[list[Any]]:
    rows: list[list[Any]] = [list(COLUMNS)]
    for number, (line, paper) in enumerate(chosen, start=1):
        link = ABSTRACT_PAGE.format(arxiv_id=line["id"])
        rows.append(
            [number, line["archive"], line["id"], link, "", paper.chars, _cell(paper.meta.title)]
            + ["", "", ""]
        )
        for section in paper.sections:
            indent = "  " if section.level == 2 else ""
            rows.append(
                [number, "", "", "", section.section_id, section.chars]
                + [_cell(indent + section.title), "", "", ""]
            )
    return rows


def write_sheet(rows: Sequence[Sequence[Any]], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        csv.writer(stream).writerows(rows)


def read_sheet(path: Path, chosen: Sequence[Mapping[str, Any]]) -> list[Check]:
    """The verdicts of a filled sheet, one for each paper that was to be checked.

    Refused as a whole when the papers on it are not those papers, in that order, or
    when a paper is without a verdict: a verdict that is counted for the wrong paper,
    or a paper that is counted as checked and was not, would not show anywhere.
    """
    try:
        with path.open(encoding="utf-8-sig", newline="") as stream:
            lines = list(csv.DictReader(stream))
    except UnicodeDecodeError as error:
        raise SheetError(
            f'{path.name}: the sheet is not UTF-8 text; save it as "CSV UTF-8" ({error})'
        ) from error
    if lines and not {"arxiv_id", "sections", "subsections", "note"} <= set(lines[0]):
        raise SheetError(f"{path.name}: the columns arxiv_id, sections, subsections, note")
    rows = []
    for at, line in enumerate(lines, start=2):  # the first line of the file is the header
        values = {name: (value or "").strip() for name, value in line.items() if name}
        if values.get("arxiv_id"):
            rows.append((at, values))
    named = [values["arxiv_id"] for _, values in rows]
    expected = [line["id"] for line in chosen]
    if named != expected:
        odd = next(
            (
                f"line {at} has {values['arxiv_id']}, not {want}"
                for (at, values), want in zip(rows, expected, strict=False)
                if values["arxiv_id"] != want
            ),
            f"{len(named)} paper(s), not {len(expected)}",
        )
        raise SheetError(f"{path.name}: not the sheet of these outcomes ({odd})")
    checks = []
    for (at, values), line in zip(rows, chosen, strict=True):
        where = f"{path.name} line {at} ({line['id']})"
        verdicts = [values["sections"].casefold(), values["subsections"].casefold()]
        for name, verdict in zip(("sections", "subsections"), verdicts, strict=True):
            if not verdict:
                raise SheetError(f"{where}: nothing under {name} yet")
            if verdict not in VERDICTS:
                raise SheetError(
                    f"{where}: {values[name]!r} under {name} is neither same nor differ"
                )
        if "differ" in verdicts and not values["note"]:
            raise SheetError(f"{where}: something differs, and the note does not say what")
        checks.append(Check(line["archive"], line["rank"], line["id"], *verdicts, values["note"]))
    return checks


def check_lines(checks: Sequence[Check], head: Mapping[str, Any]) -> list[dict[str, Any]]:
    both = sum(1 for check in checks if (check.sections, check.subsections) == ("same", "same"))
    return [
        {"record": "outline_check", **head, "papers": len(checks), "same": both},
        *(
            {
                "record": "paper",
                "archive": check.archive,
                "rank": check.rank,
                "id": check.arxiv_id,
                "sections": check.sections,
                "subsections": check.subsections,
                "note": check.note,
            }
            for check in checks
        ),
    ]


def outlines(
    source: PaperSource, chosen: Sequence[Mapping[str, Any]]
) -> list[tuple[Mapping[str, Any], Paper]]:
    """Every paper that is to be checked, split again, and held against what the survey wrote.

    The sheet has to show the outline that was counted. A paper that now splits into
    other sections (another parser, another download) is refused.
    """
    found = []
    for line in chosen:
        try:
            paper = source.paper(parse_arxiv_id(line["id"]))
        except SourceError as error:
            raise SheetError(
                f"{line['id']} could not be had again ({error.kind.value}); "
                "what the survey fetched is on disk unless the folder of downloads was emptied"
            ) from error
        split = shape(paper)
        written = {name: line.get(name) for name in split}
        if split != written:
            raise SheetError(
                f"{line['id']} splits into {split} now, and the survey wrote down {written}"
            )
        found.append((line, paper))
    return found


def main(
    argv: Sequence[str] | None = None,
    source: PaperSource | None = None,
    origin: Callable[[Path | None], Mapping[str, Any]] = code_version,
) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m hepph_paper_miner.survey.sheet",
        description="Write the sheet for holding outlines against the papers, or read it back.",
    )
    parser.add_argument("--plan", type=Path, required=True, help="the plan of the survey")
    parser.add_argument("--sample", type=Path, required=True, help="the sample (survey.sample)")
    parser.add_argument("--outcomes", type=Path, required=True, help="the outcomes (survey.run)")
    parser.add_argument("--sheet", type=Path, required=True, help="the sheet (CSV), kept private")
    parser.add_argument(
        "--checks", type=Path, help="read the filled sheet and write the verdicts here (JSON lines)"
    )
    parser.add_argument(
        "--pass-over-unanswered",
        action="store_true",
        help="take the papers that are still unanswered as not split",
    )
    arguments = parser.parse_args(argv)

    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="backslashreplace")
    try:
        plan = load_plan(arguments.plan)
        sample = read_sample(arguments.sample)
        head, papers = read_outcomes(arguments.outcomes)
    except (OSError, PlanError, RecordError) as error:
        print(f"cannot read what the sheet is made from: {error}", file=sys.stderr)
        return 2
    writing = arguments.checks is None
    target = arguments.sheet if writing else arguments.checks
    if target.exists():
        print(f"{target} is there already; move it away first", file=sys.stderr)
        return 2
    code: Mapping[str, Any] = {}
    if not writing:
        # The verdicts become a file of the repository, and it names the code that read them.
        code = origin(None)
        if code.get("modified") is not False:
            print(
                "refused: files the repository keeps have been changed, so no commit names "
                "this code",
                file=sys.stderr,
            )
            return 2

    try:
        # The three files have to be of one survey: each names the one before it.
        if (sample.head.get("plan") or {}).get("sha256") != plan.sha256:
            raise SheetError(f"{arguments.sample.name} was not drawn under {arguments.plan.name}")
        if (head.get("sample") or {}).get("sha256") != sample.sha256:
            raise SheetError(
                f"{arguments.outcomes.name} are not the outcomes of {arguments.sample.name}"
            )
        if [line["id"] for line in papers] != [paper.arxiv_id for paper in sample.papers]:
            raise SheetError(f"{arguments.outcomes.name} does not hold the papers of the sample")
        chosen, waiting = to_check(papers, plan.outline_per_archive)
        if waiting and not arguments.pass_over_unanswered:
            raise SheetError(
                f"{len(waiting)} unanswered paper(s) could still belong on the sheet (the first: "
                f"{waiting[0]['id']}). Run the survey again, or say --pass-over-unanswered"
            )
        if writing:
            if head.get("parser_version") != PARSER_VERSION:
                raise SheetError(
                    f"the outcomes were made by parser {head.get('parser_version')}, "
                    f"and this code has parser {PARSER_VERSION}"
                )
            if source is None:
                source = ArxivSource(Fetcher(default_cache_dir(), user_agent=USER_AGENT))
            write_sheet(sheet_rows(outlines(source, chosen)), arguments.sheet)
        else:
            checks = read_sheet(arguments.sheet, chosen)
    except SheetError as error:
        print(f"refused: {error}", file=sys.stderr)
        return 1
    except OSError as error:
        print(f"cannot read or write the sheet: {error}", file=sys.stderr)
        return 2

    if writing:
        print(
            f"{len(chosen)} paper(s) on the sheet {arguments.sheet}, at most "
            f"{plan.outline_per_archive} of an archive"
        )
        print(
            'on the row of each paper, write "same" or "differ" under sections and under '
            "subsections, and under note what differs"
        )
        return 0

    named = {
        "outcomes": {"file": arguments.outcomes.name, "sha256": file_digest(arguments.outcomes)},
        "sample": {"file": arguments.sample.name, "sha256": sample.sha256},
        "plan": sample.head.get("plan"),
        "code": dict(code),
        "per_archive": plan.outline_per_archive,
        "unanswered_passed_over": len(waiting),
        "written": now(),
    }
    lines = check_lines(checks, named)
    write_lines(arguments.checks, lines)
    same = {
        name: sum(1 for check in checks if getattr(check, name) == "same")
        for name in ("sections", "subsections")
    }
    print(
        f"{len(checks)} paper(s) checked: the sections are the same in {same['sections']}, "
        f"the subsections in {same['subsections']}, both in {lines[0]['same']}"
    )
    print(f"written: {arguments.checks}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
