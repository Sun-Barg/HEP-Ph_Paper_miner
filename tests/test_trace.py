"""The files of a run: their names, where they go, and that no run writes into another's."""

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from conftest import asks, says

from hepph_paper_miner.agent.model import ToolCall
from hepph_paper_miner.agent.trace import (
    FAILED,
    NOT_RUN,
    NOT_SENT,
    OK,
    RUNS_ENV,
    ToolRecord,
    Trace,
    default_private_dir,
    new_run_id,
)

CALL = ToolCall("call-1", "read_section", {"arxiv_id": "2501.00001v2", "section_id": "2.1"})
TEXT = "section | 2501.00001v2 | 2.1 | 10 chars | complete\nTitle: Data\n\nData text."


def test_a_run_id_sorts_by_time_and_says_what_was_run():
    moment = datetime(2026, 11, 13, 4, 12, 5, tzinfo=UTC)
    first, second = (new_run_id("dev-01", "staged", moment) for _ in range(2))
    assert first.startswith("20261113T041205Z_dev-01_staged_")
    assert len(first.rsplit("_", 1)[1]) == 4
    assert first != second  # two runs in one second still get two names


def test_private_records_go_outside_the_repository_unless_told_otherwise(monkeypatch, tmp_path):
    monkeypatch.delenv(RUNS_ENV, raising=False)
    assert default_private_dir() == Path.home() / "hepph-paper-miner-runs"
    repository = Path(__file__).parent.parent
    assert repository not in default_private_dir().parents
    monkeypatch.setenv(RUNS_ENV, str(tmp_path))
    assert default_private_dir() == tmp_path


def test_no_run_writes_into_the_file_of_another(tmp_path):
    Trace("run-1", tmp_path / "public", tmp_path / "private")
    with pytest.raises(FileExistsError):
        Trace("run-1", tmp_path / "public", tmp_path / "private")


def test_without_a_private_folder_only_the_public_file_is_written(tmp_path):
    trace = Trace("run-1", tmp_path, None)
    trace.start({"question": "Q?"}, private={"system": "S"})
    trace.turn(1, says("{}"), 0.5, [])
    trace.end("no_answer", "", None, turns=1, seconds=0.5)
    assert trace.private_path is None
    assert [path.name for path in tmp_path.iterdir()] == ["run-1.jsonl"]
    assert "system" not in trace.public_path.read_text(encoding="utf-8")


def test_the_public_facts_of_a_tool_call_leave_its_text_out():
    facts = ToolRecord(CALL, OK, TEXT, 1.23456).public()
    assert "Data text." not in json.dumps(facts)
    assert facts["result_chars"] == len(TEXT) and facts["seconds"] == 1.235
    assert facts["first_line"]["section_id"] == "2.1"
    # A call that got no text has no size and no hash to show.
    for status in (NOT_RUN, FAILED):
        assert "result_chars" not in ToolRecord(CALL, status).public()
    # An error text has a size, but no first line of a known form to read.
    told = ToolRecord(CALL, NOT_SENT, "Unknown tool: 'x'.", 0.0, "unknown_tool")
    assert told.is_error and told.public()["first_line"] is None


def test_totals_count_every_text_the_model_was_given(tmp_path):
    trace = Trace("run-1", tmp_path, None)
    trace.start({}, private={})
    both = asks(("read_section", {}), ("read_section", {}))
    records = [
        ToolRecord(both.tool_calls[0], OK, TEXT, 0.1),
        ToolRecord(both.tool_calls[1], NOT_RUN),
    ]
    trace.turn(1, both, 0.2, records)
    trace.end("turn_limit", "", None, turns=1, seconds=0.3)
    end = json.loads(trace.public_path.read_text(encoding="utf-8").splitlines()[-1])
    assert (end["tool_calls"], end["tool_result_chars"]) == (1, len(TEXT))
    assert (end["input_tokens"], end["output_tokens"]) == (100, 10)
