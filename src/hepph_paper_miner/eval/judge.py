"""A model as a second grader of the answers, to be held against the grades a person gave.

    uv run python -m hepph_paper_miner.eval.judge --questions eval_data/questions_dev.jsonl \
        --sheet results/judge/dev-sheet.csv --controls eval_data/judge_controls_dev.csv \
        --out results/judge/dev-j1.jsonl

The verdict on an answer is the grade a person gave it (sheet.py), and nothing here
changes that. This module asks a model for a grade of the same answers, so that the two
can be laid side by side: how often a judge of this kind says what the person said, and
where it does not.

The judge is given what the sheet shows the grader and nothing else: the question, its
reference answer, the note on what is accepted, the answer and its "found". It is not
given the layout, the repetition, the run, the sections an answer cites, what the rule
of grade.py said, or a grade. The answers are read from the sheet, from the columns
`number`, `question_id`, `found` and `answer` alone. So this module never opens the key
of a sheet, and never reads a grade off one.

Nearly every answer of the evaluation was graded right, so a judge that calls every
answer right would agree with the person nearly everywhere. The sheet alone cannot show
whether a judge can tell a wrong answer. Controls can: answers made to be wrong
(`--controls`, a CSV with the columns `id`, `question_id`, `found` and `answer`; its
other columns say how each was made and what is wrong with it, and are not read here).
They are asked like the answers of the sheet.

Each answer is one request without tools, and the API holds the reply to a form: a
verdict, right or wrong, and one sentence on why. In the runs of the questions that way
of handing in an answer kept a model asking for tools (agent/prompt.py). A request
without tools has nothing to go on asking for, and this model cannot be made to call a
tool. Every answer is asked `REPEATS` times, in passes over all of them: this model
takes no sampling settings, so the same request can come back with another verdict, and
the record shows how often it does. What a request is made with is in `JUDGE`. The texts
the judge reads have a name, `JUDGE_VERSION`, and tests/test_judge.py holds them to it,
as with the texts of a run: a change to them is another judge.

The record is one file of JSON lines: a first line that says what the judge was and what
it was given, a line for every request, and a last line with the totals once every
request has its verdict line. It holds no paper text, because the judge is given none.
A request that the API failed is written down and asked again when the command is
started again with the same arguments, which skips what is done. A reply that is no
verdict (a refusal, a text cut short) is the judge's own doing: it is kept, and not
asked again.
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import datetime
import hashlib
import json
import os
import sys
import time
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

import anthropic

from hepph_paper_miner.agent.model import ModelError, Reply, reply_from
from hepph_paper_miner.agent.origin import code_version, file_digest
from hepph_paper_miner.eval.questions import Question, QuestionFileError, load_questions
from hepph_paper_miner.eval.report import cost_of
from hepph_paper_miner.eval.run import _REFUSALS, _REFUSING_STATUS, API_FAILURES_IN_A_ROW

# The name of everything the judge reads beside the question and the answer: the system
# prompt, the layout of a request and the form of a verdict. Raise it with any of them.
JUDGE_VERSION = "j1"

# The same text for every question, so it names no paper and no fact of one. It holds
# none of the criteria that were settled while the sheet was graded: the judge starts
# from what the grader started from.
SYSTEM_PROMPT = """\
You grade one answer to a question about physics papers. You are given the question, a reference answer, a note on what is accepted, and the answer with its "found" flag. You do not have the papers: grade against what is given here, not against what you remember of a paper.

- The note decides. It says what an answer has to contain, what it may leave out, and which answers are wrong. It may be written in another language than the answer.
- The reference answer is one complete right answer. Use it to understand the note and to check what the answer states. An answer need not contain everything that is in it.
- The answer is right only if every point that the note requires is there and is stated correctly. A required point that is missing or wrong makes the answer wrong. There is no partial credit.
- What the note says may be left out is never required.
- An answer of a kind that the note calls wrong is wrong.
- "found" is the answer's own statement about the papers: false says that they do not state what the question asks for. It has to fit the note and the reference answer: false where they say that the papers do not state it, true where they give what the papers state.
- What the answer says beyond the note and the reference answer cannot be checked here. It counts neither for the answer nor against it.
- Grade what the answer states. Its length and its wording do not count.
"""

# One request. The four parts are the columns of the sheet a grader reads, in its order.
MESSAGE = """\
<question>
{question}
</question>

<reference_answer>
{reference_answer}
</reference_answer>

<note>
{accept_note}
</note>

<answer found="{found}">
{answer}
</answer>
"""

RIGHT, WRONG = "right", "wrong"

# The form of a verdict: the two things a grader writes on the sheet. "why" asks for a
# short explanation and not for the reasoning: the API may refuse a form that asks for
# the model's reasoning, and the reasoning has its own place before the reply.
VERDICT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "verdict": {
            "type": "string",
            "enum": [RIGHT, WRONG],
            "description": "right or wrong. There is no partial credit.",
        },
        "why": {
            "type": "string",
            "description": (
                "One short sentence on what decided the verdict: the required point that "
                "is missing or wrong, the kind of answer that the note calls wrong, or "
                "that every required point is there."
            ),
        },
    },
    "required": ["verdict", "why"],
    "additionalProperties": False,
}

# What a request is made with. The model, its thinking and its effort are those of the
# runs it grades (eval/conditions.py), written out for the same reason: a record says
# what was used, and a changed default cannot change the judge unnoticed. There is no
# cache: a request is short and is not continued.
JUDGE: dict[str, Any] = {
    "model": "claude-sonnet-5-5",
    "max_tokens": 16000,
    "thinking": {"type": "adaptive"},
    "effort": "high",
    "max_retries": 2,
    "request_seconds": 600.0,
}

# How often each answer is asked. The verdict on an answer is the one that more than half
# of the requests gave, as a layout has a question right in more than half of its runs.
REPEATS = 3


class JudgeError(ValueError):
    """Something the judge cannot be started with. The message says what."""


@dataclass(frozen=True)
class Item:
    """One answer to grade."""

    id: str  # "sheet-<number>" for a row of the sheet, the id of a control otherwise
    question_id: str
    found: bool
    answer: str


@dataclass(frozen=True)
class Verdict:
    verdict: str | None  # RIGHT or WRONG; None when the reply is no verdict
    why: str
    problem: str | None  # what is wrong with a reply that is no verdict


def texts_digest() -> str:
    """The digest of everything the judge reads beside a question and an answer."""
    texts = [SYSTEM_PROMPT, MESSAGE, VERDICT_SCHEMA]
    return hashlib.sha256(json.dumps(texts).encode("utf-8")).hexdigest()


def message_for(question: Question, item: Item) -> str:
    """The request for one answer: what the sheet shows of its question, and the answer."""
    return MESSAGE.format(
        question=question.question,
        reference_answer=question.reference_answer,
        accept_note=question.accept_note,
        found="true" if item.found else "false",
        answer=item.answer,
    )


# --- the answers to grade ------------------------------------------------------------------


def _columns(path: Path, what: str, names: Sequence[str]) -> list[dict[str, str]]:
    """The named columns of a CSV file, and no other: one mapping for each line that has any."""
    try:
        with path.open(encoding="utf-8-sig", newline="") as stream:
            reader = csv.DictReader(stream)
            lines = list(reader)
            there = reader.fieldnames or []
    except UnicodeDecodeError as error:
        raise JudgeError(f"{path.name}: the {what} is not UTF-8 text ({error})") from error
    missing = [name for name in names if name not in there]
    if missing:
        raise JudgeError(f"{path.name}: the {what} has no column {', '.join(missing)}")
    kept = [{name: line.get(name) or "" for name in names} for line in lines]
    return [line for line in kept if any(value.strip() for value in line.values())]


def _item(name: str, line: Mapping[str, str], where: str) -> Item:
    found = line["found"].strip().casefold()
    if found not in ("true", "false"):
        raise JudgeError(f"{where}: found is {line['found']!r}, neither true nor false")
    if not line["answer"].strip():
        raise JudgeError(f"{where}: no answer")
    # The answer goes to the judge as the cell holds it, as the grader read it.
    return Item(name, line["question_id"].strip(), found == "true", line["answer"])


def sheet_items(path: Path) -> list[Item]:
    """The answers of a sheet, in its order. Its grades and its key are not read."""
    items = []
    for line in _columns(path, "sheet", ("number", "question_id", "found", "answer")):
        try:
            number = int(line["number"])
        except ValueError:
            raise JudgeError(f"{path.name}: number {line['number']!r} is not a number") from None
        items.append(_item(f"sheet-{number}", line, f"{path.name} number {number}"))
    return items


def control_items(path: Path) -> list[Item]:
    """The answers of a file of controls, in its order. What it says of them is not read."""
    items = []
    for line in _columns(path, "file of controls", ("id", "question_id", "found", "answer")):
        name = line["id"].strip()
        if not name or name.startswith("sheet-"):
            raise JudgeError(f"{path.name}: {name!r} cannot be the id of a control")
        items.append(_item(name, line, f"{path.name} {name}"))
    return items


def chosen(
    items: Sequence[Item], questions: Mapping[str, Question], only: Sequence[str] | None
) -> list[Item]:
    """The answers to ask, checked: every id once, every question known."""
    seen: set[str] = set()
    for item in items:
        if item.id in seen:
            raise JudgeError(f"{item.id} is there twice")
        seen.add(item.id)
        if item.question_id not in questions:
            raise JudgeError(f"{item.id}: its question {item.question_id!r} is not in the file")
    if only is None:
        return list(items)
    unknown = [name for name in only if name not in seen]
    if unknown:
        raise JudgeError(f"--only names {', '.join(unknown)}, which is not among the answers")
    return [item for item in items if item.id in set(only)]


# --- one request ---------------------------------------------------------------------------


class Judge(Protocol):
    """What the runner needs of a judge."""

    @property
    def settings(self) -> dict[str, Any]:
        """Everything about this judge that belongs in the record."""
        ...

    async def ask(self, system: str, message: str, schema: dict[str, Any]) -> Reply:
        """Ask once. Raises ModelError when there is no reply."""
        ...


class ClaudeJudge:
    """The judge through the Messages API, made with `JUDGE`.

    A request holds no tools, no cache mark and no sampling settings. The key is read
    from ANTHROPIC_API_KEY by the SDK, and is never passed around, printed or recorded.
    """

    def __init__(self, client: anthropic.AsyncAnthropic | None = None) -> None:
        self._client = client or anthropic.AsyncAnthropic(
            max_retries=JUDGE["max_retries"], timeout=JUDGE["request_seconds"]
        )

    @property
    def settings(self) -> dict[str, Any]:
        return {**JUDGE, "sdk": f"anthropic {anthropic.__version__}"}

    async def ask(self, system: str, message: str, schema: dict[str, Any]) -> Reply:
        try:
            response = await self._client.messages.create(
                model=JUDGE["model"],
                max_tokens=JUDGE["max_tokens"],
                system=system,
                messages=[{"role": "user", "content": message}],
                thinking=dict(JUDGE["thinking"]),
                output_config={
                    "effort": JUDGE["effort"],
                    "format": {"type": "json_schema", "schema": schema},
                },
            )
        except anthropic.APIError as error:
            status = getattr(error, "status_code", None)
            raise ModelError(type(error).__name__, str(error), status) from error
        return reply_from(response)


def read_verdict(reply: Reply) -> Verdict:
    """The verdict in a reply, or what keeps the reply from being one."""
    if reply.stop_reason != "end_turn":
        # A refusal or a text cut short need not have the form, whatever it looks like.
        return Verdict(None, "", f"the reply stopped with {reply.stop_reason}")
    try:
        data = json.loads(reply.text)
    except ValueError:
        return Verdict(None, "", "the reply is not JSON")
    if not isinstance(data, dict) or set(data) != {"verdict", "why"}:
        return Verdict(None, "", "the reply does not have the two fields of a verdict")
    verdict, why = data["verdict"], data["why"]
    # The API may give back a value of the form in other capitals than the form has.
    if not isinstance(verdict, str) or verdict.casefold() not in (RIGHT, WRONG):
        return Verdict(None, "", f"the verdict is {verdict!r}")
    if not isinstance(why, str):
        return Verdict(None, "", "why is not a text")
    return Verdict(verdict.casefold(), why, None)


def verdict_of(verdicts: Sequence[str | None], repeats: int = REPEATS) -> str | None:
    """The verdict on an answer: the one that more than half of its requests gave."""
    for value in (RIGHT, WRONG):
        if sum(1 for verdict in verdicts if verdict == value) * 2 > repeats:
            return value
    return None


# --- the record ----------------------------------------------------------------------------


def _source(path: Path | None, count: int) -> dict[str, Any] | None:
    if path is None:
        return None
    return {"file": path.name, "sha256": file_digest(path), "answers": count}


def head_of(
    judge: Judge,
    code: Mapping[str, Any],
    questions: Path,
    sheet: tuple[Path, int] | None,
    controls: tuple[Path, int] | None,
    repeats: int,
    only: Sequence[str] | None,
) -> dict[str, Any]:
    """The first line of a record: what the judge was, and what it was given."""
    return {
        "record": "judge",
        "judge_version": JUDGE_VERSION,
        "texts_sha256": texts_digest(),
        "settings": judge.settings,
        "repeats": repeats,
        "code": dict(code),
        "questions": {"file": questions.name, "sha256": file_digest(questions)},
        "sheet": _source(*sheet) if sheet else None,
        "controls": _source(*controls) if controls else None,
        "only": sorted(only) if only is not None else None,
    }


def read_record(path: Path) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, Any] | None]:
    """A record as it lies: its first line, its request lines, and its last line if it has one."""
    try:
        lines = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]
    except ValueError as error:
        raise JudgeError(f"{path.name}: a line that is not JSON ({error})") from error
    if not lines or lines[0].get("record") != "judge":
        raise JudgeError(f"{path.name}: not the record of a judge")
    end = lines[-1] if lines[-1].get("record") == "end" else None
    return lines[0], [line for line in lines[1:] if line.get("record") != "end"], end


def _asked(lines: Sequence[Mapping[str, Any]]) -> set[tuple[str, int]]:
    """The requests that got a reply. One that the API failed is not among them."""
    return {(line["item"], line["repeat"]) for line in lines if line.get("record") == "verdict"}


def totals(lines: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """The last line of a record, from its request lines."""
    replies = [line for line in lines if line.get("record") == "verdict"]
    usage: Counter[str] = Counter()
    cost: float | None = 0.0
    for line in replies:
        for name, value in (line.get("usage") or {}).items():
            if isinstance(value, int):
                usage[name] += value
        one = cost_of([line], line.get("model"))
        cost = None if cost is None or one is None else cost + one
    return {
        "record": "end",
        "requests": len(replies),
        "verdicts": {
            RIGHT: sum(1 for line in replies if line["verdict"] == RIGHT),
            WRONG: sum(1 for line in replies if line["verdict"] == WRONG),
            "none": sum(1 for line in replies if line["verdict"] is None),
        },
        "failed": sum(1 for line in lines if line.get("record") == "failed"),
        "usage": dict(sorted(usage.items())),
        # Worked out from the usage at the list prices of report.py; not read from the Console.
        "cost": cost,
    }


def append(path: Path, line: Mapping[str, Any]) -> None:
    """Add one line to a record."""
    # Opened for each line and never kept: a line is on the disk when this returns, and
    # a record that the command is stopped over ends with a whole line.
    with path.open("a", encoding="utf-8", newline="\n") as stream:
        stream.write(json.dumps(line, ensure_ascii=False) + "\n")


class Stop(Exception):
    """Why the runner gives up: more requests would end the same way."""


class Runner:
    """Asks every answer `repeats` times and writes each reply down as it comes."""

    def __init__(
        self,
        judge: Judge,
        questions: Mapping[str, Question],
        items: Sequence[Item],
        out: Path,
        repeats: int = REPEATS,
        parallel: int = 1,
        echo: Callable[[str], None] = print,
    ) -> None:
        self._judge = judge
        self._questions = questions
        self._items = list(items)
        self._out = out
        self._repeats = repeats
        self._parallel = max(1, parallel)
        self._echo = echo
        self._failures = 0
        self._stop: str | None = None

    def to_ask(self, lines: Sequence[Mapping[str, Any]]) -> list[tuple[int, Item]]:
        """What is still to ask, in order: the repetition is the outer loop."""
        asked = _asked(lines)
        return [
            (repeat, item)
            for repeat in range(1, self._repeats + 1)
            for item in self._items
            if (item.id, repeat) not in asked
        ]

    async def _one(self, repeat: int, item: Item) -> None:
        message = message_for(self._questions[item.question_id], item)
        begun = time.monotonic()
        try:
            reply = await self._judge.ask(SYSTEM_PROMPT, message, VERDICT_SCHEMA)
        except ModelError as error:
            append(
                self._out,
                {
                    "record": "failed",
                    "item": item.id,
                    "repeat": repeat,
                    "error": {"kind": error.kind, "detail": error.detail, "status": error.status},
                },
            )
            self._echo(f"  {item.id} [{repeat}] failed: {error.kind}")
            self._failures += 1
            detail = error.detail.lower()
            if (
                error.kind in _REFUSALS
                or error.status in _REFUSING_STATUS
                or "credit balance" in detail
            ):
                self._stop = f"the API refuses: {str(error)[:300]}"
            elif self._failures >= API_FAILURES_IN_A_ROW:
                self._stop = f"the API failed {self._failures} requests in a row"
            return
        self._failures = 0
        verdict = read_verdict(reply)
        line = {
            "record": "verdict",
            "item": item.id,
            "question_id": item.question_id,
            "repeat": repeat,
            "verdict": verdict.verdict,
            "why": verdict.why,
            "stop_reason": reply.stop_reason,
            "blocks": list(reply.blocks),
            "usage": reply.usage,
            "model": reply.model,
            "seconds": round(time.monotonic() - begun, 1),
        }
        if verdict.problem is not None:
            # What the judge wrote in place of a verdict. It was given no paper text.
            line |= {"problem": verdict.problem, "text": reply.text[:2000]}
        append(self._out, line)
        self._echo(f"  {item.id} [{repeat}] {verdict.verdict or verdict.problem}")

    async def run(self, lines: Sequence[Mapping[str, Any]]) -> None:
        """Ask what `lines`, the request lines of the record so far, leave to ask."""
        waiting = iter(self.to_ask(lines))

        async def worker() -> None:
            # The workers share one row of requests. Nothing here is awaited between
            # taking a request and starting it, so each is taken once.
            for repeat, item in waiting:
                if self._stop is not None:
                    return
                await self._one(repeat, item)

        await asyncio.gather(*(worker() for _ in range(self._parallel)))
        if self._stop is not None:
            raise Stop(self._stop)


def summary(lines: Sequence[Mapping[str, Any]], items: Sequence[Item], repeats: int) -> list[str]:
    """What the record says, answer by answer. It knows no grade: it lists, and does not compare."""
    given: dict[str, list[str | None]] = {item.id: [] for item in items}
    for line in lines:
        if line.get("record") == "verdict" and line["item"] in given:
            given[line["item"]].append(line["verdict"])
    said = [verdict for verdicts in given.values() for verdict in verdicts]
    counts = f"{said.count(RIGHT)} right, {said.count(WRONG)} wrong, {said.count(None)} without"
    text = [f"{len(said)} request(s) with a reply: {counts} a verdict"]
    kinds = (
        ("sheet", [item for item in items if item.id.startswith("sheet-")]),
        ("controls", [item for item in items if not item.id.startswith("sheet-")]),
    )
    for name, group in kinds:
        if not group:
            continue
        final = {item.id: verdict_of(given[item.id], repeats) for item in group}
        text.append(
            f"{name}: {len(group)} answer(s); by more than half of {repeats} request(s): "
            f"{sum(1 for v in final.values() if v == RIGHT)} right, "
            f"{sum(1 for v in final.values() if v == WRONG)} wrong, "
            f"{sum(1 for v in final.values() if v is None)} without a verdict"
        )
        # For the answers of a sheet the rare verdict is "wrong", for controls it is "right".
        rare = WRONG if name == "sheet" else RIGHT
        listed = [item.id for item in group if final[item.id] == rare]
        if listed:
            text.append(f"  {rare}: {' '.join(listed)}")
        open_ = [item.id for item in group if final[item.id] is None]
        if open_:
            text.append(f"  without a verdict: {' '.join(open_)}")
        mixed = [item.id for item in group if len(set(given[item.id])) > 1]
        if mixed:
            text.append(f"  not the same in every request: {' '.join(mixed)}")
    return text


# --- the command ---------------------------------------------------------------------------


def main(argv: Sequence[str] | None = None, judge: Judge | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m hepph_paper_miner.eval.judge",
        description="Ask a model to grade the answers of a sheet, and controls made to be wrong.",
    )
    parser.add_argument("--questions", type=Path, required=True, help="the question file")
    parser.add_argument("--sheet", type=Path, help="a sheet of answers (eval.sheet)")
    parser.add_argument("--controls", type=Path, help="a CSV of answers made to be wrong")
    parser.add_argument("--out", type=Path, required=True, help="the record to write (JSON lines)")
    parser.add_argument(
        "--repeats", type=int, default=REPEATS, help="requests per answer (default: %(default)s)"
    )
    parser.add_argument(
        "--parallel", type=int, default=1, help="requests at a time (default: %(default)s)"
    )
    parser.add_argument("--only", nargs="+", metavar="ID", help="ask these answers only")
    parser.add_argument("--plan", action="store_true", help="say what would be asked, and stop")
    arguments = parser.parse_args(argv)

    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="backslashreplace")
    if arguments.sheet is None and arguments.controls is None:
        print("nothing to grade: give --sheet, --controls or both", file=sys.stderr)
        return 2
    try:
        questions = {question.id: question for question in load_questions(arguments.questions)}
        from_sheet = sheet_items(arguments.sheet) if arguments.sheet else []
        from_controls = control_items(arguments.controls) if arguments.controls else []
        items = chosen(from_sheet + from_controls, questions, arguments.only)
    except (OSError, QuestionFileError, JudgeError) as error:
        print(f"refused: {error}", file=sys.stderr)
        return 2

    code = code_version()
    if code["modified"]:
        # A record names the commit that made it. Changed code has no commit to name.
        print("refused: the code has changes that are not committed", file=sys.stderr)
        return 1
    given = judge is not None
    judge = judge or ClaudeJudge()
    head = head_of(
        judge,
        code,
        arguments.questions,
        (arguments.sheet, len(from_sheet)) if arguments.sheet else None,
        (arguments.controls, len(from_controls)) if arguments.controls else None,
        arguments.repeats,
        arguments.only,
    )
    out: Path = arguments.out
    lines: list[dict[str, Any]] = []
    end = None
    if out.exists():
        try:
            begun, lines, end = read_record(out)
        except JudgeError as error:
            print(f"refused: {error}", file=sys.stderr)
            return 1
        begun = {name: value for name, value in begun.items() if name != "started_at"}
        if begun != head:
            differing = sorted(
                name for name in set(begun) | set(head) if begun.get(name) != head.get(name)
            )
            print(
                f"refused: {out} was begun with something else ({', '.join(differing)}); "
                "move it away first",
                file=sys.stderr,
            )
            return 1

    runner = Runner(judge, questions, items, out, arguments.repeats, arguments.parallel)
    waiting = runner.to_ask(lines)
    total = len(items) * arguments.repeats
    print(
        f"{len(items)} answer(s), {total} request(s): {total - len(waiting)} done, "
        f"{len(waiting)} to ask"
    )
    if arguments.plan:
        return 0
    if end is None:
        if waiting and not given and not os.environ.get("ANTHROPIC_API_KEY"):
            print(
                "ANTHROPIC_API_KEY is not set in this shell, so the judge cannot be asked.",
                file=sys.stderr,
            )
            return 2
        if not out.exists():
            out.parent.mkdir(parents=True, exist_ok=True)
            stamp = datetime.datetime.now(datetime.UTC).isoformat(timespec="seconds")
            append(out, {**head, "started_at": stamp})
        try:
            asyncio.run(runner.run(lines))
        except Stop as stop:
            print(f"stopped: {stop}", file=sys.stderr)
            return 1
        _, lines, _ = read_record(out)
        left = len(runner.to_ask(lines))
        if left:
            # The last line stands for a record in which every request has its reply.
            print(
                f"{left} request(s) got no reply from the API: start the command again",
                file=sys.stderr,
            )
            return 1
        append(out, totals(lines))
    for line in summary(lines, items, arguments.repeats):
        print(line)
    cost = totals(lines)["cost"]
    if cost is not None:
        print(f"cost, computed: ${cost:.2f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
