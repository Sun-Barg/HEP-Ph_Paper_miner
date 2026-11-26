"""Ask a model request after request, and write each reply down as it comes.

The generator of drafts (draft.py) and the two filters (sift.py) ask a model the way the
judge does (eval/judge.py): one system text and one message of the user, the reply held
to a form by the API, adaptive thinking, no tools, no cache mark and no sampling
setting, and the SDK's retries. What differs is what each of them sends, and the
settings, which each names in its own module. The judge is not changed for them: its
texts and its settings have a name of their own, and the runs of the first evaluation
were graded with them.

A record is one file of JSON lines: a first line that says what was asked and with what,
a "reply" line for every request that the API answered, a "failed" line for every
request that it did not, and a last line with the totals once every request has its
reply. A reply that is of no use (a refusal, a text cut short, a text of another form)
is kept and not asked again: it is the model's own doing, and asking until something
fits would make the count of such replies mean nothing. A request that the API failed
is asked again when the command is started again with the same arguments, and nothing
else is.

The rules for stopping are those of the runs and the judge (eval/run.py): at once when
the API refuses for good (the key, the permissions, the limit of spending, no credit),
and after three requests in a row that it failed. A command does not start from code
that has changes that are not committed, or from code that git cannot name, because a
record names the commit that made it.
"""

from __future__ import annotations

import asyncio
import datetime
import json
import os
import subprocess
import sys
import time
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

import anthropic

from hepph_paper_miner.agent.model import ModelError, Reply, reply_from
from hepph_paper_miner.agent.origin import code_version
from hepph_paper_miner.eval.report import cost_of
from hepph_paper_miner.eval.run import _REFUSALS, _REFUSING_STATUS, API_FAILURES_IN_A_ROW

REPLY = "reply"
FAILED = "failed"
END = "end"


class AskError(ValueError):
    """Something a command cannot be started with. The message says what."""


class Asker(Protocol):
    """What the runner needs of a model."""

    @property
    def settings(self) -> dict[str, Any]:
        """Everything about the model and the requests that belongs in the record."""
        ...

    async def ask(self, system: str, message: str, schema: dict[str, Any]) -> Reply:
        """Ask once. Raises ModelError when there is no reply."""
        ...


class ClaudeAsker:
    """A model through the Messages API, made with the settings it is given.

    `settings` has the keys of eval/judge.py's JUDGE: model, max_tokens, thinking,
    effort, max_retries and request_seconds. A request holds no tools, no cache mark and
    no sampling setting. The key is read from ANTHROPIC_API_KEY by the SDK, and is never
    passed around, printed or recorded.
    """

    def __init__(
        self, settings: Mapping[str, Any], client: anthropic.AsyncAnthropic | None = None
    ) -> None:
        self._settings = dict(settings)
        self._client = client or anthropic.AsyncAnthropic(
            max_retries=self._settings["max_retries"], timeout=self._settings["request_seconds"]
        )

    @property
    def settings(self) -> dict[str, Any]:
        return {**self._settings, "sdk": f"anthropic {anthropic.__version__}"}

    async def ask(self, system: str, message: str, schema: dict[str, Any]) -> Reply:
        try:
            response = await self._client.messages.create(
                model=self._settings["model"],
                max_tokens=self._settings["max_tokens"],
                system=system,
                messages=[{"role": "user", "content": message}],
                thinking=dict(self._settings["thinking"]),
                output_config={
                    "effort": self._settings["effort"],
                    "format": {"type": "json_schema", "schema": schema},
                },
            )
        except anthropic.APIError as error:
            status = getattr(error, "status_code", None)
            raise ModelError(type(error).__name__, str(error), status) from error
        return reply_from(response)


def thoughts(reply: Reply) -> list[str]:
    """The text of the thinking blocks of a reply: a summary when it was asked for, else empty.

    For the private record only. A summary is written by another model than the one that
    thought (platform.claude.com/docs/build-with-claude/thinking, read 2026-11-26), so it
    says why the model did something only roughly, and it can quote the paper.
    """
    content = (reply.raw or {}).get("content") or []
    return [
        block.get("thinking", "")
        for block in content
        if isinstance(block, dict) and block.get("type") == "thinking" and block.get("thinking")
    ]


@dataclass(frozen=True)
class Job:
    """One request: its name in the record, and what is sent."""

    id: str
    system: str
    message: str
    schema: dict[str, Any]


def append(path: Path, line: Mapping[str, Any]) -> None:
    """Add one line to a record."""
    # Opened for each line and never kept: a line is on the disk when this returns, and a
    # record that the command is stopped over ends with a whole line.
    with path.open("a", encoding="utf-8", newline="\n") as stream:
        stream.write(json.dumps(line, ensure_ascii=False) + "\n")


def read_record(
    path: Path, record: str
) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, Any] | None]:
    """A record as it lies: its first line, the lines after it, and its last line if it has one."""
    try:
        text = path.read_text(encoding="utf-8")
        lines = [json.loads(line) for line in text.splitlines() if line.strip()]
    except (UnicodeDecodeError, ValueError) as error:
        raise AskError(f"{path.name}: a line that is not JSON ({error})") from error
    if not lines or not isinstance(lines[0], dict) or lines[0].get("record") != record:
        raise AskError(f"{path.name}: not a record of {record}")
    end = lines[-1] if lines[-1].get("record") == END else None
    return lines[0], [line for line in lines[1:] if line.get("record") != END], end


def answered(lines: Iterable[Mapping[str, Any]]) -> set[str]:
    """The requests that got a reply. One that the API failed is not among them."""
    return {line["id"] for line in lines if line.get("record") == REPLY}


def replies(lines: Iterable[Mapping[str, Any]]) -> dict[str, dict[str, Any]]:
    """The reply line of every request that has one, by its name."""
    return {line["id"]: dict(line) for line in lines if line.get("record") == REPLY}


class Stop(Exception):
    """Why the runner gives up: more requests would end the same way."""


class Runner:
    """Asks every job once and writes each reply down as it comes.

    `on_reply` makes what a reply line says of the job and the reply, with an "outcome" in
    a word when it has one; the runner adds what every line has (its kind, the job, how
    the reply stopped, its usage, the model and the seconds it took).
    """

    def __init__(
        self,
        asker: Asker,
        jobs: Sequence[Job],
        out: Path,
        on_reply: Callable[[Job, Reply], dict[str, Any]],
        parallel: int = 1,
        echo: Callable[[str], None] = print,
    ) -> None:
        names = [job.id for job in jobs]
        if len(set(names)) != len(names):
            raise AskError("two requests have the same name")
        self._asker = asker
        self._jobs = list(jobs)
        self._out = out
        self._on_reply = on_reply
        self._parallel = max(1, parallel)
        self._echo = echo
        self._failures = 0
        self._stop: str | None = None

    def to_ask(self, lines: Sequence[Mapping[str, Any]]) -> list[Job]:
        """What is still to ask, in the order of the jobs."""
        done = answered(lines)
        return [job for job in self._jobs if job.id not in done]

    async def _one(self, job: Job) -> None:
        begun = time.monotonic()
        try:
            reply = await self._asker.ask(job.system, job.message, job.schema)
        except ModelError as error:
            failed = {"kind": error.kind, "detail": error.detail, "status": error.status}
            append(self._out, {"record": FAILED, "id": job.id, "error": failed})
            self._echo(f"  {job.id} failed: {error.kind}")
            self._failures += 1
            if (
                error.kind in _REFUSALS
                or error.status in _REFUSING_STATUS
                or "credit balance" in error.detail.lower()
            ):
                self._stop = f"the API refuses: {str(error)[:300]}"
            elif self._failures >= API_FAILURES_IN_A_ROW:
                self._stop = f"the API failed {self._failures} requests in a row"
            return
        self._failures = 0
        line = {
            "record": REPLY,
            "id": job.id,
            **self._on_reply(job, reply),
            "stop_reason": reply.stop_reason,
            "blocks": list(reply.blocks),
            "usage": reply.usage,
            "model": reply.model,
            "seconds": round(time.monotonic() - begun, 1),
        }
        append(self._out, line)
        self._echo(f"  {job.id} {line.get('outcome', reply.stop_reason)}")

    async def run(self, lines: Sequence[Mapping[str, Any]]) -> None:
        """Ask what `lines`, the lines of the record so far, leave to ask."""
        waiting = iter(self.to_ask(lines))

        async def worker() -> None:
            # The workers share one row of jobs. Nothing is awaited between taking a job
            # and starting it, so each is taken once.
            for job in waiting:
                if self._stop is not None:
                    return
                await self._one(job)

        await asyncio.gather(*(worker() for _ in range(self._parallel)))
        if self._stop is not None:
            raise Stop(self._stop)


def private_path_problem(path: Path) -> str | None:
    """Why a file that will hold paper text must not be written at `path`, or None.

    Paper text is never committed (CLAUDE.md), and runs_private/ is the folder that git
    ignores for it. A path inside a repository that git would not ignore is refused. A path
    outside any repository, or one where git cannot be asked, is allowed: nothing there can
    be committed by mistake from this repository.
    """
    target = path.resolve()
    base = target.parent
    while not base.exists() and base != base.parent:
        base = base.parent
    try:
        inside = subprocess.run(
            ["git", "-C", str(base), "rev-parse", "--is-inside-work-tree"],
            capture_output=True,
            timeout=10,
            check=False,
        )
        if inside.returncode != 0 or inside.stdout.strip() != b"true":
            return None
        ignored = subprocess.run(
            ["git", "-C", str(base), "check-ignore", "-q", "--", str(target.relative_to(base))],
            capture_output=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.SubprocessError, ValueError):
        return None
    if ignored.returncode == 1:
        return f"{path} is not a path that git ignores: put files with paper text in runs_private/"
    return None


def stamp() -> str:
    return datetime.datetime.now(datetime.UTC).isoformat(timespec="seconds")


def run_command(
    *,
    out: Path,
    record: str,
    head: Mapping[str, Any],
    runner: Runner,
    totals: Callable[[Sequence[Mapping[str, Any]]], dict[str, Any]],
    plan_only: bool,
    given: bool,
    what: str,
    after_head: Sequence[Mapping[str, Any]] = (),
) -> tuple[int, list[dict[str, Any]]]:
    """What draft.py and sift.py do once they know their jobs, as the judge does it.

    `after_head` are lines that a new record holds right after its first line, before any
    reply (sift.py writes the checks of the drafts there). A record that is begun already
    has them: the same first line means the same inputs and the same code.

    Returns the exit status and the lines of the record as it stands at the end.
    """
    code = head.get("code") or {}
    if code.get("modified") is not False:
        # A record names the commit that made it. Changed code has no commit to name, and
        # neither has code that git cannot be asked about: run.py refuses both as well.
        if code.get("modified"):
            print("refused: the code has changes that are not committed", file=sys.stderr)
        else:
            print("refused: git cannot say which commit this code is", file=sys.stderr)
        return 1, []
    lines: list[dict[str, Any]] = []
    end = None
    if out.exists():
        try:
            begun, lines, end = read_record(out, record)
        except AskError as error:
            print(f"refused: {error}", file=sys.stderr)
            return 1, []
        begun = {name: value for name, value in begun.items() if name != "started_at"}
        if begun != dict(head):
            differing = sorted(
                name for name in set(begun) | set(head) if begun.get(name) != head.get(name)
            )
            print(
                f"refused: {out} was begun with something else ({', '.join(differing)}); "
                "move it away first",
                file=sys.stderr,
            )
            return 1, lines
    waiting = runner.to_ask(lines)
    total = len(runner.to_ask([]))
    print(f"{total} request(s): {total - len(waiting)} done, {len(waiting)} to ask")
    if plan_only or end is not None:
        return 0, lines
    if waiting and not given and not os.environ.get("ANTHROPIC_API_KEY"):
        print(
            f"ANTHROPIC_API_KEY is not set in this shell, so {what} cannot be asked.",
            file=sys.stderr,
        )
        return 2, lines
    if not out.exists():
        out.parent.mkdir(parents=True, exist_ok=True)
        append(out, {**head, "started_at": stamp()})
        for line in after_head:
            append(out, line)
        lines = list(map(dict, after_head))
    try:
        asyncio.run(runner.run(lines))
    except Stop as stop:
        print(f"stopped: {stop}", file=sys.stderr)
        return 1, read_record(out, record)[1]
    _, lines, _ = read_record(out, record)
    left = len(runner.to_ask(lines))
    if left:
        # The last line stands for a record in which every request has its reply.
        print(
            f"{left} request(s) got no reply from the API: start the command again",
            file=sys.stderr,
        )
        return 1, lines
    append(out, totals(lines))
    return 0, lines


def usage_totals(lines: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    """The usage of every reply added up, and its cost at the list prices of eval/report.py."""
    used: dict[str, int] = {}
    cost: float | None = 0.0
    for line in lines:
        if line.get("record") != REPLY:
            continue
        for name, value in (line.get("usage") or {}).items():
            if isinstance(value, int):
                used[name] = used.get(name, 0) + value
        one = cost_of([line], line.get("model"))
        cost = None if cost is None or one is None else cost + one
    # Worked out from the usage at the list prices; not read from the Console.
    return {"usage": dict(sorted(used.items())), "cost": cost}


def checked_code() -> dict[str, Any]:
    """The commit of this code, for the first line of a record (agent/origin.py)."""
    return code_version()
