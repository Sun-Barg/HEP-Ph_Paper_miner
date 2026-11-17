# Pre-registration of the evaluation

Written before any run of the evaluation questions, and committed with them. Nothing here
changes after the first run; a change after it is listed under Deviations, with its date
and reason.

## 1. What is compared

The MCP server of this repository offers two tool layouts for reading arXiv papers:

- **flat** (`flat-4`): `search_papers`, whose results carry abstracts, and `read_paper`,
  which returns the whole text with a marker line before every section.
- **staged** (`staged-5`): `search_papers` without abstracts, `get_outline` (sections and
  their sizes), and `read_section`, up to 20,000 characters per call.

Two things change together, the abstracts in search results and the unit of reading, so
a result speaks of the two layouts, not of either factor alone.

## 2. Conditions

Every run is made under `src/hepph_paper_miner/eval/conditions.py`, frozen in `bcd431c`
(2026-11-17): model `claude-sonnet-5-5`, `max_tokens` 16000, adaptive thinking, effort
`high`, no answer format, prompt cache `ephemeral`, 2 retries of 600 s; the answer is
handed in through the loop's `submit_answer` tool with prompt `p2-tool`; parser `4`;
at most 12 responses, 700 s per tool call and 900 s per run. The runner adds
`--cache --show-thinking`; the model reads the same with and without the summaries of
its thinking. A record whose first line differs from the conditions stops the runner,
and the report names it.

The code is the commit that adds this file. The question file is
`eval_data/questions_eval.jsonl`, SHA-256
`67f83aa79c513843d7c105e20a788979783683e70aeaaca5157896bb2dc98281`, and the runs are
started with `--questions-sha256` set to it.

## 3. Questions

Twenty questions in English about thirteen papers (`eval_data/target_papers.txt`), seven
of them about the maintainer's own paper (arXiv:2610.26648v1). As `eval.check` counts
them: single_section 8, several_sections 6, not_in_paper 3, several_places 3; an answer
expected in 17 and "not in the papers" in 3; evidence in one section 11, in several with
all needed 6, in several with any one enough 3; a paper to be found by a search 5
(eval-06, eval-10, eval-11, eval-12, eval-17); a place that the first call of
`read_section` does not give 3 (eval-03, eval-04, eval-05); an abstract that is enough 0.
On 2026-11-17 the check found no problem, every number of the answer keys written in its
evidence, and each of the five papers to be found by a search listed by arXiv in the
version its question names.

The questions, reference answers, answer keys and notes were drafted by a Claude session
of the maintainer's research project and revised and committed by the maintainer.

The tool texts and the prompt were tuned on the five development questions only. The
conditions were frozen before any evaluation question was in the repository: the first
commit that holds one (`9045ab7`) is a child of `bcd431c`.

## 4. Runs

```
uv run python -m hepph_paper_miner.eval.run --questions eval_data/questions_eval.jsonl --out results/runs/eval --questions-sha256 67f83aa79c513843d7c105e20a788979783683e70aeaaca5157896bb2dc98281
```

120 cells: 20 questions × 2 layouts × 3 repetitions, in a fixed order. The repetition is
the outer loop; within it the questions come in the order of the file, and which layout
of a question runs first alternates from question to question and from repetition to
repetition. Each run is a process of its own.

A run is **spoilt** when arXiv or the API failed under it: a tool call that ended in
`timeout` or `upstream_busy`, or a run that ended in `api_error`,
`tool_transport_error`, `tool_timeout` or `time_limit`, or one that never wrote its last
line. Its cell is run again with the same repetition number after the pass, at most
twice; a cell spoilt three times is given up. The runner stops when the API refuses the
key, the credit or the spending limit, after three runs in a row that the API failed,
and when a record differs from the conditions.

## 5. What is measured

For each run that counts, from its public record and the parsed papers (`eval.grade`):

1. **Search**: for the five questions that do not name their paper, whether a search
   listed it, and at which rank.
2. a. **Access**: whether every character of the passage the answer rests on (the
   anchor of the question) was given to the model, and in which turn.
   b. **Citation**: whether the evidence the answer lists names the sections of the
   question, section for section (strict) or with the section around a subsection
   (loose).
3. **Answer**: graded by hand (Section 8), right or wrong, with no partial credit. A run
   without an answer is wrong. What the rule of `eval.grade` says is reported beside the
   hand grade, and is not the verdict.

Volume: **tool result characters** as the model received them (the measure of H1);
input tokens (new, written to the cache and read from it); paper text given, each
character counted once; tool calls; responses; cost worked out from the usage at the list
prices read on 2026-11-17 (input $2, cache write $2.50, cache read $0.10, output $10 per
million tokens). Exploratory: calls that gave nothing new; responses from the moment the
passage was given to the answer; tool errors by kind; why wrong runs were wrong, from
their records.

## 6. Hypotheses, and how each is read

The unit is the question, because the three runs of a question are not independent
samples (Section 9).

- **H1**: staged gives the model less tool result text than flat. For each question and
  layout, the median of its runs that count. Reported: the number of questions whose
  staged median is lower, higher, and equal, and the p of a one-sided exact sign test
  with ties left out. The p is reported as it comes; no threshold is fixed in advance.
- **H2**: staged does not answer clearly worse than flat. A layout answers a question
  right when more than half of its runs that count are right: two of three, and both
  when a cell given up leaves two. Reported: the paired table of questions (both right,
  staged only, flat only, neither). No threshold is set: twenty questions cannot show
  that the two are the same.
- **H3** (exploratory): staged makes more tool calls, and its wrong runs gather in "its
  paper was given but not the passage".

The results are reported whichever way they point. The same tables come from
`eval.report`.

## 7. Exclusions

Only spoilt runs are left out, and their records are kept and counted in the report. No
other run is left out: a run that reaches the turn limit, ends without an answer, or
meets a tool error counts, and without an answer it is wrong.

## 8. Grading by hand

When every cell is done, `eval.sheet` writes the sheet and its key. The sheet shows each
answer and its `found`, and for each question its text, reference answer and what is
accepted; not the layout, the repetition, the run, the cited sections or the rule. The
key stays in `runs_private/`, unopened, until every row is graded. The grader is the
maintainer, and the criteria are the `accept_note` of each question. Then `eval.report`
reads the records, the sheet and the key.

## 9. Known limits, stated before the runs

- Twenty questions and three repetitions. In the third diagnosis the three runs of a
  cell repeated the same calls in six of ten cells, so runs are not treated as
  independent samples.
- One model, one effort, one prompt. The layouts differ in two factors at once.
- The questions were kept only when readers given the full text answered them as the
  reference does. Answers may then be right in both layouts, and the comparison rests
  on H1 and on access and citation more than on H2.
- The blinding is partial: the wording of an answer may hint at its layout, and the
  grader also revised the questions.
- Sonnet 5.5 knows the world up to June 2026. A fact of an older paper may be answered
  from memory; the maintainer's paper (October 2026) is later. Both layouts are exposed
  alike, and the access layer shows whether the passage was given.
- Five questions depend on a live arXiv search, which lists the latest version of a
  paper, while a run is graded against the version the question names. All five were
  listed in that version on 2026-11-17; a later replacement by the authors would show
  in the identifiers that the records keep of every search.
- The evidence of eval-05 stands in a figure caption. An answer that says the figure
  could not be seen is not marked down for that alone.
- Costs are worked out from the usage at list prices; they are not read from the
  Console.

## 10. Deviations

None yet.
