"""The interval that the comparison of the two layouts is read by (eval/paired.py)."""

import math

import pytest

from hepph_paper_miner.eval.paired import (
    NOT_SHOWN,
    NOT_WORSE,
    WORSE,
    WORSE_WITHIN,
    Z95,
    adjusted_wald,
    reading,
)


def diffpropci_mp(b, c, n, z=Z95):
    """diffpropci.mp of the R package PropCIs, line by line, without its cut at -1 and 1.

    From rdrr.io/cran/PropCIs/src/R/diffpropci.mp.R, read 2026-11-26; the same lines stand
    in the R code for matched pairs on Agresti's pages. It writes the difference as c - b.
    """
    diff = (c - b) / (n + 2)
    sd = math.sqrt((b + c + 1) - (c - b) ** 2 / (n + 2)) / (n + 2)
    return diff, diff - z * sd, diff + z * sd


def test_it_is_the_interval_of_propcis_with_the_difference_turned_round():
    # The example of the PropCIs manual, diffpropci.mp(b = 40, c = 20, n = 160): its b is
    # the questions right in the first only, so here it is the c of flat.
    ours = adjusted_wald(20, 40, 160)
    assert ours == pytest.approx(diffpropci_mp(40, 20, 160), abs=1e-12)
    # What that gives, written out (the manual prints no output).
    assert ours == pytest.approx((-0.12345679, -0.21601726, -0.03089632), abs=1e-8)
    for b, c, n in ((0, 0, 80), (3, 5, 80), (7, 2, 80), (12, 30, 300)):
        assert adjusted_wald(b, c, n) == pytest.approx(diffpropci_mp(c, b, n), abs=1e-12)


def test_a_table_on_which_the_layouts_never_differ_still_has_a_width():
    estimate, low, high = adjusted_wald(0, 0, 80)
    assert estimate == 0 and high == pytest.approx(Z95 / 82) and low == -high


def test_an_end_past_one_is_cut():
    assert adjusted_wald(3, 0, 3)[2] == 1.0
    assert adjusted_wald(0, 3, 3)[1] == -1.0


def test_counts_that_are_no_pairs_are_refused():
    for b, c, n in ((-1, 0, 5), (3, 3, 5)):
        with pytest.raises(ValueError, match="no pairs"):
            adjusted_wald(b, c, n)


def test_the_readings_of_the_design():
    # The tables that the design (DESIGN 14, section 21-14-2, item 12) gives as examples.
    for b, c, said in ((3, 3, NOT_WORSE), (2, 5, NOT_SHOWN), (0, 8, WORSE)):
        _, low, high = adjusted_wald(b, c, 80)
        assert reading(low, high, 0.10) == said
    assert adjusted_wald(3, 3, 80)[2] == pytest.approx(0.063, abs=5e-4)
    assert adjusted_wald(2, 5, 80)[1:] == pytest.approx((-0.104, 0.031), abs=5e-4)
    assert adjusted_wald(0, 8, 80)[1:] == pytest.approx((-0.166, -0.029), abs=5e-4)


def test_worse_and_not_worse_by_more_than_the_margin_can_both_hold():
    _, low, high = adjusted_wald(0, 30, 2000)
    assert -0.10 < low and high < 0
    assert reading(low, high, 0.10) == WORSE_WITHIN


def test_with_eighty_questions_they_never_hold_both():
    # So the pre-registration can read 80 questions in three ways.
    for b in range(81):
        for c in range(81 - b):
            _, low, high = adjusted_wald(b, c, 80)
            assert reading(low, high, 0.10) != WORSE_WITHIN


def test_the_ends_of_the_margin():
    assert reading(-0.0999, 0.05, 0.10) == NOT_WORSE
    assert reading(-0.10, 0.05, 0.10) == NOT_SHOWN
    assert reading(-0.20, -0.0001, 0.10) == WORSE
    assert reading(-0.20, 0.0, 0.10) == NOT_SHOWN
