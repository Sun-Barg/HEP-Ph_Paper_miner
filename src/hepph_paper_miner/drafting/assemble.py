"""The questions of the second evaluation, made of the drafts the owner accepted, and a
summary of every candidate.

    uv run python -m hepph_paper_miner.drafting.assemble \\
        --places results/archives/places.jsonl \\
        --drafts runs_private/archives/drafts.jsonl --sift runs_private/archives/sift.jsonl \\
        --review results/archives/review.jsonl \\
        --questions eval_data/questions_archives.jsonl --summary results/archives/candidates.jsonl

For every kind and archive, the first four accepted drafts in the order of the walk
become questions: the file of places stands in that order. Where a kind and archive has
fewer than four, further accepted drafts of named_first of that archive take the places,
as far as there are any, and are asked as named_first. No draft is made after the review.
The mark of the paper becomes arXiv:<identifier>, and for search_first the title that
arXiv lists. The questions stand in the order of the walk and are named archives-01,
archives-02, ... A question file has no line of its own to name what it was made of, so
the summary names it by its SHA-256 beside the records it came from.

The summary (--summary) has a line for every candidate, which is a place: its place; what
the generator returned; for each of its drafts, the checks it failed and what the rule
said of the two answers of the filters; which draft the place keeps; the verdict and its
reason; the question it became; and the tokens and the computed cost of its requests.
Then the counts by kind and archive, and by reason (a draft counts under every check it
failed), with how many places kept their first, their second and their third draft. It
holds no text of a paper: no question, no anchor, no answer, no reason the generator
wrote, no note. It can go into the repository.

The summary is always written: a question file without it would not say where it came
from. A round of the tuning is summed up the same way, from its own files, without
--questions.

The questions of the rehearsal come from the last round (--rehearsal, with --questions):
two of every kind, by the same rule. A paper of the tuning has no search_first place, so
search_first takes the accepted named_first drafts whose paper a search for its title
finds (assign.look_up: the latest version, among the first five results), and named_first
the accepted named_first drafts that are left. That search is the only use of the network.

The questions are written from records that were made by the texts this code holds
(DRAFTER_VERSION and SIFT_VERSION, with their digests), and from papers split by the parser
this code holds, or not at all: a question file names the texts that drafted it in its
notes, and those are this code's.
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from hepph_paper_miner.agent.origin import code_version
from hepph_paper_miner.drafting import ask
from hepph_paper_miner.drafting import draft as drafting
from hepph_paper_miner.drafting import sift as sifting
from hepph_paper_miner.drafting.assign import Placed, PlacesFile, look_up, paper_source, read_places
from hepph_paper_miner.drafting.checks import CHECKS
from hepph_paper_miner.drafting.draft import (
    DRAFT,
    MAX_DRAFTS,
    NO_DRAFT,
    NOTHING,
    Draft,
    drafts_in,
    line_of,
    section_of,
)
from hepph_paper_miner.drafting.places import KINDS, NAMED_FIRST, SEARCH_FIRST
from hepph_paper_miner.drafting.review import ACCEPT, REASONS, REJECT, read_review
from hepph_paper_miner.eval.grade import RIGHT
from hepph_paper_miner.eval.questions import QuestionFileError, _question, problems_with_evidence
from hepph_paper_miner.sources.arxiv_latex import PARSER_VERSION
from hepph_paper_miner.sources.base import Paper, PaperSource, SourceError, parse_arxiv_id
from hepph_paper_miner.survey.records import RecordError, now, write_lines

PER_CELL = 4  # questions of every kind and archive
REHEARSAL_PER_KIND = 2  # questions of every kind in the rehearsal: ten at most


# --- what became of every place -----------------------------------------------------------


@dataclass(frozen=True)
class Drafted:
    """One draft of a place, and what the checks and the filters said of it."""

    index: int  # 1 for the first draft of its place
    failed: tuple[str, ...]  # the checks it failed
    without: str | None  # what the rule said of the answer without the paper, if asked
    passage: str | None  # and of the answer from the passage


@dataclass(frozen=True)
class Candidate:
    place: Placed
    draft: str  # DRAFT, NOTHING or NO_DRAFT
    problem: str | None  # what keeps a reply from being a draft, in the code's words
    drafts: tuple[Drafted, ...]  # in the generator's order; none when there was no draft
    kept: int | None  # the draft the place keeps (sift.kept), or None
    verdict: str | None  # ACCEPT or REJECT for the draft on the sheet
    why_rejected: str | None
    lines: tuple[Mapping[str, Any], ...]  # its replies, for the usage

    @property
    def accepted(self) -> bool:
        return self.verdict == ACCEPT


@dataclass(frozen=True)
class Records:
    """The four files a question is made of, read and held to each other."""

    places: PlacesFile
    drafts_head: dict[str, Any]
    drafts: dict[int, dict[str, Any]]
    drafts_sha256: str
    sift_head: dict[str, Any]
    sift: list[dict[str, Any]]
    sift_sha256: str
    review_head: dict[str, Any]
    verdicts: dict[int, tuple[str, str, int]]  # by place: verdict, reason, draft judged
    review_sha256: str


def read_records(places: Path, drafts: Path, sift: Path, review: Path) -> Records:
    """The records of one set of places, or RecordError when they are not of each other."""
    found = read_places(places)
    drafts_head, by_place, drafts_sha = drafting.read_drafts(drafts)
    sift_head, lines, sift_sha = sifting.read_sift(sift)
    review_head, verdicts, review_sha = read_review(review)
    if drafts_head.get("places") != found.stamp or sift_head.get("places") != found.stamp:
        raise RecordError(f"the records are not of {found.name}")
    if (sift_head.get("drafts") or {}).get("sha256") != drafts_sha:
        raise RecordError(f"{sift.name} is not a record of {drafts.name}")
    named = {name: (review_head.get(name) or {}).get("sha256") for name in ("places", "drafts")}
    named["sift"] = (review_head.get("sift") or {}).get("sha256")
    if named != {"places": found.sha256, "drafts": drafts_sha, "sift": sift_sha}:
        raise RecordError(f"{review.name} is not a review of these records")
    missing = [place.number for place in found.places if place.number not in by_place]
    if missing:
        raise RecordError(f"{drafts.name} has no reply for place {missing[0]}")
    keep = sifting.kept(lines)
    if {number: judged[2] for number, judged in verdicts.items()} != keep:
        raise RecordError(f"{review.name} does not judge the drafts that {sift.name} kept")
    return Records(
        found,
        drafts_head,
        by_place,
        drafts_sha,
        sift_head,
        lines,
        sift_sha,
        review_head,
        verdicts,
        review_sha,
    )


def candidates_of(records: Records) -> list[Candidate]:
    """What became of every place, in the order of the file of places."""
    checked: dict[int, list[dict[str, Any]]] = {}
    for line in records.sift:
        if line.get("record") == "checked":
            checked.setdefault(line["number"], []).append(line)
    said = sifting.filter_replies(records.sift)
    keep = sifting.kept(records.sift)
    found = []
    for place in records.places.places:
        reply = records.drafts[place.number]
        outcome = reply.get("outcome")
        lines = sorted(checked.get(place.number, ()), key=sifting.draft_of)
        count = len(drafts_in(reply)) if outcome == DRAFT else 0
        if [sifting.draft_of(line) for line in lines] != list(range(1, count + 1)):
            raise RecordError(f"the checks of place {place.number} do not fit its reply")
        drafted, asked = [], []
        for line in lines:
            index = sifting.draft_of(line)
            without = said.get((place.number, index, sifting.WITHOUT))
            passage = said.get((place.number, index, sifting.PASSAGE))
            drafted.append(
                Drafted(
                    index,
                    tuple(line["failed"]),
                    without.get("outcome") if without else None,
                    passage.get("outcome") if passage else None,
                )
            )
            asked += [each for each in (without, passage) if each]
        verdict, why, _ = records.verdicts.get(place.number, (None, None, None))
        found.append(
            Candidate(
                place=place,
                draft=outcome,
                problem=reply.get("problem"),
                drafts=tuple(drafted),
                kept=keep.get(place.number),
                verdict=verdict,
                why_rejected=why or None,
                lines=(reply, *asked),
            )
        )
    return found


# --- which accepted drafts become questions -----------------------------------------------


@dataclass(frozen=True)
class Chosen:
    place: Placed
    kind: str  # the kind it is asked as
    fill: bool  # a named_first draft in the place of a kind its archive was short of


def choose(
    accepted: Sequence[Placed],
    per_cell: int,
    findable: Callable[[str], bool] | None = None,
) -> list[Chosen]:
    """The places whose drafts become questions, in the order of the file of places.

    `accepted` stands in that order. For every archive and kind, the first `per_cell` of
    that kind; then, for every place a kind other than named_first could not fill, the
    next named_first. With `findable` (the rehearsal), search_first is no kind of a place:
    it takes the named_first places whose paper is findable, before named_first does, and
    `findable` is asked of one paper after another only until the kind is full.
    """
    archives = list(dict.fromkeys(place.archive for place in accepted))
    chosen: list[Chosen] = []
    for archive in archives:
        own = [place for place in accepted if place.archive == archive]
        taken: dict[int, Chosen] = {}
        short = 0
        for kind in KINDS:
            picked = 0
            for place in own:
                if picked == per_cell:
                    break
                if place.number in taken:
                    continue
                if findable is not None and kind == SEARCH_FIRST:
                    if place.kind != NAMED_FIRST or not findable(place.paper):
                        continue
                elif place.kind != kind:
                    continue
                taken[place.number] = Chosen(place, kind, False)
                picked += 1
            if kind != NAMED_FIRST:
                short += per_cell - picked
        for place in own:
            if short == 0:
                break
            if place.kind == NAMED_FIRST and place.number not in taken:
                taken[place.number] = Chosen(place, NAMED_FIRST, True)
                short -= 1
        chosen += taken.values()
    return sorted(chosen, key=lambda each: each.place.number)


# --- the question file --------------------------------------------------------------------


def papers_for(
    chosen: Sequence[Chosen], parser_version: Any, source: PaperSource
) -> dict[str, Paper]:
    """The papers of the chosen places, read as the tools read them and held to the places."""
    if parser_version != PARSER_VERSION:
        raise RecordError(
            f"the places were given out by parser {parser_version}, and this code splits "
            f"papers with parser {PARSER_VERSION}"
        )
    papers: dict[str, Paper] = {}
    for each in chosen:
        place = each.place
        if place.paper not in papers:
            papers[place.paper] = source.paper(parse_arxiv_id(place.paper))
        section = section_of(papers[place.paper], place.section)
        if section is None or not 0 <= place.start < place.end <= section.chars:
            raise RecordError(f"place {place.number} is not where the file of places says it is")
    return papers


def question_lines(
    chosen: Sequence[Chosen],
    records: Records,
    papers: Mapping[str, Paper],
    prefix: str,
) -> list[dict[str, Any]]:
    """The lines of the question file, each checked as a question file is read."""
    anchors = {
        (line["number"], sifting.draft_of(line)): line["anchor"]
        for line in records.sift
        if line.get("record") == "checked"
    }
    keep = sifting.kept(records.sift)
    width = max(2, len(str(len(chosen))))
    lines = []
    for at, each in enumerate(chosen, start=1):
        place = each.place
        index = keep[place.number]
        found = Draft.from_dict(drafts_in(records.drafts[place.number])[index - 1])
        paper = papers[place.paper]
        name = f"{prefix}-{at:0{width}d}"
        anchor = anchors[(place.number, index)]
        line = line_of(found, place, each.kind, paper.meta.title, anchor, name)
        notes = {**line["notes"], "candidate": str(place.number), "draft": str(index)}
        if place.archive:
            notes["archive"] = place.archive
        line["notes"] = notes
        try:
            question = _question(line, name)
        except QuestionFileError as error:
            raise RecordError(f"place {place.number} makes no question: {error}") from error
        problems = problems_with_evidence(question, papers)
        if problems:
            raise RecordError(problems[0])
        lines.append(line)
    return lines


def texts_problem(records: Records) -> str | None:
    """Why the records were not made by the texts this code holds, or None."""
    drafted = (records.drafts_head.get("drafter_version"), records.drafts_head.get("texts_sha256"))
    if drafted != (drafting.DRAFTER_VERSION, drafting.texts_digest()):
        return (
            f"the drafts were made by the generator {drafted[0]}, and this code holds "
            f"{drafting.DRAFTER_VERSION}"
        )
    sifted = (records.sift_head.get("sift_version"), records.sift_head.get("texts_sha256"))
    if sifted != (sifting.SIFT_VERSION, sifting.texts_digest()):
        return (
            f"the drafts were sifted by the filters {sifted[0]}, and this code holds "
            f"{sifting.SIFT_VERSION}"
        )
    return None


class Finder:
    """Whether a search for the title of a paper of the tuning finds it (assign.look_up),
    asked once a paper, with what the search said kept for the summary."""

    def __init__(self, source: PaperSource, echo: Callable[[str], None] = print) -> None:
        self._source = source
        self._echo = echo
        self.said: dict[str, dict[str, Any]] = {}

    def __call__(self, paper_id: str) -> bool:
        if paper_id not in self.said:
            looked = look_up(self._source, self._source.paper(parse_arxiv_id(paper_id)))
            self.said[paper_id] = {
                "findable": looked.findable,
                "latest": looked.latest,
                "rank": looked.rank,
                "problem": looked.problem,
            }
            self._echo(f"  {paper_id}: findable {looked.findable}, rank {looked.rank}")
        return bool(self.said[paper_id]["findable"])


# --- the summary --------------------------------------------------------------------------


def _counts(found: Sequence[Candidate]) -> dict[str, Any]:
    """Counts of places, and of drafts where the name says drafts: a place has up to three."""
    drafts = [one for each in found for one in each.drafts]
    keeps = [each.kept for each in found if each.kept is not None]
    return {
        "places": len(found),
        "with_drafts": sum(1 for each in found if each.draft == DRAFT),
        "drafts": len(drafts),
        "nothing_to_ask": sum(1 for each in found if each.draft == NOTHING),
        "no_draft": sum(1 for each in found if each.draft == NO_DRAFT),
        "passed_checks": sum(1 for one in drafts if one.failed == ()),
        "right_without_the_paper": sum(1 for one in drafts if one.without == RIGHT),
        "right_from_the_passage": sum(1 for one in drafts if one.passage == RIGHT),
        "kept": len(keeps),
        "kept_by_draft": {str(index): keeps.count(index) for index in range(1, MAX_DRAFTS + 1)},
        "accepted": sum(1 for each in found if each.verdict == ACCEPT),
        "rejected": sum(1 for each in found if each.verdict == REJECT),
    }


def summary_lines(
    found: Sequence[Candidate],
    chosen: Sequence[Chosen] | None,
    per_cell: int | None,
    records: Records,
    files: Mapping[str, Path],
    questions: Mapping[str, Any] | None,
    names: Mapping[int, str],
    searched: Mapping[str, Mapping[str, Any]],
    code: Mapping[str, Any],
) -> list[dict[str, Any]]:
    """The summary: a first line, a line for every candidate, the counts by kind and archive
    (cells), the counts by reason, and the totals.

    `questions` names the question file and `names` the question each chosen place
    became, when questions were made. `searched` holds what the search for a title said of
    the papers of the tuning that were looked up for the rehearsal.
    """
    by_number = {each.place.number: each for each in (chosen or ())}
    head = {
        "record": "candidates",
        "places": records.places.stamp,
        "drafts": {
            "file": files["drafts"].name,
            "sha256": records.drafts_sha256,
            "drafter_version": records.drafts_head.get("drafter_version"),
            "texts_sha256": records.drafts_head.get("texts_sha256"),
        },
        "sift": {
            "file": files["sift"].name,
            "sha256": records.sift_sha256,
            "sift_version": records.sift_head.get("sift_version"),
            "texts_sha256": records.sift_head.get("texts_sha256"),
        },
        "review": {"file": files["review"].name, "sha256": records.review_sha256},
        "questions": dict(questions) if questions is not None else None,
        "per_cell": per_cell,
        "parser_version": records.places.head.get("parser_version"),
        "code": dict(code),
        "made": now(),
    }
    lines: list[dict[str, Any]] = [head]
    for each in found:
        place, picked = each.place, by_number.get(each.place.number)
        used = ask.usage_totals(each.lines)
        line = {
            "record": "candidate",
            **{key: value for key, value in place.as_line().items() if key != "record"},
            "draft": each.draft,
            "problem": each.problem,
            "drafts": [
                {
                    "draft": one.index,
                    "failed_checks": list(one.failed),
                    "without_the_paper": one.without,
                    "from_the_passage": one.passage,
                }
                for one in each.drafts
            ],
            "kept": each.kept is not None,
            "kept_draft": each.kept,
            "verdict": each.verdict,
            "why_rejected": each.why_rejected,
            "question": names.get(place.number),
            "asked_as": picked.kind if picked else None,
            "fill": picked.fill if picked else None,
            "usage": used["usage"],
            "cost": used["cost"],
        }
        if place.paper in searched and place.kind == NAMED_FIRST and each.accepted:
            line["search"] = dict(searched[place.paper])
        lines.append(line)
    archives = list(dict.fromkeys(each.place.archive for each in found))
    for archive in archives:
        for kind in KINDS:
            own = [
                each for each in found if each.place.archive == archive and each.place.kind == kind
            ]
            asked = [
                each
                for each in (chosen or ())
                if each.place.archive == archive and each.kind == kind
            ]
            if not own and not asked:
                continue
            line = {"record": "cell", "archive": archive, "kind": kind, **_counts(own)}
            if chosen is not None and per_cell is not None:
                fills = sum(1 for each in asked if each.fill)
                line["questions"] = len(asked)
                line["fills"] = fills
                line["short"] = max(0, per_cell - (len(asked) - fills))
            lines.append(line)
    rejected = Counter(each.why_rejected for each in found if each.verdict == REJECT)
    lines.append(
        {
            "record": "reasons",
            "failed_checks": {
                name: sum(1 for each in found for one in each.drafts if name in one.failed)
                for name in CHECKS
            },
            "no_draft": dict(Counter(each.problem for each in found if each.draft == NO_DRAFT)),
            "rejected": {name: rejected[name] for name in REASONS},
        }
    )
    used = ask.usage_totals([line for each in found for line in each.lines])
    total = {"record": "total", **_counts(found)}
    if chosen is not None:
        total["questions"] = len(chosen)
        total["fills"] = sum(1 for each in chosen if each.fill)
    lines.append({**total, "usage": used["usage"], "cost": used["cost"]})
    return lines


def table(lines: Sequence[Mapping[str, Any]]) -> list[str]:
    """The counts by kind and archive, as the command prints them."""
    names = ("places", "drafts", "passed_checks", "kept", "accepted", "questions")
    shown = ("places", "drafts", "checks", "kept", "accepted", "questions")
    out = [f"{'archive':<9} {'kind':<13} " + " ".join(f"{name:>9}" for name in shown)]
    for line in lines:
        if line["record"] not in ("cell", "total"):
            continue
        archive = "all" if line["record"] == "total" else (line["archive"] or "-")
        kind = "" if line["record"] == "total" else line["kind"]
        values = [line.get(name) for name in names]
        out.append(
            f"{archive:<9} {kind:<13} "
            + " ".join(f"{'-' if value is None else value:>9}" for value in values)
        )
    return out


# --- the command --------------------------------------------------------------------------


def main(
    argv: Sequence[str] | None = None,
    source: PaperSource | None = None,
    origin: Callable[[], Mapping[str, Any]] = code_version,
) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m hepph_paper_miner.drafting.assemble",
        description="Make the questions of the drafts that were accepted, and sum up every "
        "candidate.",
    )
    parser.add_argument("--places", type=Path, required=True, help="the file of places")
    parser.add_argument("--drafts", type=Path, required=True, help="the record of the generator")
    parser.add_argument("--sift", type=Path, required=True, help="the record of the filters")
    parser.add_argument("--review", type=Path, required=True, help="the file of verdicts")
    parser.add_argument("--questions", type=Path, help="the question file to write")
    parser.add_argument(
        "--summary", type=Path, required=True, help="the summary to write, which names them all"
    )
    parser.add_argument(
        "--rehearsal",
        action="store_true",
        help="with --questions: the questions of the rehearsal, from the last round of the tuning",
    )
    arguments = parser.parse_args(argv)

    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="backslashreplace")
    if arguments.rehearsal and arguments.questions is None:
        print("--rehearsal makes questions: give --questions", file=sys.stderr)
        return 2
    for path in (arguments.questions, arguments.summary):
        if path is not None and path.exists():
            print(f"refused: {path} is there already; move it away first", file=sys.stderr)
            return 1
    code = origin()
    if code.get("modified") is not False:
        # The summary names the commit that made it, as every record of the repository does.
        print(
            "refused: the code has changes that are not committed, or git cannot name it",
            file=sys.stderr,
        )
        return 1
    try:
        records = read_records(arguments.places, arguments.drafts, arguments.sift, arguments.review)
        found = candidates_of(records)
    except (OSError, RecordError, ask.AskError) as error:
        print(f"refused: {error}", file=sys.stderr)
        return 1

    tuning = records.places.head.get("input") == "tuning"
    chosen: list[Chosen] | None = None
    per_cell: int | None = None
    questions: dict[str, Any] | None = None
    names: dict[int, str] = {}
    searched: dict[str, dict[str, Any]] = {}
    if arguments.questions is not None:
        if tuning and not arguments.rehearsal:
            print(
                "refused: the places are of the tuning; their questions are the rehearsal's "
                "(--rehearsal)",
                file=sys.stderr,
            )
            return 1
        if arguments.rehearsal and not (tuning and records.places.head.get("last") is True):
            print(
                "refused: the rehearsal is made of the last round of the tuning, and "
                f"{records.places.name} is not of it",
                file=sys.stderr,
            )
            return 1
        problem = texts_problem(records)
        if problem:
            print(f"refused: {problem}", file=sys.stderr)
            return 1
        source = source or paper_source()
        per_cell = REHEARSAL_PER_KIND if arguments.rehearsal else PER_CELL
        accepted = [each.place for each in found if each.accepted]
        finder = Finder(source) if arguments.rehearsal else None
        try:
            chosen = choose(accepted, per_cell, finder)
            papers = papers_for(chosen, records.places.head.get("parser_version"), source)
            prefix = "rehearsal" if arguments.rehearsal else "archives"
            lines = question_lines(chosen, records, papers, prefix)
        except (OSError, RecordError, SourceError) as error:
            print(f"refused: {error}", file=sys.stderr)
            return 1
        if finder is not None:
            searched = finder.said
        digest = write_lines(arguments.questions, lines)
        questions = {"file": arguments.questions.name, "sha256": digest, "questions": len(lines)}
        names = {each.place.number: line["id"] for each, line in zip(chosen, lines)}
        print(f"{len(lines)} question(s) written to {arguments.questions} (SHA-256 {digest})")

    files = {"drafts": arguments.drafts, "sift": arguments.sift, "review": arguments.review}
    lines = summary_lines(found, chosen, per_cell, records, files, questions, names, searched, code)
    digest = write_lines(arguments.summary, lines)
    print(f"the summary written to {arguments.summary} (SHA-256 {digest[:16]})")
    for line in table(lines):
        print(line)
    total = lines[-1]
    by_draft = ", ".join(f"draft {name}: {n}" for name, n in total["kept_by_draft"].items())
    print(f"the places that keep a draft keep ({by_draft})")
    if total["cost"] is not None:
        print(f"cost of the requests, computed: ${total['cost']:.2f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
