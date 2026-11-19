"""The judge: what it is given, what it is not given, what a request holds, and its record.

No network and no LLM. The API is the real SDK over a transport that answers from
memory, and the runner is given a judge that answers from a script.
"""

import csv
import hashlib
import json
import re
from pathlib import Path

import anthropic
import httpx2
import pytest

from hepph_paper_miner.agent.model import ModelError, Reply
from hepph_paper_miner.agent.origin import file_digest
from hepph_paper_miner.eval import judge
from hepph_paper_miner.eval.conditions import EVALUATION
from hepph_paper_miner.eval.judge import (
    JUDGE,
    JUDGE_VERSION,
    MESSAGE,
    REPEATS,
    SYSTEM_PROMPT,
    VERDICT_SCHEMA,
    ClaudeJudge,
    Item,
    JudgeError,
    chosen,
    control_items,
    message_for,
    read_record,
    read_verdict,
    sheet_items,
    summary,
    texts_digest,
    verdict_of,
)
from hepph_paper_miner.eval.questions import load_questions
from hepph_paper_miner.eval.sheet import (
    SHEET_COLUMNS,
    counted_attempts,
    rows_of,
    write_key,
    write_sheet,
)

ROOT = Path(__file__).parent.parent
PAPER = "2501.00001v2"
# The name of the texts the judge reads, and the digest of those texts.
PINNED = ("j1", "a6adc483e6edb104867575a450e450d0b7af5196fbe4bb523795fc98f0f5b88d")
CONTROL_COLUMNS = ("id", "question_id", "kind", "found", "answer", "grade", "why_wrong", "detail")


def question(name: str) -> dict:
    return {
        "id": name,
        "question": f"What does the paper say about {name}?",
        "type": "single_section",
        "gold_papers": [PAPER],
        "gold_evidence": {
            "need": "all",
            "items": [{"arxiv_id": PAPER, "section_id": "2.1", "anchor": f"anchor of {name}"}],
        },
        "expect_found": True,
        "reference_answer": f"The reference of {name}.",
        "answer_key": {"by_hand": [f"the key of {name}"]},
        "accept_note": f"What is accepted for {name}.",
        "abstract_sufficient": False,
        "notes": {"origin": f"a note on {name}"},
    }


def questions_file(folder: Path, *names: str) -> Path:
    path = folder / "questions.jsonl"
    path.write_text("".join(json.dumps(question(name)) + "\n" for name in names), encoding="utf-8")
    return path


def sheet_file(folder: Path, rows: list[dict], columns=SHEET_COLUMNS, name="sheet.csv") -> Path:
    path = folder / name
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, columns, extrasaction="ignore", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    return path


def row(number: int, name: str, answer: str, found: str = "true", **more: str) -> dict:
    return {"number": str(number), "question_id": name, "found": found, "answer": answer, **more}


def control(name: str, of: str, answer: str, found: str = "true", **more: str) -> dict:
    said = {"kind": "made", "grade": "wrong", "why_wrong": "a number", "detail": "changed"}
    return {"id": name, "question_id": of, "found": found, "answer": answer, **said, **more}


def reply(verdict="right", why="Every required point is there.", **more) -> Reply:
    values = {
        "stop_reason": "end_turn",
        "text": json.dumps({"verdict": verdict, "why": why}),
        "tool_calls": (),
        "blocks": ("thinking", "text"),
        "usage": {"input_tokens": 1000, "output_tokens": 500},
        "content": None,
        "model": "claude-sonnet-5-5",
    }
    return Reply(**{**values, **more})


class Scripted:
    """A judge that answers from a function of the request, and keeps the requests."""

    def __init__(self, answer=lambda message: reply()) -> None:
        self._answer = answer
        self.asked: list[str] = []
        self.systems: set[str] = set()
        self.schemas: list[dict] = []

    @property
    def settings(self) -> dict:
        return {"model": "scripted"}

    async def ask(self, system: str, message: str, schema: dict) -> Reply:
        self.asked.append(message)
        self.systems.add(system)
        self.schemas.append(schema)
        said = self._answer(message)
        if isinstance(said, Exception):
            raise said
        return said


def answers_in(messages: list[str]) -> list[str]:
    return [re.search(r'<answer found="\w+">\n(.*)\n</answer>', text, re.S)[1] for text in messages]


@pytest.fixture(autouse=True)
def committed_code(monkeypatch):
    # The command names the commit it runs from and refuses changed code. Under test the
    # code is whatever is being worked on.
    monkeypatch.setattr(judge, "code_version", lambda: {"commit": "c0ffee", "modified": False})


@pytest.fixture
def given(tmp_path) -> dict:
    """Two questions, a sheet of three answers and two controls."""
    questions = questions_file(tmp_path, "q1", "q2")
    rows = [row(1, "q1", "first"), row(2, "q1", "second"), row(3, "q2", "third", found="false")]
    sheet = sheet_file(tmp_path, rows)
    controls = sheet_file(
        tmp_path,
        [control("syn-1", "q1", "made one"), control("syn-2", "q2", "made two")],
        CONTROL_COLUMNS,
        "controls.csv",
    )
    out = tmp_path / "out" / "record.jsonl"
    argv = ["--questions", str(questions), "--sheet", str(sheet), "--controls", str(controls)]
    return {
        "questions": questions,
        "sheet": sheet,
        "controls": controls,
        "out": out,
        "argv": [*argv, "--out", str(out)],
    }


# --- the texts the judge reads -------------------------------------------------------------


def test_the_texts_are_the_ones_this_version_names():
    # The judge reads these texts, so a change to them is another judge. When this fails:
    # raise JUDGE_VERSION (eval/judge.py), then put the new name and digest into PINNED.
    texts = [SYSTEM_PROMPT, MESSAGE, VERDICT_SCHEMA]
    digest = hashlib.sha256(json.dumps(texts).encode("utf-8")).hexdigest()
    assert (JUDGE_VERSION, digest) == PINNED, digest
    assert texts_digest() == digest


def test_the_judge_is_made_with_these_settings():
    assert JUDGE == {
        "model": "claude-sonnet-5-5",
        "max_tokens": 16000,
        "thinking": {"type": "adaptive"},
        "effort": "high",
        "max_retries": 2,
        "request_seconds": 600.0,
    }
    assert REPEATS == 3
    # They are the settings of the runs it grades, as far as it has them.
    assert all(EVALUATION["model"][name] == value for name, value in JUDGE.items())


def test_the_texts_name_no_paper_and_no_question():
    # An example in a prompt is a hint, and this prompt is used for every question.
    for text in (SYSTEM_PROMPT, MESSAGE, json.dumps(VERDICT_SCHEMA)):
        assert not re.search(r"\d{4}\.\d{4,5}", text)
        assert not re.search(r"\b(eval|dev)-\d", text)


def test_the_form_of_a_verdict_is_one_the_api_can_hold():
    assert VERDICT_SCHEMA["additionalProperties"] is False
    assert (
        set(VERDICT_SCHEMA["required"]) == set(VERDICT_SCHEMA["properties"]) == {"verdict", "why"}
    )
    assert VERDICT_SCHEMA["properties"]["verdict"]["enum"] == ["right", "wrong"]


# --- what a request shows ------------------------------------------------------------------


def test_a_request_shows_what_the_sheet_shows_and_nothing_else(tmp_path):
    (asked,) = load_questions(questions_file(tmp_path, "q1"))

    message = message_for(asked, Item("sheet-7", "q1", True, "It says\ntwo things."))

    assert message == (
        "<question>\nWhat does the paper say about q1?\n</question>\n\n"
        "<reference_answer>\nThe reference of q1.\n</reference_answer>\n\n"
        "<note>\nWhat is accepted for q1.\n</note>\n\n"
        '<answer found="true">\nIt says\ntwo things.\n</answer>\n'
    )
    # In particular: not the number of the row, the papers, the evidence or the answer key.
    for kept_back in ("sheet-7", PAPER, "anchor of q1", "the key of q1", "a note on q1", "2.1"):
        assert kept_back not in message


def test_found_is_shown_as_the_sheet_shows_it(tmp_path):
    (asked,) = load_questions(questions_file(tmp_path, "q1"))

    assert '<answer found="false">' in message_for(asked, Item("sheet-1", "q1", False, "No."))


# --- the answers to grade ------------------------------------------------------------------


def test_the_answers_of_a_sheet_are_read_in_its_order(tmp_path):
    rows = [row(2, "q1", " -1 is the value"), row(1, "q2", "The paper\ndoes not say.", "false")]

    assert sheet_items(sheet_file(tmp_path, rows)) == [
        # As the cell holds it: a text that begins like a formula has a space before it.
        Item("sheet-2", "q1", True, " -1 is the value"),
        Item("sheet-1", "q2", False, "The paper\ndoes not say."),
    ]


def test_the_grades_on_a_sheet_do_not_reach_the_judge(tmp_path):
    graded = [
        row(1, "q1", "first", grade="wrong", why_wrong="GRADERSWORD", note="GRADERSNOTE"),
        row(2, "q1", "second", grade="right", question="SHOWNONTHESHEET"),
    ]
    bare = ("number", "question_id", "found", "answer")
    with_grades = sheet_file(tmp_path, graded)
    without = sheet_file(tmp_path, graded, bare, "bare.csv")
    (asked,) = load_questions(questions_file(tmp_path, "q1"))

    items = sheet_items(with_grades)

    assert items == sheet_items(without)
    said = "".join(message_for(asked, item) for item in items) + repr(items)
    assert not re.search("GRADERS|SHOWNONTHESHEET|wrong|right", said)


def test_what_a_file_of_controls_says_of_them_does_not_reach_the_judge(tmp_path):
    made = [control("syn-1", "q1", "made one", kind="HOWMADE", detail="WHATISWRONG")]
    bare = ("id", "question_id", "found", "answer")
    (asked,) = load_questions(questions_file(tmp_path, "q1"))

    items = control_items(sheet_file(tmp_path, made, CONTROL_COLUMNS, "controls.csv"))

    assert items == control_items(sheet_file(tmp_path, made, bare, "bare.csv"))
    assert items == [Item("syn-1", "q1", True, "made one")]
    said = "".join(message_for(asked, item) for item in items) + repr(items)
    assert not re.search("HOWMADE|WHATISWRONG|wrong|a number", said)


def test_a_sheet_saved_by_a_spreadsheet_is_read(tmp_path):
    # A spreadsheet writes TRUE and FALSE, and leaves lines of empty cells behind.
    rows = [row(1, "q1", "first", "TRUE"), row(2, "q1", "second", "FALSE")]
    path = sheet_file(tmp_path, rows)
    path.write_text(path.read_text(encoding="utf-8-sig") + ",,,,,,,,,\n", encoding="utf-8-sig")

    assert [item.found for item in sheet_items(path)] == [True, False]


@pytest.mark.parametrize(
    ("change", "says"),
    [
        ({"number": "one"}, "is not a number"),
        ({"found": "perhaps"}, "neither true nor false"),
        ({"answer": "  "}, "no answer"),
    ],
)
def test_a_sheet_with_a_row_that_cannot_be_asked_is_refused(tmp_path, change, says):
    with pytest.raises(JudgeError, match=says):
        sheet_items(sheet_file(tmp_path, [row(1, "q1", "first") | change]))


def test_a_file_without_a_column_it_needs_is_refused(tmp_path):
    path = sheet_file(tmp_path, [row(1, "q1", "first")], ("number", "question_id", "answer"))

    with pytest.raises(JudgeError, match="no column found"):
        sheet_items(path)


@pytest.mark.parametrize("name", ["sheet-4", ""])
def test_a_control_cannot_have_the_id_of_a_row(tmp_path, name):
    path = sheet_file(tmp_path, [control(name, "q1", "made")], CONTROL_COLUMNS)

    with pytest.raises(JudgeError, match="cannot be the id of a control"):
        control_items(path)


def test_every_answer_is_there_once_and_its_question_is_known(tmp_path):
    questions = {asked.id: asked for asked in load_questions(questions_file(tmp_path, "q1"))}
    one, other = Item("sheet-1", "q1", True, "a"), Item("syn-1", "q1", True, "b")

    assert chosen([one, other], questions, None) == [one, other]
    assert chosen([one, other], questions, ["syn-1"]) == [other]
    with pytest.raises(JudgeError, match="sheet-1 is there twice"):
        chosen([one, one], questions, None)
    with pytest.raises(JudgeError, match="'q9' is not in the file"):
        chosen([Item("sheet-2", "q9", True, "c")], questions, None)
    with pytest.raises(JudgeError, match="--only names syn-9"):
        chosen([one, other], questions, ["syn-9"])


# --- one request ---------------------------------------------------------------------------


class Api:
    """Answers each request with the next prepared response, and keeps the requests."""

    def __init__(self, *responses: httpx2.Response) -> None:
        self._responses = list(responses)
        self.requests: list[dict] = []

    def __call__(self, request: httpx2.Request) -> httpx2.Response:
        self.requests.append(json.loads(request.content))
        return self._responses.pop(0)

    def judge(self) -> ClaudeJudge:
        client = anthropic.AsyncAnthropic(
            api_key="not-a-real-key",
            max_retries=0,
            http_client=httpx2.AsyncClient(transport=httpx2.MockTransport(self)),
        )
        return ClaudeJudge(client=client)


def api_message(text: str, stop_reason: str = "end_turn") -> dict:
    return {
        "id": "msg_01",
        "type": "message",
        "role": "assistant",
        "model": "claude-sonnet-5-5",
        "content": [
            {"type": "thinking", "thinking": "", "signature": "c2lnbmF0dXJl"},
            {"type": "text", "text": text},
        ],
        "stop_reason": stop_reason,
        "stop_sequence": None,
        "usage": {"input_tokens": 1200, "output_tokens": 340},
    }


@pytest.mark.anyio
async def test_a_request_holds_the_settings_of_the_judge_and_nothing_else():
    api = Api(httpx2.Response(200, json=api_message('{"verdict": "wrong", "why": "No value."}')))

    answer = await api.judge().ask(SYSTEM_PROMPT, "the request", VERDICT_SCHEMA)

    assert api.requests == [
        {
            "model": "claude-sonnet-5-5",
            "max_tokens": 16000,
            "system": SYSTEM_PROMPT,
            "messages": [{"role": "user", "content": "the request"}],
            "thinking": {"type": "adaptive"},
            "output_config": {
                "effort": "high",
                "format": {"type": "json_schema", "schema": VERDICT_SCHEMA},
            },
        }
    ]
    # In particular: no tools, no cache mark, and no sampling setting (the model takes none).
    assert (answer.stop_reason, answer.blocks) == ("end_turn", ("thinking", "text"))
    assert read_verdict(answer) == judge.Verdict("wrong", "No value.", None)
    assert answer.usage["output_tokens"] == 340


@pytest.mark.anyio
async def test_a_request_the_api_refuses_gives_no_reply():
    body = {"type": "error", "error": {"type": "overloaded_error", "message": "busy"}}
    api = Api(httpx2.Response(529, json=body))

    with pytest.raises(ModelError) as caught:
        await api.judge().ask(SYSTEM_PROMPT, "the request", VERDICT_SCHEMA)

    assert caught.value.status == 529


def test_the_record_names_the_settings_and_the_sdk():
    settings = ClaudeJudge(client=anthropic.AsyncAnthropic(api_key="not-a-real-key")).settings

    assert settings == {**JUDGE, "sdk": f"anthropic {anthropic.__version__}"}


# --- reading a reply -----------------------------------------------------------------------


@pytest.mark.parametrize(
    ("answer", "verdict"),
    [
        (reply("right", ""), "right"),
        (reply("wrong", "The second value is missing."), "wrong"),
        # The API may return a value of the form in other capitals than the form has.
        (reply("Right"), "right"),
        (reply("WRONG"), "wrong"),
    ],
)
def test_a_verdict_is_read_from_a_reply_of_the_form(answer, verdict):
    read = read_verdict(answer)

    assert (read.verdict, read.problem) == (verdict, None)
    assert read.why == json.loads(answer.text)["why"]


@pytest.mark.parametrize(
    ("answer", "problem"),
    [
        # A refusal or a text cut short is no verdict, whatever its text looks like.
        (reply(stop_reason="refusal"), "stopped with refusal"),
        (reply(stop_reason="max_tokens"), "stopped with max_tokens"),
        (reply(text="The answer is right."), "not JSON"),
        (reply(text='["right", "why"]'), "two fields"),
        (reply(text='{"verdict": "right"}'), "two fields"),
        (reply(text='{"verdict": "right", "why": "", "score": 1}'), "two fields"),
        (reply(text='{"verdict": "partly", "why": ""}'), "'partly'"),
        (reply(text='{"verdict": true, "why": ""}'), "True"),
        (reply(text='{"verdict": "right", "why": 3}'), "why is not a text"),
    ],
)
def test_a_reply_that_is_no_verdict_is_not_read_as_one(answer, problem):
    read = read_verdict(answer)

    assert read.verdict is None
    assert problem in read.problem


@pytest.mark.parametrize(
    ("verdicts", "repeats", "verdict"),
    [
        (["right", "right", "right"], 3, "right"),
        (["right", "wrong", "right"], 3, "right"),
        (["wrong", "wrong", "right"], 3, "wrong"),
        # A reply without a verdict is a request that did not say "right": two of three
        # are needed, and one of each is no verdict on the answer.
        (["right", None, "right"], 3, "right"),
        (["right", None, "wrong"], 3, None),
        (["right", None, None], 3, None),
        (["right"], 3, None),
        ([], 3, None),
        (["wrong"], 1, "wrong"),
        (["right", "wrong"], 2, None),
    ],
)
def test_the_verdict_on_an_answer_is_what_more_than_half_of_its_requests_gave(
    verdicts, repeats, verdict
):
    assert verdict_of(verdicts, repeats) == verdict


# --- the runner and its record -------------------------------------------------------------


def test_every_answer_is_asked_three_times_in_passes_over_all_of_them(given, capsys):
    scripted = Scripted()

    assert judge.main(given["argv"], scripted) == 0

    order = ["first", "second", "third", "made one", "made two"]
    assert answers_in(scripted.asked) == order * 3
    assert scripted.systems == {SYSTEM_PROMPT}
    assert all(schema == VERDICT_SCHEMA for schema in scripted.schemas)
    assert "5 answer(s), 15 request(s): 0 done, 15 to ask" in capsys.readouterr().out


def test_the_record_says_what_the_judge_was_and_what_it_was_given(given):
    scripted = Scripted(lambda message: reply("wrong" if "made" in message else "right", "Why."))

    assert judge.main(given["argv"], scripted) == 0

    head, lines, end = read_record(given["out"])
    assert head.pop("started_at").endswith("+00:00")
    assert head == {
        "record": "judge",
        "judge_version": JUDGE_VERSION,
        "texts_sha256": texts_digest(),
        "settings": {"model": "scripted"},
        "repeats": 3,
        "code": {"commit": "c0ffee", "modified": False},
        "questions": {"file": "questions.jsonl", "sha256": file_digest(given["questions"])},
        "sheet": {"file": "sheet.csv", "sha256": file_digest(given["sheet"]), "answers": 3},
        "controls": {
            "file": "controls.csv",
            "sha256": file_digest(given["controls"]),
            "answers": 2,
        },
        "only": None,
    }
    assert [(line["item"], line["repeat"]) for line in lines[:6]] == [
        ("sheet-1", 1),
        ("sheet-2", 1),
        ("sheet-3", 1),
        ("syn-1", 1),
        ("syn-2", 1),
        ("sheet-1", 2),
    ]
    seconds = lines[3].pop("seconds")
    assert seconds >= 0
    assert lines[3] == {
        "record": "verdict",
        "item": "syn-1",
        "question_id": "q1",
        "repeat": 1,
        "verdict": "wrong",
        "why": "Why.",
        "stop_reason": "end_turn",
        "blocks": ["thinking", "text"],
        "usage": {"input_tokens": 1000, "output_tokens": 500},
        "model": "claude-sonnet-5-5",
    }
    assert end == {
        "record": "end",
        "requests": 15,
        "verdicts": {"right": 9, "wrong": 6, "none": 0},
        "failed": 0,
        "usage": {"input_tokens": 15000, "output_tokens": 7500},
        # 15 requests of 1000 tokens in at $2 and 500 out at $10 a million.
        "cost": pytest.approx(15 * (1000 * 2 + 500 * 10) / 1e6),
    }


def test_a_record_holds_no_answer_and_no_question(given):
    # It names the rows and the controls. Their texts are in the files it names.
    assert judge.main(given["argv"], Scripted()) == 0

    text = given["out"].read_text(encoding="utf-8")
    assert not re.search(r"first|\bsecond\b|third|made one|What does the paper|reference of", text)


def test_started_again_it_asks_only_what_the_api_failed(given, capsys):
    failing = {"second": 1}  # the first request for this answer finds the API busy

    def answer(message: str):
        for text, left in failing.items():
            if text in message and left:
                failing[text] = left - 1
                return ModelError("OverloadedError", "busy", 529)
        return reply()

    first = Scripted(answer)
    assert judge.main(given["argv"], first) == 1
    assert "1 request(s) got no reply from the API: start the command again" in (
        capsys.readouterr().err
    )
    head, lines, end = read_record(given["out"])
    assert end is None
    assert [line["record"] for line in lines].count("failed") == 1
    assert len(first.asked) == 15

    again = Scripted()
    assert judge.main(given["argv"], again) == 0

    assert answers_in(again.asked) == ["second"]
    assert "15 request(s): 14 done, 1 to ask" in capsys.readouterr().out
    _, lines, end = read_record(given["out"])
    assert (end["requests"], end["failed"]) == (15, 1)
    asked = [(line["item"], line["repeat"]) for line in lines if line["record"] == "verdict"]
    assert len(asked) == len(set(asked)) == 15
    assert read_record(given["out"])[0] == head  # the first line is written once


def test_a_finished_record_is_not_asked_again(given, capsys):
    assert judge.main(given["argv"], Scripted()) == 0
    before = given["out"].read_bytes()
    capsys.readouterr()

    again = Scripted()
    assert judge.main(given["argv"], again) == 0

    assert again.asked == []
    assert given["out"].read_bytes() == before
    out = capsys.readouterr().out
    assert "15 request(s): 15 done, 0 to ask" in out
    assert "sheet: 3 answer(s); by more than half of 3 request(s): 3 right, 0 wrong" in out


@pytest.mark.parametrize(
    ("change", "differing"),
    [
        (lambda given: sheet_file(given["sheet"].parent, [row(1, "q1", "another")]), "sheet"),
        (lambda given: given["argv"].extend(["--repeats", "2"]), "repeats"),
        (lambda given: given["argv"].extend(["--only", "sheet-1"]), "only"),
        (
            lambda given: given["questions"].write_bytes(given["questions"].read_bytes() + b"\n"),
            "questions",
        ),
    ],
)
def test_a_record_begun_with_something_else_is_refused(given, capsys, change, differing):
    assert judge.main(given["argv"], Scripted()) == 0
    before = given["out"].read_bytes()
    change(given)

    again = Scripted()
    assert judge.main(given["argv"], again) == 1

    assert f"was begun with something else ({differing})" in capsys.readouterr().err
    assert again.asked == []
    assert given["out"].read_bytes() == before


def test_a_record_begun_by_other_code_or_another_judge_is_refused(given, capsys, monkeypatch):
    assert judge.main(given["argv"], Scripted()) == 0
    monkeypatch.setattr(judge, "code_version", lambda: {"commit": "decaf", "modified": False})
    monkeypatch.setattr(judge, "JUDGE_VERSION", "j2")

    assert judge.main(given["argv"], Scripted()) == 1

    assert "(code, judge_version)" in capsys.readouterr().err


def test_a_reply_that_is_no_verdict_is_kept_and_not_asked_again(given):
    def answer(message: str):
        if "third" in message:
            return reply(stop_reason="refusal", text="I cannot grade this.")
        return reply()

    scripted = Scripted(answer)
    assert judge.main(given["argv"], scripted) == 0

    _, lines, end = read_record(given["out"])
    kept = [line for line in lines if line["item"] == "sheet-3"]
    assert [(line["verdict"], line["stop_reason"]) for line in kept] == [(None, "refusal")] * 3
    assert kept[0]["problem"] == "the reply stopped with refusal"
    assert kept[0]["text"] == "I cannot grade this."
    assert end["verdicts"] == {"right": 12, "wrong": 0, "none": 3}
    assert len(scripted.asked) == 15

    again = Scripted()
    assert judge.main(given["argv"], again) == 0
    assert again.asked == []


@pytest.mark.parametrize(
    "error",
    [
        ModelError("AuthenticationError", "invalid x-api-key", 401),
        ModelError("BadRequestError", "Your credit balance is too low", 400),
        ModelError("APIStatusError", "Error code: 402", 402),
    ],
)
def test_it_stops_at_once_when_the_api_refuses_for_good(given, capsys, error):
    scripted = Scripted(lambda message: error)

    assert judge.main(given["argv"], scripted) == 1

    assert len(scripted.asked) == 1
    assert "stopped: the API refuses" in capsys.readouterr().err
    assert read_record(given["out"])[2] is None


def test_it_stops_after_three_requests_in_a_row_that_the_api_failed(given, capsys):
    calls = []

    def answer(message: str):
        calls.append(message)
        # One failure, a reply, then failures only: the count starts again after a reply.
        return reply() if len(calls) == 2 else ModelError("APITimeoutError", "timed out")

    assert judge.main(given["argv"], Scripted(answer)) == 1

    assert len(calls) == 5
    assert "stopped: the API failed 3 requests in a row" in capsys.readouterr().err


def test_changed_code_is_refused_before_anything_is_asked(given, capsys, monkeypatch):
    monkeypatch.setattr(judge, "code_version", lambda: {"commit": "c0ffee", "modified": True})
    scripted = Scripted()

    assert judge.main(given["argv"], scripted) == 1

    assert "changes that are not committed" in capsys.readouterr().err
    assert scripted.asked == []
    assert not given["out"].exists()


def test_a_plan_asks_nothing_and_writes_nothing(given, capsys):
    scripted = Scripted()

    assert judge.main([*given["argv"], "--plan"], scripted) == 0

    assert "5 answer(s), 15 request(s): 0 done, 15 to ask" in capsys.readouterr().out
    assert scripted.asked == []
    assert not given["out"].exists()


def test_only_asks_the_answers_named(given):
    scripted = Scripted()

    assert (
        judge.main([*given["argv"], "--only", "syn-2", "sheet-1", "--repeats", "1"], scripted) == 0
    )

    assert answers_in(scripted.asked) == ["first", "made two"]
    assert read_record(given["out"])[0]["only"] == ["sheet-1", "syn-2"]


def test_without_a_key_the_command_does_not_start(given, capsys, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    assert judge.main(given["argv"]) == 2

    assert "ANTHROPIC_API_KEY is not set" in capsys.readouterr().err
    assert not given["out"].exists()


@pytest.mark.parametrize(
    ("argv", "says"),
    [
        (["--questions", "{questions}", "--out", "{out}"], "nothing to grade"),
        (["--questions", "{questions}", "--sheet", "nowhere.csv", "--out", "{out}"], "refused"),
        (["--questions", "nowhere.jsonl", "--sheet", "{sheet}", "--out", "{out}"], "refused"),
    ],
)
def test_it_refuses_arguments_it_cannot_start_with(given, capsys, argv, says):
    argv = [text.format(**given) for text in argv]

    assert judge.main(argv, Scripted()) == 2
    assert says in capsys.readouterr().err


def test_several_requests_at_a_time_ask_everything_once(given):
    import asyncio

    running, most = 0, 0

    class Slow(Scripted):
        async def ask(self, system: str, message: str, schema: dict) -> Reply:
            nonlocal running, most
            running += 1
            most = max(most, running)
            await asyncio.sleep(0.01)
            running -= 1
            return await super().ask(system, message, schema)

    slow = Slow()
    assert judge.main([*given["argv"], "--parallel", "4"], slow) == 0

    assert sorted(answers_in(slow.asked)) == sorted(
        ["first", "second", "third", "made one", "made two"] * 3
    )
    assert most == 4
    _, lines, end = read_record(given["out"])
    asked = [(line["item"], line["repeat"]) for line in lines]
    assert len(set(asked)) == 15 and end["requests"] == 15


def test_the_summary_lists_and_does_not_compare():
    items = [
        Item("sheet-1", "q1", True, "a"),
        Item("sheet-2", "q1", True, "b"),
        Item("syn-1", "q1", True, "c"),
        Item("syn-2", "q1", True, "d"),
    ]
    said = {
        "sheet-1": ["right", "right", "right"],
        "sheet-2": ["wrong", "right", "wrong"],
        "syn-1": ["wrong", "wrong", "wrong"],
        "syn-2": ["right", None, "right"],
    }
    lines = [
        {"record": "verdict", "item": name, "repeat": at, "verdict": verdict}
        for name, verdicts in said.items()
        for at, verdict in enumerate(verdicts, start=1)
    ]
    lines.append({"record": "failed", "item": "syn-1", "repeat": 1, "error": {}})

    assert summary(lines, items, 3) == [
        "12 request(s) with a reply: 6 right, 5 wrong, 1 without a verdict",
        "sheet: 2 answer(s); by more than half of 3 request(s): 1 right, 1 wrong, "
        "0 without a verdict",
        "  wrong: sheet-2",
        "  not the same in every request: sheet-2",
        "controls: 2 answer(s); by more than half of 3 request(s): 1 right, 1 wrong, "
        "0 without a verdict",
        "  right: syn-2",
        "  not the same in every request: syn-2",
    ]


# --- what the repository holds for the judge -----------------------------------------------

DEV_QUESTIONS = ROOT / "eval_data" / "questions_dev.jsonl"
DEV_RUNS = ROOT / "results" / "runs" / "dev" / "diag-3-tool"
DEV_SHEET = ROOT / "results" / "judge" / "dev-sheet.csv"
DEV_KEY = ROOT / "results" / "judge" / "dev-sheet-key.csv"
DEV_CONTROLS = ROOT / "eval_data" / "judge_controls_dev.csv"
DEV_SEED = 20261119
# The ways a control is wrong, as the files of controls name them.
WAYS = {
    "다른 것을 답함",
    "요소 빠짐",
    "숫자 틀림",
    "뒤바꿔 답함",
    "없는 것을 지어냄",
    "있는데 없다고 함",
    "found 표시 틀림",
}


def _table(path: Path) -> list[dict]:
    with path.open(encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def test_the_development_sheet_is_the_one_the_sheet_command_writes(tmp_path):
    # The judge is tried on the thirty answers that the conditions were fixed with. Their
    # sheet was written with `eval.sheet --seed`; nobody graded it, and its grades are empty.
    questions = load_questions(DEV_QUESTIONS)
    attempts, _ = counted_attempts(questions, DEV_RUNS, file_digest(DEV_QUESTIONS))
    rows = rows_of(questions, attempts, DEV_SEED)
    write_sheet(rows, tmp_path / "sheet.csv")
    write_key(rows, tmp_path / "key.csv")

    sheet = _table(DEV_SHEET)

    assert len(sheet) == 30
    assert sheet == _table(tmp_path / "sheet.csv")
    assert _table(DEV_KEY) == _table(tmp_path / "key.csv")
    assert all((line["grade"], line["why_wrong"], line["note"]) == ("", "", "") for line in sheet)


def test_the_development_controls_fit_their_questions_and_their_sheet():
    known = {asked.id for asked in load_questions(DEV_QUESTIONS)}
    sheet = {line["number"]: line for line in _table(DEV_SHEET)}
    controls = _table(DEV_CONTROLS)

    assert [item.id for item in control_items(DEV_CONTROLS)] == [line["id"] for line in controls]
    assert len({line["id"] for line in controls}) == len(controls) > 0
    assert {line["question_id"] for line in controls} == known
    for line in controls:
        assert re.fullmatch(r"dsyn-\d\d-\d\d", line["id"])
        assert line["question_id"] == f"dev-{line['id'][5:7]}"
        assert line["grade"] == "wrong"
        assert line["kind"] in ("accept_note 오답 조건", "임의 오답")
        assert line["why_wrong"] in WAYS
        assert line["detail"] and line["invented_content"] in ("yes", "no")
        if line["base_number"]:
            # Made from a real answer to the same question, and not that answer itself.
            base = sheet[line["base_number"]]
            assert base["question_id"] == line["question_id"]
            assert (base["answer"], base["found"]) != (line["answer"], line["found"])
