"""HEP-Ph_Paper_miner: an MCP server for searching and reading arXiv papers."""

from importlib.metadata import version

# Single source of truth is pyproject.toml; this reads it from the installed package.
__version__ = version("hepph-paper-miner")
