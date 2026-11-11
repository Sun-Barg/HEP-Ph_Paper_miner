# HEP-Ph_Paper_miner

Work in progress. Not ready for use.

The goal is an MCP server that lets a model search arXiv and read papers, a minimal
tool-calling loop that drives it, and a small evaluation set that compares two tool
layouts: reading a whole paper at once, or reading an outline first and then single
sections.

## Status

- [x] Project skeleton and one placeholder tool (`check_arxiv_id`); tests run without network
- [ ] arXiv search and LaTeX section parsing
- [ ] Tool-calling loop and run records
- [ ] Evaluation set, graders, results

## Development

Requires [uv](https://docs.astral.sh/uv/). It installs the Python version named in
`.python-version` and the locked dependencies into `.venv`.

```
uv sync
uv run pytest
```

The server speaks MCP over stdio. Started by hand it prints nothing and waits for a
client on stdin (stop it with Ctrl-C):

```
uv run python -m hepph_paper_miner.server
```

## License

MIT. See `LICENSE`.
