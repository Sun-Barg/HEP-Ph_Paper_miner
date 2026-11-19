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
  model, its settings and the limits of a run. They are fixed. Do not change that file, a
  version it names or a default it covers unless the owner asks for exactly that.
  `tests/test_conditions.py` fails when one of them moves, and editing the expected values
  until it passes is not a fix.

## Style

- Format with `uvx ruff format` (line length 100).
- The default test run needs no network, no LLM and no TeX. Mark a test that needs one of
  them (`network`, `tex`).
- Comments say why, in plain English.
