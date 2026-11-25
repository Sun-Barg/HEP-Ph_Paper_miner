"""From the bytes of an arXiv source download to a list of sections. No network.

    unpack      bytes            -> {file name: text}
    find_main   files            -> name of the file that holds \\begin{document}
    split       files, main name -> sections
    check       sections         -> (ok, message)

parse_source() runs the four in order. The parser reads LaTeX as text and never
runs TeX, so it follows \\input but not macros that authors define for themselves.

A section begins at \\section and \\subsection, and in three more places where a paper
has a division and no such command: at the acknowledgements a class sets, behind a list
of references that text follows, and at titles that are run into the paragraphs of text
without headings (split() says how each is told).

A split that lost text is worse than no split: the reader would take a part of the
paper for the whole. So where the parser can see that text is missing (a file named
by \\input that it could not find, a command that reads files in a way it does not
follow), it reports PARSE_ERROR instead of a result.

Known limits. tests/test_against_tex.py shows each of them by running TeX itself.

    Turned away with PARSE_ERROR although TeX reads them:
      - a paper that, inside its body, reads a file of the TeX installation by a
        bare name (\\input epsf). In the preamble this does no harm.
      - a paper that reads files with \\import, \\subimport or their relatives, or
        with \\InputIfFileExists.
      - a part for the subfiles package that lies in a folder and reads a file
        from beside itself: names are looked up beside the main file only.
      - without arXiv's list of the files: a paper whose \\begin{document} stands
        in an \\input file. That file is then taken for the main file.
    Read wrongly, and nothing shows it:
      - text in files that are read through a macro of the author's own is left out.
      - a download that holds several documents and comes without arXiv's list of
        its files: the longest file is taken for the paper.
      - a download in which arXiv's list names several files as "toplevel" (a paper
        and its supplemental material, each a document of its own): arXiv typesets
        them one after the other, and only the first is read here.
      - \\includeonly, \\endinput and \\if... are not obeyed, so text that TeX
        skips can end up in a section.
      - a few words that stand under no heading (in front of the first place where
        a section begins, or between \\appendix and the next such place) are taken
        for commands and left out.

Where a section begins without a \\section, the parser goes by what is typed, and TeX
is not asked. tests/test_latex.py shows these:

      - the acknowledgements of a class get a section of their own whether the class
        prints a heading over them (most do), runs the word into the paragraph or
        prints none (REVTeX with the option prl).
      - titles run into paragraphs are found where they are typed in italics and set
        off by a dash, a colon or a full stop, three or more of them, in text that
        stands under no heading. A paper that sets them in bold, numbers them by hand
        or sets them off in another way stays one section, like a paper that has none.
"""

from __future__ import annotations

import gzip
import io
import json
import re
import tarfile
import zlib

from hepph_paper_miner.sources.base import ErrorKind, Section, SourceError

# Part of every run record. Change it whenever the same source would split differently.
PARSER_VERSION = "5"

_MAX_UNPACKED_BYTES = 200_000_000
_MAX_MEMBER_BYTES = 5_000_000
_TEXT_SUFFIXES = (".tex", ".ltx", ".latex")
_MANIFEST = "00README.json"
_MIN_TOTAL_CHARS = 1000
# Text that stands under no heading is a section of its own from this size on. Below
# it, it is commands (\\tableofcontents, \\keywords, counters set anew) and is left out.
_MIN_UNHEADED_CHARS = 200
_MAX_INPUT_DEPTH = 10


class NotASource(SourceError):
    """PARSE_ERROR for a download that is not a paper's files: asking again may bring others.

    Broken gzip, an archive that ends early, an empty answer, a web page sent in
    place of the paper. The caller can tell these from a real source that only
    failed to split, and must not keep them. A real source without
    \\begin{document} (plain TeX, the notice left by a withdrawn paper) is not one
    of them: asking again would bring the same bytes.
    Takes the arguments of SourceError, so that it survives pickle.
    """


def parse_source(data: bytes) -> tuple[Section, ...]:
    """Split a source download into sections, or raise SourceError.

    NO_FULL_TEXT: there is no TeX source (the download is a PDF, PostScript or DVI).
    PARSE_ERROR:  there is something, but it could not be split into sections.
    """
    files = unpack(data)
    sections = split(files, find_main(files))
    ok, message = check(sections)
    if not ok:
        raise SourceError(ErrorKind.PARSE_ERROR, message)
    return sections


# --- unpack ------------------------------------------------------------------------


def unpack(data: bytes) -> dict[str, str]:
    """Return the text files of a source download.

    arXiv sends a gzipped tar when a paper has several files, and otherwise a single
    gzipped TeX file or a PDF. The HTTP client may already have removed the gzip
    layer, so every layer is recognised by its first bytes, not by a header.

    Raises NotASource for bytes that are damaged or plainly not a paper's files.
    """
    if data[:2] == b"\x1f\x8b":
        try:
            with gzip.GzipFile(fileobj=io.BytesIO(data)) as packed:
                data = packed.read(_MAX_UNPACKED_BYTES + 1)
        except (OSError, EOFError, zlib.error) as error:
            # zlib.error is not an OSError: a damaged byte inside the stream raises it.
            raise NotASource(
                ErrorKind.PARSE_ERROR, f"the download is not valid gzip ({error})"
            ) from error
        if len(data) > _MAX_UNPACKED_BYTES:
            raise SourceError(ErrorKind.PARSE_ERROR, "the download is too large to unpack")

    if data[:5] == b"%PDF-" or data[:4] == b"%!PS" or data[:2] == b"\xf7\x02":
        raise SourceError(ErrorKind.NO_FULL_TEXT, "the source is a PDF, PostScript or DVI file")

    try:
        bundle = tarfile.open(fileobj=io.BytesIO(data), mode="r:")
    except tarfile.TarError:
        return {"main.tex": _single_file(data)}  # not an archive: a single TeX file

    files: dict[str, str] = {}
    try:
        with bundle:
            for member in bundle:
                name = member.name.removeprefix("./")
                wanted = name == _MANIFEST or name.lower().endswith(_TEXT_SUFFIXES)
                if not (member.isfile() and wanted and member.size <= _MAX_MEMBER_BYTES):
                    continue
                # Members are read into memory and never written to disk, so a member
                # name cannot place a file anywhere.
                extracted = bundle.extractfile(member)
                if extracted is not None:
                    files[name] = _decode(extracted.read())
    except tarfile.TarError as error:
        # It began as an archive and then broke off. What was read so far is not the paper.
        raise NotASource(
            ErrorKind.PARSE_ERROR, f"the download is a damaged archive ({error})"
        ) from error
    return files


def _single_file(data: bytes) -> str:
    """The text of a download that is one file, unless it plainly is not TeX.

    Any other text is taken for the paper's source, also when it later turns out to
    have no \\begin{document}.
    """
    start = data.lstrip(b"\xef\xbb\xbf \t\r\n")[:16].lower()
    if not start:
        raise NotASource(ErrorKind.PARSE_ERROR, "the download is empty")
    if start.startswith((b"<!doctype", b"<html", b"<?xml")):
        raise NotASource(ErrorKind.PARSE_ERROR, "the download is a web page, not the paper's files")
    return _decode(data)


def _decode(raw: bytes) -> str:
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        text = raw.decode("latin-1")  # never fails; older papers are often Latin-1
    return text.replace("\r\n", "\n").replace("\r", "\n")


# --- find the main file --------------------------------------------------------------


def find_main(files: dict[str, str]) -> str:
    """Name the file to start from.

    1. The file that arXiv's own list (00README.json) marks as "toplevel".
    2. Otherwise a file that contains \\begin{document}: one that also has
       \\documentclass or \\documentstyle before one that has not, then the longest.
       A part written for the subfiles package is left out: it has both, and it can
       be longer than the main file, but it is never the paper.
    """
    manifest = files.get(_MANIFEST)
    if manifest is not None:
        try:
            for entry in json.loads(manifest).get("sources", []):
                if entry.get("usage") == "toplevel" and entry.get("filename") in files:
                    return entry["filename"]
        except (ValueError, AttributeError, TypeError):
            pass  # an unreadable list is the same as no list

    candidates = []
    for name, text in files.items():
        if name == _MANIFEST:
            continue
        bare = strip_comments(text)
        if "\\begin{document}" in bare and not _SUBFILES_PART.search(bare):
            has_class = "\\documentclass" in bare or "\\documentstyle" in bare
            candidates.append((not has_class, -len(bare), name))
    if not candidates:
        # A real source, only not LaTeX: plain TeX, or the notice of a withdrawn paper.
        raise SourceError(ErrorKind.PARSE_ERROR, "no file contains \\begin{document}")
    return min(candidates)[2]


# --- split ---------------------------------------------------------------------------

_COMMENT = re.compile(r"(?<!\\)((?:\\\\)*)%.*")  # a percent sign that is not escaped
_BLOCK_COMMENT = re.compile(
    r"\\begin\{comment\}.*?\\end\{comment\}|\\iffalse\b.*?\\fi\b", re.DOTALL
)
# In these arguments a percent sign is a character of the address, not a comment.
_VERBATIM_ARGUMENT = re.compile(r"\\(?:url|href|nolinkurl|path)\s*\{[^{}\n]*\}")
_KEPT_PERCENT = "\ue000"  # stands in for such a percent sign while comments are removed
# Commands that read another file into the text and that expand_inputs follows:
# \input{name}, \include{name}, \subfile{name}, \subfileinclude{name}, and TeX's own
# form: \input name
_INPUT = re.compile(
    r"\\(input|include|subfile|subfileinclude)(?![A-Za-z])\s*\{([^{}]+)\}"
    r"|\\(input)(?![A-Za-z])[ \t]+([^\s{}\\%]+)"
)
# Commands that read a file too, but in ways that are not followed here. The import
# package: \import{folder/}{name}, \subimport, \inputfrom, \subinputfrom, \includefrom,
# \subincludefrom, each also with a star. LaTeX itself: \InputIfFileExists{name}{..}{..}
_NOT_FOLLOWED = re.compile(
    r"\\((?:sub)?(?:import|inputfrom|includefrom))(?![A-Za-z])\s*\*?\s*\{([^{}]*)\}\s*\{([^{}]+)\}"
    r"|\\(InputIfFileExists)(?![A-Za-z])\s*\{([^{}]+)\}"
)
# The first line of a part written for the subfiles package: \documentclass[main]{subfiles}
_SUBFILES_PART = re.compile(r"\\documentclass\s*(?:\[[^\]]*\])?\s*\{subfiles\}")
_BIBLIOGRAPHY = re.compile(
    r"\\begin\{thebibliography\}.*?\\end\{thebibliography\}"
    r"|\\bibliography(?:style)?\s*\{[^{}]*\}"
    r"|\\printbibliography(?:\[[^\]]*\])?",
    re.DOTALL,
)
_HEADING = re.compile(
    # The short title in [...] may hold a "]" inside braces: \section[a {[b]} c]{...}
    r"\\(section|subsection)(?![A-Za-z])\s*(\*)?\s*"
    r"(?:\[(?:[^\]{}]|\{[^{}]*\})*\]|\[[^\]]*\])?\s*\{"
    r"|\\appendix(?![A-Za-z])|\\begin\{appendi(?:x|ces)\}"
)
_MAKETITLE = re.compile(r"\\maketitle(?![A-Za-z])")
_END_OF_ABSTRACT = re.compile(r"\\end\{abstract\}")
_LABEL = re.compile(r"\\label\s*\{[^{}]*\}")
# Of what _BIBLIOGRAPHY removes, the commands that print the list. \bibliographystyle
# prints nothing, and stands wherever the author put it.
_PRINTS_THE_LIST = re.compile(r"\\begin\{thebibliography\}|\\bibliography\s*\{|\\printbibliography")
# The acknowledgements as a class sets them: \begin{acknowledgments} ... \end{...}, or the
# command alone (\acknowledgments in REVTeX and JHEP, \ack in the IOP classes), in either
# spelling. No heading is typed there, so _HEADING does not find them.
_ACKNOWLEDGEMENTS = re.compile(
    r"\\begin\{(acknowledge?ments?|acks?)\}|\\(acknowledge?ments?|acks?)(?![A-Za-z@])"
)
# What stands right in front of a command that is being defined, not used:
# \def\ack, \renewcommand{\acknowledgments}
_DEFINITION = re.compile(r"\\(?:def|let|(?:re)?newcommand|providecommand)\s*\*?\s*\{?\s*\Z")
# A title that is run into the head of a paragraph, the way letters without section
# headings divide their text:  \textit{Introduction.}---  \emph{Results:}  {\it Summary}.
# It is typed in italics, and a mark sets it off from the sentence, last inside the
# braces or right behind them: a dash anywhere, a colon or a full stop only where a
# paragraph begins (inside one, "\textit{et al.}" can stand at the head of a line).
_BLANK_LINE = re.compile(r"\n[ \t]*\n")
_ITALICS = re.compile(
    r"(?:\\(?:noindent|par|indent)(?![A-Za-z])\s*)*"
    r"(?:\\(?:textit|emph)\s*(\{)|(\{)\s*\\(?:it|em|itshape)(?![A-Za-z]))"
)
_DASH = r"(?:---|\\textemdash(?![A-Za-z])|\u2014)"
_DASH_INSIDE = re.compile(r"[.:]?\s*" + _DASH + r"\s*\Z")
_DASH_BEHIND = re.compile(r"[.:]?[ \t~]*" + _DASH)
_STOP_INSIDE = re.compile(r"[.:]\s*\Z")
_STOP_BEHIND = re.compile(r"[.:](?=[\s~])")
# LaTeX's own command for a title that is run into its paragraph.
_PARAGRAPH = re.compile(r"\\paragraph(?![A-Za-z])\s*\*?\s*\{")
_MAX_RUN_IN_TITLE = 80
# One paragraph that begins with italics and a full stop can be a turn of phrase, and so
# can two. Three are taken for the division of the text.
_MIN_RUN_IN_TITLES = 3
# What a section is called that has no heading: always in parentheses, which tell a
# reader of the outline that this is not a title of the paper.
_NO_HEADINGS = "(the paper has no section headings)"
_BEFORE_FIRST = "(text before the first section)"
_AFTER_APPENDIX = "(text after \\appendix, without a section heading)"
_AFTER_REFERENCES = "(text after the list of references, without a section heading)"

# (position, level, starred, title, where the text starts). Level 0 is a place where a
# section can begin without a heading; its title is the one such a section would get.
_Mark = tuple[int, int, bool, str, int]


def strip_comments(text: str) -> str:
    """Remove what TeX would not typeset: % comments, comment environments, \\iffalse blocks."""
    kept = []
    for line in text.split("\n"):
        if line.lstrip().startswith("%"):
            continue  # the whole line is a comment: drop it without leaving a blank line
        if "%" in line:
            line = _VERBATIM_ARGUMENT.sub(
                lambda match: match.group(0).replace("%", _KEPT_PERCENT), line
            )
            line = _COMMENT.sub(r"\1", line).replace(_KEPT_PERCENT, "%")
        kept.append(line)
    return _BLOCK_COMMENT.sub("", "\n".join(kept))


def expand_inputs(text: str, files: dict[str, str], depth: int = 0, folder: str = "") -> str:
    """Read the files that the text names into it, in the order in which TeX reads them.

    `folder` is where the main file lies ("" or "paper/"): TeX runs there, so names
    are also tried from there. A name that is not among the files stays as written:
    papers also \\input files of the TeX installation, which are not part of the
    download. split() decides afterwards whether what stayed means lost text.

    Before the document has begun, a file is read as it is: it may be the one that
    holds \\begin{document}. Inside the document, a file that is a document of its
    own (a part for the subfiles package) adds only what stands between its own
    \\begin{document} and \\end{document}, as it does in TeX.
    """
    in_document = False

    def read(text: str, depth: int) -> str:
        nonlocal in_document
        pieces: list[str] = []
        position = 0
        for match in _INPUT.finditer(text):
            before = text[position : match.start()]
            in_document = in_document or "\\begin{document}" in before
            pieces += [before, read_file(match, depth)]
            position = match.end()
        rest = text[position:]
        in_document = in_document or "\\begin{document}" in rest
        pieces.append(rest)
        return "".join(pieces)

    def read_file(match: re.Match[str], depth: int) -> str:
        name = _input_name(match)[1]
        if depth < _MAX_INPUT_DEPTH:
            for candidate in (name, name + ".tex", folder + name, folder + name + ".tex"):
                if candidate in files:
                    inner = strip_comments(files[candidate])
                    return read(_document_body(inner) if in_document else inner, depth + 1)
        return match.group(0)

    return read(text, depth)


def _input_name(match: re.Match[str]) -> tuple[str, str]:
    """(command, file name) of an _INPUT match."""
    command = match.group(1) or match.group(3)
    return command, (match.group(2) or match.group(4)).strip().removeprefix("./")


def _document_body(text: str) -> str:
    """What stands between the first \\begin{document} and the first \\end{document} after it.

    All of the text when there is no \\begin{document}; up to the end of the text
    when no \\end{document} follows.
    """
    start = text.find("\\begin{document}")
    if start < 0:
        return text
    end = text.find("\\end{document}", start)
    return text[start + len("\\begin{document}") : end if end >= 0 else len(text)]


def _holds_text(name: str) -> bool:
    """Whether a file of this name can hold running text: no suffix, or a TeX suffix.

    "plot.pstex_t", "paper.bbl" and "epsf.sty" do not.
    """
    last = name.rsplit("/", 1)[-1]
    return "." not in last or last.lower().endswith(_TEXT_SUFFIXES)


def _unread_files(body: str) -> list[str]:
    """Files that the body reads and whose text is not in it.

    Either the body still names the file after expand_inputs, so it was not among
    the TeX files of the download. Or the body reads it with a command that is not
    followed; that command is then given in brackets after the name.

    \\include, \\subfile and their relatives always name a file of the paper. For
    \\input and the like, the name counts when it can hold text. This can also turn
    away a paper that, inside its body, reads a file of the TeX installation by a
    bare name. That is the cheaper mistake.
    """
    unread: list[str] = []
    for match in _INPUT.finditer(body):
        command, name = _input_name(match)
        if (command != "input" or _holds_text(name)) and name not in unread:
            unread.append(name)
    for match in _NOT_FOLLOWED.finditer(body):
        if match.group(1):  # \import{folder/}{name} and its relatives
            folder = match.group(2).strip()
            if folder and not folder.endswith("/"):
                folder += "/"  # the package adds the missing slash as well
            command, name = match.group(1), folder + match.group(3).strip()
        else:  # \InputIfFileExists{name}{..}{..}
            command, name = match.group(4), match.group(5).strip()
        entry = f"{name} (\\{command})"
        if ("include" in command or _holds_text(name)) and entry not in unread:
            unread.append(entry)
    return unread


def split(files: dict[str, str], main: str) -> tuple[Section, ...]:
    """Cut the document body at \\section and \\subsection.

    Identifiers follow the numbers LaTeX would print: "1", "2", "2.1", and after
    \\appendix "A", "B", "B.1". Starred headings have no number in LaTeX; they get
    "u1", "u2" in document order (or "2.u1" inside section 2).

    Every piece of the body lies in a section, also text under no heading of its own.
    What comes before the first \\section is section "0", and what stands between
    \\appendix and the next \\section gets the next "u" identifier. Like any section,
    each of the two holds the subsections that follow it. Short and without a
    subsection, such text is commands and makes no section (_MIN_UNHEADED_CHARS).

    Three more places begin a section, and no \\section stands there:

        the acknowledgements   \\begin{acknowledgments} or \\acknowledgments, as a class
                               sets them. Titled with the word the source uses.
        behind the references  text that follows the list of references under no
                               heading: in the paper it stands below the list, not in
                               the section above it. Treated like text after \\appendix,
                               where a title stands in front of the list.
        titles run in          \\paragraph{...}, or italics that a mark sets off at the
                               head of a paragraph, in text that stands under no
                               heading. Under a \\section they are a level that is not
                               cut at, like anything below a subsection.

    All three are unnumbered and get "u" identifiers.
    """
    # Read the other files in first, then cut. TeX begins the document at the first
    # \begin{document} it meets and ends it at the first \end{document} after that,
    # in whichever file they stand: an \input file may hold either of them, and what
    # the main file says after an \end{document} that was read in is never typeset.
    # (A part for the subfiles package has lost its own pair in expand_inputs.)
    folder = main.rpartition("/")[0]
    text = expand_inputs(strip_comments(files[main]), files, folder=folder + "/" if folder else "")
    if "\\begin{document}" not in text:
        raise SourceError(
            ErrorKind.PARSE_ERROR,
            "no \\begin{document} in the main file or in the files it reads",
        )
    body = _document_body(text)
    unread = _unread_files(body)
    if unread:
        listed = ", ".join(unread[:5]) + (" ..." if len(unread) > 5 else "")
        # Short, and the names last: this is what a person reads to see what was lost.
        raise SourceError(
            ErrorKind.PARSE_ERROR,
            f"text is missing, {len(unread)} file(s) could not be read: {listed}",
        )
    body, lists = _without_bibliography(body)

    # Where a section begins. First the places that say so themselves: the headings,
    # and the acknowledgements of a class.
    marks = _find_headings(body)
    marks = sorted(marks + _find_acknowledgements(body, marks))
    first = marks[0][0] if marks else len(body)

    # The text begins after the title block. Papers without an "Introduction" heading
    # start it right there.
    front_end = _front_end(body, first)

    # What stands between the title block and the first of these places is under no
    # heading. It can still be divided, by titles that are run into its paragraphs.
    marks = _find_run_in_titles(body, front_end, first) + marks
    # And a list of references ends the section it stands in when text follows it.
    marks = _with_ends_of_lists(marks, body, lists)
    headings = [mark for mark in marks if mark[1] > 0]

    if not headings:
        # All of it, also what follows an \appendix: with no heading there either, it
        # belongs to this one section.
        text = _tidy(body[front_end:])
        return (Section("1", _NO_HEADINGS, 1, text),)

    sections: list[Section] = []
    in_appendix = False
    numbered = lettered = unnumbered = 0
    parent, sub_numbered, sub_unnumbered = "0", 0, 0
    holder_start = front_end  # where the text of the section begins that holds what follows

    # What comes before the first \section or \appendix, subsections included.
    first_section = next((mark[0] for mark in marks if mark[1] <= 1), len(body))
    front = _tidy(body[front_end:first_section])
    if _makes_a_section(front, followed_by=marks[0]):
        sections.append(Section("0", _BEFORE_FIRST, 1, front))

    for index, (position, level, starred, title, text_start) in enumerate(marks):
        # A section runs to the next section or to \appendix, and so does the text
        # after \appendix. A subsection runs to the next heading.
        stop = len(body)
        for later_position, later_level, *_ in marks[index + 1 :]:
            if level == 2 or later_level <= 1:
                stop = later_position
                break
        text = _tidy(body[text_start:stop])

        if level == 0:
            # \appendix, or the end of a list of references. Only the first changes how
            # the sections that follow are numbered.
            in_appendix = in_appendix or title == _AFTER_APPENDIX
            later = marks[index + 1] if index + 1 < len(marks) else None
            if _makes_a_section(text, followed_by=later):
                # No heading, so no number: the next of the identifiers that say so.
                unnumbered += 1
                parent, sub_numbered, sub_unnumbered = f"u{unnumbered}", 0, 0
                holder_start = text_start
                sections.append(Section(parent, title, 1, text))
            continue

        if level == 1:
            sub_numbered = sub_unnumbered = 0
            holder_start = text_start
            if starred:
                unnumbered += 1
                parent = f"u{unnumbered}"
            elif in_appendix:
                lettered += 1
                parent = chr(ord("A") + lettered - 1) if lettered <= 26 else f"A{lettered}"
            else:
                numbered += 1
                parent = str(numbered)
            sections.append(Section(parent, title, 1, text))
            continue

        if starred:
            sub_unnumbered += 1
            section_id = f"{parent}.u{sub_unnumbered}"
        else:
            sub_numbered += 1
            section_id = f"{parent}.{sub_numbered}"
        # Where the heading begins in the text of its section. That text is tidied, so
        # the heading stands after what comes before it, tidied the same way. It is
        # no white space, so no run of line breaks that _tidy shortens is cut in two.
        before = _squeeze(body[holder_start:position]).lstrip()
        sections.append(Section(section_id, title, 2, text, heading_at=len(before)))
    return tuple(sections)


def _makes_a_section(text: str, followed_by: _Mark | None) -> bool:
    """Whether text under no heading of its own is kept as a section.

    When it is long enough to be text, and whatever its length when a subsection
    follows it: that subsection has to lie in a section, and this is the one.
    """
    if followed_by is not None and followed_by[1] == 2:
        return True
    return len(re.sub(r"\s", "", text)) >= _MIN_UNHEADED_CHARS


def _front_end(body: str, stop: int) -> int:
    """Where the title block ends: behind \\maketitle and behind the abstract, whichever is later.

    The first of each. A second \\maketitle further down sets the title of something
    else (supplemental material with a title of its own), and what stands in front of
    it is the paper, not a title block.
    """
    ends = [
        match.end()
        for pattern in (_MAKETITLE, _END_OF_ABSTRACT)
        if (match := pattern.search(body, 0, stop)) is not None
    ]
    return max(ends, default=0)


def _without_bibliography(body: str) -> tuple[str, list[int]]:
    """The body without its lists of references, and where each list stood in what is left."""
    pieces: list[str] = []
    places: list[int] = []
    position = length = 0
    for match in _BIBLIOGRAPHY.finditer(body):
        pieces.append(body[position : match.start()])
        length += match.start() - position
        if _PRINTS_THE_LIST.match(match.group(0)):
            places.append(length)
        position = match.end()
    pieces.append(body[position:])
    return "".join(pieces), places


def _find_acknowledgements(body: str, headings: list[_Mark]) -> list[_Mark]:
    """The acknowledgements that a class sets, each as the mark of an unnumbered section.

    Not where a heading for them stands right in front: that heading is their section
    already. The title is the word as the source has it; "ack" and "acks" are short for it.
    """
    marks: list[_Mark] = []
    for match in _ACKNOWLEDGEMENTS.finditer(body):
        if _DEFINITION.search(body, max(0, match.start() - 30), match.start()):
            continue
        before = [mark for mark in headings if mark[1] > 0 and mark[0] < match.start()]
        if before and "cknowledg" in before[-1][3]:
            if not body[before[-1][4] : match.start()].strip():
                continue  # \section*{Acknowledgments}\begin{acknowledgments}: one section
        name = match.group(1) or match.group(2)
        title = name.capitalize() if name.startswith("acknowledg") else "Acknowledgments"
        marks.append((match.start(), 1, True, title, match.end()))
    return marks


def _with_ends_of_lists(marks: list[_Mark], body: str, lists: list[int]) -> list[_Mark]:
    """The marks, and among them the ends of the lists of references that begin a section.

    The end of a list is a place like \\appendix: what follows it under no heading stands
    below the list in the paper, not in the section above it. It is taken for such a
    place when a title stands in front of the list (a heading, the acknowledgements, a
    title run into a paragraph) and what follows makes a section (_makes_a_section).

    So no text is left out for it. What stands in front of the list belongs to the
    section of that title, and a few commands behind the list stay where they were, at
    the end of that section. A list in text that has no title, or in the text after
    \\appendix, is no such place: there the text in front of it could be too short to
    be kept by itself.
    """
    for place in lists:
        before = [mark for mark in marks if mark[0] < place]
        if not before or before[-1][1] == 0:
            continue
        later = [mark for mark in marks if mark[0] >= place]
        stop = next((mark[0] for mark in later if mark[1] <= 1), len(body))
        if _makes_a_section(_tidy(body[place:stop]), followed_by=later[0] if later else None):
            end_of_list = (place, 0, False, _AFTER_REFERENCES, place)
            # In front of a heading that begins at the same place.
            marks = sorted([*marks, end_of_list], key=lambda mark: (mark[0], mark[1] != 0))
    return marks


def _find_run_in_titles(body: str, start: int, stop: int) -> list[_Mark]:
    """The titles run into the head of a paragraph between two places, as unnumbered sections.

    \\paragraph{...} is always one. A title typed by hand is taken for one when a line
    begins with it in italics and a mark sets it off (_ITALICS), and when there are at
    least _MIN_RUN_IN_TITLES of them: fewer are left alone.
    """
    marks: list[_Mark] = []
    for match in _PARAGRAPH.finditer(body, start, stop):
        close = _closing_brace(body, match.end() - 1)
        if close < stop and body[close] == "}":
            title = " ".join(_LABEL.sub("", body[match.end() : close]).split())
            marks.append((match.start(), 1, True, title, close + 1))

    typed: list[_Mark] = []
    position = start
    begins_paragraph = True  # the text begins here, and so does a paragraph
    for line in body[start:stop].splitlines(keepends=True):
        head = position + len(line) - len(line.lstrip())
        position += len(line)
        if not line.strip():
            begins_paragraph = True
            continue
        found = _run_in_title(body, head, stop, begins_paragraph)
        begins_paragraph = False
        if found is not None:
            typed.append(found)
    if len(typed) >= _MIN_RUN_IN_TITLES:
        marks += typed
    return sorted(marks)


def _run_in_title(body: str, head: int, stop: int, begins_paragraph: bool) -> _Mark | None:
    """The mark of a title typed in italics at the head of a line, or None when it is none."""
    match = _ITALICS.match(body, head, stop)
    if match is None:
        return None
    # \textit{Title}: the brace ends the match. {\it Title}: it begins the group.
    opening = match.end() - 1 if match.group(1) else match.start(2)
    close = _closing_brace(body, opening)
    if close >= stop or body[close] != "}" or _BLANK_LINE.search(body, opening, close):
        return None
    title = " ".join(body[match.end() : close].split())
    inside = _DASH_INSIDE.search(title)
    behind = _DASH_BEHIND.match(body, close + 1, stop)
    if begins_paragraph:
        inside = inside or _STOP_INSIDE.search(title)
        behind = behind or _STOP_BEHIND.match(body, close + 1, stop)
    if inside is None and behind is None:
        return None  # italics at the head of a line, and no title
    if inside is not None:
        title = title[: inside.start()]
    title = title.rstrip(" .:")
    if not title or len(title) > _MAX_RUN_IN_TITLE:
        return None
    # The mark belongs to the title, as the braces of \section{...} do.
    return (head, 1, True, title, behind.end() if behind is not None else close + 1)


def _find_headings(body: str) -> list[_Mark]:
    """The marks of \\section, \\subsection and \\appendix. Level 0 marks \\appendix."""
    marks: list[_Mark] = []
    for match in _HEADING.finditer(body):
        if match.group(1) is None:
            marks.append((match.start(), 0, False, _AFTER_APPENDIX, match.end()))
            continue
        close = _closing_brace(body, match.end() - 1)
        title = _LABEL.sub("", body[match.end() : close])
        level = 1 if match.group(1) == "section" else 2
        marks.append(
            (match.start(), level, match.group(2) is not None, " ".join(title.split()), close + 1)
        )
    return marks


def _closing_brace(text: str, opening: int) -> int:
    """Index of the brace that closes the one at `opening`; the end of that line if none does."""
    depth = 0
    index = opening
    while index < len(text):
        char = text[index]
        if char == "\\":
            index += 2  # skip an escaped character, also \{ and \}
            continue
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return index
        index += 1
    line_end = text.find("\n", opening)
    return len(text) - 1 if line_end < 0 else line_end


def _tidy(text: str) -> str:
    return _squeeze(text).strip()


def _squeeze(text: str) -> str:
    return re.sub(r"\n{3,}", "\n\n", text)


# --- check ---------------------------------------------------------------------------


def check(sections: tuple[Section, ...]) -> tuple[bool, str]:
    """Decide whether a split can be trusted. Returns (ok, message)."""
    if not sections:
        return False, "no sections"
    identifiers = [section.section_id for section in sections]
    if len(identifiers) != len(set(identifiers)):
        return False, "two sections share an identifier"
    # The text of a paper is the text of its sections, which hold their subsections
    # (Paper.chars, and the whole paper as the flat layout returns it). A subsection
    # outside the section before it would be missing from both.
    holder: Section | None = None
    for section in sections:
        if section.level == 1:
            holder = section
        elif holder is None or section.text not in holder.text:
            return False, f"subsection {section.section_id} is not part of the section before it"
        elif section.heading_at is None or not holder.text.startswith(
            "\\subsection", section.heading_at
        ):
            # The flat layout puts the marker of a subsection in front of this place.
            return (
                False,
                f"the heading of subsection {section.section_id} is not where it should be",
            )
    total = sum(section.chars for section in sections if section.level == 1)
    if total < _MIN_TOTAL_CHARS:
        return False, f"only {total} characters of text were found"
    return True, f"{len(sections)} sections, {total} characters"
