# The judge against the grades by hand

Made by `eval/agree.py` from `eval-j2.jsonl`. The grades by hand are the verdicts: the judge changes none of them, and nothing in `results/report.md`.

- Judge `j2`, its texts sha256 `38bc359e5841b16a9d0367ff8cec556e0a285f2c50eab7e4d0e3b04765fea07f`; code `9711ca54fe4a4dded8722a101cfdf581c9c01ec3`; begun 2026-11-19T13:04:33+00:00
- Model `claude-sonnet-5-5`, thinking `adaptive`, effort `high`, max_tokens 16000, anthropic 2.8.0
- 3 requests for every answer; the judge's verdict on an answer is the one that more than half of them gave, and an answer without one has none
- Questions `questions_eval.jsonl`; sheet `grading.csv` (118 rows) with its key `grading-key.csv`; controls `judge_controls_eval.csv` (91)

## The rows of the sheet

| by hand | judge right | judge wrong | no verdict |
| --- | --- | --- | --- |
| right | 117 | 0 | 0 |
| wrong | 0 | 1 | 0 |

The judge's verdict is the grade by hand on 118 of 118 rows. A judge that called every answer right would agree on 117 of them.

All 3 requests said the same on 117 of 118 rows. Of the 354 requests, 352 said right, 2 wrong, and 0 gave no verdict; 78 of the replies held a thinking block.

### Rows graded wrong by hand

- Row 86 (eval-15): wrong by hand; the judge: right, wrong, wrong
  - 1, right: The answer sets found=false and gives no factor, so it reports no result for fixed J-factors and does not borrow a change from another comparison or estimate one from general reasoning, which is what the note requires.
  - 2, wrong: The answer correctly reports no factor, but it says the paper contains no statement about deriving J-fixed limits, whereas the reference says the paper states it derived them for comparison without showing results.
  - 3, wrong: The answer correctly gives no factor, but it denies that the paper states it derives fixed-J-factor limits, whereas the paper does say it derived them for comparison and just reports no result.

### Rows where the judge's verdict is not the grade by hand

None.

### Other rows on which the requests did not all say the same

None.

## The controls

Every control is an answer made to be wrong.

|  | controls | wrong by more than half | wrong in every request | right | no verdict |
| --- | --- | --- | --- | --- | --- |
| all | 91 | 91 | 91 | 0 | 0 |

All 3 requests said the same on 91 of 91 controls. Of the 273 requests, 273 said wrong, 0 right, and 0 gave no verdict; 79 of the replies held a thinking block.

### By the kind of fault

| fault | controls | wrong by more than half | wrong in every request | right | no verdict |
| --- | --- | --- | --- | --- | --- |
| 다른 것을 답함 | 24 | 24 | 24 | 0 | 0 |
| 요소 빠짐 | 20 | 20 | 20 | 0 | 0 |
| 숫자 틀림 | 19 | 19 | 19 | 0 | 0 |
| 뒤바꿔 답함 | 15 | 15 | 15 | 0 | 0 |
| 없는 것을 지어냄 | 6 | 6 | 6 | 0 | 0 |
| 있는데 없다고 함 | 4 | 4 | 4 | 0 | 0 |
| found 표시 틀림 | 3 | 3 | 3 | 0 | 0 |

### By how they were made

| kind | controls | wrong by more than half | wrong in every request | right | no verdict |
| --- | --- | --- | --- | --- | --- |
| 임의 오답 | 64 | 64 | 64 | 0 | 0 |
| accept_note 오답 조건 | 27 | 27 | 27 | 0 | 0 |

| made | controls | wrong by more than half | wrong in every request | right | no verdict |
| --- | --- | --- | --- | --- | --- |
| from a row of the sheet | 71 | 71 | 71 | 0 | 0 |
| written anew | 20 | 20 | 20 | 0 | 0 |

### By question

| question | controls | wrong by more than half | wrong in every request | right | no verdict |
| --- | --- | --- | --- | --- | --- |
| eval-01 | 4 | 4 | 4 | 0 | 0 |
| eval-02 | 5 | 5 | 5 | 0 | 0 |
| eval-03 | 4 | 4 | 4 | 0 | 0 |
| eval-04 | 4 | 4 | 4 | 0 | 0 |
| eval-05 | 5 | 5 | 5 | 0 | 0 |
| eval-06 | 5 | 5 | 5 | 0 | 0 |
| eval-07 | 5 | 5 | 5 | 0 | 0 |
| eval-08 | 4 | 4 | 4 | 0 | 0 |
| eval-09 | 6 | 6 | 6 | 0 | 0 |
| eval-10 | 5 | 5 | 5 | 0 | 0 |
| eval-11 | 4 | 4 | 4 | 0 | 0 |
| eval-12 | 4 | 4 | 4 | 0 | 0 |
| eval-13 | 5 | 5 | 5 | 0 | 0 |
| eval-14 | 5 | 5 | 5 | 0 | 0 |
| eval-15 | 4 | 4 | 4 | 0 | 0 |
| eval-16 | 4 | 4 | 4 | 0 | 0 |
| eval-17 | 4 | 4 | 4 | 0 | 0 |
| eval-18 | 6 | 6 | 6 | 0 | 0 |
| eval-19 | 5 | 5 | 5 | 0 | 0 |
| eval-20 | 3 | 3 | 3 | 0 | 0 |

### Against the rule of grade.py

What the rule says of the text of a control, read as an answer a run handed in. `by_hand`: nothing the rule checks is missing, and a person has to read it.

| rule | controls | wrong by more than half | wrong in every request | right | no verdict |
| --- | --- | --- | --- | --- | --- |
| wrong | 47 | 47 | 47 | 0 | 0 |
| by_hand | 44 | 44 | 44 | 0 | 0 |

### Controls not called wrong in every request

None.

## H2 with the judge's verdicts

A layout answers a question right when more than half of its runs that count are right, and a run without an answer is wrong. By hand, as in `results/report.md`:

|  | flat right | flat wrong |
| --- | --- | --- |
| staged right | 19 | 0 |
| staged wrong | 1 | 0 |

With the judge's verdict in place of the grade by hand:

|  | flat right | flat wrong |
| --- | --- | --- |
| staged right | 19 | 0 |
| staged wrong | 1 | 0 |

Questions in which the runs called right are not the same:

None.

## The requests

627 requests, each with a reply; 157 of the replies held a thinking block. Requests that failed at the API and were asked again: 0.

Input 1,084,533 tokens, output 94,713 tokens, thinking included. $3.12, worked out from the usage at the prices of `eval/report.py`; not read from the Console.
