"""scripts/show_thinking.py: the model's thinking beside its tool calls, and no paper text."""

import dataclasses
import importlib.util
from pathlib import Path

import pytest
from conftest import asks, says

from hepph_paper_miner.agent.trace import ANSWER, OK, ToolRecord, Trace

SCRIPT = Path(__file__).parent.parent / "scripts" / "show_thinking.py"
spec = importlib.util.spec_from_file_location("show_thinking", SCRIPT)
show_thinking = importlib.util.module_from_spec(spec)
spec.loader.exec_module(show_thinking)

THOUGHT = "The outline has a data section; reading it."
TEXT = "section | 2501.00001v2 | 2.1 | 10 chars | complete\nTitle: Data\n\nData text."


@pytest.fixture
def run(tmp_path):
    """One finished run in two files: a turn with a thought and a tool call, then an answer."""
    trace = Trace("run-1", tmp_path / "public", tmp_path / "private")
    trace.start(
        {
            "question_id": "q1",
            "toolset_version": "staged-5",
            "model": {"thinking": {"type": "adaptive", "display": "summarized"}},
            "code": {"commit": "0123456789abcdef0123456789abcdef01234567", "modified": True},
            "repeat": 2,
        },
        private={},
    )
    raw = {"content": [{"type": "thinking", "thinking": THOUGHT, "signature": "c2ln"}]}
    first = dataclasses.replace(asks(("read_section", {"section_id": "2.1"})), raw=raw)
    trace.turn(1, first, 0.5, [ToolRecord(first.tool_calls[0], OK, TEXT, 0.1)])
    answer = {"answer": "Ten.", "found": True, "evidence": []}
    trace.turn(2, says("{}"), 0.5, [])
    trace.end("answered", "", answer, turns=2, seconds=1.0)
    return trace


def test_the_thought_stands_with_the_call_it_led_to_and_no_tool_text_is_printed(run, capsys):
    assert (
        show_thinking.main([str(run.public_path), "--private", str(run.private_path.parent)]) == 0
    )
    shown = capsys.readouterr().out
    assert "== run-1 | q1 | staged-5 | repeat 2 | code 0123456+changes | thinking shown" in shown
    assert f"   thought: {THOUGHT}" in shown
    assert '   asks: read_section {"section_id": "2.1"} -> ok, 74 chars' in shown
    assert '"section_id": "2.1", "start": 0, "stop": 10' in shown  # the facts of the first line
    assert "end: answered | 2 turns | 74 chars in 1 results | found True" in shown
    assert "   answer: Ten." in shown
    assert "Data text." not in shown  # what the tool returned


def test_a_last_text_that_was_not_read_as_the_answer_is_printed(tmp_path, capsys):
    # A run made without the answer form ends with plain text, and the record has no
    # answer. The text is the model's own, so it is shown, like a thought.
    trace = Trace("run-2", tmp_path / "public", tmp_path / "private")
    trace.start({"question_id": "q1", "toolset_version": "flat-4", "model": {}}, private={})
    raw = {"content": [{"type": "text", "text": "The paper gives no such number."}]}
    trace.turn(1, dataclasses.replace(says("The paper gives no such number."), raw=raw), 0.5, [])
    trace.end("no_answer", "the text was not an answer of the expected form", None, 1, 1.0)

    assert (
        show_thinking.main([str(trace.public_path), "--private", str(trace.private_path.parent)])
        == 0
    )
    shown = capsys.readouterr().out
    assert "   text: The paper gives no such number." in shown
    assert "end: no_answer | 1 turns" in shown


def test_the_text_that_was_read_as_the_answer_is_printed_once(tmp_path, capsys):
    # The answer of a run stands with its end. Its text is not printed a second time.
    answer = {"answer": "Ten.", "found": True, "evidence": []}
    trace = Trace("run-3", tmp_path / "public", tmp_path / "private")
    trace.start({"question_id": "q1", "toolset_version": "flat-4", "model": {}}, private={})
    raw = {"content": [{"type": "text", "text": '{"answer": "Ten."}'}]}
    trace.turn(1, dataclasses.replace(says('{"answer": "Ten."}'), raw=raw), 0.5, [])
    trace.end("answered", "", answer, 1, 1.0)

    assert (
        show_thinking.main([str(trace.public_path), "--private", str(trace.private_path.parent)])
        == 0
    )
    shown = capsys.readouterr().out
    assert "   answer: Ten." in shown and "   text:" not in shown


def test_text_beside_a_call_that_handed_in_the_answer_is_printed(tmp_path, capsys):
    # Where the answer comes as a call of the answer tool, no text is the answer. What
    # the model wrote in that response is its own wording, and is shown like any other.
    answer = {"answer": "Ten.", "found": True, "evidence": []}
    trace = Trace("run-4", tmp_path / "public", tmp_path / "private")
    start = {
        "question_id": "q1",
        "toolset_version": "flat-4",
        "model": {},
        "answer_channel": "tool",
    }
    trace.start(start, private={})
    raw = {"content": [{"type": "text", "text": "That settles it."}]}
    last = dataclasses.replace(asks(("submit_answer", answer)), raw=raw)
    trace.turn(1, last, 0.5, [ToolRecord(last.tool_calls[0], ANSWER)])
    trace.end("answered", "", answer, 1, 1.0)

    assert (
        show_thinking.main([str(trace.public_path), "--private", str(trace.private_path.parent)])
        == 0
    )
    shown = capsys.readouterr().out
    assert "| thinking not asked for | answer by tool" in shown
    assert "   text: That settles it." in shown
    assert "   asks: submit_answer " in shown and "-> answer" in shown
    assert "end: answered | 1 turns | 0 chars in 0 results | found True" in shown
    assert "   answer: Ten." in shown


def test_a_turn_the_loop_asked_about_shows_its_text_and_that_it_was_asked(tmp_path, capsys):
    # The text that ended the turn was no answer in this way. The loop asked for the
    # call, and the answer that was handed in then stands with the end, as ever.
    answer = {"answer": "Ten.", "found": True, "evidence": []}
    trace = Trace("run-5", tmp_path / "public", tmp_path / "private")
    start = {"question_id": "q1", "toolset_version": "staged-6", "answer_channel": "tool"}
    trace.start({**start, "model": {}}, private={})
    raw = {"content": [{"type": "text", "text": "It is ten."}]}
    written = dataclasses.replace(says("It is ten."), raw=raw)
    trace.turn(1, written, 0.5, [], asked_again="Call the tool.")
    last = asks(("submit_answer", answer))
    trace.turn(2, last, 0.5, [ToolRecord(last.tool_calls[0], ANSWER)])
    trace.end("answered", "", answer, 2, 1.0, asked_again=1)

    assert (
        show_thinking.main([str(trace.public_path), "--private", str(trace.private_path.parent)])
        == 0
    )
    shown = capsys.readouterr().out.splitlines()
    asked = shown.index("   then: the loop asked again for the call of the answer tool")
    assert shown[asked - 1] == "   text: It is ten." and shown[asked + 1].startswith("turn 2 | ")
    assert shown.count("   then: the loop asked again for the call of the answer tool") == 1
    assert "   answer: Ten." in shown
    # The message itself is a text of the loop, named by the prompt, and is not printed.
    assert not any("Call the tool." in line for line in shown)


def test_a_pattern_is_opened_here_and_the_output_can_go_to_a_file(run, tmp_path, capsys):
    out = tmp_path / "thinking.txt"
    pattern = str(run.public_path.parent / "run-*.jsonl")
    private = ["--private", str(run.private_path.parent)]
    assert show_thinking.main([pattern, *private, "--out", str(out)]) == 0
    assert THOUGHT in out.read_text(encoding="utf-8")
    assert "1 run(s) written to" in capsys.readouterr().out


def test_without_the_private_record_the_run_is_still_listed_and_says_what_is_missing(
    run, tmp_path, capsys
):
    assert show_thinking.main([str(run.public_path), "--private", str(tmp_path / "none")]) == 0
    shown = capsys.readouterr().out
    assert "no private record of this name" in shown
    assert "asks: read_section" in shown and THOUGHT not in shown


def test_a_pattern_that_matches_nothing_is_an_error(tmp_path, capsys):
    assert show_thinking.main([str(tmp_path / "*.jsonl")]) == 2
    assert "no record matches" in capsys.readouterr().err
