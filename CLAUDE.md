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
  the tool texts as they were changed after the evaluation) and what the code has now
  (`ASKING_AGAIN`: `REVISED` with the prompt that holds the loop's message for a turn that
  ends without the call). When the owner has a text changed, its new name goes into a new
  set of conditions there, never into a set that runs were made under: every record stays
  held against the conditions it was made under. Runs made before a change are no runs of
  what comes after, so the development questions are run again and held against the runs
  before (`eval/regress.py`).

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
- `unanswered` is not an outcome of the survey. A number about the papers that were read
  is given with the papers that are still unanswered beside it, never with them counted
  as failures or left out without a word.

## Style

- Format with `uvx ruff format` (line length 100).
- The default test run needs no network, no LLM and no TeX. Mark a test that needs one of
  them (`network`, `tex`).
- Comments say why, in plain English.
