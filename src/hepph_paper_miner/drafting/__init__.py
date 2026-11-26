"""The second evaluation: questions that a model drafts about papers that nobody picked.

The first evaluation asked twenty questions about papers that one person had read.
This one takes its papers by the rule of the survey (places 41 to 80 of four archives
in the survey's order), gives every paper one place to ask about, has a model draft a
question bound to a passage there, and sifts the drafts by program, by model and by
hand before any run. A pre-registration says why and how, and it is committed with the
plan before any of those papers is fetched.

The parts, in the order they are used:

    papers.py   which papers: places 41 to 80 of the survey's order, from its list
    places.py   where in a split paper a question can stand, and of which kind
    assign.py   which place every paper is given, by a rule that no choice enters; and
                the command that writes the places, for a round of the tuning of the
                texts or for the papers of the evaluation
    draft.py    the generator: a model drafts a question bound to a passage of a place
    checks.py   what a program checks of a draft
    sift.py     the checks, then two filters of a model: without the paper, and with the
                passage alone
    review.py   the sheet on which every draft that is kept is read beside its passage
    ask.py      how draft.py and sift.py ask the model and keep its replies

eval/paired.py holds the interval that the comparison of the two layouts is read by.
"""
