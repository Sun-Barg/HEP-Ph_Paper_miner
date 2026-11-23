"""The loop, with a model that replies from a script: no network, no API, no cost.

The tools are the real ones, reached through the SDK's in-memory client, with papers
held in memory behind them. For results a real server never sends, a stand-in client
takes its place.
"""

import dataclasses
import hashlib
import json
import threading
import time
from importlib.metadata import version
from types import SimpleNamespace

import pytest
from conftest import ScriptedModel, asks, sample_source, says
from mcp import Client, MCPError
from mcp.types import CONNECTION_CLOSED, REQUEST_TIMEOUT

from hepph_paper_miner.agent.loop import EndReason, Limits, run
from hepph_paper_miner.agent.model import ModelError, Reply
from hepph_paper_miner.agent.origin import code_version
from hepph_paper_miner.agent.prompt import (
    ANSWER_SCHEMA,
    ANSWER_TOOL,
    ASK_AGAIN_TEXT,
    FORMAT,
    INVALID_ANSWER_TEXT,
    SYSTEM_PROMPT,
    TEXT,
    TOOL,
    system_prompt,
    unknown_tool_text,
)
from hepph_paper_miner.agent.trace import Trace
from hepph_paper_miner.server import build_server
from hepph_paper_miner.sources.base import Paper, PaperMeta, Section
from hepph_paper_miner.sources.fixture import FixtureSource

ANSWER = {
    "answer": "The data section says so.",
    "found": True,
    "evidence": [{"arxiv_id": "2501.00001v2", "section_id": "2.1"}],
}
OUTLINE = ("get_outline", {"arxiv_id": "2501.00001v2"})
SECTION = ("read_section", {"arxiv_id": "2501.00001v2", "section_id": "2.1"})


class StandInClient:
    """A client whose one tool returns, or raises, whatever a test gives it."""

    server_info = SimpleNamespace(name="stand-in", version="stand-in-1")

    def __init__(self, result=None, error: Exception | None = None) -> None:
        self._result, self._error = result, error
        self.calls: list[tuple] = []

    async def list_tools(self):
        tool = SimpleNamespace(name="echo", description="Echo.", input_schema={"type": "object"})
        return SimpleNamespace(tools=[tool])

    async def call_tool(self, name, arguments, read_timeout_seconds=None):
        self.calls.append((name, arguments, read_timeout_seconds))
        if self._error is not None:
            raise self._error
        return self._result


def result_of(*blocks, is_error: bool = False):
    return SimpleNamespace(content=list(blocks), is_error=is_error)


def text_block(text: str):
    return SimpleNamespace(type="text", text=text)


@pytest.fixture
def source() -> FixtureSource:
    return sample_source()


@pytest.fixture
async def client(source):
    async with Client(build_server(source)) as connected:
        yield connected


@pytest.fixture
def trace(tmp_path) -> Trace:
    return Trace("run-1", tmp_path / "public", tmp_path / "private", labels={"question_id": "q1"})


def records(path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


# --- the way a run is meant to go ------------------------------------------------------


@pytest.mark.anyio
async def test_a_question_is_answered_through_search_outline_and_section(client, trace):
    reading = asks(SECTION)
    model = ScriptedModel(
        asks(("search_papers", {"query": "sample"})),
        asks(OUTLINE),
        reading,
        says(json.dumps(ANSWER)),
    )

    outcome = await run(
        "What does the data say?", client=client, model=model, trace=trace, channel=FORMAT
    )

    assert (outcome.reason, outcome.answer, outcome.turns) == (EndReason.ANSWERED, ANSWER, 4)
    assert len(model.asked) == 4

    # What the model is given at the start: the loop's own prompt and answer form, and
    # the server's tools exactly as the server describes them.
    first = model.asked[0]
    assert first["system"] == SYSTEM_PROMPT and first["schema"] == ANSWER_SCHEMA
    assert first["messages"] == [{"role": "user", "content": "What does the data say?"}]
    listed = (await client.list_tools()).tools
    assert first["tools"] == [
        {"name": tool.name, "description": tool.description, "input_schema": tool.input_schema}
        for tool in listed
    ]

    # What it is given after a tool call: its own turn, untouched, and the tool's text.
    last = model.asked[3]["messages"]
    assert [message["role"] for message in last] == ["user"] + ["assistant", "user"] * 3
    assert last[-2]["content"] is reading.content
    assert last[-1]["content"] == [
        {
            "type": "tool_result",
            "tool_use_id": "call-read_section-0",
            "content": "section | 2501.00001v2 | 2.1 | 10 chars | complete\nTitle: Data\n\nData text.",
        }
    ]


@pytest.mark.anyio
async def test_the_record_says_what_was_run_and_what_each_result_was(client, trace):
    model = ScriptedModel(
        asks(("search_papers", {"query": "sample"})),
        asks(OUTLINE),
        asks(SECTION),
        says(json.dumps(ANSWER)),
    )
    await run("What does the data say?", client=client, model=model, trace=trace, channel=FORMAT)

    start, *turns, end = records(trace.public_path)
    assert start["record"] == "run" and start["run_id"] == "run-1" and start["question_id"] == "q1"
    assert start["toolset_version"] == "staged-6"  # as the server reported it over MCP
    assert start["tools"] == ["search_papers", "get_outline", "read_section"]
    # The name of the loop's own texts, and the way the answer was to be handed in.
    assert (start["prompt_version"], start["answer_channel"]) == ("p1", "format")
    assert start["model"] == {"model": "scripted"}
    assert start["limits"] == {"max_turns": 12, "tool_seconds": 700.0, "run_seconds": 900.0}
    # The SDK and pydantic write a part of what the model reads (the sentence for
    # arguments that break a schema, say), so the record names the versions in use.
    assert start["packages"] == {"mcp": version("mcp"), "pydantic": version("pydantic")}
    # And which code ran: the commit, and whether a kept file differed from it. The
    # names above say what the model read, not what the loop was (test_origin.py).
    assert start["code"] == code_version()
    assert set(start["code"]) == {"commit", "modified"}

    assert [turn["turn"] for turn in turns] == [1, 2, 3, 4]
    assert turns[0]["blocks"] == ["thinking", "tool_use"] and turns[0]["stop_reason"] == "tool_use"
    search, outline, section = (turn["tools"][0] for turn in turns[:3])
    assert search["name"] == "search_papers" and search["arguments"] == {"query": "sample"}
    assert search["status"] == "ok" and search["error_kind"] is None
    assert search["first_line"]["ids"] == ["2501.00001v2"]
    assert search["first_line"]["as_of"] == "2026-01-01"  # the day the source gave this answer
    assert outline["first_line"]["sections"] == 8
    assert section["first_line"] == {
        "shape": "section",
        "arxiv_id": "2501.00001v2",
        "section_id": "2.1",
        "start": 0,
        "stop": 10,
        "chars": 10,
        "extent": "complete",
    }
    given = "section | 2501.00001v2 | 2.1 | 10 chars | complete\nTitle: Data\n\nData text."
    assert section["result_chars"] == len(given)
    assert section["result_sha256"] == hashlib.sha256(given.encode("utf-8")).hexdigest()
    assert turns[3]["tools"] == []

    assert end["record"] == "end" and end["reason"] == "answered" and end["answer"] == ANSWER
    assert end["turns"] == 4 and end["tool_calls"] == 3
    assert end["tool_result_chars"] == sum(turn["tools"][0]["result_chars"] for turn in turns[:3])
    assert end["input_tokens"] == 400 and end["output_tokens"] == 40
    assert end["parser_versions"] == ["4"]  # as the outline's first line named it


@pytest.mark.anyio
async def test_the_public_record_holds_no_text_that_a_tool_returned(tmp_path):
    # A title, an abstract and a section text that occur nowhere else.
    meta = PaperMeta("2504.00004v1", "ZEBRA-TITLE", ("Jo Kappa",), 2025, "hep-ph", "ZEBRA-ABSTRACT")
    paper = Paper(meta, (Section("1", "ZEBRA-HEADING", 1, "ZEBRA-BODY of the paper."),), "3")
    trace = Trace("run-2", tmp_path / "public", tmp_path / "private")
    # The model's own turn can repeat what it read (in its thinking, say), so the raw
    # response is private as well.
    thinking = {"content": [{"type": "thinking", "thinking": "ZEBRA-THOUGHT"}]}
    searching = asks(("search_papers", {"query": "zebra-title"}))
    model = ScriptedModel(
        dataclasses.replace(searching, raw=thinking),
        asks(("get_outline", {"arxiv_id": "2504.00004v1"})),
        asks(("read_section", {"arxiv_id": "2504.00004v1", "section_id": "1"})),
        asks(("read_section", {"arxiv_id": "2504.00004v1", "section_id": "9"})),  # an error text
        says(json.dumps(ANSWER)),
    )
    async with Client(build_server(FixtureSource([paper]))) as client:
        outcome = await run("Q?", client=client, model=model, trace=trace, channel=FORMAT)
    assert outcome.reason is EndReason.ANSWERED

    public = trace.public_path.read_text(encoding="utf-8")
    private = trace.private_path.read_text(encoding="utf-8")
    for planted in (
        "ZEBRA-TITLE",
        "ZEBRA-ABSTRACT",
        "ZEBRA-HEADING",
        "ZEBRA-BODY",
        "ZEBRA-THOUGHT",
    ):
        assert planted not in public
        assert planted in private
    # The private file has the rest too: what the model was told at the start.
    assert records(trace.private_path)[0]["system"] == SYSTEM_PROMPT


# --- tool calls that do not go well ----------------------------------------------------


@pytest.mark.anyio
async def test_an_error_result_goes_to_the_model_as_it_is_and_the_run_goes_on(client, trace):
    wrong = ("read_section", {"arxiv_id": "2501.00001v2", "section_id": "9"})
    model = ScriptedModel(asks(wrong), asks(SECTION), says(json.dumps(ANSWER)))

    outcome = await run("Q?", client=client, model=model, trace=trace, channel=FORMAT)

    assert outcome.reason is EndReason.ANSWERED
    told = model.asked[1]["messages"][-1]["content"][0]
    assert told["is_error"] is True
    assert told["content"].startswith("Error executing tool read_section: [no_such_section] ")
    assert "Its sections are: 1, 2, 2.1" in told["content"]  # the server's sentence, whole
    failed = records(trace.public_path)[1]["tools"][0]
    assert (failed["status"], failed["error_kind"], failed["first_line"]) == (
        "error",
        "no_such_section",
        None,
    )
    assert records(trace.public_path)[-1]["tool_calls"] == 2  # an error text was read, too


@pytest.mark.anyio
async def test_arguments_that_break_the_schema_are_told_apart_from_failures_of_the_tool(
    client, source, trace
):
    broken = ("read_section", {"arxiv_id": "2501.00001v2", "section_id": "1", "start": -1})
    model = ScriptedModel(asks(broken), says(json.dumps(ANSWER)))

    await run("Q?", client=client, model=model, trace=trace, channel=FORMAT)

    assert records(trace.public_path)[1]["tools"][0]["error_kind"] == "invalid_arguments"
    assert source.calls == []


@pytest.mark.anyio
async def test_a_tool_the_server_never_offered_is_answered_without_asking_the_server(
    client, source, trace
):
    model = ScriptedModel(
        asks(("read_paper", {"arxiv_id": "2501.00001v2"})), says(json.dumps(ANSWER))
    )

    outcome = await run("Q?", client=client, model=model, trace=trace, channel=FORMAT)

    assert outcome.reason is EndReason.ANSWERED
    assert source.calls == []
    told = model.asked[1]["messages"][-1]["content"][0]
    names = ["search_papers", "get_outline", "read_section"]
    assert told == {
        "type": "tool_result",
        "tool_use_id": "call-read_paper-0",
        "content": unknown_tool_text("read_paper", names),
        "is_error": True,
    }
    assert told["content"] == (
        "Unknown tool: 'read_paper'. The tools are: search_papers, get_outline, read_section."
    )
    kept = records(trace.public_path)[1]["tools"][0]
    assert (kept["status"], kept["error_kind"]) == ("not_sent", "unknown_tool")


@pytest.mark.anyio
async def test_several_calls_in_one_response_run_in_order_and_go_back_in_one_message(
    client, source, trace
):
    both = asks(OUTLINE, ("get_outline", {"arxiv_id": "2502.00002v1"}), SECTION)
    model = ScriptedModel(both, says(json.dumps(ANSWER)))

    await run("Q?", client=client, model=model, trace=trace, channel=FORMAT)

    assert [what for what in source.calls if what[0] == "paper"] == [
        ("paper", "2501.00001v2"),
        ("paper", "2502.00002v1"),
        ("paper", "2501.00001v2"),
    ]
    results = model.asked[1]["messages"][-1]["content"]
    assert [result["tool_use_id"] for result in results] == [call.id for call in both.tool_calls]
    assert [result["content"].split(" | ")[0] for result in results] == [
        "outline",
        "outline",
        "section",
    ]
    assert len(records(trace.public_path)[1]["tools"]) == 3


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("error", "reason"),
    [
        (MCPError(REQUEST_TIMEOUT, "Timed out while waiting for response"), EndReason.TOOL_TIMEOUT),
        (MCPError(CONNECTION_CLOSED, "Connection closed"), EndReason.TOOL_TRANSPORT_ERROR),
        (ConnectionError("pipe broke"), EndReason.TOOL_TRANSPORT_ERROR),
    ],
)
async def test_a_tool_call_without_any_result_ends_the_run(trace, error, reason):
    stand_in = StandInClient(error=error)
    model = ScriptedModel(asks(("echo", {})), says(json.dumps(ANSWER)))

    outcome = await run(
        "Q?",
        client=stand_in,
        model=model,
        trace=trace,
        limits=Limits(tool_seconds=55.0),
        channel=FORMAT,
    )

    assert outcome.reason is reason and "echo" in outcome.detail
    assert len(model.asked) == 1  # there was nothing to tell the model
    assert stand_in.calls == [("echo", {}, 55.0)]  # the limit travels with the call
    _, turn, end = records(trace.public_path)
    assert turn["tools"][0]["status"] == "failed" and "result_chars" not in turn["tools"][0]
    assert end["reason"] == reason.value


@pytest.mark.anyio
async def test_a_tool_of_the_real_server_that_hangs_is_ended_by_the_time_limit(trace):
    # Nothing here raises the timeout by hand: the real client waits for the real
    # server, whose tool waits for a source that does not answer.
    release = threading.Event()

    class Hanging(FixtureSource):
        def listing(self, arxiv_id):
            release.wait(30)
            return super().listing(arxiv_id)

    model = ScriptedModel(asks(OUTLINE), says(json.dumps(ANSWER)))
    began = time.monotonic()
    try:
        async with Client(build_server(Hanging([]))) as connected:
            outcome = await run(
                "Q?",
                client=connected,
                model=model,
                trace=trace,
                limits=Limits(tool_seconds=0.2),
                channel=FORMAT,
            )
        waited = time.monotonic() - began
    finally:
        release.set()  # the thread of the tool was let go, not stopped: let it end

    assert outcome.reason is EndReason.TOOL_TIMEOUT and "get_outline" in outcome.detail
    assert waited < 10  # and not the 30 s that the source would have taken
    assert len(model.asked) == 1
    _, turn, end = records(trace.public_path)
    assert turn["tools"][0]["status"] == "failed"
    assert end["reason"] == "tool_timeout"


@pytest.mark.anyio
@pytest.mark.parametrize(
    "blocks",
    [
        [],
        [text_block("one"), text_block("two")],
        [SimpleNamespace(type="image", data="...")],
    ],
)
async def test_a_result_that_is_not_one_piece_of_text_ends_the_run(trace, blocks):
    model = ScriptedModel(asks(("echo", {})), says(json.dumps(ANSWER)))

    outcome = await run(
        "Q?", client=StandInClient(result_of(*blocks)), model=model, trace=trace, channel=FORMAT
    )

    assert outcome.reason is EndReason.TOOL_TRANSPORT_ERROR
    assert "not one text block" in outcome.detail
    assert len(model.asked) == 1


@pytest.mark.anyio
async def test_an_error_text_of_no_known_form_is_still_passed_on(trace):
    odd = result_of(text_block("it broke"), is_error=True)
    model = ScriptedModel(asks(("echo", {})), says(json.dumps(ANSWER)))

    outcome = await run("Q?", client=StandInClient(odd), model=model, trace=trace, channel=FORMAT)

    assert outcome.reason is EndReason.ANSWERED
    assert model.asked[1]["messages"][-1]["content"][0]["content"] == "it broke"
    assert records(trace.public_path)[1]["tools"][0]["error_kind"] == "unrecognised"


# --- limits -----------------------------------------------------------------------------


@pytest.mark.anyio
async def test_the_last_allowed_response_does_not_get_its_tools_run(client, source, trace):
    model = ScriptedModel(asks(OUTLINE), asks(SECTION, OUTLINE), says(json.dumps(ANSWER)))

    outcome = await run(
        "Q?", client=client, model=model, trace=trace, limits=Limits(max_turns=2), channel=FORMAT
    )

    assert (outcome.reason, outcome.turns, outcome.answer) == (EndReason.TURN_LIMIT, 2, None)
    assert len(model.asked) == 2
    # Only the first response had its tool run: one outline, which asks the source twice.
    assert source.calls == [("listing", "2501.00001v2"), ("paper", "2501.00001v2")]
    _, _, second, end = records(trace.public_path)
    assert [tool["status"] for tool in second["tools"]] == ["not_run", "not_run"]
    assert "result_chars" not in second["tools"][0]
    assert end["tool_calls"] == 1


@pytest.mark.anyio
async def test_a_single_turn_is_enough_for_a_model_that_answers_at_once(client, trace):
    model = ScriptedModel(says(json.dumps(ANSWER)))
    outcome = await run(
        "Q?", client=client, model=model, trace=trace, limits=Limits(max_turns=1), channel=FORMAT
    )
    assert (outcome.reason, outcome.turns) == (EndReason.ANSWERED, 1)


def test_a_run_needs_at_least_one_turn():
    with pytest.raises(ValueError, match="at least 1"):
        Limits(max_turns=0)


@pytest.mark.anyio
async def test_the_time_limit_is_looked_at_between_turns_only(client, source, trace):
    now = [0.0]

    def a_minute_passes() -> None:
        now[0] += 60.0

    model = ScriptedModel(
        asks(OUTLINE), asks(SECTION), says(json.dumps(ANSWER)), on_reply=a_minute_passes
    )

    outcome = await run(
        "Q?",
        client=client,
        model=model,
        trace=trace,
        limits=Limits(run_seconds=100.0),
        clock=lambda: now[0],
        channel=FORMAT,
    )

    # The second response arrives at 120 s. Its tool still runs: the limit is only
    # looked at before the model is asked again, and then the run ends.
    assert (outcome.reason, outcome.turns) == (EndReason.TIME_LIMIT, 2)
    assert len(model.asked) == 2
    assert source.calls[-1] == ("paper", "2501.00001v2") and len(source.calls) == 3
    end = records(trace.public_path)[-1]
    assert end["reason"] == "time_limit" and end["seconds"] == 120.0


# --- responses that are not an answer --------------------------------------------------


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("text", "detail"),
    [
        ("", "the response had no text"),
        ("   \n", "the response had no text"),
        ("The answer is 42.", "the text was not an answer of the expected form"),
        (
            json.dumps({"answer": "42", "found": True}),
            "the text was not an answer of the expected form",
        ),
        (json.dumps({**ANSWER, "answer": "  "}), "the text was not an answer of the expected form"),
        (json.dumps({**ANSWER, "found": "yes"}), "the text was not an answer of the expected form"),
        (
            json.dumps({**ANSWER, "evidence": [{"arxiv_id": "x"}]}),
            "the text was not an answer of the expected form",
        ),
        (
            json.dumps({**ANSWER, "reasoning": "..."}),
            "the text was not an answer of the expected form",
        ),
        (json.dumps([ANSWER]), "the text was not an answer of the expected form"),
    ],
)
async def test_an_end_of_turn_without_a_usable_answer_is_no_answer(client, trace, text, detail):
    outcome = await run(
        "Q?", client=client, model=ScriptedModel(says(text)), trace=trace, channel=FORMAT
    )
    assert (outcome.reason, outcome.detail, outcome.answer) == (EndReason.NO_ANSWER, detail, None)
    assert records(trace.public_path)[-1]["answer"] is None


@pytest.mark.anyio
async def test_an_answer_may_say_that_the_papers_do_not_hold_it(client, trace):
    nothing = {"answer": "The paper reports no such value.", "found": False, "evidence": []}
    outcome = await run(
        "Q?",
        client=client,
        model=ScriptedModel(says(json.dumps(nothing))),
        trace=trace,
        channel=FORMAT,
    )
    assert (outcome.reason, outcome.answer) == (EndReason.ANSWERED, nothing)


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("stop", "reason"),
    [
        ("max_tokens", EndReason.MAX_TOKENS),
        ("refusal", EndReason.REFUSAL),
        ("model_context_window_exceeded", EndReason.CONTEXT_FULL),
        ("pause_turn", EndReason.UNEXPECTED_STOP),
        ("stop_sequence", EndReason.UNEXPECTED_STOP),
        ("a_reason_from_the_future", EndReason.UNEXPECTED_STOP),
        (None, EndReason.UNEXPECTED_STOP),
    ],
)
async def test_every_other_stop_reason_ends_the_run_under_its_own_name(client, trace, stop, reason):
    # The text is a perfectly good answer. A response that was cut off or refused is
    # still not one: only a turn the model ended itself counts.
    model = ScriptedModel(says(json.dumps(ANSWER), stop=stop))
    outcome = await run("Q?", client=client, model=model, trace=trace, channel=FORMAT)
    assert (outcome.reason, outcome.answer) == (reason, None)
    assert records(trace.public_path)[-1]["reason"] == reason.value


@pytest.mark.anyio
async def test_a_refusal_keeps_what_the_api_said_about_it(client, trace):
    details = {"type": "refusal", "category": "cyber", "explanation": "Declined."}
    model = ScriptedModel(says("", stop="refusal", stop_details=details))
    outcome = await run("Q?", client=client, model=model, trace=trace, channel=FORMAT)
    assert (outcome.reason, outcome.detail) == (EndReason.REFUSAL, "cyber | Declined.")
    assert records(trace.public_path)[1]["stop_details"] == details


@pytest.mark.anyio
async def test_a_tool_use_stop_without_a_tool_call_is_unexpected(client, trace):
    hollow = Reply("tool_use", "", (), ("thinking",), {}, content=object())
    outcome = await run(
        "Q?", client=client, model=ScriptedModel(hollow), trace=trace, channel=FORMAT
    )
    assert outcome.reason is EndReason.UNEXPECTED_STOP


@pytest.mark.anyio
async def test_a_failure_of_the_api_ends_the_run_and_is_named(client, trace):
    model = ScriptedModel(asks(OUTLINE), ModelError("RateLimitError", "429 slow down", 429))

    outcome = await run("Q?", client=client, model=model, trace=trace, channel=FORMAT)

    assert (outcome.reason, outcome.turns) == (EndReason.API_ERROR, 1)
    assert outcome.detail == "RateLimitError: 429 slow down"
    assert [line["record"] for line in records(trace.public_path)] == ["run", "turn", "end"]


@pytest.mark.anyio
async def test_a_run_that_dies_leaves_what_it_had_done_and_no_end_line(client, trace):
    model = ScriptedModel(asks(OUTLINE), RuntimeError("a bug, not an expected failure"))

    with pytest.raises(RuntimeError):
        await run("Q?", client=client, model=model, trace=trace, channel=FORMAT)

    # No "end" line: that is how an unfinished run is told from a finished one.
    assert [line["record"] for line in records(trace.public_path)] == ["run", "turn"]


# --- the ways to hand in an answer: a tool of the loop, and text asked for as JSON ---------

SUBMIT = (ANSWER_TOOL["name"], ANSWER)


@pytest.mark.anyio
async def test_a_call_of_the_answer_tool_is_the_answer_and_ends_the_run(client, source, trace):
    model = ScriptedModel(asks(SECTION), asks(SUBMIT))

    outcome = await run("Q?", client=client, model=model, trace=trace, channel=TOOL)

    assert (outcome.reason, outcome.answer, outcome.turns) == (EndReason.ANSWERED, ANSWER, 2)
    assert len(model.asked) == 2  # nothing was asked after the answer
    # What the model is given in this way: the prompt with its one more line, the tools
    # of the server as the server describes them with the loop's own after them, and no
    # form for the API to hold a text to.
    first = model.asked[0]
    assert first["system"] == system_prompt(TOOL) and first["schema"] is None
    listed = (await client.list_tools()).tools
    assert first["tools"] == [
        *(
            {"name": tool.name, "description": tool.description, "input_schema": tool.input_schema}
            for tool in listed
        ),
        ANSWER_TOOL,
    ]

    start, _, second, end = records(trace.public_path)
    assert (start["prompt_version"], start["answer_channel"]) == ("p3-tool", "tool")
    assert start["tools"] == ["search_papers", "get_outline", "read_section", "submit_answer"]
    (handed_in,) = second["tools"]
    assert (handed_in["name"], handed_in["status"]) == ("submit_answer", "answer")
    assert handed_in["arguments"] == ANSWER and "result_chars" not in handed_in
    assert (end["reason"], end["answer"]) == ("answered", ANSWER)
    # The loop had nothing to ask for, and the record says so.
    assert outcome.asked_again is None and end["asked_again"] is None
    assert "asked_again" not in second
    # The model read one result, the section. Nothing was returned for the answer.
    assert end["tool_calls"] == 1 and end["tool_result_chars"] == 74
    private = records(trace.private_path)[0]
    assert private["system"] == system_prompt(TOOL)
    assert private["tool_definitions"][-1] == ANSWER_TOOL


@pytest.mark.anyio
async def test_calls_that_come_with_the_answer_are_not_run(client, source, trace):
    model = ScriptedModel(asks(OUTLINE, SUBMIT, SECTION))

    outcome = await run("Q?", client=client, model=model, trace=trace, channel=TOOL)

    assert (outcome.reason, outcome.answer, outcome.turns) == (EndReason.ANSWERED, ANSWER, 1)
    assert source.calls == []  # neither the call before the answer nor the one after it
    _, turn, end = records(trace.public_path)
    assert [tool["status"] for tool in turn["tools"]] == ["not_run", "answer", "not_run"]
    assert end["tool_calls"] == 0


@pytest.mark.anyio
async def test_arguments_that_are_no_answer_are_sent_back_and_the_run_goes_on(
    client, source, trace
):
    incomplete = (ANSWER_TOOL["name"], {"answer": "The data section says so.", "found": True})
    model = ScriptedModel(asks(incomplete, SECTION), asks(SUBMIT))

    outcome = await run("Q?", client=client, model=model, trace=trace, channel=TOOL)

    assert (outcome.reason, outcome.answer, outcome.turns) == (EndReason.ANSWERED, ANSWER, 2)
    told, read = model.asked[1]["messages"][-1]["content"]
    assert told == {
        "type": "tool_result",
        "tool_use_id": "call-submit_answer-0",
        "content": INVALID_ANSWER_TEXT,
        "is_error": True,
    }
    # The call beside it was a call like any other, and was run.
    assert read["content"].startswith("section | 2501.00001v2 | 2.1 | ")
    refused, _ = records(trace.public_path)[1]["tools"]
    assert (refused["status"], refused["error_kind"]) == ("not_sent", "invalid_answer")
    # The model read the sentence, so it counts like every other text it was given.
    assert refused["result_chars"] == len(INVALID_ANSWER_TEXT)
    assert records(trace.public_path)[-1]["tool_calls"] == 2
    assert INVALID_ANSWER_TEXT == (
        "The answer was not accepted. Its arguments have to be: answer (text, not empty), "
        "found (true or false) and evidence (a list, each item with arxiv_id and section_id "
        "as text), and nothing else. Call submit_answer again."
    )


@pytest.mark.anyio
async def test_of_several_answers_in_one_response_the_first_that_is_one_counts(client, trace):
    empty = (ANSWER_TOOL["name"], {**ANSWER, "answer": ""})
    later = (ANSWER_TOOL["name"], {**ANSWER, "answer": "Something else."})

    outcome = await run(
        "Q?",
        client=client,
        model=ScriptedModel(asks(empty, SUBMIT, later)),
        trace=trace,
        channel=TOOL,
    )

    assert (outcome.reason, outcome.answer) == (EndReason.ANSWERED, ANSWER)
    statuses = [tool["status"] for tool in records(trace.public_path)[1]["tools"]]
    assert statuses == ["not_run", "answer", "not_run"]


# --- a turn that ends without the call is asked for it, once --------------------------------

WITHOUT = "the turn ended without a call of submit_answer"


@pytest.mark.anyio
@pytest.mark.parametrize("text", ["It is ten.", json.dumps(ANSWER)])
async def test_a_turn_that_ends_without_the_call_is_asked_for_it(client, source, trace, text):
    # Text is no answer where the answer is to come through the tool, also not text that
    # has the very form of an answer: the way is part of what is run. The loop asks for
    # the call, and what is handed in then is the answer of the run.
    written = says(text)
    model = ScriptedModel(asks(SECTION), written, asks(SUBMIT))

    outcome = await run("Q?", client=client, model=model, trace=trace, channel=TOOL)

    assert (outcome.reason, outcome.answer, outcome.turns) == (EndReason.ANSWERED, ANSWER, 3)
    assert outcome.asked_again == 2
    # The third request is the second with two messages more: the reply as it came, and
    # the message of the loop. The system prompt and the tools are what they were.
    second, third = model.asked[1], model.asked[2]
    assert third["messages"][:-2] == second["messages"]
    assert third["messages"][-2:] == [
        {"role": "assistant", "content": written.content},
        {"role": "user", "content": ASK_AGAIN_TEXT},
    ]
    assert (third["system"], third["tools"]) == (second["system"], second["tools"])
    assert third["schema"] is None

    _, _, asked, last, end = records(trace.public_path)
    assert asked["asked_again"] is True and asked["tools"] == []
    assert "asked_again" not in last
    assert (end["reason"], end["answer"]) == ("answered", ANSWER)
    assert (end["asked_again"], end["turns"]) == (2, 3)
    # The message is no result of a tool: the model read one result, the section.
    assert end["tool_calls"] == 1 and end["tool_result_chars"] == 74
    # The private record holds the message, as it holds everything the model was given.
    kept = records(trace.private_path)
    assert kept[2]["asked_with"] == ASK_AGAIN_TEXT and "asked_with" not in kept[3]
    assert "asked_with" not in asked


@pytest.mark.anyio
async def test_asked_for_the_call_a_run_may_read_on_before_it_hands_in(client, source, trace):
    model = ScriptedModel(says("It is ten."), asks(SECTION), asks(SUBMIT))

    outcome = await run("Q?", client=client, model=model, trace=trace, channel=TOOL)

    # The message asks for the call and forbids nothing: the tools are run as ever.
    assert (outcome.reason, outcome.turns, outcome.asked_again) == (EndReason.ANSWERED, 3, 1)
    assert [what[0] for what in source.calls] == ["paper"]
    read = model.asked[2]["messages"][-1]["content"][0]["content"]
    assert read.startswith("section | 2501.00001v2 | 2.1 | ")


@pytest.mark.anyio
async def test_a_second_turn_without_the_call_ends_the_run_without_an_answer(client, trace):
    model = ScriptedModel(says("It is ten."), says("As I said: ten."), asks(SUBMIT))

    outcome = await run("Q?", client=client, model=model, trace=trace, channel=TOOL)

    assert (outcome.reason, outcome.answer, outcome.turns) == (EndReason.NO_ANSWER, None, 2)
    assert outcome.detail == WITHOUT + ", also after the loop had asked for it"
    assert len(model.asked) == 2  # asked for the call once, and not a second time
    _, first, second, end = records(trace.public_path)
    assert first["asked_again"] is True and "asked_again" not in second
    assert (end["reason"], end["asked_again"], outcome.asked_again) == ("no_answer", 1, 1)


@pytest.mark.anyio
async def test_the_last_response_the_limit_allows_is_not_asked_about(client, trace):
    model = ScriptedModel(asks(SECTION), says("It is ten."), asks(SUBMIT))

    outcome = await run(
        "Q?", client=client, model=model, trace=trace, limits=Limits(max_turns=2), channel=TOOL
    )

    # The limit is on the responses of the model, and asking would take one more.
    assert (outcome.reason, outcome.turns, outcome.asked_again) == (EndReason.NO_ANSWER, 2, None)
    assert outcome.detail == WITHOUT + ", with the last response the limit allows"
    assert len(model.asked) == 2
    assert "asked_again" not in records(trace.public_path)[2]


@pytest.mark.anyio
async def test_an_answer_that_was_asked_for_may_come_with_the_last_response(client, trace):
    model = ScriptedModel(says("It is ten."), asks(SUBMIT))

    outcome = await run(
        "Q?", client=client, model=model, trace=trace, limits=Limits(max_turns=2), channel=TOOL
    )

    assert (outcome.reason, outcome.turns, outcome.asked_again) == (EndReason.ANSWERED, 2, 1)


@pytest.mark.anyio
async def test_a_response_that_holds_nothing_is_not_asked_about(client, trace):
    # There is no reply to send back, and the API takes no empty turn.
    model = ScriptedModel(says(""), asks(SUBMIT))

    outcome = await run("Q?", client=client, model=model, trace=trace, channel=TOOL)

    assert (outcome.reason, outcome.turns, outcome.asked_again) == (EndReason.NO_ANSWER, 1, None)
    assert outcome.detail == WITHOUT + ", and the response held nothing"
    assert len(model.asked) == 1


@pytest.mark.anyio
async def test_a_response_that_was_cut_off_is_not_asked_about(client, trace):
    # Only a turn that the model ended: a response the API ended has its own reason.
    model = ScriptedModel(says("It is", stop="max_tokens"), asks(SUBMIT))

    outcome = await run("Q?", client=client, model=model, trace=trace, channel=TOOL)

    assert (outcome.reason, outcome.asked_again) == (EndReason.MAX_TOKENS, None)
    assert len(model.asked) == 1


@pytest.mark.anyio
@pytest.mark.parametrize("channel", [FORMAT, TEXT])
async def test_where_the_answer_is_a_text_no_turn_is_asked_about(client, trace, channel):
    # In the two other ways the text that ends a turn is what is read for the answer.
    model = ScriptedModel(says("It is ten."), says(json.dumps(ANSWER)))

    outcome = await run("Q?", client=client, model=model, trace=trace, channel=channel)

    assert (outcome.reason, outcome.turns, outcome.asked_again) == (EndReason.NO_ANSWER, 1, None)
    assert outcome.detail == "the text was not an answer of the expected form"
    assert len(model.asked) == 1
    assert records(trace.public_path)[-1]["asked_again"] is None


@pytest.mark.anyio
async def test_an_answer_in_the_last_allowed_response_is_an_answer(client, source, trace):
    model = ScriptedModel(asks(SECTION), asks(OUTLINE, SUBMIT))

    outcome = await run(
        "Q?", client=client, model=model, trace=trace, limits=Limits(max_turns=2), channel=TOOL
    )

    # The limit keeps tools from being run for nobody. An answer needs none run.
    assert (outcome.reason, outcome.turns, outcome.answer) == (EndReason.ANSWERED, 2, ANSWER)
    assert [what[0] for what in source.calls] == ["paper"]  # the section of the first response


@pytest.mark.anyio
async def test_the_turn_limit_ends_a_run_whose_last_response_hands_in_no_answer(client, trace):
    no_answer = (ANSWER_TOOL["name"], {"answer": "The data section says so."})
    model = ScriptedModel(asks(SECTION), asks(no_answer), asks(SUBMIT))

    outcome = await run(
        "Q?", client=client, model=model, trace=trace, limits=Limits(max_turns=2), channel=TOOL
    )

    assert (outcome.reason, outcome.turns, outcome.answer) == (EndReason.TURN_LIMIT, 2, None)
    assert len(model.asked) == 2  # it was not told what was wrong: nobody was to read that
    last = records(trace.public_path)[2]["tools"][0]
    assert last["status"] == "not_run" and "result_chars" not in last


@pytest.mark.anyio
async def test_the_tools_named_to_the_model_include_the_loops_own(client, trace):
    model = ScriptedModel(asks(("read_paper", {"arxiv_id": "2501.00001v2"})), asks(SUBMIT))

    await run("Q?", client=client, model=model, trace=trace, channel=TOOL)

    assert model.asked[1]["messages"][-1]["content"][0]["content"] == (
        "Unknown tool: 'read_paper'. "
        "The tools are: search_papers, get_outline, read_section, submit_answer."
    )


@pytest.mark.anyio
@pytest.mark.parametrize("channel", [FORMAT, TEXT])
async def test_where_the_model_was_not_given_the_tool_a_call_of_it_is_no_answer(
    client, trace, channel
):
    model = ScriptedModel(asks(SUBMIT), says(json.dumps(ANSWER)))

    outcome = await run("Q?", client=client, model=model, trace=trace, channel=channel)

    # The call is one of an unknown tool. The run goes on, and ends with the text.
    assert (outcome.reason, outcome.turns) == (EndReason.ANSWERED, 2)
    start, first, _, _ = records(trace.public_path)
    assert "submit_answer" not in start["tools"]
    assert (first["tools"][0]["status"], first["tools"][0]["error_kind"]) == (
        "not_sent",
        "unknown_tool",
    )


@pytest.mark.anyio
async def test_asked_for_as_text_the_answer_is_the_text_that_ends_the_turn(client, trace):
    model = ScriptedModel(asks(SECTION), says(json.dumps(ANSWER)))

    outcome = await run("Q?", client=client, model=model, trace=trace, channel=TEXT)

    assert (outcome.reason, outcome.answer, outcome.turns) == (EndReason.ANSWERED, ANSWER, 2)
    # The prompt asks for the form here, so nothing else does: no form for the API to
    # hold the text to, and no tool beside those of the server.
    first = model.asked[0]
    assert first["system"] == system_prompt(TEXT) and first["schema"] is None
    assert [tool["name"] for tool in first["tools"]] == [
        "search_papers",
        "get_outline",
        "read_section",
    ]
    start = records(trace.public_path)[0]
    assert (start["prompt_version"], start["answer_channel"]) == ("p2-text", "text")
    assert records(trace.private_path)[0]["system"] == system_prompt(TEXT)


@pytest.mark.anyio
@pytest.mark.parametrize(
    "text",
    [
        "Here is the answer:\n" + json.dumps(ANSWER),
        "```json\n" + json.dumps(ANSWER) + "\n```",
        json.dumps(ANSWER) + "\n\nI did not read the appendix.",
        "The data section says so.",
    ],
)
async def test_text_that_is_not_the_object_alone_is_no_answer(client, trace, text):
    # Nothing holds the model to the form in this way, and nothing is read into what it
    # wrote instead. How often that costs an answer is what the records are to show.
    outcome = await run(
        "Q?", client=client, model=ScriptedModel(says(text)), trace=trace, channel=TEXT
    )
    assert (outcome.reason, outcome.answer) == (EndReason.NO_ANSWER, None)
    assert outcome.detail == "the text was not an answer of the expected form"


@pytest.mark.anyio
async def test_a_server_with_a_tool_of_the_same_name_is_not_given_the_loops_own(trace):
    class Clashing(StandInClient):
        async def list_tools(self):
            tool = SimpleNamespace(
                name=ANSWER_TOOL["name"], description="Another.", input_schema={"type": "object"}
            )
            return SimpleNamespace(tools=[tool])

    with pytest.raises(ValueError, match="a tool named 'submit_answer' of its own"):
        await run("Q?", client=Clashing(), model=ScriptedModel(), trace=trace, channel=TOOL)
    # Nothing was written: the run never began.
    assert trace.public_path.read_text(encoding="utf-8") == ""


@pytest.mark.anyio
async def test_a_way_to_hand_in_an_answer_that_does_not_exist_is_refused(client, trace):
    with pytest.raises(ValueError, match="no such way to hand in an answer: 'letter'"):
        await run("Q?", client=client, model=ScriptedModel(), trace=trace, channel="letter")


@pytest.mark.anyio
async def test_a_run_has_to_be_told_how_its_answer_is_handed_in(client, trace):
    # There is no way that a run uses when nobody names one: the way decides what the
    # model reads, so a run in a way that nobody chose would be a run of another experiment.
    with pytest.raises(TypeError, match="channel"):
        await run("Q?", client=client, model=ScriptedModel(), trace=trace)
    assert trace.public_path.read_text(encoding="utf-8") == ""
