"""scripts/show_thinking.py: the model's thinking beside its tool calls, and no paper text."""

import dataclasses
import importlib.util
from pathlib import Path

import pytest
from conftest import asks, says

from hepph_paper_miner.agent.trace import OK, ToolRecord, Trace

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
