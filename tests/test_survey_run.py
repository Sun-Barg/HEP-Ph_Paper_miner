"""The survey itself: the line of a paper, what is no outcome, and the command. No network.

Papers come from a source held in memory, and for what the cache does, from the real
source with arXiv played by a scripted transport.
"""

import gzip
import json
from pathlib import Path

import httpx2
import pytest
from conftest import LONG_LATEX, SAMPLE_LATEX, filler, tar_gz
from test_survey_listing import entry, feed
from test_survey_plan import a_plan
from test_survey_sample import COMMIT, committed, lines_of

from hepph_paper_miner.agent.origin import file_digest
from hepph_paper_miner.http import CACHE_ENV, Fetcher
from hepph_paper_miner.server import SECTION_CHAR_LIMIT, own_text
from hepph_paper_miner.sources import arxiv_latex
from hepph_paper_miner.sources.arxiv import ArxivSource
from hepph_paper_miner.sources.arxiv_latex import PARSER_VERSION, check, parse_source
from hepph_paper_miner.sources.base import ErrorKind, PaperMeta, Section, SourceError
from hepph_paper_miner.sources.fixture import paper_from_latex
from hepph_paper_miner.survey import run
from hepph_paper_miner.survey.listing import Listed
from hepph_paper_miner.survey.plan import read_plan
from hepph_paper_miner.survey.records import RecordError, write_lines
from hepph_paper_miner.survey.run import (
    NO_HEADINGS,
    OUTCOMES,
    branch,
    read_outcomes,
    shape,
    survey_one,
    tally,
    walk,
)
from hepph_paper_miner.survey.sample import Drawn, draw, read_sample, sample_lines

PLAN = read_plan(json.dumps(a_plan()))
NO_SECTIONS_LATEX = (
    "\\documentclass{article}\\begin{document}\\maketitle\n" + filler(400) + "\n\\end{document}"
)
# A section whose own text, in front of its first subsection, is its largest part.
OWN_TEXT_LATEX = (
    "\\documentclass{article}\\begin{document}\n\\section{Big}\n"
    + filler(4000)
    + "\n\\subsection{Small}\nA little.\n\\section{Other}\nSome more.\n\\end{document}"
)


def a_paper(arxiv_id: str, latex: str = SAMPLE_LATEX, primary: str = "hep-ph"):
    meta = PaperMeta(arxiv_id, "A title no line keeps", ("A. Author",), 2026, primary, "Abstract.")
    return paper_from_latex(meta, latex)


def drawn(arxiv_id: str = "2608.00001v1", archive: str = "hep-ph", rank: int = 1) -> Drawn:
    return Drawn(archive, rank, arxiv_id, archive, "0" * 64)


class Memory:
    """A source that gives each identifier what it was told to: a paper, or an error to raise.

    A list is given out one by one, and its last entry from then on.
    """

    def __init__(self, answers: dict):
        self.answers = {
            name: list(each) if isinstance(each, list) else [each] for name, each in answers.items()
        }
        self.asked: list[str] = []

    def paper(self, arxiv_id):
        name = str(arxiv_id)
        self.asked.append(name)
        answers = self.answers[name]
        answer = answers.pop(0) if len(answers) > 1 else answers[0]
        if isinstance(answer, BaseException):
            raise answer
        return answer


# --- the line of one paper -------------------------------------------------------------------


def test_a_paper_that_was_split_leaves_counts_and_nothing_of_its_text():
    paper = a_paper("2608.00001v1")
    line = survey_one(Memory({"2608.00001v1": paper}), drawn())

    by_id = {section.section_id: section for section in paper.sections}
    assert line == {
        "record": "paper",
        "archive": "hep-ph",
        "rank": 1,
        "id": "2608.00001v1",
        "primary": "hep-ph",
        "outcome": "ok",
        "sections": 4,  # 1, 2, u1 and A
        "subsections": 4,  # 2.1, 2.u1, 2.2 and A.1
        "chars": paper.chars,
        "largest": by_id["1"].chars,  # the introduction, which has no subsection
        "no_headings": False,
    }
    assert line["largest"] > 2000 and line["chars"] > line["largest"]


def test_the_largest_piece_is_what_one_call_can_be_asked_for():
    # A subsection, a section without subsections, or the text a section has of its own.
    paper = a_paper("2608.00001v1", OWN_TEXT_LATEX)
    own = own_text(paper)["1"]
    others = [s.chars for s in paper.sections if s.section_id in ("1.1", "2")]

    assert shape(paper)["largest"] == own > SECTION_CHAR_LIMIT > max(others)
    # The whole of section 1 is larger still, and is no piece: its parts can be asked for.
    assert paper.sections[0].chars > own

    long = shape(a_paper("2502.00002v1", LONG_LATEX))
    assert long["largest"] > 2 * SECTION_CHAR_LIMIT and long["subsections"] == 1


def test_a_paper_without_any_section_heading_is_marked():
    without = a_paper("2608.00001v1", NO_SECTIONS_LATEX)
    # The title the parser gives its one section: if it is reworded there, this fails.
    assert [section.title for section in without.sections] == [NO_HEADINGS]
    assert shape(without) == {
        "sections": 1,
        "subsections": 0,
        "chars": without.chars,
        "largest": without.chars,
        "no_headings": True,
    }
    assert shape(a_paper("2608.00002v1"))["no_headings"] is False
    # One section is not "no heading": this paper has one, and nothing in front of it.
    one = "\\documentclass{article}\\begin{document}\\section{Only}\n" + filler(400)
    only = a_paper("2608.00004v1", one + "\n\\end{document}")
    assert [section.section_id for section in only.sections] == ["1"]
    assert shape(only)["no_headings"] is False
    # One heading at the end, and the text in front of it under none: that paper has a heading.
    late = NO_SECTIONS_LATEX.replace(
        "\\end{document}", "\\section{Thanks}\nTo all.\n\\end{document}"
    )
    assert shape(a_paper("2608.00003v1", late))["no_headings"] is False


def raised_by(data: bytes) -> SourceError:
    with pytest.raises(SourceError) as caught:
        parse_source(data)
    return caught.value


def with_body(body: str) -> bytes:
    return tar_gz({"paper.tex": SAMPLE_LATEX.replace("Thanks.", body).encode()})


WITHOUT_DOCUMENT = tar_gz(
    {
        "00README.json": json.dumps(
            {"sources": [{"usage": "toplevel", "filename": "main.tex"}]}
        ).encode(),
        "main.tex": b"\\documentclass{article}\nNo document begins here.\n",
    }
)
TEXT = filler(300)


@pytest.mark.parametrize(
    ("outcome", "sentence", "expected"),
    [
        ("parse_error", lambda: raised_by(b"\\input harvmac\n\\bye\n").detail, "no_document"),
        ("parse_error", lambda: raised_by(WITHOUT_DOCUMENT).detail, "no_document"),
        (
            "parse_error",
            lambda: raised_by(with_body("\\input{sections/intro}")).detail,
            "missing_file",
        ),
        (
            "parse_error",
            lambda: raised_by(with_body("\\include{a} \\include{b}")).detail,
            "missing_file",
        ),
        (
            "parse_error",
            lambda: raised_by(with_body("\\import{a/}{b}")).detail,
            "unfollowed_command",
        ),
        (
            "parse_error",
            lambda: raised_by(with_body("\\input{gone} \\InputIfFileExists{a}{}{}")).detail,
            "unfollowed_command",  # both: the sentence names a command
        ),
        (
            "parse_error",
            lambda: (
                raised_by(b"\\documentclass{article}\\begin{document}Short.\\end{document}").detail
            ),
            "too_short",
        ),
        (
            "parse_error",
            lambda: check((Section("1", "A", 1, TEXT), Section("1", "B", 1, TEXT)))[1],
            "duplicate_id",
        ),
        (
            "parse_error",
            lambda: check((Section("1", "A", 1, TEXT), Section("1.1", "B", 2, "elsewhere", 0)))[1],
            "misplaced_subsection",
        ),
        (
            "parse_error",
            lambda: check((Section("1", "A", 1, TEXT), Section("1.1", "B", 2, TEXT[:50], 0)))[1],
            "misplaced_subsection",
        ),
        ("parse_error", lambda: check(())[1], "no_sections"),
        ("no_full_text", lambda: raised_by(b"%PDF-1.7 ...").detail, "not_tex"),
        ("no_full_text", lambda: "", "no_source"),
        ("parse_error", lambda: "a sentence the parser has yet to learn", "other"),
        ("no_full_text", lambda: "another reason", "other"),
        ("not_found", lambda: "", "other"),
    ],
)
def test_what_the_parser_says_is_sorted_into_kinds(outcome, sentence, expected):
    # The sentences are made by the parser itself, here, so that a sentence reworded in
    # arxiv_latex.py cannot slip into "other" unseen.
    assert branch(outcome, sentence()) == expected


def test_a_download_too_large_to_unpack_has_its_kind(monkeypatch):
    monkeypatch.setattr(arxiv_latex, "_MAX_UNPACKED_BYTES", 10)
    assert branch("parse_error", raised_by(gzip.compress(b"x" * 11)).detail) == "too_large"


@pytest.mark.parametrize("kind", [ErrorKind.UPSTREAM_BUSY, ErrorKind.TIMEOUT])
def test_what_arxiv_did_not_answer_is_no_outcome(kind):
    source = Memory({"2608.00001v1": SourceError(kind, "2608.00001v1")})
    assert survey_one(source, drawn()) == {
        "record": "paper",
        "archive": "hep-ph",
        "rank": 1,
        "id": "2608.00001v1",
        "primary": "hep-ph",
        "outcome": "unanswered",
        "kind": kind.value,
        "detail": "",
    }


@pytest.mark.parametrize(
    ("error", "outcome", "kind", "detail"),
    [
        (
            SourceError(ErrorKind.PARSE_ERROR, "2608.00001v1: no file contains \\begin{document}"),
            "parse_error",
            "no_document",
            "no file contains \\begin{document}",
        ),
        (SourceError(ErrorKind.NO_FULL_TEXT, "2608.00001v1"), "no_full_text", "no_source", ""),
        (SourceError(ErrorKind.NOT_FOUND, "2608.00001v1"), "not_found", "other", ""),
    ],
)
def test_a_failure_that_is_about_the_paper_is_an_outcome_with_its_kind(
    error, outcome, kind, detail
):
    line = survey_one(Memory({"2608.00001v1": error}), drawn())
    assert (line["outcome"], line["branch"], line["detail"]) == (outcome, kind, detail)
    assert "kind" not in line


def test_an_error_nobody_foresaw_is_written_down_without_its_message():
    # The message of such an error can quote the paper. The line names the kind only.
    source = Memory({"2608.00001v1": ValueError("a sentence from the paper")})
    line = survey_one(source, drawn())
    assert (line["outcome"], line["detail"]) == ("unexpected", "the code raised ValueError")
    assert "sentence" not in json.dumps(line)


def test_a_paper_that_comes_back_in_another_version_is_not_taken_for_the_one_drawn():
    line = survey_one(Memory({"2608.00001v1": a_paper("2608.00001v2")}), drawn())
    assert (line["outcome"], line["detail"]) == (
        "unexpected",
        "asked for 2608.00001v1, given 2608.00001v2",
    )


def test_stopping_by_hand_is_not_swallowed():
    with pytest.raises(KeyboardInterrupt):
        survey_one(Memory({"2608.00001v1": KeyboardInterrupt()}), drawn())


def test_the_papers_are_asked_for_rank_by_rank_across_the_archives():
    papers = [
        drawn(f"2608.{n:05d}v1", archive, rank)
        for n, (archive, rank) in enumerate(
            [
                ("hep-ph", 1),
                ("hep-ph", 2),
                ("hep-ph", 3),
                ("astro-ph", 1),
                ("astro-ph", 2),
                ("nlin", 1),
            ]
        )
    ]
    assert [(each.archive, each.rank) for each in walk(papers)] == [
        ("hep-ph", 1),
        ("astro-ph", 1),
        ("nlin", 1),
        ("hep-ph", 2),
        ("astro-ph", 2),
        ("hep-ph", 3),
    ]


# --- the command -------------------------------------------------------------------------------

IDS = {
    "hep-ph": ["2608.00001v1", "2608.00002v1", "2608.00003v2"],
    "astro-ph": ["2608.00101v1", "2608.00102v1", "2608.00103v1"],
}


def sample_file(folder: Path, ids=IDS) -> Path:
    """A sample as survey.sample writes it, of papers that the tests name."""
    folder.mkdir(parents=True, exist_ok=True)
    listed = [
        Listed(name, "hep-ph" if archive == "hep-ph" else "astro-ph.GA", "2026-08-01T10:00:00Z")
        for archive, names in ids.items()
        for name in names
    ]
    papers = draw(listed, PLAN)
    counts = {
        archive: {"listed": 9, "primary": len(names), "drawn": len(names)}
        for archive, names in ids.items()
    }
    stamp = {"name": "test-1", "sha256": "1" * 64, "commit": COMMIT}
    named = {"file": "population.jsonl", "sha256": "2" * 64, "papers": len(listed)}
    path = folder / "sample.jsonl"
    write_lines(path, sample_lines(papers, counts, PLAN, stamp, committed(), named))
    return path


def answers(changes: dict | None = None) -> dict:
    """Every paper of IDS split, unless `changes` says otherwise of one."""
    found = {name: a_paper(name) for names in IDS.values() for name in names}
    return found | (changes or {})


BUSY = SourceError(ErrorKind.UPSTREAM_BUSY, "2608.00102v1")


def test_the_command_writes_a_line_for_every_paper_and_names_what_made_them(tmp_path, capsys):
    sample = sample_file(tmp_path)
    out = tmp_path / "out" / "outcomes.jsonl"
    not_tex = "2608.00002v1: the source is a PDF, PostScript or DVI file"
    source = Memory(
        answers(
            {
                "2608.00002v1": SourceError(ErrorKind.NO_FULL_TEXT, not_tex),
                "2608.00101v1": SourceError(
                    ErrorKind.PARSE_ERROR, "2608.00101v1: no file contains \\begin{document}"
                ),
                "2608.00103v1": a_paper("2608.00103v1", NO_SECTIONS_LATEX),
            }
        )
    )

    code = run.main(["--sample", str(sample), "--out", str(out)], source=source, origin=committed)

    assert code == 0
    head, papers = read_outcomes(out)
    assert head["sample"] == {"file": "sample.jsonl", "sha256": file_digest(sample)}
    assert head["plan"] == {"name": "test-1", "sha256": "1" * 64, "commit": COMMIT}
    assert head["code"] == {"commit": COMMIT, "modified": False}
    assert (head["parser_version"], head["section_char_limit"]) == (PARSER_VERSION, 20_000)
    assert (head["papers"], head["unanswered"]) == (6, 0)
    assert head["began"] <= head["ended"]
    # The lines stand as the sample has them, whatever the order they were asked in.
    drawn_papers = read_sample(sample).papers
    assert [line["id"] for line in papers] == [each.arxiv_id for each in drawn_papers]
    assert source.asked == [each.arxiv_id for each in walk(drawn_papers)]
    by_id = {line["id"]: line for line in papers}
    assert by_id["2608.00002v1"]["outcome"] == "no_full_text"
    assert by_id["2608.00002v1"]["branch"] == "not_tex"
    assert by_id["2608.00101v1"]["branch"] == "no_document"
    assert by_id["2608.00103v1"]["no_headings"] is True

    printed = capsys.readouterr().out
    assert f"sample    {sample} | sha256 {file_digest(sample)} | 6 paper(s)" in printed
    assert f"parser {PARSER_VERSION}" in printed
    assert "no_full_text (not_tex) | the source is a PDF, PostScript or DVI file" in printed
    table = printed[printed.index("archive ") :].splitlines()
    assert [row.split() for row in table[:4]] == [
        ["archive", "papers", "ok", "no_full_text", "parse_error"],
        ["hep-ph", "3", "2", "1", "0"],
        ["astro-ph", "3", "2", "0", "1"],
        ["all", "6", "4", "1", "1"],
    ]
    assert "no_full_text by what was said: not_tex 1" in printed
    assert "parse_error by what was said: no_document 1" in printed
    assert (
        "of the 4 split: 1 without a section heading, 0 with a piece of more than 20000" in printed
    )


def test_the_file_holds_identifiers_counts_and_sentences_and_no_text_of_a_paper(tmp_path):
    out = tmp_path / "outcomes.jsonl"
    run.main(
        ["--sample", str(sample_file(tmp_path)), "--out", str(out)],
        source=Memory(answers()),
        origin=committed,
    )
    data = out.read_bytes()
    assert b"word1" not in data and b"title" not in data.lower() and b"A. Author" not in data
    assert b"\r" not in data
    for line in lines_of(out)[1:]:
        assert set(line) == {
            "record",
            "archive",
            "rank",
            "id",
            "primary",
            "outcome",
            "sections",
            "subsections",
            "chars",
            "largest",
            "no_headings",
        }


def test_a_paper_without_an_answer_is_asked_for_again_by_the_next_run(tmp_path, capsys):
    sample, out = sample_file(tmp_path), tmp_path / "outcomes.jsonl"
    source = Memory(answers({"2608.00102v1": [BUSY, a_paper("2608.00102v1")]}))
    argv = ["--sample", str(sample), "--out", str(out)]

    assert run.main(argv, source=source, origin=committed) == 1
    head, papers = read_outcomes(out)
    assert (head["papers"], head["unanswered"]) == (6, 1)
    assert [line["outcome"] for line in papers if line["id"] == "2608.00102v1"] == ["unanswered"]
    printed = capsys.readouterr().out
    assert "unanswered (upstream_busy)" in printed
    assert "1 paper(s) unanswered: run the command again" in printed
    assert ["archive", "papers", "ok", "unanswered"] in [
        row.split() for row in printed.splitlines()
    ]

    assert run.main(argv, source=source, origin=committed) == 0
    head, papers = read_outcomes(out)
    assert head["unanswered"] == 0 and {line["outcome"] for line in papers} == {"ok"}
    assert "is there with 1 paper(s) unanswered; it is written anew" in capsys.readouterr().out


def test_a_run_that_is_stopped_by_hand_leaves_the_file_that_was_there(tmp_path, capsys):
    sample, out = sample_file(tmp_path), tmp_path / "outcomes.jsonl"
    argv = ["--sample", str(sample), "--out", str(out)]
    assert run.main(argv, source=Memory(answers()), origin=committed) == 0
    before = out.read_bytes()

    third = walk(read_sample(sample).papers)[2].arxiv_id
    stopped = Memory(answers({third: KeyboardInterrupt()}))
    assert run.main(argv, source=stopped, origin=committed) == 130
    assert out.read_bytes() == before and list(tmp_path.glob("*.tmp")) == []
    assert "stopped by hand; no file was written" in capsys.readouterr().err

    assert (
        run.main(
            ["--sample", str(sample), "--out", str(tmp_path / "new.jsonl")],
            source=stopped,
            origin=committed,
        )
        == 130
    )
    assert not (tmp_path / "new.jsonl").exists()


def test_a_first_try_asks_for_the_front_of_the_walk_and_writes_nothing(tmp_path, capsys):
    sample, out = sample_file(tmp_path), tmp_path / "outcomes.jsonl"
    source = Memory(answers())
    # Not in a commit, and that is no matter: a first try leaves no file behind.
    unknown = {"commit": None, "modified": None}

    code = run.main(
        ["--sample", str(sample), "--out", str(out), "--limit", "2"],
        source=source,
        origin=lambda file=None: unknown,
    )

    assert code == 0 and not out.exists()
    assert source.asked == [each.arxiv_id for each in walk(read_sample(sample).papers)[:2]]
    assert {each.rank for each in walk(read_sample(sample).papers)[:2]} == {1}
    assert "a first try with 2 of 6 paper(s). Nothing was written." in capsys.readouterr().out
    assert run.main(["--sample", str(sample), "--limit", "0"], source=source, origin=committed) == 2


@pytest.mark.parametrize(
    ("there", "said"),
    [
        (
            '{"record": "outcomes", "sample": {"sha256": "another"}}\n',
            "holds the outcomes of another sample",
        ),
        ('{"record": "sample"}\n', "is there and is no outcomes file"),
        ("notes of mine\n", "is there and is no outcomes file"),
    ],
)
def test_the_command_does_not_write_over_a_file_that_is_something_else(
    tmp_path, capsys, there, said
):
    sample, out = sample_file(tmp_path), tmp_path / "outcomes.jsonl"
    out.write_text(there, encoding="utf-8")
    source = Memory(answers())

    assert (
        run.main(["--sample", str(sample), "--out", str(out)], source=source, origin=committed) == 2
    )
    assert said in capsys.readouterr().err
    assert out.read_text(encoding="utf-8") == there and source.asked == []


def test_the_command_does_not_start_when_no_commit_names_the_code(tmp_path, capsys):
    sample, out = sample_file(tmp_path), tmp_path / "outcomes.jsonl"
    source = Memory(answers())
    for origin in ({"commit": COMMIT, "modified": True}, {"commit": None, "modified": None}):
        code = run.main(
            ["--sample", str(sample), "--out", str(out)],
            source=source,
            origin=lambda file=None, o=origin: o,
        )
        assert (
            code == 2 and "files the repository keeps have been changed" in capsys.readouterr().err
        )
    assert source.asked == [] and not out.exists()


def test_a_sample_that_cannot_be_read_ends_the_command(tmp_path, capsys):
    sample = sample_file(tmp_path)
    lines = lines_of(sample)
    lines[-1]["id"] = "2608.09999v1"  # a paper put in by hand
    sample.write_text("".join(json.dumps(line) + "\n" for line in lines), encoding="utf-8")
    source = Memory(answers())

    assert (
        run.main(
            ["--sample", str(sample), "--out", str(tmp_path / "o.jsonl")],
            source=source,
            origin=committed,
        )
        == 2
    )
    assert (
        "cannot read the sample: sample.jsonl: '2608.09999v1' does not have the hash"
        in capsys.readouterr().err
    )
    assert (
        run.main(
            ["--sample", str(tmp_path / "none.jsonl"), "--out", "o"],
            source=source,
            origin=committed,
        )
        == 2
    )
    assert (
        run.main(["--sample", str(sample_file(tmp_path / "ok"))], source=source, origin=committed)
        == 2
    )
    assert "--out: where to write the outcomes" in capsys.readouterr().err
    assert source.asked == []


def test_an_outcomes_file_with_a_line_that_names_no_paper_or_no_outcome_is_refused(tmp_path):
    path = tmp_path / "outcomes.jsonl"
    for line in (
        '{"record": "paper", "id": "2608.00001v1", "outcome": "fine"}',
        '{"record": "paper", "outcome": "ok"}',
    ):
        path.write_text('{"record": "outcomes"}\n' + line + "\n", encoding="utf-8")
        with pytest.raises(RecordError, match="a line without a paper or without an outcome"):
            read_outcomes(path)
    path.write_text('{"record": "outcomes"}\n', encoding="utf-8")
    assert read_outcomes(path) == ({"record": "outcomes"}, [])


def test_what_the_lines_say_is_counted():
    lines = [
        {"archive": "hep-ph", "outcome": "ok", "largest": 20_000, "no_headings": False},
        {"archive": "hep-ph", "outcome": "ok", "largest": 20_001, "no_headings": True},
        {"archive": "hep-ph", "outcome": "parse_error", "branch": "no_document"},
        {"archive": "nlin", "outcome": "parse_error", "branch": "missing_file"},
        {"archive": "nlin", "outcome": "parse_error", "branch": "no_document"},
        {"archive": "nlin", "outcome": "unanswered", "kind": "timeout"},
        {"archive": "nlin", "outcome": "unexpected"},
    ]
    found = tally(lines)

    assert found.papers == 7 and found.unanswered == 1
    assert found.by_archive == {
        "hep-ph": {"ok": 2, "parse_error": 1},
        "nlin": {"parse_error": 2, "unanswered": 1, "unexpected": 1},
    }
    assert found.branches == {"parse_error": {"no_document": 2, "missing_file": 1}}
    # A piece of exactly the limit is read in one call.
    assert (found.no_headings, found.over_limit) == (1, 1)
    assert [found.count(name) for name in OUTCOMES] == [2, 0, 3, 0, 1, 1]
    assert run.table(found)[-1] == (
        "of the 2 split: 1 without a section heading, 1 with a piece of more than 20000 characters"
    )


# --- with the real source: what is on disk is not asked for again ----------------------------

PAGE = b"<html><body>Not the paper.</body></html>"


class SurveyArxiv:
    """arXiv for the lookup of one paper and for its download. `downloads` says what comes."""

    def __init__(self, downloads: dict):
        self.downloads = downloads
        self.requests: list[str] = []

    def handler(self, request: httpx2.Request) -> httpx2.Response:
        if request.url.path == "/api/query":
            name = request.url.params["id_list"]
            self.requests.append(f"lookup {name}")
            return httpx2.Response(
                200, content=feed(1, 0, [entry(name, "hep-ph", "2026-08-01T10:00:00Z")])
            )
        name = request.url.path.removeprefix("/e-print/")
        self.requests.append(f"download {name}")
        answers = self.downloads[name]
        status, body = answers.pop(0) if len(answers) > 1 else answers[0]
        return httpx2.Response(status, content=body)

    def source(self, cache_dir) -> ArxivSource:
        fetcher = Fetcher(
            cache_dir, transport=httpx2.MockTransport(self.handler), sleep=lambda seconds: None
        )
        return ArxivSource(fetcher)


def test_a_second_run_asks_arxiv_only_for_what_has_no_answer_on_disk(tmp_path):
    good = (200, tar_gz({"paper.tex": SAMPLE_LATEX.encode()}))
    plain_tex = (200, b"\\input harvmac\n\\bye\n")
    arxiv = SurveyArxiv(
        {
            "2608.00001v1": [good],
            "2608.00002v1": [(200, b"%PDF-1.7 ...")],
            "2608.00003v2": [plain_tex],
            "2608.00101v1": [(404, b"")],  # listed, and nothing to download
            "2608.00102v1": [(200, PAGE), good],  # a page in place of the files, once
            "2608.00103v1": [(503, b""), (503, b""), (503, b""), (503, b""), good],
        }
    )
    sample, out, cache = sample_file(tmp_path), tmp_path / "outcomes.jsonl", tmp_path / "cache"
    argv = ["--sample", str(sample), "--out", str(out)]

    assert run.main(argv, source=arxiv.source(cache), origin=committed) == 1
    by_id = {line["id"]: line for line in read_outcomes(out)[1]}
    assert {name: line["outcome"] for name, line in by_id.items()} == {
        "2608.00001v1": "ok",
        "2608.00002v1": "no_full_text",
        "2608.00003v2": "parse_error",
        "2608.00101v1": "no_full_text",
        "2608.00102v1": "unanswered",
        "2608.00103v1": "unanswered",
    }
    # The sentence stands without the identifier the source put in front of it.
    assert by_id["2608.00002v1"]["detail"] == "the source is a PDF, PostScript or DVI file"
    assert (by_id["2608.00003v2"]["branch"], by_id["2608.00101v1"]["branch"]) == (
        "no_document",
        "no_source",
    )
    assert by_id["2608.00102v1"] | {"rank": 0} == {
        "record": "paper",
        "archive": "astro-ph",
        "rank": 0,
        "id": "2608.00102v1",
        "primary": "astro-ph.GA",
        "outcome": "unanswered",
        "kind": "upstream_busy",
        "detail": "the download is a web page, not the paper's files",
    }
    assert (by_id["2608.00103v1"]["kind"], by_id["2608.00103v1"]["detail"]) == ("upstream_busy", "")
    assert len(arxiv.requests) == 6 + 1 + 1 + 1 + 1 + 1 + 4

    # A new process: nothing in memory, the same folder of downloads.
    arxiv.requests.clear()
    assert run.main(argv, source=arxiv.source(cache), origin=committed) == 0
    assert sorted(arxiv.requests) == [
        "download 2608.00101v1",  # "nothing there" is not kept, so it is asked for again
        "download 2608.00102v1",
        "download 2608.00103v1",
    ]
    again = {line["id"]: line["outcome"] for line in read_outcomes(out)[1]}
    assert again == {
        **{name: line["outcome"] for name, line in by_id.items()},
        "2608.00102v1": "ok",
        "2608.00103v1": "ok",
    }


def under_its_own_name(monkeypatch, module, arxiv, cache_dir) -> list:
    """Make a command build its Fetcher over the scripted arXiv, and keep what it asked for."""
    built: list = []

    def fetcher(folder, user_agent):
        built.append((folder, user_agent))
        return Fetcher(
            folder, transport=httpx2.MockTransport(arxiv.handler), sleep=lambda seconds: None
        )

    monkeypatch.setenv(CACHE_ENV, str(cache_dir))
    monkeypatch.setattr(module, "Fetcher", fetcher)
    return built


def test_left_to_itself_the_command_reads_through_the_folder_of_downloads(
    tmp_path, monkeypatch, capsys
):
    good = (200, tar_gz({"paper.tex": SAMPLE_LATEX.encode()}))
    arxiv = SurveyArxiv({name: [good] for names in IDS.values() for name in names})
    cache = tmp_path / "downloads"
    cache.mkdir()
    (cache / "from-before").write_bytes(bytes(3_000_000))
    built = under_its_own_name(monkeypatch, run, arxiv, cache)
    out = tmp_path / "outcomes.jsonl"

    assert (
        run.main(["--sample", str(sample_file(tmp_path)), "--out", str(out)], origin=committed) == 0
    )

    assert built == [(cache, "hepph-paper-miner/survey")]
    assert {line["outcome"] for line in read_outcomes(out)[1]} == {"ok"}
    # What this run added, not what the folder held before it.
    added = sum(path.stat().st_size for path in cache.rglob("*") if path.is_file()) - 3_000_000
    assert 0 < added < 100_000
    assert (
        f"the folder of downloads grew by {added / 1e6:.1f} MB: {cache}" in capsys.readouterr().out
    )
    assert run._folder_bytes(cache) == added + 3_000_000
