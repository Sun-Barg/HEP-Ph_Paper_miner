"""ClaudeModel against a stand-in for the API: the real SDK, a transport that answers from memory.

Nothing here reaches the network. What is checked is this project's side of the
conversation: what a request holds, and what is made of a response. Whether the
API accepts such a request can only be seen with a real key (README, "Asking a question").
"""

import json

import anthropic
import httpx2
import pytest

from hepph_paper_miner.agent.model import ClaudeModel, ModelError
from hepph_paper_miner.agent.prompt import ANSWER_SCHEMA, SYSTEM_PROMPT

TOOLS = [
    {
        "name": "get_outline",
        "description": "Show one paper.",
        "input_schema": {"type": "object", "properties": {"arxiv_id": {"type": "string"}}},
    }
]
THINKING = {"type": "thinking", "thinking": "", "signature": "c2lnbmF0dXJl"}
TOOL_USE = {
    "type": "tool_use",
    "id": "toolu_01",
    "name": "get_outline",
    "input": {"arxiv_id": "2501.00001v2"},
}


def message(content: list[dict], stop_reason: str, **more) -> dict:
    return {
        "id": "msg_01",
        "type": "message",
        "role": "assistant",
        "model": "claude-sonnet-5-5",
        "content": content,
        "stop_reason": stop_reason,
        "stop_sequence": None,
        "usage": {
            "input_tokens": 1200,
            "output_tokens": 340,
            "output_tokens_details": {"thinking_tokens": 300},
        },
        **more,
    }


class Api:
    """Answers each request with the next prepared response, and keeps the requests."""

    def __init__(self, *responses: httpx2.Response | Exception) -> None:
        self._responses = list(responses)
        self.requests: list[dict] = []

    def __call__(self, request: httpx2.Request) -> httpx2.Response:
        self.requests.append(json.loads(request.content))
        response = self._responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response

    def model(self, **settings) -> ClaudeModel:
        client = anthropic.AsyncAnthropic(
            api_key="not-a-real-key",
            max_retries=0,
            http_client=httpx2.AsyncClient(transport=httpx2.MockTransport(self)),
        )
        return ClaudeModel(client=client, **settings)


def ok(body: dict) -> httpx2.Response:
    return httpx2.Response(200, json=body)


def refused(status: int, kind: str) -> httpx2.Response:
    body = {"type": "error", "error": {"type": kind, "message": "no"}}
    return httpx2.Response(status, json=body)


QUESTION = [{"role": "user", "content": "What does the data say?"}]


@pytest.mark.anyio
async def test_a_request_holds_the_settings_of_the_experiment_and_nothing_else():
    api = Api(ok(message([THINKING, TOOL_USE], "tool_use")))

    await api.model().reply(SYSTEM_PROMPT, QUESTION, TOOLS, ANSWER_SCHEMA)

    assert api.requests == [
        {
            "model": "claude-sonnet-5-5",
            "max_tokens": 16000,
            "system": SYSTEM_PROMPT,
            "messages": QUESTION,
            "tools": TOOLS,
            "thinking": {"type": "adaptive"},
            "output_config": {
                "effort": "high",
                "format": {"type": "json_schema", "schema": ANSWER_SCHEMA},
            },
        }
    ]
    # In particular: no temperature, top_p or top_k (this model rejects them), and no
    # tool_choice (the model decides when to call a tool; it cannot be forced to).


@pytest.mark.anyio
async def test_the_settings_a_caller_chooses_reach_the_request():
    api = Api(ok(message([THINKING, TOOL_USE], "tool_use")))
    model = api.model(name="claude-haiku-5-5", effort="medium", max_tokens=8000)

    await model.reply("S", QUESTION, TOOLS, {"type": "object"})

    (request,) = api.requests
    assert (request["model"], request["max_tokens"], request["system"]) == (
        "claude-haiku-5-5",
        8000,
        "S",
    )
    assert request["output_config"] == {
        "effort": "medium",
        "format": {"type": "json_schema", "schema": {"type": "object"}},
    }
    assert model.settings["effort"] == "medium" and model.settings["max_tokens"] == 8000


@pytest.mark.anyio
async def test_a_response_that_asks_for_tools_is_read():
    api = Api(ok(message([THINKING, TOOL_USE], "tool_use")))

    reply = await api.model().reply(SYSTEM_PROMPT, QUESTION, TOOLS, ANSWER_SCHEMA)

    assert reply.stop_reason == "tool_use"
    assert reply.blocks == ("thinking", "tool_use")
    assert reply.text == ""
    assert [(call.id, call.name, call.arguments) for call in reply.tool_calls] == [
        ("toolu_01", "get_outline", {"arxiv_id": "2501.00001v2"})
    ]
    assert reply.usage["input_tokens"] == 1200 and reply.usage["output_tokens"] == 340
    assert reply.usage["output_tokens_details"] == {"thinking_tokens": 300}
    assert reply.stop_details is None
    assert reply.raw["id"] == "msg_01"


@pytest.mark.anyio
async def test_the_assistant_turn_goes_back_to_the_api_as_it_came():
    answer = {"type": "text", "text": '{"answer": "x", "found": true, "evidence": []}'}
    api = Api(ok(message([THINKING, TOOL_USE], "tool_use")), ok(message([answer], "end_turn")))
    model = api.model()

    first = await model.reply(SYSTEM_PROMPT, QUESTION, TOOLS, ANSWER_SCHEMA)
    result = {"type": "tool_result", "tool_use_id": "toolu_01", "content": "outline | ..."}
    conversation = [
        *QUESTION,
        {"role": "assistant", "content": first.content},
        {"role": "user", "content": [result]},
    ]
    second = await model.reply(SYSTEM_PROMPT, conversation, TOOLS, ANSWER_SCHEMA)

    # The thinking block with its signature and the tool call, block for block: the
    # API rejects a turn whose thinking was altered or dropped.
    sent_back = api.requests[1]["messages"][1]
    assert sent_back["role"] == "assistant"
    assert sent_back["content"][0] == THINKING
    assert {key: sent_back["content"][1][key] for key in TOOL_USE} == TOOL_USE
    assert api.requests[1]["messages"][2] == {"role": "user", "content": [result]}

    assert second.stop_reason == "end_turn" and second.tool_calls == ()
    assert second.text == answer["text"]


@pytest.mark.anyio
async def test_several_text_blocks_are_joined():
    blocks = [
        {"type": "text", "text": '{"answer": "x", '},
        {"type": "text", "text": '"found": true}'},
    ]
    api = Api(ok(message(blocks, "end_turn")))
    reply = await api.model().reply(SYSTEM_PROMPT, QUESTION, TOOLS, ANSWER_SCHEMA)
    assert reply.text == '{"answer": "x", "found": true}'


@pytest.mark.anyio
async def test_a_refusal_keeps_its_details():
    details = {"type": "refusal", "category": "cyber", "explanation": "Declined."}
    api = Api(ok(message([], "refusal", stop_details=details)))
    reply = await api.model().reply(SYSTEM_PROMPT, QUESTION, TOOLS, ANSWER_SCHEMA)
    assert reply.stop_reason == "refusal" and reply.stop_details == details


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("response", "kind", "status"),
    [
        (refused(400, "invalid_request_error"), "BadRequestError", 400),
        (refused(401, "authentication_error"), "AuthenticationError", 401),
        (refused(429, "rate_limit_error"), "RateLimitError", 429),
        (httpx2.ConnectError("no route"), "APIConnectionError", None),
        (httpx2.ReadTimeout("too slow"), "APITimeoutError", None),
    ],
)
async def test_a_request_without_a_response_is_one_kind_of_error_for_the_loop(
    response, kind, status
):
    api = Api(response)
    with pytest.raises(ModelError) as caught:
        await api.model().reply(SYSTEM_PROMPT, QUESTION, TOOLS, ANSWER_SCHEMA)
    assert (caught.value.kind, caught.value.status) == (kind, status)
    assert str(caught.value).startswith(f"{kind}: ")


@pytest.mark.anyio
async def test_an_overloaded_api_is_asked_again_as_often_as_the_settings_say():
    busy = refused(529, "overloaded_error")
    api = Api(busy, busy, busy)
    client = anthropic.AsyncAnthropic(
        api_key="not-a-real-key",
        max_retries=2,
        http_client=httpx2.AsyncClient(transport=httpx2.MockTransport(api)),
    )
    # Do not wait for real: the SDK sleeps between tries.
    client._sleep_for_retry = _no_sleep.__get__(client)  # type: ignore[method-assign]
    model = ClaudeModel(client=client)

    with pytest.raises(ModelError) as caught:
        await model.reply(SYSTEM_PROMPT, QUESTION, TOOLS, ANSWER_SCHEMA)

    assert caught.value.status == 529
    assert len(api.requests) == 3  # the first try and two more


async def _no_sleep(self, **_ignored) -> None:
    return None


def test_the_settings_for_the_record_name_the_defaults_in_use():
    settings = Api().model().settings
    assert settings == {
        "model": "claude-sonnet-5-5",
        "max_tokens": 16000,
        "thinking": {"type": "adaptive"},
        "effort": "high",
        "max_retries": 2,
        "request_seconds": 600.0,
        "sdk": f"anthropic {anthropic.__version__}",
    }
    assert "key" not in json.dumps(settings)
