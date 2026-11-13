"""The command that asks one question: what it refuses to start, and one run from end to end.

The run uses a model that replies from a script and papers held in memory, put in
place of the real ones. The real ones cost money and send requests.
"""

import dataclasses
import json

import pytest
from conftest import ScriptedModel, asks, sample_source, says

from hepph_paper_miner.agent import __main__ as command

ANSWER = {
    "answer": "Ten.",
    "found": True,
    "evidence": [{"arxiv_id": "2501.00001v2", "section_id": "2.1"}],
}


@pytest.fixture
def folders(tmp_path):
    return ["--out", str(tmp_path / "public"), "--private", str(tmp_path / "private")]


def test_without_a_key_nothing_is_started(monkeypatch, capsys, tmp_path, folders):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert command.main(["--question", "Q?", *folders]) == 2
    assert "ANTHROPIC_API_KEY is not set" in capsys.readouterr().err
    assert not any(tmp_path.iterdir())


def test_a_turn_limit_below_one_is_refused_before_anything_is_written(
    monkeypatch, capsys, tmp_path, folders
):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "not-a-real-key")
    assert command.main(["--question", "Q?", "--max-turns", "0", *folders]) == 2
    assert "--max-turns 0: max_turns has to be at least 1" in capsys.readouterr().err
    assert not any(tmp_path.iterdir())  # before, two empty record files stayed behind


def test_a_question_that_is_not_in_the_file_is_refused_before_anything_is_written(
    monkeypatch, capsys, tmp_path, tmp_path_factory, folders
):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "not-a-real-key")
    assert command.main(["--question-id", "dev-99", *folders]) == 2
    assert "no question 'dev-99'; there are: dev-01, dev-02" in capsys.readouterr().err
    assert (
        command.main(["--question-id", "dev-01", "--questions", str(tmp_path / "none"), *folders])
        == 2
    )
    assert "cannot read the questions" in capsys.readouterr().err
    # A file with a value of the wrong form is refused in the same way, with its line named.
    line = {
        "id": 7,
        "question": "What?",
        "type": "single_section",
        "gold_papers": ["2501.00001v2"],
        "gold_evidence": {
            "need": "all",
            "items": [{"arxiv_id": "2501.00001v2", "section_id": "2.1"}],
        },
        "expect_found": True,
        "reference_answer": "That.",
        "answer_key": {},
        "accept_note": "That, or close to it.",
        "abstract_sufficient": False,
    }
    wrong = tmp_path_factory.mktemp("questions") / "wrong.jsonl"
    wrong.write_text(json.dumps(line) + "\n", encoding="utf-8")
    assert command.main(["--question-id", "7", "--questions", str(wrong), *folders]) == 2
    assert (
        "cannot read the questions: wrong.jsonl line 1: id has to be text"
        in capsys.readouterr().err
    )
    assert not any(tmp_path.iterdir())


def test_one_question_from_the_command_line_to_the_two_files(
    monkeypatch, capsys, tmp_path, folders
):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "not-a-real-key")
    section = ("read_section", {"arxiv_id": "2501.00001v2", "section_id": "2.1"})
    scripted = ScriptedModel(asks(section), says(json.dumps(ANSWER)))
    made = {}

    def model(name, effort, cache, show_thinking):
        made.update(name=name, effort=effort, cache=cache, show_thinking=show_thinking)
        return scripted

    monkeypatch.setattr(command, "ClaudeModel", model)
    monkeypatch.setattr(command, "Fetcher", lambda *args, **kwargs: None)
    monkeypatch.setattr(command, "ArxivSource", lambda fetcher: sample_source())

    code = command.main(
        ["--question", "How much data?", "--toolset", "staged", "--effort", "medium", *folders]
    )

    assert code == 0
    assert made == {
        "name": "claude-sonnet-5-5",
        "effort": "medium",
        "cache": False,
        "show_thinking": False,
    }
    shown = capsys.readouterr().out
    assert "ended     answered" in shown and "answer    Ten." in shown
    assert "evidence  2501.00001v2 2.1" in shown
    assert "read      74 characters in 1 tool results" in shown
    assert "cache" not in shown  # nothing went through the cache, so nothing is said of it
    (public,) = (tmp_path / "public").iterdir()
    (private,) = (tmp_path / "private").iterdir()
    assert public.name == private.name and "_adhoc_staged_" in public.name
    first = json.loads(public.read_text(encoding="utf-8").splitlines()[0])
    assert (first["question_id"], first["toolset"], first["toolset_version"]) == (
        "adhoc",
        "staged",
        "staged-5",
    )
    assert "Data text." not in public.read_text(encoding="utf-8")
    assert "Data text." in private.read_text(encoding="utf-8")


def test_with_the_cache_asked_for_the_model_is_told_and_the_counts_are_shown(
    monkeypatch, capsys, folders
):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "not-a-real-key")
    # As the API counts a second request with the cache on: most of the prompt read
    # from the cache, what is new written to it, and little left that is neither.
    usage = {
        "input_tokens": 12,
        "output_tokens": 10,
        "cache_creation_input_tokens": 900,
        "cache_read_input_tokens": 300,
    }
    answer = dataclasses.replace(says(json.dumps(ANSWER)), usage=usage)
    made = {}

    def model(name, effort, cache, show_thinking):
        made.update(cache=cache)
        return ScriptedModel(answer)

    monkeypatch.setattr(command, "ClaudeModel", model)
    monkeypatch.setattr(command, "Fetcher", lambda *args, **kwargs: None)
    monkeypatch.setattr(command, "ArxivSource", lambda fetcher: sample_source())

    assert command.main(["--question", "Q?", "--cache", *folders]) == 0

    assert made == {"cache": True}
    shown = capsys.readouterr().out
    assert "12 input and 10 output tokens" in shown
    assert "cache     900 tokens written to it, 300 read from it" in shown


def test_with_the_thinking_asked_for_the_model_is_told(monkeypatch, folders):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "not-a-real-key")
    made = {}

    def model(name, effort, cache, show_thinking):
        made.update(show_thinking=show_thinking)
        return ScriptedModel(says(json.dumps(ANSWER)))

    monkeypatch.setattr(command, "ClaudeModel", model)
    monkeypatch.setattr(command, "Fetcher", lambda *args, **kwargs: None)
    monkeypatch.setattr(command, "ArxivSource", lambda fetcher: sample_source())

    assert command.main(["--question", "Q?", "--show-thinking", *folders]) == 0

    assert made == {"show_thinking": True}


def test_a_run_without_an_answer_ends_with_a_code_that_says_so(monkeypatch, capsys, folders):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "not-a-real-key")
    monkeypatch.setattr(
        command, "ClaudeModel", lambda name, effort, cache, show_thinking: ScriptedModel(says(""))
    )
    monkeypatch.setattr(command, "Fetcher", lambda *args, **kwargs: None)
    monkeypatch.setattr(command, "ArxivSource", lambda fetcher: sample_source())
    assert command.main(["--question-id", "dev-05", "--toolset", "flat", *folders]) == 1
    assert "ended     no_answer (the response had no text)" in capsys.readouterr().out
