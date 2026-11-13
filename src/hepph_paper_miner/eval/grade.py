"""Grade one run from its public record.

Four things are asked of a run. Each is answered from the record, the question and the
parsed papers, without a model:

    search     Did a search return the paper that holds the answer, and at which rank?
    access     Was the passage the answer rests on given to the model, and in which turn?
    citation   Does the evidence the answer lists name the sections it rests on?
    answer     Does the answer say "found" as expected, and does it hold the numbers and
               the phrases of the answer key?

The first three are facts. The fourth is a rule, and a rule cannot read: a person
grades every answer, and what the rule said is kept beside that grade so that the two
can be compared. A run that gave no answer has a wrong answer; why it gave none is in
its record.

A record holds no paper text. It says which characters of which section, or of the
whole text, each call returned. Where the passage of a question stands is worked out
here, from the parsed paper and the anchor of the question. So a run has to be graded
against papers split by the same parser that split them for the run.

    uv run python -m hepph_paper_miner.eval.grade "results/runs/dev/diag-1/*.jsonl"

reads the papers through the cache of downloads, and asks arXiv for one that is not
in it.
"""

from __future__ import annotations

import argparse
import glob
import json
import re
import sys
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import asdict, dataclass
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from typing import Any

from hepph_paper_miner.eval.questions import Question, QuestionFileError, load_questions
from hepph_paper_miner.server import full_text, section_marker
from hepph_paper_miner.sources.base import Paper, PaperSource, SourceError, parse_arxiv_id

# What the rule says of an answer.
RIGHT = "right"  # everything a rule can check is there, and nothing is left for a person
WRONG = "wrong"  # no answer, "found" the wrong way round, or something of the key is missing
BY_HAND = "by_hand"  # nothing is missing, but a person has to look (see AnswerGrade.why)


class RecordError(ValueError):
    """A file that is not the record of a finished run."""


@dataclass(frozen=True)
class Record:
    """The public record of one finished run: its first line, its turns, its last line."""

    run: dict[str, Any]
    turns: tuple[dict[str, Any], ...]
    end: dict[str, Any]


def read_record(path: Path) -> Record:
    """Read a public record, and refuse one whose run did not finish.

    A run that died has no last line, so nothing says how it ended. It is not a run
    with a wrong answer, and must not be counted as one.
    """
    lines = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]
    if not lines or lines[0].get("record") != "run":
        raise RecordError(f"{path.name}: not the record of a run")
    if lines[-1].get("record") != "end":
        raise RecordError(f"{path.name}: the run did not finish (no last line)")
    return Record(lines[0], tuple(x for x in lines[1:-1] if x.get("record") == "turn"), lines[-1])


# --- places in a paper -------------------------------------------------------------------


def plain_id(text: str) -> str | None:
    """An arXiv identifier in the one form the tools write, or None when it is none.

    "arXiv:2610.26648v1" and " 2610.26648v1 " both name 2610.26648v1. A tool takes
    either, and a model that was asked with one of them cites it that way.
    """
    try:
        return str(parse_arxiv_id(text))
    except SourceError:
        return None


def parent_of(section_id: str) -> str | None:
    """The section a subsection stands in: "6" for "6.3", "A" for "A.1", None for "6".

    The parser names a subsection after its section, so the name says it.
    """
    head, dot, _ = section_id.rpartition(".")
    return head if dot else None


def _all(text: str, piece: str) -> list[int]:
    found, at = [], text.find(piece)
    while at != -1:
        found.append(at)
        at = text.find(piece, at + 1)
    return found


def _add(covered: list[tuple[int, int]], start: int, stop: int) -> None:
    """Put [start, stop) into a sorted list of stretches that do not touch."""
    if stop <= start:
        return
    merged: list[tuple[int, int]] = []
    for low, high in sorted([*covered, (start, stop)]):
        if merged and low <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], high))
        else:
            merged.append((low, high))
    covered[:] = merged


def _covers(covered: list[tuple[int, int]], start: int, stop: int) -> bool:
    return any(low <= start and stop <= high for low, high in covered)


class Places:
    """Where the text of one paper stands, on the two scales a record uses.

    The staged layout says which characters of a section a call returned, and the text
    of a section holds its subsections. So every such stretch is put on the scale of
    the top-level section it lies in: reading "6.3", and reading the part of "6" that
    holds "6.3", then cover the same characters.

    The flat layout says which characters of the whole text a call returned. That text
    has a marker line in front of every section, and a section stands between its
    marker and the next marker that is not one of its own subsections.
    """

    def __init__(self, paper: Paper) -> None:
        self.paper = paper
        self._sections = {section.section_id: section for section in paper.sections}
        self._in_top: dict[str, tuple[str, int]] = {}
        top = None
        for section in paper.sections:
            if section.level == 1:
                top = section
                self._in_top[section.section_id] = (section.section_id, 0)
            elif top is not None:
                at = top.text.find(section.text, section.heading_at or 0)
                if at != -1:
                    self._in_top[section.section_id] = (top.section_id, at)
        self._whole = full_text(paper)
        marked: list[tuple[int, int, str]] = []  # level, place of the marker, section id
        cursor = 0
        for section in paper.sections:
            at = self._whole.find(section_marker(section) + "\n", cursor)
            if at != -1:  # a subsection made by hand can be without a marker
                marked.append((section.level, at, section.section_id))
                cursor = at + 1
        self._in_whole: dict[str, tuple[int, int]] = {}
        for index, (level, at, section_id) in enumerate(marked):
            later = [place for other, place, _ in marked[index + 1 :] if other <= level]
            self._in_whole[section_id] = (at, later[0] if later else len(self._whole))

    def read(self, section_id: str, start: int, stop: int) -> tuple[str, int, int]:
        """A stretch of a section, on the scale of its top-level section."""
        top, offset = self._in_top.get(section_id, (section_id, 0))
        return top, offset + start, offset + stop

    def in_sections(self, section_id: str, anchor: str | None) -> tuple[str, list[tuple[int, int]]]:
        """Every place of a passage, on the scale of its top-level section.

        Without an anchor the passage is the whole section. An anchor that stands in
        its section more than once marks every one of those places: the fact is
        stated at each, and a run that was given one of them was given the fact.
        """
        section = self._sections.get(section_id)
        if section is None or section_id not in self._in_top:
            return section_id, []
        top, offset = self._in_top[section_id]
        if anchor is None:
            return top, [(offset, offset + section.chars)]
        return top, [(offset + at, offset + at + len(anchor)) for at in _all(section.text, anchor)]

    def in_whole(self, section_id: str, anchor: str | None) -> list[tuple[int, int]]:
        """Every place of a passage in the whole text of the paper."""
        if section_id not in self._in_whole:
            return []
        start, stop = self._in_whole[section_id]
        if anchor is None:
            return [(start, stop)]
        return [
            (start + at, start + at + len(anchor)) for at in _all(self._whole[start:stop], anchor)
        ]


@dataclass(frozen=True)
class _Read:
    """A call that returned text of a paper, as the first line of its result says."""

    turn: int
    arxiv_id: str
    section_id: str | None  # None: a stretch of the whole text (the flat layout)
    start: int
    stop: int


def _reads(record: Record) -> Iterator[_Read]:
    for turn in record.turns:
        for tool in turn["tools"]:
            first = tool.get("first_line") or {}
            if tool.get("status") != "ok" or "start" not in first:
                continue  # an error, a search, an outline, or a paper without text
            yield _Read(
                turn["turn"],
                first["arxiv_id"],
                first.get("section_id"),
                first["start"],
                first["stop"],
            )


# --- search ------------------------------------------------------------------------------


@dataclass(frozen=True)
class SearchGrade:
    searches: int  # searches that came back
    empty: int  # of them, without a single paper
    # For each paper that holds the answer: the turn of the first search that listed it,
    # its rank in that list, and whether the version listed was the one of the question.
    # None when no search listed it (the model may have had the identifier anyway).
    first_hit: dict[str, tuple[int, int, bool] | None]


def grade_search(record: Record, question: Question) -> SearchGrade:
    lists = [
        (turn["turn"], (tool.get("first_line") or {})["ids"])
        for turn in record.turns
        for tool in turn["tools"]
        if tool.get("status") == "ok" and (tool.get("first_line") or {}).get("shape") == "search"
    ]
    first_hit: dict[str, tuple[int, int, bool] | None] = {}
    for gold in question.gold_papers:
        base = parse_arxiv_id(gold).base
        first_hit[gold] = None
        for turn, ids in lists:
            ranks = [n for n, listed in enumerate(ids, start=1) if _base(listed) == base]
            if ranks:
                first_hit[gold] = (turn, ranks[0], ids[ranks[0] - 1] == gold)
                break
    return SearchGrade(len(lists), sum(1 for _, ids in lists if not ids), first_hit)


def _base(listed: str) -> str | None:
    try:
        return parse_arxiv_id(listed).base
    except SourceError:
        return None


# --- access ------------------------------------------------------------------------------


@dataclass(frozen=True)
class AccessGrade:
    need: str  # "all" or "any", from the question
    # For each piece of evidence: the turn whose results completed its passage, or None.
    delivered_in: tuple[int | None, ...]
    met: bool | None  # None: a paper of the question was not given, so nobody can tell
    turn: int | None  # the turn in which the model had what the question needs
    turns_after: int | None  # how many more responses the run took from there


def grade_access(
    record: Record, question: Question, papers: Mapping[str, Paper]
) -> tuple[AccessGrade, list[str]]:
    """Whether, and when, the passages of the question were given to the model.

    A passage counts as given once the calls so far have returned every character of
    one of its places, in one piece or in several: a long section comes in pieces, and
    the cut can fall inside a passage.
    """
    problems = []
    places = {key: Places(papers[key]) for key in question.gold_papers if key in papers}
    for missing in sorted(set(question.gold_papers) - set(places)):
        problems.append(f"{missing} was not given: access cannot be told")
    passages = []
    for item in question.evidence:
        place = places.get(item.arxiv_id)
        if place is None:
            passages.append(None)
            continue
        top, in_sections = place.in_sections(item.section_id, item.anchor)
        in_whole = place.in_whole(item.section_id, item.anchor)
        if not in_sections:
            problems.append(
                f"{item.arxiv_id} {item.section_id}: the evidence is not in the paper as it is "
                "split now (another parser, or a question that was never checked)"
            )
        passages.append((top, in_sections, in_whole))

    in_section: dict[tuple[str, str], list[tuple[int, int]]] = {}
    in_paper: dict[str, list[tuple[int, int]]] = {}
    delivered: list[int | None] = [None] * len(question.evidence)
    for read in _reads(record):
        place = places.get(read.arxiv_id)
        if place is None:
            continue
        if read.section_id is None:
            _add(in_paper.setdefault(read.arxiv_id, []), read.start, read.stop)
        else:
            top, start, stop = place.read(read.section_id, read.start, read.stop)
            _add(in_section.setdefault((read.arxiv_id, top), []), start, stop)
        for index, item in enumerate(question.evidence):
            passage = passages[index]
            if delivered[index] is not None or passage is None or item.arxiv_id != read.arxiv_id:
                continue
            top, wanted_in_sections, wanted_in_whole = passage
            by_sections = in_section.get((item.arxiv_id, top), [])
            by_paper = in_paper.get(item.arxiv_id, [])
            if any(_covers(by_sections, *span) for span in wanted_in_sections) or any(
                _covers(by_paper, *span) for span in wanted_in_whole
            ):
                delivered[index] = read.turn

    if any(passage is None for passage in passages):
        return AccessGrade(question.need, tuple(delivered), None, None, None), problems
    turns = [turn for turn in delivered if turn is not None]
    if question.need == "all":
        met = len(turns) == len(delivered)
        turn = max(turns) if met else None
    else:
        met = bool(turns)
        turn = min(turns) if met else None
    after = record.end["turns"] - turn if turn is not None else None
    return AccessGrade(question.need, tuple(delivered), met, turn, after), problems


# --- citation ----------------------------------------------------------------------------


@dataclass(frozen=True)
class CitationGrade:
    cited: tuple[tuple[str, str], ...]  # paper and section, as the answer wrote them
    strict: bool  # the evidence of the question is cited, section for section
    loose: bool  # the same, with the section around a subsection taken for the subsection
    extra: int  # cited places that are no evidence of the question, not even loosely
    not_as_shown: int  # identifiers written in another form than the tools show
    unread: int  # cited sections of which the run asked for nothing


def grade_citation(record: Record, question: Question) -> CitationGrade | None:
    """How the evidence an answer lists compares with the evidence of the question.

    None for a run without an answer. Identifiers are compared in their plain form,
    with the version: another version of a paper may be split into other sections.
    """
    answer = record.end.get("answer")
    if not answer:
        return None
    cited = [(item["arxiv_id"], item["section_id"]) for item in answer["evidence"]]
    plain = [(plain_id(paper), section.strip()) for paper, section in cited]

    def is_cited(item, loosely: bool) -> bool:
        wanted = {item.section_id}
        if loosely and parent_of(item.section_id):
            wanted.add(parent_of(item.section_id))
        return any(paper == item.arxiv_id and section in wanted for paper, section in plain)

    quantifier = all if question.need == "all" else any
    loose_places = {
        (item.arxiv_id, section)
        for item in question.evidence
        for section in (item.section_id, parent_of(item.section_id))
        if section
    }
    asked = [(read.arxiv_id, read.section_id) for read in _reads(record)]
    return CitationGrade(
        cited=tuple(cited),
        strict=quantifier(is_cited(item, False) for item in question.evidence),
        loose=quantifier(is_cited(item, True) for item in question.evidence),
        extra=sum(1 for place in plain if place not in loose_places),
        not_as_shown=sum(1 for (paper, _), (as_plain, _) in zip(cited, plain) if paper != as_plain),
        unread=sum(1 for place in plain if not _asked_for(place, asked)),
    )


def _asked_for(place: tuple[str | None, str], asked: list[tuple[str, str | None]]) -> bool:
    """Whether a run asked for any text of a cited section.

    Coarse on purpose: the section itself, the section around it, a subsection of it,
    or the whole paper. It answers "did the answer cite a section the run never
    opened", and not "did the run read all of it".
    """
    paper, section = place
    for read_paper, read_section in asked:
        if read_paper != paper:
            continue
        if read_section is None or read_section == section:
            return True
        if parent_of(section) == read_section or parent_of(read_section) == section:
            return True
    return False


# --- answer ------------------------------------------------------------------------------


@dataclass(frozen=True)
class Number:
    """A number as an answer writes it."""

    value: Decimal
    digits: int  # significant digits as written: 3 for "62.6", 4 for "0.7910", 2 for "63"
    text: str


_SUPERSCRIPT = str.maketrans("⁰¹²³⁴⁵⁶⁷⁸⁹⁺⁻", "0123456789+-")
_TIMES_TEN = r"\s*(?:×|x|\\times|·|\*)\s*10"
_NUMBER = re.compile(
    rf"""
    (?: (?<![\w)\]}}.]) (?P<sign>[-−])     # a minus sign, when no number or word stands before it:
      | (?<![\w.]) )                        # "0.2-0.4" is a range, and the "2" of "h2" is no number
    (?P<mantissa> \d{{1,3}}(?:,\d{{3}})+(?:\.\d+)? | \d+(?:\.\d+)? )
    (?: {_TIMES_TEN} \s*\^\s* [{{(]? (?P<power>[-−+]?\d+) [}})]?     # 2.26×10^-26, 2.26\times 10^{{-26}}
      | {_TIMES_TEN} (?P<raised>[⁺⁻]?[⁰¹²³⁴⁵⁶⁷⁸⁹]+)                  # 2.26×10⁻²⁶
      | [eE] (?P<exponent>[-−+]?\d+) (?![\w.])                       # 2.26e-26
      | \^\s* [{{(]? (?P<bare>[-−+]?\d+) [}})]?                       # 10^-26, with nothing in front
      | (?P<bare_raised>[⁺⁻]?[⁰¹²³⁴⁵⁶⁷⁸⁹]+)                          # 10⁻²⁶
    )?
    """,
    re.VERBOSE,
)


def numbers_in(text: str) -> list[Number]:
    """Every number an answer writes, with the digits it was written with.

    Read: 62.6, 0.7910, 19,837, -3, 2.26×10⁻²⁶ in the forms a model writes it, and a
    bare 10^-26. Not read as a number: digits inside a name ("h2", "FL16Y"), and the
    dash of a range ("0.2-0.4" is 0.2 and 0.4). A power on anything but ten is left
    alone: "0.79²" is read as 0.79.
    """
    found = []
    for match in _NUMBER.finditer(text):
        mantissa = match["mantissa"].replace(",", "")
        power = match["power"] or match["exponent"]
        if match["raised"]:
            power = match["raised"].translate(_SUPERSCRIPT)
        bare = match["bare"] or (match["bare_raised"] or "").translate(_SUPERSCRIPT)
        end = match.end()
        if bare and mantissa == "10" and not match["sign"]:
            value, digits = Decimal(1).scaleb(int(bare.replace("−", "-"))), 1
        else:
            if bare:  # a power on something other than ten: the number ends before it
                end = match.end("mantissa")
            value = Decimal(mantissa)
            if power:
                value = value.scaleb(int(power.replace("−", "-")))
            if match["sign"]:
                value = -value
            digits = len(mantissa.replace(".", "").lstrip("0")) or 1
        found.append(Number(value, digits, text[match.start() : end]))
    return found


def _digits_of(value: float) -> int:
    """Significant digits of a number of an answer key, as it is written in the file.

    A whole number counts every digit it is written with, so 100 has three.
    """
    if isinstance(value, int):
        return len(str(abs(value)))
    return len(Decimal(repr(value)).normalize().as_tuple().digits)


def _rounded(value: Decimal, digits: int) -> Decimal:
    if value == 0:
        return value
    return value.quantize(Decimal(1).scaleb(value.adjusted() - digits + 1), rounding=ROUND_HALF_UP)


def agrees(written: Number, value: float, least_digits: int | None = None) -> bool:
    """Whether a number in an answer is the number of the key.

    Written with as many digits as the key or more, it has to be equal: 0.7910 is
    0.791, and 0.24 is not 0.2. Written with fewer, it has to be the key rounded to
    those digits, and no fewer than `least_digits`: 0.79 is 0.791 when two digits are
    allowed. Without `least_digits` an answer has to be as exact as the key.
    """
    key = Decimal(repr(value))
    key_digits = _digits_of(value)
    least = key_digits if least_digits is None else least_digits
    if written.digits < least:
        return False
    if written.digits >= key_digits:
        return written.value == key
    return written.value == _rounded(key, written.digits)


@dataclass(frozen=True)
class AnswerGrade:
    rule: str  # RIGHT, WRONG or BY_HAND
    why: tuple[str, ...]  # what made it wrong, or what a person has to look at
    found: bool | None  # what the answer said; None without an answer
    numbers: tuple[tuple[str, str | None], ...]  # label, and the number that agreed as written
    phrases: tuple[tuple[str, bool], ...]  # label, and whether one of its wordings is there
    wrong_numbers: tuple[tuple[str, str], ...]  # label and number: listed wrong values that occur
    by_hand: tuple[str, ...]  # what the question leaves to a person


def grade_answer(record: Record, question: Question) -> AnswerGrade:
    """What a rule can say of the answer.

    A listed wrong number that occurs does not make an answer wrong. An answer may name
    it to say what it is not ("72.1 is not a significance"), and a rule cannot tell.
    It sends the answer to a person.
    """
    key = question.answer_key
    by_hand = tuple(key.get("by_hand", ()))
    answer = record.end.get("answer")
    if not answer:
        reason = f"no answer ({record.end['reason']})"
        return AnswerGrade(WRONG, (reason,), None, (), (), (), by_hand)

    text = answer["answer"]
    written = numbers_in(text)
    numbers = []
    for item in key.get("numbers", ()):
        match = next(
            (n for n in written if agrees(n, item["value"], item.get("min_sig_figs"))), None
        )
        numbers.append((item["label"], match.text if match else None))
    phrases = [
        (item["label"], any(wording.casefold() in text.casefold() for wording in item["any_of"]))
        for item in key.get("phrases", ())
    ]
    wrong = [
        (item["label"], n.text)
        for item in key.get("wrong_numbers", ())
        for n in written
        if agrees(n, item["value"])
    ]

    missing = []
    if answer["found"] != question.expect_found:
        missing.append(f"found is {answer['found']}, expected {question.expect_found}")
    missing += [f"number missing: {label}" for label, match in numbers if match is None]
    missing += [f"phrase missing: {label}" for label, there in phrases if not there]
    look = [f"a listed wrong number occurs: {label} ({text})" for label, text in wrong]
    look += [f"by hand: {item}" for item in by_hand]
    rule, why = (WRONG, missing) if missing else (BY_HAND, look) if look else (RIGHT, [])
    return AnswerGrade(
        rule, tuple(why), answer["found"], tuple(numbers), tuple(phrases), tuple(wrong), by_hand
    )


# --- one run -----------------------------------------------------------------------------


@dataclass(frozen=True)
class Grade:
    run_id: str
    question_id: str
    toolset: str | None
    repeat: int | None
    reason: str  # why the run ended
    turns: int
    search: SearchGrade
    access: AccessGrade
    citation: CitationGrade | None
    answer: AnswerGrade
    problems: tuple[str, ...]  # what makes a part of this grade doubtful

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def grade(record: Record, question: Question, papers: Mapping[str, Paper]) -> Grade:
    """Grade one finished run. `papers` holds the parsed papers of the question, by identifier."""
    run = record.run
    if run.get("question_id") != question.id:
        raise ValueError(f"the record is of {run.get('question_id')!r}, not of {question.id!r}")
    access, problems = grade_access(record, question, papers)
    now = {papers[key].parser_version for key in question.gold_papers if key in papers}
    then = set(record.end.get("parser_versions") or [])
    if then and now and then != now:
        problems.append(
            f"the run read papers split by parser {sorted(then)}, and is graded against "
            f"parser {sorted(now)}: places may have moved"
        )
    return Grade(
        run_id=run["run_id"],
        question_id=question.id,
        toolset=run.get("toolset"),
        repeat=run.get("repeat"),
        reason=record.end["reason"],
        turns=record.end["turns"],
        search=grade_search(record, question),
        access=access,
        citation=grade_citation(record, question),
        answer=grade_answer(record, question),
        problems=tuple(problems),
    )


# --- the command -------------------------------------------------------------------------


def line_of(result: Grade) -> str:
    """One run on one line, for a person who looks down a column."""
    hits = [hit for hit in result.search.first_hit.values() if hit]
    search = f"{result.search.searches} ({result.search.empty} empty)"
    search += "".join(f", hit at turn {turn} rank {rank}" for turn, rank, _ in hits)
    access = {True: f"turn {result.access.turn}", False: "no", None: "?"}[result.access.met]
    if result.access.turns_after is not None:
        access += f" (+{result.access.turns_after})"
    cited = "-"
    if result.citation is not None:
        cited = "strict" if result.citation.strict else "loose" if result.citation.loose else "no"
        cited += f" (+{result.citation.extra})" if result.citation.extra else ""
    return (
        f"{result.run_id} | {result.reason} | {result.turns} turns | search {search} "
        f"| access {access} | cited {cited} | answer {result.answer.rule}"
    )


def main(argv: Sequence[str] | None = None, source: PaperSource | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m hepph_paper_miner.eval.grade",
        description="Grade finished runs from their public records.",
    )
    parser.add_argument("records", nargs="+", help="public records, or a pattern in quotes")
    parser.add_argument(
        "--questions",
        type=Path,
        default=Path("eval_data/questions_dev.jsonl"),
        help="the question file (default: %(default)s)",
    )
    parser.add_argument("--out", type=Path, help="write every grade here, one JSON object a line")
    arguments = parser.parse_args(argv)

    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="backslashreplace")
    try:
        questions = {item.id: item for item in load_questions(arguments.questions)}
    except (OSError, QuestionFileError) as error:
        print(f"cannot read the questions: {error}", file=sys.stderr)
        return 2
    # The shell of Windows hands a pattern over as it was typed, so it is opened here.
    paths = sorted({Path(found) for name in arguments.records for found in glob.glob(name)})
    if not paths:
        print(f"no record matches: {' '.join(arguments.records)}", file=sys.stderr)
        return 2
    if source is None:
        source = _arxiv()

    papers: dict[str, Paper] = {}
    unreadable: dict[str, str] = {}
    grades = []
    for path in paths:
        try:
            record = read_record(path)
        except (RecordError, ValueError) as error:
            print(f"skipped: {error}", file=sys.stderr)
            continue
        question = questions.get(record.run.get("question_id"))
        if question is None:
            print(f"skipped: {path.name}: its question is not in the file", file=sys.stderr)
            continue
        for key in question.gold_papers:
            if key not in papers and key not in unreadable:
                try:
                    papers[key] = source.paper(parse_arxiv_id(key))
                except SourceError as error:
                    unreadable[key] = str(error)
                    print(f"cannot read {key}: {error}", file=sys.stderr)
        result = grade(record, question, papers)
        grades.append(result)
        print(line_of(result))
        for problem in result.problems:
            print(f"   ! {problem}")
    if arguments.out:
        lines = [json.dumps(result.as_dict(), ensure_ascii=False) for result in grades]
        arguments.out.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
        print(f"{len(grades)} grade(s) written to {arguments.out}")
    return 0


def _arxiv() -> PaperSource:
    """The papers as a run read them: from arXiv, through the folder of downloads."""
    from hepph_paper_miner import __version__
    from hepph_paper_miner.http import Fetcher, default_cache_dir
    from hepph_paper_miner.server import SERVER_NAME
    from hepph_paper_miner.sources.arxiv import ArxivSource

    return ArxivSource(Fetcher(default_cache_dir(), user_agent=f"{SERVER_NAME}/{__version__}"))


if __name__ == "__main__":
    sys.exit(main())
