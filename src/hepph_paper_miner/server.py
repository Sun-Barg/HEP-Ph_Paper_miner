"""The MCP server.

This first version exposes one placeholder tool, `check_arxiv_id`, to prove the
plumbing: install, stdio transport, registration in a host. The search and
reading tools replace it later. What stays is the error path: a source raises
SourceError, and the server turns it into a sentence the model can act on.

Start it with:  python -m hepph_paper_miner.server
"""

from __future__ import annotations

from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from hepph_paper_miner import __version__
from hepph_paper_miner.sources.base import ErrorKind, SourceError, parse_arxiv_id

SERVER_NAME = "hepph-paper-miner"


def explain(error: SourceError) -> str:
    """Turn an expected failure into a sentence that says what went wrong and what to do next.

    The sentence starts with the error kind in brackets, so that a client can
    classify the failure without understanding the prose.
    """
    if error.kind is ErrorKind.INVALID_ID:
        return (
            f"[{error.kind.value}] {error.detail!r} is not an arXiv identifier. "
            "Expected forms: '2610.26648v1' or '2610.26648' (papers from 2007-04 on), "
            "'hep-ph/0404175v2' or 'hep-ph/0404175' (earlier papers). "
            "Pass the identifier only, not a URL."
        )
    return f"[{error.kind.value}] {error.detail}"


def build_server() -> MCPServer:
    """Create the server and register its tools.

    A function rather than a module-level object: tests build a fresh server each,
    and later versions pass in the paper source and the tool layout.
    """
    mcp = MCPServer(SERVER_NAME, version=__version__)

    @mcp.tool()
    def check_arxiv_id(arxiv_id: str) -> str:
        """Check that a string is a well-formed arXiv identifier and return its normalized form.

        This checks the format only. It does not look the paper up.
        """
        try:
            parsed = parse_arxiv_id(arxiv_id)
        except SourceError as error:
            # ToolError reaches the model as a result with is_error=True and this text.
            # Any other exception would reach it as a bare "Error executing tool ...".
            raise ToolError(explain(error)) from error
        pinned = "no version pinned" if parsed.version is None else f"version {parsed.version}"
        return f"{parsed} is a well-formed arXiv identifier ({pinned})."

    return mcp


def main() -> None:
    # No arguments: serve over stdio. stdout carries the protocol, so nothing here may print.
    build_server().run()


if __name__ == "__main__":
    main()
