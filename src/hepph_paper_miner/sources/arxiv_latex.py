"""From the bytes of an arXiv source download to a list of sections. No network.

    unpack      bytes            -> {file name: text}
    find_main   files            -> name of the file that holds \\begin{document}
    split       files, main name -> sections
    check       sections         -> (ok, message)

parse_source() runs the four in order. The parser reads LaTeX as text and never
runs TeX, so it follows \\input but not macros that authors define for themselves.

A split that lost text is worse than no split: the reader would take a part of the
paper for the whole. So where the parser can see that text is missing (a file named
by \\input that it could not find), it reports PARSE_ERROR instead of a result.
"""

from __future__ import annotations

import gzip
import io
import json
import re
import tarfile

from hepph_paper_miner.sources.base import ErrorKind, Section, SourceError

# Part of every run record. Change it whenever the same source would split differently.
PARSER_VERSION = "2"

_MAX_UNPACKED_BYTES = 200_000_000
_MAX_MEMBER_BYTES = 5_000_000
_TEXT_SUFFIXES = (".tex", ".ltx", ".latex")
_MANIFEST = "00README.json"
_MIN_TOTAL_CHARS = 1000
_MIN_FRONT_CHARS = 200
_MAX_INPUT_DEPTH = 10


class NotASource(SourceError):
    """PARSE_ERROR for a download that holds no LaTeX document at all.

    Broken gzip, or no file with \\begin{document}: a page sent in place of the
    paper looks like this, and so do a withdrawn paper and a paper in plain TeX.
    The caller can tell it from a real source that only failed to split, and must
    not keep it. Takes the arguments of SourceError, so that it survives pickle.
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
    """
    if data[:2] == b"\x1f\x8b":
        try:
            with gzip.GzipFile(fileobj=io.BytesIO(data)) as packed:
                data = packed.read(_MAX_UNPACKED_BYTES + 1)
        except (OSError, EOFError) as error:
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
        return {"main.tex": _decode(data)}  # a single TeX file

    files: dict[str, str] = {}
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
    return files


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
    """
    manifest = files.get(_MANIFEST)
    if manifest is not None:
        try:
            for entry in json.loads(manifest).get("sources", []):
                if entry.get("usage") == "toplevel" and entry.get("filename") in files:
                    return entry["filename"]
        except (ValueError, AttributeError):
            pass  # an unreadable list is the same as no list

    candidates = []
    for name, text in files.items():
        if name == _MANIFEST:
            continue
        bare = strip_comments(text)
        if "\\begin{document}" in bare:
            has_class = "\\documentclass" in bare or "\\documentstyle" in bare
            candidates.append((not has_class, -len(bare), name))
    if not candidates:
        raise NotASource(ErrorKind.PARSE_ERROR, "no file contains \\begin{document}")
    return min(candidates)[2]


# --- split ---------------------------------------------------------------------------

_COMMENT = re.compile(r"(?<!\\)((?:\\\\)*)%.*")  # a percent sign that is not escaped
_BLOCK_COMMENT = re.compile(
    r"\\begin\{comment\}.*?\\end\{comment\}|\\iffalse\b.*?\\fi\b", re.DOTALL
)
# In these arguments a percent sign is a character of the address, not a comment.
_VERBATIM_ARGUMENT = re.compile(r"\\(?:url|href|nolinkurl|path)\s*\{[^{}\n]*\}")
_KEPT_PERCENT = "\ue000"  # stands in for such a percent sign while comments are removed
# \input{name}, \include{name}, \subfile{name}, and TeX's own form: \input name
_INPUT = re.compile(
    r"\\(input|include|subfile)(?![A-Za-z])\s*\{([^{}]+)\}"
    r"|\\(input)(?![A-Za-z])[ \t]+([^\s{}\\%]+)"
)
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
    """Replace \\input{name} by the file it names, as long as that file came with the paper.

    `folder` is where the main file lies ("" or "paper/"): TeX runs there, so names
    are also tried from there. A name that is not among the files stays as written:
    papers also \\input files of the TeX installation, which are not part of the
    download. split() decides afterwards whether what stayed means lost text.
    """

    def replace(match: re.Match[str]) -> str:
        name = _input_name(match)[1]
        if depth < _MAX_INPUT_DEPTH:
            for candidate in (name, name + ".tex", folder + name, folder + name + ".tex"):
                if candidate in files:
                    inner = _document_body(strip_comments(files[candidate]))
                    return expand_inputs(inner, files, depth + 1, folder)
        return match.group(0)

    return _INPUT.sub(replace, text)


def _input_name(match: re.Match[str]) -> tuple[str, str]:
    """(command, file name) of an _INPUT match."""
    command = match.group(1) or match.group(3)
    return command, (match.group(2) or match.group(4)).strip().removeprefix("./")


def _document_body(text: str) -> str:
    """What a file adds when it is read into another one.

    A file that can also be compiled alone (the subfiles package) has a preamble and
    its own \\begin{document} ... \\end{document}. Only what lies between them
    counts; pasted whole, its \\end{document} would end the paper early.
    """
    start = text.find("\\begin{document}")
    if start < 0:
        return text
    end = text.find("\\end{document}", start)
    return text[start + len("\\begin{document}") : end if end >= 0 else len(text)]


def _missing_inputs(body: str) -> list[str]:
    """Files the body still asks for after expand_inputs, and whose text is therefore missing.

    \\include and \\subfile always name a file of the paper. \\input counts when the
    name has no suffix or a TeX suffix; "plot.pstex_t", "paper.bbl" or "epsf.sty" hold
    no running text. This can also turn away a paper that, inside its body, reads a
    file of the TeX installation by a bare name. That is the cheaper mistake.
    """
    missing = []
    for match in _INPUT.finditer(body):
        command, name = _input_name(match)
        last = name.rsplit("/", 1)[-1]
        holds_text = "." not in last or last.lower().endswith(_TEXT_SUFFIXES)
        if (command != "input" or holds_text) and name not in missing:
            missing.append(name)
    return missing


def split(files: dict[str, str], main: str) -> tuple[Section, ...]:
    """Cut the document body at \\section and \\subsection.

    Identifiers follow the numbers LaTeX would print: "1", "2", "2.1", and after
    \\appendix "A", "B", "B.1". Starred headings have no number in LaTeX; they get
    "u1", "u2" in document order (or "2.u1" inside section 2).
    """
    # The main file is cut to its body first and the other files are read into it
    # afterwards. In the other order the first \\end{document} found could be one
    # that an \\input file brought along.
    text = strip_comments(files[main])
    start = text.find("\\begin{document}")
    if start < 0:
        raise SourceError(ErrorKind.PARSE_ERROR, "no \\begin{document} in the main file")
    folder = main.rpartition("/")[0]
    body = expand_inputs(_document_body(text), files, folder=folder + "/" if folder else "")
    missing = _missing_inputs(body)
    if missing:
        listed = ", ".join(missing[:5]) + (" ..." if len(missing) > 5 else "")
        raise SourceError(
            ErrorKind.PARSE_ERROR,
            f"{len(missing)} file(s) named by \\input are not among the TeX files "
            f"of the download, so text would be missing: {listed}",
        )
    body = _BIBLIOGRAPHY.sub("", body)

    marks = _find_headings(body)
    headings = [mark for mark in marks if mark[1] > 0]
    first = marks[0][0] if marks else len(body)

    # Text between the title block and the first heading. Papers without an
    # "Introduction" heading start their text here.
    front_end = 0
    for match in _FRONT_END.finditer(body, 0, first):
        front_end = match.end()
    front = _tidy(body[front_end:first])

    if not headings:
        return (Section("1", "(the paper has no section headings)", 1, front),)

    sections: list[Section] = []
    if len(re.sub(r"\s", "", front)) >= _MIN_FRONT_CHARS:
        sections.append(Section("0", "(text before the first section)", 1, front))

    in_appendix = False
    numbered = lettered = unnumbered = 0
    parent, sub_numbered, sub_unnumbered = "0", 0, 0
    for index, (position, level, starred, title, text_start) in enumerate(marks):
        if level == 0:
            in_appendix = True
            continue
        # A section runs to the next section or to \appendix; a subsection to the next heading.
        stop = len(body)
        for later_position, later_level, *_ in marks[index + 1 :]:
            if level == 2 or later_level <= 1:
                stop = later_position
                break

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
        sections.append(Section(section_id, title, level, _tidy(body[text_start:stop])))
    return tuple(sections)


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
    total = sum(section.chars for section in sections if section.level == 1)
    if total < _MIN_TOTAL_CHARS:
        return False, f"only {total} characters of text were found"
    return True, f"{len(sections)} sections, {total} characters"
