"""Start the server the way a host does: as a child process, speaking MCP over stdin and stdout.

This is the one test that depends on the operating system (pipes, encodings,
process handling), so it is the one to watch on a new machine.
"""

import sys

import pytest
from mcp import Client, StdioServerParameters

from hepph_paper_miner.server import SERVER_NAME


@pytest.mark.anyio
async def test_server_starts_over_stdio_and_answers_a_tool_call():
    # Same command a host is configured with: this environment's python, the module, no shell.
    launch = StdioServerParameters(command=sys.executable, args=["-m", "hepph_paper_miner.server"])

    async with Client(launch, read_timeout_seconds=30) as client:
        assert client.server_info.name == SERVER_NAME

        tools = (await client.list_tools()).tools
        assert [tool.name for tool in tools] == ["check_arxiv_id"]

        result = await client.call_tool("check_arxiv_id", {"arxiv_id": "2610.26648v1"})
        assert result.is_error is False
        assert result.content[0].text.startswith("2610.26648v1 ")
