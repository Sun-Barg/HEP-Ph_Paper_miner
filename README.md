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

The default test run sends no requests. Four further tests and one script talk to arXiv,
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
uv run python -m hepph_paper_miner.agent --question-id dev-01 --cache
uv run python -m hepph_paper_miner.agent --question-id dev-01 --show-thinking --repeat 2
```

A run writes two files with the same name:

- `results/runs/<run id>.jsonl`: what happened, turn by turn, without any text a tool
  returned (sizes, hashes and the first line of each result stand in for it).
- `~/hepph-paper-miner-runs/<run id>.jsonl` (set `HEPPH_PAPER_MINER_RUNS` to use
  another folder): the same with the full conversation. It holds paper text and stays
  outside this repository.

With `--cache` every request asks the API to keep the conversation so far for five
minutes (the API's own cache; it has nothing to do with the folder of downloads
below). The next request of the run then pays a fraction of the price for what was
sent before, and a quarter more for what is new. The model reads the same either way,
so this is a matter of cost only, and it is off unless asked for: after a long tool
result it is cheaper when the run goes on for two more responses or longer, and dearer
when the run ends with the next one, as a run that reads a whole paper often does.
With it on, `input_tokens` in a record counts only what was neither written to that
cache nor read from it; the two cache counts stand beside it.

With `--show-thinking` the API returns a summary of what the model thought: its
reasoning, and the short notes it writes before a tool call. Without it these blocks
come back empty, and a record cannot say why a tool was asked for a second time. The
model reads the same and pays the same either way. The summaries go into the private
record only, because a summary can quote a paper. To read them beside the tool calls
of a run:

```
uv run python scripts/show_thinking.py "results/runs/20261113T*.jsonl" --out thinking.txt
```

A run hands in its answer in one of three ways (`--answer-channel`). The model reads
something else with each, so each has a prompt of its own (`prompt_version` in a
record, beside `answer_channel`):

| Channel | The answer is | Prompt |
|---|---|---|
| `tool` (default) | the arguments of a call of `submit_answer`, a tool that the loop adds to the tools of the server | `p2-tool`: `p1` and one line that says to call it |
| `format` | the text that ends the turn, which the API holds to the form of an answer | `p1` |
| `text` | the text that ends the turn, which the prompt asks for as one JSON object | `p2-text`: `p1` and a paragraph with the form |

```
uv run python -m hepph_paper_miner.agent --question-id dev-01 --answer-channel format
uv run python -m hepph_paper_miner.agent --question-id dev-01 --answer-channel text
```

`format` was the first of them, and the two others came from what it did on the
development questions (`results/runs/dev/README.md`): held to the form by the API, most
runs went on asking for tools long after they had been given what the question needs,
and without the form every run ended by itself. The two others were then run side by
side, on the five questions with both layouts, three times each: with `tool` all thirty
runs handed in an answer, with `text` twenty-six of the thirty. The evaluation uses
`tool` (next section), so that is what the command does unless it is told otherwise.
`format` and `text` are kept, for the records that were made with them and to run those
conditions again.

Neither `tool` nor `text` holds the model to anything. With `tool`, a turn that ends
without the call is `no_answer`, whatever its text says; a call whose arguments are not
an answer gets an error result, and the run goes on. The model cannot be made to call a
tool, and the tool is not marked strict, because strict input is made under the same
constraint as text held to a form. With `text`, a last text that is anything but the
one JSON object is `no_answer`.

With `--no-answer-format`, which goes with `--answer-channel format` only, a request
leaves out the form of the final answer, so the model ends the run with whatever text
it writes. This is for a diagnosis and not for an evaluation: it shows whether a model
that is not held to a form stops asking for tools sooner. The text of such a run is
read as an answer only when it happens to have the form, so the run can end as
`no_answer`. `scripts/show_thinking.py` prints that text as well.

The first line of a record says what was run: the names of the tool texts and of the
prompt, the settings of the model, and which code it was (`code`: the commit, and
whether a file the repository keeps had been changed). For a question from a file it
names the file and its SHA-256 (`questions`), and with `--repeat` the repetition. Every
turn names the model that answered (`response_model`), and the last line names the
parser, as the results of the run named it (`parser_versions`).

The questions are in `eval_data/questions_dev.jsonl`. These five are for development:
tool texts and the prompt were tuned on them, so they are not part of the evaluation.

## The conditions of the evaluation

The evaluation compares the two layouts. Everything else is the same in every run of
it, and is written down in `src/hepph_paper_miner/eval/conditions.py`:

| What | Fixed at |
|---|---|
| Tool texts | `staged-5` and `flat-4` |
| Parser | `4` |
| Answer | handed in with `tool`; prompt `p2-tool` |
| Model | `claude-sonnet-5-5`, adaptive thinking, effort `high`, at most 16,000 output tokens in a response |
| Limits of a run | 12 responses; 700 s for one tool call; 900 s for the run, looked at between responses |
| Requests to the API | 600 s for one request, which the SDK tries again up to twice; the API's cache on |

These are the defaults of the command, with one exception: the cache is off unless
asked for, so a run of the evaluation is started with `--cache`.

They were fixed while this repository held the five development questions and no
question of the evaluation. Tool texts and the prompt were tuned on those five, and are
not tuned on the questions they are then measured with. The thirty runs of
`results/runs/dev/diag-3-tool/` were made under these conditions (and with
`--show-thinking`, which the conditions leave open: the model reads the same with it).

Tests keep the conditions in place. A text that a model reads cannot change under its
name (`tests/test_toolset_pin.py`, `tests/test_prompt.py`). A name, or a default of the
command, the loop or the model, cannot move away from the conditions
(`tests/test_conditions.py`). And `differences` in the module holds the first line of a
record against them, which is how those thirty records are checked, and how the records
of the evaluation can be.

## Checking a question file

A question names the sections its answer stands in, and for each a short piece of the
section's text that marks the place (the anchor). Before a file of questions is used:

```
uv run python -m hepph_paper_miner.eval.check eval_data/questions_dev.jsonl
```

reads the file (a line of the wrong form refuses the whole file, with the line named;
that includes an answer key a grader could not use), reads the papers through the folder
of downloads, and says for every piece of evidence where it stands:

```
dev-04 | long_section | an answer is expected
   2610.26648v1 6.3 | chars 20342-20354 of 25531 | given by call 2 of 2
```

The last part is the number of calls of `read_section` it takes, from the start of the
section, until the place has been given whole: a section of more than 20,000 characters
comes in pieces. A section that does not exist, or an anchor that does not stand in its
section, is listed as a problem, and the command then ends with code 1. It closes with
counts over the file (how many questions expect "not in the papers", name no paper,
need a second call, and so on), to hold against the mix that was planned. It prints
places and sizes, and no text of a paper.

## Grading a run

`src/hepph_paper_miner/eval/grade.py` grades a finished run from its public record, the
question and the parsed papers, without a model:

```
uv run python -m hepph_paper_miner.eval.grade "results/runs/dev/diag-1/*.jsonl"
uv run python -m hepph_paper_miner.eval.grade "results/runs/dev/*/*.jsonl" --out grades.jsonl
```

It prints one line for each run and says four things:

- `search`: how many searches came back, how many of them empty, and the turn and rank at
  which a search first listed the paper that holds the answer.
- `access`: the turn in which the passage the answer rests on had been given to the
  model, and how many more responses the run took from there. A record holds no paper
  text, so the place of the passage is worked out from the parsed paper and the anchor
  of the question; the papers are read through the folder of downloads (and asked of
  arXiv when they are not in it).
- `cited`: whether the evidence the answer lists names the sections of the question,
  section for section (`strict`) or with the section around a subsection taken for it
  (`loose`), and how many other places it lists.
- `answer`: what a rule can check. `wrong` when there is no answer, when "found" is the
  wrong way round, or when a number or a phrase of the answer key is missing; `by_hand`
  when nothing is missing but the question leaves something to a person; `right`
  otherwise. This is not the verdict: a person grades every answer, and the rule is kept
  beside that grade to see how far the two agree.

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
