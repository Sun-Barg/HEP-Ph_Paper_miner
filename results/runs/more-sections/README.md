# Runs with parser 5: what will be run, and how it will be read

Parser `5` begins a section in more places than parser `4` did, and no longer leaves out
a letter that supplemental material follows in the same file ("A parser that begins a
section in more places" in the README of the repository; `6aaf20f`). No run has been
made with it. This file says what will be run with it and how each thing will be read.
The commit that brings it holds no record of such a run, and what comes back will be
added to this folder under a heading of its own, with this text left as it is.

Three things will be run: six questions about six papers that the two parsers split
differently, asked with each parser; the five development questions again; and the
sample of the survey, split again. Nothing of this is a result of the evaluation, whose
twenty questions are not asked again.

## 1. Six questions about papers that the two parsers split differently

### Why the questions that exist cannot show the change

The development questions and the three target questions of 2026-11-20 read two papers:
the maintainer's own (`2610.26648v1`) and `1601.05089v3`. `tests/test_own_paper.py` holds
that the first has the same outline under both parsers. A Claude session split the second
by both, with a script that is not in this repository, and got the same sections with the
same text. A run of those questions with parser `5` is given what a run with parser `4`
was given, so it can say nothing of the change. The questions below are about papers in
which the change reaches the place of the answer.

### The six papers

All six are papers of the survey's sample (`results/survey/sample.jsonl`). They were not
drawn. A Claude session, the one that wrote the change to the parser and this plan, chose
them among the papers of the sample that the two parsers split differently, from their
sources in the folder of downloads and with scripts that are not in this repository:
the one paper it had found in which parser `4` left the letter out, and five letters that
parser `4` returned as one section and parser `5` cuts at titles run into the paragraphs.
Five are in hep-ex and one in hep-th.

| question | paper | under parser 4 | the passage under parser 4 | the passage under parser 5 |
|---|---|---|---|---|
| sec-01 | `2610.39042v1` | ten sections, 31,251 characters: the supplemental material. The letter in front of it is left out | nowhere | section `0` (no heading, 24,532 characters), in the first of its two pieces |
| sec-02 | `2608.11124v1` | one section, 27,811 characters | section `1`, in the second of its two pieces | section `u10` (1,290 characters) |
| sec-03 | `2609.20949v1` | one section, 26,452 characters | section `1`, in the first of its two pieces | section `u5` (1,818 characters) |
| sec-04 | `2608.26881v1` | one section, 35,197 characters | section `1`, in the second of its two pieces | section `u5` (1,811 characters) |
| sec-05 | `2610.05980v1` | one section, 32,708 characters | section `1`, in the second of its two pieces | section `u7` (8,043 characters) |
| sec-06 | `2610.37318v1` | one section, 21,542 characters | section `1`, in the first of its two pieces | section `u6` (502 characters) |

The sizes under parser `4` are those of `results/survey/outcomes.jsonl`, and a test holds
them to it. A piece is what one call of `read_section` returns, 20,000 characters at the
most; the first piece of the five sections of parser `4` ends after 19,100 to 19,966
characters. The places, the pieces and the sizes under parser `5` are what the code of
each parser said of the sources in the folder of downloads (`eval.check` on each question
file, and the cut of `read_section`); no file of this repository holds them yet. The sample of the survey split again (3
below) will hold the sizes of the six papers under parser `5`.

### The questions

`eval_data/questions_sections_parser4.jsonl` (SHA-256
`f60ee6da61f4e9ec7034c2c9d996ac7db6197b82b3721dc8752ca5dd90f7fda0`) and
`eval_data/questions_sections_parser5.jsonl` (SHA-256
`717f1709c7a34b8775667a299ab123f87d370f07de11059d65fc5a31130a1076`) hold the same six
questions. A question names the section its passage stands in, and a section has
another identifier under each parser, so there is a file for each. They differ in those
identifiers and in nothing else: the questions, the pieces of text that mark the
passages, the reference answers, the answer keys and the notes are the same, and
`tests/test_section_questions.py` holds that.

Every question names its paper, so that no search has to find it, and none can be
answered from the abstract. In sec-02 to sec-06 the passage stands under a title that is
run into a paragraph, and the question asks for what that title names. In three of the
five (sec-02, sec-04, sec-05) the passage lies behind the first piece of the one section
parser `4` makes, so that a staged run with parser `4` has to ask for the second piece to
be given it; in two (sec-03, sec-06) it lies within the first.

The session that chose the papers drafted the questions, the reference answers and the
answer keys from the sources. The maintainer held each question, its answer and its
passage against the paper before this file was pushed.

With parser `4`, `eval.check` names one problem in its file, and is meant to: the passage
of sec-01 is not in the paper as parser `4` splits it. With parser `5` it names none.

### The runs

Each side is `eval.run` over its question file: six questions, both layouts, three times,
36 runs that count. The model, its settings and the limits are those of the evaluation.

- **Before.** The code of `e7e9576`, the last commit with parser `4`. It has the tool
  texts `staged-6` and `flat-5` and the prompt `p3-tool`, so its runs are held against
  `ASKING_AGAIN` (`eval/conditions.py`). It is checked out into a second working tree,
  and the question file of parser `4` is copied into it, where no commit of that tree
  knows it:

  ```
  git worktree add ..\HEP-Ph_Paper_miner-parser4 e7e9576
  cd ..\HEP-Ph_Paper_miner-parser4
  uv sync
  copy ..\HEP-Ph_Paper_miner\eval_data\questions_sections_parser4.jsonl eval_data\
  uv run python -m hepph_paper_miner.eval.run --questions eval_data/questions_sections_parser4.jsonl --questions-sha256 f60ee6da61f4e9ec7034c2c9d996ac7db6197b82b3721dc8752ca5dd90f7fda0 --out ..\HEP-Ph_Paper_miner\results\runs\more-sections\sections-before
  ```

- **After.** The code of `main` as it is then, which has parser `5` and the same texts,
  so its runs are held against `MORE_SECTIONS`:

  ```
  uv run python -m hepph_paper_miner.eval.run --questions eval_data/questions_sections_parser5.jsonl --questions-sha256 717f1709c7a34b8775667a299ab123f87d370f07de11059d65fc5a31130a1076 --out results/runs/more-sections/sections-after
  ```

The side before is run first and the side after right behind it, on one day. The
sources of the six papers are in the folder of downloads already, so no run of either
side waits for arXiv to send one.

### Each side is graded by its own code

`eval.regress` cannot hold these two sides against each other. It grades both with the
code that runs it and against one question file, and where a passage stands is worked
out from the paper as that code splits it (`eval/grade.py`). A record of the side
before says that a run was given characters 0 to 20,000 of section `1`. Under parser `5`
these papers have no section `1`.

So each side gets a sheet, a record of the judge and a report of its own: `eval.sheet`,
`eval.judge` and `eval.report --conditions asking-again` in the second working tree for
the side before, with the question file of parser `4`; `eval.sheet`, `eval.judge` and
`eval.report --conditions more-sections` on `main` for the side after, with the file of
parser `5`. The six files are written into this folder
(`sections-before-sheet.csv`, `-key.csv`, `-j2.jsonl`, `-report.md`, and the same four
with `after`). The table that holds the two sides beside each other is put together
from them here, and a test will hold it against the records and the two reports.

### What is counted

For each question, each layout and each side:

- **The runs in which the passage was given**, of three: from the report of the side.
- **The characters of the tool results** (the median of the three runs) and **the
  responses** each run took: both stand in the last line of a record, and need no parser.
- **The answers that are right**: by the judge `j2`, three requests an answer, on the
  sheet of the side. The judge reads the question, the reference answer and the note of
  the question, which the two files share. An answer that the judge calls wrong in a
  request is read by the maintainer, and a grade the maintainer writes on a sheet is the
  verdict. A run without an answer is wrong.

### How it is read

This was written before any of these runs. Nothing passes or fails.

1. **The passage, staged.** As `eval.regress --targets` reads it: "shown" when the
   passage was given in more staged runs after than before, counted over the questions,
   and in fewer runs of no question; "not shown" otherwise, also when the side before
   was given it every time. This is said twice: over all six questions, and over sec-02
   to sec-06 alone. With parser `4` the passage of sec-01 can be given to no run, so
   over all six "shown" takes nothing but staged runs after that read section `0`.
2. **The characters, staged, sec-02 to sec-06.** The questions in which the median after
   is lower than the median before are counted. With five questions on five papers the
   count is given as it is, and no test is made of it.
3. **The flat layout** is given beside both and decides nothing. It is given the whole
   text in one call under either parser. For sec-02 to sec-06 that is the same text but
   for the titles, which parser `5` takes out of the paragraphs and writes as lines of
   their own (21,604 to 35,259 characters under parser `4`, and within 150 of that under
   parser `5`). For sec-01 it is 31,825 characters under parser `4` and 59,146 under
   parser `5`.
4. **The answers** are counted for each side and layout. Whether an answer is right
   depends on the model as well as on what it was given, so the count is shown and no
   reading of it is fixed here.

### What is expected

- sec-01, before: the passage is given in none of the three staged and none of the
  three flat runs. This follows from the split and not from what a model does. A right
  answer needs the letter, so few of the six answers before, or none, are expected to be
  right.
- sec-01, after: the passage is given in the three flat runs, and in a staged run that
  reads section `0`.
- sec-02 to sec-06, staged: the median of the characters is lower after than before in
  each of the five. Before, the first piece of the one section alone has more than
  19,000 characters; after, the section that holds the passage has 502 to 8,043.
- sec-02 to sec-06, flat: the passage is given in three of three runs on both sides, and
  the characters are nearly the same.
- Not foreseen: in how many staged runs before the passage of sec-02, sec-04 and sec-05
  is given (the model has to ask for the second piece), and how many answers are right.

Where a count that follows from the split comes out otherwise (the first and the fourth
point), something is not as this text takes it to be, and that is looked into before
anything else is read from the runs.

### What it cannot show

The papers were chosen and the questions written by somebody who knew the change, on
the places it reaches, and the passages stand under titles that say what they hold. So
the runs can show that the change does what it was made for in these six cases: a
letter that was missing can be read, and a letter cut at its titles is read in smaller
pieces. They say nothing about questions in general, nothing about how many papers are
split better, and nothing about the outlines of parser `5`, which have been held against
no paper. The five letters set their titles off in ways the parser looks for; a letter
that sets them in bold or numbers them by hand stays one section under both parsers.
The two sides are run by two commits and name two question files, which no command of
this repository compares: the table is put together by hand from two reports, and the
test that holds it is written after the runs.

## 2. The development questions again

```
uv run python -m hepph_paper_miner.eval.run --questions eval_data/questions_dev.jsonl --out results/runs/more-sections/dev-after
uv run python -m hepph_paper_miner.eval.sheet --questions eval_data/questions_dev.jsonl --runs results/runs/more-sections/dev-after --sheet results/runs/more-sections/dev-sheet.csv --key results/runs/more-sections/dev-key.csv
uv run python -m hepph_paper_miner.eval.judge --questions eval_data/questions_dev.jsonl --sheet results/runs/more-sections/dev-sheet.csv --out results/runs/more-sections/dev-j2.jsonl
uv run python -m hepph_paper_miner.eval.regress --questions eval_data/questions_dev.jsonl --criteria 2 --before results/runs/asking-again/dev-after --after results/runs/more-sections/dev-after --sheet results/runs/more-sections/dev-sheet.csv --key results/runs/more-sections/dev-key.csv --judge results/runs/more-sections/dev-j2.jsonl --out results/runs/more-sections/regress-dev.md
```

Thirty runs, held against the thirty of 2026-11-23 (`../asking-again/dev-after/`) by the
second set of criteria of `eval/regress.py`, as those were held against the runs before
them. The rule of this repository asks for it: runs made before a change are no runs of
what comes after.

Said before the runs: the two papers these questions read are split alike by both
parsers (above), so the two sides differ in the day they were run and in the commit,
and in nothing a model reads. Passed or failed, the comparison says nothing of what
parser `5` does. A criterion that fails is looked into like any other, and is not put
down to the parser unless a record shows text that parser `4` did not return.

## 3. The sample of the survey, split again

```
uv run python -m hepph_paper_miner.survey.run --sample results/survey/sample.jsonl --out results/survey/outcomes-parser5.jsonl
```

The same 520 papers, by the code of `main`, into a file of its own. The outcomes of
parser `4` (`results/survey/outcomes.jsonl`) stay fixed, and so does the check of the
65 outlines, which was made of them. What arXiv answered for the sample is in the folder
of downloads, so the command is expected to ask arXiv for little or nothing. A paper
that comes back `unanswered` is no outcome, as before: the command is run again, and a
paper that stays unanswered is reported beside the numbers.

What is read from the two files, line against line:

- **Papers that parser `4` split and parser `5` does not.** Their number, and each by
  its identifier. None is expected.
- **Papers whose line differs** in the number of sections or subsections, in the
  characters, in the largest piece or in having no section heading: their number.
- **The two shapes**, beside the 26 and the 125 of parser `4`: the papers without any
  section heading, and the papers with a piece of more than 20,000 characters.

How far that goes, said before: a paper leaves the count of papers without a section
heading as soon as parser `5` makes one section in it, also when that section is the
acknowledgements and the rest is one piece as before. So a lower count is not read as
that many papers cut at their titles, and a line of the outcomes cannot tell the two
apart; the papers with a piece of more than 20,000 characters are the count to read for
that. No outline of parser `5` is held against a paper, so nothing is said of whether
the new sections are the sections of the papers. And the papers that carry a second
document, which neither parser reads, are not counted: a line of the outcomes has no
field for it, and none is added, so that the lines of the two files can be held against
each other field by field.

A test will hold what is then written of the two files against them.
