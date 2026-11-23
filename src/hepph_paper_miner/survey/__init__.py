"""The survey: of papers drawn by a rule that was fixed beforehand, which can the server read?

The evaluation asks its questions of papers that one person had read, all from one corner
of physics. That says nothing about the papers the reading tools turn away. The survey
counts them: it draws papers from every archive of arXiv's physics group, hands each to
the source the tools use, and writes down whether it came back split into sections, and
if not, why not. It asks no model anything.

plan.py      the plan: which papers are the population, how many are drawn, with which seed
listing.py   the list the sample is drawn from, asked of arXiv piece by piece and checked
sample.py    drawing the sample from that list, in an order anyone can work out again
run.py       the survey itself: every paper of the sample through the source, one line each
sheet.py     the sheet on which a person holds outlines against the papers themselves
records.py   the files all of them write: JSON lines, the same bytes on every system
"""
