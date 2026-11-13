"""One call to a model: what the loop sends, and what it gets back.

The loop knows a model only as "give it the conversation and the tools, get a reply".
ClaudeModel does that with the Claude API. Tests put a model in its place that
replies from a script, which is how the loop is tested without a network or a bill.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

import anthropic


@dataclass(frozen=True)
class ToolCall:
    """A tool the model asks for."""

    id: str
    name: str
    arguments: dict[str, Any]


@dataclass(frozen=True)
class Reply:
    """One response of a model.

    `content` is the assistant turn exactly as it has to be sent back with the tool
    results. The loop never looks inside it and never changes it: it holds the
    model's thinking blocks, and the API rejects a request in which they were
    altered or left out.
    """

    stop_reason: str | None
    text: str  # the text blocks, joined
    tool_calls: tuple[ToolCall, ...]
    blocks: tuple[str, ...]  # the type of every content block, in order
    usage: dict[str, Any]
    content: Any
    stop_details: dict[str, Any] | None = None
    raw: dict[str, Any] | None = None  # the whole response, for the private record
    # The model that answered, as the response names it. A request names the model it
    # wants; this is what the API says it got.
    model: str | None = None


class ModelError(Exception):
    """The model gave no reply: the API refused the request, or did not answer in time."""

    def __init__(self, kind: str, detail: str, status: int | None = None) -> None:
        super().__init__(kind, detail, status)
        self.kind = kind  # the name of the SDK's exception, for example "RateLimitError"
        self.detail = detail
        self.status = status

    def __str__(self) -> str:
        return f"{self.kind}: {self.detail}"


class Model(Protocol):
    """What the loop needs from a model."""

    @property
    def settings(self) -> dict[str, Any]:
        """Everything about this model that belongs in the record of a run."""
        ...

    async def reply(
        self,
        system: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        answer_schema: dict[str, Any],
    ) -> Reply:
        """Ask once. Raises ModelError when there is no reply."""
        ...


# What a request says to have the API keep the conversation so far. Given once for the
# whole request, the API sets the mark at its end and moves it on as the run grows.
_CACHE = {"type": "ephemeral"}

# How the model is to think. "adaptive" is what this model does anyway; the second form
# also asks for the text of the thinking blocks, as a summary (the default is "omitted").
_THINKING = {"type": "adaptive"}
_THINKING_SHOWN = {"type": "adaptive", "display": "summarized"}


class ClaudeModel:
    """A Claude model through the Messages API.

    Thinking and effort are set to what the API uses anyway for this model when a
    request leaves them out (adaptive, high). They are written out so that a run
    record says what was used, and so that a changed default cannot change the
    experiment unnoticed. Sampling settings (temperature and the like) are not
    sent: this model accepts none, so repeated runs differ by the model's own
    sampling and by nothing a caller chose.

    Retries after rate limits, overload and timeouts are the SDK's, with its
    waits; `max_retries` and `request_seconds` are its defaults, written out for
    the same reason as above.

    With `cache`, every request asks the API to keep the conversation so far for five
    minutes. The next request of the run then pays a fraction of the price for what
    this one sent, and a quarter more for what is new. The model reads the same
    either way. What changes is the bill, and how usage is counted: `input_tokens`
    is then only the part of a prompt that was neither written to the cache nor read
    from it. It is off unless asked for, because it does not always pay: a long tool
    result costs more when the run ends with the next response, and less when the
    run goes on.

    With `show_thinking`, the API returns a summary of what the model thought. On this
    model the reasoning and the short notes it writes before a tool call both come as
    thinking blocks, and their text is left out unless a request asks for it, so a
    record could not say why a tool was asked for a second time. The model reads the
    same and pays the same either way: a block carries the same signature with or
    without its text, and the signature is what the API reads when the block is sent
    back. The text is for the private record only (trace.py): a summary can quote a
    paper. Without `show_thinking` a request holds what it held before.
    """

    def __init__(
        self,
        name: str = "claude-sonnet-5-5",
        *,
        max_tokens: int = 16_000,
        effort: str = "high",
        cache: bool = False,
        show_thinking: bool = False,
        max_retries: int = 2,
        request_seconds: float = 600.0,
        client: anthropic.AsyncAnthropic | None = None,
    ) -> None:
        self.name = name
        self._max_tokens = max_tokens
        self._effort = effort
        self._cache = cache
        self._thinking = dict(_THINKING_SHOWN if show_thinking else _THINKING)
        self._max_retries = max_retries
        self._request_seconds = request_seconds
        # Without a client given, the key is read from ANTHROPIC_API_KEY. It is never
        # passed around in this code, printed or written to a record.
        self._client = client or anthropic.AsyncAnthropic(
            max_retries=max_retries, timeout=request_seconds
        )

    @property
    def settings(self) -> dict[str, Any]:
        return {
            "model": self.name,
            "max_tokens": self._max_tokens,
            "thinking": dict(self._thinking),
            "effort": self._effort,
            "cache_control": dict(_CACHE) if self._cache else None,
            "max_retries": self._max_retries,
            "request_seconds": self._request_seconds,
            "sdk": f"anthropic {anthropic.__version__}",
        }

    async def reply(
        self,
        system: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        answer_schema: dict[str, Any],
    ) -> Reply:
        try:
            response = await self._client.messages.create(
                model=self.name,
                max_tokens=self._max_tokens,
                system=system,
                messages=messages,
                tools=tools,
                thinking=self._thinking,
                output_config={
                    "effort": self._effort,
                    "format": {"type": "json_schema", "schema": answer_schema},
                },
                # Left out of the request altogether when the cache is not asked for.
                **({"cache_control": _CACHE} if self._cache else {}),
            )
        except anthropic.APIError as error:
            status = getattr(error, "status_code", None)
            raise ModelError(type(error).__name__, str(error), status) from error
        return reply_from(response)


def reply_from(response: anthropic.types.Message) -> Reply:
    """What the loop needs from an API response."""
    content = response.content
    return Reply(
        stop_reason=response.stop_reason,
        text="".join(block.text for block in content if block.type == "text"),
        tool_calls=tuple(
            ToolCall(block.id, block.name, dict(block.input))
            for block in content
            if block.type == "tool_use"
        ),
        blocks=tuple(block.type for block in content),
        usage=response.usage.model_dump(mode="json", exclude_none=True),
        content=content,
        stop_details=(
            response.stop_details.model_dump(mode="json") if response.stop_details else None
        ),
        raw=response.model_dump(mode="json"),
        model=response.model,
    )
