# Report of the evaluation

Questions: questions_eval.jsonl, SHA-256 67f83aa79c513843d7c105e20a788979783683e70aeaaca5157896bb2dc98281
Records: results/runs/eval; code 70c7384 (120 runs)
Held against the conditions (conditions.py): no record differs
Answers graded by hand: 118 of 118

## By layout

|  | staged | flat |
| --- | --- | --- |
| runs that count | 60 | 60 |
| answered | 58 / 60 | 60 / 60 |
| 1 search listed the paper (questions that do not name it) | 15 / 15 | 15 / 15 |
| 2a passage given | 58 / 60 | 60 / 60 |
| 2b cited strictly / loosely | 57 / 57 of 58 | 60 / 60 of 60 |
| 3 right, by hand (no answer is wrong) | 57 / 60 | 60 / 60 |
| questions right in more than half of their runs | 19 / 20 | 20 / 20 |
| tool result chars per run, median (range) | 20,399 (6,412 to 113,344) | 147,086 (29,560 to 347,325) |
| input tokens per run, median (range) | 19,459 (10,801 to 278,432) | 67,665 (21,539 to 285,781) |
| new paper text per run, median (range) | 15,304 (2,479 to 107,999) | 145,177 (26,201 to 343,907) |
| tool calls per run, median (range) | 3 (2 to 19) | 1 (1 to 7) |
| turns per run, median (range) | 4 (3 to 12) | 2 (2 to 8) |
| repeat reads, all runs | 0 | 0 |
| responses from the passage to the answer, median | 1 | 1 |
| runs with a tool error | 6 | 3 |
| cost, computed | $2.78 | $10.90 |

## H1: tool result characters, question by question

The median of the staged runs is lower in 20 question(s), higher in 0, equal in 0; 0 without runs of both layouts.
One-sided sign test, ties left out: p = 9.537e-07 (n = 20).
Input tokens, the same way: lower in 18, higher in 2, equal in 0; p = 0.0002012.

## H2: answers, question by question

|  | flat right | flat wrong |
| --- | --- | --- |
| staged right | 19 | 0 |
| staged wrong | 1 | 0 |

## Question by question

| question | type | staged right | flat right | staged chars | flat chars | staged passage | flat passage |
| --- | --- | --- | --- | --- | --- | --- | --- |
| eval-01 | single_section | 3 / 3 | 3 / 3 | 23,352 | 147,086 | 3 / 3 | 3 / 3 |
| eval-02 | single_section | 3 / 3 | 3 / 3 | 7,114 | 147,086 | 3 / 3 | 3 / 3 |
| eval-03 | single_section | 3 / 3 | 3 / 3 | 45,493 | 187,185 | 3 / 3 | 3 / 3 |
| eval-04 | single_section | 3 / 3 | 3 / 3 | 37,402 | 46,619 | 3 / 3 | 3 / 3 |
| eval-05 | single_section | 3 / 3 | 3 / 3 | 34,312 | 181,158 | 3 / 3 | 3 / 3 |
| eval-06 | single_section | 3 / 3 | 3 / 3 | 6,580 | 196,046 | 3 / 3 | 3 / 3 |
| eval-07 | single_section | 3 / 3 | 3 / 3 | 8,506 | 104,268 | 3 / 3 | 3 / 3 |
| eval-08 | single_section | 3 / 3 | 3 / 3 | 9,942 | 114,063 | 3 / 3 | 3 / 3 |
| eval-09 | several_sections | 3 / 3 | 3 / 3 | 14,296 | 147,086 | 3 / 3 | 3 / 3 |
| eval-10 | several_sections | 3 / 3 | 3 / 3 | 20,399 | 336,680 | 3 / 3 | 3 / 3 |
| eval-11 | several_sections | 3 / 3 | 3 / 3 | 24,488 | 241,583 | 3 / 3 | 3 / 3 |
| eval-12 | several_sections | 3 / 3 | 3 / 3 | 17,063 | 29,560 | 3 / 3 | 3 / 3 |
| eval-13 | several_sections | 2 / 3 | 3 / 3 | 34,414 | 347,325 | 3 / 3 | 3 / 3 |
| eval-14 | several_sections | 3 / 3 | 3 / 3 | 21,567 | 78,191 | 3 / 3 | 3 / 3 |
| eval-15 | not_in_paper | 1 / 3 | 3 / 3 | 109,279 | 147,086 | 1 / 3 | 3 / 3 |
| eval-16 | not_in_paper | 3 / 3 | 3 / 3 | 28,438 | 187,185 | 3 / 3 | 3 / 3 |
| eval-17 | not_in_paper | 3 / 3 | 3 / 3 | 40,951 | 127,173 | 3 / 3 | 3 / 3 |
| eval-18 | several_places | 3 / 3 | 3 / 3 | 8,110 | 149,026 | 3 / 3 | 3 / 3 |
| eval-19 | several_places | 3 / 3 | 3 / 3 | 18,328 | 155,726 | 3 / 3 | 3 / 3 |
| eval-20 | several_places | 3 / 3 | 3 / 3 | 18,196 | 90,834 | 3 / 3 | 3 / 3 |

Chars are the median of the runs of the question; (?) marks a run not graded yet.

## Why runs were wrong

|  | staged | flat |
| --- | --- | --- |
| answered wrong, its paper was given but not the passage | 1 | 0 |
| no answer: no_answer | 1 | 0 |
| no answer: turn_limit | 1 | 0 |

Tool calls that ended in an error, by kind:

|  | staged | flat |
| --- | --- | --- |
| invalid_arguments | 5 | 0 |
| not_found | 1 | 4 |

## The rule of grade.py and the grade by hand (answered runs)

| rule | staged: right | staged: wrong | staged: not graded | flat: right | flat: wrong | flat: not graded |
| --- | --- | --- | --- | --- | --- | --- |
| right | 0 | 0 | 0 | 0 | 0 | 0 |
| by_hand | 57 | 1 | 0 | 60 | 0 | 0 |
| wrong | 0 | 0 | 0 | 0 | 0 | 0 |

## Runs that do not count

Spoilt runs kept: 0, cost computed $0.00. Cells given up after three spoilt runs: 0. Cells still to run: 0.
