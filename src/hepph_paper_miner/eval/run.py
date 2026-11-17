"""Run the evaluation: every question with both tool layouts, a set number of times, in order.

    uv run python -m hepph_paper_miner.eval.run \
        --questions eval_data/questions_eval.jsonl --out results/runs/eval

Each run is the command `python -m hepph_paper_miner.agent`, started in a process of its
own as a run of the evaluation is started: a layout, the question, `--cache`,
`--show-thinking` and the repetition (eval/conditions.py names what the rest has to be).
A process of its own, because a tool call that ran out of time leaves its thread behind
until the process ends, and that thread keeps its place in the queue for arXiv.

The order is fixed. The repetition is the outer loop, so that the three runs of a
question are minutes apart rather than seconds, and within a repetition the questions
come in the order of the file. The two layouts of a question run one after the other,
and which comes first alternates, from question to question and from repetition to
repetition: neither is always the first to meet an empty folder of downloads or a
passing failure of arXiv.

A cell (question, layout, repetition) is done when the folder holds a finished record of
it that the environment did not spoil. A run is spoilt when arXiv or the API failed
under it: a tool call that ended in `timeout` or `upstream_busy`, or a run that ended in
`api_error`, `tool_transport_error`, `tool_timeout` or `time_limit`, or one that never
wrote its last line. A spoilt run is kept, and the cell is run again with the same
repetition number, in a later pass over the plan and at most twice. Started again, the
runner skips what is done, so it can be stopped and resumed.

It stops at once when the API refuses for a reason more runs cannot change (the key, the
credit, the spending limit of the workspace), after three runs in a row that the API
failed, and when a record names anything but the conditions of the evaluation.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from hepph_paper_miner.eval.conditions import differences

LAYOUTS = ("staged", "flat")
REPEATS = 3
TRIES = 3  # the first run of a cell and at most two more (decision 10 of the plan)

# Why a run says nothing about the layouts: arXiv or the API failed under it.
SPOILING_ENDS = frozenset({"api_error", "tool_transport_error", "tool_timeout", "time_limit"})
SPOILING_TOOL_ERRORS = frozenset({"timeout", "upstream_busy"})

# Errors of the API that more runs cannot change. In anthropic 2.8.0 a 402 has no class of
# its own ("Error code: 402" in the message), and a 429 that carries the code
# enforced_spend_limit_reached is EnforcedSpendLimitReachedError, not RateLimitError.
_REFUSALS = frozenset(
    {"AuthenticationError", "PermissionDeniedError", "EnforcedSpendLimitReachedError"}
)
_REFUSING_STATUS = frozenset({401, 402, 403})
API_FAILURES_IN_A_ROW = 3

# A run has its own limits (900 s, checked between responses). This only ends a process
# that hangs; a run ended this way leaves no last line and counts as spoilt.
PROCESS_SECONDS = 3600.0


@dataclass(frozen=True, order=True)
class Cell:
    question_id: str
    toolset: str
    repeat: int

    def __str__(self) -> str:
        return f"{self.question_id} {self.toolset} {self.repeat}"


def plan(question_ids: Sequence[str], repeats: int = REPEATS) -> list[Cell]:
    """Every cell, in the order the runs are made."""
    cells = []
    for repeat in range(1, repeats + 1):
        for index, question_id in enumerate(question_ids):
            first = (index + repeat - 1) % 2
            for toolset in (LAYOUTS[first], LAYOUTS[1 - first]):
                cells.append(Cell(question_id, toolset, repeat))
    return cells


@dataclass(frozen=True)
class Attempt:
    """One record of a run in the folder, finished or not."""

    path: Path
    run: dict[str, Any]
    turns: tuple[dict[str, Any], ...]
    end: dict[str, Any] | None  # None: the run never wrote its last line

    @property
    def cell(self) -> Cell:
        return Cell(self.run.get("question_id"), self.run.get("toolset"), self.run.get("repeat"))

    @property
    def spoilt(self) -> str | None:
        """Why arXiv or the API spoilt this run, or None when they did not."""
        if self.end is None:
            return "the run did not finish"
        if self.end.get("reason") in SPOILING_ENDS:
            return self.end["reason"]
        for turn in self.turns:
            for call in turn.get("tools", ()):
                if call.get("error_kind") in SPOILING_TOOL_ERRORS:
                    return f"a tool call ended in {call['error_kind']}"
        return None


def read_attempt(path: Path) -> Attempt | None:
    """The record at `path`, or None when the file is not the record of a run."""
    lines = []
    for text in path.read_text(encoding="utf-8").splitlines():
        try:
            lines.append(json.loads(text))
        except json.JSONDecodeError:
            break  # a line cut off when the process was ended: what came before still holds
    if not lines or lines[0].get("record") != "run":
        return None
    end = lines[-1] if len(lines) > 1 and lines[-1].get("record") == "end" else None
    turns = tuple(line for line in lines[1:] if line.get("record") == "turn")
    return Attempt(path, lines[0], turns, end)


def attempts_in(folder: Path) -> dict[Cell, list[Attempt]]:
    """The records in the folder, by cell, oldest first (a run id begins with its time)."""
    found: dict[Cell, list[Attempt]] = {}
    if folder.is_dir():
        for path in sorted(folder.glob("*.jsonl")):
            attempt = read_attempt(path)
            if attempt is not None:
                found.setdefault(attempt.cell, []).append(attempt)
    return found


def counted(attempts: Mapping[Cell, list[Attempt]]) -> dict[Cell, Attempt]:
    """The run that counts for each cell: the first one that arXiv and the API did not spoil.

    The same rule makes a cell done (State.done), so the runs the runner stops at are the
    runs the sheet and the report read.
    """
    found = {}
    for cell, tried in attempts.items():
        first = next((attempt for attempt in tried if attempt.spoilt is None), None)
        if first is not None:
            found[cell] = first
    return found


def refusal(end: Mapping[str, Any] | None) -> str | None:
    """Why the API will refuse every run from now on, when the last line says so."""
    if not end or end.get("reason") != "api_error":
        return None
    detail = end.get("detail") or ""
    kind = detail.split(":", 1)[0].strip()
    code = re.search(r"Error code: (\d{3})", detail)
    status = int(code[1]) if code else None
    if kind in _REFUSALS or status in _REFUSING_STATUS or "credit balance" in detail.lower():
        return detail[:300]
    return None


@dataclass
class State:
    """What the folder says of each cell of the plan."""

    cells: list[Cell]
    attempts: dict[Cell, list[Attempt]]

    def done(self, cell: Cell) -> Attempt | None:
        return next((a for a in self.attempts.get(cell, ()) if a.spoilt is None), None)

    def spoilt(self, cell: Cell) -> list[Attempt]:
        return [a for a in self.attempts.get(cell, ()) if a.spoilt is not None]

    def to_run(self, cell: Cell) -> bool:
        return self.done(cell) is None and len(self.spoilt(cell)) < TRIES

    def counts(self) -> str:
        done = sum(1 for cell in self.cells if self.done(cell))
        given_up = sum(1 for cell in self.cells if not self.done(cell) and not self.to_run(cell))
        again = sum(1 for cell in self.cells if self.to_run(cell) and self.spoilt(cell))
        fresh = sum(1 for cell in self.cells if self.to_run(cell) and not self.spoilt(cell))
        spoilt = sum(len(self.spoilt(cell)) for cell in self.cells)
        return (
            f"{len(self.cells)} cell(s): {done} done, {fresh} to run, {again} to run again, "
            f"{given_up} given up after {TRIES} spoilt runs | {spoilt} spoilt run(s) kept"
        )

    def line(self, cell: Cell) -> str:
        done = self.done(cell)
        if done is not None:
            return f"{cell} | done ({done.end['reason']})"
        why = "; ".join(a.spoilt for a in self.spoilt(cell))
        if not why:
            return f"{cell} | to run"
        return f"{cell} | spoilt ({why}) | " + ("to run again" if self.to_run(cell) else "given up")


class Stop(Exception):
    """A reason to stop the whole evaluation, not just one run."""


def check_folder(
    attempts: Mapping[Cell, list[Attempt]],
    questions_sha256: str,
    code: Mapping[str, Any],
    allow_other_code: bool,
) -> None:
    """Refuse to add runs to a folder that holds runs of something else."""
    records = [a for found in attempts.values() for a in found]
    # A run given its question on the command line names no file (null).
    named = {(a.run.get("questions") or {}).get("sha256") for a in records}
    other_files = named - {questions_sha256}
    if other_files:
        raise Stop(
            f"the folder holds runs of another question file ({len(other_files)} other digest(s)); "
            "use another folder"
        )
    if not allow_other_code:
        other = {
            (a.run.get("code") or {}).get("commit")
            for a in records
            if a.run.get("code") != dict(code)
        }
        if other:
            raise Stop(
                "the folder holds runs made by other code ("
                + ", ".join(sorted(str(c)[:7] for c in other))
                + "); --allow-other-code adds to them anyway"
            )


Launch = Callable[[list[str]], int]


@dataclass
class Runner:
    """Makes the runs of a plan, one process each, and stops when it has to."""

    questions: Path
    out: Path
    private: Path | None
    launch: Launch
    say: Callable[[str], None] = print
    failures_in_a_row: int = field(default=0, init=False)

    def arguments(self, cell: Cell) -> list[str]:
        """The command line of one run, as the README says a run of the evaluation starts."""
        argv = [
            "--questions",
            str(self.questions),
            "--question-id",
            cell.question_id,
            "--toolset",
            cell.toolset,
            "--cache",
            # The model reads the same with it (conditions.py leaves it open), and the
            # summaries of its thinking are what a failure is analysed with.
            "--show-thinking",
            "--repeat",
            str(cell.repeat),
            "--out",
            str(self.out),
        ]
        if self.private is not None:
            argv += ["--private", str(self.private)]
        return argv

    def run_one(self, cell: Cell, number: str) -> Attempt:
        before = set(self.out.glob("*.jsonl")) if self.out.is_dir() else set()
        self.say(f"{number} {cell} | running")
        code = self.launch(self.arguments(cell))
        new = sorted(set(self.out.glob("*.jsonl")) - before) if self.out.is_dir() else []
        made = [a for a in map(read_attempt, new) if a is not None and a.cell == cell]
        if not made:
            raise Stop(f"{cell}: the command wrote no record (exit code {code})")
        attempt = made[-1]

        found = differences(attempt.run, attempt.end)
        if found:
            raise Stop(f"{cell}: the run was not made under the conditions: " + "; ".join(found))
        end = attempt.end or {}
        why = refusal(attempt.end)
        if why:
            raise Stop(f"{cell}: the API refuses: {why}")
        self.failures_in_a_row = (
            self.failures_in_a_row + 1 if end.get("reason") == "api_error" else 0
        )
        spoilt = f" | spoilt: {attempt.spoilt}" if attempt.spoilt else ""
        reason, turns = end.get("reason", "no last line"), end.get("turns", "?")
        chars = end.get("tool_result_chars", "?")
        self.say(f"{number} {cell} | {reason} | {turns} turn(s) | {chars} chars{spoilt}")
        if self.failures_in_a_row >= API_FAILURES_IN_A_ROW:
            detail = end.get("detail", "")[:300]
            raise Stop(f"the API failed {self.failures_in_a_row} runs in a row: {detail}")
        return attempt

    def run(self, cells: list[Cell]) -> State:
        """Run every cell that is not done, then pass again over the spoilt ones."""
        while True:
            state = State(cells, attempts_in(self.out))
            todo = [cell for cell in cells if state.to_run(cell)]
            if not todo:
                return state
            for index, cell in enumerate(todo, start=1):
                self.run_one(cell, f"[{index}/{len(todo)}]")


def _in_a_process(argv: list[str]) -> int:
    """Run the command of one question in a process of its own.

    What it printed is passed on only when it refused to start: the runner says how each
    run ended, and the record holds the rest.
    """
    try:
        done = subprocess.run(
            [sys.executable, "-m", "hepph_paper_miner.agent", *argv],
            capture_output=True,
            timeout=PROCESS_SECONDS,
            # The output holds the answer, in any script; read it as UTF-8 on every system.
            env={**os.environ, "PYTHONIOENCODING": "utf-8"},
            check=False,
        )
    except subprocess.TimeoutExpired:
        return -1  # the record has no last line, so the run counts as spoilt
    if done.returncode not in (0, 1):  # 2: the command refused to start
        sys.stderr.write(
            done.stdout.decode("utf-8", "replace") + done.stderr.decode("utf-8", "replace")
        )
    return done.returncode


def main(argv: Sequence[str] | None = None, launch: Launch | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m hepph_paper_miner.eval.run",
        description="Run every question of a file with both tool layouts, in a fixed order.",
    )
    parser.add_argument("--questions", type=Path, required=True, help="the question file")
    parser.add_argument("--out", type=Path, required=True, help="folder of the public records")
    parser.add_argument(
        "--private", type=Path, help="folder of the private records (default: the command's)"
    )
    parser.add_argument(
        "--repeats", type=int, default=REPEATS, help="repetitions (default: %(default)s)"
    )
    parser.add_argument("--only", help="question ids to run, separated by commas (default: all)")
    parser.add_argument(
        "--questions-sha256", help="refuse to start unless the file has this SHA-256"
    )
    parser.add_argument(
        "--allow-other-code", action="store_true", help="add to runs made by another commit"
    )
    parser.add_argument(
        "--plan", action="store_true", help="say what is done and what would run, and stop"
    )
    arguments = parser.parse_args(argv)

    from hepph_paper_miner.agent.origin import code_version, file_digest
    from hepph_paper_miner.eval.questions import QuestionFileError, load_questions

    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="backslashreplace")
    try:
        questions = load_questions(arguments.questions)
    except (OSError, QuestionFileError) as error:
        print(f"cannot read the questions: {error}", file=sys.stderr)
        return 2
    ids = [question.id for question in questions]
    wanted = None
    if arguments.only:
        wanted = [name.strip() for name in arguments.only.split(",") if name.strip()]
        unknown = [name for name in wanted if name not in ids]
        if unknown:
            print(
                f"no question {', '.join(unknown)} in {arguments.questions.name}", file=sys.stderr
            )
            return 2
    if arguments.repeats < 1:
        print("--repeats: at least 1", file=sys.stderr)
        return 2
    digest = file_digest(arguments.questions)
    if arguments.questions_sha256 and arguments.questions_sha256.lower() != digest:
        print(
            f"{arguments.questions.name} has SHA-256 {digest}, not the one given", file=sys.stderr
        )
        return 2

    # A part is taken from the plan of the whole file: its cells keep the order, and the
    # layout that comes first, that the whole evaluation gives them.
    cells = plan(ids, arguments.repeats)
    if wanted is not None:
        cells = [cell for cell in cells if cell.question_id in wanted]
    print(f"questions {arguments.questions} | sha256 {digest}")
    try:
        attempts = attempts_in(arguments.out)
        if arguments.plan:
            state = State(cells, attempts)
            for cell in cells:
                print(state.line(cell))
            print(state.counts())
            return 0
        code = code_version()
        print(f"code      {code.get('commit')} | modified {code.get('modified')}")
        if code.get("modified") is not False:
            raise Stop("files the repository keeps have been changed, so no commit names this code")
        if not os.environ.get("ANTHROPIC_API_KEY"):
            raise Stop("ANTHROPIC_API_KEY is not set in this shell")
        check_folder(attempts, digest, code, arguments.allow_other_code)
        runner = Runner(
            arguments.questions, arguments.out, arguments.private, launch or _in_a_process
        )
        state = runner.run(cells)
    except Stop as stop:
        print(f"stopped: {stop}", file=sys.stderr)
        print(State(cells, attempts_in(arguments.out)).counts())
        return 1
    except KeyboardInterrupt:
        print("stopped by hand", file=sys.stderr)
        print(State(cells, attempts_in(arguments.out)).counts())
        return 130
    print(state.counts())
    return 0 if all(state.done(cell) for cell in cells) else 1


if __name__ == "__main__":
    sys.exit(main())
