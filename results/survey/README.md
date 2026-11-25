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

`tests/test_survey_results.py` holds the list and the sample against each other and
against the plan. `tests/test_survey_outcomes.py` holds the three other files against
the sample and against each other, and holds what is said here and in the README of the
repository against them.

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
