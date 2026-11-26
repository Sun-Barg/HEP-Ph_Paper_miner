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
                     the title of a section (the outline shows the titles)
    question_clean   the question holds the mark of its paper once, and no identifier, no
                     value of the key, no title of its section, no number of a section,
                     an equation, a figure or a table, and not the word "appendix"
    lengths          the question and the reference answer have at most 400 characters
                     each, the anchor 20 to 120
    running_text     the anchor does not stand in a table, a figure, a display equation,
                     a caption or a footnote

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
eval/check.py reads them, and held to the key with its significant digits. A phrase is
written when one of its wordings stands in the text, regardless of capitals, after the
TeX is made plain (spacing and the signs of math mode become spaces, braces go, a control
word loses its backslash) and white space is taken out of both: "\\textit{Fermi}-LAT"
then holds "Fermi-LAT", and a name that runs over a line break is found.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from hepph_paper_miner.drafting.assign import Placed
from hepph_paper_miner.drafting.draft import PAPER_MARK, Draft, line_of, section_of
from hepph_paper_miner.eval.check import _CONTROL_WORD_BEFORE_DIGIT, _TEX_SPACING
from hepph_paper_miner.eval.grade import Number, agrees, numbers_in
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
)

QUESTION_CHARS = 400
ANSWER_CHARS = 400
ANCHOR_CHARS = (20, 120)


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


def numbers_written(tex: str) -> list[Number]:
    """The numbers of a text of TeX, as eval/check.py reads the numbers of an anchor."""
    text = _TEX_SPACING.sub(" ", tex)
    return numbers_in(_CONTROL_WORD_BEFORE_DIGIT.sub(r"\1 ", text))


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
        elsewhere = [at for piece in pieces for at in written_in(draft, piece)]
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

    ordered = sorted(failed, key=lambda pair: CHECKS.index(pair[0]))
    return Checked(tuple(name for name, _ in ordered), tuple(why for _, why in ordered), anchor, at)


def counted(checks: Sequence[Checked]) -> dict[str, int]:
    """How many drafts failed each check: one draft counts under every check it failed."""
    return {name: sum(1 for one in checks if name in one.failed) for name in CHECKS}
