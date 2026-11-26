"""What a program checks of a draft before a model sees it again (drafting/checks.py).

The paper is the invented one of drafting_paper.py: every value it holds stands in one
known place, so each check can be made to pass and to fail on purpose.
"""

import pytest
from conftest import OWN_PAPER
from drafting_paper import LONG_FIRST, draft, paper, placed

from hepph_paper_miner.drafting.checks import (
    CHECKS,
    as_written,
    check,
    counted,
    not_running,
    numbers_written,
    phrase_written,
    squeezed,
)
from hepph_paper_miner.drafting.draft import Draft
from hepph_paper_miner.drafting.places import (
    APPENDIX,
    LATER_PIECE,
    NAMED_FIRST,
    OWN_TEXT,
    SEARCH_FIRST,
    places_of,
)
from hepph_paper_miner.sources.base import PaperMeta
from hepph_paper_miner.sources.fixture import paper_from_latex


def checked(changes=None, section="2.1", kind=None, of=None):
    place = placed(section, kind, of=of)
    return check(Draft.from_dict(draft(**(changes or {}))), of or paper(), place, place.kind)


def failures(result) -> dict:
    return dict(zip(result.failed, result.why))


def test_a_good_draft_passes_every_check():
    result = checked()
    assert result.passed and result.failed == ()
    assert result.anchor == "The detector has an area of 37.2 square metres"
    section = next(s for s in paper().sections if s.section_id == "2.1")
    assert section.text[result.at : result.at + len(result.anchor)] == result.anchor


def test_the_checks_are_these_in_this_order():
    # Written out, not read from the module: the list is what the pre-registration names.
    assert CHECKS == (
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


# --- 1: a line of a question file -----------------------------------------------------------


@pytest.mark.parametrize(
    "changes",
    [
        {"reference_answer": " "},
        {"accept_note": ""},
        {"numbers": [{"label": "area", "value": 37.2, "unit": "", "min_sig_figs": 0}]},
        {"phrases": [{"label": "unit", "any_of": [" "]}]},
        {"numbers": [{"label": "", "value": 37.2, "unit": "", "min_sig_figs": 3}]},
    ],
)
def test_a_draft_that_is_no_line_of_a_question_file_fails(changes):
    assert "line" in checked(changes).failed


# --- 2: the anchor stands once, in the part ---------------------------------------------------


def test_an_anchor_that_differs_in_white_space_alone_is_taken_as_the_paper_writes_it():
    changes = {
        "anchor": "a model of widgets and their decays",
        "question": "{paper} studies a model: of what?",
        "reference_answer": "Of widgets and their decays.",
        "numbers": [],
        "phrases": [{"label": "object", "any_of": ["widgets"]}],
    }
    result = checked(changes, section="1")
    assert result.anchor == "a model of widgets\nand their decays"
    assert "anchor_once" not in result.failed


def test_an_anchor_that_the_section_does_not_hold_fails():
    result = checked({"anchor": "The detector has an area of 37.3 square metres"})
    assert failures(result)["anchor_once"] == "the anchor does not stand in its section"


def test_an_anchor_that_stands_twice_in_its_section_fails():
    # A piece of the filler, which stands in every line of it.
    result = checked({"anchor": "aaaaaaaaa aaaaaaaaa aaaaaaaaa"})
    assert failures(result)["anchor_once"].startswith("the anchor stands ")


def test_an_anchor_outside_the_part_fails_although_it_is_in_the_section():
    # The part is the later piece of 2.2; the anchor stands once in 2.2, in its first piece.
    place = placed("2.2", LATER_PIECE)
    first = LONG_FIRST[: len("\\subsection{Long run}")]
    result = check(Draft.from_dict(draft(anchor=first)), paper(), place, place.kind)
    assert failures(result)["anchor_once"] == "the anchor stands outside the part"


def test_the_whole_section_is_searched_subsections_too():
    # Section 2 holds 2.1. An anchor of 2.1 asked about as the own text of 2 is outside.
    result = checked(section="2", kind=OWN_TEXT)
    assert failures(result)["anchor_once"] == "the anchor stands outside the part"


def test_as_written_prefers_the_place_in_the_part():
    text = "x the a  b y\n\nz the a\nb w"
    assert as_written("the a b", text, 10, len(text)) == "the a\nb"
    assert as_written("the a b", text, 0, 9) == "the a  b"
    assert as_written("  ", text, 0, len(text)) is None


# --- 3 and 4: the key, and the key in the anchor ---------------------------------------------


def test_a_key_without_numbers_and_phrases_fails():
    assert "key_kinds" in checked({"numbers": [], "phrases": []}).failed


def test_a_value_of_the_key_that_the_anchor_does_not_write_fails():
    numbers = [{"label": "area", "value": 37.25, "unit": "", "min_sig_figs": 4}]
    assert failures(checked({"numbers": numbers}))["key_in_anchor"] == (
        "the anchor does not write 'area'"
    )


def test_fewer_digits_than_the_key_count_when_the_key_allows_them():
    numbers = [{"label": "area", "value": 37.24, "unit": "", "min_sig_figs": 3}]
    # 37.2 is 37.24 to three digits.
    assert "key_in_anchor" not in checked({"numbers": numbers}).failed
    numbers = [{"label": "area", "value": 37.24, "unit": "", "min_sig_figs": 4}]
    assert "key_in_anchor" in checked({"numbers": numbers}).failed


def test_a_name_in_tex_formatting_is_written():
    changes = {
        "anchor": "The data of \\textit{Fermi}-LAT were used for the slope fit.",
        "question": "Whose data does {paper} use for the slope fit?",
        "reference_answer": "The data of Fermi-LAT.",
        "numbers": [],
        "phrases": [{"label": "instrument", "any_of": ["Fermi-LAT", "Fermi LAT"]}],
    }
    result = checked(changes, section="3")
    assert result.passed, result.why


def test_phrases_are_held_to_text_without_white_space_and_capitals():
    tex = "the $\\gamma$-ray excess of \\textit{Fermi}-LAT in dark\nmatter"
    text = squeezed(tex)
    for wording in ("gamma-ray", "Fermi-LAT", "dark matter", "DARK  MATTER"):
        assert phrase_written({"any_of": [wording]}, text)
    assert not phrase_written({"any_of": ["neutrino"]}, text)
    assert not phrase_written({"any_of": ["{}", " "]}, text)  # nothing left to look for


def test_numbers_are_read_off_tex_as_the_check_of_a_question_file_reads_them():
    written = [n.text for n in numbers_written("$2.5\\,\\times\\,10^{-26}$ and $\\sim100$")]
    assert written == ["2.5 \\times 10^{-26}", "100"]


# --- 5 and 6: nowhere else -------------------------------------------------------------------


def test_a_value_of_the_abstract_fails():
    changes = {
        "anchor": "The detector has an area of 37.2 square metres",
        "numbers": [{"label": "mass", "value": 12.5, "unit": "GeV", "min_sig_figs": 3}],
    }
    assert "not_in_listing" in checked(changes).failed


def test_a_value_of_the_title_fails():
    # "low energy" stands in the title and nowhere else, not in the abstract either.
    changes = {"phrases": [{"label": "regime", "any_of": ["low energy"]}]}
    assert failures(checked(changes))["not_in_listing"] == (
        "the title or the abstract writes 'regime'"
    )


def test_a_value_that_another_section_writes_fails():
    changes = {
        "anchor": "The detector has an area of 37.2 square metres in total",
        "numbers": [{"label": "points", "value": 4096, "unit": "", "min_sig_figs": 4}],
    }
    result = checked(changes)
    assert failures(result)["not_elsewhere"] == "outside the part: 'points'"


def test_a_value_of_a_subsection_is_elsewhere_for_the_own_text_of_its_section():
    changes = {
        "anchor": "The scan of the model uses 4096 points on a regular grid.",
        "question": "How many points does the scan of {paper} use?",
        "reference_answer": "4096 points.",
        "numbers": [
            {"label": "points", "value": 4096, "unit": "", "min_sig_figs": 4},
            {"label": "area", "value": 37.2, "unit": "", "min_sig_figs": 3},
        ],
    }
    result = checked(changes, section="2", kind=OWN_TEXT)
    assert failures(result)["not_elsewhere"] == "outside the part: 'area'"


def test_a_value_in_the_first_piece_is_elsewhere_for_a_later_piece():
    changes = {
        "anchor": "the coupling is fixed to 0.0318 at the reference scale",
        "question": "To what is the coupling fixed at the reference scale in {paper}?",
        "reference_answer": "0.0318.",
        "numbers": [{"label": "coupling", "value": 0.0318, "unit": "", "min_sig_figs": 3}],
    }
    result = checked(changes, section="2.2", kind=LATER_PIECE)
    assert result.passed, result.why
    # The same draft asked about the first piece: its anchor is not there.
    assert "anchor_once" in checked(changes, section="2.2", kind=NAMED_FIRST).failed


def test_the_title_of_a_section_counts_as_elsewhere():
    # The title of the appendix is written in no text of the paper, only in its outline.
    changes = {"phrases": [{"label": "fit", "any_of": ["details of the fit"]}]}
    assert failures(checked(changes))["not_elsewhere"] == "outside the part: 'fit'"


# --- 7: the question -------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("question", "why"),
    [
        ("What is the area of the detector?", "the mark {paper} stands 0 times"),
        ("In {paper} and {paper}, what is the area?", "the mark {paper} stands 2 times"),
        ("In {paper} (2609.01234), what is the area?", "it holds an arXiv identifier"),
        ("In {paper}, is the area 37.2 square metres?", "it writes the value of 'area'"),
        (
            "In the detector setup of {paper}, what is the area?",
            "it names the title of its section",
        ),
        (
            "In {paper}, what area does Section 2 give?",
            "it names a section, an equation, a figure or a table by its number",
        ),
        (
            "In {paper}, what area enters Eq. (5)?",
            "it names a section, an equation, a figure or a table by its number",
        ),
        (
            "In {paper}, what area does Table I list?",
            "it names a section, an equation, a figure or a table by its number",
        ),
        ("In {paper}, what area does the appendix give?", 'it holds the word "appendix"'),
    ],
)
def test_a_question_that_gives_something_away_fails(question, why):
    assert why in failures(checked({"question": question}))["question_clean"]


def test_a_title_of_one_word_may_stand_in_a_question():
    # "Results" is a word of any question about results.
    changes = {
        "anchor": "The fitted slope is 2.37 for the main sample of events.",
        "question": "Among the results of {paper}, what is the fitted slope of the main sample?",
        "reference_answer": "2.37.",
        "numbers": [{"label": "slope", "value": 2.37, "unit": "", "min_sig_figs": 3}],
    }
    assert checked(changes, section="3").passed


# --- 8: lengths ------------------------------------------------------------------------------


def test_the_lengths_are_held_to_their_limits():
    long = "In {paper}, " + "what " * 80 + "is the area?"
    result = failures(checked({"question": long, "anchor": "37.2 square metres"}))
    assert "the question has" in result["lengths"]
    assert "the anchor has 18 characters" in result["lengths"]
    result = failures(checked({"reference_answer": "37.2 " * 81, "anchor": "x" * 121}))
    assert "the reference answer has 405 characters" in result["lengths"]
    assert "the anchor has 121 characters" in result["lengths"]
    # At the limits themselves, nothing fails.
    assert "lengths" not in checked({"reference_answer": "37.2" + " " * 395 + "."}).failed


# --- 10: running text ------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("anchor", "value"),
    [
        ("\\caption{The yields of the 815 runs.}", 815),
        ("\\begin{tabular}{cc} 77.7 & 88.8", 77.7),
        ("\\footnote{The run lasted 51 days.}", 51),
    ],
)
def test_an_anchor_in_a_table_a_caption_or_a_footnote_fails(anchor, value):
    changes = {
        "anchor": anchor,
        "question": "In {paper}, what number is given there?",
        "numbers": [{"label": "it", "value": value, "unit": "", "min_sig_figs": 2}],
    }
    assert "running_text" in checked(changes, section="3").failed


def test_an_anchor_that_runs_into_a_footnote_fails():
    changes = {
        "anchor": "A remark here\\footnote{The run",
        "question": "In {paper}, what remark is made?",
        "numbers": [],
        "phrases": [{"label": "remark", "any_of": ["remark here"]}],
    }
    assert "running_text" in checked(changes, section="3").failed


def test_the_stretches_that_are_no_running_text():
    text = (
        "a $x$ b \\[ y \\] c $$ z $$ d \\begin{align*} w \\end{align*} e "
        "\\\\[2pt] f \\footnote[3]{q {r} s} g \\begin{figure}\\begin{tabular}t\\end{tabular}"
        "\\end{figure} h"
    )
    spans = [text[start:end] for start, end in not_running(text)]
    assert spans == [
        "\\[ y \\]",
        "$$ z $$",
        "\\begin{align*} w \\end{align*}",
        "\\footnote[3]{q {r} s}",
        "\\begin{figure}\\begin{tabular}t\\end{tabular}\\end{figure}",
    ]
    # Inline math, and the line break with its spacing, are running text.
    assert all("$x$" not in span and "[2pt]" not in span for span in spans)


@pytest.mark.parametrize(
    ("text", "stretch"),
    [
        ("a \\begin{table} a note \\end{table} b", "\\begin{table} a note \\end{table}"),
        ("a \\begin{tabular}{c} x \\end{tabular} b", "\\begin{tabular}{c} x \\end{tabular}"),
        ("a \\caption[short]{a {long} one} b", "\\caption[short]{a {long} one}"),
        ("a \\captionof{figure}{the text} b", "\\captionof{figure}{the text}"),
        ("a \\begin{equation*} y \\end{equation*} b", "\\begin{equation*} y \\end{equation*}"),
    ],
)
def test_each_kind_of_stretch_is_found_on_its_own(text, stretch):
    assert [text[start:end] for start, end in not_running(text)] == [stretch]


# --- all of them -----------------------------------------------------------------------------


def test_a_draft_counts_under_every_check_it_fails():
    bad = checked({"anchor": "37.2", "question": "What is 37.2?"})
    good = checked()
    assert bad.failed == ("question_clean", "lengths")
    assert counted([bad, good]) == {name: int(name in bad.failed) for name in CHECKS}


def test_search_first_is_checked_as_its_place_is():
    result = checked(kind=SEARCH_FIRST)
    assert result.passed
    assert placed("2.1", SEARCH_FIRST).kind == SEARCH_FIRST


def test_the_checks_run_on_every_place_of_a_real_paper():
    # The owner's paper (CC0, tests/fixtures), as the parser splits it: it has a place of
    # every kind, its equations, figures and tables are seen, and a draft about any of its
    # places is checked without an error.
    tex = (OWN_PAPER / "FermiLAT-main.tex").read_text(encoding="utf-8")
    meta = PaperMeta("2610.26648v1", "A paper", ("A",), 2026, "astro-ph.HE", "Abstract.")
    real = paper_from_latex(meta, tex)
    found = places_of(real)
    assert {place.kind for place in found} == {NAMED_FIRST, OWN_TEXT, APPENDIX, LATER_PIECE}
    assert sum(len(not_running(section.text)) for section in real.sections) > 10
    for place in found:
        section = next(s for s in real.sections if s.section_id == place.section)
        anchor = section.text[place.start : place.end].strip()[:60]
        result = check(
            Draft.from_dict(draft(anchor=anchor)),
            real,
            placed(place.section, place.kind, of=real),
            place.kind,
        )
        assert "line" not in result.failed
