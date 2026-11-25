"""Section splitting on invented LaTeX. No network."""

import gzip
import pickle
import random
import zlib

import pytest
from conftest import SAMPLE_LATEX, filler, plain_tar, tar_gz

from hepph_paper_miner.sources.arxiv_latex import (
    NotASource,
    check,
    expand_inputs,
    find_main,
    parse_source,
    split,
    strip_comments,
    unpack,
)
from hepph_paper_miner.sources.base import ErrorKind, Section, SourceError


def sections_of(latex: str, extra: dict[str, str] | None = None):
    files = {"main.tex": latex, **(extra or {})}
    return split(files, "main.tex")


def document(body: str) -> str:
    return "\\documentclass{article}\n\\begin{document}\n" + body + "\n\\end{document}\n"


# --- comments ------------------------------------------------------------------------


def test_comments_go_and_escaped_percent_signs_stay():
    text = "kept 100\\% here % gone\n% a whole line gone\nline break\\\\% gone too\nlast"
    assert strip_comments(text) == "kept 100\\% here \nline break\\\\\nlast"


def test_a_percent_sign_inside_a_web_address_is_not_a_comment():
    text = "See \\url{http://x.org/a%20b} and \\href{http://x.org/c%2Fd}{here}, then more. % gone"
    assert strip_comments(text) == (
        "See \\url{http://x.org/a%20b} and \\href{http://x.org/c%2Fd}{here}, then more. "
    )
    # After a comment has started, an address is part of the comment.
    assert strip_comments("kept % \\url{http://x.org/a%20b} gone") == "kept "


def test_comment_environment_and_iffalse_blocks_go():
    text = "a\n\\begin{comment}\n\\section{Hidden}\n\\end{comment}\nb\n\\iffalse\n\\section{Hidden too}\n\\fi\nc"
    stripped = strip_comments(text)
    assert "Hidden" not in stripped
    assert stripped.split() == ["a", "b", "c"]


# --- identifiers and extents -----------------------------------------------------------


def test_sample_paper_gets_the_identifiers_latex_would_print():
    sections = sections_of(SAMPLE_LATEX)
    outline = [(section.section_id, section.level, section.title) for section in sections]
    assert outline == [
        ("1", 1, "Introduction"),
        ("2", 1, "Methods and the $\\mathcal{O}(1)$ case"),
        ("2.1", 2, "Data"),
        ("2.u1", 2, "A side note"),
        ("2.2", 2, "Fit"),
        ("u1", 1, "Acknowledgements"),
        ("A", 1, "Extra tables"),
        ("A.1", 2, "More"),
    ]


def test_a_section_contains_its_subsections_and_a_subsection_stops_at_the_next_heading():
    by_id = {section.section_id: section for section in sections_of(SAMPLE_LATEX)}

    assert by_id["2"].text.startswith("Methods overview.")
    assert "\\subsection{Data}" in by_id["2"].text
    assert "Fit text." in by_id["2"].text
    assert "Thanks." not in by_id["2"].text

    assert by_id["2.1"].text == "Data text."
    assert by_id["2.2"].text == "Fit text."
    assert by_id["u1"].text == "Thanks."  # stops at \appendix
    assert by_id["A"].text.endswith("More text.")  # the bibliography command is gone


def test_comments_are_not_part_of_the_text_and_not_counted():
    intro = sections_of(SAMPLE_LATEX)[0]
    assert "100\\% of it stays." in intro.text
    assert "trailing comment" not in intro.text
    assert intro.chars == len(intro.text)


def test_heading_inside_a_comment_and_commands_that_only_start_like_a_heading_are_ignored():
    body = (
        "\\section{One}\n"
        + filler(200)
        + "\n%\\section{Two}\n\\sectionmark{x}\n\\subsectionfont{y}\n"
    )
    assert [section.section_id for section in sections_of(document(body))] == ["1"]


def test_bibliography_environment_is_removed():
    body = "\\section{One}\nText.\n\\begin{thebibliography}{9}\n\\bibitem{a} Somebody.\n\\end{thebibliography}\n"
    (section,) = sections_of(document(body))
    assert section.text == "Text."


def test_paper_without_headings_is_one_section():
    (section,) = sections_of(document("\\maketitle\nJust text."))
    assert (section.section_id, section.level, section.text) == ("1", 1, "Just text.")


def test_long_text_before_the_first_heading_becomes_section_zero():
    body = "\\maketitle\n" + filler(100) + "\n\\section{Later}\nMore."
    assert [section.section_id for section in sections_of(document(body))] == ["0", "1"]

    short = "\\maketitle\nA line.\n\\section{Later}\nMore."
    assert [section.section_id for section in sections_of(document(short))] == ["1"]


# Text under no heading of its own: every piece of the body has to lie in a section.


def test_long_text_after_appendix_and_before_the_next_section_is_a_section_of_its_own():
    # It used to lie in no section: the one before it ends at \appendix.
    lead = "Lead-in. " + filler(60)
    body = (
        "\\section{One}\nFirst.\n\\section*{Thanks}\nThanks.\n"
        "\\appendix\n" + lead + "\n\\section{Tables}\nTable text."
    )
    assert [(s.section_id, s.level, s.title, s.text) for s in sections_of(document(body))] == [
        ("1", 1, "One", "First."),
        ("u1", 1, "Thanks", "Thanks."),
        ("u2", 1, "(text after \\appendix, without a section heading)", lead),
        ("A", 1, "Tables", "Table text."),
    ]


def test_commands_after_appendix_are_not_a_section():
    body = (
        "\\section{One}\nFirst.\n\\appendix\n\\setcounter{equation}{0}\n"
        "\\renewcommand{\\theequation}{A.\\arabic{equation}}\n\\section{Tables}\nTable text."
    )
    assert [s.section_id for s in sections_of(document(body))] == ["1", "A"]


def test_a_paper_without_headings_keeps_what_follows_appendix():
    (section,) = sections_of(document("\\maketitle\nMain text.\n\\appendix\nMore text."))
    assert (section.section_id, section.text) == ("1", "Main text.\n\\appendix\nMore text.")


def test_subsections_before_the_first_section_lie_in_section_zero():
    body = (
        "\\maketitle\nA line.\n\\subsection{Notation}\nSigns.\n"
        "\\subsection*{Units}\nGeV.\n\\section{One}\nFirst."
    )
    sections = sections_of(document(body))
    assert [(s.section_id, s.level, s.title) for s in sections] == [
        ("0", 1, "(text before the first section)"),
        ("0.1", 2, "Notation"),
        ("0.u1", 2, "Units"),
        ("1", 1, "One"),
    ]
    # Short as it is, section 0 is kept: without it its subsections would lie in no section.
    assert sections[0].text == (
        "A line.\n\\subsection{Notation}\nSigns.\n\\subsection*{Units}\nGeV."
    )
    assert (sections[1].text, sections[2].text) == ("Signs.", "GeV.")


def test_a_paper_with_subsections_and_no_section_is_one_section_that_holds_them():
    body = "\\subsection{First}\nOne.\n\\subsection{Second}\nTwo."
    assert [(s.section_id, s.level, s.text) for s in sections_of(document(body))] == [
        ("0", 1, "\\subsection{First}\nOne.\n\\subsection{Second}\nTwo."),
        ("0.1", 2, "One."),
        ("0.2", 2, "Two."),
    ]


def test_subsections_after_appendix_without_a_section_lie_in_a_section_of_their_own():
    # They used to be numbered on from the section before \appendix, whose text ends there.
    body = (
        "\\section{One}\nFirst.\n\\subsection{Part}\nPart.\n\\appendix\n\\subsection{Proof}\nProof."
    )
    assert [(s.section_id, s.level, s.text) for s in sections_of(document(body))] == [
        ("1", 1, "First.\n\\subsection{Part}\nPart."),
        ("1.1", 2, "Part."),
        ("u1", 1, "\\subsection{Proof}\nProof."),
        ("u1.1", 2, "Proof."),
    ]


def test_in_random_papers_every_piece_of_text_lies_in_a_section():
    # A split that lost text is worse than no split. Every piece of text here names
    # itself with a word found nowhere else, and each has to turn up in a section.
    # Right after \appendix the pieces are long: a short one there, under no heading,
    # is taken for commands.
    rng = random.Random(2026)
    commands = [
        "\\section{S}",
        "\\section*{S}",
        "\\subsection{S}",
        "\\subsection*{S}",
        "\\appendix",
    ]
    for _ in range(300):
        lines, named = ["PIECE0 " + filler(200)], ["PIECE0"]
        for number in range(1, rng.randint(2, 10)):
            command = rng.choice(commands)
            lines.append(command)
            if rng.random() < 0.8:
                long = command == "\\appendix" or rng.random() < 0.5
                lines.append(f"PIECE{number} " + filler(60 if long else 3))
                named.append(f"PIECE{number}")
        sections = sections_of(document("\n".join(lines)))
        assert check(sections)[0] is True, lines
        found = " ".join(section.text for section in sections if section.level == 1).split()
        assert [name for name in named if name not in found] == [], lines


# --- where a section begins and no \section stands there (since parser 5) ------------------
#
# The survey of the papers the server can read showed three such places (results/survey/):
# the acknowledgements a class sets, text behind the list of references, and the titles
# that letters run into their paragraphs. In all three the text was returned before as
# well, inside another section. Now it has a section of its own.


@pytest.mark.parametrize(
    ("typed", "title"),
    [
        ("\\begin{acknowledgments}\nThanks to all.\n\\end{acknowledgments}", "Acknowledgments"),
        ("\\begin{acknowledgements}\nThanks to all.\n\\end{acknowledgements}", "Acknowledgements"),
        ("\\begin{acknowledgement}\nThanks to all.\n\\end{acknowledgement}", "Acknowledgement"),
        ("\\begin{acks}\nThanks to all.\n\\end{acks}", "Acknowledgments"),
        ("\\acknowledgments\nThanks to all.", "Acknowledgments"),
        ("\\acknowledgements{Thanks to all.}", "Acknowledgements"),
        ("\\ack{Thanks to all.}", "Acknowledgments"),
    ],
)
def test_the_acknowledgements_of_a_class_are_a_section_of_their_own(typed, title):
    # No heading is typed, so they used to be the end of the section before them. The
    # title is the word of the source, written out where the source shortens it.
    body = "\\section{One}\nFirst.\n\\section{Conclusions}\nLast words.\n" + typed
    _, last, thanks = sections_of(document(body))
    assert (last.section_id, last.title, last.text) == ("2", "Conclusions", "Last words.")
    assert (thanks.section_id, thanks.level, thanks.title) == ("u1", 1, title)
    assert thanks.text.startswith(("Thanks to all.", "{Thanks to all.}"))


def test_the_section_of_the_acknowledgements_runs_to_the_next_heading():
    # Like any section: what a paper prints below them stands under their heading.
    body = (
        "\\section{One}\nFirst.\n\\begin{acknowledgments}\nThanks.\n\\end{acknowledgments}\n"
        "A note added in proof.\n\\appendix\n\\section{Tables}\nTable text."
    )
    assert [(s.section_id, s.title, s.text) for s in sections_of(document(body))] == [
        ("1", "One", "First."),
        ("u1", "Acknowledgments", "Thanks.\n\\end{acknowledgments}\nA note added in proof."),
        ("A", "Tables", "Table text."),
    ]


def test_acknowledgements_under_a_heading_of_their_own_stay_one_section():
    body = (
        "\\section{One}\nFirst.\n\\section*{Acknowledgments}\n"
        "\\begin{acknowledgments}\nThanks.\n\\end{acknowledgments}"
    )
    assert [(s.section_id, s.title) for s in sections_of(document(body))] == [
        ("1", "One"),
        ("u1", "Acknowledgments"),
    ]
    # With text between the two, the environment begins a section as it does anywhere.
    apart = body.replace("{Acknowledgments}\n", "{Acknowledgments}\nFunding.\n")
    assert [s.section_id for s in sections_of(document(apart))] == ["1", "u1", "u2"]


def test_a_command_that_is_defined_or_only_begins_like_one_is_no_acknowledgement():
    body = (
        "\\renewcommand{\\acknowledgments}{\\par}\n\\def\\ack{x}\n\\let\\acks\\relax\n"
        "\\section{One}\nFirst. \\acknowledgmentsname\\ and \\acksfont are other commands."
    )
    assert [s.section_id for s in sections_of(document(body))] == ["1"]


REFERENCES = "\\begin{thebibliography}{9}\n\\bibitem{a} Somebody.\n\\end{thebibliography}\n"
AFTER_REFERENCES = "(text after the list of references, without a section heading)"


def test_text_behind_the_list_of_references_is_a_section_of_its_own():
    # It used to be the end of the section before the list, where no paper prints it:
    # the authors of a collaboration, tables, material without a heading.
    tail = "Authors. " + filler(60)
    body = "\\section{One}\nFirst.\n\\section{Summary}\nLast.\n" + REFERENCES + tail
    assert [(s.section_id, s.level, s.title, s.text) for s in sections_of(document(body))] == [
        ("1", 1, "One", "First."),
        ("2", 1, "Summary", "Last."),
        ("u1", 1, AFTER_REFERENCES, tail),
    ]
    # The commands that have BibTeX or biblatex print the list are such a place too.
    for command in (
        "\\bibliography{refs}\n",
        "\\bibliographystyle{plain}\n\\bibliography{refs}\n",
        "\\printbibliography[heading=none]\n",
    ):
        swapped = body.replace(REFERENCES, command)
        assert [s.section_id for s in sections_of(document(swapped))] == ["1", "2", "u1"]
    # Unlike \appendix, the end of a list does not change how later sections are numbered.
    later = sections_of(document(body + "\n\\section{Later}\nMore."))
    assert [s.section_id for s in later] == ["1", "2", "u1", "3"]
    # And \bibliographystyle prints no list, wherever it stands.
    style = (
        "\\section{One}\nFirst.\n\\bibliographystyle{plain}\n" + tail + "\n\\section{Two}\nLast."
    )
    assert [s.section_id for s in sections_of(document(style))] == ["1", "2"]


def test_commands_behind_the_list_of_references_stay_where_they_were():
    # Unlike a few words after \appendix, they are not left out: they end the section
    # before the list, as they did.
    body = (
        "\\section{One}\nFirst.\n"
        + REFERENCES
        + "\\clearpage\nA line.\n\\appendix\n\\section{Tables}\nTable text."
    )
    assert [(s.section_id, s.text) for s in sections_of(document(body))] == [
        ("1", "First.\n\n\\clearpage\nA line."),
        ("A", "Table text."),
    ]


def test_subsections_behind_the_list_of_references_lie_in_a_section_of_their_own():
    # In the paper they stand below the list. They used to be rows under the last
    # section before it, numbered on from its subsections.
    body = (
        "\\section{One}\nFirst.\n\\subsection{Part}\nPart.\n"
        + REFERENCES
        + "\\subsection*{Appendix A}\nProof."
    )
    sections = sections_of(document(body))
    assert [(s.section_id, s.level, s.title, s.text) for s in sections] == [
        ("1", 1, "One", "First.\n\\subsection{Part}\nPart."),
        ("1.1", 2, "Part", "Part."),
        ("u1", 1, AFTER_REFERENCES, "\\subsection*{Appendix A}\nProof."),
        ("u1.u1", 2, "Appendix A", "Proof."),
    ]
    # Where the heading of the subsection begins in the text of the section that holds it.
    assert sections[3].heading_at == 0


def test_a_list_of_references_under_no_title_is_no_place_where_a_section_begins():
    # In front of such a list there may be a few words only, which would then be left
    # out for standing under no heading by themselves. The text stays in one piece, as
    # it was: in a paper without headings, and after \appendix.
    tail = "More. " + filler(60)
    (section,) = sections_of(document("\\maketitle\nA few words.\n" + REFERENCES + tail))
    assert section.title == "(the paper has no section headings)"
    assert section.text == "A few words.\n\n" + tail

    body = "\\section{One}\nFirst.\n\\appendix\nA few words.\n" + REFERENCES + tail
    assert [(s.section_id, s.title, s.text) for s in sections_of(document(body))] == [
        ("1", "One", "First."),
        ("u1", "(text after \\appendix, without a section heading)", "A few words.\n\n" + tail),
    ]
    # One title in front is enough, also when the list comes twice.
    twice = "\\section{One}\nFirst.\n" + REFERENCES + "A line.\n" + REFERENCES + tail
    assert [(s.section_id, s.text) for s in sections_of(document(twice))] == [
        ("1", "First."),
        ("u1", "A line.\n\n" + tail),
    ]


def test_a_list_of_references_between_appendices_does_not_end_their_lettering():
    body = (
        "\\section{One}\nFirst.\n\\appendix\n\\section{Tables}\nTable text.\n"
        + REFERENCES
        + "Added later. "
        + filler(60)
        + "\n\\section{Proofs}\nProof."
    )
    assert [s.section_id for s in sections_of(document(body))] == ["1", "A", "u1", "B"]


# A letter as the journals of the APS print them: no heading, and titles in italics.
LETTER = (
    "\\maketitle\n"
    "\\textit{Introduction.}---" + filler(40) + "\n\n"
    "\\textit{Method.}---How it was done.\n\n"
    "\\textit{Results.}---What came out.\n"
)


def test_titles_run_into_paragraphs_divide_a_paper_without_headings():
    # Such a letter used to come back as one section.
    assert [(s.section_id, s.level, s.title, s.text) for s in sections_of(document(LETTER))] == [
        ("u1", 1, "Introduction", filler(40)),
        ("u2", 1, "Method", "How it was done."),
        ("u3", 1, "Results", "What came out."),
    ]


@pytest.mark.parametrize(
    "typed",
    [
        "\\textit{TITLE.---}",
        "\\textit{TITLE}---",
        "\\textit{TITLE}.---",
        "\\emph{TITLE}\\textemdash ",
        "\\emph{TITLE\u2014}",
        "{\\it TITLE}.---",
        "{\\em TITLE.} ---",
        "\\noindent\\textit{TITLE}: ",
        "\\textit{TITLE}. ",
        "\\textit{TITLE:} ",
    ],
)
def test_the_ways_a_title_is_typed_and_set_off(typed):
    # The mark belongs to the title: it is in neither the title of the section nor its text.
    words = ("Setup", "Data and selection", "Summary")
    paragraphs = [typed.replace("TITLE", word) + "Text of it." for word in words]
    body = "\\maketitle\n" + "\n\n".join(paragraphs)
    assert [(s.title, s.text) for s in sections_of(document(body))] == [
        (word, "Text of it.") for word in words
    ]


def test_fewer_than_three_typed_titles_are_left_alone():
    # Italics and a full stop at the head of a paragraph can be a turn of phrase.
    two = "\\maketitle\n\\textit{Note.} A remark.\n\n\\textit{Remark.} Another.\n\n" + filler(40)
    (section,) = sections_of(document(two))
    assert section.title == "(the paper has no section headings)"
    assert section.text.startswith("\\textit{Note.} A remark.")


def test_italics_without_a_mark_are_no_title():
    emphasis = "\n\n".join(f"\\textit{{Very}} important, point {n}." for n in range(4))
    (section,) = sections_of(document("\\maketitle\n" + emphasis))
    assert section.title == "(the paper has no section headings)"


def test_a_long_passage_in_italics_is_no_title():
    # A sentence set in italics ends with a full stop as well. A title is short.
    passage = "\\textit{" + filler(20) + ".} And on.\n\n"
    (section,) = sections_of(document("\\maketitle\n" + passage * 4))
    assert section.title == "(the paper has no section headings)"


def test_inside_a_paragraph_only_a_dash_sets_a_title_off():
    # A line of the source can begin in italics in the middle of a sentence. A title at
    # the head of such a line, behind a figure for one, is told by its dash.
    body = (
        LETTER
        + "It was shown by Somebody\n\\textit{et al.} in another way.\n"
        + "\\textit{Discussion}---What it means.\n"
    )
    sections = sections_of(document(body))
    assert [s.title for s in sections] == ["Introduction", "Method", "Results", "Discussion"]
    assert sections[2].text == (
        "What came out.\nIt was shown by Somebody\n\\textit{et al.} in another way."
    )


def test_titles_run_into_paragraphs_under_a_section_are_not_cut_at():
    # There they are a level below the heading, like anything below a subsection.
    body = "\\section{One}\n" + LETTER.removeprefix("\\maketitle\n") + "\\paragraph{More} So on."
    (section,) = sections_of(document(body))
    assert section.section_id == "1"
    assert "\\textit{Method.}---" in section.text and "\\paragraph{More}" in section.text


def test_text_in_front_of_the_first_title_is_section_zero():
    lead = "An opening without a title. " + filler(60)
    sections = sections_of(
        document(LETTER.replace("\\maketitle\n", "\\maketitle\n" + lead + "\n\n"))
    )
    assert [(s.section_id, s.title) for s in sections[:2]] == [
        ("0", "(text before the first section)"),
        ("u1", "Introduction"),
    ]
    assert sections[0].text == lead
    # A known limit of text under no heading: a few words are taken for commands. Before
    # parser 5 such a letter was one section, and they were in it.
    few = sections_of(document(LETTER.replace("\\maketitle\n", "\\maketitle\nA few words.\n\n")))
    assert [s.section_id for s in few] == ["u1", "u2", "u3"]
    assert "A few words." not in " ".join(s.text for s in few)


def test_the_paragraph_command_divides_text_without_headings_too():
    # LaTeX's own command for a title that is run in. One is enough, and its title stays
    # as typed, like the title of a \section.
    body = (
        "\\maketitle\n\\paragraph{Introduction.} Why.\n\\paragraph*{Model} What.\n"
        "\\begin{acknowledgments}\nThanks.\n\\end{acknowledgments}\n"
        "\\paragraph{Late} Behind another mark, and so under it."
    )
    assert [(s.section_id, s.title, s.text) for s in sections_of(document(body))] == [
        ("u1", "Introduction.", "Why."),
        ("u2", "Model", "What."),
        (
            "u3",
            "Acknowledgments",
            "Thanks.\n\\end{acknowledgments}\n\\paragraph{Late} Behind another mark, and so under it.",
        ),
    ]


def test_a_letter_with_headings_in_its_end_matter_only_is_divided_in_front_of_them():
    # It used to come back as "text before the first section" and the sections behind it.
    body = (
        LETTER
        + "\\begin{acknowledgments}\nThanks.\n\\end{acknowledgments}\n"
        + REFERENCES
        + "\\appendix\n\\section{Details}\nMore."
    )
    assert [(s.section_id, s.title) for s in sections_of(document(body))] == [
        ("u1", "Introduction"),
        ("u2", "Method"),
        ("u3", "Results"),
        ("u4", "Acknowledgments"),
        ("A", "Details"),
    ]


def test_a_second_maketitle_does_not_make_the_paper_a_title_block():
    # Supplemental material with a title of its own, in the file of the paper. The last
    # \maketitle before the first heading used to end the title block, and so the letter
    # in front of it was left out without a word.
    letter = "The letter. " + filler(60)
    body = (
        "\\title{T}\n\\begin{abstract}\nShort.\n\\end{abstract}\n\\maketitle\n"
        + letter
        + "\n\\clearpage\n\\title{Supplemental material}\n\\maketitle\n\\section{Details}\nMore."
    )
    first, second = sections_of(document(body))
    assert (first.section_id, first.title) == ("0", "(text before the first section)")
    assert first.text.startswith(letter)
    assert (second.section_id, second.text) == ("1", "More.")
    # An abstract can stand behind \maketitle as well: the later of the two ends the block.
    other = "\\maketitle\n\\begin{abstract}\nShort.\n\\end{abstract}\n" + letter
    assert sections_of(document(other + "\n\\section{One}\nMore."))[0].text == letter


def test_in_random_papers_with_these_places_every_piece_of_text_lies_in_a_section():
    # The test of random papers above, with the places of parser 5 among the commands.
    # The first piece after \appendix is long, as it is there: what stands under no
    # heading has to be text enough to be kept. Behind a list of references that does
    # not hold: a short piece there stays in the section in front of the list.
    rng = random.Random(5)
    commands = [
        "\\section{S}",
        "\\subsection{S}",
        "\\appendix",
        "\\begin{acknowledgments}",
        "\\acknowledgements",
        REFERENCES.strip(),
        "\\bibliography{refs}",
        "\\paragraph{P}",
        "\n\\textit{Title.}---",
        "\n\\emph{Title}: ",
    ]
    cut_at_titles = behind_lists = 0
    for _ in range(400):
        lines, named = ["\\maketitle", "PIECE0 " + filler(200)], ["PIECE0"]
        under_appendix = False  # no piece has followed the last \appendix yet
        # Every third paper is a letter: it begins with paragraphs under titles in italics.
        titled = rng.randint(3, 5) if rng.random() < 0.33 else 0
        for number in range(1, rng.randint(2, 12) + titled):
            command = commands[-rng.randint(1, 2)] if number <= titled else rng.choice(commands)
            lines.append(command)
            under_appendix = under_appendix or command == "\\appendix"
            if rng.random() < 0.8:
                long = under_appendix or rng.random() < 0.5
                lines.append(f"PIECE{number} " + filler(60 if long else 3))
                named.append(f"PIECE{number}")
                under_appendix = False
        sections = sections_of(document("\n".join(lines)))
        assert check(sections)[0] is True, lines
        found = " ".join(section.text for section in sections if section.level == 1).split()
        assert [name for name in named if name not in found] == [], lines
        cut_at_titles += any(section.title == "Title" for section in sections)
        behind_lists += any(section.title == AFTER_REFERENCES for section in sections)
    # Both kinds of places came up in papers enough for the test to say something.
    assert cut_at_titles > 50 and behind_lists > 50


def test_only_the_first_document_of_a_download_is_read():
    # A known limit (the head of arxiv_latex.py). arXiv typesets every file that its
    # list names as "toplevel", one after the other: a paper and its supplemental
    # material. The second is not read, and nothing in the result shows it.
    listed = (
        '{"sources": [{"usage": "toplevel", "filename": "paper.tex"},'
        ' {"usage": "toplevel", "filename": "supplement.tex"}]}'
    )
    files = {
        "paper.tex": document("\\section{One}\nPAPER " + filler(300)),
        "supplement.tex": document("\\section{More}\nSUPPLEMENT " + filler(300)),
        "00README.json": listed,
    }
    sections = parse_source(tar_gz({name: text.encode() for name, text in files.items()}))
    assert [section.title for section in sections] == ["One"]
    assert "SUPPLEMENT" not in sections[0].text


def test_title_with_an_unclosed_brace_ends_at_the_line_end():
    body = "\\section{Broken title\nText after.\n\\section{Fine}\nMore."
    titles = [section.title for section in sections_of(document(body))]
    assert titles == ["Broken title", "Fine"]


def test_short_title_with_a_bracket_inside_braces_is_still_a_heading():
    body = "\\section[Short {[x]} one]{Long $[a,b]$ title}\nFirst.\n\\section[Plain]{Second}\nMore."
    assert [(s.section_id, s.title) for s in sections_of(document(body))] == [
        ("1", "Long $[a,b]$ title"),
        ("2", "Second"),
    ]


# --- \input ----------------------------------------------------------------------------


def test_input_is_replaced_by_a_file_of_the_paper_with_or_without_suffix():
    files = {"intro.tex": "From intro. % comment", "sub/more.tex": "From more."}
    text = expand_inputs("A \\input{intro} B \\include{sub/more.tex} C", files)
    assert text == "A From intro.  B From more. C"


def test_input_of_a_file_that_did_not_come_with_the_paper_stays_as_written():
    assert expand_inputs("\\input{colordvi.tex}", {}) == "\\input{colordvi.tex}"


def test_a_file_that_inputs_itself_does_not_loop_forever():
    text = expand_inputs("\\input{loop}", {"loop.tex": "x \\input{loop}"})
    assert text.count("x") == 10  # stops at the depth limit


def test_sections_are_found_inside_input_files():
    main = document("\\input{sec1}\n\\input{sec2}")
    extra = {"sec1.tex": "\\section{One}\nFirst.", "sec2.tex": "\\section{Two}\nSecond."}
    assert [(s.section_id, s.text) for s in sections_of(main, extra)] == [
        ("1", "First."),
        ("2", "Second."),
    ]


def test_input_without_braces_is_followed_too():
    main = document("\\input sec1\n\\input sec2.tex\nAfter \\inputencoding{utf8}.")
    extra = {"sec1.tex": "\\section{One}\nFirst.", "sec2.tex": "\\section{Two}\nSecond."}
    assert [(s.section_id, s.text) for s in sections_of(main, extra)] == [
        ("1", "First."),
        ("2", "Second.\nAfter \\inputencoding{utf8}."),
    ]


def test_names_are_also_looked_up_beside_a_main_file_in_a_folder():
    files = {
        "paper/main.tex": document("\\input{sec/intro}\n\\section{Two}\nSecond."),
        "paper/sec/intro.tex": "\\section{One}\nFirst.",
    }
    assert [(s.section_id, s.text) for s in split(files, "paper/main.tex")] == [
        ("1", "First."),
        ("2", "Second."),
    ]


def test_a_file_with_its_own_document_adds_only_what_is_inside_it():
    # The subfiles package: every part can be compiled alone, so every part ends the document.
    part = (
        "\\documentclass[main]{subfiles}\n\\begin{document}\n\\section{%s}\n%s\n\\end{document}\n"
        "Kept below the end of the part. Never typeset.\n"
    )
    main = document("\\subfile{one}\n\\subfileinclude{two}\n\\section{Three}\nThird.")
    extra = {"one.tex": part % ("One", "First."), "two.tex": part % ("Two", "Second.")}
    assert [(s.section_id, s.title, s.text) for s in sections_of(main, extra)] == [
        ("1", "One", "First."),
        ("2", "Two", "Second."),
        ("3", "Three", "Third."),
    ]


# Where the document begins and ends. test_against_tex.py runs the same shapes through TeX.


def test_a_file_that_is_read_in_can_end_the_document():
    # TeX stops at the first \end{document} it meets. What the main file says after
    # that point, and what the file itself says below it, is never typeset.
    main = document(
        "\\section{One}\nFirst.\n\\input{tail}\nNotes to self.\n\\section{Ghost}\nNever typeset."
    )
    extra = {"tail.tex": "\\section{Two}\nLast words.\n\\end{document}\nKept below the end.\n"}
    assert [(s.section_id, s.title, s.text) for s in sections_of(main, extra)] == [
        ("1", "One", "First."),
        ("2", "Two", "Last words."),
    ]


def test_a_file_that_is_read_in_can_begin_the_document():
    main = "\\input{header}\n\\section{One}\nFirst.\n\\section{Two}\nSecond.\n\\end{document}\n"
    extra = {"header.tex": "\\documentclass{article}\n\\title{T}\n\\begin{document}\n\\maketitle\n"}
    assert [(s.section_id, s.text) for s in sections_of(main, extra)] == [
        ("1", "First."),
        ("2", "Second."),
    ]


def test_a_main_file_can_read_the_whole_paper_from_another_file():
    paper = document("\\section{One}\nFirst.\n\\section{Two}\nSecond.") + "Kept below the end.\n"
    sections = sections_of("\\input{paper}\n", {"paper.tex": paper})
    assert [(s.section_id, s.text) for s in sections] == [("1", "First."), ("2", "Second.")]


def test_no_document_in_the_main_file_or_in_what_it_reads_is_a_parse_error():
    with pytest.raises(SourceError) as caught:
        sections_of("\\input{macros}\nNo document.", {"macros.tex": "\\newcommand{\\x}{y}"})
    assert caught.value.kind is ErrorKind.PARSE_ERROR
    assert "no \\begin{document}" in caught.value.detail


@pytest.mark.parametrize(
    ("line", "named"),
    [
        ("\\input{sec2}", "sec2"),
        ("\\input sec2", "sec2"),
        ("\\input{parts/sec2.tex}", "parts/sec2.tex"),
        ("\\include{sec2}", "sec2"),
        ("\\subfile{sec2}", "sec2"),
    ],
)
def test_a_body_that_names_a_file_the_download_lacks_is_a_parse_error(line, named):
    # Without this the paper would come back with a section missing and nothing to show it.
    main = document("\\section{One}\nFirst.\n" + line + "\n\\section{Three}\nThird.")
    with pytest.raises(SourceError) as caught:
        sections_of(main)
    assert caught.value.kind is ErrorKind.PARSE_ERROR
    assert not isinstance(caught.value, NotASource)  # a real source: the download is kept
    assert caught.value.detail.endswith(": " + named)


@pytest.mark.parametrize(
    ("line", "named"),
    [
        ("\\import{parts/}{sec2}", "parts/sec2 (\\import)"),
        ("\\subimport*{parts}{sec2.tex}", "parts/sec2.tex (\\subimport)"),
        ("\\inputfrom{parts/}{sec2}", "parts/sec2 (\\inputfrom)"),
        ("\\subinputfrom {}{sec2}", "sec2 (\\subinputfrom)"),
        ("\\includefrom{parts/}{sec2}", "parts/sec2 (\\includefrom)"),
        ("\\subincludefrom{parts/}{sec2}", "parts/sec2 (\\subincludefrom)"),
        ("\\InputIfFileExists{sec2}{}{}", "sec2 (\\InputIfFileExists)"),
    ],
)
def test_a_body_that_reads_a_file_in_a_way_that_is_not_followed_is_a_parse_error(line, named):
    # The file is in the download, and still its section would be left out without a sign.
    main = document("\\section{One}\nFirst.\n" + line + "\n\\section{Three}\nThird.")
    extra = {"sec2.tex": "\\section{Two}\nSecond.", "parts/sec2.tex": "\\section{Two}\nSecond."}
    with pytest.raises(SourceError) as caught:
        sections_of(main, extra)
    assert caught.value.kind is ErrorKind.PARSE_ERROR
    assert not isinstance(caught.value, NotASource)  # a real source: the download is kept
    assert caught.value.detail.endswith(": " + named)


def test_commands_that_are_not_followed_do_no_harm_where_the_file_holds_no_text():
    body = (
        "\\section{One}\nFirst. \\import{figures/}{drawing.pdf_tex} \\subimport{figures/}{plot.pgf}\n"
        "\\InputIfFileExists{paper.aux}{}{} \\important{a}{b} \\inputencoding{utf8}"
    )
    (section,) = sections_of(document(body))
    assert section.text == body.removeprefix("\\section{One}\n")


def test_every_file_that_could_not_be_read_is_named_once():
    body = "\\input{a}\n\\import{p/}{b}\n\\input{a}\n\\include{c}\n\\import{p/}{b}"
    with pytest.raises(SourceError) as caught:
        sections_of(document(body))
    assert caught.value.detail == (
        "text is missing, 3 file(s) could not be read: a, c, p/b (\\import)"
    )


def test_missing_files_that_hold_no_running_text_do_not_stop_the_split():
    body = (
        "\\section{One}\nFirst. \\input{plot.pstex_t} \\input{fig.tikz} \\input epsf.sty\n"
        "\\includegraphics{sec2} \\input{paper.bbl}"
    )
    preamble = "\\documentclass{article}\n\\input{mymacros}\n\\begin{document}\n"
    (section,) = sections_of(preamble + body + "\n\\end{document}")
    assert section.text == body.removeprefix("\\section{One}\n")


# --- unpack ----------------------------------------------------------------------------


def test_every_packaging_of_the_same_file_unpacks_to_the_same_text():
    tex = SAMPLE_LATEX.encode()
    as_tar = unpack(tar_gz({"paper.tex": tex}))
    assert as_tar == {"paper.tex": SAMPLE_LATEX}
    assert (
        unpack(plain_tar({"paper.tex": tex})) == as_tar
    )  # gzip already removed by the HTTP client
    assert unpack(gzip.compress(tex)) == {"main.tex": SAMPLE_LATEX}  # a paper with a single file
    assert unpack(tex) == {"main.tex": SAMPLE_LATEX}


def test_only_text_files_of_reasonable_size_are_kept():
    files = unpack(
        tar_gz(
            {
                "./paper.tex": b"\\begin{document}x\\end{document}",
                "00README.json": b"{}",
                "Figures/plot.png": b"\x89PNG....",
                "refs.bib": b"@article{a}",
                "huge.tex": b"x" * 5_000_001,
            }
        )
    )
    assert sorted(files) == ["00README.json", "paper.tex"]


@pytest.mark.parametrize(
    "data", [b"%PDF-1.7 ...", gzip.compress(b"%PDF-1.7 ..."), b"%!PS-Adobe-3.0", b"\xf7\x02 dvi"]
)
def test_a_download_without_tex_source_is_no_full_text(data):
    with pytest.raises(SourceError) as caught:
        unpack(data)
    assert caught.value.kind is ErrorKind.NO_FULL_TEXT


def test_broken_gzip_is_a_parse_error():
    with pytest.raises(NotASource) as caught:
        unpack(gzip.compress(b"some text")[:-6])
    assert caught.value.kind is ErrorKind.PARSE_ERROR


def test_gzip_with_a_damaged_byte_inside_is_not_a_source():
    # A good header, then a block of a kind that does not exist. That raises
    # zlib.error, which is neither an OSError nor an EOFError.
    damaged = b"\x1f\x8b\x08\x00\x00\x00\x00\x00\x00\x03" + b"\x07" + bytes(20)
    with pytest.raises(zlib.error):
        gzip.decompress(damaged)
    with pytest.raises(NotASource) as caught:
        unpack(damaged)
    assert "not valid gzip" in caught.value.detail


def test_an_archive_that_breaks_off_is_not_a_source():
    cut = plain_tar({"paper.tex": SAMPLE_LATEX.encode()})[:700]  # inside the text of its first file
    for data in (cut, gzip.compress(cut)):
        with pytest.raises(NotASource) as caught:
            unpack(data)
        assert caught.value.kind is ErrorKind.PARSE_ERROR
        assert "damaged archive" in caught.value.detail


@pytest.mark.parametrize(
    "data",
    [
        b"",
        b" \r\n\t",
        b"<!DOCTYPE html>\n<html><body>Rate exceeded.</body></html>",
        b"\xef\xbb\xbf\n <HTML><head>",
        b'<?xml version="1.0"?><error>no</error>',
    ],
)
def test_an_empty_answer_and_a_web_page_are_not_a_source(data):
    for packed in (data, gzip.compress(data)):
        with pytest.raises(NotASource):
            unpack(packed)


def test_a_single_file_that_is_not_latex_is_still_taken_for_the_source():
    # Plain TeX, or the notice a withdrawn paper leaves. That it has no \begin{document}
    # is found later, and it is no reason to ask arXiv for the same bytes again.
    plain = b"\\input harvmac\n\\Title{HUTP-91/A001}{A paper in plain TeX}\n<not a tag>\n\\bye\n"
    assert unpack(plain) == {"main.tex": plain.decode()}
    with pytest.raises(SourceError) as caught:
        parse_source(gzip.compress(plain))
    assert caught.value.kind is ErrorKind.PARSE_ERROR
    assert not isinstance(caught.value, NotASource)


def test_latin1_bytes_and_windows_line_ends_are_read():
    files = unpack("caf\xe9\r\nline two\r".encode("latin-1"))
    assert files == {"main.tex": "caf\xe9\nline two\n"}


# --- main file -------------------------------------------------------------------------


def test_the_file_that_arxiv_marks_as_toplevel_is_the_main_file():
    manifest = '{"sources": [{"usage": "ignore", "filename": "a.tex"}, {"usage": "toplevel", "filename": "b.tex"}]}'
    files = {"a.tex": document("x" * 500), "b.tex": document("y"), "00README.json": manifest}
    assert find_main(files) == "b.tex"


def test_without_a_list_the_file_with_documentclass_wins_then_the_longest():
    files = {
        "fragment.tex": "\\begin{document}" + "long " * 500,  # no \documentclass
        "short.tex": document("short"),
        "paper.tex": document("the paper " * 50),
        "notes.tex": "% \\documentclass \\begin{document} only in a comment",
    }
    assert find_main(files) == "paper.tex"
    assert find_main({"00README.json": "not json", **files}) == "paper.tex"
    for unusable in ('{"sources": null}', "[1]", '{"sources": [3]}', "null"):
        assert find_main({"00README.json": unusable, **files}) == "paper.tex"


def test_no_file_with_a_document_is_a_parse_error():
    with pytest.raises(SourceError) as caught:
        find_main({"macros.tex": "\\newcommand{\\x}{y}"})
    assert caught.value.kind is ErrorKind.PARSE_ERROR
    assert not isinstance(caught.value, NotASource)  # a real source: the download is kept


def test_a_part_for_the_subfiles_package_is_never_the_main_file():
    # Every part has \documentclass and \begin{document}, and a part can be far
    # longer than the main file, which may hold little more than \subfile lines.
    part = (
        "\\documentclass[main]{subfiles}\n\\begin{document}\n"
        + "A long part. " * 500
        + "\n\\end{document}\n"
    )
    files = {
        "one.tex": part,
        "sec/two.tex": part.replace("[main]", " [../main] "),
        "main.tex": document("\\subfile{one}\n\\subfile{sec/two}"),
    }
    assert find_main(files) == "main.tex"


def test_not_a_source_survives_pickle():
    clone = pickle.loads(pickle.dumps(NotASource(ErrorKind.PARSE_ERROR, "no document")))
    assert type(clone) is NotASource
    assert (clone.kind, clone.detail) == (ErrorKind.PARSE_ERROR, "no document")


# --- check and the whole path ------------------------------------------------------------


def test_check_reports_ok_and_a_message():
    sections = sections_of(SAMPLE_LATEX)
    ok, message = check(sections)
    assert ok is True
    assert message.startswith("8 sections, ")
    assert check(()) == (False, "no sections")


def test_a_subsection_outside_the_section_before_it_is_not_trusted():
    # The text of a paper is the text of its sections, which hold their subsections.
    # A subsection that lies in none would be missing from the paper read as a whole.
    lead = "Lead.\n"
    whole = Section("1", "One", 1, lead + "\\subsection{Part}\nPart text. " + filler(300))
    part = Section("1.1", "Part", 2, "Part text. " + filler(300), heading_at=len(lead))
    assert check((whole, part))[0] is True

    stray = Section("1.1", "Part", 2, "Text that section 1 does not hold.", heading_at=len(lead))
    assert check((whole, stray)) == (False, "subsection 1.1 is not part of the section before it")
    assert check((part, whole)) == (False, "subsection 1.1 is not part of the section before it")

    # Where its heading begins is checked too: the flat layout puts a marker there.
    for elsewhere in (None, 0, len(lead) + 1):
        moved = Section("1.1", "Part", 2, part.text, heading_at=elsewhere)
        assert check((whole, moved)) == (
            False,
            "the heading of subsection 1.1 is not where it should be",
        )


def test_a_subsection_says_where_its_heading_begins_in_the_text_of_its_section():
    # The text of a section is tidied: line breaks at its start go, long runs of them
    # shrink. The place of a heading is counted in the text as it is after that.
    body = (
        "\\section{One}\n\n\n\nFirst.\n\n\n\n\\subsection{Part}\nPart."
        "\n\n\n\n\n\\subsection*{More}\nMore."
    )
    one, part, more = sections_of(document(body))
    assert one.text == "First.\n\n\\subsection{Part}\nPart.\n\n\\subsection*{More}\nMore."
    assert one.heading_at is None  # a section holds no place: its text begins after its heading
    assert one.text[part.heading_at :].startswith("\\subsection{Part}")
    assert one.text[more.heading_at :].startswith("\\subsection*{More}")

    holder = None
    for section in sections_of(SAMPLE_LATEX):
        if section.level == 1:
            holder = section
        else:
            assert holder.text.startswith("\\subsection", section.heading_at), section.section_id


def test_a_paper_whose_text_stands_under_no_section_heading_is_read_whole():
    body = "\\subsection{First}\nONE " + filler(200) + "\n\\appendix\nTWO " + filler(200)
    sections = parse_source(document(body).encode())
    assert [s.section_id for s in sections] == ["0", "0.1", "u1"]
    whole = " ".join(s.text for s in sections if s.level == 1)
    assert "ONE" in whole and "TWO" in whole


def test_too_little_text_is_a_parse_error():
    with pytest.raises(SourceError) as caught:
        parse_source(document("\\section{One}\nAlmost nothing.").encode())
    assert caught.value.kind is ErrorKind.PARSE_ERROR
    assert "characters" in caught.value.detail


def test_parse_source_runs_the_whole_path_on_an_archive():
    sections = parse_source(tar_gz({"paper.tex": SAMPLE_LATEX.encode(), "fig.png": b"\x89PNG"}))
    assert [section.section_id for section in sections] == [
        "1",
        "2",
        "2.1",
        "2.u1",
        "2.2",
        "u1",
        "A",
        "A.1",
    ]
