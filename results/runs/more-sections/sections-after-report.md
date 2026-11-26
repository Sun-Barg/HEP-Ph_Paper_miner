# Report of the evaluation

Questions: questions_sections_parser5.jsonl, SHA-256 717f1709c7a34b8775667a299ab123f87d370f07de11059d65fc5a31130a1076
Records: results/runs/more-sections/sections-after; code 44bca1f (36 runs)
Held against the conditions 'more-sections' (conditions.py): no record differs
Answers graded by hand: 0 of 36 (no sheet given)

## By layout

|  | staged | flat |
| --- | --- | --- |
| runs that count | 18 | 18 |
| answered | 18 / 18 | 18 / 18 |
| of them after the loop had asked again for the call | 0 | 0 |
| 1 search listed the paper (questions that do not name it) | 0 / 0 | 0 / 0 |
| 2a passage given | 18 / 18 | 18 / 18 |
| 2b cited strictly / loosely | 18 / 18 of 18 | 18 / 18 of 18 |
| 3 right, by hand (no answer is wrong) | 0 / 0 (18 not graded) | 0 / 0 (18 not graded) |
| questions right in more than half of their runs | 0 / 0 | 0 / 0 |
| tool result chars per run, median (range) | 8,484.5 (1,922 to 22,307) | 31,333 (22,675 to 60,522) |
| input tokens per run, median (range) | 11,689.5 (8,841 to 16,930) | 17,968.5 (13,591 to 30,729) |
| new paper text per run, median (range) | 6,870 (502 to 20,000) | 30,422.5 (21,754 to 59,146) |
| tool calls per run, median (range) | 2 (2 to 3) | 1 (1 to 1) |
| turns per run, median (range) | 3 (3 to 3) | 2 (2 to 2) |
| repeat reads, all runs | 0 | 0 |
| responses from the passage to the answer, median | 1 | 1 |
| runs with a tool error | 0 | 0 |
| cost, computed | $0.19 | $0.31 |

## H1: tool result characters, question by question

The median of the staged runs is lower in 6 question(s), higher in 0, equal in 0; 0 without runs of both layouts.
One-sided sign test, ties left out: p = 0.01562 (n = 6).
Input tokens, the same way: lower in 6, higher in 0, equal in 0; p = 0.01562.

## H2: answers, question by question

|  | flat right | flat wrong |
| --- | --- | --- |
| staged right | 0 | 0 |
| staged wrong | 0 | 0 |

6 question(s) not in the table: a run of theirs is not graded yet.

## Question by question

| question | type | staged right | flat right | staged chars | flat chars | staged passage | flat passage |
| --- | --- | --- | --- | --- | --- | --- | --- |
| sec-01 | text_left_out | 0 / 3 (?) | 0 / 3 (?) | 22,297 | 60,522 | 3 / 3 | 3 / 3 |
| sec-02 | one_block_second_piece | 0 / 3 (?) | 0 / 3 (?) | 2,658 | 28,877 | 3 / 3 | 3 / 3 |
| sec-03 | one_block_first_piece | 0 / 3 (?) | 0 / 3 (?) | 11,864 | 27,713 | 3 / 3 | 3 / 3 |
| sec-04 | one_block_second_piece | 0 / 3 (?) | 0 / 3 (?) | 7,572 | 36,698 | 3 / 3 | 3 / 3 |
| sec-05 | one_block_second_piece | 0 / 3 (?) | 0 / 3 (?) | 9,397 | 33,789 | 3 / 3 | 3 / 3 |
| sec-06 | one_block_first_piece | 0 / 3 (?) | 0 / 3 (?) | 1,922 | 22,675 | 3 / 3 | 3 / 3 |

Chars are the median of the runs of the question; (?) marks a run not graded yet.

## Why runs were wrong

No run is wrong, or none is graded yet.

## The rule of grade.py and the grade by hand (answered runs)

| rule | staged: right | staged: wrong | staged: not graded | flat: right | flat: wrong | flat: not graded |
| --- | --- | --- | --- | --- | --- | --- |
| right | 0 | 0 | 12 | 0 | 0 | 9 |
| by_hand | 0 | 0 | 6 | 0 | 0 | 9 |
| wrong | 0 | 0 | 0 | 0 | 0 | 0 |

## Runs that do not count

Spoilt runs kept: 0, cost computed $0.00. Cells given up after three spoilt runs: 0. Cells still to run: 0.
