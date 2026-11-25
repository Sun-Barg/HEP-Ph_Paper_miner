"""The section parser against TeX itself. Not run by default:  uv run pytest -m tex

Needs pdflatex on the PATH. A case that uses a package is skipped when kpsewhich
does not find it (in TeX Live, subfiles and import come with texlive-latex-extra,
epsf with texlive-plain-generic).

Each case is a small invented paper in which every piece of text announces itself:
\\typeout{SEEN-A} writes "SEEN-A" to the terminal when TeX reads that piece and
does nothing in a piece that TeX skips. The pieces TeX announced are compared with
the pieces found in what the parser returns, once with arXiv's list of the files in
a download (00README.json) and once without it. A case with several documents names
them: arXiv typesets every one, so TeX is run on each, and the list marks each as it
does ("toplevel").

What a case expects of the parser:

    SAME    it returns exactly the pieces that TeX read
    TURNED  it reports PARSE_ERROR although TeX reads the paper: a known limit
    WRONG   it returns other pieces than TeX read, and nothing shows it: a known
            limit. On the day one of these is put right this test fails; then
            change the expectation here and the list of limits in arxiv_latex.py.
"""

import json
import re
import shutil
import subprocess

import pytest
from conftest import filler, tar_gz

from hepph_paper_miner.sources.arxiv_latex import parse_source
from hepph_paper_miner.sources.base import ErrorKind, SourceError

pytestmark = [
    pytest.mark.tex,
    pytest.mark.skipif(shutil.which("pdflatex") is None, reason="pdflatex is not on the PATH"),
]

SAME, TURNED, WRONG = "same", "turned away", "wrong"

PRE = "\\documentclass{article}\n"
BEGIN = "\\begin{document}\n"
END = "\\end{document}\n"
FILL = filler(300)  # enough text to pass the parser's minimum length
PART = "\\documentclass[main]{subfiles}\n"

_PLACE = re.compile(r"<([A-Z])>")  # <A> in a case stands for \typeout{SEEN-A}
_SEEN = re.compile(r"SEEN-([A-Z])")


def case(label, files, with_list, without_list, needs=(), documents=("main.tex",)):
    return pytest.param(files, with_list, without_list, needs, documents, id=label)


CASES = [
    # --- where the document begins and ends ------------------------------------------
    case(
        "an input file ends the document and the main file goes on",
        {
            "main.tex": PRE
            + BEGIN
            + f"\\section{{One}}\n<A> {FILL}\n\\input{{tail}}\n<C> notes to self\n"
            + "\\section{Ghost}\n<D>\n"
            + END,
            "tail.tex": "\\section{Two}\n<B> last words\n\\end{document}\n<E> below the end\n",
        },
        SAME,
        SAME,
    ),
    case(
        "an input file begins the document",
        {
            "main.tex": f"\\input{{header}}\n\\section{{One}}\n<A> {FILL}\n\\section{{Two}}\n<B>\n"
            + END,
            "header.tex": PRE + "\\title{T}\n" + BEGIN,
        },
        SAME,
        TURNED,  # without the list, header.tex is taken for the main file: it has no text
    ),
    case(
        "the main file only reads the paper from another file",
        {
            "main.tex": "\\input{paper}\n",
            "paper.tex": PRE
            + BEGIN
            + f"\\section{{One}}\n<A> {FILL}\n\\section{{Two}}\n<B>\n"
            + END
            + "<C> below the end\n",
        },
        SAME,
        SAME,
    ),
    case(
        "subfiles, and the text below the end of a part",
        {
            "main.tex": PRE
            + "\\usepackage{subfiles}\n"
            + BEGIN
            + f"\\subfile{{one}}\n\\subfileinclude{{two}}\n\\section{{Three}}\n<C> {FILL} {FILL}\n"
            + END,
            "one.tex": PART + BEGIN + f"\\section{{One}}\n<A> {FILL}\n" + END + "<X> below\n",
            "two.tex": PART + BEGIN + "\\section{Two}\n<B>\n" + END,
        },
        SAME,
        SAME,
        needs=("subfiles.cls",),
    ),
    case(
        "subfiles, with a part that is longer than the main file",
        {
            "main.tex": PRE
            + "\\usepackage{subfiles}\n"
            + BEGIN
            + "\\subfile{one}\n\\subfile{two}\n\\section{Three}\n<C>\n"
            + END,
            "one.tex": PART + BEGIN + f"\\section{{One}}\n<A> {FILL} {FILL}\n" + END,
            "two.tex": PART + BEGIN + f"\\section{{Two}}\n<B> {FILL}\n" + END,
        },
        SAME,
        SAME,
        needs=("subfiles.cls",),
    ),
    case(
        "two documents in one download, the paper being the shorter",
        {
            "main.tex": PRE
            + BEGIN
            + f"\\section{{One}}\n<A> {FILL}\n\\section{{Two}}\n<B>\n"
            + END,
            "supplement.tex": PRE + BEGIN + f"\\section{{More}}\n<S> {FILL} {FILL}\n" + END,
        },
        SAME,
        WRONG,  # without the list the longest file is taken for the paper
    ),
    # --- commands that read a file and are not followed --------------------------------
    case(
        "import and subimport",
        {
            "main.tex": PRE
            + "\\usepackage{import}\n"
            + BEGIN
            + f"\\section{{One}}\n<A> {FILL}\n\\import{{parts/}}{{two}}\n"
            + "\\subimport{parts/}{four}\n\\section{Five}\n<E>\n"
            + END,
            "parts/two.tex": "\\section{Two}\n<B>\n\\input{three}\n",
            "parts/three.tex": "\\section{Three}\n<C>\n",
            "parts/four.tex": "\\section{Four}\n<D>\n",
        },
        TURNED,
        TURNED,
        needs=("import.sty",),
    ),
    case(
        "inputfrom, includefrom, a star, a folder without its slash",
        {
            "main.tex": PRE
            + "\\usepackage{import}\n"
            + BEGIN
            + f"\\section{{One}}\n<A> {FILL}\n\\inputfrom{{parts/}}{{two}}\n"
            + "\\includefrom{parts/}{three}\n\\import*{parts}{four}\n"
            + END,
            "parts/two.tex": "\\section{Two}\n<B>\n",
            "parts/three.tex": "\\section{Three}\n<C>\n",
            "parts/four.tex": "\\section{Four}\n<D>\n",
        },
        TURNED,
        TURNED,
        needs=("import.sty",),
    ),
    case(
        "InputIfFileExists, for a file that is there and one that is not",
        {
            "main.tex": PRE
            + BEGIN
            + f"\\section{{One}}\n<A> {FILL}\n\\InputIfFileExists{{two}}{{<Y>}}{{<N>}}\n"
            + "\\InputIfFileExists{nothere}{<P>}{<Q>}\n"
            + END,
            "two.tex": "\\section{Two}\n<B>\n",
        },
        TURNED,
        TURNED,
    ),
    case(
        "a part in a folder reads a file that lies beside it",
        {
            "main.tex": PRE
            + "\\usepackage{subfiles}\n"
            + BEGIN
            + f"\\section{{One}}\n<A> {FILL} {FILL}\n\\subfile{{parts/two}}\n"
            + END,
            "parts/two.tex": "\\documentclass[../main]{subfiles}\n"
            + BEGIN
            + "\\section{Two}\n<B>\n\\input{three}\n"
            + END,
            "parts/three.tex": "\\section{Three}\n<C>\n",
        },
        TURNED,  # "three" is looked for beside the main file only
        TURNED,
        needs=("subfiles.cls",),
    ),
    case(
        "a macro of the author's own reads the files",
        {
            "main.tex": PRE
            + "\\newcommand{\\readpart}[1]{\\input{parts/#1}}\n"
            + BEGIN
            + f"\\section{{One}}\n<A> {FILL}\n\\readpart{{two}}\n\\readpart{{three}}\n"
            + END,
            "parts/two.tex": "\\section{Two}\n<B>\n",
            "parts/three.tex": "\\section{Three}\n<C>\n",
        },
        WRONG,
        WRONG,
    ),
    # --- a file of the TeX installation, read by a bare name -----------------------------
    case(
        "input epsf inside the body",
        {
            "main.tex": PRE
            + BEGIN
            + f"\\input epsf\n\\section{{One}}\n<A> {FILL}\n\\section{{Two}}\n<B>\n"
            + END,
        },
        TURNED,
        TURNED,
        needs=("epsf.tex",),
    ),
    case(
        "input epsf in the preamble, and a name with a suffix inside the body",
        {
            "main.tex": PRE
            + "\\input epsf\n"
            + BEGIN
            + f"\\input{{epsf.sty}}\n\\section{{One}}\n<A> {FILL}\n\\section{{Two}}\n<B>\n"
            + END,
        },
        SAME,
        SAME,
        needs=("epsf.tex", "epsf.sty"),
    ),
    # --- text that stands under no heading of its own ---------------------------------------
    case(
        "text between appendix and the section after it",
        {
            "main.tex": PRE
            + BEGIN
            + f"\\section{{One}}\n<A> {FILL}\n\\appendix\n<B> {FILL}\n\\section{{Two}}\n<C>\n"
            + END,
        },
        SAME,
        SAME,
    ),
    case(
        "no heading at all, and text after appendix",
        {"main.tex": PRE + BEGIN + f"<A> {FILL}\n\\appendix\n<B> {FILL}\n" + END},
        SAME,
        SAME,
    ),
    case(
        "subsections before the first section and after appendix",
        {
            "main.tex": PRE
            + BEGIN
            + f"\\subsection{{Zero}}\n<A> {FILL}\n\\section{{One}}\n<B>\n"
            + "\\appendix\n\\subsection{Last}\n<C>\n"
            + END,
        },
        SAME,
        SAME,
    ),
    case(
        "subsections and no section",
        {
            "main.tex": PRE
            + BEGIN
            + f"\\subsection{{One}}\n<A> {FILL}\n\\subsection*{{Two}}\n<B>\n"
            + END,
        },
        SAME,
        SAME,
    ),
    case(
        "a few words under no heading",
        {
            "main.tex": PRE
            + BEGIN
            + f"<A> a few words\n\\section{{One}}\n<B> {FILL}\n"
            + "\\appendix\n<C> a few more\n\\section{Two}\n<D>\n"
            + END,
        },
        WRONG,  # short text under no heading is taken for commands and left out
        WRONG,
    ),
    # --- a section that begins where no \section stands (parser 5) ---------------------------
    case(
        "a second maketitle further down",
        {
            "main.tex": PRE
            + "\\title{T}\\author{A}\n"
            + BEGIN
            + f"\\maketitle\n<A> {FILL}\n\\title{{More}}\n\\maketitle\n"
            + f"\\section{{One}}\n<B> {FILL}\n"
            + END,
        },
        SAME,  # until parser 4, the last \maketitle ended the title block: <A> was left out
        SAME,
    ),
    case(
        "the acknowledgements of a class, and text behind the list of references",
        {
            "main.tex": PRE
            + "\\newenvironment{acknowledgments}{\\section*{Acknowledgments}}{}\n"
            + BEGIN
            + f"\\section{{One}}\n<A> {FILL}\n"
            + "\\begin{acknowledgments}\n<B> thanks\n\\end{acknowledgments}\n"
            + "\\begin{thebibliography}{9}\n\\bibitem{a} Somebody.\n\\end{thebibliography}\n"
            + f"<C> {FILL}\n"
            + END,
        },
        SAME,
        SAME,
    ),
    case(
        "titles run into the paragraphs of a paper without headings",
        {
            "main.tex": PRE
            + BEGIN
            + f"\\textit{{First.}}---<A> {FILL}\n\n\\textit{{Second.}}---<B> more\n\n"
            + "\\emph{Third}: <C> more\n\\textit{Fourth}---<D> and more\n"
            + END,
        },
        SAME,
        SAME,
    ),
    case(
        "a few words in front of the first of such titles",
        {
            "main.tex": PRE
            + BEGIN
            + f"<A> a few words\n\n\\textit{{First.}}---<B> {FILL}\n\n"
            + "\\textit{Second.}---<C> more\n\n\\textit{Third.}---<D> more\n"
            + END,
        },
        WRONG,  # short text under no heading is taken for commands and left out
        WRONG,
    ),
    case(
        "a paper and its supplemental material as two documents",
        {
            "main.tex": PRE + BEGIN + f"\\section{{One}}\n<A> {FILL} {FILL}\n" + END,
            "supplement.tex": PRE + BEGIN + f"\\section{{More}}\n<B> {FILL}\n" + END,
        },
        WRONG,  # only the first document is read
        WRONG,
        documents=("main.tex", "supplement.tex"),
    ),
    # --- text that TeX skips ---------------------------------------------------------------
    case(
        "include with includeonly",
        {
            "main.tex": PRE
            + "\\includeonly{two}\n"
            + BEGIN
            + f"\\section{{One}}\n<A> {FILL}\n\\include{{two}}\n\\include{{three}}\n"
            + END,
            "two.tex": "\\section{Two}\n<B>\n",
            "three.tex": "\\section{Three}\n<C>\n",
        },
        WRONG,
        WRONG,
    ),
    case(
        "endinput in a file that is read",
        {
            "main.tex": PRE
            + BEGIN
            + f"\\section{{One}}\n<A> {FILL}\n\\input{{two}}\n\\section{{Three}}\n<C>\n"
            + END,
            "two.tex": "\\section{Two}\n<B>\n\\endinput\n<X> old text kept below\n",
        },
        WRONG,
        WRONG,
    ),
    case(
        "a branch that is not taken",
        {
            "main.tex": PRE
            + BEGIN
            + f"\\section{{One}}\n<A> {FILL}\n\\iftrue <B> \\else <X> \\fi\n"
            + END,
        },
        WRONG,
        WRONG,
    ),
]


def read_by_tex(files: dict[str, str], folder, documents=("main.tex",)) -> set[str]:
    """The pieces that TeX announces when it runs on each document: on main.tex alone, as a rule."""
    for name, text in files.items():
        path = folder / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8", newline="\n")
    seen: set[str] = set()
    for document in documents:
        run = subprocess.run(
            ["pdflatex", "-interaction=nonstopmode", "-halt-on-error", "-draftmode", document],
            cwd=folder,
            capture_output=True,
            text=True,
            errors="replace",
            timeout=300,
            check=False,  # a failure is reported below, with what TeX said
        )
        assert run.returncode == 0, "TeX stopped on this case:\n" + run.stdout[-1500:]
        seen |= set(_SEEN.findall(run.stdout))
    return seen


def found_by_parser(files: dict[str, str], with_list: bool, documents=("main.tex",)) -> set[str]:
    """The pieces in the sections that the parser returns for the same files as a download."""
    members = {name: text.encode() for name, text in files.items()}
    if with_list:
        listed = {"sources": [{"usage": "toplevel", "filename": name} for name in documents]}
        members["00README.json"] = json.dumps(listed).encode()
    sections = parse_source(tar_gz(members))
    return set(_SEEN.findall(" ".join(s.text for s in sections if s.level == 1)))


def installed(name: str) -> bool:
    """Whether TeX would find this file. True when that cannot be asked."""
    if shutil.which("kpsewhich") is None:
        return True
    found = subprocess.run(["kpsewhich", name], capture_output=True, check=False)
    return bool(found.stdout.strip())


@pytest.mark.parametrize(("files", "with_list", "without_list", "needs", "documents"), CASES)
def test_parser_returns_what_tex_reads(tmp_path, files, with_list, without_list, needs, documents):
    missing = [name for name in needs if not installed(name)]
    if missing:
        pytest.skip(f"not in this TeX installation: {', '.join(missing)}")
    files = {name: _PLACE.sub(r"\\typeout{SEEN-\1}", text) for name, text in files.items()}

    read = read_by_tex(files, tmp_path, documents)
    assert read, "TeX announced nothing: the case itself is broken"

    for listed, expected in ((True, with_list), (False, without_list)):
        where = "with the list" if listed else "without the list"
        try:
            found = found_by_parser(files, listed, documents)
        except SourceError as error:
            assert error.kind is ErrorKind.PARSE_ERROR
            assert expected == TURNED, f"{where}: turned away ({error.detail})"
            continue
        assert expected != TURNED, f"{where}: a result where PARSE_ERROR was expected"
        if expected == SAME:
            assert found == read, where
        else:
            assert found != read, f"{where}: no longer wrong, so this limit is gone"
