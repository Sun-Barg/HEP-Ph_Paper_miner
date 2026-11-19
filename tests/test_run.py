"""The runner of the evaluation: its order, what it skips, what it runs again, when it stops.

The command it starts is the real one, called in this process instead of a process of
its own, with a model that replies from a script and the papers held in memory. So the
records the runner reads are the records a run writes. No network, no LLM.
"""

import json
from collections import Counter
from pathlib import Path

import pytest
from conftest import asks, sample_source

from hepph_paper_miner.agent import __main__ as command
from hepph_paper_miner.agent import loop, origin
from hepph_paper_miner.agent.model import ClaudeModel, ModelError, Reply
from hepph_paper_miner.eval import run
from hepph_paper_miner.eval.run import Attempt, Cell, Runner, Stop, plan, read_attempt, refusal

SAMPLE = "2501.00001v2"
BUSY = "2503.00003v1"  # the source answers upstream_busy for it
ANSWER = {"answer": "Ten.", "found": True, "evidence": [{"arxiv_id": SAMPLE, "section_id": "2.1"}]}
CODE = {"commit": "c" * 40, "modified": False}

# What the scripted model does, by the word in the question:
#   ok          reads the paper, then hands in the answer
#   busy        the first time for a layout, reads the paper arXiv cannot give; then like ok
#   stuck       always reads the paper arXiv cannot give
#   refused     the API refuses the key
#   flaky       the API cannot be reached
CREDIT_400 = (
    "BadRequestError",
    "Error code: 400 - {'type': 'error', 'error': {'type': 'invalid_request_error', "
    "'message': 'Your credit balance is too low to access the Anthropic API.'}}",
    400,
)


def question(name: str) -> dict:
    return {
        "id": name,
        "question": f"What does the paper say? ({name})",
        "type": "single_section",
        "gold_papers": [SAMPLE],
        "gold_evidence": {"need": "all", "items": [{"arxiv_id": SAMPLE, "section_id": "2.1"}]},
        "expect_found": True,
        "reference_answer": "Ten.",
        "answer_key": {},
        "accept_note": "Ten.",
        "abstract_sufficient": False,
    }


def file_of(folder: Path, *names: str, called: str = "questions.jsonl") -> Path:
    path = folder / called
    path.write_text("".join(json.dumps(question(name)) + "\n" for name in names), "utf-8")
    return path


@pytest.fixture
def world(monkeypatch, tmp_path):
    """The command, with the scripted model and the papers in memory; the launches it got."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "not-a-real-key")
    monkeypatch.setattr(loop, "code_version", lambda: dict(CODE))
    monkeypatch.setattr(origin, "code_version", lambda: dict(CODE))
    seen: Counter = Counter()

    class Scripted(ClaudeModel):
        def __init__(self, name, **settings):
            # A client that is never asked anything: reply() below stands in for the API.
            super().__init__(name, client=object(), **settings)
            self.turn = 0

        async def reply(self, system, messages, tools, answer_schema) -> Reply:
            self.turn += 1
            text = messages[0]["content"]
            names = [tool["name"] for tool in tools]
            layout = "staged" if "get_outline" in names else "flat"
            if "refused" in text:
                raise ModelError("AuthenticationError", "Error code: 401 - invalid x-api-key", 401)
            if "credit" in text:
                raise ModelError(*CREDIT_400)
            if "flaky" in text:
                raise ModelError("APIConnectionError", "Connection error.", None)
            if self.turn > 1:
                return asks(("submit_answer", ANSWER))
            seen[(text, layout)] += 1
            unreadable = "stuck" in text or ("busy" in text and seen[(text, layout)] == 1)
            paper = BUSY if unreadable else SAMPLE
            return asks(
                ("get_outline" if layout == "staged" else "read_paper", {"arxiv_id": paper})
            )

    monkeypatch.setattr(command, "ClaudeModel", Scripted)
    monkeypatch.setattr(command, "Fetcher", lambda *args, **kwargs: None)
    monkeypatch.setattr(command, "ArxivSource", lambda fetcher: sample_source())
    launched: list[Cell] = []

    def launch(argv: list[str]) -> int:
        launched.append(
            Cell(
                argv[argv.index("--question-id") + 1],
                argv[argv.index("--toolset") + 1],
                int(argv[argv.index("--repeat") + 1]),
            )
        )
        return command.main(argv)

    return tmp_path, launch, launched


def runner(folder: Path, questions: Path, launch, said: list[str] | None = None) -> Runner:
    return Runner(
        questions,
        folder / "public",
        folder / "private",
        launch,
        (said if said is not None else []).append,
    )


# --- the order ---------------------------------------------------------------------------


def test_the_repetition_is_the_outer_loop_and_the_first_layout_alternates():
    cells = plan(["a", "b", "c"], repeats=2)
    assert [str(cell) for cell in cells] == [
        "a staged 1", "a flat 1", "b flat 1", "b staged 1", "c staged 1", "c flat 1",
        "a flat 2", "a staged 2", "b staged 2", "b flat 2", "c flat 2", "c staged 2",
    ]  # fmt: skip
    # Every question with every layout and repetition, once.
    assert len(set(cells)) == len(cells) == 3 * 2 * 2


# --- running, skipping, running again -----------------------------------------------------


def test_every_cell_runs_once_in_the_order_of_the_plan(world):
    folder, launch, launched = world
    questions = file_of(folder, "ok-a", "ok-b")
    cells = plan(["ok-a", "ok-b"], repeats=1)
    said: list[str] = []
    state = runner(folder, questions, launch, said).run(cells)

    assert launched == cells
    assert all(state.done(cell) for cell in cells)
    assert state.counts().startswith("4 cell(s): 4 done, 0 to run, 0 to run again, 0 given up")
    assert said[0] == "[1/4] ok-a staged 1 | running"
    assert said[1].startswith("[1/4] ok-a staged 1 | answered | 2 turn(s) | ")
    # Each record is the run's own, made as a run of the evaluation is made.
    for path in sorted((folder / "public").glob("*.jsonl")):
        first = read_attempt(path).run
        assert first["model"]["cache_control"] == {"type": "ephemeral"}
        assert first["model"]["thinking"] == {"type": "adaptive", "display": "summarized"}
        assert first["questions"]["file"] == "questions.jsonl"
    assert len(list((folder / "private").glob("*.jsonl"))) == 4


def test_a_second_start_runs_nothing_that_is_done(world):
    folder, launch, launched = world
    questions = file_of(folder, "ok-a")
    cells = plan(["ok-a"], repeats=2)
    runner(folder, questions, launch).run(cells)
    launched.clear()
    runner(folder, questions, launch).run(cells)
    assert launched == []


def test_a_spoilt_run_is_kept_and_its_cell_runs_again_after_the_pass(world):
    folder, launch, launched = world
    questions = file_of(folder, "busy", "ok")
    cells = plan(["busy", "ok"], repeats=1)
    state = runner(folder, questions, launch).run(cells)

    assert [str(cell) for cell in launched] == [
        "busy staged 1", "busy flat 1", "ok flat 1", "ok staged 1",  # the pass
        "busy staged 1", "busy flat 1",  # then again, what arXiv spoilt
    ]  # fmt: skip
    assert all(state.done(cell) for cell in cells)
    spoilt = [a for cell in cells for a in state.spoilt(cell)]
    assert [a.spoilt for a in spoilt] == ["a tool call ended in upstream_busy"] * 2
    assert all(a.end["reason"] == "answered" for a in spoilt)  # spoilt, though answered
    assert state.counts().endswith("| 2 spoilt run(s) kept")


def test_a_cell_spoilt_three_times_is_given_up(world):
    folder, launch, launched = world
    questions = file_of(folder, "stuck")
    cells = plan(["stuck"], repeats=1)
    state = runner(folder, questions, launch).run(cells)

    assert len(launched) == 2 * run.TRIES
    assert not any(state.to_run(cell) or state.done(cell) for cell in cells)
    assert "0 done, 0 to run, 0 to run again, 2 given up after 3 spoilt runs" in state.counts()
    assert state.line(cells[0]).endswith("| given up")


# --- stopping ------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("word", "said"),
    [
        ("refused", "the API refuses: AuthenticationError: Error code: 401"),
        ("credit", "the API refuses: BadRequestError: Error code: 400"),
    ],
)
def test_the_api_refusing_stops_everything_at_once(world, word, said):
    folder, launch, launched = world
    questions = file_of(folder, word, "ok")
    with pytest.raises(Stop, match=said):
        runner(folder, questions, launch).run(plan([word, "ok"], repeats=1))
    assert len(launched) == 1


def test_three_runs_in_a_row_that_the_api_failed_stop_the_runner(world):
    folder, launch, launched = world
    questions = file_of(folder, "flaky")
    with pytest.raises(Stop, match="the API failed 3 runs in a row: APIConnectionError"):
        runner(folder, questions, launch).run(plan(["flaky"], repeats=1))
    assert len(launched) == 3  # two in the pass, the third when the first is run again


def test_a_run_that_the_api_did_not_fail_starts_the_count_again(world):
    folder, launch, launched = world
    questions = file_of(folder, "flaky", "ok")
    with pytest.raises(Stop, match="the API failed 3 runs in a row"):
        runner(folder, questions, launch).run(plan(["flaky", "ok"], repeats=1))
    assert [str(cell) for cell in launched] == [
        "flaky staged 1", "flaky flat 1", "ok flat 1", "ok staged 1",  # two failures, then not
        "flaky staged 1", "flaky flat 1",  # the second pass: two in a row again
        "flaky staged 1",  # the third pass: the third in a row
    ]  # fmt: skip


def test_a_run_not_made_under_the_conditions_stops_the_runner(world):
    folder, launch, launched = world
    questions = file_of(folder, "ok")

    def another_effort(argv):
        return launch([*argv, "--effort", "medium"])

    with pytest.raises(Stop, match="not made under the conditions: model.effort is 'medium'"):
        runner(folder, questions, another_effort).run(plan(["ok"], repeats=1))
    assert len(launched) == 1


def test_a_command_that_wrote_no_record_stops_the_runner(tmp_path):
    questions = file_of(tmp_path, "ok")
    with pytest.raises(Stop, match=r"ok staged 1: the command wrote no record \(exit code 2\)"):
        runner(tmp_path, questions, lambda argv: 2).run(plan(["ok"], repeats=1))


@pytest.mark.parametrize(
    ("detail", "refuses"),
    [
        ("AuthenticationError: Error code: 401 - invalid x-api-key", True),
        ("PermissionDeniedError: Error code: 403 - not allowed", True),
        (
            "APIStatusError: Error code: 402 - {'error': {'type': 'billing_error'}}",
            True,
        ),
        ("EnforcedSpendLimitReachedError: Error code: 429 - spend limit", True),
        (": ".join(CREDIT_400[:2]), True),
        ("RateLimitError: Error code: 429 - rate limit", False),  # passes; three in a row stop
        ("OverloadedError: Error code: 529 - overloaded", False),
        ("APIConnectionError: Connection error.", False),
    ],
)
def test_which_errors_of_the_api_more_runs_cannot_change(detail, refuses):
    assert (refusal({"reason": "api_error", "detail": detail}) is not None) is refuses
    # Only a run that ended in an error of the API says anything about the API.
    assert refusal({"reason": "no_answer", "detail": detail}) is None


# --- what spoils a run ----------------------------------------------------------------------


def attempt(end=None, *errors: str) -> Attempt:
    turns = tuple(
        {"record": "turn", "tools": [{"name": "get_outline", "error_kind": kind}]}
        for kind in errors
    )
    return Attempt(Path("x.jsonl"), {"record": "run"}, turns, end)


# Decision 10 of the plan: what arXiv or the API failing looks like in a record. Written
# out here, not taken from the code, so that dropping one from the code is noticed.
SPOILING_ENDS = ["api_error", "tool_transport_error", "tool_timeout", "time_limit"]
SPOILING_TOOL_ERRORS = ["timeout", "upstream_busy"]


def test_what_spoils_a_run_is_what_the_plan_says():
    assert sorted(run.SPOILING_ENDS) == sorted(SPOILING_ENDS)
    assert sorted(run.SPOILING_TOOL_ERRORS) == sorted(SPOILING_TOOL_ERRORS)


@pytest.mark.parametrize("reason", SPOILING_ENDS)
def test_a_run_that_ended_because_arxiv_or_the_api_failed_is_spoilt(reason):
    assert attempt({"reason": reason}).spoilt == reason


@pytest.mark.parametrize("kind", SPOILING_TOOL_ERRORS)
def test_a_tool_call_that_arxiv_failed_spoils_the_run(kind):
    assert attempt({"reason": "answered"}, None, kind).spoilt == f"a tool call ended in {kind}"


@pytest.mark.parametrize(
    "reason", ["answered", "no_answer", "turn_limit", "max_tokens", "context_full"]
)
def test_how_the_model_ended_a_run_does_not_spoil_it(reason):
    # A wrong path, a missing answer or a full context are results, not failures of arXiv.
    assert attempt({"reason": reason}, "not_found", "no_such_section", "invalid_id").spoilt is None


def test_a_run_that_did_not_finish_is_spoilt(tmp_path):
    path = tmp_path / "cut.jsonl"
    path.write_text(json.dumps({"record": "run", "question_id": "q"}) + '\n{"record": "tu', "utf-8")
    found = read_attempt(path)
    assert found.end is None and found.spoilt == "the run did not finish"
    other = tmp_path / "other.jsonl"
    other.write_text('{"record": "grade"}\n', "utf-8")
    assert read_attempt(other) is None


# --- the command -----------------------------------------------------------------------------


def test_the_command_says_what_is_done_without_running_anything(world, monkeypatch, capsys):
    folder, launch, launched = world
    questions = file_of(folder, "ok-a", "ok-b")
    out = [
        "--questions",
        str(questions),
        "--out",
        str(folder / "public"),
        "--private",
        str(folder / "private"),
    ]
    assert run.main([*out, "--only", "ok-a", "--repeats", "1"], launch=launch) == 0
    launched.clear()
    capsys.readouterr()
    monkeypatch.delenv("ANTHROPIC_API_KEY")  # not needed to look
    assert run.main([*out, "--plan"], launch=launch) == 0
    shown = capsys.readouterr().out.splitlines()
    assert launched == []
    assert "ok-a staged 1 | done (answered)" in shown and "ok-b flat 1 | to run" in shown
    assert shown[-1].startswith("12 cell(s): 2 done, 10 to run")


def test_a_part_keeps_the_order_that_the_whole_file_gives_its_cells(world, monkeypatch, capsys):
    folder, launch, _ = world
    questions = file_of(folder, "ok-a", "ok-b")
    monkeypatch.delenv("ANTHROPIC_API_KEY")
    out = ["--questions", str(questions), "--out", str(folder / "public"), "--plan"]
    assert run.main([*out, "--only", "ok-b", "--repeats", "2"], launch=launch) == 0
    listed = [line.split(" | ")[0] for line in capsys.readouterr().out.splitlines()[1:-1]]
    # ok-b is the second question of the file, so the flat layout runs first in repetition 1.
    assert listed == ["ok-b flat 1", "ok-b staged 1", "ok-b staged 2", "ok-b flat 2"]


def test_the_run_that_counts_for_a_cell_is_its_first_unspoilt_one(tmp_path):
    def kept(name: str, end: dict | None) -> Attempt:
        return Attempt(
            tmp_path / name, {"question_id": "q", "toolset": "flat", "repeat": 1}, (), end
        )

    spoilt, first, second = kept("1", None), kept("2", {"reason": "answered"}), kept("3", {})
    other = Cell("q", "staged", 1)
    found = run.counted({Cell("q", "flat", 1): [spoilt, first, second], other: [spoilt]})
    assert found == {Cell("q", "flat", 1): first}


def test_the_command_ends_with_counts_and_a_code(world, capsys):
    folder, launch, _ = world
    questions = file_of(folder, "ok", "stuck")
    out = ["--questions", str(questions), "--out", str(folder / "public"), "--repeats", "1"]
    assert run.main([*out, "--only", "ok"], launch=launch) == 0
    assert capsys.readouterr().out.splitlines()[-1].startswith("2 cell(s): 2 done")
    assert run.main(out, launch=launch) == 1  # a cell was given up
    assert "2 given up" in capsys.readouterr().out.splitlines()[-1]


def test_the_command_stops_and_says_why(world, capsys):
    folder, launch, _ = world
    questions = file_of(folder, "refused")
    out = ["--questions", str(questions), "--out", str(folder / "public")]
    assert run.main(out, launch=launch) == 1
    shown = capsys.readouterr()
    assert "stopped: refused staged 1: the API refuses: AuthenticationError" in shown.err
    assert shown.out.splitlines()[-1].startswith("6 cell(s): 0 done, 5 to run, 1 to run again")


def test_the_command_refuses_code_that_no_commit_names(world, monkeypatch, capsys):
    folder, launch, launched = world
    monkeypatch.setattr(origin, "code_version", lambda: {**CODE, "modified": True})
    questions = file_of(folder, "ok")
    assert (
        run.main(["--questions", str(questions), "--out", str(folder / "public")], launch=launch)
        == 1
    )
    assert "files the repository keeps have been changed" in capsys.readouterr().err
    assert launched == []


def test_the_command_refuses_a_shell_without_the_key(world, monkeypatch, capsys):
    folder, launch, launched = world
    monkeypatch.delenv("ANTHROPIC_API_KEY")
    questions = file_of(folder, "ok")
    assert (
        run.main(["--questions", str(questions), "--out", str(folder / "public")], launch=launch)
        == 1
    )
    assert "ANTHROPIC_API_KEY is not set" in capsys.readouterr().err
    assert launched == []


def test_the_command_does_not_add_to_runs_of_another_question_file_or_other_code(
    world, monkeypatch, capsys
):
    folder, launch, launched = world
    first = file_of(folder, "ok")
    out = ["--out", str(folder / "public"), "--repeats", "1"]
    assert run.main(["--questions", str(first), *out], launch=launch) == 0
    launched.clear()

    # A record of a question given on the command line names no file, and is no run of it.
    stray = folder / "public" / "20990101T000000Z_None_staged_0000.jsonl"
    stray.write_text(json.dumps({"record": "run", "questions": None}) + "\n", "utf-8")
    assert run.main(["--questions", str(first), *out], launch=launch) == 1
    assert "runs of another question file" in capsys.readouterr().err
    stray.unlink()

    second = file_of(folder, "ok", "ok-b", called="other.jsonl")
    assert run.main(["--questions", str(second), *out], launch=launch) == 1
    assert "runs of another question file" in capsys.readouterr().err

    # A second repetition of the same file, after a new commit: refused, unless asked for.
    newer = {"commit": "d" * 40, "modified": False}
    monkeypatch.setattr(origin, "code_version", lambda: dict(newer))
    monkeypatch.setattr(loop, "code_version", lambda: dict(newer))
    again = ["--questions", str(first), "--out", str(folder / "public"), "--repeats", "2"]
    assert run.main(again, launch=launch) == 1
    assert "runs made by other code (ccccccc)" in capsys.readouterr().err
    assert launched == []
    assert run.main([*again, "--allow-other-code"], launch=launch) == 0
    assert [str(cell) for cell in launched] == ["ok flat 2", "ok staged 2"]


def test_the_command_refuses_a_question_file_of_another_digest(world, capsys):
    folder, launch, launched = world
    questions = file_of(folder, "ok")
    asked = [
        "--questions",
        str(questions),
        "--out",
        str(folder / "public"),
        "--questions-sha256",
        "0" * 64,
    ]
    assert run.main(asked, launch=launch) == 2
    assert "not the one given" in capsys.readouterr().err
    assert run.main([*asked[:-2], "--only", "nope"], launch=launch) == 2
    assert "no question nope" in capsys.readouterr().err
    assert launched == []


def test_the_process_of_a_run_is_the_command_of_one_question():
    # What the default launch starts: this interpreter, the module of the command.
    runner_ = Runner(Path("q.jsonl"), Path("out"), None, lambda argv: 0)
    assert runner_.arguments(Cell("eval-01", "flat", 2)) == [
        "--questions", "q.jsonl", "--question-id", "eval-01", "--toolset", "flat",
        "--cache", "--show-thinking", "--repeat", "2", "--out", "out",
    ]  # fmt: skip


def test_the_default_launch_starts_the_command_in_a_process_of_its_own(capsys):
    # Neither call reaches the network or the model: one asks for help, one is refused.
    assert run._in_a_process(["--help"]) == 0
    assert run._in_a_process(["--no-such-option"]) == 2
    # What the command said is passed on.
    assert "python -m hepph_paper_miner.agent: error:" in capsys.readouterr().err


def test_the_traceback_of_a_command_that_died_is_passed_on_and_its_answer_is_not(
    monkeypatch, capsys
):
    # Python ends with code 1 when an error nobody caught ends it, as the command does for
    # a run without an answer. Only the traceback says which of the two it was.
    died = (b"run x\nanswer    Ten.\n", b"Traceback (most recent call last):\nKeyError: 'turns'\n")
    calm = (b"run x\nended     no_answer\n", b"")
    for printed, said in (died, calm):
        done = run.subprocess.CompletedProcess([], 1, printed, said)
        monkeypatch.setattr(run.subprocess, "run", lambda *args, done=done, **kwargs: done)
        assert run._in_a_process([]) == 1
    passed_on = capsys.readouterr().err
    assert passed_on == "Traceback (most recent call last):\nKeyError: 'turns'\n"
