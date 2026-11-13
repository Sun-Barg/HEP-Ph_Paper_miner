"""From the bytes of an arXiv source download to a list of sections. No network.

    unpack      bytes            -> {file name: text}
    find_main   files            -> name of the file that holds \\begin{document}
    split       files, main name -> sections
    check       sections         -> (ok, message)

parse_source() runs the four in order. The parser reads LaTeX as text and never
runs TeX, so it follows \\input but not macros that authors define for themselves.

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
      - \\includeonly, \\endinput and \\if... are not obeyed, so text that TeX
        skips can end up in a section.
      - a few words that stand under no heading (before the first \\section, or
        between \\appendix and the next one) are taken for commands and left out.
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
PARSER_VERSION = "4"

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
_FRONT_END = re.compile(r"\\maketitle(?![A-Za-z])|\\end\{abstract\}")
_LABEL = re.compile(r"\\label\s*\{[^{}]*\}")


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
    body = _BIBLIOGRAPHY.sub("", body)

    marks = _find_headings(body)
    headings = [mark for mark in marks if mark[1] > 0]
    first = marks[0][0] if marks else len(body)

    # The text begins after the title block. Papers without an "Introduction" heading
    # start it right there.
    front_end = 0
    for match in _FRONT_END.finditer(body, 0, first):
        front_end = match.end()

    if not headings:
        # All of it, also what follows an \appendix: with no heading there either, it
        # belongs to this one section.
        text = _tidy(body[front_end:])
        return (Section("1", "(the paper has no section headings)", 1, text),)

    sections: list[Section] = []
    in_appendix = False
    numbered = lettered = unnumbered = 0
    parent, sub_numbered, sub_unnumbered = "0", 0, 0

    # What comes before the first \section or \appendix, subsections included.
    first_section = next((mark[0] for mark in marks if mark[1] <= 1), len(body))
    front = _tidy(body[front_end:first_section])
    if _makes_a_section(front, followed_by=marks[0]):
        sections.append(Section("0", "(text before the first section)", 1, front))

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
            in_appendix = True
            later = marks[index + 1] if index + 1 < len(marks) else None
            if _makes_a_section(text, followed_by=later):
                # No heading, so no number: the next of the identifiers that say so.
                unnumbered += 1
                parent, sub_numbered, sub_unnumbered = f"u{unnumbered}", 0, 0
                title = "(text after \\appendix, without a section heading)"
                sections.append(Section(parent, title, 1, text))
            continue

        if level == 1:
            sub_numbered = sub_unnumbered = 0
            if starred:
                unnumbered += 1
                parent = f"u{unnumbered}"
            elif in_appendix:
                lettered += 1
                parent = chr(ord("A") + lettered - 1) if lettered <= 26 else f"A{lettered}"
            else:
                numbered += 1
                parent = str(numbered)
            section_id = parent
        elif starred:
            sub_unnumbered += 1
            section_id = f"{parent}.u{sub_unnumbered}"
        else:
            sub_numbered += 1
            section_id = f"{parent}.{sub_numbered}"
        sections.append(Section(section_id, title, level, text))
    return tuple(sections)


def _makes_a_section(text: str, followed_by: tuple[int, int, bool, str, int] | None) -> bool:
    """Whether text under no heading of its own is kept as a section.

    When it is long enough to be text, and whatever its length when a subsection
    follows it: that subsection has to lie in a section, and this is the one.
    """
    if followed_by is not None and followed_by[1] == 2:
        return True
    return len(re.sub(r"\s", "", text)) >= _MIN_UNHEADED_CHARS


def _find_headings(body: str) -> list[tuple[int, int, bool, str, int]]:
    """(position, level, starred, title, where the text starts). Level 0 marks \\appendix."""
    marks = []
    for match in _HEADING.finditer(body):
        if match.group(1) is None:
            marks.append((match.start(), 0, False, "", match.end()))
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
    return re.sub(r"\n{3,}", "\n\n", text).strip()


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
    total = sum(section.chars for section in sections if section.level == 1)
    if total < _MIN_TOTAL_CHARS:
        return False, f"only {total} characters of text were found"
    return True, f"{len(sections)} sections, {total} characters"
