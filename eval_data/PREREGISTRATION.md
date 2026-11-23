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

- **2026-11-18, grading (Section 8).** After the maintainer had graded all 118 rows,
  and before the report was made, a Claude session that works on the repository held
  the graded sheet against the `accept_note` of each question. It had read the public
  records of all runs, so it was not blind to the layouts. It pointed out one row: 86
  (eval-15), graded right, whose answer says that it found no statement that limits
  with fixed J-factors were derived, where the note asks for an answer that says they
  were derived and that no result of them is reported. The maintainer changed the
  verdict to wrong, not knowing the layout of the row; it is the second staged run of
  eval-15. With the first verdict the paired table of H2 reads 20, 0, 0, 0 (both right,
  staged only, flat only, neither), and with the second 19, 0, 1, 0. Section 8 names one
  grader and no second look at the grades, so the change is listed here. The
  `accept_note` in the question file is as it was.
- **2026-11-18, outside the counts.** The staged run of eval-13 that ended its turn
  with text, without a call of `submit_answer`, is wrong by Section 7. The maintainer
  read that text, knowing which run it was, and graded it right by the `accept_note`.
  No count of the report uses this.
- **2026-11-19, an analysis added after the results: a model as a second grader.**
  Nothing above changes: the grades by hand stay the verdicts, and no count of
  `results/report.md` moves. A judge, `eval/judge.py`, is asked to grade every row of
  the sheet of Section 8 from what the sheet shows the grader: the question, its
  reference answer, its `accept_note`, the answer and its `found`. It is not given the
  layout, the run, the cited sections, what the rule said, a grade, or a note the grader
  wrote while grading. The grader called 117 of the 118 rows right, so a judge that
  calls every answer right would agree on 117 of them. The judge is therefore also
  asked to grade 91 controls, answers made to be wrong, in
  `eval_data/judge_controls_eval.csv` (SHA-256 beginning `dcb047f6f0b675bd`): 27 of a
  kind that an `accept_note` calls wrong and 64 of other kinds, 71 of them a right answer
  of the sheet changed only where the fault lies and 20 written anew. A Claude session
  of the maintainer's research project drafted them, a Claude session that works on this
  repository held them against the rows they were made from, and the maintainer reviewed
  each one the way the sheet was graded and decided that it is wrong.
- The judge is `j2` (its texts SHA-256 beginning `38bc359e5841b16a`), the model and the
  settings of Section 2 (`claude-sonnet-5-5`, adaptive thinking, effort `high`,
  `max_tokens` 16000) without a cache. Every answer is asked three times, and the
  judge's verdict on an answer is the one that two or three of its requests gave. A
  Claude session that works on this repository wrote its texts, and the maintainer
  read them. They were changed on the five development questions only: `j1` called one
  of the 25 development controls right in one of its three requests
  (`results/judge/dev-j1.jsonl`); `j2` adds one sentence that asks the judge to think
  before it replies, and called every development control wrong in every request
  (`results/judge/dev-j2.jsonl`). No row of this sheet and no control of the evaluation
  had been given to the judge.
- The judge is run once, from the commit that adds this entry, on the 118 rows and the
  91 controls: 627 requests. A request that the API fails is asked again by starting the
  same command; a reply that is no verdict is kept, and an answer without a verdict of
  two or three requests has none.
- `eval/agree.py` writes `results/judge/report.md`. For the rows: the grade by hand
  against the judge's verdict, beside the 117 rows that a judge calling every answer
  right would agree on, and the rows where the two differ, with what the judge wrote.
  For the controls: how many the judge called wrong, by two or three requests and by
  all three, in all, by the kind of fault, by how they were made, by question, and
  against what the rule of `grade.py` says of the same text (47 `wrong`, 44
  `by_hand`). Then H2 again, with the judge's verdicts in place of the grades by hand;
  how often the three requests agreed; how many replies held a thinking block; and the
  cost from the usage. No rate of agreement is given alone.
- What this cannot show. The controls are made up: they show whether the judge tells
  wrong answers of these kinds, not whether it tells the wrong answers a model gives,
  of which the sheet holds one (row 86, whose grade was changed once). The controls of
  a question are made from one row, so they are not independent of each other. The 20
  controls written anew are shorter than the answers on the sheet. The judge is the
  model that gave the answers. The judge's texts were written by a Claude session that
  had read the graded sheet, its notes and these controls (the sentence that `j2` adds
  is the documentation's own); what stands is that none of them was given to the judge
  before its texts were fixed, as the first line of its record shows (the commit and
  the digest of the texts).
- **2026-11-19, a change to the code after the runs, under the same names.** The search
  told the error feed of arXiv by an entry whose id begins `http://arxiv.org/api/errors`.
  arXiv writes that id with `https://` now (seen on 2026-11-19), so an error feed was
  read as a search that found nothing, and the tool said so. Commit `e13cb0d` reads both
  forms, and such a search comes back as `[bad_query]`. A tool that answers the same
  call differently is to get a new name (`TOOLSET_VERSION` in `server.py`). The names
  `staged-5` and `flat-4` were kept. Of the 118 searches asked for in the records of
  the development runs and of the evaluation, 115 came back, and none of them had been
  answered with that feed: read as a search, the feed shows no paper of a total that is
  not zero, and the 41 searches that showed no paper all had a total of zero. So no
  recorded run would have read anything else. The lookup of a paper was not affected:
  an error feed there was `not_found` before and after. The same commit changes two
  checks of the commands that no model reads: `eval.run` now shows the traceback of a
  run that died, and `eval.judge` refuses to start from code whose state git cannot
  tell.
- **2026-11-20, the tool texts were changed after the runs, under new names.** Nothing
  above changes: no count of `results/report.md` moves, and the records of the
  evaluation stay held against the conditions of Section 2. Commit `1b2baa3` changes
  what a model reads and what a tool answers in four places. A call that holds an
  argument its tool does not have comes back as an error, and `read_section` and
  `read_paper` take an `end` (the SDK had dropped such an argument without a word, and
  four calls in the records of the evaluation carried one). The outline shows how much
  text a section has before its first subsection, which is where the passage of
  eval-15 stands. The description of the search says that small words are left out.
  And the search parts a word at an underscore. The texts have the names `staged-6` and `flat-5`. `eval/conditions.py`
  keeps the conditions of Section 2 as they were and names beside them what the code
  has now.
- The questions of the evaluation were not asked again with the new texts, and nothing
  is claimed for those texts on them: these questions are what suggested the change.
  Two other things were run on 2026-11-20, with the model and the settings of Section
  2. The five development questions were asked again and held against the thirty runs
  the conditions were fixed with, by five criteria that `eval/regress.py` names, written
  in the commit before the change (`e66a854`) and before any such run. And three
  questions whose passage stands in such text of a section
  (`eval_data/questions_target.jsonl`, SHA-256 beginning `63e37b9575d564b7`, in the same
  commit) were asked by the code before the change and by the code after it, to be
  counted and neither passed nor failed. The Claude session that wrote the change
  drafted the three, and the maintainer reviewed them.
- The comparison failed. Two of the thirty runs, one of each layout of dev-02, ended
  their turn with text and no call of `submit_answer` (criterion 1, and criterion 3,
  since no answer is wrong by the rule), and one answer to dev-03 is left to a person
  by the rule, which had called every answer to it right before (criterion 3). The
  three other criteria held. A
  measurement was added after that result: dev-02 again, ten times with each layout by
  the code before the change and by the code after it. How its count would be read was
  written down before it, in the notes of the work and not in this repository: "more
  often after the change" only for a one-sided Fisher test below 0.05. No run of the
  twenty before ended without an answer, and none of the twenty after, so no difference
  is shown; forty runs show a large one only. The texts were not changed again, and
  the comparison stays failed. On the three target questions the passage was given in
  4 of the 9 staged runs before the change and in 8 of 9 after it. The records, and
  what can and cannot be said of them, are in `results/runs/regress/`.
- **2026-11-23, the loop was changed after the runs, under a new name of the prompt.**
  Nothing above changes: no count of `results/report.md` moves, and the run of eval-13
  that ended its turn without the call stays a run without an answer, by the rule that
  was fixed before the runs. Since this change the loop asks for the call when a turn
  ends without it: the reply goes back as it came, with one message of the loop after
  it, once in a run. That message is a text a model reads, so the prompt of the way
  `tool` has a new name, `p3-tool`, and `eval/conditions.py` names a third set of
  conditions beside the two there were. The reason is the three runs that ended so, the
  one of the evaluation and two of dev-02 on 2026-11-20, each with its answer written
  as text; the API refuses a forced tool choice for this model, so the call cannot be
  made to come.
- The questions of the evaluation are not asked again with the new prompt, and the end
  of the run of eval-13 is not sent again either. What the runs with the new prompt
  will be held against was written down with the change, before any of them, in the
  README ("An answer that was written and not handed in"), in `eval/regress.py` (the
  second set of criteria) and in `eval/replay.py` (twenty requests, and the eighteen
  that decide how they are read).
- Both were run on 2026-11-23, from that commit (`0af1c02`). All twenty responses handed
  in an answer by the call, ten of each of the two conversations, where eighteen had
  been fixed as enough: the message got the answer handed in at these two ends, and no
  other way was tried. The thirty runs of the development questions passed, by the five
  criteria of the second set, held against the thirty of 2026-11-20 with the same tool
  texts; every run ended with an answer. The loop asked in none of the thirty, since no
  turn of them ended without the call. So no run has yet been asked by the loop, and
  what is shown of the message is the twenty requests: two conversations of one
  question. The records, and what can and cannot be said of them, are in
  `results/runs/asking-again/`.
- The same day, after that count, the maintainer graded the twenty answers by hand: all
  twenty right. No reading of this was fixed before the requests, and the grader had
  been told beforehand what the rule finds in the answers; the sheet and its key are in
  that folder.
