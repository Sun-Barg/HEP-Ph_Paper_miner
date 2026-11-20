# Records of the development runs

The public records of the runs on the five development questions
(`eval_data/questions_dev.jsonl`), one folder for each set of runs. A record says what
was asked for in every turn, how much text came back (sizes and hashes, and the facts of
the first line of each result), what the API counted, and the answer. It holds no text
that a tool returned. "Asking one question" in the README of the repository describes
the form.

Tool texts and the prompt are tuned on these questions, so nothing here is a result of
the evaluation.

| folder | runs | made (UTC) | code | tool texts | what was run | how the runs ended |
|---|---|---|---|---|---|---|
| `first-run/` | 2 | 2026-11-12 17:46 to 17:49 | `8594338` | `staged-3`, `flat-1` | dev-01 with each layout: the first runs against the real API | 2 answered |
| `pilot-1/` | 8 | 2026-11-12 18:08 to 18:13 | `8594338` | `staged-3`, `flat-1` | dev-02 to dev-05 with each layout, once | 6 answered, 2 at the turn limit |
| `pilot-2/` | 8 | 2026-11-13 01:49 to 01:52 | `8594338` | `staged-3`, `flat-1` | the same as `pilot-1/`, a second time | 6 answered, 2 at the turn limit |
| `diag-1/` | 12 | 2026-11-13 06:25 to 06:30 | `c96912a` | `staged-5`, `flat-4` | dev-04 and dev-05 with each layout, three times, with `--cache --show-thinking` | 5 answered, 7 at the turn limit |
| `diag-2/` | 12 | 2026-11-13 08:06 to 08:09 | `62185a7` | `staged-5`, `flat-4` | the same as `diag-1/`, with `--no-answer-format` as well | 12 ended by the model, none with an answer of the expected form |
| `diag-3-tool/` | 30 | 2026-11-16 08:12 to 08:27 | `9d8024c` | `staged-5`, `flat-4` | dev-01 to dev-05 with each layout, three times, with `--answer-channel tool --cache --show-thinking` | 30 answered |
| `diag-3-text/` | 30 | 2026-11-16 08:13 to 08:27 | `9d8024c` | `staged-5`, `flat-4` | the same as `diag-3-tool/`, with `--answer-channel text` instead | 26 answered, 3 at the turn limit, 1 ended by the model without an answer of the expected form |

All of them: model `claude-sonnet-5-5`, effort `high`, at most 12 turns. The prompt is `p1`
in the first five folders, `p2-tool` in `diag-3-tool/` and `p2-text` in `diag-3-text/`.

- The records of the first three folders do not name their code: a record has done that
  since `c96912a` (`code` in its first line). They name the tool texts `staged-3` and
  `flat-1`, and `8594338` is the one commit that has both the loop and those names.
- `pilot-2/` was meant to be run with the code after a round of changes. The folder it
  was run in did not have the changes yet, so `pilot-1/` and `pilot-2/` are two
  repetitions of one condition.
- In `diag-1/` the prompt cache of the API was on. `input_tokens` in those records is
  only the part of a prompt that went through no cache: the size of a prompt is the sum
  of `input_tokens`, `cache_creation_input_tokens` and `cache_read_input_tokens`.
  A later run of the same question and layout read from the cache what an earlier one
  had written, as far as the two had asked for the same things, so the cache counts of a
  run depend on what ran in the five minutes before it. The sum does not.
- In `diag-2/` the request left out the form of the answer (`answer_format` is null in
  the first line of a record). This was a diagnosis: with the form, seven of the twelve
  runs of `diag-1/` went on asking for tools until the turn limit; without it, all
  twelve ended their turn after two to seven responses. The system prompt stayed in the
  request, and it asks for the sections an answer rests on: eleven of the twelve last
  texts name them under the word "Evidence", and two of the texts close with a JSON
  object of their own that has the three fields of an answer and lists its evidence as
  strings. None of the twelve is an answer of the form the loop reads, as a whole or in
  that last part, so these records hold no answer. The texts are in the private records
  only.
- `diag-3-tool/` and `diag-3-text/` are one set of sixty runs, the third diagnosis: the
  two other ways of handing in an answer (`--answer-channel`, "Asking one question" in
  the README of the repository), each on the five questions with both layouts, three
  times. For every question, layout and repetition the two ran one after the other, with
  the cache and the summaries of thinking on, as in `diag-1/`. With `tool` the answer is
  the arguments of a call of `submit_answer`, a tool that the loop adds to those of the
  server. With `text` the prompt asks for one JSON object as the last text, and the
  request holds no form of the answer, as in `diag-2/`.
- With `tool`, all thirty runs handed in an answer, after two to six responses. Three
  calls of `read_section` gave the section under a name the tool does not have (`section`
  in place of `section_id`, in the three runs of dev-01 with the staged layout): each
  came back as an error, and the next call was right.
- With `text`, twenty-six runs ended with an answer that the loop could read, after two
  to eleven responses. Three went on asking for tools until the turn limit. One closed
  with the object inside a code fence, which is not an answer of the form the loop reads
  (the text is in the private record only). Four runs called a tool that does not exist,
  with no arguments: `json`, `json_dump` (twice) and `[object Object]`.
- `diag-3-tool/` is the set from which the conditions of the evaluation were then fixed
  (`src/hepph_paper_miner/eval/conditions.py`; "The conditions of the evaluation" in the
  README of the repository). Its thirty records name those conditions, and no record of
  another folder does: `tests/test_conditions.py` checks both.
- When these runs were made, the command handed in an answer with `format` unless it was
  told otherwise. It now does so with `tool`. To run again what a folder before
  `diag-3-tool/` ran, add `--answer-channel format` to the options in the table.
- The runs made after the tool texts were changed (2026-11-20, `staged-6` and `flat-5`)
  are in `../regress/`, with a README of their own. `diag-3-tool/` is what they are held
  against.
- A file is named after its run: `<UTC time>_<question id>_<layout>_<four random
  characters>.jsonl`.
