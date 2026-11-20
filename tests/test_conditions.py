"""The conditions of the evaluation: that they stay, and that code and pilot agree with them.

Three things are held together here.

    the conditions     They stand below a second time, as they were fixed. A change to
                       them has to be made in two places, by somebody who means it.
    the code           The command, started the way a run of the evaluation is started,
                       has to write a record that names the conditions the code has now
                       (REVISED: those of the evaluation with the tool texts as they
                       were changed after it). That fails when a default of the command,
                       of the loop or of the model moves, and when a text that a model
                       reads gets a new name.
    the pilot          The conditions were chosen from thirty runs on the development
                       questions. Their records are in the repository, and name them too.

When a test here fails, raising a name or a number until it passes is not the repair.
The evaluation is one experiment as long as its conditions stay: whether to change them
is the owner's decision, and runs made before a change are no runs of what comes after.
"""

import json
from collections import Counter
from pathlib import Path

import pytest
from conftest import asks, sample_source, says

from hepph_paper_miner.agent import __main__ as command
from hepph_paper_miner.agent.model import ClaudeModel, Reply
from hepph_paper_miner.agent.prompt import PROMPT_VERSION
from hepph_paper_miner.eval import conditions
from hepph_paper_miner.eval.conditions import (
    CONDITIONS,
    EVALUATION,
    PARSER,
    REVISED,
    differences,
    of_the_code,
)
from hepph_paper_miner.eval.grade import Record, read_record
from hepph_paper_miner.server import TOOLSET_VERSION
from hepph_paper_miner.sources.arxiv_latex import PARSER_VERSION

RUNS = Path(__file__).parent.parent / "results" / "runs" / "dev"

MODEL = {
    "model": "claude-sonnet-5-5",
    "max_tokens": 16000,
    "thinking": {"type": "adaptive"},
    "effort": "high",
    "answer_format": None,
    "cache_control": {"type": "ephemeral"},
    "max_retries": 2,
    "request_seconds": 600.0,
}
LIMITS = {"max_turns": 12, "tool_seconds": 700.0, "run_seconds": 900.0}
FIXED = {
    "toolset_version": {"staged": "staged-5", "flat": "flat-4"},
    "answer_channel": "tool",
    "prompt_version": "p2-tool",
    "model": MODEL,
    "limits": LIMITS,
}

ANSWER = {
    "answer": "Ten.",
    "found": True,
    "evidence": [{"arxiv_id": "2501.00001v2", "section_id": "2.1"}],
}
SUBMIT = asks(("submit_answer", ANSWER))
# One call that returns text of a paper, so that the record names the parser.
READ = {
    "staged": asks(("get_outline", {"arxiv_id": "2501.00001v2"})),
    "flat": asks(("read_paper", {"arxiv_id": "2501.00001v2"})),
}


# --- the conditions ----------------------------------------------------------------------


def test_the_conditions_are_the_ones_that_were_fixed():
    assert (EVALUATION, PARSER) == (FIXED, "4")


# The tool texts as they were changed after the evaluation, for what its runs had shown.
NOW = {"staged": "staged-6", "flat": "flat-5"}


def test_the_revised_conditions_are_those_of_the_evaluation_with_other_tool_texts():
    assert REVISED == {**FIXED, "toolset_version": NOW}
    assert CONDITIONS == {"evaluation": EVALUATION, "revised": REVISED}
    assert [name for name in EVALUATION if EVALUATION[name] != REVISED[name]] == ["toolset_version"]


def test_the_revised_conditions_name_the_texts_that_the_code_has():
    # A text cannot change under its name (test_toolset_pin.py, test_prompt.py). When a
    # name here differs, a text was changed and renamed, and no conditions name the code.
    assert TOOLSET_VERSION == REVISED["toolset_version"]
    assert PROMPT_VERSION[REVISED["answer_channel"]] == REVISED["prompt_version"]
    assert PARSER_VERSION == PARSER
    assert of_the_code() == "revised"


def test_code_with_texts_that_no_conditions_name_is_code_of_no_conditions(monkeypatch):
    import hepph_paper_miner.server as server

    monkeypatch.setattr(server, "TOOLSET_VERSION", {"staged": "staged-7", "flat": "flat-5"})
    assert of_the_code() is None
    # And the code of the evaluation, were it here again, would be named by its own.
    monkeypatch.setattr(server, "TOOLSET_VERSION", dict(EVALUATION["toolset_version"]))
    assert of_the_code() == "evaluation"
    monkeypatch.setattr(conditions, "PARSER", "5")
    assert of_the_code() is None


# --- the code ----------------------------------------------------------------------------


def started(monkeypatch, tmp_path, *options: str, replies: list[Reply]) -> Record:
    """Start the command and read the record it wrote.

    The model is the real one as far as its settings go, which is what a record names.
    Its replies come from a script, and the papers are held in memory.
    """
    replies = list(replies)

    class Scripted(ClaudeModel):
        def __init__(self, name, **settings):
            # A client that is never asked anything: reply() below stands in for the API.
            super().__init__(name, client=object(), **settings)

        async def reply(self, system, messages, tools, answer_schema) -> Reply:
            return replies.pop(0)

    monkeypatch.setenv("ANTHROPIC_API_KEY", "not-a-real-key")
    monkeypatch.setattr(command, "ClaudeModel", Scripted)
    monkeypatch.setattr(command, "Fetcher", lambda *args, **kwargs: None)
    monkeypatch.setattr(command, "ArxivSource", lambda fetcher: sample_source())
    folders = ["--out", str(tmp_path / "public"), "--private", str(tmp_path / "private")]
    assert command.main(["--question", "How much data?", *options, *folders]) == 0
    (public,) = (tmp_path / "public").iterdir()
    return read_record(public)


@pytest.mark.parametrize("toolset", ["staged", "flat"])
@pytest.mark.parametrize("more", [[], ["--show-thinking"]])
def test_the_command_started_as_for_the_evaluation_runs_under_the_conditions(
    monkeypatch, tmp_path, toolset, more
):
    # A layout, the cache and the repetition are all that a run of the evaluation names.
    # Everything else is what the command, the loop and the model do by themselves.
    options = ["--toolset", toolset, "--cache", "--repeat", "1", *more]
    record = started(monkeypatch, tmp_path, *options, replies=[READ[toolset], SUBMIT])

    assert record.end["parser_versions"] == ["4"]  # so the parser was looked at below
    assert differences(record.run, record.end, REVISED) == []
    # Against the conditions of the evaluation it differs in the one thing that was changed.
    was = EVALUATION["toolset_version"][toolset]
    assert differences(record.run, record.end) == [
        f"toolset_version is {NOW[toolset]!r}, not {was!r}"
    ]


def test_the_cache_is_the_one_condition_that_the_command_has_to_be_asked_for(monkeypatch, tmp_path):
    record = started(monkeypatch, tmp_path, replies=[READ["staged"], SUBMIT])
    assert differences(record.run, record.end, REVISED) == [
        "model.cache_control is None, not {'type': 'ephemeral'}"
    ]


@pytest.mark.parametrize(
    ("options", "last", "said"),
    [
        (["--effort", "medium"], SUBMIT, ["model.effort is 'medium', not 'high'"]),
        (["--max-turns", "8"], SUBMIT, ["limits.max_turns is 8, not 12"]),
        (
            ["--model", "claude-haiku-5-5"],
            SUBMIT,
            ["model.model is 'claude-haiku-5-5', not 'claude-sonnet-5-5'"],
        ),
        (
            ["--answer-channel", "format"],
            says(json.dumps(ANSWER)),
            [
                "answer_channel is 'format', not 'tool'",
                "prompt_version is 'p1', not 'p2-tool'",
                "model.answer_format is 'json_schema', not None",
            ],
        ),
        (
            ["--answer-channel", "text"],
            says(json.dumps(ANSWER)),
            ["answer_channel is 'text', not 'tool'", "prompt_version is 'p2-text', not 'p2-tool'"],
        ),
    ],
)
def test_a_run_started_with_another_option_says_so_in_its_record(
    monkeypatch, tmp_path, options, last, said
):
    record = started(monkeypatch, tmp_path, "--cache", *options, replies=[READ["staged"], last])
    assert differences(record.run, record.end, REVISED) == said


# --- holding a record against the conditions ---------------------------------------------


def line(**changes) -> dict:
    """The first line of a record that names the conditions, as it is read back from a file."""
    run = {
        "record": "run",
        "question_id": "eval-01",
        "toolset": "staged",
        "toolset_version": "staged-5",
        "tools": ["search_papers", "get_outline", "read_section", "submit_answer"],
        "prompt_version": "p2-tool",
        "answer_channel": "tool",
        "model": {**MODEL, "sdk": "anthropic 2.8.0"},
        "limits": LIMITS,
        "packages": {"mcp": "2.3.0", "pydantic": "2.14.3"},
        "code": {"commit": "0" * 40, "modified": False},
    }
    return json.loads(json.dumps({**run, **changes}))


def without(settings: dict, name: str) -> dict:
    return {key: value for key, value in settings.items() if key != name}


def test_a_record_that_names_the_conditions_has_no_difference():
    assert differences(line()) == []
    assert differences(line(toolset="flat", toolset_version="flat-4")) == []
    assert differences(line(), {"parser_versions": ["4"]}) == []
    assert differences(line(), {"parser_versions": []}) == []  # a run that read no paper
    # Whether the summaries of the thinking were asked for is left open.
    for display in ("summarized", "omitted"):
        shown = {**MODEL, "thinking": {"type": "adaptive", "display": display}}
        assert differences(line(model=shown)) == []
    # What is no condition can be anything: the code, the packages, the SDK, the question.
    other = line(
        code={"commit": "f" * 40, "modified": True},
        packages={"mcp": "2.4.0"},
        model={**MODEL, "sdk": "anthropic 2.9.1"},
        question_id="dev-03",
        repeat=3,
    )
    assert differences(other) == []


@pytest.mark.parametrize(
    ("changes", "said"),
    [
        ({"toolset_version": "staged-6"}, "toolset_version is 'staged-6', not 'staged-5'"),
        # The texts of one layout under the name of the other.
        ({"toolset": "flat"}, "toolset_version is 'staged-5', not 'flat-4'"),
        ({"toolset": "both"}, "toolset is 'both', not one of the layouts: staged, flat"),
        ({"toolset": None}, "toolset is None, not one of the layouts: staged, flat"),
        ({"toolset_version": None}, "toolset_version is None, not 'staged-5'"),
        ({"answer_channel": "format"}, "answer_channel is 'format', not 'tool'"),
        ({"prompt_version": "p3-tool"}, "prompt_version is 'p3-tool', not 'p2-tool'"),
        (
            {"model": {**MODEL, "model": "claude-opus-5-5"}},
            "model.model is 'claude-opus-5-5', not 'claude-sonnet-5-5'",
        ),
        ({"model": {**MODEL, "max_tokens": 8000}}, "model.max_tokens is 8000, not 16000"),
        (
            {"model": {**MODEL, "thinking": {"type": "enabled", "budget_tokens": 4000}}},
            "model.thinking is {'type': 'enabled', 'budget_tokens': 4000}, "
            "not {'type': 'adaptive'}",
        ),
        (
            {"model": {**MODEL, "thinking": {"type": "adaptive", "budget_tokens": 4000}}},
            "model.thinking is {'type': 'adaptive', 'budget_tokens': 4000}, "
            "not {'type': 'adaptive'}",
        ),
        ({"model": {**MODEL, "effort": "xhigh"}}, "model.effort is 'xhigh', not 'high'"),
        (
            {"model": {**MODEL, "answer_format": "json_schema"}},
            "model.answer_format is 'json_schema', not None",
        ),
        (
            {"model": {**MODEL, "cache_control": None}},
            "model.cache_control is None, not {'type': 'ephemeral'}",
        ),
        ({"model": {**MODEL, "max_retries": 0}}, "model.max_retries is 0, not 2"),
        (
            {"model": {**MODEL, "request_seconds": 60.0}},
            "model.request_seconds is 60.0, not 600.0",
        ),
        # Something a request held that nobody decided on.
        (
            {"model": {**MODEL, "temperature": 0.0}},
            "model.temperature is a setting that the conditions do not name",
        ),
        # Left out is not the same as null: a record written before the setting existed.
        (
            {"model": without(MODEL, "answer_format")},
            "model.answer_format is not in the record",
        ),
        ({"limits": {**LIMITS, "max_turns": 20}}, "limits.max_turns is 20, not 12"),
        ({"limits": {**LIMITS, "tool_seconds": 300.0}}, "limits.tool_seconds is 300.0, not 700.0"),
        ({"limits": {**LIMITS, "run_seconds": 1800.0}}, "limits.run_seconds is 1800.0, not 900.0"),
        (
            {"limits": {**LIMITS, "tool_calls": 30}},
            "limits.tool_calls is a limit that the conditions do not name",
        ),
        ({"limits": without(LIMITS, "run_seconds")}, "limits.run_seconds is not in the record"),
    ],
)
def test_every_departure_from_the_conditions_is_named_by_itself(changes, said):
    assert differences(line(**changes)) == [said]


def test_a_record_is_held_against_the_conditions_that_are_given():
    now = line(toolset_version="staged-6")
    assert differences(now, None, REVISED) == []
    assert differences(now) == ["toolset_version is 'staged-6', not 'staged-5'"]
    assert differences(line(), None, REVISED) == ["toolset_version is 'staged-5', not 'staged-6'"]
    flat = line(toolset="flat", toolset_version="flat-5")
    assert differences(flat, {"parser_versions": ["4"]}, REVISED) == []
    # Everything else is held as before.
    slower = line(toolset_version="staged-6", limits={**LIMITS, "max_turns": 20})
    assert differences(slower, None, REVISED) == ["limits.max_turns is 20, not 12"]


def test_a_result_of_another_parser_is_named_from_the_last_line():
    assert differences(line(), {"parser_versions": ["3", "4"]}) == [
        "a result came from parser '3', not '4'"
    ]


def test_what_a_record_does_not_say_at_all_is_named_as_missing():
    assert differences({}) == [
        "toolset is not in the record",
        "answer_channel is not in the record",
        "prompt_version is not in the record",
        *(f"model.{name} is not in the record" for name in MODEL),
        *(f"limits.{name} is not in the record" for name in LIMITS),
    ]
    # Settings of a model that is not the real one, as a test of the loop has them.
    assert differences(line(model={"model": "scripted"}))[:2] == [
        "model.model is 'scripted', not 'claude-sonnet-5-5'",
        "model.max_tokens is not in the record",
    ]


# --- the pilot: the runs on the development questions that the conditions rest on --------


def records_of(folder: str) -> list[Record]:
    return [read_record(path) for path in sorted((RUNS / folder).glob("*.jsonl"))]


def test_the_runs_that_the_conditions_rest_on_were_made_under_them():
    records = records_of("diag-3-tool")
    # The five development questions with each layout, three times: every one once.
    made = Counter(
        (record.run["question_id"], record.run["toolset"], record.run["repeat"])
        for record in records
    )
    assert len(made) == 30 and set(made.values()) == {1}
    assert {question for question, _, _ in made} == {f"dev-0{n}" for n in range(1, 6)}
    assert {layout for _, layout, _ in made} == {"staged", "flat"}

    for record in records:
        assert differences(record.run, record.end) == [], record.run["run_id"]
    # They were made by one commit, with no file of it changed.
    code = {
        (record.run["code"]["commit"][:7], record.run["code"]["modified"]) for record in records
    }
    assert code == {("9d8024c", False)}

    # What the README and the loop say of these runs: every one handed in an answer, and
    # the longest took six responses, so the limit of twelve ended none of them.
    assert {record.end["reason"] for record in records} == {"answered"}
    turns = [record.end["turns"] for record in records]
    assert (min(turns), max(turns)) == (2, 6)


@pytest.mark.parametrize(
    "folder", ["first-run", "pilot-1", "pilot-2", "diag-1", "diag-2", "diag-3-text"]
)
def test_the_other_development_runs_were_not(folder):
    # The test above would be worth nothing if every record passed it.
    records = records_of(folder)
    assert records
    for record in records:
        assert differences(record.run, record.end), record.run["run_id"]


def test_the_two_halves_of_the_third_diagnosis_differ_in_the_way_to_answer_only():
    records = records_of("diag-3-text")
    assert len(records) == 30
    for record in records:
        assert differences(record.run, record.end) == [
            "answer_channel is 'text', not 'tool'",
            "prompt_version is 'p2-text', not 'p2-tool'",
        ]
