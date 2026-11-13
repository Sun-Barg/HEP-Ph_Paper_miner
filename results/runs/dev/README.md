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

All of them: model `claude-sonnet-5-5`, effort `high`, prompt `p1`, at most 12 turns.

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
- A file is named after its run: `<UTC time>_<question id>_<layout>_<four random
  characters>.jsonl`.
