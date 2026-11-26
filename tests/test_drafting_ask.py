"""How the generator and the filters ask the model and keep its replies (drafting/ask.py)."""

import asyncio
import json

import pytest
from drafting_paper import Scripted, reply_of

from hepph_paper_miner.agent.model import ModelError
from hepph_paper_miner.drafting import ask
from hepph_paper_miner.drafting.ask import AskError, Job, Runner, Stop


def jobs(count: int) -> list[Job]:
    return [Job(str(n), "system", f"message {n}", {"type": "object"}) for n in range(1, count + 1)]


def run(runner: Runner, lines=()) -> None:
    asyncio.run(runner.run(list(lines)))


def lines_of(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def test_several_requests_at_a_time_ask_every_job_once(tmp_path):
    out = tmp_path / "record.jsonl"
    seen = []

    class Slow(Scripted):
        async def ask(self, system, message, schema):
            seen.append(message)
            await asyncio.sleep(0)  # let another worker take its turn
            return reply_of({"answer": message})

    runner = Runner(Slow(None), jobs(9), out, lambda job, reply: {"outcome": "ok"}, parallel=4)
    run(runner)
    assert sorted(seen) == sorted(f"message {n}" for n in range(1, 10))
    assert sorted(line["id"] for line in lines_of(out)) == sorted(str(n) for n in range(1, 10))
    assert runner.to_ask(lines_of(out)) == []


def test_a_reply_line_holds_what_every_reply_has(tmp_path):
    out = tmp_path / "record.jsonl"
    runner = Runner(
        Scripted(lambda *_: reply_of({"answer": "x"})),
        jobs(1),
        out,
        lambda job, reply: {"outcome": "fine"},
    )
    run(runner)
    (line,) = lines_of(out)
    assert line["record"] == "reply" and line["id"] == "1" and line["outcome"] == "fine"
    assert line["stop_reason"] == "end_turn" and line["blocks"] == ["thinking", "text"]
    assert line["usage"] == {"input_tokens": 1000, "output_tokens": 200}
    assert line["model"] == "claude-sonnet-5-5" and isinstance(line["seconds"], float)


def test_it_stops_after_three_requests_in_a_row_that_the_api_failed(tmp_path):
    out = tmp_path / "record.jsonl"
    failing = Scripted(lambda *_: ModelError("APIConnectionError", "lost", None))
    runner = Runner(failing, jobs(5), out, lambda job, reply: {})
    with pytest.raises(Stop, match="failed 3 requests in a row"):
        run(runner)
    assert [line["record"] for line in lines_of(out)] == ["failed"] * 3


@pytest.mark.parametrize(
    "error",
    [
        ModelError("AuthenticationError", "bad key", 401),
        ModelError("APIStatusError", "Error code: 402", 402),
        ModelError("BadRequestError", "Your credit balance is too low", 400),
        ModelError("EnforcedSpendLimitReachedError", "limit", 429),
    ],
)
def test_it_stops_at_once_when_the_api_refuses_for_good(tmp_path, error):
    out = tmp_path / "record.jsonl"
    runner = Runner(Scripted(lambda *_: error), jobs(5), out, lambda job, reply: {})
    with pytest.raises(Stop, match="the API refuses"):
        run(runner)
    assert len(lines_of(out)) == 1


def test_a_reply_between_failures_starts_the_count_again(tmp_path):
    out = tmp_path / "record.jsonl"
    said = iter(
        [ModelError("APITimeoutError", "t", None)] * 2
        + [reply_of({"a": 1})]
        + [ModelError("APITimeoutError", "t", None)] * 2
    )
    runner = Runner(Scripted(lambda *_: next(said)), jobs(5), out, lambda job, reply: {})
    run(runner)  # no stop: never three in a row
    assert [line["record"] for line in lines_of(out)] == [
        "failed",
        "failed",
        "reply",
        "failed",
        "failed",
    ]
    assert [job.id for job in runner.to_ask(lines_of(out))] == ["1", "2", "4", "5"]


def test_two_jobs_cannot_have_one_name(tmp_path):
    with pytest.raises(AskError):
        Runner(Scripted(None), [*jobs(1), *jobs(1)], tmp_path / "r.jsonl", lambda job, reply: {})


def test_the_thinking_of_a_reply_is_its_summary_and_nothing_when_it_was_left_out():
    assert ask.thoughts(reply_of({"a": 1}, thinking="It reads the part.")) == ["It reads the part."]
    assert ask.thoughts(reply_of({"a": 1}, thinking="")) == []


def test_the_usage_of_the_replies_is_added_up_and_priced():
    lines = [
        {
            "record": "reply",
            "usage": {"input_tokens": 1_000_000, "output_tokens": 100_000},
            "model": "claude-sonnet-5-5",
        },
        {"record": "failed", "usage": {"input_tokens": 5}},
        {
            "record": "reply",
            "usage": {"input_tokens": 500_000, "output_tokens": 0},
            "model": "claude-sonnet-5-5",
        },
    ]
    found = ask.usage_totals(lines)
    assert found["usage"] == {"input_tokens": 1_500_000, "output_tokens": 100_000}
    assert found["cost"] == pytest.approx(1.5 * 2.00 + 0.1 * 10.00)
    assert ask.usage_totals([{**lines[0], "model": "another"}])["cost"] is None


def test_a_path_outside_any_repository_is_allowed(tmp_path):
    assert ask.private_path_problem(tmp_path / "deep" / "record.jsonl") is None
