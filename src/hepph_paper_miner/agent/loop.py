"""The loop: ask the model, run the tools it asks for, hand back the results, until it answers.

The Claude SDK has a tool runner that does this. This one is written by hand for
three things the runner does not give:

    why a run ended     Every run ends with one of the reasons below, and the caller
                        gets it as a value. The runner stops without saying why, and
                        a run cut off by its iteration limit looks like any other.
    what counts as      Only what comes in the way chosen for the run, and has the
    the answer          expected form, is an answer (prompt.py names the ways). The
                        runner returns the last message, whatever it is.
    a record            Every turn is written down as it happens (trace.py).

What it leaves to others: retries of API requests are the SDK's (model.py), and the
tools retry their own requests to arXiv (http.py).
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import asdict, dataclass
from enum import Enum
from importlib.metadata import version
from typing import Any

from mcp import Client, MCPError
from mcp.types import REQUEST_TIMEOUT

from hepph_paper_miner.agent.model import Model, ModelError, Reply, ToolCall
from hepph_paper_miner.agent.origin import code_version
from hepph_paper_miner.agent.prompt import (
    ANSWER_SCHEMA,
    ANSWER_TOOL,
    FORMAT,
    INVALID_ANSWER_TEXT,
    PROMPT_VERSION,
    TOOL,
    as_answer,
    read_answer,
    system_prompt,
    unknown_tool_text,
)
from hepph_paper_miner.agent.trace import (
    ANSWER,
    ERROR,
    FAILED,
    NOT_RUN,
    NOT_SENT,
    OK,
    ToolRecord,
    Trace,
)
from hepph_paper_miner.result_text import error_kind


# Packages that write a part of what a model reads. The SDK puts its own words in front
# of an error and makes the schema of every tool from the tool's arguments; pydantic
# writes the sentence for arguments that break a schema, and names its own version in
# it. The name of the tool texts does not cover any of that, so the versions go into
# the record beside it. They are the versions in this process, which is also where
# the command runs the server.
_WRITE_FOR_THE_MODEL = ("mcp", "pydantic")


class EndReason(str, Enum):
    """Why a run ended. There is no run without one."""

    ANSWERED = "answered"  # the model handed in an answer of the expected form
    NO_ANSWER = "no_answer"  # it ended its turn without one (what was missing is in the detail)
    TURN_LIMIT = "turn_limit"  # the last allowed response still asked for tools
    MAX_TOKENS = "max_tokens"  # a response was cut off at the output limit
    REFUSAL = "refusal"  # the API declined to answer
    CONTEXT_FULL = "context_full"  # the conversation outgrew the model's context window
    UNEXPECTED_STOP = "unexpected_stop"  # a stop reason this loop should never see
    API_ERROR = "api_error"  # the API gave no response, after the SDK's retries
    TIME_LIMIT = "time_limit"  # the run took too long (checked between turns)
    TOOL_TRANSPORT_ERROR = "tool_transport_error"  # a tool call broke at the protocol level
    TOOL_TIMEOUT = "tool_timeout"  # a tool call did not return in time


# stop_reason values of the API that end a run without an answer. "end_turn" and
# "tool_use" are handled in the loop. Whatever is not listed is unexpected, and that
# includes "pause_turn" (only server-side tools cause it, and there are none here)
# and "stop_sequence" (none is sent).
_STOPS = {
    "max_tokens": EndReason.MAX_TOKENS,
    "refusal": EndReason.REFUSAL,
    "model_context_window_exceeded": EndReason.CONTEXT_FULL,
}


@dataclass(frozen=True)
class Limits:
    """How far a run may go. The defaults are the limits of the evaluation (eval/conditions.py).

    max_turns is not shown to the model, so it changes a run only where it ends one.
    It was kept at its first value: handing in the answer through the loop's tool, the
    thirty runs of results/runs/dev/diag-3-tool/ ended after two to six responses.

    tool_seconds is a backstop, not a budget. The arXiv source gives up by itself
    and says so ("[timeout]", "[upstream_busy]"); in the worst case, three requests
    with five tries of 30 s each and 69 s of pauses, that takes about eleven
    minutes. The limit here is longer, so that it only ends a call that would never
    have come back.

    run_seconds is looked at between turns only, so a run can exceed it by one
    turn: one API request with its retries, and the tool calls that follow.
    """

    max_turns: int = 12
    tool_seconds: float = 700.0
    run_seconds: float = 900.0

    def __post_init__(self) -> None:
        if self.max_turns < 1:
            raise ValueError("max_turns has to be at least 1")


@dataclass(frozen=True)
class Outcome:
    """How a run ended."""

    reason: EndReason
    detail: str
    answer: dict[str, Any] | None  # {"answer", "found", "evidence"} when reason is ANSWERED
    turns: int


class _ToolFailure(Exception):
    """A tool call that produced no result. It ends the run."""

    def __init__(self, reason: EndReason, detail: str) -> None:
        super().__init__(reason, detail)
        self.reason = reason
        self.detail = detail


async def run(
    question: str,
    *,
    client: Client,
    model: Model,
    trace: Trace,
    channel: str,
    limits: Limits | None = None,
    clock: Callable[[], float] = time.monotonic,
) -> Outcome:
    """Answer one question with the tools of the connected server.

    A turn is one response of the model. With max_turns = N the model is asked at
    most N times, and tools are run at most N - 1 times: if the Nth response still
    asks for tools, they are not run, because nobody would read their results.

    `channel` is the way the answer is handed in (prompt.py). It decides which
    system prompt the model reads, whether it is given the loop's own tool, and
    what is taken for the answer. It has no default: whoever starts a run says which
    way it uses, so that no run is made in a way that nobody chose.
    """
    limits = limits or Limits()
    if channel not in PROMPT_VERSION:
        raise ValueError(f"no such way to hand in an answer: {channel!r}")
    listed = (await client.list_tools()).tools
    # The server's own names, descriptions and schemas, passed on unchanged. They are
    # all of the server that the model is shown. The instructions a server sends when
    # a client connects (client.instructions) are not passed on, although a host may
    # put them into its system prompt: the model reads the system prompt of this loop.
    tools = [
        {
            "name": tool.name,
            "description": tool.description or "",
            "input_schema": tool.input_schema,
        }
        for tool in listed
    ]
    if channel == TOOL:
        if any(tool["name"] == ANSWER_TOOL["name"] for tool in tools):
            # Two tools of one name: the call that is to end the run could not be
            # told from a call for the server.
            raise ValueError(f"the server has a tool named {ANSWER_TOOL['name']!r} of its own")
        # After the tools of the server, so that the model is shown those exactly as
        # in a run without it.
        tools.append(ANSWER_TOOL)
    declared = [tool["name"] for tool in tools]
    system = system_prompt(channel)
    # The API is given the form to hold a text to in one of the ways only. In the
    # others no form goes into a request, whatever the model is set to send.
    held_to = ANSWER_SCHEMA if channel == FORMAT else None
    server = client.server_info
    trace.start(
        {
            "question": question,
            "server": server.name if server else None,
            # What the server says its tool texts are called. Asked over MCP, not
            # imported: the loop knows the server through the protocol only.
            "toolset_version": server.version if server else None,
            "tools": declared,
            "prompt_version": PROMPT_VERSION[channel],
            # How the answer was to be handed in (prompt.py).
            "answer_channel": channel,
            "model": model.settings,
            "limits": asdict(limits),
            "packages": {name: version(name) for name in _WRITE_FOR_THE_MODEL},
            # The names above say what the model reads. This says which code ran:
            # the commit, and whether a file of it had been changed (origin.py).
            "code": code_version(),
        },
        private={
            "system": system,
            "tool_definitions": tools,
            "answer_schema": ANSWER_SCHEMA,
        },
    )

    messages: list[dict[str, Any]] = [{"role": "user", "content": question}]
    started = clock()
    turn = 0

    def end(reason: EndReason, detail: str = "", answer: dict[str, Any] | None = None) -> Outcome:
        trace.end(reason.value, detail, answer, turns=turn, seconds=clock() - started)
        return Outcome(reason, detail, answer, turn)

    while True:
        if clock() - started > limits.run_seconds:
            return end(EndReason.TIME_LIMIT, f"over {limits.run_seconds:.0f} s after {turn} turns")
        asked_at = clock()
        try:
            reply = await model.reply(system, messages, tools, held_to)
        except ModelError as error:
            return end(EndReason.API_ERROR, str(error))
        turn += 1
        seconds = clock() - asked_at

        if reply.stop_reason != "tool_use":
            trace.turn(turn, reply, seconds, [])
            return end(*_final(reply, channel))
        if not reply.tool_calls:
            trace.turn(turn, reply, seconds, [])
            return end(EndReason.UNEXPECTED_STOP, "stop_reason 'tool_use' without a tool call")
        if channel == TOOL:
            # Looked at before the turn limit: the limit is there to stop tools from
            # being run for nobody, and an answer that is handed in needs none run.
            handed_in = _handed_in(reply.tool_calls)
            if handed_in is not None:
                call, answer = handed_in
                # The other calls of this response are not run. The model asked for
                # them and gave its answer in one breath, so it did not wait to read
                # what they return.
                trace.turn(
                    turn,
                    reply,
                    seconds,
                    [
                        ToolRecord(each, ANSWER if each is call else NOT_RUN)
                        for each in reply.tool_calls
                    ],
                )
                return end(EndReason.ANSWERED, "", answer)
        if turn == limits.max_turns:
            trace.turn(
                turn, reply, seconds, [ToolRecord(call, NOT_RUN) for call in reply.tool_calls]
            )
            return end(EndReason.TURN_LIMIT, f"turn {turn} still asked for tools")

        # One after the other, in the order asked: the tools share one paced
        # connection to arXiv, and a record in a fixed order is easier to read.
        records: list[ToolRecord] = []
        for call in reply.tool_calls:
            if channel == TOOL and call.name == ANSWER_TOOL["name"]:
                # Its arguments are no answer, or the run would have ended above. The
                # model is told so, and can hand in an answer again.
                records.append(
                    ToolRecord(call, NOT_SENT, INVALID_ANSWER_TEXT, 0.0, "invalid_answer")
                )
                continue
            try:
                records.append(await _call_tool(client, call, declared, limits.tool_seconds, clock))
            except _ToolFailure as failure:
                records.append(ToolRecord(call, FAILED))
                trace.turn(turn, reply, seconds, records)
                return end(failure.reason, failure.detail)
        trace.turn(turn, reply, seconds, records)

        # The assistant turn goes back exactly as it came (see Reply.content), and
        # every tool call gets its result, all in one message and in the same order.
        messages.append({"role": "assistant", "content": reply.content})
        messages.append({"role": "user", "content": [_tool_result(record) for record in records]})


def _handed_in(calls: tuple[ToolCall, ...]) -> tuple[ToolCall, dict[str, Any]] | None:
    """The first call of the loop's own tool whose arguments are an answer, with that answer."""
    for call in calls:
        if call.name == ANSWER_TOOL["name"]:
            answer = as_answer(call.arguments)
            if answer is not None:
                return call, answer
    return None


def _final(reply: Reply, channel: str) -> tuple[EndReason, str, dict[str, Any] | None]:
    """Reason, detail and answer for a response that did not ask for tools."""
    stop = reply.stop_reason
    if stop == "end_turn" and channel == TOOL:
        # Text is no answer in this way, whatever it says. One rule for every run, and
        # the records show how often a model ends a run like this.
        detail = f"the turn ended without a call of {ANSWER_TOOL['name']}"
        return EndReason.NO_ANSWER, detail, None
    if stop == "end_turn":
        answer = read_answer(reply.text)
        if answer is not None:
            return EndReason.ANSWERED, "", answer
        if not reply.text.strip():
            return EndReason.NO_ANSWER, "the response had no text", None
        return EndReason.NO_ANSWER, "the text was not an answer of the expected form", None
    if stop in _STOPS:
        details = reply.stop_details or {}
        told = " | ".join(
            str(details[key]) for key in ("category", "explanation") if details.get(key)
        )
        return _STOPS[stop], told, None
    return EndReason.UNEXPECTED_STOP, f"stop_reason {stop!r}", None


async def _call_tool(
    client: Client,
    call: ToolCall,
    declared: list[str],
    seconds: float,
    clock: Callable[[], float],
) -> ToolRecord:
    """Run one tool call and return what the model is to be given for it.

    An error result is a result: the model reads the server's sentence, unchanged,
    and chooses what to do next. Only a call that produces nothing at all, or
    something other than one piece of text, raises _ToolFailure.
    """
    if call.name not in declared:
        # Answered here. A name the model was never given is not passed on to the server.
        return ToolRecord(
            call, NOT_SENT, unknown_tool_text(call.name, declared), 0.0, "unknown_tool"
        )
    began = clock()
    try:
        result = await client.call_tool(call.name, call.arguments, read_timeout_seconds=seconds)
    except MCPError as error:
        timed_out = error.code == REQUEST_TIMEOUT
        reason = EndReason.TOOL_TIMEOUT if timed_out else EndReason.TOOL_TRANSPORT_ERROR
        raise _ToolFailure(reason, f"{call.name}: {error}") from error
    except Exception as error:
        # Whatever else a broken connection raises. Nothing can be told to the model
        # about a call whose answer never arrived, so the run ends.
        detail = f"{call.name}: {type(error).__name__}: {error}"
        raise _ToolFailure(EndReason.TOOL_TRANSPORT_ERROR, detail) from error
    took = clock() - began

    # The server returns one piece of text and nothing else. If something else
    # arrives, the loop does not choose a part of it: what the model read would no
    # longer be what the record says it read.
    blocks = result.content
    if len(blocks) != 1 or getattr(blocks[0], "type", None) != "text":
        kinds = [getattr(block, "type", type(block).__name__) for block in blocks]
        raise _ToolFailure(
            EndReason.TOOL_TRANSPORT_ERROR,
            f"{call.name}: the result was not one text block but {kinds}",
        )
    text = blocks[0].text
    if result.is_error:
        return ToolRecord(call, ERROR, text, took, error_kind(text))
    return ToolRecord(call, OK, text, took)


def _tool_result(record: ToolRecord) -> dict[str, Any]:
    block: dict[str, Any] = {
        "type": "tool_result",
        "tool_use_id": record.call.id,
        "content": record.text,
    }
    if record.is_error:
        block["is_error"] = True
    return block
