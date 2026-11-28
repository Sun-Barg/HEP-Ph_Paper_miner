# Notes for AI coding agents

This repository is written with AI assistance and reviewed by its owner. An agent that
works here follows the rules below.

## Commits and pushes

- The owner is the author and the committer of every commit. A cloud session defaults to
  another identity and signs its commits, so name the owner and switch signing off:

      git -c user.name="Haebarg Kang" \
          -c user.email="216486749+Sun-Barg@users.noreply.github.com" \
          commit --no-gpg-sign -m "<title>" -m "<body>" \
          -m "Co-Authored-By: <your model name> <noreply@anthropic.com>"

- The message ends with that one Co-Authored-By line. No Claude-Session line and no other
  trailer after it.
- Check the result before pushing. The first command has to print
  `Haebarg Kang | Haebarg Kang`, the second `0` (no signature):

      git log -1 --format="%an | %cn"
      git cat-file -p HEAD | grep -c "^gpgsig"

- Stage files by name. Never `git add -A` or `git add .`.
- Run `uv run pytest` first; it has to pass. After a change to the section parser also run
  `uv run pytest -m tex` where pdflatex is installed.
- Push to main (`git push origin HEAD:main`) and leave no work on a side branch. Never
  force-push unless the owner asks for exactly that.

## Never commit

- Paper text, the HTTP cache, or run records that contain paper text. The one exception is
  `tests/fixtures/arxiv-2610.26648v1/`: the owner's own paper, under CC0.
- API keys, or a `.env` file.

## Version markers

- `PARSER_VERSION` in `src/hepph_paper_miner/sources/arxiv_latex.py`: raise it whenever the
  same source would split differently.
- `TOOLSET_VERSION` in `src/hepph_paper_miner/server.py`: raise it whenever a tool
  description, an argument description or the form of a result changes. The model reads all
  three, so a change to any of them is a different experiment.
- `PROMPT_VERSION` in `src/hepph_paper_miner/agent/prompt.py`: raise it whenever the system
  prompt, the answer schema, the loop's own tool or a message the loop writes for the model
  changes. It has one name for each way a run hands in its answer: raise the name of every
  way whose texts change.
- `tests/test_toolset_pin.py` and `tests/test_prompt.py` fail when one of these texts changes
  under an unchanged version. Raise the version first, then pin the digest the failure prints.
- `JUDGE_VERSION` in `src/hepph_paper_miner/eval/judge.py`: raise it whenever the system
  prompt of the judge, the layout of a request or the form of a verdict changes. The judge
  reads all three, so a change to any of them is another judge. `tests/test_judge.py` fails
  when one of them changes under an unchanged version: raise the version first, then pin the
  digest the failure prints.
- `src/hepph_paper_miner/eval/conditions.py` names the versions the evaluation uses, with the
  model, its settings and the limits of a run (`EVALUATION`). They are fixed. Do not change
  that file, a version it names or a default it covers unless the owner asks for exactly that.
  `tests/test_conditions.py` fails when one of them moves, and editing the expected values
  until it passes is not a fix.
- The same file names the conditions of the runs made since (`REVISED`: `EVALUATION` with
  the tool texts as they were changed after the evaluation; `ASKING_AGAIN`: `REVISED` with
  the prompt that holds the loop's message for a turn that ends without the call) and what
  the code has now (`MORE_SECTIONS`: `ASKING_AGAIN` with the parser that begins a section
  in more places). Every set names its parser. When the owner has a text or the parser
  changed, its new name goes into a new set of conditions there, never into a set that
  runs were made under: every record stays held against the conditions it was made under.
  Runs made before a change are no runs of what comes after, so the development questions
  are run again and held against the runs before (`eval/regress.py`).
- `eval_data/questions_sections_parser4.jsonl` and
  `eval_data/questions_sections_parser5.jsonl` were asked on 2026-11-25 UTC, and are fixed
  since. So is the plan of those runs, the first part of
  `results/runs/more-sections/README.md`: it names each file by its SHA-256, and
  `tests/test_section_questions.py` holds it to the commit that brought it. Do not change
  a question, an answer, a passage or a note in the two files, or a sentence of the plan.
  What is found later is written below the plan.

## The survey

- `eval_data/survey_plan.json` says which papers the survey is about and how its sample is
  drawn. It is committed before the sample is drawn, and once a sample has been drawn
  under it, it is fixed like the conditions of the evaluation: another window, seed,
  list of categories or number of papers is another plan, in a file of its own under
  another name, and the sample of the first stays what it was.
- `results/survey/` holds identifiers, categories, dates, counts, the sentences of the
  parser and the notes of the check of the outlines. The sheet of that check
  (`survey/sheet.py`) holds section titles, which are paper text: it is written into
  `runs_private/` and never committed.
- The sample was drawn on 2026-11-23 UTC, so the plan is fixed now.
  `tests/test_survey_results.py` fails when the plan is no longer the file the sample
  names, or when `results/survey/sample.jsonl` is not what the plan draws from
  `results/survey/population.jsonl`. Editing one of the three until it passes is not a fix.
- The survey was run on 2026-11-24 and 2026-11-25 UTC, and `results/survey/outcomes.jsonl` is
  fixed as well: `tests/test_survey_outcomes.py` holds it by its SHA-256, and the check of the
  outlines names it by that. `survey.run` writes the file anew whenever it runs, with other
  times and another commit in its first line, so it is not run over that file again unless the
  owner asks for exactly that.
- The outlines of 65 papers were held against the papers on 2026-11-25: a Claude session
  drafted the verdicts and notes, and the owner checked each against its paper.
  `results/survey/outline-check.jsonl` is fixed as well: `tests/test_survey_checks.py`
  holds it by its SHA-256. An agent does not change a verdict or a note in it. Where an
  agent fills in such a sheet, it fills in a draft for the owner to check, and the README
  says who did what. A paper that is looked at again gets its verdicts in a new file
  under another name.
- The sample was split again by parser `5` on 2026-11-25 UTC, into
  `results/survey/outcomes-parser5.jsonl`, and that file is fixed as well:
  `tests/test_survey_parser5.py` holds it by its SHA-256, and `survey.run` is not run over
  it again unless the owner asks for exactly that. `outcomes.jsonl` stays the result of
  the survey, and the check of the outlines is of it. Another parser gets a file of its
  own under another name.
- `unanswered` is not an outcome of the survey. A number about the papers that were read
  is given with the papers that are still unanswered beside it, never with them counted
  as failures or left out without a word.

## The second evaluation

- `eval_data/archives_plan.json` says which papers the second evaluation asks about, and
  `eval_data/PREREGISTRATION_2.md` says how its questions are made, asked and read. Both
  were committed before any of those papers was fetched, and both are fixed.
  `tests/test_archives_plan.py` holds the plan by its SHA-256, and Sections 1 to 15 of the
  pre-registration by theirs. Do not change a sentence of them, and editing the two
  digests until the test passes is not a fix. What turns out otherwise is written under
  Deviations (Section 16), with its date and reason. Another stretch of the order, other
  archives or another count of places is another plan, in a file of its own under another
  name.
- One thing was put into Sections 9 and 10 afterwards, by the commit that added
  `eval_data/questions_archives.jsonl` and before any run: the SHA-256 of that file, in
  the place of the words `<SHA-256 of the question file>`. The test reads the digest as
  those words, so it passes with it and with nothing else.
- `DRAFTER_VERSION` in `src/hepph_paper_miner/drafting/draft.py` and `SIFT_VERSION` in
  `src/hepph_paper_miner/drafting/sift.py` name the texts that draft and sift the
  questions. They are `d3` and `s1` since the last round of their tuning (2026-11-26 UTC),
  and the pre-registration names them by their digests. Do not change those texts, the
  checks of `drafting/checks.py`, the places and kinds of `drafting/places.py`, or the
  rules of `drafting/assign.py` and `drafting/assemble.py` unless the owner asks for
  exactly that: the questions of the evaluation are what these make of its papers.
  `tests/test_draft.py` and `tests/test_sift.py` fail when a text changes under an
  unchanged name. Another text is another generator, and no part of this evaluation.
- No paper of the plan is fetched before the commit that holds the plan is pushed: not by
  a command, and not through the tools of the server. After that they are fetched by
  `survey.run`, from the sample that `drafting.papers` writes.
- The drafts, the replies of the filters and the sheet of the review hold paper text. They
  are written into `runs_private/` and never committed. `results/archives/` holds
  identifiers, kinds, counts and verdicts, and no text of a paper.
- The papers were fetched and the places given out on 2026-11-27 UTC, by the commit that
  holds the plan. `results/archives/sample.jsonl`, `outcomes.jsonl` and `places.jsonl`
  are fixed: `tests/test_archives_results.py` holds each by its SHA-256. A command would
  write its file anew, so `drafting.papers`, `survey.run` and `drafting.assign` are not
  run over them again unless the owner asks for exactly that, and the places are given
  out once.
- The 82 drafts that were left were reviewed on a sheet in `runs_private/`: a first
  reader, a Claude session, drafted the verdicts and notes, and the owner checked each
  against its passage.
  `results/archives/review.jsonl` holds the verdicts as they were read off the sheet on
  2026-11-28 UTC, and is fixed as well. An agent does not change a verdict in it. Where an
  agent fills in such a sheet, it fills in a draft for the owner to check, and the README
  of the folder says who did what.
- `eval_data/questions_archives.jsonl` holds the 42 questions that `drafting.assemble`
  made of the accepted drafts that day, and `results/archives/candidates.jsonl` what
  became of every candidate. Both are fixed: the pre-registration names the question file
  by its SHA-256, and the test holds both by theirs. Do not change a question, an answer,
  a key, an anchor or a note, and do not run `drafting.assemble` over them again. No
  question is left out after the file has its digest (Section 14); what is found about a
  question later is written under Deviations, or in the report.
- `eval_data/questions_rehearsal.jsonl` holds the seven questions of the rehearsal
  (Section 10 of the pre-registration), which `drafting.assemble --rehearsal` made on
  2026-11-28 UTC of the last round of the tuning, and
  `results/archives/rehearsal-candidates.jsonl` what they were made of. Both are fixed,
  and so is the summary of the first try beside them: the test holds the three by their
  SHA-256. Nothing is changed for what the rehearsal shows. A command that fails in it is
  mended, and the change is listed under Deviations.

## Style

- Format with `uvx ruff format` (line length 100).
- The default test run needs no network, no LLM and no TeX. Mark a test that needs one of
  them (`network`, `tex`).
- Comments say why, in plain English.
