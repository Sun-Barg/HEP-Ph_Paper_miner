Questions: questions_dev.jsonl, SHA-256 3f337a84c90860e8dcdab7879e8ad8bd52f033320fb8baf2871016469e495926
Before: results/runs/regress/dev-after; 30 runs; tool texts staged-6, flat-5; prompt p2-tool; code 1b2baa3
After: results/runs/asking-again/dev-after; 30 runs; tool texts staged-6, flat-5; prompt p3-tool; code 0af1c02
Criteria: the second set (3 asks only that the rule calls no answer wrong)

- 1 every run ended with an answer: passed
- 2 the passage was given in every run: passed
- 3 the rule calls no answer wrong: passed
- 4 no answer left to a person is wrong: passed
- 5 staged was given less text than flat: passed

The runs after, held against the runs before: passed.

No run after was asked again for the call.

| question | layout | side | answered | passage given | rule | responses | characters (median) | cost | rank in a search | calls that failed |  |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| dev-01 | staged | before | 3 / 3 | 3 / 3 | 3 right | 3 3 3 | 10,509 | $0.03 | - | - |  |
| dev-01 | staged | after | 3 / 3 | 3 / 3 | 3 right | 3 3 3 | 10,509 | $0.03 | - | - |  |
| dev-01 | flat | before | 3 / 3 | 3 / 3 | 3 right | 2 2 2 | 147,086 | $0.19 | - | - |  |
| dev-01 | flat | after | 3 / 3 | 3 / 3 | 3 right | 2 2 2 | 147,086 | $0.19 | - | - |  |
| dev-02 | staged | before | 2 / 3 | 3 / 3 | 2 by_hand, 1 wrong | 4 4 4 | 19,594 | $0.08 | - | - |  |
| dev-02 | staged | after | 3 / 3 | 3 / 3 | 3 by_hand | 4 4 4 | 19,594 | $0.08 | - | - |  |
| dev-02 | flat | before | 2 / 3 | 3 / 3 | 2 by_hand, 1 wrong | 2 2 2 | 147,086 | $0.20 | - | - |  |
| dev-02 | flat | after | 3 / 3 | 3 / 3 | 3 by_hand | 2 2 2 | 147,086 | $0.21 | - | - |  |
| dev-03 | staged | before | 3 / 3 | 3 / 3 | 3 right | 5 4 4 | 19,532 | $0.11 | 1 1 1 | - |  |
| dev-03 | staged | after | 3 / 3 | 3 / 3 | 3 right | 4 4 4 | 19,532 | $0.09 | 1 1 1 | - |  |
| dev-03 | flat | before | 3 / 3 | 3 / 3 | 1 by_hand, 2 right | 3 3 3 | 198,349 | $0.33 | 1 1 1 | - |  |
| dev-03 | flat | after | 3 / 3 | 3 / 3 | 3 right | 3 3 3 | 198,349 | $0.70 | 1 1 1 | - |  |
| dev-04 | staged | before | 3 / 3 | 3 / 3 | 3 by_hand | 4 4 4 | 29,408 | $0.07 | - | - |  |
| dev-04 | staged | after | 3 / 3 | 3 / 3 | 3 by_hand | 4 4 4 | 29,388 | $0.13 | - | - |  |
| dev-04 | flat | before | 3 / 3 | 3 / 3 | 3 by_hand | 2 2 2 | 147,086 | $0.19 | - | - |  |
| dev-04 | flat | after | 3 / 3 | 3 / 3 | 3 by_hand | 2 2 2 | 147,086 | $0.19 | - | - |  |
| dev-05 | staged | before | 3 / 3 | 3 / 3 | 3 by_hand | 6 7 7 | 42,562 | $0.17 | none none none | - |  |
| dev-05 | staged | after | 3 / 3 | 3 / 3 | 3 by_hand | 7 7 6 | 45,029 | $0.22 | none none none | - |  |
| dev-05 | flat | before | 3 / 3 | 3 / 3 | 3 by_hand | 2 2 2 | 147,086 | $0.20 | - | - |  |
| dev-05 | flat | after | 3 / 3 | 3 / 3 | 3 by_hand | 2 2 2 | 147,086 | $0.20 | - | - |  |
