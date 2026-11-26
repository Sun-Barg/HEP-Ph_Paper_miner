# The files of the survey

What the survey of which papers can be read left behind. The README of the repository
says what the survey is, how its sample was drawn and what came back ("A survey of which
papers can be read"). This file says what the files are and how the runs went. No file
here holds a title, an abstract or text of a paper, and nothing here is a result of the
evaluation.

| here | what it is |
|---|---|
| `population.jsonl` | the list the sample was drawn from: the 29,285 papers that arXiv listed for the plan on 2026-11-23 UTC, each with its primary category and the time of its first version |
| `sample.jsonl` | the 520 papers that the rule of the plan draws from that list, 40 of each of the 13 archives, in their order |
| `outcomes.jsonl` | what came back for each of the 520 papers: the file that the third run of `survey.run` wrote on 2026-11-25 |
| `outcomes-first-run.jsonl`, `outcomes-second-run.jsonl` | the files that the two runs before it wrote, with 67 papers and with 3 papers unanswered. They are kept to show what asking again changed, and they are not the result |
| `outcomes-parser5.jsonl` | what came back for the same 520 papers when parser `5` split them again: the file that one run of `survey.run` wrote on 2026-11-25, by `44bca1f`. It is not the result of the survey either, which stays `outcomes.jsonl`, and the check of the outlines is of that file |
| `outline-check.jsonl` | what was found when 65 outlines were held against the papers: for each paper two verdicts and a note. `survey.sheet` wrote it on 2026-11-25 from the sheet, which a Claude session had filled in as a draft and the maintainer had checked against each paper. The sheet is not here, because it holds section titles |
| `outline-check-first.jsonl` | what the same command wrote when it first read the sheet, earlier that day. It is kept to show what was changed after it, and it is not the result |

`tests/test_survey_results.py` holds the list and the sample against each other and
against the plan. `tests/test_survey_outcomes.py` holds the three other files against
the sample and against each other, and holds what is said here and in the README of the
repository against them. `tests/test_survey_checks.py` does the same for the two files
of the check of the outlines. `tests/test_survey_parser5.py` holds the file of parser
`5` against the sample and against `outcomes.jsonl`, line by line.

## The three runs

All three were made on the maintainer's computer by `ceea850`, the commit that brought
the sample, with no file of the repository changed, and with version 4 of the parser.
The first line of each file says so. A run goes through all 520 papers and reads from
the folder of downloads what arXiv has answered before.

The first run began at 13:45 UTC on 2026-11-24 and ended at 16:10, 145 minutes later.
For 67 papers arXiv gave no answer that could be used: 63 came back as `upstream_busy`
and 4 as `timeout`. A run asks for the first paper of every archive, then for the second
of every archive, and so on, and these 67 are papers 5 to 9 and 18 to 20 of their
archives: two stretches of that walk in which arXiv answered badly. So no archive lost
more than 6 of its 40 papers to them.

The second run began at 17:25 UTC and ended at 17:40, 15 minutes later. Of the 67, 64
came back with an outcome: 61 were split and 3 have no TeX source. The 3 that did not
are the first 3 of the 67 in the order of the walk, paper 5 of astro-ph, of cond-mat and
of gr-qc, each as `timeout`.

The third run began at 01:59 UTC on 2026-11-25 and ended within a minute. The 3 came
back with an outcome: 2 were split and 1 has no TeX source.

No line that had an outcome was another line afterwards: the 453 lines that the first
run filled are the same in all three files, and the 517 of the second are the same in
the third, letter for letter.

## The two shapes, archive by archive

A paper that was split is not thereby a paper that is easy to read: one without any
section heading comes back as one piece, and a piece of more than 20,000 characters
takes more than one call of `read_section`. Of the papers of each archive that were
split:

| Archive | Split | Without a section heading | With a piece of more than 20,000 characters |
|---|---|---|---|
| astro-ph | 39 | 0 | 5 |
| cond-mat | 30 | 1 | 9 |
| gr-qc | 40 | 0 | 5 |
| hep-ex | 40 | 6 | 14 |
| hep-lat | 40 | 0 | 9 |
| hep-ph | 40 | 1 | 8 |
| hep-th | 40 | 1 | 9 |
| math-ph | 40 | 1 | 15 |
| nlin | 39 | 0 | 10 |
| nucl-ex | 37 | 7 | 12 |
| nucl-th | 39 | 3 | 9 |
| physics | 30 | 4 | 11 |
| quant-ph | 40 | 2 | 9 |
| all | 494 | 26 | 125 |

## The check of the outlines

Of the papers of each archive that were split, the first 5 in the order of the sample
were on the sheet: 65 papers, each with its outline as the server gives it. A Claude
session filled in a draft of the sheet from the PDF or HTML pages of the papers, and the
maintainer opened each paper and held the draft against it. The first line of
`outline-check.jsonl` names the outcomes, the sample and the plan it belongs to, and
`2293bd3`, the commit whose code read the sheet. It was written at 04:52 UTC on
2026-11-25, after the last run of the survey had ended (02:00 UTC).

A line has the two verdicts and a note. For 42 papers both verdicts are `same`, and 36
of them have no note. The notes of the other 29 papers are put together from six
sentences, here with the number of papers whose note holds each:

| The note says | Papers |
|---|---|
| an acknowledgements heading that stands on a line of its own has no row | 15 |
| an acknowledgements title run into the head of a paragraph has no row (not counted: it stands below the section headings of the paper) | 6 |
| titles run into the head of paragraphs are the top division of the paper and have no rows | 5 |
| section headings of supplementary material after the reference list have no rows | 4 |
| subsection headings of supplementary material after the reference list have no rows | 2 |
| subsection headings that the paper prints after the reference list are rows under the last section before it | 1 |

The first, the third and the fourth go with `differ` under `sections` (22 papers: two
papers have two of them), the last two with `differ` under `subsections` (3 papers). The
second goes with no `differ`: it is the whole note of 6 papers whose verdicts are both
`same`, and the README of the repository says how such a title was read. The papers
with the first sentence are of eleven archives: 3 of hep-ph, 2 of hep-lat and of
quant-ph, and 1 of astro-ph, cond-mat, gr-qc, hep-ex, hep-th, nucl-ex, nucl-th and
physics.

`outline-check-first.jsonl` is what the command wrote when it first read the sheet, at
03:39 UTC. Both files have the same 65 papers, and the lines of 54 of them are the same
in both. For 4 papers `sections` went from `same` to `differ`, with the third sentence
as their note. For 7 papers only the note changed: the third sentence was added to the
note of 1 paper, and the second sentence became the note of 6. Those 6 notes were put
on the sheet by a Claude session, in the words above, after the maintainer had settled
how such a title is read; the maintainer then had the command read the sheet again.

The draft was a model's, and the check of it one person's. Nobody has looked a second
time.

## The weighted share

The archives were drawn at different rates: 40 of the 131 papers of nucl-ex, and 40 of
the 6,125 of cond-mat. So a share for the 29,285 papers of the list is worked out
archive by archive: the share of each archive that was split, weighted by the number of
papers the archive has in the list (`primary` in `sample.jsonl`). That gives 89.5%,
where the unweighted count gives 95.0%.

Its standard error is 2.0 points. That is the square root of

    the sum over the archives of  w² (1 − n/N) p (1 − p) / (n − 1)

where w is the weight of the archive, N the number of its papers in the list, n the 40
that were drawn and p the share of them that was split. An archive whose forty papers
were all split adds nothing to that sum, so the error is somewhat too small.

## The sample split again by parser 5

Everything above is of parser `4`. The parser was changed afterwards for what the check
of the outlines had noted ("A parser that begins a section in more places" in the
README of the repository), and on 2026-11-25 the same 520 papers were split again by
the code that has parser `5` (`44bca1f`), into `outcomes-parser5.jsonl`. What would be
read from the two files was written down before that run, in
`../runs/more-sections/README.md`, which also goes through what came back. The run
began at 10:46 UTC and ended within a minute, and left no paper unanswered.

The same 494 papers were split, and the same 26 have no TeX source. Of the 494, the
lines of 191 differ. Archive by archive:

| Archive | Split | Lines that differ | Without a section heading, parser `4` | parser `5` | With a piece of more than 20,000 characters, parser `4` | parser `5` |
|---|---|---|---|---|---|---|
| astro-ph | 39 | 23 | 0 | 0 | 5 | 5 |
| cond-mat | 30 | 14 | 1 | 0 | 9 | 7 |
| gr-qc | 40 | 15 | 0 | 0 | 5 | 4 |
| hep-ex | 40 | 21 | 6 | 2 | 14 | 11 |
| hep-lat | 40 | 20 | 0 | 0 | 9 | 8 |
| hep-ph | 40 | 18 | 1 | 0 | 8 | 8 |
| hep-th | 40 | 11 | 1 | 0 | 9 | 8 |
| math-ph | 40 | 5 | 1 | 1 | 15 | 15 |
| nlin | 39 | 8 | 0 | 0 | 10 | 9 |
| nucl-ex | 37 | 14 | 7 | 4 | 12 | 12 |
| nucl-th | 39 | 14 | 3 | 0 | 9 | 6 |
| physics | 30 | 11 | 4 | 1 | 11 | 8 |
| quant-ph | 40 | 17 | 2 | 1 | 9 | 7 |
| all | 494 | 191 | 26 | 9 | 125 | 108 |

A paper leaves the count of papers without a section heading as soon as parser `5`
makes one section in it, also when that section is its acknowledgements and the rest is
one piece as before. So the columns to read for how the papers are cut are the last
two. Eighteen papers left that count, and one came into it: `2610.39042v1` of hep-ex,
whose letter parser `4` had left out and parser `5` returns as one piece of 24,532
characters.

The share of the papers that were split is what it was, since the same papers were
split. No outline of parser `5` has been held against a paper: the check above is of
the outlines of parser `4`, and it says nothing of the new sections.
