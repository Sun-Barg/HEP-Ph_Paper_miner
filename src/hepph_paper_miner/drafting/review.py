"""The sheet on which the owner reads every draft that is kept, beside its passage.

    uv run python -m hepph_paper_miner.drafting.review \\
        --places runs_private/drafting/round-1/places.jsonl \\
        --drafts runs_private/drafting/round-1/drafts.jsonl \\
        --sift runs_private/drafting/round-1/sift.jsonl \\
        --sheet runs_private/drafting/round-1/review-sheet.csv \\
        --key runs_private/drafting/round-1/review-key.jsonl

writes the sheet and its key. Once every row has its verdict,

    uv run python -m hepph_paper_miner.drafting.review --read \\
        --sheet runs_private/drafting/round-1/review-sheet.csv \\
        --key runs_private/drafting/round-1/review-key.jsonl --out <verdicts>.jsonl

reads it back into a file of verdicts.

A row shows what a reviewer judges a draft by, and nothing else: the question as a run
would be asked it, the section of its passage, the passage (the paragraph of the part
that holds the anchor, with the anchor between ⟦ and ⟧), the reference answer, the key
and the note. Not its kind, its archive or its place in the walk: the first four drafts
that are accepted in a kind and archive become the questions, and which kind is short of
drafts is not to enter a verdict. The rows stand in the order of the SHA-256 of
"<seed>:<paper>:<section>:<start>", so that the order is drawn by no one, and the key
says which place a row is.

A verdict is "accept" or "reject", and a draft is judged as it stands: no word of it is
changed. A rejection names one of the kinds of REASONS, and "other" says what in the
note. The verdicts are written without the notes, since a note can quote the passage.

The sheet is CSV in UTF-8 with a byte-order mark, so that Excel reads its letters right;
it has to be saved as "CSV UTF-8" again. The sheet and the key hold paper text, so they
go into runs_private/.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import sys
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from hepph_paper_miner.agent.origin import file_digest
from hepph_paper_miner.drafting import ask
from hepph_paper_miner.drafting.assign import Placed, PlacesFile, paper_source, read_places
from hepph_paper_miner.drafting.draft import Draft, fill_paper, papers_of, read_drafts, section_of
from hepph_paper_miner.drafting.sift import kept, read_sift
from hepph_paper_miner.sources.base import Paper, PaperSource, SourceError
from hepph_paper_miner.survey.records import RecordError, now, read_lines, write_lines

SHEET_COLUMNS = (
    "number",
    "question",
    "section",
    "passage",
    "reference_answer",
    "key",
    "accept_note",
    "verdict",
    "why_rejected",
    "note",
)
ACCEPT, REJECT = "accept", "reject"
VERDICTS = (ACCEPT, REJECT)
REASONS = {
    "ambiguous": "to somebody who has the passage, the question reads more than one way",
    "not_the_passage": "the reference answer is not what the passage says",
    "key_or_note": "the key or the note does not fit the reference answer",
    "not_running_text": "the passage is a table, a caption, a list of names or an equation",
    "other": "anything else, said in the note",
}
OTHER = "other"
# How far a passage reaches on either side of its anchor at most.
REACH = 2_000

_BLANK_LINE = re.compile(r"\n[ \t]*\n")


class ReviewError(ValueError):
    """A sheet or a key that cannot be used as it is. The message says where."""


def passage_of(text: str, start: int, end: int, at: int, anchor: str) -> str:
    """The paragraph of a part that holds the anchor, with the anchor marked.

    It runs from the blank line before the anchor to the one after it, inside the part
    and at most REACH characters on either side.
    """
    stop = at + len(anchor)
    low = max(start, at - REACH)
    before = [match.end() for match in _BLANK_LINE.finditer(text, low, at)]
    begin = before[-1] if before else low
    high = min(end, stop + REACH)
    after = _BLANK_LINE.search(text, stop, high)
    finish = after.start() if after else high
    return f"{text[begin:at]}⟦{text[at:stop]}⟧{text[stop:finish]}".strip()


def key_text(draft: Draft) -> str:
    """The key of a draft as a reader reads it."""
    parts = []
    for item in draft.numbers:
        unit = f" {item['unit']}" if item["unit"].strip() else ""
        digits = item["min_sig_figs"]
        parts.append(f"{item['label']}: {json.dumps(item['value'])}{unit} (≥ {digits} digit(s))")
    for item in draft.phrases:
        wordings = " / ".join(f'"{wording}"' for wording in item["any_of"])
        parts.append(f"{item['label']}: one of {wordings}")
    return "; ".join(parts)


def order_key(seed: int, place: Placed) -> str:
    return hashlib.sha256(
        f"{seed}:{place.paper}:{place.section}:{place.start}".encode()
    ).hexdigest()


@dataclass(frozen=True)
class Row:
    row: int
    place: Placed
    question: str
    section: str
    passage: str
    reference_answer: str
    key: str
    accept_note: str


def rows_of(
    places: PlacesFile,
    drafts: Mapping[int, Mapping[str, Any]],
    lines: Sequence[Mapping[str, Any]],
    papers: Mapping[str, Paper],
) -> list[Row]:
    """A row for every draft the filters kept, in the order of the hash."""
    by_number = {place.number: place for place in places.places}
    checked = {line["number"]: line for line in lines if line.get("record") == "checked"}
    chosen = sorted(
        (by_number[number] for number in kept(lines)),
        key=lambda place: order_key(places.head["seed"], place),
    )
    rows = []
    for at, place in enumerate(chosen, start=1):
        paper = papers[place.paper]
        section = section_of(paper, place.section)
        draft = Draft.from_dict(drafts[place.number]["draft"])
        anchor, where = checked[place.number]["anchor"], checked[place.number]["at"]
        rows.append(
            Row(
                at,
                place,
                fill_paper(draft.question, place.kind, place.paper, paper.meta.title),
                f"{section.section_id} | {section.title}",
                passage_of(section.text, place.start, place.end, where, anchor),
                draft.reference_answer,
                key_text(draft),
                draft.accept_note,
            )
        )
    return rows


def _cell(text: str) -> str:
    """Text as a spreadsheet shows it: one that begins like a formula is kept as text."""
    return " " + text if text[:1] in ("=", "+", "-", "@", "\t", "\r") else text


def write_sheet(rows: Sequence[Row], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(SHEET_COLUMNS)
        for row in rows:
            texts = (row.question, row.section, row.passage, row.reference_answer, row.key)
            writer.writerow(
                [row.row, *(_cell(text) for text in texts), _cell(row.accept_note), "", "", ""]
            )


def key_lines(rows: Sequence[Row], head: Mapping[str, Any]) -> list[dict[str, Any]]:
    return [
        dict(head),
        *(
            {
                "record": "row",
                "row": row.row,
                "number": row.place.number,
                "paper": row.place.paper,
                "kind": row.place.kind,
                "section": row.place.section,
                "start": row.place.start,
                "end": row.place.end,
                "question": row.question,
            }
            for row in rows
        ),
    ]


# --- reading the verdicts back -------------------------------------------------------------


@dataclass(frozen=True)
class Verdict:
    row: int
    number: int  # the place in the file of places
    paper: str
    kind: str
    verdict: str  # ACCEPT or REJECT
    why_rejected: str  # one of REASONS, or "" for an accepted draft


def _same(one: str, other: str) -> bool:
    return " ".join(one.split()) == " ".join(other.split())


def read_verdicts(sheet: Path, key: Path) -> tuple[dict[str, Any], list[Verdict]]:
    """The verdicts of a sheet, each with its place, in the order of the rows.

    Refused as a whole when a row cannot be matched to the key, or when a row is not
    judged: a verdict put next to the wrong draft would decide a question without anyone
    seeing it.
    """
    lines, _ = read_lines(key, "review-key")
    rows = {line["row"]: line for line in lines[1:] if line.get("record") == "row"}
    try:
        with sheet.open(encoding="utf-8-sig", newline="") as stream:
            found = list(csv.DictReader(stream))
    except UnicodeDecodeError as error:
        raise ReviewError(
            f'{sheet.name}: the sheet is not UTF-8 text; save it as "CSV UTF-8" ({error})'
        ) from error
    wanted = {"number", "question", "verdict", "why_rejected", "note"}
    if found and not wanted <= set(found[0]):
        raise ReviewError(f"{sheet.name}: the columns {', '.join(sorted(wanted))} are needed")
    verdicts: dict[int, Verdict] = {}
    for at, line in enumerate(found, start=2):  # the first line of the file is the header
        values = {name: (value or "").strip() for name, value in line.items() if name}
        if not any(values.values()):
            continue  # an empty line that a spreadsheet left
        where = f"{sheet.name} line {at}"
        try:
            number = int(values.get("number", ""))
        except ValueError:
            raise ReviewError(f"{where}: number {values.get('number')!r} is not a number") from None
        if number in verdicts:
            raise ReviewError(f"{where}: row {number} is there twice")
        row = rows.get(number)
        if row is None:
            raise ReviewError(f"{where}: row {number} is not in the key {key.name}")
        if not _same(values.get("question", ""), row["question"]):
            raise ReviewError(f"{where}: row {number} has another question than the key says")
        verdict = values.get("verdict", "").casefold()
        why = values.get("why_rejected", "").casefold()
        if verdict not in VERDICTS:
            raise ReviewError(
                f"{where}: the verdict is {values.get('verdict')!r}, not accept or reject"
            )
        if verdict == REJECT and why not in REASONS:
            raise ReviewError(
                f"{where}: a rejection needs one of {', '.join(REASONS)} under why_rejected"
            )
        if verdict == ACCEPT and why:
            raise ReviewError(f"{where}: an accepted draft has a reason for a rejection")
        if why == OTHER and not values.get("note"):
            raise ReviewError(f"{where}: a rejection for another reason says which in the note")
        verdicts[number] = Verdict(number, row["number"], row["paper"], row["kind"], verdict, why)
    missing = sorted(set(rows) - set(verdicts))
    if missing:
        shown = ", ".join(str(number) for number in missing[:10])
        raise ReviewError(f"{sheet.name}: no row for number(s) {shown} of the key")
    return lines[0], [verdicts[number] for number in sorted(verdicts)]


def verdict_lines(
    key_head: Mapping[str, Any], sheet: Path, key: Path, verdicts: Sequence[Verdict]
) -> list[dict[str, Any]]:
    """The file of verdicts: no question, no passage and no note, by the place of each draft."""
    reasons = Counter(each.why_rejected for each in verdicts if each.verdict == REJECT)
    head = {
        "record": "review",
        "places": key_head.get("places"),
        "drafts": key_head.get("drafts"),
        "sift": key_head.get("sift"),
        "key": {"file": key.name, "sha256": file_digest(key)},
        "sheet": {"file": sheet.name, "sha256": file_digest(sheet)},
        "read": now(),
        "accepted": sum(1 for each in verdicts if each.verdict == ACCEPT),
        "rejected": sum(1 for each in verdicts if each.verdict == REJECT),
        "reasons": {name: reasons[name] for name in REASONS},
    }
    lines = [
        {
            "record": "verdict",
            "number": each.number,
            "paper": each.paper,
            "kind": each.kind,
            "verdict": each.verdict,
            "why_rejected": each.why_rejected or None,
        }
        for each in sorted(verdicts, key=lambda each: each.number)
    ]
    return [head, *lines]


def read_review(path: Path) -> tuple[dict[str, Any], dict[int, tuple[str, str]], str]:
    """A file of verdicts (--read --out): its first line, by place the verdict and the reason
    of a rejection ("" for an accepted draft), and its SHA-256."""
    lines, digest = read_lines(path, "review")
    found: dict[int, tuple[str, str]] = {}
    for line in lines[1:]:
        if line.get("record") != "verdict":
            continue
        number, verdict, why = line.get("number"), line.get("verdict"), line.get("why_rejected")
        if isinstance(number, bool) or not isinstance(number, int) or number in found:
            raise RecordError(f"{path.name}: a verdict without its place, or one twice")
        named = isinstance(why, str) and why in REASONS
        if verdict not in VERDICTS or (verdict == REJECT) != named or (not named and why):
            raise RecordError(f"{path.name}: the verdict on place {number} is not of the form")
        found[number] = (verdict, why or "")
    return lines[0], found, digest


def main(argv: Sequence[str] | None = None, source: PaperSource | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m hepph_paper_miner.drafting.review",
        description="Write the sheet of the drafts that are kept, or read its verdicts back.",
    )
    parser.add_argument("--places", type=Path, help="the file of places")
    parser.add_argument("--drafts", type=Path, help="the record of the generator")
    parser.add_argument("--sift", type=Path, help="the record of the filters")
    parser.add_argument("--sheet", type=Path, required=True, help="the sheet, in runs_private/")
    parser.add_argument("--key", type=Path, required=True, help="its key, in runs_private/")
    parser.add_argument("--read", action="store_true", help="read the verdicts of a sheet")
    parser.add_argument("--out", type=Path, help="with --read: the file of verdicts to write")
    arguments = parser.parse_args(argv)

    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="backslashreplace")
    if arguments.read:
        if arguments.out is None:
            print("--read needs --out", file=sys.stderr)
            return 2
        if arguments.out.exists():
            print(f"refused: {arguments.out} is there already; move it away first", file=sys.stderr)
            return 1
        try:
            key_head, verdicts = read_verdicts(arguments.sheet, arguments.key)
        except (OSError, RecordError, ReviewError) as error:
            print(f"refused: {error}", file=sys.stderr)
            return 1
        lines = verdict_lines(key_head, arguments.sheet, arguments.key, verdicts)
        write_lines(arguments.out, lines)
        head = lines[0]
        print(
            f"{len(verdicts)} verdict(s): {head['accepted']} accepted, {head['rejected']} rejected"
        )
        return 0

    if None in (arguments.places, arguments.drafts, arguments.sift):
        print("a sheet is written from --places, --drafts and --sift", file=sys.stderr)
        return 2
    for path in (arguments.sheet, arguments.key):
        problem = ask.private_path_problem(path)
        if problem:
            print(f"refused: {problem}", file=sys.stderr)
            return 2
        if path.exists():
            print(f"refused: {path} is there already; move it away first", file=sys.stderr)
            return 1
    try:
        places = read_places(arguments.places)
        drafts_head, drafts, drafts_sha = read_drafts(arguments.drafts)
        sift_head, lines, sift_sha = read_sift(arguments.sift)
        if drafts_head.get("places") != places.stamp or sift_head.get("places") != places.stamp:
            raise RecordError("the records are not of this file of places")
        if (sift_head.get("drafts") or {}).get("sha256") != drafts_sha:
            raise RecordError(f"{arguments.sift.name} is not a record of {arguments.drafts.name}")
        papers = papers_of(places, source or paper_source())
        rows = rows_of(places, drafts, lines, papers)
    except (OSError, RecordError, SourceError, ask.AskError) as error:
        print(f"refused: {error}", file=sys.stderr)
        return 1
    head = {
        "record": "review-key",
        "places": places.stamp,
        "drafts": {"file": arguments.drafts.name, "sha256": drafts_sha},
        "sift": {"file": arguments.sift.name, "sha256": sift_sha},
        "seed": places.head["seed"],
        "made": now(),
    }
    write_sheet(rows, arguments.sheet)
    write_lines(arguments.key, key_lines(rows, head))
    print(f"{len(rows)} row(s) written to {arguments.sheet}, the key to {arguments.key}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
