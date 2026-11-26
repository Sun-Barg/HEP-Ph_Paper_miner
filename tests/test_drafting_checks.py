"""What a program checks of a draft before a model sees it again (drafting/checks.py).

The paper is the invented one of drafting_paper.py: every value it holds stands in one
known place, so each check can be made to pass and to fail on purpose.
"""

from dataclasses import replace

import pytest
from conftest import OWN_PAPER
from drafting_paper import LONG_FIRST, draft, paper, placed

from hepph_paper_miner.drafting.checks import (
    CHECKS,
    LEAST_DIGITS,
    as_written,
    check,
    counted,
    not_running,
    number_elsewhere,
    numbers_with_ends,
    numbers_written,
    phrase_written,
    short_numbers,
    squeezed,
    unit_after,
    unit_of,
    with_power,
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
from hepph_paper_miner.sources.base import Paper, PaperMeta
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
        "two_digits",
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


def test_the_dash_of_a_range_in_tex_is_no_minus():
    # "--" makes the dash of a range in TeX. Read as it stands, the number after it would
    # be negative: a minus sign is a minus where no number stands right before it.
    assert [str(n.value) for n in numbers_written("energies of 30--37.2~GeV")] == ["30", "37.2"]
    assert [str(n.value) for n in numbers_written("from 6.4---290 GeV")] == ["6.4", "290"]
    # A minus and a range of one dash are read as before.
    assert [str(n.value) for n in numbers_written("$-3.5$ and 0.2-0.4")] == ["-3.5", "0.2", "0.4"]
    numbers = [{"label": "area", "value": 37.2, "unit": "", "min_sig_figs": 3}]
    changes = {"anchor": "detector has an area of 37.2 square metres", "numbers": numbers}
    assert "key_in_anchor" not in checked(changes).failed


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


# --- 6: a number with its unit, outside the part ------------------------------------------


def with_intro(more: str) -> Paper:
    """The invented paper with a sentence more at the end of its introduction."""
    base = paper()
    sections = tuple(
        replace(section, text=section.text + more) if section.section_id == "1" else section
        for section in base.sections
    )
    return Paper(base.meta, sections, base.parser_version)


@pytest.mark.parametrize(
    ("sentence", "elsewhere"),
    [
        ("A ring of 37.2 parsecs is not an area.\n", False),  # the same number, another unit
        ("We count 37.2 events.\n", False),
        ("An area of 37.2~square metres is used again.\n", True),
        ("An area of $37.2\\,{\\rm square}$ metres.\n", True),
        ("Areas of 30--37.2 square metres were tried.\n", True),  # either end of a range
        ("Areas of 30-37.2 square metres were tried.\n", True),
        ("Areas of 37.2--40 square metres were tried.\n", True),
        ("Areas of 37.2--40 parsecs were tried.\n", False),
        ("It is (37.2 \\pm 0.1) square metres.\n", True),
    ],
)
def test_a_number_with_a_unit_is_elsewhere_only_with_its_unit(sentence, elsewhere):
    result = checked(of=with_intro(sentence))
    assert ("not_elsewhere" in result.failed) == elsewhere, result.why


def test_a_number_without_its_unit_after_it_is_not_counted_elsewhere():
    # What the rule misses, on purpose: the same value without its unit right after it, as
    # in a table whose unit stands in its head.
    sentence = "\\begin{tabular}{cc} area (square metres) & 37.2 \\\\ \\end{tabular}\n"
    assert "not_elsewhere" not in checked(of=with_intro(sentence)).failed


def test_a_number_of_the_key_without_a_unit_is_elsewhere_wherever_it_stands():
    changes = {"numbers": [{"label": "area", "value": 37.2, "unit": "", "min_sig_figs": 3}]}
    for sentence in ("A ring of 37.2 parsecs.\n", "We count 37.2 events.\n"):
        result = checked(changes, of=with_intro(sentence))
        assert failures(result)["not_elsewhere"] == "outside the part: 'area'"


def test_the_unit_rule_reads_only_outside_the_part():
    # In the anchor and the question a number counts without its unit, as before: a value
    # that the question writes gives the answer away whatever stands after it.
    changes = {"question": "In {paper}, is 37.2 the area of the detector?"}
    assert "it writes the value of 'area'" in failures(checked(changes))["question_clean"]
    numbers = [{"label": "area", "value": 37.2, "unit": "parsecs", "min_sig_figs": 3}]
    assert "key_in_anchor" not in checked({"numbers": numbers}).failed


@pytest.mark.parametrize(
    ("tex", "value", "unit", "written"),
    [
        ("r_s = 20~kpc", 20, "kpc", True),
        ("$r_s =20$ kpc, and", 20, "kpc", True),
        ("20\\,{\\rm kpc}", 20, "kpc", True),
        ("20~\\mathrm{kpc}", 20, "kpc", True),
        ("\\SI{20}{kpc}", 20, "kpc", True),
        ("20 pc and 2 kpc", 20, "kpc", False),
        ("20 & 30 kpc", 20, "kpc", False),
        ("the value 20.", 20, "kpc", False),
        ("6.4-9.1 GeV", 6.4, "GeV", True),
        ("6.4--9.1~GeV", 6.4, "GeV", True),
        ("6.4$-$9.1 GeV", 6.4, "GeV", True),
        ("6.4 to 290 GeV", 6.4, "GeV", True),
        ("20 \\pm 5 kpc", 20, "kpc", True),
        ("(20 \\pm 5)~kpc", 20, "kpc", True),
        ("20^{+5}_{-3}\\,{\\rm kpc}", 20, "kpc", True),
        ("1.3^{+0.2}_{-0.1} \\pm 0.1~TeV", 1.3, "TeV", True),  # two uncertainties
        ("1.2345(6) GeV", 1.2345, "GeV", True),
        ("20kpc", 20, "kpc", True),
        ("10\\%", 10, "%", True),
        ("10 percent", 10, "%", True),
        ("10\\% and 20 cm", 20, "%", False),
        ("5~\\kev", 5, "keV", True),
        ("\\rule{0mm}{5mm}", 5, "keV", False),
        ("2 \\times 10^{-9} \\; \\textrm{ph cm}^{-2}", 2e-9, "ph cm^-2 s^-1", True),
        ("14 &10.0 & 11.5 \\\\ 15 &11.5 & 16.5", 11.5, "GV", False),
        ("|b| < 20^\\circ", 20, "deg", True),
        ("|b| < 20$^{\\circ}$", 20, "°", True),
        ("|b| < 20°", 20, "degrees", True),
        ("|b| < 20\\textdegree", 20, "°", True),
        ("|b| < 20\\degree", 20, "$^\\circ$", True),
        ("|b| < 20^\\circ", 20, "kpc", False),
        ("3\\sigma", 3, "σ", True),
        ("3 $\\sigma$", 3, "sigma", True),
        ("20 \\mu m", 20, "μm", True),
        ("0.79^2 kpc", 0.79, "kpc", False),  # a power on the number, not the unit
        ("20~{\\rm kpc}", 20, "{\\rm kpc}", True),  # a unit written as TeX
        ("20 kpc", 20, "~kpc", True),
        ("20 cm", 20, "~kpc", False),
        ("z\\sim 300", 300, "", True),
        ("\\sim 300 GeV", 300, "", True),  # no unit in the key: wherever it stands
    ],
)
def test_a_number_and_its_unit_are_read_off_tex(tex, value, unit, written):
    item = {"label": "x", "value": value, "unit": unit, "min_sig_figs": 1}
    assert number_elsewhere(item, tex) == written


def test_units_are_held_to_each_other_by_their_first_word():
    assert [unit_of({"unit": unit}) for unit in ("GeV/c^2", "ph cm^-2 s^-1", "°", "")] == [
        "gev",
        "ph",
        "deg",
        "",
    ]
    assert unit_of({"unit": "Degrees"}) == unit_of({"unit": "\\circ"}) == "deg"
    assert unit_of({"unit": "μm"}) == unit_of({"unit": "µm"}) == "mu"  # Greek mu, micro sign
    text = "a 40\\,{\\rm GeV} b"
    assert unit_after(text, text.index("40") + 2) == "gev"
    assert unit_after("12 ", 2) == ""


def test_the_numbers_with_their_ends_are_the_numbers_of_the_check():
    for tex in (
        "$2.5\\,\\times\\,10^{-26}$ and $\\sim100$",
        "0.2-0.4 and h2 at -3 and 1,234.5",
        "a 0.79^2 and 2.26e-26 then 10^{-5}",
    ):
        text, found = numbers_with_ends(tex)
        assert [number for number, _ in found] == numbers_written(tex)
        for number, end in found:
            assert text[end - len(number.text) : end] == number.text


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


# --- two digits ------------------------------------------------------------------------------


def one_number(value, min_sig_figs: int = 1) -> Draft:
    numbers = [{"label": "n", "value": value, "unit": "", "min_sig_figs": min_sig_figs}]
    return Draft.from_dict(draft(numbers=numbers))


@pytest.mark.parametrize(
    ("tex", "value", "short"),
    [
        ("a shell of 5~pc", 5, True),
        ("a shell of $\\sim5$~pc", 5, True),  # read off the TeX, as the other checks read it
        ("a fraction of 0.5", 0.5, True),
        ("about 0.5 of the flux", 0.52, True),  # the key allows one digit, and the text has one
        ("$-3$ in the slope", -3, True),
        ("at 3\\sigma", 3, True),
        ("a radius of 37~kpc", 37, False),
        ("a ratio of 1.0", 1.0, False),  # two digits written, whatever the key holds
        ("0.52 of the flux", 0.52, False),
        ("20~kpc", 20, False),
        ("10\\% of the sky", 10, False),
        ("one in $10^{15}$ events", 1e15, False),  # one digit to the grader, but a power
        ("$2\\times10^{-26}$ cm$^3$/s", 2e-26, False),
        ("a value of 2.26e-26", 2.26e-26, False),
        ("$10^2$ samples", 100, False),
        ("5 and 5.0 pc", 5.0, False),  # written once with two digits
        ("37.2 square metres", 5, False),  # not written at all: that is key_in_anchor's
    ],
)
def test_a_number_of_the_key_is_written_with_two_digits_or_a_power_of_ten(tex, value, short):
    assert LEAST_DIGITS == 2
    assert (short_numbers(one_number(value), tex) == [0]) == short


def test_a_power_of_ten_is_read_off_the_text_of_a_number():
    written = numbers_written("10^{15}, 2.5\\times10^{-3}, 2e-26, 2×10⁻²⁶, 10⁻⁵, 0.79^2 and 37")
    assert [with_power(number) for number in written] == [True] * 5 + [False, False]


def test_only_the_numbers_of_the_key_that_are_short_are_named():
    numbers = [
        {"label": "radius", "value": 37, "unit": "kpc", "min_sig_figs": 2},
        {"label": "shell", "value": 5, "unit": "pc", "min_sig_figs": 1},
    ]
    found = Draft.from_dict(draft(numbers=numbers))
    assert short_numbers(found, "a radius of 37 kpc and a shell of 5 pc") == [1]


def test_a_key_of_one_digit_fails():
    # The draft that the owner turned down in the second round of the tuning had a radius of
    # 5 pc for its key: the prompt asked for two digits, and nothing checked it.
    changes = {
        "anchor": "A shell of 5 pc lies around the core of the model",
        "question": "In {paper}, how thick is the shell around the core of the model?",
        "reference_answer": "5 pc.",
        "numbers": [{"label": "shell", "value": 5, "unit": "pc", "min_sig_figs": 1}],
    }
    of = with_intro("A shell of 5 pc lies around the core of the model.\n")
    assert failures(checked(changes, section="1", of=of)) == {
        "two_digits": (
            "the anchor writes 'shell' with fewer than 2 significant digits and no power of ten"
        )
    }
    # Written with two digits, the same draft passes every check.
    changes["anchor"] = "A shell of 5.0 pc lies around the core of the model"
    changes["numbers"] = [{"label": "shell", "value": 5.0, "unit": "pc", "min_sig_figs": 2}]
    of = with_intro("A shell of 5.0 pc lies around the core of the model.\n")
    result = checked(changes, section="1", of=of)
    assert result.passed, result.why


def test_the_failure_names_the_short_numbers_only():
    changes = {
        "anchor": "A shell of 5 pc lies 37 kpc away from the core",
        "question": "In {paper}, how thick is the shell, and how far is it from the core?",
        "reference_answer": "5 pc thick, 37 kpc from the core.",
        "numbers": [
            {"label": "distance", "value": 37, "unit": "kpc", "min_sig_figs": 2},
            {"label": "shell", "value": 5, "unit": "pc", "min_sig_figs": 1},
        ],
    }
    of = with_intro("A shell of 5 pc lies 37 kpc away from the core.\n")
    why = failures(checked(changes, section="1", of=of))
    assert list(why) == ["two_digits"] and why["two_digits"].startswith(
        "the anchor writes 'shell' with"
    )


def test_a_number_that_the_anchor_does_not_write_is_left_to_key_in_anchor():
    # One fault of a draft is counted once.
    numbers = [{"label": "area", "value": 5, "unit": "", "min_sig_figs": 1}]
    result = checked({"numbers": numbers})
    assert "key_in_anchor" in result.failed and "two_digits" not in result.failed


def test_two_digits_is_made_of_an_anchor_that_differs_in_white_space():
    # The draft writes a space where the paper breaks the line: the anchor is taken as the
    # paper writes it, and the check is made of it as of any other.
    changes = {
        "anchor": "A shell of 5 pc lies around the core",
        "question": "In {paper}, how thick is the shell around the core of the model?",
        "reference_answer": "5 pc.",
        "numbers": [{"label": "shell", "value": 5, "unit": "pc", "min_sig_figs": 1}],
    }
    of = with_intro("A shell of 5 pc lies around\nthe core of the model.\n")
    result = checked(changes, section="1", of=of)
    assert result.anchor == "A shell of 5 pc lies around\nthe core"
    assert "two_digits" in result.failed


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
