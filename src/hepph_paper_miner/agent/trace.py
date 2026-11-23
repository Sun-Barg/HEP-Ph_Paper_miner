"""The record of one run, written while it runs.

Two files, one line of JSON per event (the run, each turn, the end):

    public    what happened, without any text a tool returned. Sizes, hashes and the
              facts of each result's first line stand in for the text. This file may
              be committed and published.
    private   the same events with everything: the tool results (paper text), the
              model's raw responses. It lives outside the repository and is never
              committed: paper text is not ours to redistribute.

A line is written when its event is over, so a run that dies leaves what it had done.
A run is complete when its file ends with the "end" line.
"""

from __future__ import annotations

import hashlib
import json
import os
import secrets
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from hepph_paper_miner.agent.model import Reply, ToolCall
from hepph_paper_miner.result_text import read_first_line

RUNS_ENV = "HEPPH_PAPER_MINER_RUNS"

# What became of a tool call.
OK = "ok"  # the tool ran and returned a result
ERROR = "error"  # the tool ran and returned an error result
# The loop answered the call itself, with an error text: the model was given no tool of
# that name, or the call was for the loop's own tool and its arguments were no answer.
NOT_SENT = "not_sent"
NOT_RUN = "not_run"  # the run ended before the call was made (the turn limit, or an answer)
FAILED = "failed"  # the call got no result at all, and the run ended with it
# The call handed in the answer of the run (the loop's own tool: prompt.py). Nothing was
# returned for it, so it adds nothing to the count of results the model read.
ANSWER = "answer"


def default_private_dir() -> Path:
    """Where the private records go unless the environment says otherwise.

    Under the home directory and outside the repository, so that a careless
    `git add` cannot pick up paper text.
    """
    configured = os.environ.get(RUNS_ENV)
    return Path(configured) if configured else Path.home() / "hepph-paper-miner-runs"


def new_run_id(question_id: str, toolset: str, now: datetime | None = None) -> str:
    """A name for a run that sorts by time and says what was run.

    The four random characters keep two runs of one question in one second apart.
    """
    moment = now or datetime.now(UTC)
    return f"{moment:%Y%m%dT%H%M%SZ}_{question_id}_{toolset}_{secrets.token_hex(2)}"


@dataclass(frozen=True)
class ToolRecord:
    """One tool call and what the model was given for it."""

    call: ToolCall
    status: str
    text: str | None = None  # what the model read; None when it was given nothing
    seconds: float = 0.0
    error_kind: str | None = None

    @property
    def is_error(self) -> bool:
        return self.status in (ERROR, NOT_SENT)

    def public(self) -> dict[str, Any]:
        """Everything about the call except the text of its result."""
        facts: dict[str, Any] = {
            "id": self.call.id,
            "name": self.call.name,
            "arguments": self.call.arguments,
            "status": self.status,
            "error_kind": self.error_kind,
            "seconds": round(self.seconds, 3),
        }
        if self.text is not None:
            facts["result_chars"] = len(self.text)
            facts["result_sha256"] = hashlib.sha256(self.text.encode("utf-8")).hexdigest()
            # Read from the text the model was given, and from nowhere else: the
            # record cannot say something the model did not see.
            facts["first_line"] = read_first_line(self.text) if self.status == OK else None
        return facts


class Trace:
    """Writes the two files of one run."""

    def __init__(
        self,
        run_id: str,
        public_dir: Path,
        private_dir: Path | None,
        *,
        labels: dict[str, Any] | None = None,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self.run_id = run_id
        self.public_path = public_dir / f"{run_id}.jsonl"
        self.private_path = private_dir / f"{run_id}.jsonl" if private_dir else None
        self._labels = dict(labels or {})
        self._now = now
        self._tool_calls = 0
        self._tool_result_chars = 0
        # What the API counted, added up over the turns. input_tokens is the part of
        # every prompt that was billed in full. With the cache on (model.py), the rest
        # of a prompt is in the two cache counts, and its size is the sum of the three.
        self._tokens = {
            "input_tokens": 0,
            "output_tokens": 0,
            "cache_creation_input_tokens": 0,
            "cache_read_input_tokens": 0,
        }
        self._parsers: list[str] = []
        self._models: list[str] = []
        # "x": a run never writes into another's file. When one of the two cannot be
        # made, the one this run has made goes again, for the reason given in
        # __main__.py: left behind and empty, it would read as a run that died.
        made: list[Path] = []
        try:
            for path in (self.public_path, self.private_path):
                if path is not None:
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.open("x", encoding="utf-8").close()
                    made.append(path)
        except OSError:
            for path in made:
                path.unlink(missing_ok=True)
            raise

    def start(self, facts: dict[str, Any], private: dict[str, Any]) -> None:
        """The first line: what was run. `private` is added in the private file only."""
        line = {
            "record": "run",
            "run_id": self.run_id,
            **self._labels,
            **facts,
            "started_at": self._stamp(),
        }
        self._write(self.public_path, line)
        self._write(self.private_path, {**line, **private})

    def turn(
        self,
        number: int,
        reply: Reply,
        seconds: float,
        tools: Sequence[ToolRecord],
        asked_again: str | None = None,
    ) -> None:
        """One response of the model and what followed it: its tool calls, or a message.

        `asked_again` is the message the loop wrote after this response, when the turn
        had ended without the call that hands in the answer (loop.py). The public line
        says that it did; the private line has the message as well, since it holds
        everything the model was given.
        """
        for name in self._tokens:
            self._tokens[name] += int(reply.usage.get(name) or 0)
        public_tools = [tool.public() for tool in tools]
        for tool, facts in zip(tools, public_tools, strict=True):
            if tool.text is not None:
                self._tool_calls += 1
                self._tool_result_chars += len(tool.text)
            parser = (facts.get("first_line") or {}).get("parser")
            if parser and parser not in self._parsers:
                self._parsers.append(parser)
        if reply.model and reply.model not in self._models:
            self._models.append(reply.model)
        line = {
            "record": "turn",
            "turn": number,
            "seconds": round(seconds, 3),
            # The model that answered, as the response names it. The first line of the
            # record has the name that was asked for; this is what the API says it got.
            "response_model": reply.model,
            "stop_reason": reply.stop_reason,
            "stop_details": reply.stop_details,
            "blocks": list(reply.blocks),
            "usage": reply.usage,
        }
        if asked_again is not None:
            # Only on the line of that response: a line without it is the line of a
            # response the loop did not ask about, in a record of any age.
            line["asked_again"] = True
        self._write(self.public_path, {**line, "tools": public_tools})
        self._write(
            self.private_path,
            {
                **line,
                "tools": public_tools,
                "reply": reply.raw if reply.raw is not None else {"text": reply.text},
                "tool_results": [{"id": tool.call.id, "text": tool.text} for tool in tools],
                **({"asked_with": asked_again} if asked_again is not None else {}),
            },
        )

    def end(
        self,
        reason: str,
        detail: str,
        answer: dict[str, Any] | None,
        turns: int,
        seconds: float,
        asked_again: int | None = None,
    ) -> None:
        """The last line: why the run ended, the answer if there is one, and the totals.

        `asked_again` is the number of the response after which the loop asked for the
        call that hands in the answer, or None when it did not ask.
        """
        line = {
            "record": "end",
            "run_id": self.run_id,
            "reason": reason,
            "detail": detail,
            "answer": answer,
            # Always written, so that a record says of itself that the loop did not ask.
            # A record without it was made by a loop that could not (before p3-tool).
            "asked_again": asked_again,
            "turns": turns,
            "seconds": round(seconds, 3),
            # Every result the model was given counts, error texts included: this is
            # the amount of text it had to read to get where it got.
            "tool_calls": self._tool_calls,
            "tool_result_chars": self._tool_result_chars,
            **self._tokens,
            "parser_versions": self._parsers,
            "response_models": self._models,
            "ended_at": self._stamp(),
        }
        self._write(self.public_path, line)
        self._write(self.private_path, line)

    def _stamp(self) -> str:
        return self._now().isoformat(timespec="seconds")

    @staticmethod
    def _write(path: Path | None, line: dict[str, Any]) -> None:
        if path is None:
            return
        with path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(line, ensure_ascii=False) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
