# Notes on the question file of the evaluation

`questions_eval.jsonl` is fixed by its digest. The pre-registration names it, and so do
the first line of every record of the evaluation and the record of the judge. A change
to the file would cut all of them loose from it. So what was learned about a question
after the runs is written here, and the file stays as it is.

## eval-15: what its `accept_note` leaves unsaid

The note calls an answer right when it says, with found = false, that the paper only
states that limits with fixed J-factors were derived for comparison, and reports no
result of them. It names two kinds of wrong answer: one that takes the change seen in
another comparison of the paper for the effect of fixing the J-factors, and one that
estimates the factor from a general argument.

It does not say what to do with an answer that gives no number, has found = false, and
says that it could not find the statement that such limits were derived. That answer
denies a statement which the paper makes and the question repeats. On 2026-11-18 the
grader decided that it is wrong, and held every row of eval-15 to that. The criterion
stands in the `note` column of row 86 of `results/grading.csv`, and how the decision
came about is in the pre-registration, Section 10.

A new question file that takes this question over should say so in its note. In the
words of the note:

> ‘고정 J 한계도 구했다’는 논문의 서술 자체를 찾지 못했다고 답하면, found = false 이고 배수를 내지 않았더라도 오답.

The judge (`eval/judge.py`) was given the note as it stands in the file, without this
sentence.
