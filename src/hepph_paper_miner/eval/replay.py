"""Send the end of a run again, with the message of the loop after it, and count what comes back.

    uv run python -m hepph_paper_miner.eval.replay --runs results/runs/regress/dev-after \
        --repeats 10 --out results/runs/asking-again/replay-dev-02.jsonl

Since the prompt p3-tool the loop asks for the call that hands in the answer when a turn
ends without it (agent/loop.py). Runs seldom end that way: three of the 256 runs in this
repository that hand in with the tool and count. So thirty runs made anew will most
likely not meet the message at all, and say nothing of what it does.

This command makes the case happen. It takes runs that did end their turn without the
call, builds the conversation of each again from its private record, as the loop had
sent it, puts the reply and the message of the loop at its end as the loop now would,
and sends that request a number of times. The request is the one the loop would send:
the same system prompt, tools and settings (it refuses a run whose texts are not the
ones the code has now). Each response is read as the loop reads it, and is one of:

    handed in     it calls the loop's tool with an answer of the expected form
    asked on      it asks for tools and hands in no answer; the loop would run them and
                  go on, this command does not, so what would follow is not known
    text again    it ends the turn again without the call; the loop would end the run
                  without an answer
    other         any other end of a response (cut off, refused), or no response at all

How the count is read was written down here before any such request was made. There
are two such runs of a development question, both of dev-02 on 2026-11-20
(results/runs/regress/README.md), and each is sent ten times: twenty requests. When
eighteen or more of the twenty are "handed in", the message is said to have got the
answer handed in at these two ends. With fewer it is said not to have, and another way
to get such an answer is tried. Eighteen is nine in ten, a choice made before the
requests; "asked on" counts against the message, although a run of the loop might still
have ended with an answer.

What this can show is small. It is two conversations of one question, sent again; it
says nothing of how often a run ends this way, or of an end that looks different. The
run of the evaluation that ended this way (eval-13) is not sent: its question belongs
to the evaluation, and nothing here is tried on those.

The record of the command has a line for every request, without any text a tool
returned or the model wrote, except an answer that was handed in. With --private a
second file keeps the responses whole, outside the repository. A run whose record holds
thinking blocks is sent with them as they were kept; that the API takes them a second
time has not been tried, and the two runs of dev-02 hold none.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import anyio

from hepph_paper_miner.agent.loop import _handed_in, _tool_result
from hepph_paper_miner.agent.model import ClaudeModel, Model, ModelError, Reply, ToolCall
from hepph_paper_miner.agent.origin import code_version
from hepph_paper_miner.agent.prompt import (
    ANSWER_TOOL,
    ASK_AGAIN_TEXT,
    PROMPT_VERSION,
    TOOL,
    system_prompt,
)
from hepph_paper_miner.agent.trace import ToolRecord, default_private_dir
from hepph_paper_miner.eval.report import cost_of
from hepph_paper_miner.eval.run import Attempt, attempts_in, counted

HANDED_IN, ASKED_ON, TEXT_AGAIN, OTHER = "handed in", "asked on", "text again", "other"
REPEATS = 10


class ReplayError(ValueError):
    """A run that cannot be sent again as the loop would send it."""


@dataclass(frozen=True)
class Source:
    """A run that ended its turn without the call, and the request that asks for it."""

    attempt: Attempt
    system: str
    tools: list[dict[str, Any]]
    messages: list[dict[str, Any]]


def ended_without_the_call(attempt: Attempt) -> bool:
    """Whether the run ended as the loop now asks about: with a turn that held no call."""
    run, end = attempt.run, attempt.end or {}
    last = attempt.turns[-1] if attempt.turns else {}
    limit = (run.get("limits") or {}).get("max_turns", 0)
    return (
        run.get("answer_channel") == TOOL
        and end.get("reason") == "no_answer"
        # A run the loop had asked already ended with its second such turn.
        and end.get("asked_again") is None
        and last.get("stop_reason") == "end_turn"
        # The loop asks only about a response that holds something, and not about the
        # last one the limit allows (agent/loop.py).
        and bool(last.get("blocks"))
        and not last.get("tools")
        and len(attempt.turns) < limit
    )


def _block(block: Mapping[str, Any]) -> dict[str, Any]:
    """A content block of a kept response, with what a request has to hold of it."""
    kind = block.get("type")
    if kind == "text":
        return {"type": "text", "text": block["text"]}
    if kind == "tool_use":
        return {k: block[k] for k in ("type", "id", "name", "input")}
    if kind == "thinking":
        return {
            "type": kind,
            "thinking": block.get("thinking", ""),
            "signature": block["signature"],
        }
    if kind == "redacted_thinking":
        return {"type": kind, "data": block["data"]}
    raise ReplayError(f"a block of the kind {kind!r} cannot be sent again")


def conversation(attempt: Attempt, private: Path) -> Source:
    """The request that follows the last response of the run, as the loop now makes it.

    Built from the private record, and held against the public one line by line: the
    same turns, the same calls, and for every result the text whose hash the public
    record keeps. Refused when the texts of the run are not those of the code.
    """
    from hepph_paper_miner.server import TOOLSET_VERSION

    run_id = attempt.run["run_id"]
    try:
        lines = [json.loads(text) for text in private.read_text("utf-8").splitlines()]
    except (OSError, ValueError) as error:
        raise ReplayError(f"{run_id}: its private record cannot be read: {error}") from error
    head = lines[0] if lines else {}
    turns = [line for line in lines if line.get("record") == "turn"]
    if head.get("record") != "run" or head.get("run_id") != run_id:
        raise ReplayError(f"{private.name} is not the private record of {run_id}")
    if len(turns) != len(attempt.turns):
        raise ReplayError(f"{run_id}: the two records differ in their turns")

    system, tools = head.get("system"), head.get("tool_definitions") or []
    layout = attempt.run.get("toolset")
    now = (
        TOOLSET_VERSION.get(layout) == attempt.run.get("toolset_version"),
        system == system_prompt(TOOL),
        bool(tools) and tools[-1] == ANSWER_TOOL,
    )
    if not all(now):
        raise ReplayError(
            f"{run_id}: its tool texts, system prompt or answer tool are not the ones the code "
            "has now, so the loop would not send this conversation"
        )

    messages: list[dict[str, Any]] = [{"role": "user", "content": head["question"]}]
    for public, kept in zip(attempt.turns, turns, strict=True):
        content = (kept.get("reply") or {}).get("content")
        if not isinstance(content, list) or [b.get("type") for b in content] != public["blocks"]:
            raise ReplayError(f"{run_id}: turn {public['turn']} is not kept as the loop sent it")
        messages.append({"role": "assistant", "content": [_block(block) for block in content]})
        texts = {result["id"]: result["text"] for result in kept.get("tool_results") or []}
        results = []
        for call in public["tools"]:
            text = texts.get(call["id"])
            digest = hashlib.sha256((text or "").encode("utf-8")).hexdigest()
            if text is None or digest != call.get("result_sha256"):
                raise ReplayError(
                    f"{run_id}: the result of {call['name']} in turn {public['turn']} is not "
                    "the text the public record names"
                )
            record = ToolRecord(
                ToolCall(call["id"], call["name"], call["arguments"]), call["status"], text
            )
            results.append(_tool_result(record))
        if results:
            messages.append({"role": "user", "content": results})
    if messages[-1]["role"] != "assistant":
        raise ReplayError(f"{run_id}: the run did not end with a response that asked for no tool")
    # What the loop does since p3-tool: the reply as it came, then its one message.
    messages.append({"role": "user", "content": ASK_AGAIN_TEXT})
    return Source(attempt, system, tools, messages)


def model_of(settings: Mapping[str, Any], client: Any = None) -> ClaudeModel:
    """The model as the run had it, so that the request is made with the same settings.

    `client` is for asking whether the settings can be made again without a key at hand.
    """
    thinking = settings.get("thinking") or {}
    try:
        model = ClaudeModel(
            settings["model"],
            max_tokens=settings["max_tokens"],
            effort=settings["effort"],
            cache=settings.get("cache_control") is not None,
            show_thinking=thinking.get("display") == "summarized",
            answer_format=False,
            max_retries=settings["max_retries"],
            request_seconds=settings["request_seconds"],
            client=client,
        )
    except KeyError as error:
        raise ReplayError(f"the record of the run does not name its {error.args[0]}") from error
    asked = {name: value for name, value in settings.items() if name != "sdk"}
    made = {name: value for name, value in model.settings.items() if name != "sdk"}
    if asked != made:
        raise ReplayError(f"the settings of the run cannot be made again: {asked} is not {made}")
    return model


def outcome_of(reply: Reply) -> tuple[str, dict[str, Any] | None]:
    """What a response is to the loop that asked for the call, and the answer if it has one."""
    if reply.stop_reason == "tool_use":
        handed_in = _handed_in(reply.tool_calls)
        if handed_in is not None:
            return HANDED_IN, handed_in[1]
        return (ASKED_ON, None) if reply.tool_calls else (OTHER, None)
    return (TEXT_AGAIN if reply.stop_reason == "end_turn" else OTHER), None


class Record:
    """Writes the lines of the record as they come: the public file, and the private one."""

    def __init__(self, public: Path, private: Path | None) -> None:
        self.paths = [path for path in (public, private) if path is not None]
        for path in self.paths:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.open("x", encoding="utf-8").close()  # never over a record that is there

    def write(self, line: dict[str, Any], kept: dict[str, Any] | None = None) -> None:
        """One line. `kept` is added in the private file only."""
        for index, path in enumerate(self.paths):
            whole = {**line, **(kept or {})} if index else line
            with path.open("a", encoding="utf-8", newline="\n") as handle:
                handle.write(json.dumps(whole, ensure_ascii=False) + "\n")
                handle.flush()
                os.fsync(handle.fileno())


def _stamp() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


async def send(
    sources: Sequence[Source],
    repeats: int,
    record: Record,
    model_for: Callable[[Mapping[str, Any]], Model],
    say: Callable[[str], None] = print,
) -> Counter:
    """Send every request `repeats` times, one after the other, and count the outcomes."""
    counts: Counter = Counter()
    usages: dict[str, list[dict[str, Any]]] = {}
    for source in sources:
        run = source.attempt.run
        model = model_for(run["model"])
        for repeat in range(1, repeats + 1):
            began = time.monotonic()
            line: dict[str, Any] = {"record": "request", "run_id": run["run_id"], "repeat": repeat}
            kept: dict[str, Any] = {}
            try:
                reply = await model.reply(source.system, source.messages, source.tools, None)
            except ModelError as error:
                outcome = OTHER
                line.update(stop_reason=None, error=str(error)[:300])
            else:
                outcome, answer = outcome_of(reply)
                line.update(
                    stop_reason=reply.stop_reason,
                    response_model=reply.model,
                    blocks=list(reply.blocks),
                    calls=[call.name for call in reply.tool_calls],
                    usage=reply.usage,
                    answer=answer,
                )
                usages.setdefault(run["model"]["model"], []).append({"usage": reply.usage})
                kept["reply"] = reply.raw if reply.raw is not None else {"text": reply.text}
            line.update(outcome=outcome, seconds=round(time.monotonic() - began, 3))
            record.write(line, kept)
            counts[run["run_id"], outcome] += 1
            say(f"{run['run_id']} | {repeat}/{repeats} | {outcome}")
    costs = [cost_of(turns, name) for name, turns in usages.items()]
    by_outcome = Counter()
    for (_, outcome), number in counts.items():
        by_outcome[outcome] += number
    record.write(
        {
            "record": "end",
            "requests": sum(counts.values()),
            "outcomes": dict(sorted(by_outcome.items())),
            "by_run": {
                run_id: {o: n for (r, o), n in sorted(counts.items()) if r == run_id}
                for run_id in dict.fromkeys(r for r, _ in counts)
            },
            "cost": None if None in costs else round(sum(costs), 4),
            "ended_at": _stamp(),
        }
    )
    return by_outcome


def read_record(path: Path) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, Any] | None]:
    """The first line of a record of this command, its requests, and its last line if it has one."""
    lines = [json.loads(text) for text in path.read_text("utf-8").splitlines()]
    if not lines or lines[0].get("record") != "replay":
        raise ReplayError(f"{path.name} is not a record of this command")
    end = lines[-1] if lines[-1].get("record") == "end" else None
    return lines[0], [line for line in lines if line.get("record") == "request"], end


def main(
    argv: Sequence[str] | None = None,
    model_for: Callable[[Mapping[str, Any]], Model] = model_of,
) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m hepph_paper_miner.eval.replay",
        description="Send the end of runs that ended without the call again, with the "
        "message of the loop, and count what comes back.",
    )
    parser.add_argument("--runs", type=Path, required=True, help="folder of the public records")
    parser.add_argument(
        "--only", nargs="+", metavar="RUN_ID", help="these runs only (default: every such run)"
    )
    parser.add_argument(
        "--repeats", type=int, default=REPEATS, help="requests for each run (default: %(default)s)"
    )
    parser.add_argument("--out", type=Path, required=True, help="the record to write (JSONL)")
    parser.add_argument(
        "--private",
        type=Path,
        default=None,
        help="folder of the private records, where the responses are kept whole as well "
        "(default: the folder the runs write theirs to)",
    )
    parser.add_argument(
        "--plan", action="store_true", help="say what would be sent, and send nothing"
    )
    arguments = parser.parse_args(argv)
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="backslashreplace")
    if arguments.repeats < 1:
        print("--repeats has to be at least 1", file=sys.stderr)
        return 2
    private = arguments.private or default_private_dir()

    found = [a for a in counted(attempts_in(arguments.runs)).values() if ended_without_the_call(a)]
    if arguments.only:
        by_id = {attempt.run["run_id"]: attempt for attempt in found}
        missing = [run_id for run_id in arguments.only if run_id not in by_id]
        if missing:
            print(
                f"refused: no run that ended without the call is named {missing[0]}",
                file=sys.stderr,
            )
            return 2
        found = [by_id[run_id] for run_id in arguments.only]
    if not found:
        print(
            f"refused: {arguments.runs} holds no run that ended without the call", file=sys.stderr
        )
        return 2
    try:
        sources = [conversation(a, private / f"{a.run['run_id']}.jsonl") for a in found]
        for source in sources:
            # Asked before the first request, so that no run is found out halfway.
            model_of(source.attempt.run.get("model") or {}, client=object())
    except ReplayError as error:
        print(f"refused: {error}", file=sys.stderr)
        return 2

    code = code_version()
    print(f"code      {code.get('commit')} | modified {code.get('modified')}")
    print(f"message   {PROMPT_VERSION[TOOL]} | {ASK_AGAIN_TEXT}")
    for source in sources:
        run, messages = source.attempt.run, source.messages
        chars = sum(len(json.dumps(message["content"])) for message in messages)
        print(f"{run['run_id']} | {len(source.attempt.turns)} turn(s) | {chars} characters to send")
    if arguments.plan:
        print(f"{len(sources)} run(s), {arguments.repeats} request(s) each: nothing was sent")
        return 0
    if code.get("modified") is not False:
        print("refused: files the repository keeps have been changed", file=sys.stderr)
        return 2
    if model_for is model_of and not os.environ.get("ANTHROPIC_API_KEY"):
        print("refused: ANTHROPIC_API_KEY is not set in this shell", file=sys.stderr)
        return 2
    try:
        record = Record(arguments.out, private / arguments.out.name)
    except OSError as error:
        print(f"refused: the record cannot be made: {error}", file=sys.stderr)
        return 2
    record.write(
        {
            "record": "replay",
            "prompt_version": PROMPT_VERSION[TOOL],
            "message_sha256": hashlib.sha256(ASK_AGAIN_TEXT.encode("utf-8")).hexdigest(),
            "repeats": arguments.repeats,
            "code": code,
            "runs": [
                {
                    name: source.attempt.run.get(name)
                    for name in ("run_id", "question_id", "toolset", "toolset_version", "model")
                }
                | {
                    "prompt_version": source.attempt.run.get("prompt_version"),
                    "code": source.attempt.run.get("code"),
                    "turns": len(source.attempt.turns),
                    "thinking_blocks": sum(
                        kind in ("thinking", "redacted_thinking")
                        for turn in source.attempt.turns
                        for kind in turn["blocks"]
                    ),
                }
                for source in sources
            ],
            "started_at": _stamp(),
        }
    )
    counts = anyio.run(send, sources, arguments.repeats, record, model_for)
    total = sum(counts.values())
    said = ", ".join(f"{number} {outcome}" for outcome, number in sorted(counts.items()))
    print(f"{total} request(s): {said}")
    print(f"record    {arguments.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
