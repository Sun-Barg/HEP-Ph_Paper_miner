# Results of the evaluation

What the evaluation left behind. The README of the repository gives the main numbers and
says how strong each claim is. This file says what the files are, and goes through the
runs that went wrong.

| here | what it is |
|---|---|
| `runs/eval/` | the public records of the 120 runs, made on 2026-11-17 from 08:13 to 08:42 UTC by `70c7384` under the conditions of the evaluation |
| `grading.csv` | the sheet on which the maintainer graded the 118 answers by hand on 2026-11-18, without seeing the layouts |
| `grading-key.csv` | which run each row of the sheet stands for |
| `report.md` | the report that `eval.report` wrote from the three: every table, question by question |
| `runs/dev/` | the records of the runs on the development questions, with a README of their own. Nothing there is a result of the evaluation |
| `runs/regress/` | the records of the runs made on 2026-11-20, after the tool texts were changed, and what was made from them, with a README of their own. Nothing there is a result of the evaluation |
| `runs/asking-again/` | what was run on 2026-11-23, after the loop began to ask for the call when a turn ends without it: twenty requests that sent the end of two such runs again, the records of the development questions run once more, and what was made from them, with a README of their own. Nothing there is a result of the evaluation |
| `judge/` | a model as a second grader: its one run on the 118 answers and on 91 controls made to be wrong (`eval-j2.jsonl`, 2026-11-19, by `9711ca5`), the report that `eval.agree` wrote from it (`report.md`), and its two runs on the development answers. The grades by hand stay the verdicts; the README of the repository says what this shows and what it does not, and `tests/test_agree.py` holds the files against each other |

`eval_data/PREREGISTRATION.md` says what was measured and how each hypothesis is read,
and lists under Deviations what was done otherwise. `tests/test_results.py` holds the
four files against each other, and holds what is said below against the records.

## The three wrong runs

Of the 120 runs, 117 are right. The three that are wrong are staged, and two of them are
of one question.

### eval-15, second and third run: the passage was never read

The question is about the maintainer's own paper, the one kept in `tests/fixtures/` of
this repository. It repeats a statement of the paper and asks for a number that the
paper does not report. A right answer says that the number is not there, and that the
paper only states that such limits were derived. That statement stands in section `4`,
in the 1,072 characters before the heading of its first subsection. The outline shows
`4` with 18,876 characters and `4.1`, `4.2`, `4.3` with 17,644 together, and says that
the size of a section includes its subsections. That a section has text of its own,
which only a read of the section itself returns, has to be worked out from those
numbers: no tool text says it. All three staged runs read `4.1`, `4.2` and `4.3` and
went on to other sections.

- The first run read `4` itself with its thirteenth read, was given the passage, and
  answered right with its tenth response.
- The second never read `4`. With its twelfth response it answered that it had found no
  such statement in the paper, and named `4.1` to `4.3` as the sections on the subject
  that it had read. Graded wrong.
- The third asked for one more section with its twelfth response and was ended by the
  limit of twelve.

The three flat runs read the whole paper in one call and answered right with their
second response. The staged runs of this question were given 101,202 to 113,344
characters of tool results where a flat run was given 147,086, but over ten to twelve
responses. They took 3.7 times the input tokens of the flat runs (medians 251,330 and
67,581), most of them read from the API's cache, and the cost worked out for the three
runs is the same in both layouts ($0.51).

Every section of this paper that has subsections begins with such text, 292 to 1,804
characters of it. The tool texts are fixed with the conditions, so nothing was changed
while the evaluation ran. Afterwards they were (`staged-6`): the outline now shows how
much text a section has of its own, and a read can stop where that text ends. eval-15
was not asked again, so whether its runs would have gone differently is not known.
Three questions written for such text were asked before and after the change
(`runs/regress/README.md`).

### eval-13, third run: an answer written as text

The run asked for the same two outlines and two sections as the two other staged runs of
the question. Its third response then ended the turn with text, without a call of
`submit_answer`. The rule fixed before the runs reads no answer out of a text, and a run
without an answer is wrong, so this run is wrong in every count of the report. The
question still counts as right for staged, because the two other runs are right. Outside
that rule, the maintainer read the text of that response on 2026-11-18, knowing which
run it was, and graded it by the note of the question: right. By that reading, what
failed in this run is how the answer was handed in. The text is kept outside this
repository. It is one run of 120; none of the thirty runs of the third diagnosis
(`runs/dev/README.md`) ended this way. Two of the thirty runs made on the development
questions after the tool texts were changed did, both of one question; none of forty
more runs of that question did, twenty with the texts of the evaluation and twenty with
the changed ones (`runs/regress/README.md`). The loop has since been changed to ask for
the call when a turn ends this way (`runs/asking-again/README.md`). This run was made
before that, and stays a run without an answer.

## Tool calls that ended in an error

There are ten, and none of them because arXiv or the API failed. Five times a staged run
gave the section as `section` where the tool has `section_id`: in all three runs of
eval-08 and in two of eval-15, as in the third diagnosis. The call came back as an error
and the next one was right, at the price of one response. The five others are calls in
runs of eval-17, one staged and four flat, that asked for a second or third version of
its paper where the search of the run had listed the first; the tool answered
`not_found`.

## The limit of twelve responses

The limit was kept from development runs that took two to six. Here the staged runs of
eval-15 took 10, 12 and 12, those of eval-17 took 11, 8 and 9, and one flat run of
eval-17 took 8. The limit ended one run.

## The cost with and without the API's cache

The evaluation was run with the API's cache on, and the cost in the report is worked
out for that: $2.78 for the 60 staged runs and $10.90 for the 60 flat runs, a factor of
3.9. The cache changes what a token costs and not what the model reads, so the same
usage can be priced without it. Every input token at the plain price gives $5.00 and
$10.49, a factor of 2.1.

The cache moves the two layouts in opposite directions. A request pays a quarter more
for what it writes to the cache, and a twentieth of the price for what it reads from
it. A flat run is mostly over with its second response: the 60 runs wrote 4,147,361
tokens to the cache and read 876,362 back, and came out a little dearer than without
it. A staged run goes on for more responses, each asked for with the whole conversation
so far: the 60 runs wrote 832,385 tokens and read 1,384,589, at a little more than half
the price. So "staged costs a quarter of flat" is said of these runs with the cache on.
Without it, staged costs about half of flat.
