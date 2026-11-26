"""An invented paper for the tests of the drafting commands, and what they are given.

Its sections are written out as the parser leaves them (TeX, a subsection's text inside
its section's text), so that every place the checks look at is known: which values
stand where, a table, a caption and a footnote, a name in TeX formatting, a sentence
that runs over a line break, and a subsection longer than one call of read_section.
The filler is lines of 70 characters without a digit or a name in them.
"""

import json
from dataclasses import replace
from pathlib import Path

from hepph_paper_miner.agent.model import Reply
from hepph_paper_miner.drafting.assign import Placed
from hepph_paper_miner.drafting.places import NAMED_FIRST, SEARCH_FIRST, places_of
from hepph_paper_miner.sources.arxiv_latex import PARSER_VERSION
from hepph_paper_miner.sources.base import Paper, PaperMeta, Section
from hepph_paper_miner.sources.fixture import FixtureSource
from hepph_paper_miner.survey.records import write_lines

ID = "2609.01234v1"
TITLE = "Widgets at low energy"
META = PaperMeta(
    ID,
    TITLE,
    ("Ada Alpha", "Ben Beta"),
    2026,
    "hep-ph",
    "We study widgets. Their mass is 12.5 GeV.",
)


def filler(count: int) -> str:
    """`count` characters in lines of 70, the last one with its line break."""
    line = " ".join(["a" * 9] * 7) + "\n"
    return (line * (count // len(line) + 1))[:count]


INTRO = "We study a model of widgets\nand their decays in this work.\n\n" + filler(1_500)
OWN = "The scan of the model uses 4096 points on a regular grid.\n\n" + filler(1_200)
SETUP = (
    "\\subsection{Detector setup}\n"
    "The detector has an area of 37.2 square metres in total.\n\n" + filler(1_500)
)
LONG_FIRST = "\\subsection{Long run}\n" + filler(20_500)
LONG = (
    LONG_FIRST
    + "\n\nIn the long run the coupling is fixed to 0.0318 at the reference scale.\n\n"
    + filler(3_000)
)
RESULTS = (
    "The fitted slope is 2.37 for the main sample of events.\n\n"
    "The data of \\textit{Fermi}-LAT were used for the slope fit.\n\n"
    "\\begin{table}\n\\caption{The yields of the 815 runs.}\n"
    "\\begin{tabular}{cc} 77.7 & 88.8 \\\\ \\end{tabular}\n\\end{table}\n\n"
    "A remark here\\footnote{The run lasted 51 days.} closes the part.\n\n" + filler(1_500)
)
APPENDIX_TEXT = "The cutoff of the final fit is set to 6.6 TeV for every sample.\n\n" + filler(
    1_500
)
THANKS = "We thank the referees for their help.\n\n" + filler(500)


def paper(meta: PaperMeta = META) -> Paper:
    method = OWN + SETUP + LONG
    sections = (
        Section("1", "Introduction", 1, INTRO),
        Section("2", "Method of the scan", 1, method),
        Section("2.1", "Detector setup", 2, SETUP, heading_at=len(OWN)),
        Section("2.2", "Long run", 2, LONG, heading_at=len(OWN) + len(SETUP)),
        Section("3", "Results", 1, RESULTS),
        Section("A", "Details of the fit", 1, APPENDIX_TEXT),
        Section("u1", "Acknowledgments", 1, THANKS),
    )
    return Paper(meta, sections, PARSER_VERSION)


def source(*papers: Paper) -> FixtureSource:
    return FixtureSource(papers or (paper(),))


def placed(
    section: str, kind: str | None = None, number: int = 1, of: Paper | None = None
) -> Placed:
    """The place of a kind in a section of the paper, as a file of places names it."""
    found = [each for each in places_of(of or paper()) if each.section == section]
    if kind is not None:
        # search_first is a named_first place asked about by its title (places.py).
        wanted = NAMED_FIRST if kind == SEARCH_FIRST else kind
        found = [each for each in found if each.kind == wanted]
    (one,) = found[:1]
    pid = (of or paper()).meta.arxiv_id
    return Placed(number, "", 1, pid, kind or one.kind, one.section, one.start, one.end)


def draft(**changed) -> dict:
    """A draft about section 2.1 that passes every check, with changes."""
    values = {
        "anchor": "The detector has an area of 37.2 square metres",
        "question": "In {paper}, what is the total area of the detector?",
        "reference_answer": "37.2 square metres.",
        "numbers": [{"label": "area", "value": 37.2, "unit": "square metres", "min_sig_figs": 3}],
        "phrases": [],
        "accept_note": "The value 37.2 has to be there; the unit may be written another way.",
    }
    return {**values, **changed}


def later_draft(**changed) -> dict:
    """A draft about the later piece of section 2.2 that passes every check."""
    values = {
        "anchor": "the coupling is fixed to 0.0318 at the reference scale",
        "question": "To what value is the coupling fixed at the reference scale in {paper}?",
        "reference_answer": "0.0318.",
        "numbers": [{"label": "coupling", "value": 0.0318, "unit": "", "min_sig_figs": 3}],
        "phrases": [],
        "accept_note": "The value 0.0318 has to be there.",
    }
    return {**values, **changed}


def reply_of(data: dict, stop: str = "end_turn", thinking: str = "") -> Reply:
    """A reply of the model that writes `data` as its text."""
    blocks = [{"type": "thinking", "thinking": thinking, "signature": "c2ln"}]
    blocks.append({"type": "text", "text": json.dumps(data)})
    return Reply(
        stop,
        json.dumps(data),
        (),
        ("thinking", "text"),
        {"input_tokens": 1000, "output_tokens": 200},
        None,
        raw={"content": blocks},
        model="claude-sonnet-5-5",
    )


def as_reply(found: dict) -> dict:
    """What the generator writes for a draft."""
    return {"nothing_to_ask": False, "why_nothing": "", **found}


def nothing(why: str = "The part holds only a list.") -> dict:
    return {
        "nothing_to_ask": True,
        "why_nothing": why,
        "anchor": "",
        "question": "",
        "reference_answer": "",
        "numbers": [],
        "phrases": [],
        "accept_note": "",
    }


class Scripted:
    """A model that answers from a function of the request, and keeps the requests."""

    def __init__(self, answer) -> None:
        self._answer = answer
        self.asked: list[tuple[str, str, dict]] = []

    @property
    def settings(self) -> dict:
        return {"model": "scripted"}

    async def ask(self, system: str, message: str, schema: dict) -> Reply:
        self.asked.append((system, message, schema))
        said = self._answer(system, message, schema)
        if isinstance(said, Exception):
            raise said
        return said


def another(arxiv_id: str, title: str = TITLE) -> Paper:
    """The same paper under another identifier and title."""
    return paper(replace(META, arxiv_id=arxiv_id, title=title))


SEED = 20261124


def places_file(folder: Path, *wanted: tuple[str, str]) -> Path:
    """A file of places of the invented paper: (section, kind) for each, numbered in order."""
    head = {"record": "places", "input": "tuning", "seed": SEED, "parser_version": PARSER_VERSION}
    found = [placed(section, kind, number) for number, (section, kind) in enumerate(wanted, 1)]
    path = folder / "places.jsonl"
    write_lines(path, [head, *(place.as_line() for place in found)])
    return path
