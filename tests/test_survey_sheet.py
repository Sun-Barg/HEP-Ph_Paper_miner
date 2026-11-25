"""The sheet for holding outlines against papers: which papers, what is on it, reading it back.

The outcomes are made here by the survey command from papers held in memory. No network.
"""

import csv
import json
from pathlib import Path

import pytest
from conftest import SAMPLE_LATEX, tar_gz
from test_survey_plan import a_plan
from test_survey_run import (
    BUSY,
    NO_SECTIONS_LATEX,
    Memory,
    SurveyArxiv,
    a_paper,
    under_its_own_name,
)
from test_survey_sample import COMMIT, committed, lines_of, no_commit

from hepph_paper_miner.agent.origin import file_digest
from hepph_paper_miner.sources.base import ErrorKind, SourceError
from hepph_paper_miner.survey import run, sheet
from hepph_paper_miner.survey.listing import Listed
from hepph_paper_miner.survey.plan import load_plan
from hepph_paper_miner.survey.records import write_lines
from hepph_paper_miner.survey.sample import draw, read_sample, sample_lines
from hepph_paper_miner.survey.sheet import COLUMNS, SheetError, read_sheet, to_check

NO_SOURCE = SourceError(ErrorKind.NO_FULL_TEXT, "x")


def line(archive: str, rank: int, outcome: str = "ok") -> dict:
    return {"archive": archive, "rank": rank, "id": f"{archive}-{rank}", "outcome": outcome}


def test_the_first_papers_of_every_archive_that_were_split_are_checked():
    papers = [
        line("hep-ph", 3),
        line("hep-ph", 1, "parse_error"),
        line("hep-ph", 2),
        line("hep-ph", 4),
        line("nlin", 1),
        line("nlin", 2, "no_full_text"),
    ]
    chosen, waiting = to_check(papers, 2)
    # In the order of the sample, whatever order the lines come in. nlin has one only.
    assert [each["id"] for each in chosen] == ["hep-ph-2", "hep-ph-3", "nlin-1"]
    assert waiting == []


def test_an_unanswered_paper_that_could_still_belong_on_the_sheet_is_named():
    papers = [
        line("hep-ph", 1),
        line("hep-ph", 2, "unanswered"),  # in front of the last paper chosen: it could displace it
        line("hep-ph", 3),
        line("hep-ph", 4, "unanswered"),  # behind it: whatever it turns out to be, the sheet stands
        line("nlin", 1),
        line("nlin", 2, "unanswered"),  # nlin is one short, so this one could fill the place
    ]
    chosen, waiting = to_check(papers, 2)
    assert [each["id"] for each in chosen] == ["hep-ph-1", "hep-ph-3", "nlin-1"]
    assert [each["id"] for each in waiting] == ["hep-ph-2", "nlin-2"]


# --- the command -------------------------------------------------------------------------------

IDS = {
    "hep-ph": [f"2608.{n:05d}v1" for n in range(1, 5)],
    "astro-ph": [f"2608.{n:05d}v1" for n in range(101, 104)],
}
EQUALS_LATEX = SAMPLE_LATEX.replace("\\section{Introduction}", "\\section{=1+1}")


class Survey:
    """A plan, a sample and the outcomes of a survey in a folder, and the papers behind them."""

    def __init__(self, folder: Path, failing: dict | None = None, other_latex: dict | None = None):
        folder.mkdir(parents=True, exist_ok=True)
        self.folder = folder
        self.plan = folder / "plan.json"
        self.plan.write_text(json.dumps(a_plan()), encoding="utf-8")
        plan = load_plan(self.plan)
        listed = [
            Listed(name, "hep-ph" if archive == "hep-ph" else "astro-ph.GA", "2026-08-01T10:00:00Z")
            for archive, names in IDS.items()
            for name in names
        ]
        counts = {
            a: {"listed": 9, "primary": len(n), "drawn": min(3, len(n))} for a, n in IDS.items()
        }
        stamp = {"name": plan.name, "sha256": plan.sha256, "commit": COMMIT}
        named = {"file": "population.jsonl", "sha256": "2" * 64, "papers": len(listed)}
        self.sample = folder / "sample.jsonl"
        write_lines(
            self.sample, sample_lines(draw(listed, plan), counts, plan, stamp, committed(), named)
        )
        self.drawn = read_sample(self.sample).papers
        self.papers = {
            each.arxiv_id: a_paper(each.arxiv_id, (other_latex or {}).get(each.rank, SAMPLE_LATEX))
            for each in self.drawn
        }
        # `failing` names papers by (archive, rank): the identifiers follow from the seed.
        self.answers = dict(self.papers)
        for (archive, rank), answer in (failing or {}).items():
            self.answers[self.named(archive, rank)] = answer
        self.outcomes = folder / "outcomes.jsonl"
        run.main(
            ["--sample", str(self.sample), "--out", str(self.outcomes)],
            source=Memory(self.answers),
            origin=committed,
        )
        self.sheet = folder / "private" / "sheet.csv"
        self.checks = folder / "checks.jsonl"

    def named(self, archive: str, rank: int) -> str:
        return next(
            each.arxiv_id for each in self.drawn if (each.archive, each.rank) == (archive, rank)
        )

    def argv(self, *extra: str) -> list[str]:
        files = [
            "--plan",
            str(self.plan),
            "--sample",
            str(self.sample),
            "--outcomes",
            str(self.outcomes),
        ]
        return [*files, "--sheet", str(self.sheet), *extra]

    def write(self, *extra: str, source=None, origin=committed) -> int:
        return sheet.main(self.argv(*extra), source=source or Memory(self.papers), origin=origin)

    def collect(self, *extra: str, origin=committed) -> int:
        return sheet.main(self.argv("--checks", str(self.checks), *extra), origin=origin)

    def rows(self) -> list[dict]:
        with self.sheet.open(encoding="utf-8-sig", newline="") as stream:
            return list(csv.DictReader(stream))

    def fill(self, verdicts: dict | None = None, default=("same", "same", "")) -> None:
        """Write verdicts on the rows of the papers, as a person would in a spreadsheet."""
        rows = self.rows()
        for row in rows:
            if row["arxiv_id"]:
                found = (verdicts or {}).get(row["arxiv_id"], default)
                row["sections"], row["subsections"], row["note"] = found
        with self.sheet.open("w", encoding="utf-8-sig", newline="") as stream:
            writer = csv.DictWriter(stream, COLUMNS)
            writer.writeheader()
            writer.writerows(rows)


def test_the_sheet_shows_each_paper_and_under_it_the_outline_the_server_gives(tmp_path, capsys):
    survey = Survey(tmp_path, failing={("hep-ph", 1): NO_SOURCE})
    assert survey.write() == 0

    rows = survey.rows()
    assert survey.sheet.read_bytes().startswith(b"\xef\xbb\xbf")  # for Excel
    assert tuple(rows[0]) == COLUMNS
    papers = [row for row in rows if row["arxiv_id"]]
    # Two of an archive (the plan), the first that were split: not the first of hep-ph.
    assert [row["arxiv_id"] for row in papers] == [
        survey.named("hep-ph", 2),
        survey.named("hep-ph", 3),
        survey.named("astro-ph", 1),
        survey.named("astro-ph", 2),
    ]
    first = papers[0]
    assert first["number"] == "1" and first["archive"] == "hep-ph"
    assert first["link"] == f"https://arxiv.org/abs/{first['arxiv_id']}"
    assert first["chars"] == str(survey.papers[first["arxiv_id"]].chars)
    assert (first["sections"], first["subsections"], first["note"]) == ("", "", "")
    outline = [row for row in rows if row["number"] == "1" and not row["arxiv_id"]]
    assert [(row["section_id"], row["title"]) for row in outline] == [
        ("1", "Introduction"),
        ("2", "Methods and the $\\mathcal{O}(1)$ case"),
        ("2.1", "  Data"),
        ("2.u1", "  A side note"),
        ("2.2", "  Fit"),
        ("u1", "Acknowledgements"),
        ("A", "Extra tables"),
        ("A.1", "  More"),
    ]
    assert all(row["chars"].isdigit() and not row["link"] for row in outline)
    printed = capsys.readouterr().out
    assert "4 paper(s) on the sheet" in printed and "at most 2 of an archive" in printed
    assert 'write "same" or "differ" under sections and under subsections' in printed


def test_a_title_that_begins_like_a_formula_is_kept_as_text(tmp_path):
    survey = Survey(tmp_path, other_latex={1: EQUALS_LATEX})
    assert survey.write() == 0
    titles = [row["title"] for row in survey.rows() if row["section_id"] == "1"]
    assert " =1+1" in titles and "=1+1" not in titles


def test_the_sheet_needs_no_commit_and_does_not_write_over_a_sheet(tmp_path, capsys):
    survey = Survey(tmp_path)
    assert survey.write(origin=no_commit) == 0  # it is no file of the repository
    before = survey.sheet.read_bytes()
    assert survey.write() == 2
    assert "is there already; move it away first" in capsys.readouterr().err
    assert survey.sheet.read_bytes() == before


def test_the_sheet_is_refused_while_an_unanswered_paper_could_belong_on_it(tmp_path, capsys):
    survey = Survey(tmp_path, failing={("hep-ph", 1): BUSY})
    assert survey.write() == 1
    said = capsys.readouterr().err
    assert "1 unanswered paper(s) could still belong on the sheet" in said
    assert survey.named("hep-ph", 1) in said and not survey.sheet.exists()

    # Taken as it is: not split, so the next paper of the archive stands in its place.
    assert survey.write("--pass-over-unanswered") == 0
    hep_ph = [row["arxiv_id"] for row in survey.rows() if row["archive"] == "hep-ph"]
    assert hep_ph == [survey.named("hep-ph", 2), survey.named("hep-ph", 3)]


def test_an_unanswered_paper_behind_the_last_one_checked_does_not_hold_the_sheet_up(tmp_path):
    survey = Survey(tmp_path, failing={("hep-ph", 3): BUSY})
    assert survey.write() == 0


def changed(path: Path, change) -> None:
    lines = lines_of(path)
    change(lines)
    path.write_text("".join(json.dumps(each) + "\n" for each in lines), encoding="utf-8")


@pytest.mark.parametrize(
    ("spoil", "said"),
    [
        (
            lambda survey: survey.plan.write_text(
                json.dumps(a_plan(**{"outline_check.per_archive": 1})), encoding="utf-8"
            ),
            "sample.jsonl was not drawn under plan.json",
        ),
        (
            lambda survey: changed(
                survey.sample, lambda lines: lines[0].update(drawn="another day")
            ),
            "outcomes.jsonl are not the outcomes of sample.jsonl",
        ),
        (
            lambda survey: changed(survey.outcomes, lambda lines: lines.pop()),
            "outcomes.jsonl does not hold the papers of the sample",
        ),
        (
            lambda survey: changed(
                survey.outcomes, lambda lines: lines[0].update(parser_version="3")
            ),
            "the outcomes were made by parser 3, and this code has parser 5",
        ),
    ],
)
def test_files_that_are_not_of_one_survey_give_no_sheet(tmp_path, capsys, spoil, said):
    survey = Survey(tmp_path)
    spoil(survey)
    assert survey.write() == 1
    assert said in capsys.readouterr().err and not survey.sheet.exists()


def test_a_paper_that_splits_differently_now_is_not_shown_as_what_was_counted(tmp_path, capsys):
    survey = Survey(tmp_path)
    name = survey.named("astro-ph", 1)
    other = Memory(survey.papers | {name: a_paper(name, NO_SECTIONS_LATEX)})
    assert survey.write(source=other) == 1
    said = capsys.readouterr().err
    assert f"{name} splits into" in said and "the survey wrote down" in said
    assert not survey.sheet.exists()


def test_a_paper_that_cannot_be_had_again_gives_no_sheet(tmp_path, capsys):
    survey = Survey(tmp_path)
    name = survey.named("astro-ph", 2)
    assert survey.write(source=Memory(survey.papers | {name: BUSY})) == 1
    assert f"{name} could not be had again (upstream_busy)" in capsys.readouterr().err
    assert not survey.sheet.exists()


def test_files_that_cannot_be_read_end_the_command(tmp_path, capsys):
    survey = Survey(tmp_path)
    survey.outcomes.write_text("notes of mine\n", encoding="utf-8")
    assert survey.write() == 2
    assert "cannot read what the sheet is made from: outcomes.jsonl" in capsys.readouterr().err


# --- reading the sheet back --------------------------------------------------------------------


def test_the_verdicts_go_into_a_file_that_holds_no_title(tmp_path, capsys):
    # One paper is unanswered, behind the papers on the sheet: nothing is passed over.
    survey = Survey(tmp_path, failing={("hep-ph", 3): BUSY})
    survey.write()
    second = survey.named("hep-ph", 2)
    survey.fill({second: (" Same", "DIFFER ", "a subsection of the paper has no row")})
    capsys.readouterr()

    assert survey.collect() == 0

    head, *papers = lines_of(survey.checks)
    assert head == {
        "record": "outline_check",
        "outcomes": {"file": "outcomes.jsonl", "sha256": file_digest(survey.outcomes)},
        "sample": {"file": "sample.jsonl", "sha256": file_digest(survey.sample)},
        "plan": {"name": "test-1", "sha256": file_digest(survey.plan), "commit": COMMIT},
        "code": {"commit": COMMIT, "modified": False},
        "per_archive": 2,
        "unanswered_passed_over": 0,
        "written": head["written"],
        "papers": 4,
        "same": 3,
    }
    assert papers[1] == {
        "record": "paper",
        "archive": "hep-ph",
        "rank": 2,
        "id": second,
        "sections": "same",
        "subsections": "differ",
        "note": "a subsection of the paper has no row",
    }
    assert [each["id"] for each in papers] == [
        row["arxiv_id"] for row in survey.rows() if row["arxiv_id"]
    ]
    data = survey.checks.read_bytes()
    for title in (b"Introduction", b"Methods", b"A title no line keeps", b"Acknowledgements"):
        assert title not in data
    assert b"\r" not in data
    printed = capsys.readouterr().out
    assert (
        "4 paper(s) checked: the sections are the same in 4, the subsections in 3, both in 3"
        in printed
    )


def test_a_note_in_another_script_is_kept_as_it_was_written(tmp_path):
    survey = Survey(tmp_path)
    survey.write()
    first = survey.named("hep-ph", 1)
    survey.fill({first: ("differ", "same", "감사의 글 제목이 개요에 없다")})
    assert survey.collect() == 0
    assert "감사의 글 제목이 개요에 없다" in survey.checks.read_text(encoding="utf-8")


def test_the_papers_passed_over_are_counted_in_the_file(tmp_path):
    survey = Survey(tmp_path, failing={("hep-ph", 1): BUSY})
    survey.write("--pass-over-unanswered")
    survey.fill()
    assert survey.collect() == 1  # the same has to be said when the sheet is read back
    assert survey.collect("--pass-over-unanswered") == 0
    assert lines_of(survey.checks)[0]["unanswered_passed_over"] == 1


@pytest.mark.parametrize(
    ("verdict", "said"),
    [
        (("same", "", ""), "nothing under subsections yet"),
        (("", "same", ""), "nothing under sections yet"),
        (("same", "mostly", ""), "'mostly' under subsections is neither same nor differ"),
        (("yes", "same", ""), "'yes' under sections is neither same nor differ"),
        (("differ", "same", ""), "something differs, and the note does not say what"),
        (("same", "differ", "  "), "something differs, and the note does not say what"),
    ],
)
def test_a_paper_without_a_verdict_that_can_be_counted_gives_no_file(
    tmp_path, capsys, verdict, said
):
    survey = Survey(tmp_path)
    survey.write()
    third = survey.named("astro-ph", 1)
    survey.fill({third: verdict})

    assert survey.collect() == 1
    refused = capsys.readouterr().err
    assert said in refused and f"({third})" in refused and "sheet.csv line " in refused
    assert not survey.checks.exists()


def drop_a_paper(rows: list[dict]) -> None:
    at = [index for index, row in enumerate(rows) if row["arxiv_id"]][1]
    del rows[at]


def swap_two_papers(rows: list[dict]) -> None:
    first, second = [index for index, row in enumerate(rows) if row["arxiv_id"]][:2]
    rows[first]["arxiv_id"], rows[second]["arxiv_id"] = (
        rows[second]["arxiv_id"],
        rows[first]["arxiv_id"],
    )


@pytest.mark.parametrize(
    ("change", "said"),
    [
        (drop_a_paper, "not the sheet of these outcomes"),
        (swap_two_papers, "not the sheet of these outcomes (line 2 has"),
        (lambda rows: rows.clear(), "0 paper(s), not 4"),
    ],
)
def test_a_sheet_of_other_papers_is_refused_as_a_whole(tmp_path, capsys, change, said):
    survey = Survey(tmp_path)
    survey.write()
    survey.fill()
    rows = survey.rows()
    change(rows)
    with survey.sheet.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, COLUMNS)
        writer.writeheader()
        writer.writerows(rows)

    assert survey.collect() == 1
    assert said in capsys.readouterr().err and not survey.checks.exists()


def test_a_sheet_as_a_spreadsheet_saves_it_is_read(tmp_path):
    survey = Survey(tmp_path)
    survey.write()
    survey.fill()
    # Empty rows at the end, and a column the spreadsheet added.
    text = survey.sheet.read_text(encoding="utf-8-sig")
    lines = [each + "," for each in text.splitlines()] + [",,,,,,,,,,", ",,,,,,,,,,"]
    survey.sheet.write_bytes(b"\xef\xbb\xbf" + "\r\n".join(lines).encode() + b"\r\n")

    chosen, _ = to_check(run.read_outcomes(survey.outcomes)[1], 2)
    checks = read_sheet(survey.sheet, chosen)
    assert [(check.sections, check.subsections) for check in checks] == [("same", "same")] * 4
    assert [check.rank for check in checks] == [1, 2, 1, 2]


def test_a_sheet_that_is_not_utf8_or_has_lost_its_columns_is_refused(tmp_path):
    survey = Survey(tmp_path)
    survey.write()
    chosen, _ = to_check(run.read_outcomes(survey.outcomes)[1], 2)
    survey.sheet.write_bytes("number,arxiv_id\n1,é\n".encode("latin-1"))
    with pytest.raises(SheetError, match='save it as "CSV UTF-8"'):
        read_sheet(survey.sheet, chosen)
    survey.sheet.write_text("number,arxiv_id\n1,x\n", encoding="utf-8")
    with pytest.raises(SheetError, match="the columns arxiv_id, sections, subsections, note"):
        read_sheet(survey.sheet, chosen)


def test_the_verdicts_are_not_written_over_a_file_or_by_code_no_commit_names(tmp_path, capsys):
    survey = Survey(tmp_path)
    survey.write()
    survey.fill()
    assert survey.collect(origin=lambda file=None: {"commit": COMMIT, "modified": True}) == 2
    assert "files the repository keeps have been changed" in capsys.readouterr().err
    assert not survey.checks.exists()

    survey.checks.write_text("kept\n", encoding="utf-8")
    assert survey.collect() == 2
    assert "is there already; move it away first" in capsys.readouterr().err
    assert survey.checks.read_text(encoding="utf-8") == "kept\n"


def test_left_to_itself_the_sheet_is_made_from_the_folder_of_downloads(tmp_path, monkeypatch):
    survey = Survey(tmp_path)
    good = (200, tar_gz({"paper.tex": SAMPLE_LATEX.encode()}))
    arxiv = SurveyArxiv({each.arxiv_id: [good] for each in survey.drawn})
    built = under_its_own_name(monkeypatch, sheet, arxiv, tmp_path / "downloads")

    assert sheet.main(survey.argv(), origin=committed) == 0

    assert built == [(tmp_path / "downloads", "hepph-paper-miner/survey")]
    papers = [row for row in survey.rows() if row["arxiv_id"]]
    assert len(papers) == 4
    # Only the papers on the sheet are fetched: a lookup and a download for each.
    assert sorted(arxiv.requests) == sorted(
        f"{what} {row['arxiv_id']}" for row in papers for what in ("lookup", "download")
    )


def test_a_sheet_that_is_not_there_cannot_be_read_back(tmp_path, capsys):
    survey = Survey(tmp_path)
    assert survey.collect() == 2
    assert "cannot read or write the sheet" in capsys.readouterr().err
    assert not survey.checks.exists()
