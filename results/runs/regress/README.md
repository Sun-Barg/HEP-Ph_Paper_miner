# Records of the runs made after the tool texts were changed

After the evaluation the tool texts were changed (`staged-6` and `flat-5`: "What was
changed after the evaluation" in the README of the repository). The twenty questions of
the evaluation were not asked again. What was run instead is here: the public records of
five sets of runs, all made on 2026-11-20 with the model and the settings of the
evaluation, and what was made from them. Nothing here is a result of the evaluation.

| folder | records | made (UTC) | code | tool texts | what was run | how the runs ended | cost |
|---|---|---|---|---|---|---|---|
| `target-before/` | 24 | 06:00 to 06:18 | `e66a854` | `staged-5`, `flat-4` | the three target questions with each layout, three times | 18 runs count, all answered; arXiv spoilt 6 more, which were run again | $1.96 |
| `dev-after/` | 30 | 06:54 to 07:00 | `1b2baa3` | `staged-6`, `flat-5` | dev-01 to dev-05 with each layout, three times | 28 answered, 2 ended by the model without an answer | $1.56 |
| `target-after/` | 18 | 07:01 to 07:05 | `1b2baa3` | `staged-6`, `flat-5` | the same as `target-before/` | 18 answered | $0.84 |
| `dev02-before/` | 20 | 07:50 to 07:54 | `e66a854` | `staged-5`, `flat-4` | dev-02 with each layout, ten times | 20 answered | $0.48 |
| `dev02-after/` | 20 | 08:01 to 08:06 | `1b2baa3` | `staged-6`, `flat-5` | the same as `dev02-before/` | 20 answered | $0.52 |

`1b2baa3` is the commit that changed the tool texts, and `e66a854` the one before it,
which has the texts of the evaluation. Every set was run by `eval.run`, so each run was
started as a run of the evaluation is, and its record names the conditions of its code:
those of the evaluation before the change, and after it the same with the new texts
(`EVALUATION` and `REVISED` in `eval/conditions.py`). The cost is worked out from the
usage at list prices, over every record of the folder.

The development questions are in `eval_data/questions_dev.jsonl`, the target questions
in `eval_data/questions_target.jsonl`. The runs of the development questions before the
change are the thirty of `../dev/diag-3-tool/`, made on 2026-11-16.

| file | what it is |
|---|---|
| `regress-dev.md` | what `eval.regress` wrote of `dev-after/` held against `../dev/diag-3-tool/` |
| `regress-target.md` | what it wrote of `target-after/` held against `target-before/`, with `--targets` |
| `regress-dev-sheet.csv`, `regress-dev-key.csv` | the sheet of the 28 answers of `dev-after/` and its key, as `eval.sheet` wrote them. Nobody graded it |
| `regress-dev-j2.jsonl` | the record of the judge `j2` on that sheet: 84 requests, each of which said `right` ($0.30) |

The two CSV files are kept byte for byte (`.gitattributes`), because the record of the
judge names the sheet by its SHA-256. `tests/test_regress_results.py` holds the files
against each other, and holds what is said below against the records.

## The development questions again: failed

`eval/regress.py` names five things the runs after a change have to do. They were
written there in `e66a854`, before any run of this folder was made. Held against the
thirty runs before, the thirty runs of `dev-after/` do three of them: the passage was
given in every run (2), no answer that the rule leaves to a person is wrong (4: by the
judge, since nobody graded the sheet), and in every question the staged runs were given
less text than the flat ones (5). They fail two:

- **1, every run ended with an answer.** The second flat run and the third staged run
  of dev-02 ended as `no_answer`.
- **3, the rule calls no answer wrong, and what it called right in every run before it
  calls right now.** A run without an answer is wrong by the rule, which makes two. The
  third is the third flat run of dev-03, which the rule now leaves to a person
  (`by_hand`) where it had called all six runs of dev-03 right before.

**The two runs without an answer.** Each asked for what the two other runs of its
question and layout asked for, was given the same text, and with it the passage. Its
last response then ended the turn with text, without a call of `submit_answer`: an
answer written as text, as in one run of the evaluation (eval-13, in
`results/README.md`). The texts are kept outside this repository. None of the six runs
of dev-02 before the change had ended this way.

**The answer of dev-03.** It gives the four values of the answer key. It then names two
more, of a case in the same paper, and says that it did not use that case. The key
lists those two as values that another channel has, and the rule leaves an answer in
which such a value occurs to a person; it does not call it wrong. The judge called this
answer right in all three requests. The second half of criterion 3 asks for more than
the rule means by `by_hand`. It was written before the runs, so it is applied as it was
written, and the comparison would have failed by the two runs of dev-02 alone.

## Do the changed texts make a run end without the call? Not shown

Two of thirty runs ended that way with the changed texts, and none of the thirty
before, which were made four days earlier. To tell the texts from the day, dev-02 was
asked again: ten times with each layout by the code before the change
(`dev02-before/`), and right after that ten times with each layout by the code after it
(`dev02-after/`).

How the count would be read was written down before these runs, in the notes of the
work on this repository and not in a commit, so the repository cannot show that it came
first. The runs of each side that end without an answer are counted. "More often with
the changed texts" is said only when a one-sided Fisher test of the two counts gives
less than 0.05; with twenty runs on each side that takes five such runs after against
none before, or six against one. Then the texts are changed once more. Anything else
is "no difference shown", and the comparison above stays failed either way.

None of the twenty runs before the change ended without an answer, and none of the
twenty after it. No difference is shown, and the texts were not changed again.

Forty runs show a large difference only. If one run in three with the changed texts
ended without the call, as two of the first six of dev-02 did, twenty in a row with an
answer would come about 3 times in 10,000. If one run in twenty did, it would come once
in three times. So the changed texts do not make a third of these runs fail, and
whether they make a few in a hundred fail is not known. Over every run in this
repository that counts and hands in its answer with the tool, 1 of 188 ended without
the call with the texts of the evaluation (eval-13) and 2 of 68 with the changed ones.
The two sets differ in their questions and in their days, so those two rates are not a
comparison.

## The three target questions: shown

The passage of each target question stands in the text that a section has before its
first subsection: for tgt-01 and tgt-02 in section `3` of the maintainer's paper, for
tgt-03 in section `6`. This is the text that the outline did not show before the
change. A Claude session that works on this repository, the one that also wrote the
change, drafted the three questions, and the maintainer reviewed them; they were
committed in `e66a854`, before any of these runs.

Nothing passes or fails here. What is counted is the staged runs in which the passage
was given to the model, which a program reads off the records. The answers were not
graded, by a person or by the judge.

| question | given before | given after | responses before | responses after | characters before (median) | characters after (median) |
|---|---|---|---|---|---|---|
| tgt-01 | 2 / 3 | 3 / 3 | 6 9 7 | 4 4 4 | 55,943 | 9,337 |
| tgt-02 | 0 / 3 | 3 / 3 | 8 7 7 | 4 4 4 | 41,529 | 11,992 |
| tgt-03 | 2 / 3 | 2 / 3 | 11 5 11 | 4 3 10 | 96,229 | 21,439 |

The passage was given in 4 of the 9 staged runs before the change and in 8 of 9 after
it, and in fewer runs of no question: `eval.regress` calls that "shown". All 9 flat
runs were given it both times, so the questions can be answered from the paper.

- In each of the eight staged runs after the change that were given the passage, the
  model read the section's own text with the `end` that the outline names
  (`read_section` of `3` with `end=1804`, or of `6` with `end=926`), and answered with
  its third or fourth response. The nine runs before took five to eleven.
- The ninth, the third run of tgt-03, read `6.1`, `6.2`, `6.3` and six other sections,
  and the own text of section `4`, but never that of `6`. With its tenth response it
  answered that the paper does not say.
- Before the change, the four runs that were given the passage had read the section
  itself, each after other sections. The three runs of tgt-02 and one run of tgt-01
  answered that the paper does not say.

What this does not show. The questions were written by somebody who knew the change,
to rest on exactly the text it brings into view. They are about one paper and two
pieces of text, and tgt-01 and tgt-02 rest on the same piece. They show that the change
does what it was made for in these cases. They say nothing about questions in general,
and nothing about eval-15, which was not asked again.

## What else the records show

None of this decides anything.

- No call came back as an error in the 48 runs of `dev-after/` and `target-after/`. In
  the thirty runs before, the three staged runs of dev-01 each gave the section as
  `section` and took a fourth response for it; after the change they took three.
  Whether the new error text had a part in that cannot be told, since no run met it.
- `end` was used 17 times in those 48 runs: 12 times to read the own text of a section
  (`3` nine times, `6` twice, `4` once) and 5 times for another part of a section.
- The staged runs of dev-05 took 6, 7 and 7 responses, where the runs before took 6, 6
  and 5, which is why `regress-dev.md` marks them. All three read the own text of
  section `3`, and two of them ran a search.
- The flat runs of `dev-after/` cost $1.11, and the flat runs before $1.89. That is the
  API's cache and not the tools. The cache keeps what a run sent for five minutes. The
  repetitions of a question came about two minutes apart after the change and about
  five before it, so the fifteen runs after wrote 376,910 tokens to the cache and read
  786,975 from it, where the fifteen before wrote 702,177 and read 583,966.

## Making the two texts again

```
uv run python -m hepph_paper_miner.eval.regress --questions eval_data/questions_dev.jsonl --before results/runs/dev/diag-3-tool --after results/runs/regress/dev-after --sheet results/runs/regress/regress-dev-sheet.csv --key results/runs/regress/regress-dev-key.csv --judge results/runs/regress/regress-dev-j2.jsonl
uv run python -m hepph_paper_miner.eval.regress --questions eval_data/questions_target.jsonl --before results/runs/regress/target-before --after results/runs/regress/target-after --targets
```

The first needs the paper of dev-03 from arXiv to say whether its passage was given;
without it that criterion is left open for dev-03. The second needs only the paper kept
in `tests/fixtures/`.
