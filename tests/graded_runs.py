"""Shared by the tests of eval/hand.py and eval/second.py: a judge that answers from a
script, and sheets read and graded as a person leaves them. No network, no LLM."""

import csv
import json
from pathlib import Path

from hepph_paper_miner.agent.model import Reply
from hepph_paper_miner.eval import judge
from hepph_paper_miner.eval.grade import RIGHT


def reply(verdict, **more) -> Reply:
    """A reply of the judge with a verdict; `more` makes it one that is none."""
    values = {
        "stop_reason": "end_turn",
        "text": json.dumps({"verdict": verdict, "why": f"{verdict}, it says."}),
        "tool_calls": (),
        "blocks": ("text",),
        "usage": {"input_tokens": 1000, "output_tokens": 100},
        "content": None,
        "model": "claude-sonnet-5-5",
    }
    return Reply(**{**values, **more})


class Scripted:
    """A judge that answers from a table by the text of the answer: what it says in each
    of its requests on that answer. What the table does not name is right every time."""

    def __init__(self, table) -> None:
        self._table = table
        self._asked: dict[str, int] = {}

    @property
    def settings(self) -> dict:
        return {"model": "claude-sonnet-5-5", "thinking": {"type": "adaptive"}, "effort": "high"}

    async def ask(self, system: str, message: str, schema: dict) -> Reply:
        text = message.split('">\n', 1)[1].rsplit("\n</answer>", 1)[0]
        self._asked[text] = self._asked.get(text, 0) + 1
        script, asked = self._table.get(text, ()), self._asked[text] - 1
        word = script[asked] if asked < len(script) else RIGHT
        return word if isinstance(word, Reply) else reply(word)


def judged_by(questions: Path, sheet: Path, out: Path, table: dict) -> Path:
    """The record that eval.judge writes of a sheet, with the scripted judge."""
    argv = ["--questions", str(questions), "--sheet", str(sheet), "--out", str(out)]
    assert judge.main(argv, Scripted(table)) == 0
    return out


def read_csv(path: Path) -> list[dict]:
    with path.open(encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def write_csv(path: Path, rows: list[dict]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def grade_sheet(path: Path, grade_of=lambda row: RIGHT) -> None:
    """Write a grade into every row of a sheet, and save it as a spreadsheet would."""
    rows = read_csv(path)
    for row in rows:
        row["grade"] = grade_of(row)
    write_csv(path, rows)
