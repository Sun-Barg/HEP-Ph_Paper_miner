# HEP-Ph_Paper_miner

Work in progress. Not ready for use.

The goal is an MCP server that lets a model search arXiv and read papers, a minimal
tool-calling loop that drives it, and a small evaluation set that compares two tool
layouts: reading a whole paper at once, or reading an outline first and then single
sections.

## Status

- [x] Project skeleton; tests run without network
- [x] arXiv search, LaTeX section parsing, and the reading tools in two layouts
- [x] Tool-calling loop and run records
- [ ] Evaluation set, graders, results

## The two tool layouts

A server offers one of them, chosen when it is started.

| Layout | Tools | What the model reads |
|---|---|---|
| `staged` (default) | `search_papers`, `get_outline`, `read_section` | titles from a search, then an outline with section sizes, then single sections (at most 20,000 characters per call) |
| `flat` | `search_papers`, `read_paper` | titles and abstracts from a search, then a whole paper with every section marked |

Every result is one piece of text. Its first line has a fixed form that a program can
read (`section | 2501.00001v2 | 3.2 | chars 0-19980 of 25531 | partial, more follows`);
`src/hepph_paper_miner/result_text.py` writes and reads these lines.

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

A further set of tests runs TeX itself on small invented papers and compares what TeX
reads with what the section parser returns. It needs `pdflatex` on the PATH and is
skipped without it:

```
uv run pytest -m tex
```

The server speaks MCP over stdio. Started by hand it prints nothing and waits for a
client on stdin (stop it with Ctrl-C):

```
uv run hepph-paper-miner
uv run hepph-paper-miner --toolset flat
```

`uv run python -m hepph_paper_miner.server` does the same.

## Asking one question

The loop in `src/hepph_paper_miner/agent/` gives one question to a Claude model, runs
the tools the model asks for, and stops with a named reason (`answered`, `turn_limit`,
`tool_timeout`, ...). It needs an API key in the environment variable
`ANTHROPIC_API_KEY`. Every run costs money and sends requests to arXiv.

```
uv run python -m hepph_paper_miner.agent --question-id dev-01
uv run python -m hepph_paper_miner.agent --question-id dev-01 --toolset flat
uv run python -m hepph_paper_miner.agent --question "Which paper ...?"
```

A run writes two files with the same name:

- `results/runs/<run id>.jsonl`: what happened, turn by turn, without any text a tool
  returned (sizes, hashes and the first line of each result stand in for it).
- `~/hepph-paper-miner-runs/<run id>.jsonl` (set `HEPPH_PAPER_MINER_RUNS` to use
  another folder): the same with the full conversation. It holds paper text and stays
  outside this repository.

The questions are in `eval_data/questions_dev.jsonl`. These five are for development:
tool texts and the prompt may be tuned on them, so they are not part of the evaluation.

## Paper text and the cache

Downloads from arXiv are kept in `~/.cache/hepph-paper-miner` (set
`HEPPH_PAPER_MINER_CACHE` to use another folder), outside this repository. Paper text
is never committed, and neither is a run record that contains it. The one exception is
`tests/fixtures/arxiv-2610.26648v1/`: a paper under CC0 by the maintainer of this
repository, used to test the section parser.

This project uses arXiv's API and source downloads. It is not affiliated with or
endorsed by arXiv.

## License

MIT. See `LICENSE`.
