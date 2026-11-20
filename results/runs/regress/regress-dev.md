Questions: questions_dev.jsonl, SHA-256 3f337a84c90860e8dcdab7879e8ad8bd52f033320fb8baf2871016469e495926
Before: results/runs/dev/diag-3-tool; 30 runs; tool texts staged-5, flat-4; code 9d8024c
After: results/runs/regress/dev-after; 30 runs; tool texts staged-6, flat-5; code 1b2baa3

- 1 every run ended with an answer: failed
    - dev-02 flat 2: ended as no_answer
    - dev-02 staged 3: ended as no_answer
- 2 the passage was given in every run: passed
- 3 the rule calls no answer wrong: failed
    - dev-02 flat 2: the rule calls the answer wrong
    - dev-02 staged 3: the rule calls the answer wrong
    - dev-03 flat 3: right by the rule in every run before, by_hand now
- 4 no answer left to a person is wrong: passed
- 5 staged was given less text than flat: passed

The runs after, held against the runs before: failed.

| question | layout | side | answered | passage given | rule | responses | characters (median) | cost | rank in a search | calls that failed |  |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| dev-01 | staged | before | 3 / 3 | 3 / 3 | 3 right | 4 4 4 | 10,566 | $0.04 | - | 3 invalid_arguments |  |
| dev-01 | staged | after | 3 / 3 | 3 / 3 | 3 right | 3 3 3 | 10,509 | $0.03 | - | - |  |
| dev-01 | flat | before | 3 / 3 | 3 / 3 | 3 right | 2 2 2 | 147,086 | $0.35 | - | - |  |
| dev-01 | flat | after | 3 / 3 | 3 / 3 | 3 right | 2 2 2 | 147,086 | $0.19 | - | - |  |
| dev-02 | staged | before | 3 / 3 | 3 / 3 | 3 by_hand | 4 4 4 | 19,377 | $0.10 | - | - |  |
| dev-02 | staged | after | 2 / 3 | 3 / 3 | 2 by_hand, 1 wrong | 4 4 4 | 19,594 | $0.08 | - | - |  |
| dev-02 | flat | before | 3 / 3 | 3 / 3 | 3 by_hand | 2 2 2 | 147,086 | $0.35 | - | - |  |
| dev-02 | flat | after | 2 / 3 | 3 / 3 | 2 by_hand, 1 wrong | 2 2 2 | 147,086 | $0.20 | - | - |  |
| dev-03 | staged | before | 3 / 3 | 3 / 3 | 3 right | 4 5 4 | 9,758 | $0.11 | 1 1 1 | - |  |
| dev-03 | staged | after | 3 / 3 | 3 / 3 | 3 right | 5 4 4 | 19,532 | $0.11 | 1 1 1 | - |  |
| dev-03 | flat | before | 3 / 3 | 3 / 3 | 3 right | 3 3 3 | 198,349 | $0.50 | 1 1 1 | - |  |
| dev-03 | flat | after | 3 / 3 | 3 / 3 | 1 by_hand, 2 right | 3 3 3 | 198,349 | $0.33 | 1 1 1 | - |  |
| dev-04 | staged | before | 3 / 3 | 3 / 3 | 3 by_hand | 4 4 4 | 29,191 | $0.11 | - | - |  |
| dev-04 | staged | after | 3 / 3 | 3 / 3 | 3 by_hand | 4 4 4 | 29,408 | $0.07 | - | - |  |
| dev-04 | flat | before | 3 / 3 | 3 / 3 | 3 by_hand | 2 2 2 | 147,086 | $0.50 | - | - |  |
| dev-04 | flat | after | 3 / 3 | 3 / 3 | 3 by_hand | 2 2 2 | 147,086 | $0.19 | - | - |  |
| dev-05 | staged | before | 3 / 3 | 3 / 3 | 3 by_hand | 6 6 5 | 46,717 | $0.19 | - | - |  |
| dev-05 | staged | after | 3 / 3 | 3 / 3 | 3 by_hand | 6 7 7 | 42,562 | $0.17 | none none none | - | more responses than any run before: read the records |
| dev-05 | flat | before | 3 / 3 | 3 / 3 | 3 by_hand | 2 2 2 | 147,086 | $0.20 | - | - |  |
| dev-05 | flat | after | 3 / 3 | 3 / 3 | 3 by_hand | 2 2 2 | 147,086 | $0.20 | - | - |  |
