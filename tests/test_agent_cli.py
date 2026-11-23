"""The command that asks one question: what it refuses to start, and one run from end to end.

The run uses a model that replies from a script and papers held in memory, put in
place of the real ones. The real ones cost money and send requests.
"""

import dataclasses
import hashlib
import json
from pathlib import Path

import pytest
from conftest import ScriptedModel, asks, sample_source, says

from hepph_paper_miner.agent import __main__ as command
from hepph_paper_miner.agent.origin import code_version
from hepph_paper_miner.agent.prompt import ANSWER_SCHEMA

ANSWER = {
    "answer": "Ten.",
    "found": True,
    "evidence": [{"arxiv_id": "2501.00001v2", "section_id": "2.1"}],
}
# How a run hands in that answer when the command is told nothing else.
SUBMIT = ("submit_answer", ANSWER)


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


def test_a_repetition_below_one_is_refused_before_anything_is_written(
    monkeypatch, capsys, tmp_path, folders
):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "not-a-real-key")
    assert command.main(["--question", "Q?", "--repeat", "0", *folders]) == 2
    assert "--repeat 0: repetitions are counted from 1" in capsys.readouterr().err
    assert not any(tmp_path.iterdir())


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
    scripted = ScriptedModel(asks(section), asks(SUBMIT))
    made = {}

    def model(name, effort, cache, show_thinking, answer_format):
        made.update(
            name=name,
            effort=effort,
            cache=cache,
            show_thinking=show_thinking,
            answer_format=answer_format,
        )
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
        "answer_format": False,
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
        "staged-6",
    )
    # A question typed on the command line comes from no file, and nobody said which
    # repetition this is. The code that ran is named all the same.
    assert (first["questions"], first["repeat"]) == (None, None)
    assert first["code"] == code_version()
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
    answer = dataclasses.replace(asks(SUBMIT), usage=usage)
    made = {}

    def model(name, effort, cache, show_thinking, answer_format):
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

    def model(name, effort, cache, show_thinking, answer_format):
        made.update(show_thinking=show_thinking)
        return ScriptedModel(asks(SUBMIT))

    monkeypatch.setattr(command, "ClaudeModel", model)
    monkeypatch.setattr(command, "Fetcher", lambda *args, **kwargs: None)
    monkeypatch.setattr(command, "ArxivSource", lambda fetcher: sample_source())

    assert command.main(["--question", "Q?", "--show-thinking", *folders]) == 0

    assert made == {"show_thinking": True}


def test_without_the_answer_form_the_model_is_told_and_plain_text_is_no_answer(
    monkeypatch, capsys, tmp_path, folders
):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "not-a-real-key")
    made = {}

    def model(name, effort, cache, show_thinking, answer_format):
        made.update(answer_format=answer_format)
        # What a model writes when nothing holds it to the form.
        return ScriptedModel(says("The paper gives no such number."))

    monkeypatch.setattr(command, "ClaudeModel", model)
    monkeypatch.setattr(command, "Fetcher", lambda *args, **kwargs: None)
    monkeypatch.setattr(command, "ArxivSource", lambda fetcher: sample_source())

    # Such a run is a diagnosis. Its text is not taken for an answer, and the command
    # says so with its exit code like for any other run without one.
    asked = ["--question", "Q?", "--answer-channel", "format", "--no-answer-format", *folders]
    assert command.main(asked) == 1

    assert made == {"answer_format": False}
    shown = capsys.readouterr().out
    assert "ended     no_answer (the text was not an answer of the expected form)" in shown
    (public,) = (tmp_path / "public").iterdir()
    last = json.loads(public.read_text(encoding="utf-8").splitlines()[-1])
    assert (last["reason"], last["answer"]) == ("no_answer", None)


def test_the_record_names_the_question_file_and_the_repetition(monkeypatch, tmp_path, folders):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "not-a-real-key")
    monkeypatch.setattr(
        command,
        "ClaudeModel",
        lambda name, effort, cache, show_thinking, answer_format: ScriptedModel(asks(SUBMIT)),
    )
    monkeypatch.setattr(command, "Fetcher", lambda *args, **kwargs: None)
    monkeypatch.setattr(command, "ArxivSource", lambda fetcher: sample_source())

    assert command.main(["--question-id", "dev-04", "--repeat", "3", *folders]) == 0

    (public,) = (tmp_path / "public").iterdir()
    first = json.loads(public.read_text(encoding="utf-8").splitlines()[0])
    assert (first["question_id"], first["repeat"]) == ("dev-04", 3)
    # An id says nothing once the file has been edited, so the file is named as it lay
    # on the disk: two records with the same digest were asked the same question.
    file = Path("eval_data/questions_dev.jsonl")
    assert first["questions"] == {
        "file": "questions_dev.jsonl",
        "sha256": hashlib.sha256(file.read_bytes()).hexdigest(),
    }


def test_a_run_without_an_answer_ends_with_a_code_that_says_so(monkeypatch, capsys, folders):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "not-a-real-key")
    monkeypatch.setattr(
        command,
        "ClaudeModel",
        lambda name, effort, cache, show_thinking, answer_format: ScriptedModel(
            says("It is ten."), says("Ten, as I said.")
        ),
    )
    monkeypatch.setattr(command, "Fetcher", lambda *args, **kwargs: None)
    monkeypatch.setattr(command, "ArxivSource", lambda fetcher: sample_source())
    assert command.main(["--question-id", "dev-05", "--toolset", "flat", *folders]) == 1
    shown = capsys.readouterr().out
    # The loop asked for the call after the first response, and the second had none either.
    assert (
        "ended     no_answer (the turn ended without a call of submit_answer, "
        "also after the loop had asked for it)"
    ) in shown
    assert "turns     2\nasked     again for the call, after response 1\n" in shown


def test_a_run_that_was_not_asked_again_says_nothing_of_it(monkeypatch, capsys, folders):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "not-a-real-key")
    monkeypatch.setattr(
        command,
        "ClaudeModel",
        lambda name, effort, cache, show_thinking, answer_format: ScriptedModel(asks(SUBMIT)),
    )
    monkeypatch.setattr(command, "Fetcher", lambda *args, **kwargs: None)
    monkeypatch.setattr(command, "ArxivSource", lambda fetcher: sample_source())
    assert command.main(["--question-id", "dev-05", "--toolset", "flat", *folders]) == 0
    assert "asked " not in capsys.readouterr().out


@pytest.mark.parametrize(
    ("channel", "last", "prompt", "held"),
    [
        ("tool", asks(SUBMIT), "p3-tool", None),
        ("format", says(json.dumps(ANSWER)), "p1", ANSWER_SCHEMA),
        ("text", says(json.dumps(ANSWER)), "p2-text", None),
    ],
)
def test_each_way_to_hand_in_the_answer_reaches_the_loop_and_the_record(
    monkeypatch, capsys, tmp_path, folders, channel, last, prompt, held
):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "not-a-real-key")
    section = ("read_section", {"arxiv_id": "2501.00001v2", "section_id": "2.1"})
    scripted = ScriptedModel(asks(section), last)
    made = {}

    def model(name, effort, cache, show_thinking, answer_format):
        made.update(answer_format=answer_format)
        return scripted

    monkeypatch.setattr(command, "ClaudeModel", model)
    monkeypatch.setattr(command, "Fetcher", lambda *args, **kwargs: None)
    monkeypatch.setattr(command, "ArxivSource", lambda fetcher: sample_source())

    assert (
        command.main(["--question", "How much data?", "--answer-channel", channel, *folders]) == 0
    )

    # A form goes into the requests in one of the ways only. In the two others the
    # model is set to send none, so that its settings in the record say what the
    # requests held, and the loop passes it none either.
    assert made == {"answer_format": held is not None}
    assert [asked["schema"] for asked in scripted.asked] == [held, held]
    shown = capsys.readouterr().out
    assert "ended     answered" in shown and "answer    Ten." in shown
    assert "read      74 characters in 1 tool results" in shown
    (public,) = (tmp_path / "public").iterdir()
    first, *_, end = (json.loads(line) for line in public.read_text(encoding="utf-8").splitlines())
    assert (first["answer_channel"], first["prompt_version"]) == (channel, prompt)
    assert (end["reason"], end["answer"]) == ("answered", ANSWER)


def test_without_the_option_the_answer_is_a_call_of_the_loops_tool(monkeypatch, tmp_path, folders):
    # The way the evaluation uses is what the command does when it is told nothing else.
    monkeypatch.setenv("ANTHROPIC_API_KEY", "not-a-real-key")
    scripted = ScriptedModel(asks(SUBMIT))
    monkeypatch.setattr(
        command,
        "ClaudeModel",
        lambda name, effort, cache, show_thinking, answer_format: scripted,
    )
    monkeypatch.setattr(command, "Fetcher", lambda *args, **kwargs: None)
    monkeypatch.setattr(command, "ArxivSource", lambda fetcher: sample_source())

    assert command.main(["--question", "Q?", *folders]) == 0

    assert scripted.asked[0]["schema"] is None
    assert scripted.asked[0]["tools"][-1]["name"] == "submit_answer"
    (public,) = (tmp_path / "public").iterdir()
    first = json.loads(public.read_text(encoding="utf-8").splitlines()[0])
    assert (first["answer_channel"], first["prompt_version"]) == ("tool", "p3-tool")


@pytest.mark.parametrize(
    ("options", "channel"),
    [
        ([], "tool"),  # what the command does when it is not told a way
        (["--answer-channel", "tool"], "tool"),
        (["--answer-channel", "text"], "text"),
    ],
)
def test_leaving_out_the_form_goes_with_the_one_way_that_sends_it(
    monkeypatch, capsys, tmp_path, folders, options, channel
):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "not-a-real-key")
    asked = ["--question", "Q?", "--no-answer-format", *options, *folders]
    assert command.main(asked) == 2
    assert (
        f"--no-answer-format goes with --answer-channel format only: a run with "
        f"--answer-channel {channel} sends no form of the answer anyway"
    ) in capsys.readouterr().err
    assert not any(tmp_path.iterdir())


def test_a_way_to_hand_in_the_answer_that_does_not_exist_is_refused(monkeypatch, capsys, folders):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "not-a-real-key")
    with pytest.raises(SystemExit):
        command.main(["--question", "Q?", "--answer-channel", "letter", *folders])
    assert "invalid choice: 'letter'" in capsys.readouterr().err
