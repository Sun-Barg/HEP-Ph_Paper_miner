Questions: questions_target.jsonl, SHA-256 63e37b9575d564b74489558aed618374f993731d767c9f47890a2db57afaba94
Before: results/runs/regress/target-before; 18 runs; tool texts staged-5, flat-4; code e66a854
After: results/runs/regress/target-after; 18 runs; tool texts staged-6, flat-5; code 1b2baa3

Runs of the staged layout in which the passage was given:

- tgt-01: 2 of 3 before, 3 after
- tgt-02: 0 of 3 before, 3 after
- tgt-03: 2 of 3 before, 2 after

The effect of the change on these questions: shown.

| question | layout | side | answered | passage given | rule | responses | characters (median) | cost | rank in a search | calls that failed |  |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| tgt-01 | staged | before | 3 / 3 | 2 / 3 | 2 right, 1 wrong | 6 9 7 | 55,943 | $0.22 | none none none | - |  |
| tgt-01 | staged | after | 3 / 3 | 3 / 3 | 3 right | 4 4 4 | 9,337 | $0.04 | none none none | - |  |
| tgt-01 | flat | before | 3 / 3 | 3 / 3 | 3 right | 2 2 2 | 147,086 | $0.19 | - | - |  |
| tgt-01 | flat | after | 3 / 3 | 3 / 3 | 3 right | 2 2 2 | 147,086 | $0.19 | - | - |  |
| tgt-02 | staged | before | 3 / 3 | 0 / 3 | 3 wrong | 8 7 7 | 41,529 | $0.18 | - | - |  |
| tgt-02 | staged | after | 3 / 3 | 3 / 3 | 3 by_hand | 4 4 4 | 11,992 | $0.05 | - | - |  |
| tgt-02 | flat | before | 3 / 3 | 3 / 3 | 3 by_hand | 2 2 2 | 147,086 | $0.19 | - | - |  |
| tgt-02 | flat | after | 3 / 3 | 3 / 3 | 3 by_hand | 2 2 2 | 147,086 | $0.19 | - | - |  |
| tgt-03 | staged | before | 3 / 3 | 2 / 3 | 3 by_hand | 11 5 11 | 96,229 | $0.37 | - | - |  |
| tgt-03 | staged | after | 3 / 3 | 2 / 3 | 2 by_hand, 1 wrong | 4 3 10 | 21,439 | $0.18 | - | - |  |
| tgt-03 | flat | before | 3 / 3 | 3 / 3 | 3 by_hand | 2 2 2 | 147,086 | $0.19 | - | - |  |
| tgt-03 | flat | after | 3 / 3 | 3 / 3 | 3 by_hand | 2 2 2 | 147,086 | $0.19 | - | - |  |
