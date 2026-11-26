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

# What came back

Everything above this heading was written before any of it was run, and stands as
`44bca1f` brought it: `tests/test_section_questions.py` holds it to that commit letter
for letter. What it calls not run, and not in this repository yet, is said of that day.

The three things were run on 2026-11-25 (UTC) on the maintainer's computer, each right
behind the one before, with the model and the settings of the evaluation. The sheets,
the records of the judge, the two reports and the comparison of the development runs
were made there the day after. Nothing here is a result of the evaluation.

| here | holds | made (UTC) | code | parser | what was run | how it ended | cost |
|---|---|---|---|---|---|---|---|
| `sections-before/` | 36 records | 10:28 to 10:34 | `e7e9576` | `4` | sec-01 to sec-06 with each layout, three times, from the question file of parser `4` | 36 runs count, all answered | $0.66 |
| `sections-after/` | 36 records | 10:34 to 10:40 | `44bca1f` | `5` | the same from the question file of parser `5` | 36 runs count, all answered | $0.50 |
| `dev-after/` | 30 records | 10:40 to 10:46 | `44bca1f` | `5` | dev-01 to dev-05 with each layout, three times | 30 runs count, all answered | $1.90 |
| `../../survey/outcomes-parser5.jsonl` | a line for each of the 520 papers | 10:46 to 10:47 | `44bca1f` | `5` | the sample of the survey, split again | every paper has an outcome, none is unanswered | none: no model is asked |

`e7e9576` is the last commit with parser `4`. It was checked out into a second working
tree, as the plan says, and the question file of parser `4` was copied there. Neither
arXiv nor the API spoilt a run, so each folder holds one record for each cell of its
plan and no more. No call came back as an error, and the loop asked for the call in
none of the 102 runs. Every record names the conditions of its code
(`eval/conditions.py`): `ASKING_AGAIN` on the side before, `MORE_SECTIONS` in the two
folders of `44bca1f`. Held against the other of the two sets, a record differs in the
parser its results name and in nothing else. The cost is worked out from the usage at
list prices.

| file | what it is |
|---|---|
| `sections-before-sheet.csv`, `sections-before-key.csv` | the sheet of the 36 answers of `sections-before/` and its key, as `eval.sheet` wrote them in the second working tree. The maintainer graded rows 1 to 6 of the sheet afterwards (below, "The six answers that the judge called wrong") |
| `sections-before-j2.jsonl` | the record of the judge `j2` on that sheet, run in the second working tree: 108 requests, of which 90 said `right` and 18 `wrong` ($0.36) |
| `sections-before-report.md` | what `eval.report --conditions asking-again` wrote there from the records and the question file of parser `4` |
| `sections-after-sheet.csv`, `sections-after-key.csv` | the sheet of the 36 answers of `sections-after/` and its key. Nobody graded it |
| `sections-after-j2.jsonl` | the record of the judge on that sheet: 108 requests, each of which said `right` ($0.35) |
| `sections-after-report.md` | what `eval.report --conditions more-sections` wrote from the records and the question file of parser `5` |
| `dev-sheet.csv`, `dev-key.csv` | the sheet of the 30 answers of `dev-after/` and its key. Nobody graded it |
| `dev-j2.jsonl` | the record of the judge on that sheet: 90 requests, each of which said `right` ($0.32) |
| `regress-dev.md` | what `eval.regress --criteria 2` wrote of `dev-after/` held against `../asking-again/dev-after/` |

The CSV files are kept byte for byte (`.gitattributes`). Written again from the records
in the order of its key, each sheet comes out as the file that the record of the judge
names by its SHA-256. `sections-before-sheet.csv` is that file with the grades of six
rows written into it afterwards. `tests/test_more_sections_results.py` holds the files
against each other, against the question files and the conditions, and holds what is
said below against them.

## 1. The six questions

### The two sides beside each other

Each side is graded by its own code, as the plan says. Whether the passage was given is
taken from the report of the side, which was written on the computer that has the
papers. This repository does not keep them, so a test can hold these two columns
against the reports and no further. The characters and the responses stand in the last
line of a record. The reports were written without a sheet, so they hold no verdict on
an answer: the answers that are right are put together here from the records of the
judge and the grades of the maintainer. An answer is right by the judge when more than
half of its three requests say so, unless the maintainer graded it; here the three
requests said the same of every answer.

The staged layout:

| question | passage given, before | after | characters, before | after | responses, before | after | answers right, before | after |
|---|---|---|---|---|---|---|---|---|
| sec-01 | 0 / 3 | 3 / 3 | 13,708 | 22,297 | 5 6 5 | 3 3 3 | 0 / 3 | 3 / 3 |
| sec-02 | 3 / 3 | 3 / 3 | 29,105 | 2,658 | 4 4 4 | 3 3 3 | 3 / 3 | 3 / 3 |
| sec-03 | 3 / 3 | 3 / 3 | 20,754 | 11,864 | 3 3 3 | 3 3 3 | 3 / 3 | 3 / 3 |
| sec-04 | 3 / 3 | 3 / 3 | 9,862 | 7,572 | 3 3 3 | 3 3 3 | 3 / 3 | 3 / 3 |
| sec-05 | 3 / 3 | 3 / 3 | 16,645 | 9,397 | 4 4 4 | 3 3 3 | 3 / 3 | 3 / 3 |
| sec-06 | 3 / 3 | 3 / 3 | 21,196 | 1,922 | 3 3 3 | 3 3 3 | 3 / 3 | 3 / 3 |

The flat layout:

| question | passage given, before | after | characters, before | after | responses, before | after | answers right, before | after |
|---|---|---|---|---|---|---|---|---|
| sec-01 | 0 / 3 | 3 / 3 | 34,622 | 60,522 | 3 3 2 | 2 2 2 | 0 / 3 | 3 / 3 |
| sec-02 | 3 / 3 | 3 / 3 | 28,731 | 28,877 | 2 2 2 | 2 2 2 | 3 / 3 | 3 / 3 |
| sec-03 | 3 / 3 | 3 / 3 | 27,730 | 27,713 | 2 2 2 | 2 2 2 | 3 / 3 | 3 / 3 |
| sec-04 | 3 / 3 | 3 / 3 | 36,693 | 36,698 | 2 2 2 | 2 2 2 | 3 / 3 | 3 / 3 |
| sec-05 | 3 / 3 | 3 / 3 | 33,732 | 33,789 | 2 2 2 | 2 2 2 | 3 / 3 | 3 / 3 |
| sec-06 | 3 / 3 | 3 / 3 | 22,524 | 22,675 | 2 2 2 | 2 2 2 | 3 / 3 | 3 / 3 |

The characters are those of the tool results, the median of the three runs. The
responses are those of the three runs, in the order they were made.

### How it reads

By the four readings that the plan fixed. Nothing passes or fails.

1. **The passage, staged.** Over all six questions the passage was given in 15 of the
   18 staged runs before and in 18 of 18 after, and in fewer runs of no question:
   "shown", as `eval.regress --targets` reads it. All of that is sec-01. Over sec-02 to
   sec-06 alone it was given in 15 of 15 staged runs before and in 15 of 15 after: "not
   shown". The side before was given the passage every time, so there was nothing to
   gain.
2. **The characters, staged, sec-02 to sec-06.** The median after is lower than the
   median before in 5 of the 5 questions. No test is made of five.
3. **The flat layout** decides nothing. The passage of sec-01 was given in 0 of 3 flat
   runs before and in 3 of 3 after, and that of each of the five others in 3 of 3 on
   both sides, where the two medians are 5 to 151 characters apart.
4. **The answers.** Before, 15 of the 18 answers are right with each layout, and the
   three that are not are those to sec-01. After, 18 of 18 are right with each layout.
   No reading of these counts was fixed.

### What was expected, and what came

- **sec-01, before.** As expected: the passage was given in none of the six runs. The
  flat runs were given a text of 31,825 characters in 10 sections, the supplemental
  material, and the staged runs read five or six of those sections. Few of the six
  answers, or none, were expected to be right, and none is.
- **sec-01, after.** As expected: the passage was given in the three flat runs, whose
  text now has 59,146 characters in 11 sections, and in every staged run that read
  section `0`. All three did: two from its beginning to 20,000 characters, one from
  6,000 to 16,000.
- **sec-02 to sec-06, staged.** The median is lower after in each of the five, as
  expected, but in two of them not for the reason the plan gave. It said that the first
  piece of the one section alone has more than 19,000 characters. The staged runs
  before of sec-04 and sec-05 did not read that section from its beginning. Each run of
  sec-04 made one read of section `1`, from 26,000 or 27,000 characters to its end, and
  each run of sec-05 two, the first from 17,000 to 30,000. So their medians before are
  9,862 and 16,645 characters, below the 19,000 of that reason, and the medians after
  are 2,290 and 7,248 characters lower. In sec-02, sec-03 and sec-06 the runs before
  read the first piece, as the plan took them to.
- **sec-02 to sec-06, flat.** As expected: three of three on both sides, and nearly the
  same characters.
- **Not foreseen.** With parser `4` the passage of sec-02, sec-04 and sec-05 lies
  behind the first piece of the one section, and a staged run has to ask for more than
  the first piece to be given it. All nine runs did. Those of sec-02 read the first
  piece and asked for the rest with their next response; those of sec-04 and sec-05
  named where to begin, as above. How many answers would be right was not foreseen
  either: the table has it.

The plan names two counts that follow from the split, the first and the fourth of
these. Both came out as it takes them to be, so nothing had to be looked into before
the rest was read.

### The six answers that the judge called wrong

The judge called six answers wrong, each in all three of its requests: the six answers
of the side before to sec-01, three of each layout. Every one says that the paper does
not state what is asked (`found` is false), and that the text it was given is the
supplemental material. Each also names a figure file of that material whose name holds
`len50`, and does not take a length from it. The note of the question calls such
answers wrong.

The plan leaves an answer that the judge calls wrong to the maintainer, whose grade on
the sheet is the verdict. The maintainer read the six on 2026-11-26 and graded each
wrong, in rows 1 to 6 of `sections-before-sheet.csv`. The six rows have one note, in
Korean: the answer gives neither value, the two values stand in the letter and not in
the supplemental material (looked up in the PDF of the paper), and by the note of the
question an answer that says the paper does not state them is wrong whatever the tool
had returned. The sheet shows no layout. The grading was not blind to anything else:
the verdicts of the judge were known, and before the judge was run, a Claude session
that had read the records had told the maintainer that all six answers say the paper
does not state it.

Nobody graded the other 66 answers of the two sides. For them the judge stands alone,
as it does for the 30 answers of the development questions.

### What else the records show

None of this decides anything.

- **After, a staged run went to the section its question is about.** In each of the 15
  staged runs of sec-02 to sec-06 the model asked for the outline, read the section
  that holds the passage with its second response, whole (502 to 8,043 characters),
  and answered with its third. All three runs of sec-03 asked for `u6` in that same
  response (8,323 characters), and two of the three of sec-04 for `u1` (3,886), so the
  medians of these two questions hold a section that the passage is not in.
- **Before, a staged run took three or four responses** for these five questions, and
  five or six for sec-01. After, each of the 18 staged runs took three.
- **The sizes under parser `5`.** The plan gave them from the code of each parser and
  said that no file of this repository held them. The records do now: the first line
  of a result names the section and its size, and a record keeps what it names. They
  are the sizes of the plan's table, and the characters of each of the six papers are
  those of its line in `../../survey/outcomes-parser5.jsonl`.
- **Searches.** Nobody had to search: every question names its paper. Two flat runs
  before and two staged runs after of sec-01 searched all the same; the two searches
  after listed nothing.
- **The cost.** The 36 runs before cost $0.66, and the 36 after $0.50. The staged runs
  cost $0.34 before and $0.19 after, the flat runs $0.33 and $0.31.

### What it does not show

What the plan says under "What it cannot show" holds as it stands. The runs add this:

- "Shown" rests on one question about one paper. It says that the one letter that was
  found missing can be read now, and a model that was given it answered from it.
- In the five letters that parser `5` cuts at their titles, no run was given a passage
  that the runs before had not been given. With parser `4` a model got to the passage
  in one section of 21,542 to 35,197 characters every time: in the first piece, by
  reading on, or by naming where to begin.
- That the staged runs were given fewer characters is counted on five questions about
  five papers that were chosen for it, three runs each. How much fewer depends on what
  a model does with the one section of parser `4`, as sec-04 and sec-05 show. And the
  answers were right on both sides, so nothing here says that a smaller piece makes an
  answer better.
- The judge stands in for a person. Of the 72 answers a person graded six.

## 2. The development questions again: passed

`eval.regress --criteria 2` held the thirty runs of `dev-after/` against the thirty of
2026-11-23 (`../asking-again/dev-after/`), which `0af1c02` had made with the same tool
texts, the same prompt and parser `4`. All five criteria of the second set hold:

- **1, every run ended with an answer.**
- **2, the passage was given in every run.**
- **3, the rule calls no answer wrong.** It calls twelve right and leaves eighteen to a
  person.
- **4, no answer left to a person is wrong.** By the judge, since nobody graded the
  sheet: it called each of the thirty answers right in each of its three requests.
- **5, in every question the staged runs were given less text than the flat ones.**

As the plan said before the runs, this says nothing of what parser `5` does: the two
papers that these questions read are split alike by both parsers.

One sentence of the plan was not right. It says that the two sides differ in the day
and in the commit, "and in nothing a model reads". They differ in one more thing: the
first line of an outline and of a whole text names the parser. Both sides asked for the
outline and for the whole text of each of the two papers. Each of these four results
has the same length on both sides and another SHA-256, and what a record keeps of its
first line differs in the parser, `4` or `5`, and in nothing else. Seventeen other
calls were made on both sides with the same layout and the same arguments, fourteen
reads of a section and three searches, and each came back with the same SHA-256.

What else the records show, none of which decides anything:

- **The cost.** The thirty runs cost $1.90, and the thirty before $2.04.
- **One flat run of dev-01 searched.** Its third run asked for a search in the response
  that asked for the paper, which the two before it and the three of 2026-11-23 had not
  done. The search listed nothing. With another first response the run wrote the paper
  to the API's cache again, so the three flat runs of dev-01 cost $0.34, where the
  three before cost $0.19.
- **No cell is marked** as having taken more responses than any run before.

## 3. The sample of the survey, split again

`survey.run` went through the 520 papers again with the code of `44bca1f`, in 19
seconds. That is time for a few requests to arXiv at the most, so the sample was read
from the folder of downloads, as the plan expected. No paper came back unanswered.
`../../survey/outcomes-parser5.jsonl` names the sample and the plan that
`outcomes.jsonl` names, and has the same papers in the same order.

What the plan said would be read from the two files, line against line:

- **Papers that parser `4` split and parser `5` does not.** None, as expected. The same
  494 papers were split by both, and the lines of the 26 without a TeX source are the
  same in both files.
- **Papers whose line differs.** 191 of the 494. All 191 differ in the number of
  sections and in the characters, 39 in the largest piece, 17 in having no section
  heading, and none in the number of subsections.
- **The two shapes.**

| | parser `4` | parser `5` |
|---|---|---|
| papers that were split | 494 | 494 |
| without any section heading | 26 | 9 |
| with a piece of more than 20,000 characters | 125 | 108 |
| both | 22 | 7 |

How far that goes, as said before the run. The 17 papers that left the first count are
not 17 papers cut at their titles. Thirteen of them have 6 to 14 sections now. Four
have two, and in each of the four the largest piece is still above 20,000 characters,
334 to 787 fewer than it was: a line cannot say what the second section is, and the
rest of such a paper is one piece as before. The second count is the one to read.
Eighteen papers left it and one came into it, `2610.39042v1`: its letter, which parser
`4` left out, is one piece of 24,532 characters. So one of the 108 is a paper of which
more is read now, and not one that is split worse.

What else the two files show:

- No paper has fewer sections than before. Of the 191, 167 have one more and 24 have 2
  to 13 more; the 494 papers have 4,300 sections where they had 3,980, and 4,135
  subsections in both files.
- Parser `5` counts 27,275 characters more in `2610.39042v1`, and 2 to 394 fewer in
  each of the 190 others. A heading is not counted as text, so a title that became one
  is no longer in the count; a line cannot say whether that is all of the difference.

No outline of parser `5` has been held against a paper, so none of this says that the
new sections are the sections of the papers. The papers that carry a second document
are not counted, as the plan says. `../../survey/README.md` has the two shapes archive
by archive, and `tests/test_survey_parser5.py` holds the new file by its SHA-256 and
what is said of the two files against them.

## Making the texts again

```
uv run python -m hepph_paper_miner.eval.report --questions eval_data/questions_sections_parser5.jsonl --runs results/runs/more-sections/sections-after --conditions more-sections
uv run python -m hepph_paper_miner.eval.regress --questions eval_data/questions_dev.jsonl --criteria 2 --before results/runs/asking-again/dev-after --after results/runs/more-sections/dev-after --sheet results/runs/more-sections/dev-sheet.csv --key results/runs/more-sections/dev-key.csv --judge results/runs/more-sections/dev-j2.jsonl
```

The first reads the six papers, from arXiv where the folder of downloads does not have
them, to say in which runs the passage was given. Without them it counts no run as
given the passage and says in a note that a paper was missing; the lines that do not
rest on where a passage stands come out as they are in `sections-after-report.md`. The
second needs the paper of dev-03 for the same, and leaves that criterion open without
it. The report of the side before is made the same way by the code of `e7e9576`, with
`--conditions asking-again`, the question file of parser `4` and the folder
`sections-before`: the code of now would hold its records against papers that parser
`5` splits. The table of the two sides is put together by hand from the two reports,
the records and the verdicts, and the test holds it against them.
