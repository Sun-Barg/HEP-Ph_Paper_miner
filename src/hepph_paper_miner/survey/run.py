"""Run the survey: every paper of the sample through the source the tools use, one line each.

    uv run python -m hepph_paper_miner.survey.run --sample results/survey/sample.jsonl \\
        --out results/survey/outcomes.jsonl

A paper is fetched and split exactly as `get_outline` and `read_paper` would have it
(ArxivSource.paper), in the version the sample names. What comes back is one of:

    ok              split into sections. The line holds counts and no text: sections,
                    subsections, characters, the largest piece a reader can ask for in
                    one call, and whether the paper has a section heading at all.
    no_full_text    arXiv has no TeX source of it (a PDF, or nothing to download).
    parse_error     there is a source, and the parser turned it away. `branch` sorts the
                    sentence of the parser into a few kinds; the sentence is kept too.
    not_found       arXiv lists no such paper. Not expected of a paper that it listed.
    unexpected      something nobody foresaw: the code raised an error of its own, or
                    the paper that came back is not the version that was asked for.
    unanswered      arXiv was busy, took too long or sent something that was not the
                    paper's files. That says nothing about the paper.

`unanswered` is not an outcome. The survey is done when no paper is left with it: run
the command again, and it asks again. Every run goes through the whole sample and writes
the whole file anew, so that every line of a file was made by one version of the code,
the one its first line names. That costs little: what arXiv answered is on disk, and
only the papers without an answer are asked for again. A paper that stays unanswered
however often it is asked (one submitted as HTML is, today) is reported as such, with
the sentence it came back with. The file is written at the end, all or nothing; a run
that is stopped leaves the file that was there.

The papers are not taken archive by archive: the first of every archive, then the second
of every archive, and so on. A stretch in which arXiv answers badly then costs every
archive a few papers and no archive many.

It sends two requests for a paper the first time, three seconds apart: for 520 papers
about an hour. Nothing else on the machine should ask arXiv meanwhile: the three seconds
are kept inside one process, and a server started by a desktop app is another one.

    --limit 52    a first try: only the papers at the front of the walk; say what came
                  back and how much the folder of downloads grew, write nothing
"""

from __future__ import annotations

import argparse
import re
import sys
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from time import monotonic
from typing import Any

from hepph_paper_miner.agent.origin import code_version
from hepph_paper_miner.http import Fetcher, default_cache_dir
from hepph_paper_miner.server import SECTION_CHAR_LIMIT, own_text
from hepph_paper_miner.sources.arxiv import ArxivSource
from hepph_paper_miner.sources.arxiv_latex import PARSER_VERSION
from hepph_paper_miner.sources.base import (
    ErrorKind,
    Paper,
    PaperSource,
    SourceError,
    parse_arxiv_id,
)
from hepph_paper_miner.survey.records import RecordError, now, read_lines, write_lines
from hepph_paper_miner.survey.sample import USER_AGENT, Drawn, Sample, read_sample

OK = "ok"
UNANSWERED = "unanswered"
UNEXPECTED = "unexpected"
# The kinds of failure that are about arXiv on that day and not about the paper.
_NO_ANSWER = frozenset({ErrorKind.UPSTREAM_BUSY, ErrorKind.TIMEOUT})
# The outcomes in the order a table shows them.
OUTCOMES = (OK, "no_full_text", "parse_error", "not_found", UNEXPECTED, UNANSWERED)

# The title the parser gives the one section of a paper without any heading
# (arxiv_latex.split). tests/test_survey_run.py holds it against the parser.
NO_HEADINGS = "(the paper has no section headings)"

OTHER = "other"
# What the parser says when it turns a paper away, sorted into kinds by the form of the
# sentence. The sentences are written in sources/arxiv_latex.py, and
# tests/test_survey_run.py makes the parser say each of them: a sentence that is
# reworded there fails a test here instead of slipping into "other".
_PARSE_BRANCHES = (
    # Plain TeX, or the notice a withdrawn paper leaves behind.
    ("no_document", re.compile(r"no file contains \\begin\{document\}$")),
    (
        "no_document",
        re.compile(r"no \\begin\{document\} in the main file or in the files it reads$"),
    ),
    # A file the text names is missing from the download, or is read with a command the
    # parser does not follow (\import and its relatives): the latter names the command.
    (
        "unfollowed_command",
        re.compile(r"text is missing, [0-9]+ file\(s\) could not be read: .*\(\\\w+\)"),
    ),
    ("missing_file", re.compile(r"text is missing, [0-9]+ file\(s\) could not be read: ")),
    ("too_short", re.compile(r"only [0-9]+ characters of text were found$")),
    ("duplicate_id", re.compile(r"two sections share an identifier$")),
    ("misplaced_subsection", re.compile(r"subsection \S+ is not part of the section before it$")),
    (
        "misplaced_subsection",
        re.compile(r"the heading of subsection \S+ is not where it should be$"),
    ),
    ("no_sections", re.compile(r"no sections$")),
    ("too_large", re.compile(r"the download is too large to unpack$")),
)
_NO_TEXT_BRANCHES = (
    ("not_tex", re.compile(r"the source is a PDF, PostScript or DVI file$")),
    # No sentence: the paper is listed and arXiv has nothing to download for it.
    ("no_source", re.compile(r"$")),
)
_BRANCHES = {"parse_error": _PARSE_BRANCHES, "no_full_text": _NO_TEXT_BRANCHES}


def branch(outcome: str, sentence: str) -> str:
    """The kind of a failure, read off the sentence it came with. "other" when none fits."""
    for name, form in _BRANCHES.get(outcome, ()):
        if form.match(sentence):
            return name
    return OTHER


def shape(paper: Paper) -> dict[str, Any]:
    """What the survey writes down of a paper that was split: counts, and nothing of its text.

    `largest` is the largest piece that one call of `read_section` can be asked for: a
    subsection, a section without subsections, or the text a section has of its own in
    front of its first subsection. Above the limit of a call, the piece takes more than
    one call to read. (scripts/check_targets.py prints the same without the third kind,
    which the tools could not ask for when it was written.)
    """
    top = [section for section in paper.sections if section.level == 1]
    divided = {s.section_id.split(".")[0] for s in paper.sections if s.level == 2}
    pieces = [
        section.chars
        for section in paper.sections
        if section.level == 2 or section.section_id not in divided
    ]
    pieces += own_text(paper).values()
    return {
        "sections": len(top),
        "subsections": len(paper.sections) - len(top),
        "chars": paper.chars,
        "largest": max(pieces),
        "no_headings": len(paper.sections) == 1 and top[0].title == NO_HEADINGS,
    }


def survey_one(source: PaperSource, drawn: Drawn) -> dict[str, Any]:
    """The line of one paper."""
    line: dict[str, Any] = {
        "record": "paper",
        "archive": drawn.archive,
        "rank": drawn.rank,
        "id": drawn.arxiv_id,
        "primary": drawn.primary,
    }
    try:
        paper = source.paper(parse_arxiv_id(drawn.arxiv_id))
    except SourceError as error:
        # The source puts the identifier in front of what the parser said.
        sentence = error.detail.removeprefix(drawn.arxiv_id).removeprefix(": ")
        if error.kind in _NO_ANSWER:
            return {**line, "outcome": UNANSWERED, "kind": error.kind.value, "detail": sentence}
        outcome = error.kind.value
        return {**line, "outcome": outcome, "branch": branch(outcome, sentence), "detail": sentence}
    except Exception as error:
        # One paper the code cannot cope with must not end an hour of others, and it is
        # a finding: a tool would have failed on it too. The message of the error can
        # quote the paper, so only its kind is written down.
        return {**line, "outcome": UNEXPECTED, "detail": f"the code raised {type(error).__name__}"}
    if paper.meta.arxiv_id != drawn.arxiv_id:
        # Not the version that was drawn, so not the paper the sample names.
        return {
            **line,
            "outcome": UNEXPECTED,
            "detail": f"asked for {drawn.arxiv_id}, given {paper.meta.arxiv_id}",
        }
    return {**line, "outcome": OK, **shape(paper)}


def walk(papers: Sequence[Drawn]) -> list[Drawn]:
    """The order in which the papers are asked for: the first of every archive, then the second."""
    archives = list(dict.fromkeys(paper.archive for paper in papers))
    return sorted(papers, key=lambda paper: (paper.rank, archives.index(paper.archive)))


@dataclass(frozen=True)
class Tally:
    """What a set of lines says, counted."""

    papers: int
    by_archive: Mapping[str, Mapping[str, int]]  # archive -> outcome -> papers
    branches: Mapping[str, Mapping[str, int]]  # outcome -> branch -> papers
    no_headings: int  # of the papers that were split
    over_limit: int  # of the papers that were split: a piece larger than one call returns

    def count(self, outcome: str) -> int:
        return sum(counts.get(outcome, 0) for counts in self.by_archive.values())

    @property
    def unanswered(self) -> int:
        return self.count(UNANSWERED)


def tally(lines: Sequence[Mapping[str, Any]], limit: int = SECTION_CHAR_LIMIT) -> Tally:
    by_archive: dict[str, Counter[str]] = {}
    branches: dict[str, Counter[str]] = {}
    for line in lines:
        by_archive.setdefault(line["archive"], Counter())[line["outcome"]] += 1
        if "branch" in line:
            branches.setdefault(line["outcome"], Counter())[line["branch"]] += 1
    split = [line for line in lines if line["outcome"] == OK]
    return Tally(
        papers=len(lines),
        by_archive=by_archive,
        branches=branches,
        no_headings=sum(1 for line in split if line["no_headings"]),
        over_limit=sum(1 for line in split if line["largest"] > limit),
    )


def table(found: Tally, limit: int = SECTION_CHAR_LIMIT) -> list[str]:
    shown = [outcome for outcome in OUTCOMES if found.count(outcome) or outcome == OK]
    lines = [f"{'archive':<10} {'papers':>6} " + " ".join(f"{name:>12}" for name in shown)]
    for archive, counts in found.by_archive.items():
        lines.append(
            f"{archive:<10} {sum(counts.values()):>6} "
            + " ".join(f"{counts.get(name, 0):>12}" for name in shown)
        )
    lines.append(
        f"{'all':<10} {found.papers:>6} " + " ".join(f"{found.count(name):>12}" for name in shown)
    )
    for outcome, counts in found.branches.items():
        kinds = ", ".join(f"{name} {count}" for name, count in sorted(counts.items()))
        lines.append(f"{outcome} by what was said: {kinds}")
    lines.append(
        f"of the {found.count(OK)} split: {found.no_headings} without a section heading, "
        f"{found.over_limit} with a piece of more than {limit} characters"
    )
    return lines


def read_outcomes(path: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """The first line of an outcomes file and its paper lines, or RecordError."""
    lines, _ = read_lines(path, "outcomes")
    papers = [line for line in lines[1:] if line.get("record") == "paper"]
    for line in papers:
        if line.get("outcome") not in OUTCOMES or not isinstance(line.get("id"), str):
            raise RecordError(f"{path.name}: a line without a paper or without an outcome")
    return lines[0], papers


def _folder_bytes(folder: Path) -> int:
    return sum(path.stat().st_size for path in folder.rglob("*") if path.is_file())


def _said(line: Mapping[str, Any]) -> str:
    if line["outcome"] == OK:
        return (
            f"ok | {line['sections']} section(s), {line['subsections']} subsection(s), "
            f"{line['chars']} chars, largest {line['largest']}"
        )
    kind = line.get("branch") or line.get("kind") or ""
    return f"{line['outcome']}{f' ({kind})' if kind else ''} | {line['detail']}"


def survey(
    source: PaperSource,
    papers: Sequence[Drawn],
    say: Callable[[str], None] = print,
) -> list[dict[str, Any]]:
    """Ask for every paper, in the order of the walk. The lines come back in that order."""
    lines = []
    for at, drawn in enumerate(papers, start=1):
        line = survey_one(source, drawn)
        lines.append(line)
        say(f"[{at}/{len(papers)}] {drawn.archive} {drawn.rank} {drawn.arxiv_id} | {_said(line)}")
    return lines


def outcome_lines(
    sample: Sample,
    sample_path: Path,
    lines: Sequence[Mapping[str, Any]],
    code: Mapping[str, Any],
    began: str,
) -> list[dict[str, Any]]:
    found = tally(lines)
    head = {
        "record": "outcomes",
        "sample": {"file": sample_path.name, "sha256": sample.sha256},
        "plan": sample.head.get("plan"),
        "code": dict(code),
        "parser_version": PARSER_VERSION,
        "section_char_limit": SECTION_CHAR_LIMIT,
        "began": began,
        "ended": now(),
        "papers": found.papers,
        "unanswered": found.unanswered,
    }
    # As the sample has them, archive by archive: the order of the walk is no part of
    # the result, and a file that is written again changes only where an outcome did.
    place = {paper.arxiv_id: at for at, paper in enumerate(sample.papers)}
    return [head, *sorted(lines, key=lambda line: place[line["id"]])]


def main(
    argv: Sequence[str] | None = None,
    source: PaperSource | None = None,
    origin: Callable[[Path | None], Mapping[str, Any]] = code_version,
) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m hepph_paper_miner.survey.run",
        description="Fetch and split every paper of the sample, and write down how each came back.",
    )
    parser.add_argument("--sample", type=Path, required=True, help="the sample (survey.sample)")
    parser.add_argument("--out", type=Path, help="the outcomes to write (JSON lines)")
    parser.add_argument(
        "--limit", type=int, help="a first try: this many papers from the front, write nothing"
    )
    arguments = parser.parse_args(argv)

    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="backslashreplace")
    try:
        sample = read_sample(arguments.sample)
    except (OSError, RecordError) as error:
        print(f"cannot read the sample: {error}", file=sys.stderr)
        return 2
    trial = arguments.limit is not None
    if trial and arguments.limit < 1:
        print("--limit: at least 1", file=sys.stderr)
        return 2
    if not trial and arguments.out is None:
        print("--out: where to write the outcomes", file=sys.stderr)
        return 2

    code = origin(None)
    print(f"sample    {arguments.sample} | sha256 {sample.sha256} | {len(sample.papers)} paper(s)")
    print(
        f"code      {code.get('commit')} | modified {code.get('modified')} | parser {PARSER_VERSION}"
    )
    if not trial:
        if code.get("modified") is not False:
            print(
                "refused: files the repository keeps have been changed, so no commit names "
                "this code",
                file=sys.stderr,
            )
            return 2
        if arguments.out.exists():
            # The file is written anew by every run. Another file is not written over.
            try:
                before, lines_before = read_outcomes(arguments.out)
            except (OSError, RecordError) as error:
                print(
                    f"refused: {arguments.out} is there and is no outcomes file ({error})",
                    file=sys.stderr,
                )
                return 2
            if (before.get("sample") or {}).get("sha256") != sample.sha256:
                print(
                    f"refused: {arguments.out} holds the outcomes of another sample",
                    file=sys.stderr,
                )
                return 2
            left = sum(1 for line in lines_before if line["outcome"] == UNANSWERED)
            print(f"{arguments.out} is there with {left} paper(s) unanswered; it is written anew")

    cache = None
    if source is None:
        cache = default_cache_dir()
        source = ArxivSource(Fetcher(cache, user_agent=USER_AGENT))
    papers = walk(sample.papers)[: arguments.limit] if trial else walk(sample.papers)
    on_disk = _folder_bytes(cache) if cache is not None and cache.is_dir() else 0
    began, clock = now(), monotonic()
    try:
        lines = survey(source, papers)
    except KeyboardInterrupt:
        print(
            "stopped by hand; no file was written, and what arXiv answered is kept on disk",
            file=sys.stderr,
        )
        return 130

    found = tally(lines)
    for line in table(found):
        print(line)
    print(f"{monotonic() - clock:.0f} s")
    if cache is not None:
        grown = (_folder_bytes(cache) if cache.is_dir() else 0) - on_disk
        print(f"the folder of downloads grew by {grown / 1e6:.1f} MB: {cache}")
    if trial:
        print(
            f"a first try with {len(papers)} of {len(sample.papers)} paper(s). Nothing was written."
        )
        return 0
    write_lines(arguments.out, outcome_lines(sample, arguments.sample, lines, code, began))
    print(f"written: {arguments.out}")
    if found.count(UNEXPECTED):
        print(
            f"{found.count(UNEXPECTED)} paper(s) came back in a way nobody foresaw: read their lines"
        )
    if found.unanswered:
        print(
            f"{found.unanswered} paper(s) unanswered: run the command again to ask for them again"
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
