"""Where in a split paper a question can stand, and of which kind.

A question of the second evaluation is bound to a passage, and its kind says where that
passage stands among the pieces that the tools hand out. The kinds are about the ways
in which a reader of the staged tools can miss a passage, not about what a paper is
about, so a program can tell them without knowing the field:

    named_first   in a subsection, or in a section without subsections, within what the
                  first read_section call of it returns; not in an appendix
    own_text      in the text that a section has in front of its first subsection, which
                  a reader who takes the subsections one by one never gets (eval-15 of
                  the first evaluation was missed there)
    appendix      in a section or a subsection of an appendix
    later_piece   behind what the first read_section call of a section or a subsection
                  returns (20,000 characters), so that only a second call brings it

search_first is no place of its own. It is a named_first place, asked about a paper that
the question names by its title, so that a search has to find the paper first.

A place is a part of the text that read_section returns of one section: the first piece
of a subsection or of a section without subsections, the text of a section in front of
its first subsection, or the second piece of either. The cuts are those of the tools
(server.piece_ends), so a place is what one call of read_section with its start gives.
Where a part could have two kinds, the rarer one is taken: a second piece is always
later_piece, and the own text of an appendix is appendix.

A part of fewer than 1,000 characters is no place. Text that short is a heading with a
sentence or two, a statement of data availability, or the commands of a short section
more often than text to ask about.

Left out: the acknowledgements, which say whom the authors thank and nothing of what the
paper finds, and the text that the parser found behind the list of references without a
heading, where the lists of authors of large collaborations stand, and supplemental
material too.

Which section belongs to an appendix is read from what the parser made of it: a lettered
identifier ("A", "B.1") or the text after \\appendix that has no heading. A starred
heading after \\appendix gets a "u" identifier like any starred heading, so such a
section counts as a section of the body.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from hepph_paper_miner.server import SECTION_CHAR_LIMIT, own_text, piece_ends
from hepph_paper_miner.sources.base import Paper, Section

NAMED_FIRST = "named_first"
SEARCH_FIRST = "search_first"
OWN_TEXT = "own_text"
APPENDIX = "appendix"
LATER_PIECE = "later_piece"

# The order in which a paper is given a kind (assign.py): the rarest first, so that the
# few papers that have such a place are not spent on a kind that most papers have.
KINDS = (LATER_PIECE, APPENDIX, OWN_TEXT, SEARCH_FIRST, NAMED_FIRST)

LEAST_CHARS = 1_000

# The titles that the parser gives text without a heading of its own (sources/arxiv_latex.py).
# Written out here, as survey/run.py does with its own; a test holds them to the parser's.
AFTER_REFERENCES = "(text after the list of references, without a section heading)"
AFTER_APPENDIX = "(text after \\appendix, without a section heading)"

# "Acknowledgments", "ACKNOWLEDGEMENTS", "Acknowledgment and funding": the word comes first.
_ACKNOWLEDGEMENTS = re.compile(r"\s*acknowledge?ments?\b", re.IGNORECASE)


@dataclass(frozen=True)
class Place:
    kind: str  # NAMED_FIRST, OWN_TEXT, APPENDIX or LATER_PIECE
    section: str  # the identifier that read_section is called with
    start: int  # where the part begins in the text of that section
    end: int  # where it ends

    @property
    def chars(self) -> int:
        return self.end - self.start


def left_out(section: Section) -> bool:
    """Whether no question is asked about the text of a section."""
    return section.title == AFTER_REFERENCES or bool(_ACKNOWLEDGEMENTS.match(section.title))


def in_appendix(section: Section) -> bool:
    """Whether a section of the first level stands in an appendix, as far as the parser tells."""
    return section.section_id[:1].isupper() or section.title == AFTER_APPENDIX


def places_of(
    paper: Paper, limit: int = SECTION_CHAR_LIMIT, least: int = LEAST_CHARS
) -> list[Place]:
    """Every place of a paper, in the order of its text."""
    own = own_text(paper)
    divided = {section.section_id.split(".")[0] for section in paper.sections if section.level == 2}
    places: list[Place] = []
    holder: Section | None = None
    for section in paper.sections:
        if section.level == 1:
            holder = section
        top = holder if holder is not None else section
        if left_out(top) or left_out(section):
            continue
        if section.level == 1 and section.section_id in divided:
            # Its subsections are places of their own. What stands in front of the
            # first of them is one more, when the parser can say where it ends.
            if section.section_id in own:
                kind = APPENDIX if in_appendix(top) else OWN_TEXT
                places += _parts(section, own[section.section_id], kind, limit, least)
            continue
        kind = APPENDIX if in_appendix(top) else NAMED_FIRST
        places += _parts(section, section.chars, kind, limit, least)
    return places


def _parts(section: Section, reach: int, kind: str, limit: int, least: int) -> list[Place]:
    """The first piece of a part of a section, and the second, as far as the part reaches.

    `reach` is where the part ends in the text of the section: at its end, or where the
    heading of its first subsection begins.
    """
    ends = piece_ends(section.text, limit)
    found: list[Place] = []
    first_end = min(ends[0], reach)
    if first_end >= least:
        found.append(Place(kind, section.section_id, 0, first_end))
    if reach > ends[0]:
        second_end = min(ends[1], reach)
        if second_end - ends[0] >= least:
            found.append(Place(LATER_PIECE, section.section_id, ends[0], second_end))
    return found
