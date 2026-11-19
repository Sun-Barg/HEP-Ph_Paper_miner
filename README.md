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
- [x] Evaluation set, graders, and the pre-registration of the evaluation
- [x] Runs of the evaluation, grading by hand, results
- [x] A model as a second grader, held against the grades by hand

## The two tool layouts

A server offers one of them, chosen when it is started.

| Layout | Tools | What the model reads |
|---|---|---|
| `staged` (default) | `search_papers`, `get_outline`, `read_section` | titles from a search, then an outline with section sizes, then single sections (at most 20,000 characters per call) |
| `flat` | `search_papers`, `read_paper` | titles and abstracts from a search, then a whole paper with every section marked |

Every result is one piece of text. Its first line has a fixed form that a program can
read (`section | 2501.00001v2 | 3.2 | chars 0-19980 of 25531 | partial, more follows`);
`src/hepph_paper_miner/result_text.py` writes and reads these lines.

## Results of the evaluation

Twenty questions in English about thirteen papers, each asked three times with each
layout: 120 runs, made on 2026-11-17 with `claude-sonnet-5-5` under the conditions
described below, by the commit that pre-registered the evaluation (`70c7384`). arXiv and
the API spoilt no run, so every cell was run once. The maintainer graded the 118 answers
by hand, on a sheet that does not show the layout. What is measured, and how each
hypothesis is read, was fixed before the first run in `eval_data/PREREGISTRATION.md`.
The records, the graded sheet, its key and the whole report (`report.md`) are in
`results/`, with a README of their own.

| | staged | flat |
|---|---|---|
| Runs that handed in an answer | 58 / 60 | 60 / 60 |
| A search listed the paper (the five questions that do not name it) | 15 / 15 | 15 / 15 |
| The passage the answer rests on was given to the model | 58 / 60 | 60 / 60 |
| The answer cites the sections of the question (of the runs with an answer) | 57 / 58 | 60 / 60 |
| Right, graded by hand (a run without an answer is wrong) | 57 / 60 | 60 / 60 |
| Questions right in at least two of their three runs | 19 / 20 | 20 / 20 |
| Tool result characters in a run, median (range) | 20,399 (6,412 to 113,344) | 147,086 (29,560 to 347,325) |
| Input tokens in a run, median (range) | 19,459 (10,801 to 278,432) | 67,665 (21,539 to 285,781) |
| Responses in a run, median (range) | 4 (3 to 12) | 2 (2 to 8) |
| Runs with a tool call that ended in an error | 6 | 3 |
| Cost of the 60 runs, worked out from the usage at list prices | $2.78 | $10.90 |

Input tokens are everything a run sent to the model, summed over its responses: new,
written to the API's cache, and read from it.

- **H1, staged gives the model less tool result text: in 20 questions of 20.** The
  median of the three staged runs is lower than the median of the three flat runs in
  every question, at 0.03 (eval-06) to 0.80 (eval-04) of it. One-sided sign test over
  the questions: p = 9.5e-07, reported as it comes (no threshold was fixed in
  advance). Input tokens are lower in 18 questions and higher in 2 (p = 0.0002), one of
  them eval-15: a staged run takes more responses, and each response is asked for with
  the whole conversation so far.
- **H2, staged does not answer clearly worse: the layouts agree in 19 questions of
  20.** A layout has a question right when at least two of its three runs are right.
  Both right: 19. Staged only: 0. Flat only: 1 (eval-15). Neither: 0. This does not
  show that the two answer equally well. Twenty questions cannot show it, and all three
  wrong runs are staged.
- **H3 (exploratory), staged makes more tool calls, and its wrong runs gather in "its
  paper was given but not the passage".** It made more calls (median 3 against 1). Of
  its three wrong runs one is of that kind. The two others handed in no answer, and in
  one of those the passage had not been given either.

### The three wrong runs

All three are staged, and two of them are of one question. `results/README.md` goes
through them, with the tool calls that ended in an error and the limit of responses.

- **eval-15, second and third run: the passage was never read.** The passage stands in
  the text that a section has before its first subsection. Only a read of the section
  itself returns that text, and no tool text says that there is any. All three staged
  runs read the three subsections and went on to other sections. One then read the
  section itself and answered right. One never did, answered that it could not find
  the statement of the paper that the question repeats, and was graded wrong. One was
  ended by the limit of twelve responses. The staged runs of this question took 3.7
  times the input tokens of the flat runs, and cost the same.
- **eval-13, third run: an answer written as text**, without the call that hands it
  in. By the rule fixed before the runs that is no answer, and no answer is wrong.
  Outside that rule the maintainer read the text, knowing which run it was, and graded
  it right: what failed in this run is how the answer was handed in.

### How strong each claim is

| Claim | Strength | What it does not cover |
|---|---|---|
| Staged gives the model less tool result text | measured in every one of the 20 questions | one model, one effort and one prompt; thirteen papers with LaTeX source on arXiv; questions in English that name their paper or can find it with a search |
| Staged takes fewer input tokens | measured in 18 of the 20 questions | the two others, and what a miss costs: in eval-15 staged took 3.7 times the tokens of flat |
| Staged answers as well as flat | not shown | the layouts agree in 19 of 20 questions, and every wrong run is staged. Twenty questions cannot show that two layouts answer equally well, and these were kept only when a reader of the full text answered them as the reference does |
| Which difference between the layouts matters | not measured | abstracts in search results and the unit of reading change together |
| Why staged failed in eval-15 | one observation | text that only a read of the whole section returns: one question about one paper. No run tried a changed outline |
| Staged is cheaper | only for these 120 runs | $2.78 against $10.90, worked out from the usage at list prices with the API's cache on, and not read from the Console. In eval-15 the two layouts cost the same |
| A model as judge gives the grades by hand | measured on the 118 answers, where a judge that calls every answer right would agree on 117 | the judge is the model that gave the answers, and it thought before a quarter of its replies. On row 86, the one answer graded wrong, its first request of three said right |
| That judge tells a wrong answer | measured on 91 controls, each called wrong in all three requests | the controls are made up: wrong answers of these kinds, not the wrong answers a model gives, of which the sheet holds one. The controls of a question come from one row |

This is not "staged is as good as flat and cheaper", and not "a model can grade these
answers in place of a person". The table above is the whole of what can be claimed.

### What the grading leaves open

- **One verdict was changed after the sheet was graded, and the one question in which
  the layouts differ rests on it.** Row 86 of the sheet (eval-15, the second staged
  run) was first graded right: the answer gives no number and says that the paper
  reports none. A Claude session that works on this repository then held the finished
  sheet against the notes of the questions, and pointed out that the note of eval-15
  asks for more: a right answer says that the paper states these limits were derived,
  and this answer says it found no such statement. The maintainer graded the row wrong,
  not yet knowing its layout. The session had read the records of all runs, and could
  tell. With the first verdict staged has eval-15 right in two of three runs, and both
  layouts have all 20 questions right. The criterion is written in that row of the
  sheet. The note in the question file was left as it is, because the file is fixed by
  its digest. The change is listed under Deviations in the pre-registration.
- The grader also revised the questions, and the wording of an answer can hint at its
  layout. The sheet hides the layout, the repetition, the cited sections and what the
  rule said, and nothing more. The runner prints how each run ends, so it was known
  before the grading that the row missing for eval-13 and for eval-15 was a staged one.
- The rule of `eval.grade` sent all 118 answers to a person (`by_hand`), so the report
  says nothing here about how far the rule and the grade by hand agree.
- **A model graded the same answers afterwards, and its verdicts are the grades by hand
  on all 118 rows. That alone says little.** The grader called 117 rows right, so a
  judge that calls every answer right would agree on 117. Whether the judge can tell a
  wrong answer rests on 91 controls, answers made to be wrong: it called every one
  wrong in all three of its requests, the 44 that the rule of `eval.grade` leaves to a
  person among them. The controls are made up, and those of a question come from one
  row of the sheet. The one wrong answer a model gave is row 86, and there the first of
  the judge's three requests said right, as the grader first did; the two others said
  wrong, for the reason the row was changed. The judge is the model that gave the
  answers, and 157 of its 627 replies held a thinking block. This does not show that
  the judge finds the wrong answers of a model, or that it could stand in for the
  grader. The analysis was added after the results and is listed in the
  pre-registration, Section 10; the numbers are in `results/judge/report.md`, and how
  the judge is run is under [The judge](#the-judge).

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

It also looks for every number of an answer key in the evidence, read the way the
grader reads an answer, so that an answer copying the number from there would pass the
rule. TeX spacing and math mode are read as spaces, and a number right after a command
as the number it prints (`$\sim100$` is 100). When all places are needed, one of them
has to write it; when any one is enough, each has to, since each is meant to answer
alone. A number that is not written is listed with a `?` (the paper here is one the
tests make up):

```
   ? key 29 (regions) is not written in 2504.00004v1 1
```

That is not counted as a problem: an answer may be meant to work the number out, as a
count of regions. A person says whether it is meant, or a mistake in the key.

For a paper that a question does not name, so that a search has to find it, the check
asks arXiv which version it lists now. A search lists that version and a run reads it,
while the run is graded against the version the question names, so another one is shown
with a `~`. That is not counted as a problem either: the owner says which version to
grade.

## Running the evaluation

```
uv run python -m hepph_paper_miner.eval.run --questions eval_data/questions_eval.jsonl --out results/runs/eval
```

runs every question of the file with both layouts, three times. What is measured, and
how each hypothesis is read, was fixed before the first run in
`eval_data/PREREGISTRATION.md`, with the SHA-256 of the question file to pass as
`--questions-sha256`. Each run is the command
of one question in a process of its own, started as a run of the evaluation is started
(`--cache --show-thinking`, the layout and the repetition), and its record is held
against the conditions as soon as it is written. The repetition is the outer loop, and
within it the questions come in the order of the file; which layout of a question runs
first alternates from question to question and from repetition to repetition.

A run is spoilt when arXiv or the API failed under it: a tool call that ended in
`timeout` or `upstream_busy`, or a run that ended in `api_error`, `tool_transport_error`,
`tool_timeout` or `time_limit`, or one that never wrote its last line. Its record is kept,
and the cell is run again with the same repetition number after the pass, at most twice.
A cell spoilt three times is given up and counted. Started again, the command skips what
is done, so it can be stopped and resumed; a run stopped by hand has no last line and
counts as spoilt (move its record out of the folder if it should not).

It stops at once when the API refuses the key, the credit or the spending limit of the
workspace, after three runs in a row that the API failed, and when a record names
anything but the conditions. It does not start when files the repository keeps have
been changed, when the folder holds runs of another question file, or runs made by
another commit (`--allow-other-code` adds to them anyway), or, with `--questions-sha256`,
when the file is not the one named. `--plan` says what is done and what would run, and
runs nothing; `--only` and `--repeats` run a part, as for a rehearsal:

```
uv run python -m hepph_paper_miner.eval.run --questions eval_data/questions_dev.jsonl --out results/runs/rehearsal --only dev-01 --repeats 1
```

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

## Grading the answers by hand

```
uv run python -m hepph_paper_miner.eval.sheet --questions eval_data/questions_eval.jsonl --runs results/runs/eval --sheet grading.csv --key runs_private/grading-key.csv
```

writes, once every cell of the evaluation is done, the sheet on which a person grades
every answer. It has a row for each run that counts and handed in an answer; a run
without an answer is wrong whatever it would have said, and is not on it. The rows of a
question stand together, in an order drawn at random, numbered down the sheet, and the
first row of a question shows the question, its reference answer and what is accepted.
The sheet does not show the layout, the repetition or the run, the sections an answer
cites, or what the rule said. Write `right` or `wrong` under `grade` (there is no partial
credit), why under `why_wrong`, anything else under `note`, and save it as "CSV UTF-8".
Which run a number stands for is in the key, which goes in `runs_private/` (a folder
that is never committed) and stays closed until every row is graded.

When the last row is graded, the sheet and the key are committed together, as
`results/grading.csv` and `results/grading-key.csv`. The verdicts are a part of the
results, and without the two files the report could not be made again from this
repository.

## The report

```
uv run python -m hepph_paper_miner.eval.report --questions eval_data/questions_eval.jsonl --runs results/runs/eval --sheet results/grading.csv --key results/grading-key.csv --out results/report.md
```

grades every run that counts with `grade.py`, takes the verdicts from the sheet, and
writes tables in Markdown:

- By layout: the search, access and citation of the runs, the answers right by hand,
  the characters of tool results, the input tokens (written to the cache and read from
  it included), the paper text a run was given with each character counted once, calls,
  turns, calls that gave nothing new, and the cost worked out from the usage.
- H1, question by question: the median characters of the staged runs against those of
  the flat runs, and a one-sided sign test of the questions in which staged is lower.
- H2, question by question: a layout answers a question right when more than half of
  its runs are right, two of three.
- Why runs were wrong, from their records: no answer and why, or an answer after the
  passage was given, after only its paper was, or without a paper of the question.
- What the rule of `grade.py` said against the grade by hand, and the runs that do not
  count.

Without `--sheet` it writes everything but the verdicts. It refuses a sheet whose key
does not name exactly the runs that count with an answer, and names every record that
differs from the conditions.

`tests/test_results.py` holds the four things in `results/` against each other: the
records of the evaluation, the graded sheet, its key, and `results/report.md`. The
records have to be the 120 cells of the plan, each run once and in its order, made
under the conditions by the commit of the pre-registration. The key has to name every
run with an answer once, and the sheet has to be the one written for those runs, with
only the three columns of the grader filled in. And the report has to be what this
command writes from the three. That last check runs without the network. It covers
every line that needs no paper text, and the lines that do need it for the five
questions that are only about the paper kept in `tests/fixtures/`. The rest stands in
the report as it was made on the maintainer's computer, and making it again needs the
twelve other papers from arXiv: whether a passage of one of them was given to a run,
and the four rows that are counted over the text of every paper (passages given, new
paper text, repeat reads, responses from the passage to the answer).

## The judge

```
uv run python -m hepph_paper_miner.eval.judge --questions eval_data/questions_eval.jsonl --sheet results/grading.csv --controls eval_data/judge_controls_eval.csv --out results/judge/eval-j2.jsonl --parallel 4
uv run python -m hepph_paper_miner.eval.agree --questions eval_data/questions_eval.jsonl --record results/judge/eval-j2.jsonl --sheet results/grading.csv --key results/grading-key.csv --controls eval_data/judge_controls_eval.csv --runs results/runs/eval --out results/judge/report.md
```

The grades by hand are the verdicts. The judge is a model asked for a second grade of
the same answers, so that the two can be held side by side. The first command asks it
to grade every row of the sheet, from what the sheet shows the grader (the question,
its reference answer, what is accepted, the answer and its `found`) and nothing else:
it reads four columns of the sheet and never opens the key. Each answer is one request
without tools, its reply is held to a form (a verdict and one sentence on why), and
every answer is asked three times; the verdict on an answer is the one that two or
three of them gave. The record is one file of JSON lines with no text of an answer or
a question. `--parallel` sets how many requests go out at a time.

The grader called 117 of the 118 rows right, so a judge that calls every answer right
would agree on 117 of them. What shows whether the judge can tell a wrong answer are
controls: answers made to be wrong, asked like the rows. `eval_data/judge_controls_eval.csv`
holds 91 for the evaluation questions and `eval_data/judge_controls_dev.csv` 25 for the
development questions.

The second command reads what the judge was never given, the grades, the key, the
records of the runs and what the file of controls says of each control, and writes the
report: the rows by hand against the judge, beside what calling every answer right
would give; the rows where the two differ; the controls the judge called wrong, by the
kind of fault, by how they were made, by question, and against the rule of `grade.py`;
and H2 again with the judge's verdicts. It refuses a record that is not complete, that
asked only some of the answers, or that was begun with other files.

The texts the judge reads have a name, `JUDGE_VERSION`, now `j2`. They were changed on
the development questions only: `results/judge/dev-j1.jsonl` and `dev-j2.jsonl` are the
two runs on the development answers (`results/judge/dev-sheet.csv`, which nobody
graded) and their controls, and why the second judge replaced the first is in the
pre-registration, Section 10. The run on the evaluation is `results/judge/eval-j2.jsonl`,
made once from the commit that added that entry (`9711ca5`), and its report is
`results/judge/report.md`. `tests/test_agree.py` holds the two against the sheet, the key,
the controls and the commit, as `tests/test_results.py` does for the runs.

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
