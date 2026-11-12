"""Section splitting on invented LaTeX. No network."""

import gzip
import pickle

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
from hepph_paper_miner.sources.base import ErrorKind, SourceError


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
    )
    main = document("\\subfile{one}\n\\subfile{two}\n\\section{Three}\nThird.")
    extra = {"one.tex": part % ("One", "First."), "two.tex": part % ("Two", "Second.")}
    assert [(s.section_id, s.title, s.text) for s in sections_of(main, extra)] == [
        ("1", "One", "First."),
        ("2", "Two", "Second."),
        ("3", "Three", "Third."),
    ]


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


def test_no_file_with_a_document_is_a_parse_error():
    with pytest.raises(NotASource) as caught:
        find_main({"macros.tex": "\\newcommand{\\x}{y}"})
    assert caught.value.kind is ErrorKind.PARSE_ERROR


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
