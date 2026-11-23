# Records of what was run after the loop began to ask for the call

Since `0af1c02` the loop asks for the call of `submit_answer` when a turn ends without
it, and the prompt of the way `tool` has the name `p3-tool` ("An answer that was written
and not handed in" in the README of the repository). The same commit wrote down what
would be run with the new prompt and how it would be read. Both things were run on
2026-11-23, from that commit, with the model and the settings of the evaluation. They
are here: the record of twenty requests, the public records of one set of runs, and
what was made from the runs. Nothing here is a result of the evaluation, whose twenty
questions were not asked again.

| here | holds | made (UTC) | what was run | how it ended | cost |
|---|---|---|---|---|---|
| `replay-dev-02.jsonl` | 20 requests | 03:40 to 03:42 | the two runs of dev-02 that had ended their turn without the call (`../regress/dev-after/`): the conversation of each as far as that end, with the message of the loop after it, sent ten times | all 20 responses handed in an answer by the call | $0.37 |
| `dev-after/` | 32 records | 03:43 to 03:52 | dev-01 to dev-05 with each layout, three times | 30 runs count, all answered; arXiv spoilt 2 more, which were run again | $2.18 |

Every record of `dev-after/` names the conditions that the code has since that commit:
those of the runs of 2026-11-20 with the new prompt (`ASKING_AGAIN` in
`eval/conditions.py`). The cost is worked out from the usage at list prices, for
`dev-after/` over every record of the folder.

| file | what it is |
|---|---|
| `regress-dev.md` | what `eval.regress --criteria 2` wrote of `dev-after/` held against `../regress/dev-after/` |
| `dev-sheet.csv`, `dev-key.csv` | the sheet of the 30 answers of `dev-after/` and its key, as `eval.sheet` wrote them. Nobody graded it |
| `dev-j2.jsonl` | the record of the judge `j2` on that sheet: 90 requests, each of which said `right` ($0.33) |

The two CSV files are kept byte for byte (`.gitattributes`), because the record of the
judge names the sheet by its SHA-256. `tests/test_asking_again_results.py` holds the
files against each other, and holds what is said below against the records.

## The two ends of dev-02, sent again: the answer was handed in

On 2026-11-20 the second flat run and the third staged run of dev-02 each ended its
turn with the answer written as text, without the call (`../regress/README.md`).
`eval.replay` builds the conversation of such a run again from its private record,
holds it against the public record line by line, puts the reply that ended the turn
back as it came and the message of the loop after it, and sends that. The request has
the system prompt, the tools and the settings of the run, which the code still has. A
test holds its body to be the body of the request that the loop sends after it has
asked (`tests/test_replay.py`).

How the count would be read was written in `eval/replay.py` in `0af1c02`, before any
request: each conversation is sent ten times. When eighteen or more of the twenty
responses hand in an answer by the call, the message is said to have got the answer
handed in at these two ends. With fewer it is said not to have, and another way to get
such an answer is tried. A response that asks for other tools counts against the
message.

All twenty responses handed in an answer: ten of ten from the conversation of the flat
run, and ten of ten from that of the staged run. By what was written down, the message
got the answer handed in at these two ends, and no other way was tried. Each of the
twenty responses holds one block, the call of `submit_answer`: no text in front of it,
no other tool, no thinking block.

What this shows is small, as the command says of itself. It is two conversations of
one question about one paper, and each request is one response and not a run. It says
nothing of how often a run ends its turn without the call. It says nothing of an end
that looks different either: the run of the evaluation that ended this way (eval-13)
has a thinking block in front of its text, where these two have none, and it was not
sent, because its question belongs to the evaluation.

## The development questions again: passed

`eval/regress.py` names five things the runs after a change have to do. The thirty runs
of `dev-after/` that count were held against the thirty of 2026-11-20, which were made
with the same tool texts and the prompt before (`../regress/dev-after/`), by the second
set of criteria, as `0af1c02` had written down: the five of the first set, with the
third as "the rule calls no answer wrong" and no more. All five hold.

- **1, every run ended with an answer.** All thirty did. Of the thirty before, two had
  not, both of dev-02; its six runs all ended with an answer this time.
- **2, the passage was given in every run.**
- **3, the rule calls no answer wrong.** It calls twelve right and leaves eighteen to a
  person.
- **4, no answer left to a person is wrong.** By the judge, since nobody graded the
  sheet: it called each of the thirty answers right in each of its three requests.
- **5, in every question the staged runs were given less text than the flat ones.**

The first set would have said the same. What the second leaves out of the third
criterion is met here as well: no answer is left to a person where the rule had called
every answer of that question and layout right before.

## The loop asked in no run

No response of the 32 runs ended a turn without a call, so the loop never sent its
message: `asked_again` is null in every record, also in the two that arXiv spoilt. The
thirty runs passed the first criterion because each handed in its answer unasked, and
not because the loop asked.

This had been expected, and it is why the twenty requests were made. Before these runs
a turn had ended without the call in 3 of the 256 runs of this repository that count
and hand in with the tool. At that rate thirty runs meet no such turn seven times in
ten. With the thirty there are 286 such runs, and still three with such a turn.

So the thirty runs say nothing of the message. In a run that is not asked the model
reads what it read before the change: the system prompt and the tools are the same,
and the message is the one text that the new prompt adds (`tests/test_prompt.py`). For
the model these were thirty more runs of the kind made on 2026-11-20, and that all
thirty ended with an answer where two of those had not is no effect of the change.

What stands for the message is the twenty requests above. And no run with the model
behind it has yet gone through being asked: that the loop sends this request when a
turn ends so, and reads the response that comes back as it reads any other, is held by
tests with replies that are made up (`tests/test_loop.py`, `tests/test_replay.py`), and
not by a run.

## What else the records show

None of this decides anything.

- **The twenty answers.** The count asks for a call with an answer of the expected
  form, and no more. Nobody graded the twenty answers, and the judge did not read them.
  The rule of `eval/grade.py` finds in each of them the two numbers and the two phrases
  that the key of dev-02 asks for, and `found` as expected. It leaves each to a person,
  as it does every answer to dev-02, whose key names two things for a person to look
  at. Each answer names `4.2` and `5` as its evidence, the two sections in which the
  passages of the question stand; the ten from the staged run name `4.3` as well, which
  that run had read.
- **The two runs that arXiv spoilt.** Both are the third staged run of dev-05. Each
  asked for a search that arXiv did not answer (`upstream_busy`, after 43 and 59
  seconds), went on, and ended with an answer. A run with such a call does not count,
  so `eval.run` ran the cell again, twice; the third run asked for no search, and
  counts. No other call of the 32 runs came back as an error.
- **The cost.** The thirty runs that count cost $2.04, and the thirty before $1.56.
  That is the API's cache and not the prompt: a request is read from the cache only as
  far as it is the same as a request of the last five minutes. Most of the difference
  is the flat runs of dev-03 ($0.70, before $0.33). Each of the three asked for the
  maintainer's paper and for a search with its first response, and worded the search
  in a way of its own, so each wrote both papers of the question to the cache: 265,431
  tokens in the three. On 2026-11-20 the second run had worded its search as the first
  and wrote nothing, and the third had not asked for the maintainer's paper: 114,049
  tokens. In the same way two of the three staged runs of dev-04 read section `6.3` in
  two parts that they cut themselves (at 14,000 and at 13,000 characters), where the
  three before had all asked for the same two reads ($0.13, before $0.07).
- **The cost of the twenty requests.** The first request of each conversation wrote it
  to the cache (66,230 tokens of the flat run, 11,755 of the staged one), and the nine
  after it read it from there.

## Making the text again

```
uv run python -m hepph_paper_miner.eval.regress --questions eval_data/questions_dev.jsonl --before results/runs/regress/dev-after --after results/runs/asking-again/dev-after --sheet results/runs/asking-again/dev-sheet.csv --key results/runs/asking-again/dev-key.csv --judge results/runs/asking-again/dev-j2.jsonl --criteria 2
```

It needs the paper of dev-03 from arXiv to say whether its passage was given; without
it that criterion is left open for dev-03, and the text says "not decided". The twenty
requests cannot be made again from this repository: the conversations of the two runs
are in their private records, on the computer that made them.
