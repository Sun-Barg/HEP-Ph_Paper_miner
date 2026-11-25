# HEP-Ph_Paper_miner

An MCP server that lets a model search arXiv and read papers, a minimal tool-calling
loop that drives it, and a small evaluation set that compares two tool layouts: reading
a whole paper at once, or reading an outline first and then single sections.

Everything ticked under Status is done, and the results of the evaluation are below. The
last item has been run and counted, and the check of its outlines by hand is still to
come.

## Status

- [x] Project skeleton; tests run without network
- [x] arXiv search, LaTeX section parsing, and the reading tools in two layouts
- [x] Tool-calling loop and run records
- [x] Evaluation set, graders, and the pre-registration of the evaluation
- [x] Runs of the evaluation, grading by hand, results
- [x] A model as a second grader, held against the grades by hand
- [x] Tool texts changed for what the evaluation showed, and held against the runs before
- [x] The loop asks for an answer that was written and not handed in, tried on two such ends
- [ ] A survey of which papers the server can read, in thirteen archives: the 520 papers have been fetched and counted, the 65 outlines have not been held against the papers yet

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
| Why staged failed in eval-15 | one observation | text that only a read of the whole section returns: one question about one paper. No run of the evaluation tried a changed outline; three other questions did, afterwards ([What was changed after the evaluation](#what-was-changed-after-the-evaluation)) |
| Staged is cheaper | only for these 120 runs | $2.78 against $10.90, worked out from the usage at list prices with the API's cache on, and not read from the Console. The factor of 3.9 belongs to the cache: the same tokens at the plain input price are $5.00 against $10.49, a factor of 2.1 (`results/README.md`). In eval-15 the two layouts cost the same |
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
  its digest; what it leaves unsaid is written down in `eval_data/QUESTION_NOTES.md`.
  The change is listed under Deviations in the pre-registration.
- The grader also revised the questions, and the wording of an answer can hint at its
  layout. The sheet hides the layout, the repetition, the cited sections and what the
  rule said, and nothing more. The runner prints how each run ends, so it was known
  before the grading that the row missing for eval-13 and for eval-15 was a staged one.
- The rule of `eval.grade` sent all 118 answers to a person (`by_hand`), and it could
  not have done otherwise. Every question of the evaluation has an item in its answer
  key that is left to a person, so the rule could only say `wrong` or `by_hand` there:
  that follows from the question file, not from the answers. The report therefore says
  nothing about how far the rule and the grade by hand agree. The rule is seen at work
  on the 91 controls of the judge, of which it calls 47 `wrong`.
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

The default test run sends no requests. Six further tests and one script talk to arXiv,
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

The model is given the tools of the server, with their descriptions and schemas as the
server lists them, and the system prompt of the loop. The loop does not pass on the
instructions that the server sends when a client connects. A host may show those to
its model; no run made with this loop read them.

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
uv run python scripts/show_thinking.py "results/runs/dev/diag-1/*.jsonl" --out thinking.txt
```

A run hands in its answer in one of three ways (`--answer-channel`). The model reads
something else with each, so each has a prompt of its own (`prompt_version` in a
record, beside `answer_channel`):

| Channel | The answer is | Prompt |
|---|---|---|
| `tool` (default) | the arguments of a call of `submit_answer`, a tool that the loop adds to the tools of the server | `p3-tool`: `p1`, one line that says to call it, and a message for a turn that ends without the call |
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

Neither `tool` nor `text` holds the model to anything. With `tool`, text is no answer,
whatever it says, and a turn that ends without the call is asked for the call: the
reply goes back as it came, followed by one message of the loop, and the run goes on.

```
That reply ended without a call of submit_answer, so no answer was handed in. Give the final answer by calling submit_answer.
```

The loop asks once in a run. It does not ask after the last response the limit allows,
or after a response that holds nothing, and a run that ends its turn without the call
after it was asked is `no_answer`. The request stays what it was but for that message:
the same system prompt and the same tools, so the model can still read on. A record
says whether the loop asked: `asked_again` in its last line is the number of the
response it asked after, or null, and the line of that response has `asked_again` as
well. The loop asks since the prompt `p3-tool`; with `p2-tool`, which the evaluation
used, such a turn ended the run ("An answer that was written and not handed in", below).
A call whose arguments are not an answer gets an error result, and the run goes on. The
model cannot be made to call a tool (the API refuses a forced tool choice for it), and
the tool is not marked strict, because strict input is made under the same constraint
as text held to a form. With `text`, a last text that is anything but the one JSON
object is `no_answer`.

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

These were the defaults of the command when the evaluation was run, with one exception:
the cache is off unless asked for, so a run of the evaluation is started with `--cache`.
The tool texts have been changed since (see
[What was changed after the evaluation](#what-was-changed-after-the-evaluation)); the
rest are its defaults still.

No run read the instructions of the server, because the loop does not pass them on
(see [Asking one question](#asking-one-question)). That is the same for both layouts;
whether a run would have gone differently with them was not measured.

They were fixed while this repository held the five development questions and no
question of the evaluation. Tool texts and the prompt were tuned on those five, and are
not tuned on the questions they are then measured with. The thirty runs of
`results/runs/dev/diag-3-tool/` were made under these conditions (and with
`--show-thinking`, which the conditions leave open: the model reads the same with it).

Tests keep the conditions in place. A text that a model reads cannot change under its
name (`tests/test_toolset_pin.py`, `tests/test_prompt.py`). A name, or a default of the
command, the loop or the model, cannot move away from the conditions that name the code
(`tests/test_conditions.py`). And `differences` in the module holds the first line of a
record against them, which is how those thirty records are checked, and how the records
of the evaluation can be.

One thing that a tool answers was changed after the evaluation, under the same names.
arXiv now writes the id of an entry in its error feed with `https://`, and the search
knew only the older `http://`, so an error feed was taken for a search that found
nothing. Since `e13cb0d` such a search comes back as `[bad_query]`. A tool that answers
the same call differently gets a new name by the rule of `TOOLSET_VERSION`. Here the
names were kept: none of the 115 searches that came back in the records of the
development runs and of the evaluation had been answered with that feed, so no recorded
run would have read anything else. The pre-registration lists this under Deviations.

### What was changed after the evaluation

The code no longer has the tool texts of the evaluation. Four things were changed, for
what its runs and a review of the whole repository had shown:

- **An argument that a tool does not have.** The SDK drops what a call holds beyond the
  schema of a tool, so a made-up argument was answered as if it were not there. In the
  records of the evaluation four calls carried one (an `end` three times, a `max_results`
  once); two reads with an `end` returned some 14,000 characters more than they had
  asked for. Such a call now comes back as an error that names the arguments the tool
  has, the schema says that there are no others, and `read_section` and `read_paper`
  have an `end`.
- **The text a section has of its own.** A section can begin with text in front of its
  first subsection. No subsection holds it, and the outline did not show it: the passage
  of eval-15 stands in such text. The line of such a section now ends with the size of
  that text (`own N`), and a read with `end=N` returns just it.
- **Small words in a search.** The description said that every word has to appear, and
  did not say that common small words are left out. It says so now, and a query that
  holds nothing to search for is answered as one that was not searched.
- **An underscore in a search word.** arXiv found nothing for a word that holds one
  (tried on 2026-11-19), and every word of a search has to match. An underscore now
  parts words.

The new texts have the names `staged-6` and `flat-5`. `conditions.py` keeps the
conditions of the evaluation as they were (`EVALUATION`) and names beside them what the
code had then (`REVISED`: the same, but for the tool texts). The records of the
evaluation stay held against the first, and the runs of 2026-11-20 against the second.
`eval.run` holds its runs against the conditions that name the code, which are a third
set by now (below).

The twenty questions of the evaluation were not run again with the new texts: that
would check a change on the questions that suggested it. Instead the five development
questions were run again and held against the runs the conditions were fixed with, by
criteria that were written down before those runs (`eval/regress.py`), and three
questions written for the changed outline (`eval_data/questions_target.jsonl`) were run
with the texts before and after. All of it was run on 2026-11-20, with the model and
the settings of the evaluation. The records are in `results/runs/regress/`, and the
README of that folder goes through them.

| Claim | Strength | What it does not cover |
|---|---|---|
| With the new texts the development runs do what they did before | not shown: the comparison failed, by two of the five criteria fixed before the runs | Two of the thirty runs, both of dev-02, ended their turn with the answer written as text, without the call that hands it in, as one run of the evaluation had. One answer to dev-03 is now left to a person by the rule, which had called every answer to it right before; the judge calls it right. The three other criteria held |
| The new texts make a run end without handing in its answer | not shown, either way | dev-02 was asked again, ten times with each layout by the code before the change and by the code after it: 0 of 20 runs ended so before, and 0 of 20 after. Forty runs show a large difference only. How the count would be read was fixed before those runs, but outside this repository |
| The new outline leads a model to the text a section has of its own | shown on three questions written for it: the passage was given in 8 of 9 staged runs, against 4 of 9 with the texts before | The Claude session that wrote the change drafted the questions, about one paper and two pieces of its text, and the answers were not graded. Nothing about questions in general, and nothing about eval-15, which was not asked again |

This is not "the new texts are better". The comparison failed by criteria that were
fixed in advance, and it stays failed. The new texts were left as they are: the runs
made to tell whether they were the cause did not show that they were.

### An answer that was written and not handed in

Three runs in the records ended their turn with the answer written as text and no call
of `submit_answer`: one of the evaluation (eval-13) and the two of dev-02 in the table
above. The loop called each a run without an answer, as its rule said. Nothing makes
this model call a tool, so the loop now does what is left to it, and asks: the reply
goes back as it came with one message after it, once in a run ("Asking one question"
has the message and where the loop does not ask). The message belongs to the prompt,
which is `p3-tool` now, and `conditions.py` names a third set of conditions for it
(`ASKING_AGAIN`: `REVISED` with that prompt and nothing else).

What would be run with the new prompt, and how it would be read, was written down with
the change (`0af1c02`), before any of it. Both things were run on 2026-11-23. The
records are in `results/runs/asking-again/`, and the README of that folder goes through
them.

- **The two ends of dev-02, sent again.** A turn had ended this way in about one run in
  a hundred (3 of the 256 runs that this repository then held, of those that count and
  hand in with the tool), so thirty new runs would most likely not meet the message at
  all. `eval.replay` builds the conversation of each of the two runs again from its
  private record, puts the reply and the message at its end as the loop now would, and
  sends that request ten times. Written down before the requests: when eighteen or more
  of the twenty responses hand in an answer by the call, the message is said to have
  got the answer handed in at these two ends; with fewer it is said not to have, and
  another way to get such an answer is tried. A response that asks for other tools
  instead counts against the message, although a run of the loop might have ended with
  an answer after it. Eighteen is nine in ten, a choice made before the requests.
  **All twenty responses handed in an answer**, ten of each conversation.
- **The development questions again.** Thirty runs, held against the thirty of
  2026-11-20 that were made with the same tool texts (`results/runs/regress/dev-after`),
  by `eval.regress --criteria 2`: the five criteria as before, with the third as "the
  rule calls no answer wrong" and no more. On 2026-11-20 the other half of the third
  had failed an answer that the rule only leaves to a person, and whether such an
  answer is wrong is what the fourth criterion asks. The comparison of that day stays
  as it was written, by the first set. An answer that is handed in after the loop
  asked is an answer; the text of the comparison names the runs in which the loop
  asked and how each of them ended. **All five criteria held**, and every run ended
  with an answer. **The loop asked in none of the thirty runs**: no turn of them ended
  without the call, and the text of the comparison names no run.

| Claim | Strength | What it does not cover |
|---|---|---|
| Asked for the call after a turn that held the answer as text, the model hands the answer in | shown at the two ends of dev-02: 20 of 20 responses, where 18 had been fixed as enough | Two conversations of one question, each sent ten times as one request and not as a run. Nothing about how often a turn ends this way, and nothing about an end that looks different: the end of eval-13 was not sent. The maintainer graded the twenty answers by hand afterwards, all twenty right: that is no part of the reading fixed before the requests, and the grader had been told what the rule finds in the answers (nothing missing in any of them) |
| With the new prompt the development runs do what they did before | shown: the comparison passed, by the five criteria of the second set, which was fixed before the runs | The loop asked in none of these runs, so they say nothing of the message. A run that is not asked reads the same texts as a run before the change, so that all thirty ended with an answer, where two of the thirty before had not, is no effect of the change. The judge stands in for a person in the fourth criterion, since nobody graded the sheet |
| The loop gets an answer out of a run that would have ended without one | not shown by a run | No run with the model behind it has been asked by the loop yet. What stands for it is the twenty requests, a test that holds the request the loop sends after it has asked to be the request that was sent in them, and tests of the loop with replies that are made up |

This stays small: two conversations of one question sent again, and thirty runs that
never met the case. It says nothing of how often a run ends this way. The run of the
evaluation that ended so is not sent again and stays a run without an answer, and the
twenty questions of the evaluation are not run with the new prompt.

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
against the conditions as soon as it is written: the ones that name the texts the code
has, which the command says at its start. The code as it is now has the tool texts
`staged-6` and `flat-5` and the prompt `p3-tool`, so runs of the evaluation as it was
are made with the code as it was (`70c7384`). The repetition is the outer loop, and
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
been changed, when the code has texts that no conditions name, when the folder holds
runs of another question file, or runs made by
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
  otherwise. A question whose answer key has an item for a person never comes out
  `right`, and every question of the evaluation has one. This is not the verdict: a
  person grades every answer. The rule stands beside that grade as a check that needs no
  model: it finds the answer that lacks a number or has "found" the wrong way round.

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
  turns, calls that gave nothing new, and the cost worked out from the usage. For
  records that say whether the loop asked again for the call ("Asking one question"),
  also how many answers came only after it had.
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

## A survey of which papers can be read

The evaluation asks its questions of papers that one person had read, most of them from
one archive. It says nothing of the papers the reading tools turn away: a paper that
arXiv has only as a PDF, a source the section parser cannot split. The survey counts
them. It draws papers from the thirteen archives of arXiv's physics group by a rule that
was fixed beforehand, gives each to the source the tools use, and writes down whether
it came back split into sections, and if not, why not. No model is asked anything, and
nothing is graded.

It is a measurement that is made once. It does not make the server one "for all of
physics": the questions of the evaluation are still about one corner of it.

**It has been run, and its outlines have not been checked by hand yet.** The repository
holds the rule, the commands, the sample and the outcomes, and the table is under "What
came back". They came in commits one after the other: the plan was in the history before
the papers were drawn, and the sample before the survey was run. Nothing but that order
shows that the papers were not picked.

### The plan

`eval_data/survey_plan.json` names what the survey is about, in a form the commands read.

| | |
|---|---|
| Population | the papers whose primary category is one of the 51 categories of the physics group (13 archives: astro-ph, cond-mat, gr-qc, hep-ex, hep-lat, hep-ph, hep-th, math-ph, nlin, nucl-ex, nucl-th, physics, quant-ph; arXiv's taxonomy as read on 2026-11-24), and that arXiv's API returns for `submittedDate` from 2026-08-01 00:00 to 2026-10-31 23:59 GMT, asked month by month |
| Sample | 40 papers of every archive, 520 in all |
| Order | every paper gets the SHA-256 of `<seed>:<its identifier without the version>`, and the papers of an archive are taken from the smallest value up. The seed is 20261124, the day the plan was written |
| Check by hand | of the papers of every archive that were split, the first 5 of the same order: 65 outlines held against the papers |

The order uses no random number generator, so it does not rest on how a library is
written: with the list and the seed, anyone can work it out again. A larger sample
drawn later holds the smaller one. The categories are asked for one by one, because the
API returns nothing of an archive's categories for the name of the archive alone (on
2026-11-23 a search limited to `cat:astro-ph` found no paper, and the same search
limited to `cat:astro-ph.GA` found papers). The answer to `cat:` holds cross-listed
papers too; a paper is kept under its primary category only, so it is in the
population once.

A plan is fixed once a sample has been drawn under it. Another window, seed or number
of papers is another plan, in a file of its own.

### Drawing the sample

```
uv run python -m hepph_paper_miner.survey.sample --plan eval_data/survey_plan.json --population results/survey/population.jsonl --sample results/survey/sample.jsonl
```

asks arXiv for every category in every month (153 requests at the least, three seconds
apart) and writes two files: every paper of the population, and the papers drawn from
it. It does not start unless the plan is a file of a commit and no file the repository
keeps has been changed, and it does not write over a file.

A sample is as good as the list it is drawn from, and the API can answer with status 200
and less than it was asked for. So a list counts only when it is whole: every page says
the same total and begins where it was asked to, the pages together hold that many
papers and none twice, every paper carries a version, a primary category and the time
of its first version, and a category that is said to hold nothing in a month says so a
second time. A piece that fails is thrown away and asked for again, three times at
most; then the command stops and writes nothing. It also stops when a paper says that
its first version was submitted outside the month it was returned for: the manual of
the API does not say which version `submittedDate` is about, and the plan takes it to
be the first.

`--only hep-lat,nucl-ex` is for a first try: it asks for these categories, says what
came back, under which primary categories and after how long, and writes nothing.
`--page-size` sets how many papers one request asks for (1,000 unless told otherwise,
2,000 at the most).

**What was drawn.** The command was run on 2026-11-23 by `a3ddd0b`, the commit that
brought the plan (made at 16:52 UTC that day), and arXiv gave the answers the list is
made of from 17:59 to 18:10 UTC. It listed 49,627 entries in the 153 pieces, a
cross-listed paper once for every category it is listed in. No entry carried a first
version from outside the month it was returned for, or the command would have stopped.
29,285 papers have one of the 51 categories as their primary category, and 520 of them
were drawn.

| Archive | Listed | Papers of the archive | Drawn |
|---|---|---|---|
| astro-ph | 9,161 | 5,762 | 40 |
| cond-mat | 10,431 | 6,125 | 40 |
| gr-qc | 2,514 | 1,544 | 40 |
| hep-ex | 1,067 | 351 | 40 |
| hep-lat | 357 | 142 | 40 |
| hep-ph | 2,727 | 1,941 | 40 |
| hep-th | 2,852 | 1,550 | 40 |
| math-ph | 2,521 | 617 | 40 |
| nlin | 845 | 339 | 40 |
| nucl-ex | 422 | 131 | 40 |
| nucl-th | 903 | 450 | 40 |
| physics | 9,505 | 5,432 | 40 |
| quant-ph | 6,322 | 4,901 | 40 |

`results/survey/population.jsonl` is the list: what arXiv said each piece holds, and for
every paper its identifier, its primary category and the time of its first version.
`results/survey/sample.jsonl` holds the 520 papers in their order. A test draws the
sample again from the list and holds it against that file
(`tests/test_survey_results.py`), and it fails when the plan is no longer the file the
sample was drawn under.

Forty papers are almost a third of one archive (nucl-ex, 131 papers) and less than a
hundredth of another (cond-mat, 6,125), so a count over all 520 is not a share of the
physics group. And the papers are drawn by archive, not by category: 42 of the 51
categories have a paper among them.

### Running it

```
uv run python -m hepph_paper_miner.survey.run --sample results/survey/sample.jsonl --out results/survey/outcomes.jsonl
```

fetches and splits every paper of the sample as `get_outline` would (two requests for a
paper the first time, so 52 minutes at the least for 520 papers), in the version the
sample names, and writes a line for each:

| Outcome | Meaning |
|---|---|
| `ok` | split into sections. The line holds the numbers of sections and subsections, the characters, the size of the largest piece one call can be asked for, and whether the paper has a section heading at all |
| `no_full_text` | arXiv has no TeX source of the paper: a PDF (`not_tex`), or nothing to download (`no_source`) |
| `parse_error` | there is a source and the parser turned it away. The sentence of the parser is kept, and sorted into kinds: `no_document` (no `\begin{document}`: plain TeX, or the notice of a withdrawn paper), `missing_file`, `unfollowed_command` (`\import` and its relatives), `too_short`, and a few more |
| `not_found`, `unexpected` | arXiv lists no such paper; or the code raised an error of its own. Neither is expected, and each is counted |
| `unanswered` | arXiv was busy, took too long, or sent something that was not the paper's files. This says nothing of the paper, and **it is not an outcome** |

The survey is done when no paper is left `unanswered`: the command ends with code 1
while one is, and run again, it asks again. What arXiv answered is on disk, so only the
papers without an answer cost requests. Every run goes through the whole sample and
writes the whole file anew, so every line of a file was made by one version of the
code, and the first line names it (the commit, the version of the parser). A paper that
stays unanswered however often it is asked is reported as that, with the sentence it
came back with; a paper that was submitted as HTML is one, today.

A paper that was split is not thereby a paper that is easy to read. Two shapes are
counted beside the outcomes: a paper without any section heading comes back as one
piece, and a piece of more than 20,000 characters takes more than one call of
`read_section`.

`--limit 52` is for a first try: the first four papers of every archive, what came
back, and how much the folder of downloads grew. It writes nothing. While the survey
runs, nothing else on the machine should ask arXiv: the three seconds between requests
are kept inside one process, and a server that a desktop app started is another one.

The first try was run on 2026-11-23 UTC, after the sample had been drawn and before it
was committed. What it showed of 52 papers could not change the sample: the sample is
what the rule draws from the list, and the test draws it again.

### What came back

The command was run three times by `ceea850`, the commit that brought the sample: twice
on 2026-11-24 and once on 2026-11-25 (UTC). The first run, from 13:45 to 16:10 UTC, left
67 of the 520 papers unanswered (`upstream_busy` 63, `timeout` 4). The second, from
17:25 to 17:40 UTC, got an outcome for 64 of them and left 3 (`timeout`). The third,
from 01:59 to 02:00 UTC the next day, got an outcome for those 3, so no paper is left
unanswered. A line that a run had filled is the same line in the file of every run after
it.

| Archive | Papers | Split into sections | No TeX source |
|---|---|---|---|
| astro-ph | 40 | 39 | 1 |
| cond-mat | 40 | 30 | 10 |
| gr-qc | 40 | 40 | 0 |
| hep-ex | 40 | 40 | 0 |
| hep-lat | 40 | 40 | 0 |
| hep-ph | 40 | 40 | 0 |
| hep-th | 40 | 40 | 0 |
| math-ph | 40 | 40 | 0 |
| nlin | 40 | 39 | 1 |
| nucl-ex | 40 | 37 | 3 |
| nucl-th | 40 | 39 | 1 |
| physics | 40 | 30 | 10 |
| quant-ph | 40 | 40 | 0 |
| all | 520 | 494 | 26 |

No paper was turned away by the parser (`parse_error`), none was missing from arXiv
(`not_found`), and none came back in a way nobody foresaw (`unexpected`). Of the 26
papers without a TeX source, arXiv has 24 as a PDF, PostScript or DVI file (`not_tex`)
and nothing to download for 2 (`no_source`).

Of the 494 papers that were split, 26 have no section heading and come back as one
piece, and 125 have a piece of more than 20,000 characters, which takes more than one
call of `read_section`; 22 papers are both.

How far these numbers go:

- A row is 40 papers. Forty of forty does not say that every paper of the archive can be
  split: an archive of which 93% can be gives forty of forty about one time in twenty.
- The last row counts the sample. It is not a share of the physics group, because the
  archives were not drawn at one rate (forty papers of 131 and forty of 6,125). Weighted
  by the number of papers each archive has in the list, the share that was split is 90%,
  with a standard error of about 2 points; unweighted it is 95% (494 of 520). The
  weights were in the repository before the survey was run. That a weighted share is
  given was decided after the second run, when the outcomes of 517 papers had been seen.
- "Split into sections" is what the parser returned. Whether those are the sections of
  the paper is the question of the check by hand below, which has not been made yet.

`results/survey/README.md` says what the files are and how the three runs went, and
gives the two shapes archive by archive.

### Holding outlines against the papers

"Split into sections" says that the parser returned sections, not that they are the
sections of the paper. So some outlines are looked at by a person:

```
uv run python -m hepph_paper_miner.survey.sheet --plan eval_data/survey_plan.json --sample results/survey/sample.jsonl --outcomes results/survey/outcomes.jsonl --sheet runs_private/outline-sheet.csv
```

writes a sheet with the papers the plan fixes (of every archive, the first 5 of the
order that were split) and under each its outline as the server gives it. The person
opens the paper and writes two verdicts on its row. `sections` is `same` when the
headings the paper has at the level of a section are the rows that are not indented:
as many, in the same order, each the same heading. `subsections` is the same one level
down. A title that only looks different because the sheet shows TeX as it was typed is
no difference, and neither are the numbers in front of a heading, the list of
references (which the parser leaves out on purpose) or anything below a subsection
(where it does not cut). A heading of the paper without a row is a difference, as is a
row that is no heading of the paper, another order or another title. The rules stand in
full at the top of `src/hepph_paper_miner/survey/sheet.py`, and they were written
before any outline of the sample had been seen.

The sheet holds section titles, which are text of the papers, so it stays in
`runs_private/`. With `--checks results/survey/outline-check.jsonl` added, the command
reads the filled sheet and writes what the repository keeps: for every paper its
identifier, the two verdicts and the note of the person who checked.

### What it says, and what it does not

It says: of the papers drawn by this rule, so many of each archive were split into
sections, and the rest failed for these reasons ("What came back"). It will say, once a
person has looked: of the outlines that were looked at, so many were the outline of the
paper.

It does not say that the server answers questions about such papers: that takes
questions, and is another evaluation. It says nothing of papers from other years. The
sources of the 1990s are written differently (plain TeX), and none of them is in three
months of 2026. And 40 papers of an archive leave a share uncertain by about 15
percentage points either way where it is widest (the 95% interval of a share near one
half).

## Paper text and the cache

Downloads from arXiv are kept in `~/.cache/hepph-paper-miner` (set
`HEPPH_PAPER_MINER_CACHE` to use another folder), outside this repository. Paper text
is never committed, and neither is a run record that contains it. The one exception is
`tests/fixtures/arxiv-2610.26648v1/`: a paper under CC0 by the maintainer of this
repository, used to test the section parser. The files of the survey under
`results/survey/` hold identifiers, categories, dates, counts and the sentences of the
parser, and no title, abstract or text of a paper.

The folder has no expiry. An answer of arXiv that could be used is kept for good, and
the same request is not sent again. That holds for a search too: a search that listed
at least one paper gives the same list whenever it is asked again on this machine, so
it does not show a paper that came to arXiv later. The first line of a result names
the day on which arXiv gave the answer (`as of`). Two answers are not kept: a search
that listed nothing, and the lookup of an identifier without a version, whose latest
version can change. To ask arXiv again, delete the folder or name another one.

This project uses arXiv's API and source downloads. It is not affiliated with or
endorsed by arXiv.

## License

MIT. See `LICENSE`.
