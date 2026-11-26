"""The generator: what it reads, the form of a draft, a request, and the command's record.

No network and no LLM. The API is the real SDK over a transport that answers from
memory, and the command is given a model that answers from a script.
"""

import hashlib
import json
import re
from pathlib import Path

import anthropic
import httpx2
import pytest
from drafting_paper import (
    ID,
    TITLE,
    Scripted,
    as_reply,
    draft,
    later_draft,
    nothing,
    paper,
    placed,
    reply_of,
    source,
)

from hepph_paper_miner.agent.model import ModelError
from hepph_paper_miner.drafting import ask, assign
from hepph_paper_miner.drafting import draft as drafting
from hepph_paper_miner.drafting.draft import (
    DRAFT,
    DRAFT_SCHEMA,
    DRAFTER_VERSION,
    DRAFTING,
    MAX_DRAFTS,
    MESSAGE,
    NO_DRAFT,
    NOTHING,
    SYSTEM_PROMPT,
    Draft,
    drafts_in,
    fill_paper,
    key_of,
    line_of,
    message_for,
    read_draft,
    texts_digest,
)
from hepph_paper_miner.drafting.places import KINDS, SEARCH_FIRST
from hepph_paper_miner.eval.judge import JUDGE
from hepph_paper_miner.eval.judge import SYSTEM_PROMPT as JUDGE_PROMPT
from hepph_paper_miner.eval.questions import _question
from hepph_paper_miner.server import full_text

ROOT = Path(__file__).parent.parent
# The name of the texts the generator reads, and the digest of those texts.
PINNED = ("d2", "525e9c906a59ebc49d1079bcf4d59726db02cd38bada1f3d3058d8ee78ccf387")


# --- the texts the generator reads ---------------------------------------------------------


def test_the_texts_are_the_ones_this_version_names():
    # The generator reads these texts, so a change to them is another generator. When this
    # fails: raise DRAFTER_VERSION (drafting/draft.py), then put the new name and digest here.
    texts = [SYSTEM_PROMPT, MESSAGE, DRAFT_SCHEMA]
    digest = hashlib.sha256(json.dumps(texts).encode("utf-8")).hexdigest()
    assert (DRAFTER_VERSION, digest) == PINNED, digest
    assert texts_digest() == digest


def test_the_generator_asks_as_the_judge_does_but_sees_its_thinking():
    assert DRAFTING == {
        "model": "claude-sonnet-5-5",
        "max_tokens": 16000,
        "thinking": {"type": "adaptive", "display": "summarized"},
        "effort": "high",
        "max_retries": 2,
        "request_seconds": 600.0,
    }
    # Everything but the thinking is the judge's, so the two cannot drift apart unnoticed.
    assert {k: v for k, v in DRAFTING.items() if k != "thinking"} == {
        k: v for k, v in JUDGE.items() if k != "thinking"
    }


def test_the_last_line_of_the_prompt_is_the_judges():
    # The sentence the API documentation gives to encourage thinking, word for word.
    last = "This task involves multistep reasoning. Think carefully before responding.\n"
    assert SYSTEM_PROMPT.endswith(last) and JUDGE_PROMPT.endswith(last)


def test_the_texts_name_no_paper_and_no_kind():
    for text in (SYSTEM_PROMPT, MESSAGE, json.dumps(DRAFT_SCHEMA)):
        assert not re.search(r"\d{4}\.\d{4,5}", text)
        # The name of a kind would find its way into a question. ("appendix" stands in the
        # prompt as a word a question must not use.)
        assert not any(kind in text for kind in KINDS if kind != "appendix")
    assert not any(kind in MESSAGE for kind in KINDS)


# Words of JSON Schema that the API does not take in a form (the structured outputs page,
# read 2026-11-26): a form that holds one is refused with status 400.
UNSUPPORTED = {
    "minLength",
    "maxLength",
    "minimum",
    "maximum",
    "exclusiveMinimum",
    "exclusiveMaximum",
    "multipleOf",
    "oneOf",
    "maxItems",
}


def objects_of(schema: dict):
    yield schema
    for value in schema.values():
        if isinstance(value, dict):
            yield from objects_of(value)


def test_the_form_of_a_draft_is_one_the_api_can_hold():
    objects = [part for part in objects_of(DRAFT_SCHEMA) if part.get("type") == "object"]
    for part in objects_of(DRAFT_SCHEMA):
        assert not UNSUPPORTED & set(part), part
        assert part.get("minItems", 0) in (0, 1)
        if part.get("type") == "object":
            # Every field is required, so that the order of the work is the order written.
            assert part["additionalProperties"] is False
            assert part["required"] == list(part["properties"])
    # The reply, a draft, an item of numbers and an item of phrases: every object is seen.
    assert len(objects) == 4
    assert list(DRAFT_SCHEMA["properties"]) == ["nothing_to_ask", "why_nothing", "drafts"]
    assert list(DRAFT_SCHEMA["properties"]["drafts"]["items"]["properties"]) == [
        "anchor",
        "question",
        "reference_answer",
        "numbers",
        "phrases",
        "accept_note",
    ]
    # A list cannot be held to a length by the form: the reader keeps to three.
    assert MAX_DRAFTS == 3 and "three" in DRAFT_SCHEMA["properties"]["drafts"]["description"]


def test_the_prompt_asks_for_up_to_as_many_drafts_as_are_read():
    assert "Write up to three drafts, each about another fact of the part, the best first" in (
        SYSTEM_PROMPT
    )
    assert 'leave "drafts" empty' in SYSTEM_PROMPT


# --- what a request holds -------------------------------------------------------------------


def test_a_request_holds_the_whole_paper_and_then_the_part():
    place = placed("2.2", "later_piece")
    message = message_for(paper(), place)
    whole = full_text(paper())
    assert f"<paper>\nTitle: {TITLE}\nAuthors: Ada Alpha, Ben Beta\n" in message
    assert whole in message  # not cut, and with its marker lines
    section = next(s for s in paper().sections if s.section_id == "2.2")
    part = section.text[place.start : place.end]
    assert message.endswith(
        f"<part>\nSection: 2.2 | Long run\nCharacters {place.start} to {place.end} of "
        f"{section.chars}\n\n{part}\n</part>\n"
    )
    assert "later_piece" not in message and "later" not in message.split("<part>")[1][:80]


@pytest.mark.anyio
async def test_a_request_holds_the_settings_and_asks_for_the_summary():
    sent = []

    def api(request):
        sent.append(json.loads(request.content))
        return httpx2.Response(
            200,
            json={
                "id": "msg_01",
                "type": "message",
                "role": "assistant",
                "model": "claude-sonnet-5-5",
                "content": [
                    {
                        "type": "thinking",
                        "thinking": "The part gives an area.",
                        "signature": "c2ln",
                    },
                    {"type": "text", "text": json.dumps(as_reply(draft()))},
                ],
                "stop_reason": "end_turn",
                "stop_sequence": None,
                "usage": {"input_tokens": 9000, "output_tokens": 700},
            },
        )

    client = anthropic.AsyncAnthropic(
        api_key="not-a-real-key",
        max_retries=0,
        http_client=httpx2.AsyncClient(transport=httpx2.MockTransport(api)),
    )
    reply = await ask.ClaudeAsker(DRAFTING, client=client).ask(
        SYSTEM_PROMPT, "the request", DRAFT_SCHEMA
    )
    assert sent == [
        {
            "model": "claude-sonnet-5-5",
            "max_tokens": 16000,
            "system": SYSTEM_PROMPT,
            "messages": [{"role": "user", "content": "the request"}],
            "thinking": {"type": "adaptive", "display": "summarized"},
            "output_config": {
                "effort": "high",
                "format": {"type": "json_schema", "schema": DRAFT_SCHEMA},
            },
        }
    ]
    assert ask.thoughts(reply) == ["The part gives an area."]
    assert read_draft(reply).outcome == DRAFT


@pytest.mark.anyio
async def test_a_request_the_api_refuses_gives_no_reply():
    def api(request):
        body = {"type": "error", "error": {"type": "overloaded_error", "message": "busy"}}
        return httpx2.Response(529, json=body)

    client = anthropic.AsyncAnthropic(
        api_key="not-a-real-key",
        max_retries=0,
        http_client=httpx2.AsyncClient(transport=httpx2.MockTransport(api)),
    )
    with pytest.raises(ModelError) as caught:
        await ask.ClaudeAsker(DRAFTING, client=client).ask("s", "m", DRAFT_SCHEMA)
    assert caught.value.status == 529


# --- reading a draft ------------------------------------------------------------------------


def test_a_draft_is_read_from_a_reply_of_the_form():
    read = read_draft(reply_of(as_reply(draft())))
    assert read.outcome == DRAFT and read.problem is None and read.left_out == 0
    assert read.drafts == (Draft.from_dict(draft()),)
    assert read.drafts[0].as_dict() == draft()


def test_up_to_three_drafts_are_read_in_their_order_and_more_are_left_out():
    first, second, third = draft(), later_draft(), draft(question="In {paper}, how big?")
    read = read_draft(reply_of(as_reply(first, second, third)))
    assert [each.as_dict() for each in read.drafts] == [first, second, third]
    fourth = draft(question="In {paper}, how wide?")
    read = read_draft(reply_of(as_reply(first, second, third, fourth, fourth)))
    assert [each.as_dict() for each in read.drafts] == [first, second, third]
    assert (read.outcome, read.left_out) == (DRAFT, 2)
    # A draft past the third is not read, so its form does not matter.
    read = read_draft(reply_of(as_reply(first, second, third, {"question": "q"})))
    assert (read.outcome, len(read.drafts), read.left_out) == (DRAFT, 3, 1)


def test_nothing_to_ask_is_read_with_its_reason():
    read = read_draft(reply_of(nothing("Only a list of names.")))
    assert (read.outcome, read.drafts, read.why_nothing) == (NOTHING, (), "Only a list of names.")
    # Drafts beside "nothing to ask" are not read: the reply says there is nothing.
    said = {**as_reply(draft()), "nothing_to_ask": True, "why_nothing": "Only a list."}
    assert read_draft(reply_of(said)).outcome == NOTHING


@pytest.mark.parametrize(
    ("reply", "problem"),
    [
        (reply_of(as_reply(draft()), stop="max_tokens"), "the reply stopped with max_tokens"),
        (reply_of(as_reply(draft()), stop="refusal"), "the reply stopped with refusal"),
        (reply_of({"question": "q"}), "the reply does not have the fields of the form"),
        (reply_of(draft()), "the reply does not have the fields of the form"),  # d1's form
        (
            reply_of({**as_reply(draft()), "nothing_to_ask": "no"}),
            "a field of the reply is not of its kind",
        ),
        (
            reply_of({**as_reply(draft()), "why_nothing": None}),
            "a field of the reply is not of its kind",
        ),
        (
            reply_of({**as_reply(draft()), "drafts": draft()}),
            "a field of the reply is not of its kind",
        ),
        (reply_of(as_reply()), "the reply has no draft"),
        (reply_of(as_reply(draft(), ["a list"])), "a draft does not have the fields of a draft"),
        (
            reply_of(as_reply({**draft(), "kind": "x"})),
            "a draft does not have the fields of a draft",
        ),
        (reply_of(as_reply(draft(question=7))), "a field of a draft is not of its kind"),
        (reply_of(as_reply(draft(numbers={}))), "numbers or phrases is not a list"),
        (
            reply_of(
                as_reply(
                    draft(numbers=[{"label": "a", "value": "37.2", "unit": "", "min_sig_figs": 3}])
                )
            ),
            "an item of numbers is not of the form",
        ),
        (
            reply_of(
                as_reply(
                    draft(numbers=[{"label": "a", "value": 37.2, "unit": "", "min_sig_figs": True}])
                )
            ),
            "an item of numbers is not of the form",
        ),
        (
            reply_of(as_reply(draft(phrases=[{"label": "a", "any_of": "x"}]))),
            "an item of phrases is not of the form",
        ),
        # One draft that is not of the form makes the whole reply no draft, a good one too.
        (
            reply_of(as_reply(draft(), draft(phrases=[{"label": "a", "any_of": "x"}]))),
            "an item of phrases is not of the form",
        ),
    ],
)
def test_a_reply_that_is_no_draft_is_not_read_as_one(reply, problem):
    read = read_draft(reply)
    assert (read.outcome, read.drafts, read.problem) == (NO_DRAFT, (), problem)


def test_the_drafts_of_a_line_are_read_from_a_record_of_d1_as_well():
    assert drafts_in({"outcome": "draft", "drafts": [draft(), later_draft()]}) == [
        draft(),
        later_draft(),
    ]
    assert drafts_in({"outcome": "nothing_to_ask", "drafts": []}) == []
    # d1 wrote its one draft under "draft", and None where there was none.
    assert drafts_in({"outcome": "draft", "draft": draft()}) == [draft()]
    assert drafts_in({"outcome": "no_draft", "draft": None}) == []


def test_a_text_that_is_no_json_is_no_draft():
    reply = reply_of(as_reply(draft()))
    broken = type(reply)(**{**reply.__dict__, "text": "{not json"})
    assert read_draft(broken).problem == "the reply is not JSON"


# --- from a draft to a question -------------------------------------------------------------


def test_the_paper_is_named_by_its_identifier_or_by_its_title():
    assert fill_paper("{paper} fits a slope: what is it?", "named_first", ID, TITLE) == (
        f"arXiv:{ID} fits a slope: what is it?"
    )
    # The identifier keeps its spelling at the head of a sentence, the title form does not.
    assert fill_paper("{paper} fits a slope.", SEARCH_FIRST, ID, TITLE) == (
        f'The paper titled "{TITLE}" fits a slope.'
    )
    assert fill_paper("In {paper}, what?", SEARCH_FIRST, ID, TITLE) == (
        f'In the paper titled "{TITLE}", what?'
    )


def test_a_draft_becomes_a_line_of_a_question_file():
    found = Draft.from_dict(draft(phrases=[{"label": "unit", "any_of": ["square metres"]}]))
    place = placed("2.1")
    line = line_of(found, place, place.kind, TITLE, "the anchor", "arch-01")
    question = _question(line, "a test")
    assert question.question == f"In arXiv:{ID}, what is the total area of the detector?"
    assert question.gold_papers == (ID,) and question.expect_found is True
    assert [(e.section_id, e.anchor) for e in question.evidence] == [("2.1", "the anchor")]
    assert question.answer_key == {
        "numbers": [{"label": "area", "value": 37.2, "unit": "square metres", "min_sig_figs": 3}],
        "phrases": [{"label": "unit", "any_of": ["square metres"]}],
    }
    assert question.type == place.kind and question.notes["drafted"] == DRAFTER_VERSION


def test_an_empty_unit_is_left_out_of_the_key():
    found = Draft.from_dict(
        draft(numbers=[{"label": "n", "value": 4096, "unit": " ", "min_sig_figs": 4}])
    )
    assert key_of(found) == {"numbers": [{"label": "n", "value": 4096, "min_sig_figs": 4}]}


# --- the command ----------------------------------------------------------------------------


@pytest.fixture
def committed_code(monkeypatch):
    # The commands name the commit they run from and refuse changed code. Under test the
    # code is whatever is being worked on.
    monkeypatch.setattr(ask, "code_version", lambda: {"commit": "c0ffee", "modified": False})
    monkeypatch.setattr(assign, "code_version", lambda: {"commit": "c0ffee", "modified": False})


@pytest.fixture
def places(tmp_path, committed_code) -> Path:
    """The places of a round of the tuning that holds the invented paper alone."""
    target = tmp_path / "targets.txt"
    target.write_text(f"# the papers\n{ID}\n", encoding="utf-8")
    out = tmp_path / "places.jsonl"
    argv = [
        "--tuning",
        str(target),
        "--round",
        "1",
        "--plan",
        str(ROOT / "eval_data/survey_plan.json"),
    ]
    assert assign.main([*argv, "--out", str(out)], source=source()) == 0
    return out


def answers(system, message, schema):
    # The places of the round: the later piece of 2.2, the appendix, the own text of 2,
    # and one named_first place (which one, the hash decides).
    part = re.search(r"<part>\nSection: (\S+) \| [^\n]*\nCharacters (\d+)", message)
    if part[1] == "2.2" and part[2] != "0":
        return reply_of(as_reply(later_draft(), SECOND), thinking="A coupling is stated once.")
    if part[1] == "A":
        return reply_of(nothing(), thinking="Only a cutoff.")
    return reply_of(as_reply(draft()), stop="max_tokens")


SECOND = later_draft(question="In {paper}, what is the coupling fixed to at the reference scale?")


def test_the_command_drafts_every_place_and_writes_its_record(places, tmp_path, capsys):
    out = tmp_path / "drafts.jsonl"
    model = Scripted(answers)
    assert (
        drafting.main(["--places", str(places), "--out", str(out)], asker=model, source=source())
        == 0
    )
    lines = [json.loads(line) for line in out.read_text(encoding="utf-8").splitlines()]
    head, *replies, end = lines
    assert head["record"] == "drafts" and head["drafter_version"] == DRAFTER_VERSION
    assert head["texts_sha256"] == texts_digest() and head["code"]["commit"] == "c0ffee"
    assert head["places"]["sha256"] == hashlib.sha256(places.read_bytes()).hexdigest()
    outcomes = [line["outcome"] for line in replies]
    assert len(replies) == len(model.asked) == 4  # one place of each kind of the paper
    assert [line["kind"] for line in replies] == [
        "later_piece",
        "appendix",
        "own_text",
        "named_first",
    ]
    assert outcomes.count(DRAFT) == 1 and outcomes.count(NOTHING) == 1
    drafted = next(line for line in replies if line["outcome"] == DRAFT)
    assert drafted["drafts"] == [later_draft(), SECOND] and "left_out" not in drafted
    assert drafted["thinking"] == ["A coupling is stated once."]
    cut = [line for line in replies if line["outcome"] == NO_DRAFT]
    assert all(line["problem"] == "the reply stopped with max_tokens" for line in cut)
    assert all(line["drafts"] == [] for line in replies if line["outcome"] != DRAFT)
    assert end["record"] == "end" and end["outcomes"] == {DRAFT: 1, NOTHING: 1, NO_DRAFT: 2}
    assert (end["drafts"], end["left_out"]) == (2, 0)
    said = capsys.readouterr().out
    assert "4 reply(ies): draft 1, nothing_to_ask 1, no_draft 2; 2 draft(s)" in said
    assert "left out" not in said


def test_drafts_past_the_third_are_left_out_and_counted(places, tmp_path, capsys):
    out = tmp_path / "drafts.jsonl"

    def many(system, message, schema):
        return reply_of(as_reply(*(draft(question=f"In {{paper}}, what {n}?") for n in range(5))))

    argv = ["--places", str(places), "--out", str(out)]
    assert drafting.main(argv, asker=Scripted(many), source=source()) == 0
    head, *replies, end = [json.loads(line) for line in out.read_text().splitlines()]
    assert all(len(line["drafts"]) == MAX_DRAFTS and line["left_out"] == 2 for line in replies)
    assert [each["question"] for each in replies[0]["drafts"]] == [
        "In {paper}, what 0?",
        "In {paper}, what 1?",
        "In {paper}, what 2?",
    ]
    assert (end["drafts"], end["left_out"]) == (12, 8)
    assert "left out, past 3 drafts of a reply: 8" in capsys.readouterr().out


def test_started_again_it_asks_only_what_the_api_failed(places, tmp_path, capsys):
    out = tmp_path / "drafts.jsonl"
    calls = []

    def flaky(system, message, schema):
        calls.append(1)
        if len(calls) == 2:
            return ModelError("APITimeoutError", "timed out", None)
        return answers(system, message, schema)

    argv = ["--places", str(places), "--out", str(out)]
    assert drafting.main(argv, asker=Scripted(flaky), source=source()) == 1
    assert "1 request(s) got no reply from the API" in capsys.readouterr().err
    again = Scripted(answers)
    assert drafting.main(argv, asker=again, source=source()) == 0
    assert len(again.asked) == 1
    lines = [json.loads(line) for line in out.read_text(encoding="utf-8").splitlines()]
    assert [line["record"] for line in lines].count("reply") == 4
    # A finished record is not asked again.
    assert drafting.main(argv, asker=Scripted(answers), source=source()) == 0


def test_it_stops_at_once_when_the_api_refuses_for_good(places, tmp_path, capsys):
    out = tmp_path / "drafts.jsonl"
    refused = Scripted(lambda *_: ModelError("PermissionDeniedError", "no", 403))
    assert (
        drafting.main(["--places", str(places), "--out", str(out)], asker=refused, source=source())
        == 1
    )
    assert len(refused.asked) == 1
    assert "stopped: the API refuses" in capsys.readouterr().err


def test_a_record_begun_with_other_places_is_refused(places, tmp_path, capsys):
    out = tmp_path / "drafts.jsonl"
    argv = ["--places", str(places), "--out", str(out)]
    assert drafting.main(argv, asker=Scripted(answers), source=source()) == 0
    places.write_text(places.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    assert drafting.main(argv, asker=Scripted(answers), source=source()) == 1
    assert "was begun with something else (places)" in capsys.readouterr().err


def test_changed_code_is_refused_before_anything_is_asked(places, tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(ask, "code_version", lambda: {"commit": "c0ffee", "modified": True})
    model = Scripted(answers)
    out = tmp_path / "drafts.jsonl"
    assert (
        drafting.main(["--places", str(places), "--out", str(out)], asker=model, source=source())
        == 1
    )
    assert model.asked == [] and not out.exists()


def test_a_plan_asks_nothing_and_writes_nothing(places, tmp_path, capsys):
    out = tmp_path / "drafts.jsonl"
    model = Scripted(answers)
    argv = ["--places", str(places), "--out", str(out), "--plan"]
    assert drafting.main(argv, asker=model, source=source()) == 0
    assert model.asked == [] and not out.exists()
    assert "4 request(s): 0 done, 4 to ask" in capsys.readouterr().out


def test_a_place_that_is_not_in_its_paper_is_refused(places, tmp_path, capsys):
    lines = places.read_text(encoding="utf-8").splitlines()
    moved = [json.loads(line) for line in lines]
    for line in moved:
        if line["record"] == "place":
            line["end"] += 100_000
            break
    places.write_text("\n".join(json.dumps(line) for line in moved) + "\n", encoding="utf-8")
    argv = ["--places", str(places), "--out", str(tmp_path / "drafts.jsonl")]
    assert drafting.main(argv, asker=Scripted(answers), source=source()) == 2
    assert "is not where places.jsonl says it is" in capsys.readouterr().err


def test_places_of_another_parser_are_refused(places, tmp_path, capsys):
    lines = places.read_text(encoding="utf-8").splitlines()
    head = json.loads(lines[0]) | {"parser_version": "4"}
    places.write_text("\n".join([json.dumps(head), *lines[1:]]) + "\n", encoding="utf-8")
    argv = ["--places", str(places), "--out", str(tmp_path / "drafts.jsonl")]
    assert drafting.main(argv, asker=Scripted(answers), source=source()) == 2
    assert "made by parser 4" in capsys.readouterr().err


def test_without_a_key_the_command_does_not_start(places, tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setattr(ask, "ClaudeAsker", lambda settings: Scripted(answers))
    argv = ["--places", str(places), "--out", str(tmp_path / "drafts.jsonl")]
    assert drafting.main(argv, source=source()) == 2
    assert "ANTHROPIC_API_KEY is not set" in capsys.readouterr().err


def test_a_record_is_refused_where_git_would_not_ignore_it(places, capsys):
    # A record holds paper text, so it goes where git ignores files: runs_private/.
    if not (ROOT / ".git").exists():
        pytest.skip("not run from a clone of the repository")
    assert ask.private_path_problem(ROOT / "results" / "drafts.jsonl") is not None
    assert ask.private_path_problem(ROOT / "runs_private" / "drafting" / "drafts.jsonl") is None
    argv = ["--places", str(places), "--out", str(ROOT / "results" / "drafts.jsonl")]
    assert drafting.main(argv, asker=Scripted(answers), source=source()) == 2
    assert "is not a path that git ignores" in capsys.readouterr().err
    assert not (ROOT / "results" / "drafts.jsonl").exists()
