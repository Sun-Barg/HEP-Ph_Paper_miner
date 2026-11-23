"""Sending the end of a run again with the message of the loop: eval/replay.py.

No network and no LLM. A run that ended its turn without the call is made here by the
loop itself, as it was before it asked again (its one new decision is switched off), so
its two records are what such a run left behind. The requests of the command then go
to a model that replies from a script.
"""

import hashlib
import json
from functools import partial
from pathlib import Path

import anthropic
import anyio
import httpx2
import pytest
from conftest import sample_source
from mcp import Client
from test_model import Api, message, ok

from hepph_paper_miner.agent import loop
from hepph_paper_miner.agent.loop import EndReason, Limits
from hepph_paper_miner.agent.model import ClaudeModel, ModelError, Reply, ToolCall
from hepph_paper_miner.agent.prompt import ANSWER_TOOL, ASK_AGAIN_TEXT, TOOL, system_prompt
from hepph_paper_miner.agent.trace import Trace
from hepph_paper_miner.eval import replay
from hepph_paper_miner.eval.conditions import ASKING_AGAIN, REVISED
from hepph_paper_miner.eval.replay import (
    ASKED_ON,
    HANDED_IN,
    OTHER,
    TEXT_AGAIN,
    ReplayError,
    conversation,
    ended_without_the_call,
    model_of,
    outcome_of,
    read_record,
)
from hepph_paper_miner.eval.run import attempts_in, counted, read_attempt
from hepph_paper_miner.server import build_server

RUNS = Path(__file__).parent.parent / "results" / "runs"
CODE = {"commit": "c" * 40, "modified": False}
USAGE = {"input_tokens": 1000, "output_tokens": 100}
ANSWER = {
    "answer": "It is ten.",
    "found": True,
    "evidence": [{"arxiv_id": "2501.00001v2", "section_id": "2.1"}],
}
OUTLINE = ("get_outline", {"arxiv_id": "2501.00001v2"})
SECTION = ("read_section", {"arxiv_id": "2501.00001v2", "section_id": "2.1"})
SUBMIT = (ANSWER_TOOL["name"], ANSWER)


def calling(*calls: tuple[str, dict], thought: bool = False) -> Reply:
    """A response that asks for tools, whole as the API gives it and the private record keeps it."""
    blocks: list[dict] = []
    if thought:
        blocks.append({"type": "thinking", "thinking": "A summary.", "signature": "c2ln"})
    for number, (name, arguments) in enumerate(calls):
        # A kept block has more than a request may hold of it.
        call = {"type": "tool_use", "id": f"call-{name}-{number}", "name": name, "input": arguments}
        blocks.append({**call, "caller": {"type": "direct"}})
    wanted = tuple(ToolCall(b["id"], b["name"], b["input"]) for b in blocks if "id" in b)
    kinds = tuple(block["type"] for block in blocks)
    return Reply("tool_use", "", wanted, kinds, USAGE, blocks, raw={"content": blocks}, model="m")


def writing(text: str, stop: str = "end_turn") -> Reply:
    blocks = [{"type": "text", "text": text, "citations": None}] if text else []
    kinds = tuple(block["type"] for block in blocks)
    return Reply(stop, text, (), kinds, USAGE, blocks, raw={"content": blocks}, model="m")


class Scripted(ClaudeModel):
    """The real model as far as its settings go, with replies from a script."""

    def __init__(self, *replies, **settings) -> None:
        super().__init__("claude-sonnet-5-5", client=object(), **settings)
        self.replies, self.asked = list(replies), []

    async def reply(self, system, messages, tools, answer_schema) -> Reply:
        self.asked.append({"system": system, "messages": list(messages), "tools": tools})
        item = self.replies.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


async def a_run(folder: Path, name: str, *replies: Reply, limits: Limits | None = None):
    """One run of the loop with the staged tools, in the two files of its record."""
    model = Scripted(*replies, cache=True, show_thinking=True, answer_format=False)
    labels = {"question_id": name, "toolset": "staged", "repeat": 1}
    trace = Trace(
        f"20261120T000000Z_{name}_staged_0000", folder / "public", folder / "private", labels=labels
    )
    async with Client(build_server(sample_source(), "staged")) as client:
        outcome = await loop.run(
            "How much data?", client=client, model=model, trace=trace, channel=TOOL, limits=limits
        )
    return outcome, model, read_attempt(trace.public_path)


def made(folder: Path, name: str, *replies: Reply, limits: Limits | None = None):
    """a_run in an event loop of its own: the command under test starts one as well."""
    return anyio.run(partial(a_run, folder, name, *replies, limits=limits))


@pytest.fixture(autouse=True)
def a_commit(monkeypatch):
    """Code that a commit names, for the records of the runs and of the command."""
    monkeypatch.setattr(loop, "code_version", lambda: dict(CODE))
    monkeypatch.setattr(replay, "code_version", lambda: dict(CODE))


def made_before(monkeypatch, folder: Path, name: str, *replies: Reply, limits=None):
    """A run of the loop as it was with the prompt p2-tool: it asks no turn again."""
    with monkeypatch.context() as patch:
        patch.setattr(loop, "_why_not_asked", lambda *arguments: "")
        patch.setitem(loop.PROMPT_VERSION, TOOL, "p2-tool")
        return made(folder, name, *replies, limits=limits)


@pytest.fixture
def ended(monkeypatch, tmp_path):
    """A run that read a section and then wrote its answer as text, as three runs did."""
    replies = [calling(OUTLINE, thought=True), calling(SECTION), writing("It is ten.")]
    outcome, model, attempt = made_before(monkeypatch, tmp_path, "q-1", *replies)
    assert (outcome.reason, outcome.turns, outcome.asked_again) == (EndReason.NO_ANSWER, 3, None)
    assert outcome.detail == "the turn ended without a call of submit_answer"
    assert attempt.run["prompt_version"] == "p2-tool"
    return tmp_path, model, attempt


def private_of(folder: Path, attempt) -> Path:
    return folder / "private" / f"{attempt.run['run_id']}.jsonl"


def replayed(folder: Path, *replies, more: tuple[str, ...] = ()) -> tuple[int, Scripted | None]:
    """Start the command on the runs of the folder, with a model that replies from a script."""
    made: list[Scripted] = []

    def model_for(settings) -> Scripted:
        # The settings of the run, which the command has made sure can be made again.
        assert {k: v for k, v in settings.items() if k != "sdk"} == {
            **REVISED["model"],
            "thinking": {"type": "adaptive", "display": "summarized"},
        }
        made.append(Scripted(*replies, cache=True, show_thinking=True, answer_format=False))
        return made[-1]

    argv = ["--runs", str(folder / "public"), "--private", str(folder / "private")]
    argv += ["--out", str(folder / "out" / "replay.jsonl"), *more]
    return replay.main(argv, model_for=model_for), (made[0] if made else None)


# --- which runs --------------------------------------------------------------------------


def such_runs(folder: str) -> list[str]:
    runs = counted(attempts_in(RUNS / folder)).values()
    return sorted(str(a.cell) for a in runs if ended_without_the_call(a))


def test_the_runs_of_the_repository_that_ended_so_are_the_three_the_readmes_name():
    assert such_runs("regress/dev-after") == ["dev-02 flat 2", "dev-02 staged 3"]
    assert such_runs("eval") == ["eval-13 staged 3"]
    for folder in ("dev/diag-3-tool", "regress/dev02-before", "regress/dev02-after"):
        assert such_runs(folder) == []
    # Where the answer was a text, a turn without a call is how every run ended.
    assert such_runs("dev/diag-3-text") == []


def test_a_run_the_loop_would_not_ask_about_is_not_one_of_them(tmp_path, monkeypatch):
    # The last response the limit allows, a response that holds nothing, and a run that
    # handed in its answer.
    was = partial(made_before, monkeypatch, tmp_path)
    _, _, at_the_limit = was("q-1", calling(SECTION), writing("Ten."), limits=Limits(max_turns=2))
    _, _, nothing = was("q-2", calling(SECTION), writing(""))
    _, _, answered = was("q-3", calling(SECTION), calling(SUBMIT))
    _, _, written = was("q-4", calling(SECTION), writing("Ten."))
    found = [ended_without_the_call(a) for a in (at_the_limit, nothing, answered, written)]
    assert found == [False, False, False, True]
    # A run the loop of now asked, and that ended without the call again, was asked already.
    replies = [calling(SECTION), writing("Ten."), writing("Ten, as I said.")]
    outcome, _, asked = made(tmp_path, "q-5", *replies)
    assert (outcome.reason, outcome.asked_again) == (EndReason.NO_ANSWER, 2)
    assert not ended_without_the_call(asked)


# --- the request ---------------------------------------------------------------------------


def test_the_request_is_the_conversation_of_the_run_with_the_message_at_its_end(ended):
    folder, model, attempt = ended
    source = conversation(attempt, private_of(folder, attempt))

    # The system prompt and the tools that the run was sent, which the code still has.
    last = model.asked[-1]
    assert (source.system, source.tools) == (last["system"], last["tools"])
    assert source.system == system_prompt(TOOL) and source.tools[-1] == ANSWER_TOOL
    # Every message the loop had sent, then the reply as it came and the one message.
    roles = [message["role"] for message in source.messages]
    assert roles == ["user", "assistant", "user", "assistant", "user", "assistant", "user"]
    assert (
        source.messages[0] == last["messages"][0] == {"role": "user", "content": "How much data?"}
    )
    # The results are the very blocks the loop made of them,
    assert source.messages[2] == last["messages"][2]
    assert source.messages[4] == last["messages"][4]
    assert source.messages[4]["content"][0]["content"].startswith("section | 2501.00001v2 | 2.1 | ")
    # and a turn of the model is what a request may hold of it: a thought with its
    # signature, a call without what the API added to it, a text without its citations.
    assert source.messages[1]["content"] == [
        {"type": "thinking", "thinking": "A summary.", "signature": "c2ln"},
        {
            "type": "tool_use",
            "id": "call-get_outline-0",
            "name": "get_outline",
            "input": OUTLINE[1],
        },
    ]
    assert source.messages[5] == {
        "role": "assistant",
        "content": [{"type": "text", "text": "It is ten."}],
    }
    assert source.messages[6] == {"role": "user", "content": ASK_AGAIN_TEXT}


def test_a_result_of_a_tool_error_goes_back_as_the_error_it_was(monkeypatch, tmp_path):
    wrong = ("read_section", {"arxiv_id": "2501.00001v2", "section": "2.1"})
    replies = [calling(wrong), writing("I cannot say.")]
    _, model, attempt = made_before(monkeypatch, tmp_path, "q-1", *replies)
    source = conversation(attempt, private_of(tmp_path, attempt))
    (result,) = source.messages[2]["content"]
    assert result["is_error"] is True and "has no argument 'section'" in result["content"]
    assert source.messages[2] == model.asked[-1]["messages"][2]


def test_a_record_that_is_not_the_twin_of_the_public_one_is_refused(ended, monkeypatch):
    folder, _, attempt = ended
    private = private_of(folder, attempt)
    with pytest.raises(ReplayError, match="its private record cannot be read"):
        conversation(attempt, folder / "private" / "another.jsonl")

    whole = private.read_text("utf-8")
    lines = whole.splitlines()
    private.write_text("\n".join(lines[:-2] + lines[-1:]) + "\n", "utf-8")
    with pytest.raises(ReplayError, match="the two records differ in their turns"):
        conversation(attempt, private)
    # A result that is not the text whose hash the public record keeps.
    private.write_text(whole.replace("Title: Data", "Title: Dates"), "utf-8")
    with pytest.raises(ReplayError, match="result of read_section in turn 2 is not the text"):
        conversation(attempt, private)
    private.write_text(whole.replace(attempt.run["run_id"], "another-run"), "utf-8")
    with pytest.raises(ReplayError, match="is not the private record of"):
        conversation(attempt, private)
    # A response that is not kept with the blocks the public record lists for it: one
    # block less, or no blocks at all (a record made without the whole response).
    first, second, *rest = lines
    turn = json.loads(second)
    for content in (turn["reply"]["content"][1:], None):
        changed = {**turn, "reply": {"content": content} if content else {"text": ""}}
        private.write_text("\n".join([first, json.dumps(changed), *rest]) + "\n", "utf-8")
        with pytest.raises(ReplayError, match="turn 1 is not kept as the loop sent it"):
            conversation(attempt, private)
    private.write_text(whole, "utf-8")
    assert conversation(attempt, private).messages[-1]["content"] == ASK_AGAIN_TEXT


def test_a_run_whose_texts_the_code_no_longer_has_is_refused(ended, monkeypatch):
    # The command sends what the loop would send now. A run made with other tool texts,
    # or another prompt in front of the conversation, is no such request.
    import hepph_paper_miner.server as server

    folder, _, attempt = ended
    private = private_of(folder, attempt)
    monkeypatch.setattr(server, "TOOLSET_VERSION", {"staged": "staged-7", "flat": "flat-5"})
    with pytest.raises(ReplayError, match="are not the ones the code has now"):
        conversation(attempt, private)
    monkeypatch.undo()
    whole = private.read_text("utf-8")
    private.write_text(whole.replace("You answer questions", "You answer all questions"), "utf-8")
    with pytest.raises(ReplayError, match="are not the ones the code has now"):
        conversation(attempt, private)


def test_on_the_wire_the_request_is_the_one_the_loop_sends_after_it_asked(monkeypatch, tmp_path):
    # Through the SDK, down to the body of a request, with the API stood in for. A run
    # of the loop as it is: its second turn ends with text, the loop asks, and its third
    # request is what it sent then. The loop as it was is given the same responses and
    # ends with the text; from the two records of that run the command builds its
    # request. The two bodies are the same, whole.
    thought = {"type": "thinking", "thinking": "A summary.", "signature": "c2ln"}
    read = {"type": "tool_use", "id": "toolu_01", "name": "read_section", "input": SECTION[1]}
    hand_in = {"type": "tool_use", "id": "toolu_02", "name": "submit_answer", "input": ANSWER}
    responses = [
        message([thought, read], "tool_use"),
        message([{"type": "text", "text": "It is ten."}], "end_turn"),
        message([hand_in], "tool_use"),
    ]

    async def run_with(api: Api, name: str):
        model = api.model(cache=True, show_thinking=True, answer_format=False)
        labels = {"question_id": "q-1", "toolset": "staged", "repeat": 1}
        trace = Trace(name, tmp_path / "public", tmp_path / "private", labels=labels)
        async with Client(build_server(sample_source(), "staged")) as client:
            outcome = await loop.run(
                "How much data?", client=client, model=model, trace=trace, channel=TOOL
            )
        return outcome, trace

    now = Api(*map(ok, responses))
    outcome, _ = anyio.run(run_with, now, "now")
    assert (outcome.reason, outcome.turns, outcome.asked_again) == (EndReason.ANSWERED, 3, 2)
    assert now.requests[2]["messages"][-1] == {"role": "user", "content": ASK_AGAIN_TEXT}

    was = Api(*map(ok, responses[:2]))
    with monkeypatch.context() as patch:
        patch.setattr(loop, "_why_not_asked", lambda *arguments: "")
        outcome, trace = anyio.run(run_with, was, "was")
    assert (outcome.reason, outcome.turns) == (EndReason.NO_ANSWER, 2)
    assert was.requests == now.requests[:2]

    attempt = read_attempt(trace.public_path)
    source = conversation(attempt, trace.private_path)
    again = Api(ok(responses[2]))
    client = anthropic.AsyncAnthropic(
        api_key="not-a-real-key",
        http_client=httpx2.AsyncClient(transport=httpx2.MockTransport(again)),
    )
    model = model_of(attempt.run["model"], client=client)
    reply = anyio.run(model.reply, source.system, source.messages, source.tools, None)
    assert outcome_of(reply) == (HANDED_IN, ANSWER)
    assert again.requests == [now.requests[2]]


# --- the settings ----------------------------------------------------------------------------


def test_the_model_is_made_again_with_the_settings_of_the_run():
    for display in ({}, {"display": "summarized"}):
        settings = {**ASKING_AGAIN["model"], "sdk": "anthropic 2.8.0"}
        settings["thinking"] = {**settings["thinking"], **display}
        made = model_of(settings, client=object()).settings
        assert {k: v for k, v in made.items() if k != "sdk"} == {
            k: v for k, v in settings.items() if k != "sdk"
        }
    # Settings the model of this code cannot be given are not made up.
    with pytest.raises(ReplayError, match="cannot be made again"):
        model_of({**ASKING_AGAIN["model"], "thinking": {"type": "enabled"}}, client=object())
    with pytest.raises(ReplayError, match="does not name its max_tokens"):
        model_of({"model": "scripted"}, client=object())


# --- reading a response ----------------------------------------------------------------------


def test_a_response_is_read_as_the_loop_reads_it():
    assert outcome_of(calling(SUBMIT)) == (HANDED_IN, ANSWER)
    # With other calls beside it, the call that hands in is what counts, as in the loop.
    assert outcome_of(calling(SECTION, SUBMIT)) == (HANDED_IN, ANSWER)
    assert outcome_of(calling(SECTION)) == (ASKED_ON, None)
    # Arguments that are no answer: the loop would say so and go on.
    no_answer = (ANSWER_TOOL["name"], {"answer": "It is ten."})
    assert outcome_of(calling(no_answer)) == (ASKED_ON, None)
    assert outcome_of(writing("It is ten, as I wrote.")) == (TEXT_AGAIN, None)
    assert outcome_of(writing("")) == (TEXT_AGAIN, None)
    assert outcome_of(writing("It is", stop="max_tokens")) == (OTHER, None)
    assert outcome_of(writing("", stop="refusal")) == (OTHER, None)


# --- the command -----------------------------------------------------------------------------


def test_every_request_is_the_same_and_each_response_is_counted(ended, capsys):
    folder, _, attempt = ended
    replies = [
        calling(SUBMIT),
        calling(SECTION),
        writing("It is ten."),
        writing("It is", stop="max_tokens"),
        ModelError("APIConnectionError", "Connection error.", None),
        calling(SUBMIT, thought=True),
    ]
    code, model = replayed(folder, *replies, more=("--repeats", "6"))
    assert code == 0

    source = conversation(attempt, private_of(folder, attempt))
    assert len(model.asked) == 6
    for asked in model.asked:
        assert asked == {
            "system": source.system,
            "messages": source.messages,
            "tools": source.tools,
        }
    shown = capsys.readouterr().out
    assert f"message   p3-tool | {ASK_AGAIN_TEXT}" in shown
    assert "6 request(s): 1 asked on, 2 handed in, 2 other, 1 text again" in shown

    out = folder / "out" / "replay.jsonl"
    head, requests, end = read_record(out)
    assert (head["prompt_version"], head["repeats"], head["code"]) == ("p3-tool", 6, CODE)
    assert head["message_sha256"] == hashlib.sha256(ASK_AGAIN_TEXT.encode()).hexdigest()
    (named,) = head["runs"]
    assert named["run_id"] == attempt.run["run_id"] and named["prompt_version"] == "p2-tool"
    assert (named["turns"], named["thinking_blocks"]) == (3, 1)
    assert named["toolset_version"] == "staged-6" and named["model"] == attempt.run["model"]
    outcomes = [request["outcome"] for request in requests]
    assert outcomes == [HANDED_IN, ASKED_ON, TEXT_AGAIN, OTHER, OTHER, HANDED_IN]
    assert [request["repeat"] for request in requests] == [1, 2, 3, 4, 5, 6]
    assert [request.get("answer") for request in requests] == [
        ANSWER,
        None,
        None,
        None,
        None,
        ANSWER,
    ]
    assert requests[1]["calls"] == ["read_section"] and requests[0]["calls"] == ["submit_answer"]
    assert requests[4]["stop_reason"] is None and "Connection error." in requests[4]["error"]
    assert end["requests"] == 6
    assert end["outcomes"] == {ASKED_ON: 1, HANDED_IN: 2, OTHER: 2, TEXT_AGAIN: 1}
    assert end["by_run"] == {attempt.run["run_id"]: end["outcomes"]}
    # Five responses came, each of 1000 tokens in and 100 out, at the prices of the report.
    assert end["cost"] == round(5 * (1000 * 2.00 + 100 * 10.00) / 1_000_000, 4)

    # The public record holds no text the model wrote but an answer that was handed in.
    # The private one, beside the private records of the runs, keeps the responses whole.
    public = out.read_text("utf-8")
    assert "It is ten, as" not in public and '"reply"' not in public
    kept = [
        json.loads(line)
        for line in (folder / "private" / "replay.jsonl").read_text("utf-8").splitlines()
    ]
    assert kept[3]["reply"] == {
        "content": [{"type": "text", "text": "It is ten.", "citations": None}]
    }
    assert "reply" not in kept[5]  # no response came
    assert [line["record"] for line in kept] == ["replay", *["request"] * 6, "end"]


def test_each_such_run_of_the_folder_is_sent_and_only_names_some(monkeypatch, tmp_path, capsys):
    was = partial(made_before, monkeypatch, tmp_path)
    _, _, first = was("q-1", calling(SECTION), writing("Ten."))
    _, _, second = was("q-2", calling(OUTLINE), writing("Ten, I think."))
    was("q-3", calling(SECTION), calling(SUBMIT))
    code, _ = replayed(tmp_path, calling(SUBMIT), writing("Ten."), more=("--repeats", "2"))
    assert code == 0
    _, requests, end = read_record(tmp_path / "out" / "replay.jsonl")
    ids = [first.run["run_id"], second.run["run_id"]]
    assert [(r["run_id"], r["repeat"]) for r in requests] == [(i, n) for i in ids for n in (1, 2)]
    assert end["by_run"] == {i: {HANDED_IN: 1, TEXT_AGAIN: 1} for i in ids}

    (tmp_path / "out" / "replay.jsonl").unlink()
    (tmp_path / "private" / "replay.jsonl").unlink()
    only = ("--only", second.run["run_id"], "--repeats", "1")
    assert replayed(tmp_path, calling(SUBMIT), more=only)[0] == 0
    head, requests, _ = read_record(tmp_path / "out" / "replay.jsonl")
    assert [run["run_id"] for run in head["runs"]] == [second.run["run_id"]] and len(requests) == 1
    capsys.readouterr()
    assert replayed(tmp_path, more=("--only", "no-such-run"))[0] == 2
    assert "no run that ended without the call is named no-such-run" in capsys.readouterr().err


def test_the_plan_says_what_would_be_sent_and_sends_nothing(ended, capsys):
    folder, _, attempt = ended
    code, model = replayed(folder, more=("--plan",))
    assert code == 0 and model is None and not (folder / "out").exists()
    shown = capsys.readouterr().out
    assert f"{attempt.run['run_id']} | 3 turn(s) | " in shown
    assert "1 run(s), 10 request(s) each: nothing was sent" in shown


def test_what_cannot_be_sent_as_the_loop_would_send_it_is_refused(ended, capsys, monkeypatch):
    folder, _, attempt = ended
    # A record that is there is not written over.
    assert replayed(folder, calling(SUBMIT), more=("--repeats", "1"))[0] == 0
    capsys.readouterr()
    assert replayed(folder, calling(SUBMIT), more=("--repeats", "1"))[0] == 2
    assert "the record cannot be made" in capsys.readouterr().err
    # Code that no commit names sends nothing: the record could not say what made it.
    monkeypatch.setattr(replay, "code_version", lambda: {"commit": "c" * 40, "modified": True})
    assert replayed(folder, calling(SUBMIT))[0] == 2
    assert "files the repository keeps have been changed" in capsys.readouterr().err
    assert replayed(folder, more=("--repeats", "0"))[0] == 2
    # Without the private record of the run there is no conversation to send.
    private_of(folder, attempt).unlink()
    assert replayed(folder, calling(SUBMIT))[0] == 2
    assert "its private record cannot be read" in capsys.readouterr().err


def test_a_folder_without_such_a_run_is_refused(tmp_path, capsys):
    argv = ["--runs", str(RUNS / "dev" / "diag-3-tool"), "--out", str(tmp_path / "replay.jsonl")]
    assert replay.main(argv) == 2
    assert "holds no run that ended without the call" in capsys.readouterr().err
    assert not (tmp_path / "replay.jsonl").exists()


def test_the_runs_of_dev_02_cannot_be_sent_from_here_for_want_of_their_private_records(
    tmp_path, capsys
):
    # Their public records are kept, and the command finds the two. The conversations
    # are in the private records on the maintainer's computer.
    argv = ["--runs", str(RUNS / "regress" / "dev-after"), "--private", str(tmp_path)]
    assert replay.main([*argv, "--out", str(tmp_path / "replay.jsonl"), "--plan"]) == 2
    assert "_dev-02_flat_b80f: its private record cannot be read" in capsys.readouterr().err


def test_what_is_not_a_record_of_the_command_is_not_read_as_one(tmp_path):
    path = tmp_path / "run.jsonl"
    path.write_text(json.dumps({"record": "run"}) + "\n", "utf-8")
    with pytest.raises(ReplayError, match="is not a record of this command"):
        read_record(path)
