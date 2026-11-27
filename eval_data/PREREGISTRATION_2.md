# Pre-registration of the second evaluation: questions about papers that nobody picked

Written before any paper of this evaluation was fetched, and committed with its plan
once the texts that draft and sift its questions were fixed; the code that sends those
texts came in the commits before. One thing is added later: the digest of the question
file (Sections 9 and 10), by the commit that adds that file, before any run.
Nothing else here changes after the commit; a change after it is listed under
Deviations, with its date and reason.

The code that picks the answers to grade by hand (Section 12) and writes the tables of
Section 13 was not written when this was committed. It is written to this text, before
the rehearsal of Section 10.

The first evaluation and its pre-registration (`PREREGISTRATION.md`) stay as they are.
No count of `results/report.md` moves, and nothing here is a run of its questions.

## 1. What is asked, and why

The first evaluation asked twenty questions about thirteen papers that one person had
read, most of them of one archive. The survey (`results/survey/`) then counted which
papers of thirteen archives the server can split into sections, and asked no question.
This evaluation asks questions about papers that nobody picked and nobody had read:
papers of four archives (hep-ph, hep-th, hep-ex, astro-ph), taken by the rule of the
survey. It is to show how far the two tool layouts answer there, and where they do not.

The questions are of one sort: the look-up of a fact that a paper states in one place.
A model drafts them, each bound to a passage; programs and a model sift the drafts; the
maintainer holds every draft that is left against its passage. No question asks for a
synthesis or a judgment, or for what a paper does not say.

## 2. Papers

The list is that of the survey, `results/survey/population.jsonl` (SHA-256 beginning
`ed1a8e897f69011c`): the papers whose primary category belongs to one of its archives
and whose first version was submitted from 2026-08-01 to 2026-10-31 (GMT). That is
after June 2026, up to where the model knows the world. The order is the survey's as
well: the SHA-256 of `20261124:<identifier without its version>`, smallest first.
Places 1 to 40 of an archive are the sample of the survey. This evaluation takes places
41 to 100 of the four archives, 240 papers (`eval_data/archives_plan.json`). The command
`drafting.papers` works them out from the list on disk, without asking arXiv, and writes
their sample in the form of the survey's (`results/archives/sample.jsonl`).

The papers of the survey's sample are not used. The parser was changed for what that
sample had shown (parser `5`), and six of its papers were given questions that were
written for the change. None of the 240 had been fetched when this was written: the
commit that adds this file names them in that list and nowhere else.

Each paper is fetched and split as the survey did it (`survey.run`), in the version the
list names, into `results/archives/outcomes.jsonl`. What came back is reported as the
survey reports it. `unanswered` is not an outcome, and no question is drafted while a
paper is left with it. Questions are asked of the papers that came back split.

## 3. Places and kinds

A place is a section or a subsection as the parser made it, and a part of its text. The
kind of a question says where its passage stands, and a program works it out.

| kind | the passage stands |
|---|---|
| `named_first` | in a subsection, or in a section without subsections; not in an appendix; in what the first call of `read_section` returns of it |
| `search_first` | in such a place as well; the question names its paper by its title (Section 9) |
| `own_text` | in the text that a section with subsections has before the first of them |
| `appendix` | in a section or a subsection of an appendix |
| `later_piece` | behind what the first call of `read_section` returns of its section or subsection, which is at most 20,000 characters |

Nothing is asked about a section of acknowledgements, about a section that the parser
began behind the list of references (lists of authors stand there, and supplemental
material too), or about a part of fewer than 1,000 characters.

There are to be four questions of each kind from each archive, sixteen of a kind and 80
in all, each about a paper of its own. There can be fewer; and where a kind and archive
has fewer than four, further questions of `named_first` take the places, as far as
there are any (Section 9). For them twelve places are given out for each kind and
archive: 240 in all at most, which is one for each paper. The papers are gone through
in the order of the survey's walk: the first of every archive, then the second, and so
on. A paper gets the first kind of this order that it has a place for and that its
archive still lacks: `later_piece`, `appendix`, `own_text`, `search_first`,
`named_first`. It can get `search_first` only when arXiv lists the version of the list
as its latest version, and a search for its title as it stands lists it among the first
five results; a paper whose look-up arXiv does not answer is not given `search_first`,
and the file of places says so. Within a paper, the place of the kind with the smallest
SHA-256 of `20261124:<identifier>:<section>` is taken. Where the sixty papers of an
archive do not hold twelve places of a kind, what is missing goes to `named_first` of
that archive. Nobody chooses a paper or a place. A paper that was not split has no
place. The places are given out once: `results/archives/places.jsonl` holds what was
given out, in counts and identifiers, and it is not made a second time.

Six places for each kind and archive were planned at first, on places 41 to 80 of the
order: 120 places for 80 questions. The last round of Section 8 then left an accepted
draft in 8 of its 27 places. At that share 120 places leave about 36 accepted drafts
and 240 about 71, so the papers were taken as far as place 100, and twelve places were
planned for each kind and archive: one for each paper. What sixty papers of an archive
would hold of each kind, and what their drafts would cost, was estimated on the
survey's sample of these archives (places 1 to 40), which holds no paper of this
evaluation. All of that was settled before the plan was committed and before any paper
of this evaluation was fetched. The share comes from eleven papers of one field, which
the maintainer knows; it is no forecast for the papers of this evaluation. How many
questions there are is what the rule of Section 9 makes of the drafts that are
accepted, and the report says it.

## 4. Drafting

`drafting.draft` asks a model for up to three drafts for each place, each about another
fact of the part, the best first: one request, which holds the whole text of the paper
as the tools return it, not cut, and then the part that was given out, on its own. The
request does not say of which kind the place is. The model is `claude-sonnet-5-5` with
`max_tokens` 16000, adaptive thinking and effort `high`, without a cache, and its reply
is held to a form in which every field is required. The summary of its thinking is
returned, and kept with the drafts in the private records. The texts it reads have the
name `d3` (SHA-256 beginning `2bfcb708c891ff4f`). A draft is a question that names its
paper by a mark, an anchor copied from the part, a reference answer, an answer key of
numbers and phrases, and a note on what is accepted; or the reply says that the part
holds nothing to ask about, and why. The form cannot bound a list, so the first three
drafts of a reply are read and the record counts any after them; a reply in which one of
the drafts that are read is not of the form is no draft at all. Every place is asked
once, and every reply is kept.

## 5. Checks by a program

A draft is dropped when one of these fails (`drafting/checks.py`). Every check is made
of every draft, the later drafts of a place too, and the report counts a draft under
each check it fails.

1. It reads as a line of a question file (`eval/questions.py`).
2. Its anchor stands once in the whole text of its section, subsections included, and
   that one place lies in the part that was given out. An anchor that differs from the
   text in its white space alone is written as the text has it.
3. Its key holds a number or a phrase, and nothing that is left to a person.
4. Every number of the key, and a wording of every phrase, is written in the anchor. So
   a passage that was given to a model is a value that was given to it.
5. No value of the key is written in the title or in the abstract.
6. No value of the key is written in the paper outside the part: not in another
   section, not in another piece or a subsection of its own section, and not in the
   title of a section, which the outline shows. Out there, a number of the key that has
   a unit is written only where the same number stands with the same unit right after
   it; spacing, braces, font commands, a range or an uncertainty may stand between, and
   units are held to each other by their first word. A number without a unit, and a
   phrase, are written wherever they stand.
7. The question holds the mark for its paper once, and no identifier, no value of the
   key, no title of two or more words of its section or of the section above it, no
   section, equation, figure or table named by its number, and not the word "appendix".
8. The question and the reference answer have at most 400 characters each, the anchor
   20 to 120.
9. The anchor does not stand in a table, a figure, a display equation, a caption or a
   footnote.
10. Every number of the key that the anchor writes is written there with two or more
    significant digits, or with a power of ten. The rule of `eval/grade.py` reads no
    unit, so a number of one digit would be met by any number of an answer that rounds
    to it. A number of the key that the anchor does not write fails check 4, and not
    this one.

"Written" is read the way the rule of `eval/grade.py` reads an answer. Numbers are read
off the TeX as `eval/check.py` reads them, with "--" read as the dash of a range, and
held to the key with its significant digits. A phrase is written where one of its
wordings stands, regardless of capitals and of white space, in the TeX made plain. A
question that expects no answer cannot be drafted: the form has no field for one.

## 6. Checks by a model

Two requests for every draft that passes the checks, the later drafts of a place too
(`drafting.sift`), with the model and the settings of Section 4 save that the thinking
is not returned, and texts of the name `s1` (SHA-256 beginning `cfd6f7744121d71e`). Each
is made once, and each shows the question as a run would be asked it. The answer is
graded by the rule of `eval/grade.py`, which says right or wrong of every answer when a
key holds numbers and phrases alone.

- **Without the paper.** The question alone, with no tool and no text of the paper. The
  answer is one text, with no "found", and it is graded as an answer that says the
  paper states what is asked. A draft that is answered right is dropped: its fact can
  be known or guessed.
- **With the passage alone.** The question, and the piece that holds the anchor as
  `read_section` returns it, with the lines of the prompt of the runs said of that
  piece. A draft is kept only when it is answered right: the passage answers the
  question, and the key fits an answer as a model writes one.

A draft passes when it passes every check, is not answered right without the paper,
and is answered right from the passage. Of each place, the first draft in the order of
its reply that passes is kept, and the other drafts of the place are not: a place gives
one question at most. The private record says which draft of each place was kept, and
`results/archives/candidates.jsonl` counts the places that kept their first, second
and third draft.

## 7. Review by the maintainer

The maintainer reads every draft that is kept, one for a place at most, beside its
passage, on a sheet that stays in `runs_private/`. A draft is accepted when the question
reads one way to somebody who has the passage; when the reference answer is what the
passage says; when the key and the note fit the reference answer; and when the passage
is a sentence of the running text, not a table, a caption or a list of names. A draft is
accepted or rejected as it stands: no word of it is changed. The sheet shows the
question, the section, the paragraph of the anchor, the reference answer, the key and
the note; not the kind, the archive, the place in the walk or which draft of its place
it is, and its rows stand in the order of the SHA-256 of
`20261124:<identifier>:<section>:<start>`. A rejection names one of five kinds: the
question reads more than one way (`ambiguous`); the reference answer is not what the
passage says (`not_the_passage`); the key or the note does not fit the reference answer
(`key_or_note`); the passage is a table, a caption, a list of names or an equation
(`not_running_text`); anything else, said in a note (`other`).
`results/archives/review.jsonl` holds every verdict with the kind of its reason, and no
text of a paper.

## 8. How the texts were made

The texts of Sections 4 and 6 were written on the papers of the first evaluation
(`eval_data/target_papers.txt`), which the maintainer knows well, in three rounds. The
papers stood in the order of the SHA-256 of `20261124:<identifier without its
version>`: the first round took places 1 to 6 of that order, the second 7 to 12, and
the last round every paper that no round before it had used. In a round, a paper was
given one place of every kind it has (`search_first` aside), so that a round has more
drafts than papers. The texts of the first round asked for one draft a place, and those
after it for up to three (Section 4). After each of the first two rounds the maintainer
read the drafts that were left, as a reader who knows the paper, and the texts were
changed for what that showed. A Claude session wrote the texts and the changes to them,
and the maintainer approved them. The last round was run with the texts as they are
named here. It had 27 places on 11 papers: in 14 the reply said that the part holds
nothing to ask about, in 2 no draft passed, and 11 kept a draft (Section 6). It had
been settled before that round that the texts would be used here only if the maintainer
accepted at least two thirds of the drafts it kept. The maintainer accepted 8 of the
11. After that round the texts, the checks and the rules of Sections 3 to 7 were not
changed; what was changed is the count of the places and of the papers (Section 3). No
paper of this evaluation had been fetched when the texts were fixed. The tool texts,
the prompt and the parser of the runs are those of the conditions of Section 10: they
were not changed for this evaluation, and are not changed once a draft of it has been
seen.

## 9. The question file

For each kind and archive, the first four accepted drafts in the order of the walk. The
mark for the paper becomes `arXiv:<identifier>`, and for `search_first` the title that
arXiv lists. Where a kind and archive has fewer than four accepted drafts, further
accepted drafts of `named_first` of that archive take the places, as far as there are
any, and are asked as `named_first`. No further draft is made, and the report shows how
many questions of each kind and archive there are. An accepted draft that this rule
does not take is no question. The questions stand in the order of the walk and are
named `archives-01`, `archives-02` and so on: 80 at most. The file is
`eval_data/questions_archives.jsonl`. Its SHA-256 is put here by the commit that adds
the file, before any run: `<SHA-256 of the question file>`.
`drafting.assemble` writes the file, and with it `results/archives/candidates.jsonl`:
what became of every candidate, in counts and names and with no text of a paper, and
the counts by kind, archive and reason.

## 10. Conditions and runs

Every run is made under the conditions `more-sections` of
`src/hepph_paper_miner/eval/conditions.py`: tool texts `staged-6` and `flat-5`, prompt
`p3-tool`, parser `5`, model `claude-sonnet-5-5` with `max_tokens` 16000, adaptive
thinking, effort `high`, prompt cache `ephemeral` and 2 retries of 600 s; at most 12
responses, 700 s per tool call and 900 s per run. The code has had them since
2026-11-25.

```
uv run python -m hepph_paper_miner.eval.run --questions eval_data/questions_archives.jsonl --out results/runs/archives --repeats 1 --questions-sha256 <SHA-256 of the question file>
```

Two cells for every question, one for each layout, each run once: 160 cells at most, in
the order of the runner. The questions come in the order of the file, and which layout
of a question runs first alternates from question to question. A run is spoilt as
Section 4 of the first pre-registration says, and its cell is run again after the pass,
at most twice; a cell that is spoilt three times is given up, as there.

A cell has one run, where the first evaluation had three. There the three runs of a
cell called the tools of the server alike, call for call and argument for argument, in
26 of the 40 cells. Here the runs go to more papers, and not to repetitions.

Before the runs, the commands are tried from end to end on seven questions that the same
texts drafted for papers of the first evaluation: fourteen runs, their sheet, the judge
and the report. They are drafts of the last round of Section 8 that the maintainer
accepted, taken by the rule of Section 9 with two of a kind where it says four. No
draft of `later_piece` or `appendix` was accepted in that round, so its eight accepted
drafts give seven questions: two of the three `own_text` drafts and all five
`named_first` drafts. A paper of that round has no `search_first` place, so up to two of
those `named_first` drafts are asked as `search_first`: drafts of papers that arXiv
lists in their latest version and a search for their title lists among the first five
results. Nothing is changed for what these runs show. A command that fails is mended,
and the change is listed under Deviations.

## 11. What is measured

For each run that counts, from its public record and the parsed papers (`eval.grade`),
as in the first evaluation: for the `search_first` questions, whether a search listed
the paper and at which rank; whether every character of the anchor was given to the
model, and in which turn; whether the evidence the answer lists names the section of
the question; and the answer (Section 12).

Volume: tool result characters as the model received them (the measure of H1); input
tokens; paper text given, each character once; tool calls; responses; cost worked out
from the usage at the list prices of `eval/report.py` (for a million tokens: USD 2 of
input, 2.50 written to the cache, 0.10 read from it, 10 of output), which were read
again on 2026-11-27 and stood as they are there. Also counted: the answers that are
right although the anchor was not given, and why wrong runs were wrong, from their
records.

## 12. Verdicts

An answer can have three grades.

- The rule of `eval/grade.py`: right or wrong, from the key.
- The judge `j2` (texts SHA-256 beginning `38bc359e5841b16a`), as it was fixed on
  2026-11-19: three requests for every answer of the sheet that `eval.sheet` writes, and
  its verdict is the one that two or three of them gave.
- The maintainer, on a sheet that shows the answer and its `found`, and for each
  question its text, reference answer and note; not the layout, the run, the rule, the
  judge, or why the row is on the sheet. Graded by hand are (a) every answer on which
  the rule and the judge differ, (b) every answer that the judge calls wrong or has no
  verdict on, and (c) forty of the others, or all of them where they are fewer: those
  with the smallest SHA-256 of `20261124:<question>:<layout>`.

The verdict on an answer is the grade by hand where there is one, and the verdict of
the judge otherwise. A run without an answer is wrong. If the grade by hand differs
from the verdict of the judge in three or more of the answers of (c), every answer is
graded by hand, and the grades by hand are the verdicts.

In the first evaluation every answer was graded by hand. Here up to 160 answers follow
the review of every question by the same person, so the grading by hand goes where the
two other graders differ or doubt, and (c) says how far the rest can be trusted.

## 13. Hypotheses, and how each is read

The unit is the question, and every question is about a paper of its own. A question
one of whose cells was given up (Section 10) has no pair of runs: it is left out of H1
and H2, and the report names it and the layout that is missing.

- **H1**: staged gives the model less tool result text than flat. Reported: the number
  of questions whose staged run was given fewer characters, more, and as many, and the
  p of a one-sided exact sign test with ties left out. No threshold is fixed in advance.
- **H2**: staged does not answer worse than flat by more than 10 percentage points.
  Reported: the paired table of the questions (both right, staged only, flat only,
  neither) and the 95% interval of the difference by the adjusted Wald formula of
  Agresti and Min (2005), which adds one half to each of the four cells
  (`eval/paired.py`). With b questions right in staged only and c in flat only, of n:
  (b − c)/(n + 2) ± 1.96 · √((b + c + 1) − (b − c)²/(n + 2)) / (n + 2).
  Its lower end above −10 points: "not worse by more than 10 points, on these
  questions". Its upper end below 0: "worse". Neither: "not shown either way". Were
  both to hold, both would be said; with 80 questions or fewer no table makes them both
  hold. The margin of ten points was set for 80 questions, where it is near the least
  that they can show, and it stays whatever the count of the questions is. It is not a
  width that any use of the tools suggests. Fewer questions show less. If the layouts
  answer alike but for some questions, half of them right in staged only and half in
  flat only, the first reading comes out as long as those questions are no more than:

  | questions | 80 | 70 | 60 | 50 | 40 | 30 |
  |---|---|---|---|---|---|---|
  | of them differ, at most | 16 | 12 | 8 | 6 | 2 | 0 |

  With fewer than 18 questions not even a table on which the layouts never differ gives
  the first reading.
- **Exploratory**, by kind and by archive: the runs in which the anchor was given, and
  the answers that are right. Expected beforehand: the staged runs that were not given
  the anchor gather in `own_text` and `later_piece`. For the `search_first` questions,
  whether a search listed the paper, beside the `named_first` questions. The answers
  that are right without the anchor. The judge against the grades by hand of (c).

No threshold is set for "it works". The counts are reported by layout and by archive
as they come, whichever way they point.

## 14. Exclusions

Only spoilt runs are left out, and their records are kept and counted in the report.
No other run is left out: a run that reaches the turn limit, ends without an answer, or
meets a tool error counts, and without an answer it is wrong. No question is left out
after the question file has its digest, save one that has no pair of runs because a
cell of it was given up (Section 13).

## 15. Known limits, stated before the runs

- The questions are asked of papers that were split. How many papers are not split is
  what the survey counts.
- Look-ups of a value that running text states once. Nothing about tables, captions,
  equations or supplemental material; no synthesis; no question about what a paper does
  not say.
- The count of the questions is not fixed beforehand (Sections 3 and 9). Fewer than 80
  widen the interval of H2 (Section 13), and a kind or an archive may be left with few
  questions or with none.
- Check 6 does not find a value that the paper states again without its unit right
  after it (in a table whose unit stands in its head, say, or with another spelling of
  the unit). Such a question shows up as an answer that is right although the anchor
  was not given (Section 11).
- One model drafts, sifts, answers and judges. A draft that is kept is one that this
  model answered from its passage, so answers may be right in both layouts, and the
  comparison rests on H1 and on the anchors more than on H2.
- The reviewer has the passage and not the paper, and is no specialist of all four
  archives. How the drafts fare with a reader who knows the paper was looked at on the
  papers of the first evaluation only (Section 8). There, two of the eleven drafts that
  the last round kept asked what the texts tell the generator not to ask: the value of
  an assumption that is usual in the field, and a value taken from another study.
  Neither the generator nor the filters dropped them. The reviewer did, knowing the
  papers; a reviewer who has the passage alone may accept such a draft.
- One run for a cell: what one run does by chance goes into its verdict.
- A `search_first` question is asked only of a paper that a search for its title
  lists, and it depends on a live arXiv search, which lists the latest version of a
  paper.
- A search whose category is the name of an archive that has subcategories, such as
  astro-ph, finds nothing: arXiv takes the category as it is written. The tool's answer
  to an empty search says to drop the filter, and the tool texts were not changed for
  this evaluation (Section 10), so a run that searches so spends a call on it. Of the
  four archives, only astro-ph has subcategories.
- An answer that was not graded by hand has the judge's verdict. The grader by hand
  reviewed the questions, and the wording of an answer may hint at its layout.
- The rule of `eval/grade.py` reads no number that is written against a letter (the
  8.186 of "PYTHIA8.186"), and it reads a power of ten that an answer sets apart with
  the unit, as in "1.3 (×10⁻²⁶ cm³/s)", as a number of its own. An answer written so
  can state the value and fail the rule. Where the judge then says right, the answer is
  graded by hand (Section 12, a). The rule was fixed for the first evaluation and is
  not changed for this one.
- A section whose heading has a star and stands behind `\appendix` gets no letter from
  the parser, so a place in it counts as a place of the body (`named_first` or
  `own_text`), not as `appendix`.
- The flat runs read the lists of authors that stand in a paper, so a difference in
  text between the layouts is partly theirs where such lists are long (hep-ex).
- Three months of 2026, four archives.
- Costs are worked out from the usage at list prices; they are not read from the
  Console.

## 16. Deviations

None so far.
