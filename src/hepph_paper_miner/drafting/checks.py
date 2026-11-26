"""The checks a program makes of a draft before any model sees it again.

A draft that fails one of them is dropped, and the report counts the drops by check. All
of them are made, so that one draft can be counted under every check it fails:

    line             it reads as a line of a question file (eval/questions.py)
    anchor_once      its anchor stands once in the whole text of its section, subsections
                     included, and that one place lies in the part that was given out
    key_kinds        its key holds a number or a phrase
    key_in_anchor    every number of the key, and a wording of every phrase, is written in
                     the anchor: so a run that was given the passage was given the value
    not_in_listing   no value of the key is written in the abstract or in the title
    not_elsewhere    no value of the key is written in the paper outside the part, nor in
                     the title of a section (the outline shows the titles); there a number
                     of the key that has a unit counts only with that unit after it
    question_clean   the question holds the mark of its paper once, and no identifier, no
                     value of the key, no title of its section, no number of a section,
                     an equation, a figure or a table, and not the word "appendix"
    lengths          the question and the reference answer have at most 400 characters
                     each, the anchor 20 to 120
    running_text     the anchor does not stand in a table, a figure, a display equation,
                     a caption or a footnote
    two_digits       every number of the key that the anchor writes is written there with
                     two or more significant digits, or with a power of ten

The check that a question expects an answer is no check here: the form of a draft has no
field for a question without one.

Why the whole section, for the anchor: the grader counts a passage as given when one of
the places of its anchor in the section of the evidence was given (eval/grade.py). An
anchor that stood a second time outside the part would be given by a call that never
reached the part: a later piece read as given by the first call. Why the whole paper,
for the values: a value that the first piece of the section also writes makes no
question of a later piece, and one that a subsection also writes makes none of the text
of a section in front of its subsections.

"Written" is read the way the grader reads an answer. Numbers are read off the TeX as
eval/check.py reads them, save that "--" is the dash of a range and no minus ("30--37.2"
holds 37.2), and held to the key with its significant digits. A phrase is
written when one of its wordings stands in the text, regardless of capitals, after the
TeX is made plain (spacing and the signs of math mode become spaces, braces go, a control
word loses its backslash) and white space is taken out of both: "\\textit{Fermi}-LAT"
then holds "Fermi-LAT", and a name that runs over a line break is found.

Outside the part (not_elsewhere), a number of the key that has a unit is written only
where the same number stands with the same unit right after it: "20~kpc" and
"20\\,{\\rm kpc}" are 20 kpc, "20^\\circ", "20 cm" and "20 pc" are not. Between the number
and its unit may stand spacing, braces, font commands, a range ("6.4-9.1 GeV", "40 to 60
GeV") or an uncertainty ("40 \\pm 5 GeV", "40^{+5}_{-3} GeV", "(40 \\pm 5) GeV"). Units are
held to each other by their first word, without capitals; a Greek letter by its name
("\\sigma" is σ), and degrees and per cent in their usual spellings. A number of the key
without a unit, and a phrase, are written wherever they stand, as everywhere else.

Why the unit there: in the first round of the tuning five of the eight drafts that this
check dropped had a value that stood elsewhere for another quantity (a 20 of "20 cm"
for a radius of 20 kpc, a 5 of "{5mm}" for a mass of 5 keV), and three had their fact
stated again. Read with the unit, the three are still dropped, and three of the five
pass (the other two: a 10% that stands elsewhere for other quantities, and a number
without a unit). What it misses: the same value stated again without its unit right
after it, as in a table whose unit stands in its head, or written with another spelling
of the unit. Such a question shows up in the runs as an answer that is right without the
anchor, which the report counts.

Why two digits (two_digits): the prompt has asked for a number of two or more digits since
d1, and in the second round of the tuning the owner turned down a draft whose key was a
radius of 5 pc, which nothing had checked. The grader reads the numbers of an answer and
not their units, so a key of one digit is met by any number that rounds to it, and a paper
writes such numbers in many places. A power of ten ("10^{15}", "2\\times 10^{-26}") is
held by its exponent as well, so it is no such number, though the grader counts one digit
in a bare "10^{15}". The digits are those the anchor writes, which is what a run is given:
"1.0" has two. A number of the key that the anchor does not write is left to
key_in_anchor, so that one fault of a draft is counted once.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from hepph_paper_miner.drafting.assign import Placed
from hepph_paper_miner.drafting.draft import PAPER_MARK, Draft, line_of, section_of
from hepph_paper_miner.eval.check import _CONTROL_WORD_BEFORE_DIGIT, _TEX_SPACING
from hepph_paper_miner.eval.grade import _NUMBER, Number, agrees, numbers_in
from hepph_paper_miner.eval.questions import QuestionFileError, _question
from hepph_paper_miner.sources.base import Paper, Section

CHECKS = (
    "line",
    "anchor_once",
    "key_kinds",
    "key_in_anchor",
    "not_in_listing",
    "not_elsewhere",
    "question_clean",
    "lengths",
    "running_text",
    "two_digits",
)

QUESTION_CHARS = 400
ANSWER_CHARS = 400
ANCHOR_CHARS = (20, 120)
LEAST_DIGITS = 2  # the significant digits that a number of the key is written with, at least


@dataclass(frozen=True)
class Checked:
    failed: tuple[str, ...]  # the checks it failed, in the order of CHECKS
    why: tuple[str, ...]  # a short line for every failure, in the same order
    anchor: str | None  # the anchor as the paper writes it, when it was found
    at: int | None  # where that anchor stands in the text of its section

    @property
    def passed(self) -> bool:
        return not self.failed


# --- reading values off TeX ----------------------------------------------------------------

_BRACES = re.compile(r"[{}]")
_CONTROL_WORD = re.compile(r"\\([A-Za-z]+)")
# The dash of a range in TeX ("6.4--9.1~GeV"), and the long dash of a sentence.
_TEX_DASH = re.compile(r"-{2,3}")


def _number_text(tex: str) -> str:
    """A text of TeX as its numbers are read: as eval/check.py makes it of an anchor, save
    that "--" and "---" become a dash that is no minus. Read as they stand, "30--37.2"
    would hold -37.2, since a minus sign is a minus where no number stands right before it."""
    text = _TEX_DASH.sub(" – ", _TEX_SPACING.sub(" ", tex))
    return _CONTROL_WORD_BEFORE_DIGIT.sub(r"\1 ", text)


def numbers_written(tex: str) -> list[Number]:
    """The numbers of a text of TeX, as eval/check.py reads the numbers of an anchor."""
    return numbers_in(_number_text(tex))


def _plain(text: str) -> str:
    text = _BRACES.sub(" ", _TEX_SPACING.sub(" ", text))
    return _CONTROL_WORD.sub(r"\1", text)


def squeezed(text: str) -> str:
    """A text made plain, without white space and without capitals: what phrases are held to."""
    return "".join(_plain(text).split()).casefold()


def number_written(item: dict, numbers: Iterable[Number]) -> bool:
    return any(agrees(number, item["value"], item.get("min_sig_figs")) for number in numbers)


def phrase_written(item: dict, text: str) -> bool:
    """Whether one wording of a phrase stands in a squeezed text."""
    wordings = (squeezed(wording) for wording in item["any_of"])
    return any(wording and wording in text for wording in wordings)


def written_in(draft: Draft, tex: str) -> list[int]:
    """Which values of the key a text of TeX writes: their places among numbers, then phrases."""
    numbers, text = numbers_written(tex), squeezed(tex)
    found = [at for at, item in enumerate(draft.numbers) if number_written(item, numbers)]
    first = len(draft.numbers)
    return found + [
        first + at for at, item in enumerate(draft.phrases) if phrase_written(item, text)
    ]


# --- a number with its unit, outside the part ----------------------------------------------

_DIGITS = r"[-−+]?\d+(?:\.\d+)?(?:\s*(?:×|\\times)\s*10\s*\^\s*\{?\s*[-−+]?\d+\s*\}?)?"
_UP = r"\^\s*\{\s*\+\s*\d+(?:\.\d+)?\s*\}"
_DOWN = r"_\s*\{\s*[-−]\s*\d+(?:\.\d+)?\s*\}"
# What may stand between a number and its unit, once or twice: the other end of a range,
# an uncertainty, or an uncertainty in the last digits ("1.2345(6) GeV").
_BETWEEN = re.compile(
    rf"\s*(?:-{{1,3}}|–|—|to|and|\\pm|±|\+/-)\s*{_DIGITS}"
    rf"|\s*{_UP}\s*{_DOWN}|\s*{_DOWN}\s*{_UP}"
    r"|\(\d+\)"
)
# Spacing, braces and brackets, and font commands, which say nothing of the unit.
_LEAD = re.compile(r"[\s{}()\[\]^_]+")
_FONT = re.compile(
    r"\\(?:rm|mathrm|textrm|text|mbox|hbox|it|mathit|textit|bf|mathbf|textbf|sf|mathsf|textsf"
    r"|mathnormal|operatorname|ensuremath|unit|units)(?![A-Za-z])"
)
# The sign of degrees, which is no letter. "^\circ" and "\degree" need nothing: the "^" is
# skipped as spacing is, and their control words are spellings of "deg" (_SAME).
_DEGREES = re.compile(r"°")
_WORD = re.compile(r"\\?%|\\([A-Za-z]+)|([^\W\d_]+)")
# Spellings of one unit that are held to be the same.
_SAME = {
    "degree": "deg",
    "degrees": "deg",
    "circ": "deg",
    "textdegree": "deg",
    "percent": "%",
    "µ": "mu",
}


def _word(text: str) -> str:
    """A word as units are held to each other: without capitals, a Greek letter by its name."""
    first = text[0]
    if first in _SAME:
        text = _SAME[first]
    elif "GREEK" in unicodedata.name(first, ""):
        text = unicodedata.name(first).split()[-1]  # GREEK SMALL LETTER SIGMA: sigma
    text = text.casefold()
    return _SAME.get(text, text)


def first_word(text: str, at: int = 0) -> str:
    """The first word of a unit that stands at `at`, past spacing, braces and font commands,
    as units are held to each other; "" when no word stands there."""
    while at < len(text):
        skipped = _LEAD.match(text, at) or _FONT.match(text, at)
        if skipped is None or skipped.end() == at:
            break
        at = skipped.end()
    found = _WORD.match(text, at)
    if found is None:
        return ""
    if found.group(0) in ("%", "\\%"):
        return "%"
    return _word(found.group(1) or found.group(2))


def unit_of(item: dict) -> str:
    """The first word of the unit of a number of the key, or "" when it has none."""
    unit = _DEGREES.sub(" deg ", _TEX_SPACING.sub(" ", str(item.get("unit") or "")))
    return first_word(unit)


def unit_after(text: str, end: int) -> str:
    """The first word of the unit after a number that ends at `end`, or "" when none follows.

    `text` is TeX, or the text that numbers_with_ends read the number off: TeX spacing is
    made a space either way.
    """
    rest = _DEGREES.sub(" deg ", _TEX_SPACING.sub(" ", text[end : end + 160]))
    for _ in range(2):
        between = _BETWEEN.match(rest)
        if between is None:
            break
        rest = rest[between.end() :]
    return first_word(rest)


def numbers_with_ends(tex: str) -> tuple[str, list[tuple[Number, int]]]:
    """The numbers of a text of TeX as numbers_written reads them, each with where it ends in
    the text they were read off, which comes with them."""
    text = _number_text(tex)
    found = []
    for match in _NUMBER.finditer(text):
        # Read on its own, a match is the number that numbers_in reads of it in the text:
        # what stands before it is no part of it.
        read = numbers_in(text[match.start() : match.end()])
        if read:
            found.append((read[0], match.start() + len(read[0].text)))
    return text, found


def number_elsewhere(item: dict, tex: str) -> bool:
    """Whether a text outside the part writes a number of the key: with the key's unit right
    after it when the key has one, anywhere when it has none."""
    unit = unit_of(item)
    text, numbers = numbers_with_ends(tex)
    return any(
        agrees(number, item["value"], item.get("min_sig_figs"))
        and (not unit or unit_after(text, end) == unit)
        for number, end in numbers
    )


def written_elsewhere(draft: Draft, tex: str) -> list[int]:
    """Which values of the key a text outside the part writes, as not_elsewhere reads it:
    numbers with their units, phrases as written_in reads them."""
    text = squeezed(tex)
    found = [at for at, item in enumerate(draft.numbers) if number_elsewhere(item, tex)]
    first = len(draft.numbers)
    return found + [
        first + at for at, item in enumerate(draft.phrases) if phrase_written(item, text)
    ]


# --- the digits of a number of the key ------------------------------------------------------

# The parts of eval/grade.py's pattern of a number that hold a power of ten.
_POWERS = ("power", "raised", "exponent", "bare", "bare_raised")


def with_power(number: Number) -> bool:
    """Whether a number is written with a power of ten, as the grader reads its text:
    "10^{15}", "2.5 \\times 10^{-26}", "2.26e-26"."""
    found = _NUMBER.match(number.text)
    return found is not None and any(found[name] for name in _POWERS)


def short_numbers(draft: Draft, tex: str) -> list[int]:
    """Which numbers of the key a text of TeX writes only with fewer than LEAST_DIGITS
    significant digits and without a power of ten. A number that the text does not write at
    all is not among them."""
    numbers = numbers_written(tex)
    short = []
    for at, item in enumerate(draft.numbers):
        written = [n for n in numbers if agrees(n, item["value"], item.get("min_sig_figs"))]
        if written and not any(n.digits >= LEAST_DIGITS or with_power(n) for n in written):
            short.append(at)
    return short


def labels(draft: Draft, places: Iterable[int]) -> str:
    items = [*draft.numbers, *draft.phrases]
    return ", ".join(repr(items[at]["label"]) for at in sorted(set(places)))


# --- where the anchor stands ---------------------------------------------------------------


def _count(text: str, piece: str) -> list[int]:
    """Every place of a piece in a text, counted the way the grader counts: "aa" twice in "aaa"."""
    found, at = [], text.find(piece)
    while at != -1:
        found.append(at)
        at = text.find(piece, at + 1)
    return found


def as_written(anchor: str, text: str, start: int, end: int) -> str | None:
    """The anchor as the text writes it: the same, or the same but for white space.

    An anchor that differs from the text in white space alone (a line break where the
    model wrote a space) is taken in the text's characters, and the one in the part is
    preferred. None when the text has no such piece.
    """
    anchor = anchor.strip()
    if not anchor:
        return None
    if anchor in text:
        return anchor
    pattern = r"\s+".join(re.escape(word) for word in anchor.split())
    found = list(re.finditer(pattern, text))
    if not found:
        return None
    inside = [match for match in found if start <= match.start() and match.end() <= end]
    return (inside or found)[0].group(0)


def top_of(paper: Paper, section_id: str) -> tuple[Section, int] | None:
    """The top-level section a section stands in, and where it begins in that section's text.

    Found as eval/grade.py's Places finds it, so that the scale is the grader's.
    """
    top = None
    for section in paper.sections:
        if section.level == 1:
            top = section
        if section.section_id != section_id:
            continue
        if section.level == 1:
            return section, 0
        if top is None:
            return None
        at = top.text.find(section.text, section.heading_at or 0)
        return (top, at) if at != -1 else None
    return None


def outside(paper: Paper, place: Placed) -> list[str] | None:
    """The text of a paper outside the part of a place, in pieces that are never joined.

    Not joined, so that no value is read across the cut. The titles of the sections are
    pieces too, the part's own among them: get_outline shows every title, so a value in
    one is given without the part. None when the part cannot be put on the scale of its
    top-level section.
    """
    found = top_of(paper, place.section)
    if found is None:
        return None
    top, offset = found
    start, end = offset + place.start, offset + place.end
    pieces = [top.text[:start], top.text[end:]]
    pieces += [s.text for s in paper.sections if s.level == 1 and s.section_id != top.section_id]
    pieces += [section.title for section in paper.sections]
    return [piece for piece in pieces if piece]


# --- where text stands that is no running text ---------------------------------------------

# Environments whose text is no sentence of the running text: tables, figures and display
# equations, each also in its starred form.
_NOT_RUNNING = (
    "table",
    "tabular",
    "tabularx",
    "longtable",
    "figure",
    "equation",
    "align",
    "alignat",
    "flalign",
    "eqnarray",
    "gather",
    "multline",
    "displaymath",
)
_ENVIRONMENT = re.compile(r"\\(begin|end)\s*\{(" + "|".join(_NOT_RUNNING) + r")\*?\}")
_DISPLAY_OPEN = re.compile(r"(?<!\\)\\\[")
_DISPLAY_CLOSE = re.compile(r"(?<!\\)\\\]")
_DOUBLE_DOLLAR = re.compile(r"(?<!\\)\$\$")
_ARGUMENT = re.compile(r"\\(caption|footnote|footnotetext)\*?\s*(\[[^\]]*\])?\s*\{")
# \captionof{figure}{...} puts a caption outside a float: its text is the second argument.
_CAPTION_OF = re.compile(r"\\captionof\*?\s*\{[^{}]*\}\s*(\[[^\]]*\])?\s*\{")


def _closing_brace(text: str, opening: int) -> int:
    """Where the brace that closes the one at `opening` stands, or the end of the text."""
    depth = 0
    at = opening
    while at < len(text):
        char = text[at]
        if char == "\\":
            at += 2  # an escaped brace is no brace
            continue
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return at
        at += 1
    return len(text)


def not_running(text: str) -> list[tuple[int, int]]:
    """The stretches of a text of TeX that are no running text."""
    spans: list[tuple[int, int]] = []
    opened: list[tuple[str, int]] = []
    for match in _ENVIRONMENT.finditer(text):
        kind, name = match.groups()
        if kind == "begin":
            opened.append((name, match.start()))
        elif opened and opened[-1][0] == name:
            _, begun = opened.pop()
            if not opened:  # an inner environment lies inside the outer one
                spans.append((begun, match.end()))
    spans += [(begun, len(text)) for _, begun in opened[:1]]  # never closed: to the end
    at = 0
    while (begun := _DISPLAY_OPEN.search(text, at)) is not None:
        closed = _DISPLAY_CLOSE.search(text, begun.end())
        stop = closed.end() if closed else len(text)
        spans.append((begun.start(), stop))
        at = stop
    marks = [match.start() for match in _DOUBLE_DOLLAR.finditer(text)]
    spans += [(marks[i], marks[i + 1] + 2) for i in range(0, len(marks) - 1, 2)]
    for form in (_ARGUMENT, _CAPTION_OF):
        for match in form.finditer(text):
            spans.append((match.start(), _closing_brace(text, match.end() - 1) + 1))
    return sorted(spans)


# --- the question --------------------------------------------------------------------------

_IDENTIFIER = re.compile(r"\b\d{4}\.\d{4,5}(?:v\d+)?\b|\b[a-z]+(?:-[a-z]+)?/\d{7}\b")
# "Section 3", "Sec. II", "Secs. 2", "§2", "Appendix B", "Eq. (5)", "Eqs. 3", "Fig. 2",
# "Figure 4", "Table 1", "Tab. 3": a part of the paper named by its number.
_NUMBERED = re.compile(
    r"§\s*\d|\b(?:sections?|secs?\.?|equations?|eqs?\.?|figures?|figs?\.?|tables?|tabs?\.)"
    r"\s*\(?\s*(?:\d|[IVX]+\b|[A-Z]\b)",
    re.IGNORECASE,
)
_APPENDIX = re.compile(r"\bappendi(?:x|ces)\b", re.IGNORECASE)


def _words(text: str) -> list[str]:
    return re.findall(r"[^\W_]+", _plain(text))


def question_problems(draft: Draft, paper: Paper, place: Placed) -> list[str]:
    """What is wrong with the question of a draft, one short line each."""
    question = draft.question
    found = []
    if question.count(PAPER_MARK) != 1:
        found.append(f"the mark {PAPER_MARK} stands {question.count(PAPER_MARK)} times")
    bare = question.replace(PAPER_MARK, " ")
    if _IDENTIFIER.search(bare):
        found.append("it holds an arXiv identifier")
    written = written_in(draft, bare)
    if written:
        found.append(f"it writes the value of {labels(draft, written)}")
    titles = []
    section = section_of(paper, place.section)
    if section is not None:
        titles.append(section.title)
        if section.level == 2:
            top = top_of(paper, place.section)
            if top is not None:
                titles.append(top[0].title)
    for title in titles:
        if len(_words(title)) >= 2 and squeezed(title) in squeezed(bare):
            found.append("it names the title of its section")
            break
    if _NUMBERED.search(bare):
        found.append("it names a section, an equation, a figure or a table by its number")
    if _APPENDIX.search(bare):
        found.append('it holds the word "appendix"')
    return found


# --- all of them ---------------------------------------------------------------------------


def check(draft: Draft, paper: Paper, place: Placed, kind: str) -> Checked:
    """Every check of a draft about a place, as a question of `kind`."""
    failed: list[tuple[str, str]] = []
    section = section_of(paper, place.section)
    text = section.text if section is not None else ""
    anchor = as_written(draft.anchor, text, place.start, place.end)
    at: int | None = None

    try:
        line = line_of(draft, place, kind, paper.meta.title, anchor or draft.anchor, "draft")
        _question(line, "the draft")
    except QuestionFileError as error:
        failed.append(("line", str(error).removeprefix("the draft: ")))

    if anchor is None:
        failed.append(("anchor_once", "the anchor does not stand in its section"))
    else:
        places = _count(text, anchor)
        if len(places) != 1:
            failed.append(("anchor_once", f"the anchor stands {len(places)} times in its section"))
        else:
            at = places[0]
            if not (place.start <= at and at + len(anchor) <= place.end):
                failed.append(("anchor_once", "the anchor stands outside the part"))

    if not draft.numbers and not draft.phrases:
        failed.append(("key_kinds", "the key holds no number and no phrase"))

    # Held to the anchor as the paper writes it, or as the draft wrote it when the paper
    # has no such piece: then this says whether the draft agrees with itself.
    in_anchor = set(written_in(draft, anchor if anchor is not None else draft.anchor))
    missing = [at for at in range(len(draft.numbers) + len(draft.phrases)) if at not in in_anchor]
    if missing:
        failed.append(("key_in_anchor", f"the anchor does not write {labels(draft, missing)}"))

    listed = written_in(draft, paper.meta.title) + written_in(draft, paper.meta.abstract)
    if listed:
        failed.append(
            ("not_in_listing", f"the title or the abstract writes {labels(draft, listed)}")
        )

    pieces = outside(paper, place)
    if pieces is None:
        failed.append(("not_elsewhere", "the part cannot be placed in its section"))
    else:
        elsewhere = [at for piece in pieces for at in written_elsewhere(draft, piece)]
        if elsewhere:
            failed.append(("not_elsewhere", f"outside the part: {labels(draft, elsewhere)}"))

    problems = question_problems(draft, paper, place)
    if problems:
        failed.append(("question_clean", "; ".join(problems)))

    lengths = []
    if len(draft.question) > QUESTION_CHARS:
        lengths.append(f"the question has {len(draft.question)} characters")
    if len(draft.reference_answer) > ANSWER_CHARS:
        lengths.append(f"the reference answer has {len(draft.reference_answer)} characters")
    size = len(anchor if anchor is not None else draft.anchor.strip())
    if not ANCHOR_CHARS[0] <= size <= ANCHOR_CHARS[1]:
        lengths.append(f"the anchor has {size} characters")
    if lengths:
        failed.append(("lengths", "; ".join(lengths)))

    if at is not None and anchor is not None:
        stop = at + len(anchor)
        if any(begun < stop and at < end for begun, end in not_running(text)):
            failed.append(
                (
                    "running_text",
                    "the anchor stands in a table, a figure, a display "
                    "equation, a caption or a footnote",
                )
            )

    # Held to the same text as key_in_anchor.
    short = short_numbers(draft, anchor if anchor is not None else draft.anchor)
    if short:
        failed.append(
            (
                "two_digits",
                f"the anchor writes {labels(draft, short)} with fewer than {LEAST_DIGITS} "
                "significant digits and no power of ten",
            )
        )

    ordered = sorted(failed, key=lambda pair: CHECKS.index(pair[0]))
    return Checked(tuple(name for name, _ in ordered), tuple(why for _, why in ordered), anchor, at)


def counted(checks: Sequence[Checked]) -> dict[str, int]:
    """How many drafts failed each check: one draft counts under every check it failed."""
    return {name: sum(1 for one in checks if name in one.failed) for name in CHECKS}
