# HEP-Ph_Paper_miner

Work in progress. Not ready for use.

The goal is an MCP server that lets a model search arXiv and read papers, a minimal
tool-calling loop that drives it, and a small evaluation set that compares two tool
layouts: reading a whole paper at once, or reading an outline first and then single
sections.

## Status

- [x] Project skeleton; tests run without network
- [x] arXiv search, LaTeX section parsing, and the three reading tools
      (`search_papers`, `get_outline`, `read_section`)
- [ ] Tool-calling loop and run records
- [ ] Evaluation set, graders, results

## Development

Requires [uv](https://docs.astral.sh/uv/). It installs the Python version named in
`.python-version` and the locked dependencies into `.venv`.

```
uv sync
uv run pytest
```

The default test run sends no requests. Two further tests and one script talk to arXiv,
three seconds apart:

```
uv run pytest -m network
uv run python scripts/check_targets.py
```

The server speaks MCP over stdio. Started by hand it prints nothing and waits for a
client on stdin (stop it with Ctrl-C):

```
uv run python -m hepph_paper_miner.server
```

## Paper text and the cache

Downloads from arXiv are kept in `~/.cache/hepph-paper-miner` (set
`HEPPH_PAPER_MINER_CACHE` to use another folder), outside this repository. Paper text
is never committed. The one exception is `tests/fixtures/arxiv-2610.26648v1/`: a paper
under CC0 by the maintainer of this repository, used to test the section parser.

This project uses arXiv's API and source downloads. It is not affiliated with or
endorsed by arXiv.

## License

MIT. See `LICENSE`.
