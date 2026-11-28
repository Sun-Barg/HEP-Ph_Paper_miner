# The files of the second evaluation

What the second evaluation left behind before its first run: which papers it asks about,
how they came back, the place that each was given, what became of the drafts of its
questions, and the verdicts of the review. `eval_data/PREREGISTRATION_2.md` says how each
step is made, and was committed before any of these papers was fetched. This file says
what the files are and what is in them. No file here holds a title, an abstract or text
of a paper. Nothing here is a result: no question has been put to the server yet.

| here | what it is |
|---|---|
| `sample.jsonl` | the 240 papers of the plan `archives-1`: places 41 to 100 of hep-ph, hep-th, hep-ex and astro-ph in the order of the survey, as `drafting.papers` worked them out from `../survey/population.jsonl` on 2026-11-27 |
| `outcomes.jsonl` | what came back for each of the 240 papers when `survey.run` fetched and split them that day: the file of its one run |
| `places.jsonl` | the place that `drafting.assign` gave to each of the 237 papers that were split, with what each paper holds of every kind and whether a search for its title lists it |
| `review.jsonl` | the verdicts on the 82 drafts that the checks and the filters left, one for a place, as `drafting.review` read them off the sheet on 2026-11-28: for each its place, the verdict and, for a rejection, the kind of its reason. The sheet and its notes are not here, because they hold passages |
| `candidates.jsonl` | what became of every one of the 237 places, written by `drafting.assemble` on 2026-11-28 beside the question file: what the generator returned, the checks that each draft failed, what the two filters said of it, the verdict, and the question it became; then the counts by kind and archive, and the cost |
| `rehearsal-candidates.jsonl` | the same for the 27 places of the last round in which the texts of the generator and of the filters were tried, on 11 papers of the first evaluation: `drafting.assemble --rehearsal` wrote it on 2026-11-28 beside the seven questions of the rehearsal |
| `rehearsal-candidates-first-try.jsonl` | what the same command had written 80 minutes before, when arXiv answered none of its look-ups. It is kept to show what asking again changed, and the question file it names is not kept |

The questions are in `eval_data/questions_archives.jsonl`, 42 of them, and those of the
rehearsal in `eval_data/questions_rehearsal.jsonl`. The drafts and the replies of the
filters hold paper text as well and stay outside the repository; `review.jsonl` and the
summaries name those records by their SHA-256.

`tests/test_archives_results.py` holds every file by its SHA-256, the sample against the
plan and the list of the survey, each file against the one it was made of, and what is
said here against them all. All times are UTC.

## The papers, and how they came back

The sample, the outcomes and the places were made on the maintainer's computer on
2026-11-27 by `5a45e8d`, the commit that brought the plan and the pre-registration, with
no file of the repository changed; the first line of each file says so. `drafting.papers`
drew the sample at 14:11 from the list on disk, without a request to arXiv. `survey.run`
then went through the 240 papers once, from 14:11 to 14:51, 40 minutes, and left no paper
unanswered, so there was no second run.

| Archive | Papers | Split into sections | Turned away by the parser | No TeX source |
|---|---|---|---|---|
| hep-ph | 60 | 60 | 0 | 0 |
| hep-th | 60 | 60 | 0 | 0 |
| hep-ex | 60 | 58 | 1 | 1 |
| astro-ph | 60 | 59 | 0 | 1 |
| all | 240 | 237 | 1 | 2 |

The paper that the parser turned away is `2609.16276v2` of hep-ex: its text is read with
`\import`, a command the parser does not follow (`unfollowed_command`). The line keeps the
sentence of the parser, which names five of the six files it could not read. The two
papers without a TeX source, `2609.18799v1` of hep-ex and `2608.11253v1` of astro-ph, are
a PDF, PostScript or DVI file at arXiv (`not_tex`). No paper was missing from arXiv
(`not_found`), and none came back in a way nobody foresaw (`unexpected`). These three
papers have no place, and no question is asked about them.

The two shapes that the survey counts beside the outcomes, of the papers that were split:

| Archive | Split | Without a section heading | With a piece of more than 20,000 characters |
|---|---|---|---|
| hep-ph | 60 | 0 | 8 |
| hep-th | 60 | 0 | 16 |
| hep-ex | 58 | 5 | 20 |
| astro-ph | 59 | 2 | 8 |
| all | 237 | 7 | 52 |

Five papers are both. These are counts of sixty papers an archive, split by parser `5`.
They say how the papers of this evaluation came back, and they are no share of an
archive: the survey is where such a share is worked out, on a sample of its own.

## The places

`drafting.assign` began at 14:51, after the last paper had come back, and gave out 237
places: one for each paper that was split, in the order of the walk (the first paper of
every archive, then the second, and so on).

| Archive | `later_piece` | `appendix` | `own_text` | `search_first` | `named_first` | All |
|---|---|---|---|---|---|---|
| hep-ph | 7 | 12 | 12 | 12 | 17 | 60 |
| hep-th | 12 | 12 | 12 | 12 | 12 | 60 |
| hep-ex | 12 | 12 | 12 | 12 | 10 | 58 |
| astro-ph | 6 | 12 | 12 | 12 | 17 | 59 |
| all | 37 | 48 | 48 | 48 | 56 | 237 |

Twelve places of each kind were planned for an archive. The papers of hep-ph hold 7
places of `later_piece` and those of astro-ph 6, so 5 and 6 more went to `named_first`
there; in hep-ex, 58 papers were split, which left 10 for `named_first`. Of the 237
papers, every one holds a `named_first` place, 122 an `appendix` place, 115 an `own_text`
place and 41 a `later_piece` place.

A paper is asked about by its title only if a search for that title finds it. arXiv
answered the look-up of every paper. For 4 papers the version of the list was no longer
the latest one. Of the other 233, a search for the title listed 220 among its first five
results (216 as the first, 3 as the second and 1 as the fifth) and 13 not. The file keeps
the rank, and not the words of a search.

The places are given out once (Section 3 of the pre-registration): the command is not run
over the file again.

## The drafts, the checks and the filters

The generator was asked once for every place, and `candidates.jsonl` counts what came of
it.

- 130 replies said that the part holds nothing to ask about. 107 held drafts, 211 in all
  (34 places with one, 42 with two and 31 with three). No reply was anything else.
- 166 of the 211 drafts passed every check of a program. The 45 others failed 62 checks
  between them, a draft being counted under each check it failed:

  | Check, by its number in Section 5 of the pre-registration | Drafts |
  |---|---|
  | 6: a value of the key stands elsewhere in the paper (`not_elsewhere`) | 26 |
  | 4: a value of the key is not written in the anchor (`key_in_anchor`) | 14 |
  | 5: a value of the key stands in the title or the abstract (`not_in_listing`) | 10 |
  | 7: the question holds what it may not (`question_clean`) | 5 |
  | 10: a number of the key has one digit (`two_digits`) | 4 |
  | 9: the anchor does not stand in running text (`running_text`) | 2 |
  | 2: the anchor does not stand once, in the part that was given out (`anchor_once`) | 1 |

- Each of the 166 was put to the model twice. 28 were answered right without the paper,
  and 3 were not answered right from their passage; no draft was both. 135 drafts passed
  everything.
- 82 places keep a draft, the first of their reply that passed everything: for 73 places
  that is their first draft, for 8 their second and for 1 their third. 25 places had
  drafts and keep none.

The requests of the generator and of the filters come to 11,420,132 input tokens and
297,201 output tokens: $25.81, worked out at the list prices of `eval/report.py` and not
read from the Console.

## The review

The 82 drafts that were kept were put on a sheet, each beside its passage (Section 7 of
the pre-registration). A first reader, a Claude session that had helped the maintainer
with reviews before, was given the sheet, without the papers and without the file that
says of which kind a place is, and wrote a verdict and a note for every row as a draft.
It knew the text that tells the generator what to ask. The maintainer then held each of the 82 rows against its passage
and settled the verdict; how many verdicts of the draft were changed in that was not
counted. Section 7 has the maintainer alone read the drafts, so this is listed there
under Deviations, with its reason. `drafting.review` read the sheet back at 06:57 on
2026-11-28.

| Archive | Places | With drafts | Keep a draft | Accepted | Rejected |
|---|---|---|---|---|---|
| hep-ph | 60 | 22 | 16 | 6 | 10 |
| hep-th | 60 | 19 | 10 | 5 | 5 |
| hep-ex | 58 | 32 | 27 | 18 | 9 |
| astro-ph | 59 | 34 | 29 | 19 | 10 |
| all | 237 | 107 | 82 | 48 | 34 |

Of the 34 rejections, 15 say that the key or the note does not fit the reference answer
(`key_or_note`), 1 that the passage is no running text (`not_running_text`), and 18 give
another reason in a note (`other`). None says that the question reads more than one way,
or that the reference answer is not what the passage says. A note can quote its passage,
so the notes stay with the sheet, and the file holds the kinds alone.

Each of the 18 notes under `other` names a line of the text that tells the generator what
to ask (Section 4 of the pre-registration) and that the draft goes against: a value that
the paper takes from another work or tells as background, a value that is known outside
the paper or that the question lets a reader work out, something that is no fact of the
physics or of the method, a round number of one digit. Section 15 says that a reviewer
who has the passage alone may accept such a draft. Here the first reading was a
model's, which brought what it knows of the fields, and the maintainer could hold that
against the passage and not against the paper.

By kind, 12 of the 16 drafts of `later_piece` were accepted, 8 of the 14 of `appendix`,
4 of the 11 of `own_text`, 10 of the 19 of `search_first` and 14 of the 22 of
`named_first`.

Section 3 of the pre-registration had worked out about 71 accepted drafts for 240
places, from the share of the last round in which the texts were tried, and said that
this share was no forecast. Here 48 of the 237 places have an accepted draft.

The draft of the verdicts was a model's, and the check of it one person's, who had the
passage and not the paper. Nobody has looked a second time.

## The questions

`drafting.assemble` made the question file at 06:57 on 2026-11-28, by `97ba66e` with no
file of the repository changed: for every kind and archive the first four accepted
drafts in the order of the walk, and then accepted drafts of `named_first` for the places
that a kind of the same archive was short of (Section 9 of the pre-registration).

| Archive | `later_piece` | `appendix` | `own_text` | `search_first` | `named_first` | All |
|---|---|---|---|---|---|---|
| hep-ph | 2 | 0 | 2 | 0 | 2 | 6 |
| hep-th | 1 | 3 | 0 | 0 | 1 | 5 |
| hep-ex | 4 | 2 | 2 | 3 | 4 | 15 |
| astro-ph | 2 | 3 | 0 | 4 | 7 | 16 |
| all | 9 | 8 | 4 | 7 | 14 | 42 |

There are 42 questions, where 80 were planned at most, each about a paper of its own: 35
name their paper by its identifier and 7 by its title. Of the 42, 38 are the first draft
of their place and 4 the second.

- Six accepted drafts are no question, because their kind and archive had four before
  them: 3 of `later_piece` in hep-ex and 3 of `search_first` in astro-ph.
- Three of the seven `named_first` questions of astro-ph take places that other kinds of
  that archive were short of. No other archive had an accepted `named_first` draft left
  over.
- Five of the twenty pairs of a kind and an archive have no question: `appendix` and
  `search_first` in hep-ph, `own_text` and `search_first` in hep-th, and `own_text` in
  astro-ph.

The SHA-256 of the file is
`09ead4c927a6a0edd13ba8d9d05440ddd7e2b9ebdc3930da949efb3e1002110c`. The pre-registration
names the file by it in Sections 9 and 10, where the words for it stood until this file
was there, and the first line of `candidates.jsonl` names it as well.

What fewer questions can show was written down before their count was known (Section 13
of the pre-registration): the margin of ten points stays, and fewer questions show less.
If the two layouts answer alike but for some questions, half of them right in `staged`
only and half in `flat` only, the reading "not worse by more than 10 points" comes out
for at most 4 such questions of 42. The table of that section has 2 for 40 questions and
6 for 50.

## The questions of the rehearsal

Before the runs, the commands are tried from end to end on seven questions about papers
of the first evaluation (Section 10 of the pre-registration). They are in
`eval_data/questions_rehearsal.jsonl`, and `rehearsal-candidates.jsonl` says what they
were made of: the last round in which the texts were tried, with the texts as they are
now (`d3` and `s1`), on 11 papers of the first evaluation. The records of that round
stay outside the repository as those of the evaluation do.

That round had 27 places. In 14 the reply said that the part holds nothing to ask about,
in 2 no draft passed everything, and 11 kept a draft. The maintainer accepted 8 of the
11 and rejected 3, each for another reason (`other`). Section 8 of the pre-registration
gives the counts of the places and of the accepted drafts, and no file of the repository
held them before.

With two of a kind where the evaluation has four, the 8 accepted drafts make 7
questions:

| Kind | Accepted drafts | Questions |
|---|---|---|
| `later_piece` | 0 | 0 |
| `appendix` | 0 | 0 |
| `own_text` | 3 | 2 |
| `search_first` | none: no place of that round is of this kind | 2 |
| `named_first` | 5 | 3 |

A paper of that round has no `search_first` place. So the command looks up the papers of
the accepted `named_first` drafts one after the other, until two are found by their
title. The first two it asked about were: arXiv lists each in the version of the round
as its latest, and a search for its title lists it first. Their drafts are asked as
`search_first` and the next two as `named_first`. The fifth takes a place that a kind
without an accepted draft left open, and the third accepted draft of `own_text` is no
question. Two of the seven questions are about one paper, because a paper of that round
was given a place of every kind it holds; the questions of the evaluation are each
about a paper of its own.

`drafting.assemble --rehearsal` made the file at 08:23 on 2026-11-28, by `97ba66e` with
no file of the repository changed. It had been run once before, at 07:03, and then
arXiv answered none of its look-ups: of the five papers it asked about, two came back
as `timeout` and three as `upstream_busy`, so that no question would have named its
paper by a title. `rehearsal-candidates-first-try.jsonl` is the summary of that run; its
lines say of every place what those of the second say, but for the look-ups and the
questions. Nobody chose a question either time: the same rule made them from what arXiv
answered. Nothing is read from the rehearsal but whether the commands work.

The requests of that round come to $3.76 at list prices.
