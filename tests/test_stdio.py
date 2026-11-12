"""Start the server the way a host does: as a child process, speaking MCP over stdin and stdout.

This is the one test that depends on the operating system (pipes, encodings,
process handling), so it is the one to watch on a new machine. The server here is
the real one, with arXiv behind it, so the test only does what needs no request.
"""

import sys

import pytest
from mcp import Client, StdioServerParameters

from hepph_paper_miner.http import CACHE_ENV
from hepph_paper_miner.server import SERVER_NAME


@pytest.mark.anyio
async def test_server_starts_over_stdio_and_answers_a_tool_call(tmp_path):
    # Same command a host is configured with: this environment's python, the module, no shell.
    launch = StdioServerParameters(
        command=sys.executable,
        args=["-m", "hepph_paper_miner.server"],
        env={CACHE_ENV: str(tmp_path)},  # keep the test away from the real cache
    )

    async with Client(launch, read_timeout_seconds=30) as client:
        assert client.server_info.name == SERVER_NAME

        tools = (await client.list_tools()).tools
        assert [tool.name for tool in tools] == ["search_papers", "get_outline", "read_section"]

        # An identifier that fails the format check is answered without any request.
        result = await client.call_tool("get_outline", {"arxiv_id": "not an identifier"})
        assert result.is_error is True
        assert "[invalid_id]" in result.content[0].text

    assert not any(tmp_path.iterdir())  # nothing was fetched, nothing was cached
