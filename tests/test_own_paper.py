"""The parser on a real paper: arXiv:2610.26648v1, kept in tests/fixtures (CC0). No network.

The expected outline below was read off the paper. If a change to the parser makes
this test fail, section identifiers or sizes have moved: raise PARSER_VERSION, and
check every evaluation question that names a section.
"""

from conftest import OWN_PAPER, tar_gz

from hepph_paper_miner.sources.arxiv_latex import PARSER_VERSION, find_main, parse_source, unpack

EXPECTED = [
    # id, chars, title
    ("1", 13905, "Introduction"),
    ("2", 7579, "Fermi-LAT and AMS-02"),
    ("2.1", 5176, "Fermi-LAT"),
    ("2.2", 2064, "AMS-02"),
    ("3", 33002, "Analysis of the Galactic Center Excess"),
    ("3.1", 3511, "Modeling of Diffuse Emission Backgrounds"),
    ("3.2", 7158, "Point Source Masking"),
    ("3.3", 3650, "Data Preparation"),
    ("3.4", 2804, "Template Fitting"),
    ("3.5", 8704, "Systematic Uncertainties"),
    ("3.6", 5131, "Dark Matter interpretation"),
    ("4", 18876, "Gamma-ray constraints from dwarf spheroidal galaxies"),
    ("4.1", 7181, "Data selection and source modeling"),
    ("4.2", 5218, "SED extraction and dark-matter likelihood construction"),
    ("4.3", 5245, "Combined limits from dSphs"),
    ("5", 5312, "Constraints from AMS-02 antiproton measurements"),
    ("6", 38025, "Benchmark dark matter interpretations of the GCE"),
    ("6.1", 6672, "Interpretation with the two-body channels"),
    ("6.2", 4705, "Interpretation with the effective four-body channels"),
    ("6.3", 25531, "Mediator effects in dark matter cascade annihilation"),
    ("7", 9253, "A singlet fermionic dark matter benchmark for the GCE"),
    ("7.1", 1477, "Model details"),
    ("7.2", 6894, "An SFDM benchmark for the four-bottom cascade"),
    ("8", 5711, "Conclusions"),
    ("u1", 473, "Acknowledgements"),
    ("A", 1827, "Validation of the dSphs analysis"),
    ("B", 2967, "Comparison of the FL16Y and 4FGL-DR2 catalogs"),
    ("C", 3739, "Front and Back foil data"),
    ("D", 2785, "Explanation of weak limit of 17.7 yr"),
]


def download() -> bytes:
    """The two kept files packed the way arXiv packs a paper with several files."""
    return tar_gz(
        {path.name: path.read_bytes() for path in OWN_PAPER.iterdir() if path.suffix != ".md"}
    )


def test_main_file_comes_from_the_list_arxiv_ships():
    assert find_main(unpack(download())) == "FermiLAT-main.tex"


def test_outline_of_the_real_paper_is_what_the_paper_shows():
    assert PARSER_VERSION == "4"
    sections = parse_source(download())
    assert [(section.section_id, section.chars, section.title) for section in sections] == EXPECTED


def test_structure_counts():
    sections = parse_source(download())
    numbered = [s for s in sections if s.level == 1 and s.section_id.isdigit()]
    appendices = [
        s for s in sections if s.level == 1 and s.section_id.isalpha() and s.section_id.isupper()
    ]
    assert (len(numbered), len(appendices), sum(s.level == 2 for s in sections)) == (8, 4, 16)
    assert sum(s.chars for s in sections if s.level == 1) == 143454


def test_text_is_latex_without_comments_or_bibliography():
    sections = {section.section_id: section for section in parse_source(download())}
    assert sections["1"].text.startswith(
        "Indirect detection searches for signatures of dark matter (DM)"
    )
    assert sections["D"].text.endswith(
        "\\end{figure}"
    )  # \bibliography and \end{document} are not part of it
    assert "\\bibliography" not in sections["D"].text
    # A subsection too long for one read: the reason read_section can continue from a position.
    assert sections["6.3"].chars > 20000
