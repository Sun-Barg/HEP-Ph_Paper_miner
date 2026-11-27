"""The evaluation: questions with reference answers, and the grading of runs.

questions.py    reading a question file, and refusing one of the wrong form
check.py        checking a question file against the papers: where its evidence stands
grade.py        grading one run from its public record: search, access, citation, answer
conditions.py   what every run of the evaluation is made with, and holding a record against it
run.py          running the evaluation: every question, both layouts, in a fixed order
sheet.py        the sheet on which a person grades the answers, blind to the layout
report.py       the report of the evaluation: the layouts compared, question by question
judge.py        a model as a second grader of the answers of a sheet
agree.py        the judge held against the grades a person gave
regress.py      the runs of a changed version held against the runs of the one before
replay.py       the end of a run sent again with the message of the loop, and what came back
paired.py       the interval of the difference of two rates on the same questions
hand.py         the second evaluation: which answers a person grades, and the verdict on each
second.py       the report of the second evaluation: one run for a cell, and three graders
"""
