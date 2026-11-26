"""The interval that the second evaluation reads its comparison of the two layouts by.

Every question is asked of both layouts once, so the answers come in pairs: right in
both, right in staged only (b of them), right in flat only (c), right in neither. The
difference of the two rates of right answers is (b - c) / n.

Its interval is the adjusted Wald interval for matched pairs of Agresti and Min (2005),
which they call Wald+2: one half is added to each of the four cells, and the Wald
interval is taken of what results. Without the halves, a table on which the layouts
never differ would give an interval of no width, as if 80 questions had settled it.
The formula is the one of the R function diffpropci.mp of the package PropCIs and of
the R code on Agresti's pages (both read on 2026-11-26), which write the difference the
other way round, as c - b.

The pre-registration reads the interval against a margin m: its lower end above -m says
"not worse by more than m", its upper end below 0 says "worse". When both hold, both are
said; when neither holds, nothing has been shown either way.
"""

from __future__ import annotations

import math

Z95 = 1.959963984540054  # the 97.5% point of the standard normal distribution

NOT_WORSE = "not worse by more than the margin"
WORSE = "worse"
WORSE_WITHIN = "worse, by no more than the margin"
NOT_SHOWN = "not shown either way"


def adjusted_wald(b: int, c: int, n: int, z: float = Z95) -> tuple[float, float, float]:
    """The difference of the rates, staged less flat, with its interval: estimate, low, high.

    `b` questions right in staged only, `c` in flat only, of `n` questions. An end that
    would reach past -1 or 1 is cut there, as PropCIs does.
    """
    if min(b, c) < 0 or b + c > n:
        raise ValueError(f"{b} and {c} questions that differ are no pairs of {n} questions")
    cells = n + 2
    estimate = (b - c) / cells
    spread = z * math.sqrt((b + c + 1) - (b - c) ** 2 / cells) / cells
    return estimate, max(-1.0, estimate - spread), min(1.0, estimate + spread)


def reading(low: float, high: float, margin: float) -> str:
    """What an interval says against the margin, in the words of the pre-registration."""
    above = low > -margin
    below = high < 0
    if above and below:
        return WORSE_WITHIN
    if above:
        return NOT_WORSE
    if below:
        return WORSE
    return NOT_SHOWN
