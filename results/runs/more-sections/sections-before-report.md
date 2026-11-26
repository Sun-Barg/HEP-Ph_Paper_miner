# Report of the evaluation

Questions: questions_sections_parser4.jsonl, SHA-256 f60ee6da61f4e9ec7034c2c9d996ac7db6197b82b3721dc8752ca5dd90f7fda0
Records: ../HEP-Ph_Paper_miner/results/runs/more-sections/sections-before; code e7e9576 (36 runs)
Held against the conditions 'asking-again' (conditions.py): no record differs
Answers graded by hand: 0 of 36 (no sheet given)

## By layout

|  | staged | flat |
| --- | --- | --- |
| runs that count | 18 | 18 |
| answered | 18 / 18 | 18 / 18 |
| of them after the loop had asked again for the call | 0 | 0 |
| 1 search listed the paper (questions that do not name it) | 0 / 0 | 0 / 0 |
| 2a passage given | 15 / 18 | 15 / 18 |
| 2b cited strictly / loosely | 18 / 18 of 18 | 15 / 15 of 18 |
| 3 right, by hand (no answer is wrong) | 0 / 0 (18 not graded) | 0 / 0 (18 not graded) |
| questions right in more than half of their runs | 0 / 0 | 0 / 0 |
| tool result chars per run, median (range) | 19,022 (9,862 to 29,105) | 30,966 (22,524 to 36,693) |
| input tokens per run, median (range) | 20,742 (12,102 to 35,795) | 17,898.5 (13,498 to 38,443) |
| new paper text per run, median (range) | 17,468 (8,197 to 27,811) | 29,849 (21,604 to 35,259) |
| tool calls per run, median (range) | 2.5 (2 to 7) | 1 (1 to 2) |
| turns per run, median (range) | 3.5 (3 to 6) | 2 (2 to 3) |
| repeat reads, all runs | 0 | 0 |
| responses from the passage to the answer, median | 1 | 1 |
| runs with a tool error | 0 | 0 |
| cost, computed | $0.34 | $0.33 |

## H1: tool result characters, question by question

The median of the staged runs is lower in 5 question(s), higher in 1, equal in 0; 0 without runs of both layouts.
One-sided sign test, ties left out: p = 0.1094 (n = 6).
Input tokens, the same way: lower in 2, higher in 4, equal in 0; p = 0.8906.

## H2: answers, question by question

|  | flat right | flat wrong |
| --- | --- | --- |
| staged right | 0 | 0 |
| staged wrong | 0 | 0 |

6 question(s) not in the table: a run of theirs is not graded yet.

## Question by question

| question | type | staged right | flat right | staged chars | flat chars | staged passage | flat passage |
| --- | --- | --- | --- | --- | --- | --- | --- |
| sec-01 | text_left_out | 0 / 3 (?) | 0 / 3 (?) | 13,708 | 34,622 | 0 / 3 | 0 / 3 |
| sec-02 | one_block_second_piece | 0 / 3 (?) | 0 / 3 (?) | 29,105 | 28,731 | 3 / 3 | 3 / 3 |
| sec-03 | one_block_first_piece | 0 / 3 (?) | 0 / 3 (?) | 20,754 | 27,730 | 3 / 3 | 3 / 3 |
| sec-04 | one_block_second_piece | 0 / 3 (?) | 0 / 3 (?) | 9,862 | 36,693 | 3 / 3 | 3 / 3 |
| sec-05 | one_block_second_piece | 0 / 3 (?) | 0 / 3 (?) | 16,645 | 33,732 | 3 / 3 | 3 / 3 |
| sec-06 | one_block_first_piece | 0 / 3 (?) | 0 / 3 (?) | 21,196 | 22,524 | 3 / 3 | 3 / 3 |

Chars are the median of the runs of the question; (?) marks a run not graded yet.

## Why runs were wrong

No run is wrong, or none is graded yet.

## The rule of grade.py and the grade by hand (answered runs)

| rule | staged: right | staged: wrong | staged: not graded | flat: right | flat: wrong | flat: not graded |
| --- | --- | --- | --- | --- | --- | --- |
| right | 0 | 0 | 6 | 0 | 0 | 6 |
| by_hand | 0 | 0 | 9 | 0 | 0 | 9 |
| wrong | 0 | 0 | 3 | 0 | 0 | 3 |

## Runs that do not count

Spoilt runs kept: 0, cost computed $0.00. Cells given up after three spoilt runs: 0. Cells still to run: 0.
