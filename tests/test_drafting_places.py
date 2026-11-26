"""Where in a split paper a question can stand, and of which kind (drafting/places.py).

The texts are lines of 70 characters, so the cuts of the tools can be counted by hand:
a piece that may hold 20,000 characters ends after the last line break before that,
at 19,950 (285 lines).
"""

import pytest

from hepph_paper_miner import server
from hepph_paper_miner.drafting.places import (
    AFTER_APPENDIX,
    AFTER_REFERENCES,
    APPENDIX,
    LATER_PIECE,
    NAMED_FIRST,
    OWN_TEXT,
    Place,
    in_appendix,
    left_out,
    places_of,
)
from hepph_paper_miner.sources import arxiv_latex
from hepph_paper_miner.sources.base import Paper, PaperMeta, Section

ID = "2609.01234v1"
CUT = 19_950  # where the first piece of a text of these lines ends


def lines_of(count: int) -> str:
    """`count` characters in lines of 70, the last one with its line break."""
    line = " ".join(["a" * 9] * 7) + "\n"
    assert len(line) == 70
    return (line * (count // len(line) + 1))[:count]


def divided(section_id: str, title: str, own: int, *subsections: tuple[str, str, int]) -> list:
    """A section with text of its own in front of its subsections, as the parser makes one."""
    text, made, at = lines_of(own), [], []
    for sub_id, sub_title, size in subsections:
        at.append(len(text))
        sub_text = lines_of(size)
        text += sub_text
        made.append((sub_id, sub_title, sub_text))
    top = Section(section_id, title, 1, text)
    return [top] + [
        Section(sub_id, sub_title, 2, sub_text, heading_at=start)
        for (sub_id, sub_title, sub_text), start in zip(made, at)
    ]


def plain(section_id: str, title: str, size: int) -> Section:
    return Section(section_id, title, 1, lines_of(size))


def paper_of(sections) -> Paper:
    return Paper(
        PaperMeta(ID, "A paper", ("A",), 2026, "hep-ph", "Abstract."), tuple(sections), "5"
    )


def example() -> Paper:
    return paper_of(
        [
            plain("0", "(text before the first section)", 1_400),
            plain("1", "Introduction", 2_800),
            *divided("2", "Method", 2_520, ("2.1", "Setup", 4_900), ("2.2", "Scan", 29_960)),
            plain("3", "Short", 980),
            plain("4", "Just enough", 1_050),
            plain("5", "Long, but not two pieces", 20_510),
            plain("u1", "Acknowledgments", 2_100),
            plain("u2", AFTER_APPENDIX, 1_400),
            plain("A", "Details", 3_500),
            *divided("B", "More", 1_120, ("B.1", "Tables", 24_990)),
            plain("u3", AFTER_REFERENCES, 60_060),
        ]
    )


def test_every_kind_stands_where_the_tools_put_it():
    assert places_of(example()) == [
        Place(NAMED_FIRST, "0", 0, 1_400),
        Place(NAMED_FIRST, "1", 0, 2_800),
        Place(OWN_TEXT, "2", 0, 2_520),
        Place(NAMED_FIRST, "2.1", 0, 4_900),
        Place(NAMED_FIRST, "2.2", 0, CUT),
        Place(LATER_PIECE, "2.2", CUT, 29_960),
        # "3" has 980 characters, fewer than a place needs.
        Place(NAMED_FIRST, "4", 0, 1_050),
        # The second piece of "5" holds 560 characters, so "5" has one place.
        Place(NAMED_FIRST, "5", 0, CUT),
        # The acknowledgements ("u1") and the text behind the references ("u3") are left out.
        Place(APPENDIX, "u2", 0, 1_400),
        Place(APPENDIX, "A", 0, 3_500),
        Place(APPENDIX, "B", 0, 1_120),
        Place(APPENDIX, "B.1", 0, CUT),
        Place(LATER_PIECE, "B.1", CUT, 24_990),
    ]


def test_own_text_longer_than_a_piece_has_a_later_place_too():
    paper = paper_of(divided("7", "Long own text", 25_060, ("7.1", "Then", 1_400)))
    assert places_of(paper) == [
        Place(OWN_TEXT, "7", 0, CUT),
        Place(LATER_PIECE, "7", CUT, 25_060),
        Place(NAMED_FIRST, "7.1", 0, 1_400),
    ]


def test_a_place_needs_its_thousand_characters():
    for size, count in ((999, 0), (1_000, 1)):
        assert len(places_of(paper_of([plain("1", "Some", size)]))) == count
    # And a second piece needs as many.
    for size, later in ((CUT + 999, 0), (CUT + 1_000, 1)):
        kinds = [place.kind for place in places_of(paper_of([plain("1", "Long", size)]))]
        assert kinds.count(LATER_PIECE) == later


class OnePaper:
    """A source that knows one paper, for calling the tools themselves."""

    def __init__(self, paper: Paper):
        self._paper = paper

    def paper(self, arxiv_id):
        return self._paper


def test_a_place_is_what_one_read_section_call_gives():
    paper = example()
    source = OnePaper(paper)
    text = {section.section_id: section.text for section in paper.sections}
    for place in places_of(paper):
        given = server._section(source, ID, place.section, place.start, None)
        assert text[place.section][place.start : place.end] in given
    for place in (place for place in places_of(paper) if place.kind == LATER_PIECE):
        # A later piece begins where the first call tells the reader to go on from.
        first_call = server._section(source, ID, place.section, 0, None)
        assert f"[cut at character {place.start} of" in first_call


def test_the_own_text_ends_where_the_tools_say_it_does():
    paper = example()
    own = server.own_text(paper)
    assert own == {"2": 2_520, "B": 1_120}
    source = OnePaper(paper)
    for place in places_of(paper):
        if place.kind == OWN_TEXT:
            # read_section with end=N returns just that text, as the outline says.
            given = server._section(source, ID, place.section, 0, own[place.section])
            assert f"[stopped at character {place.end} of" in given


@pytest.mark.parametrize(
    "title",
    [
        "Acknowledgments",
        "ACKNOWLEDGEMENTS",
        "Acknowledgment",
        "Acknowledgements and funding",
        " acknowledgments",
    ],
)
def test_the_acknowledgements_are_left_out_with_what_they_hold(title):
    paper = paper_of(divided("u1", title, 1_400, ("u1.1", "Funding", 1_400)))
    assert places_of(paper) == []


def test_a_title_that_only_mentions_them_is_kept():
    for title in ("Data and acknowledgments", "Acknowledged limits"):
        assert not left_out(plain("6", title, 1_400))


def test_the_text_behind_the_references_is_left_out_with_its_subsections():
    paper = paper_of(divided("u4", AFTER_REFERENCES, 1_400, ("u4.1", "Supplement", 5_000)))
    assert places_of(paper) == []


def test_an_appendix_is_read_from_what_the_parser_made_of_it():
    assert in_appendix(plain("A", "Details", 10)) and in_appendix(plain("A27", "Late", 10))
    assert in_appendix(plain("u5", AFTER_APPENDIX, 10))
    # A starred heading after \appendix gets a "u" identifier like any starred heading.
    assert not in_appendix(plain("u6", "Supplementary figures", 10))
    assert not in_appendix(plain("0", "(text before the first section)", 10))


def test_the_titles_are_the_ones_the_parser_gives():
    assert AFTER_REFERENCES == arxiv_latex._AFTER_REFERENCES
    assert AFTER_APPENDIX == arxiv_latex._AFTER_APPENDIX
