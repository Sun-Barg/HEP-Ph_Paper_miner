"""The server through the SDK's in-memory client: real protocol layer, no process, no network."""

import pytest
from mcp import Client
from mcp.types import TextContent

from hepph_paper_miner import __version__
from hepph_paper_miner.server import SERVER_NAME, build_server


@pytest.fixture
async def client():
    # raise_exceptions=True: a failure outside a tool body shows its real message in the test.
    async with Client(build_server(), raise_exceptions=True) as connected:
        yield connected


def only_text(result) -> str:
    """The text the model would read: exactly one text block is expected."""
    assert len(result.content) == 1
    block = result.content[0]
    assert isinstance(block, TextContent)
    return block.text


@pytest.mark.anyio
async def test_server_reports_its_name_and_version(client):
    assert client.server_info.name == SERVER_NAME
    assert client.server_info.version == __version__


@pytest.mark.anyio
async def test_tool_list_carries_name_description_and_input_schema(client):
    tools = (await client.list_tools()).tools
    assert [tool.name for tool in tools] == ["check_arxiv_id"]

    tool = tools[0]
    assert "arXiv identifier" in tool.description
    assert tool.input_schema["required"] == ["arxiv_id"]
    assert tool.input_schema["properties"]["arxiv_id"]["type"] == "string"


@pytest.mark.anyio
async def test_valid_identifier_returns_normalized_form(client):
    result = await client.call_tool("check_arxiv_id", {"arxiv_id": " arXiv:2610.26648v1 "})
    assert result.is_error is False
    assert only_text(result) == "2610.26648v1 is a well-formed arXiv identifier (version 1)."
    # A tool annotated `-> str` also returns its value as data for the client application.
    assert result.structured_content == {"result": only_text(result)}


@pytest.mark.anyio
async def test_invalid_identifier_is_an_error_result_the_model_can_read(client):
    bad = "https://arxiv.org/abs/2610.26648"
    result = await client.call_tool("check_arxiv_id", {"arxiv_id": bad})

    # A result, not an exception: the call itself succeeded and the model gets the text.
    assert result.is_error is True
    assert result.structured_content is None
    text = only_text(result)
    assert text.startswith("Error executing tool check_arxiv_id: [invalid_id] ")
    assert repr(bad) in text  # what was wrong
    assert "'2610.26648v1'" in text  # what to pass instead


@pytest.mark.anyio
@pytest.mark.parametrize("arguments", [{}, {"arxiv_id": 2610}])
async def test_arguments_that_break_the_schema_never_reach_the_tool(client, arguments):
    result = await client.call_tool("check_arxiv_id", arguments)

    # The SDK rejects these before calling the function. Still an error result,
    # but without our bracketed kind: a client must tell the two apart.
    assert result.is_error is True
    text = only_text(result)
    assert text.startswith("Error executing tool check_arxiv_id: ")
    assert "[invalid_id]" not in text
