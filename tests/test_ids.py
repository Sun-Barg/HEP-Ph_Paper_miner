"""arXiv identifier parsing. No network, no MCP."""

from pathlib import Path

import pytest

from hepph_paper_miner.sources.base import (
    OLD_SCHEME_ARCHIVES,
    ErrorKind,
    SourceError,
    parse_arxiv_id,
)

TARGET_LIST = Path(__file__).parent.parent / "eval_data" / "target_papers.txt"

VALID = [
    # text, base, version
    ("2610.26648v1", "2610.26648", 1),
    ("2610.26648", "2610.26648", None),
    ("0704.0001", "0704.0001", None),  # first month of the new scheme
    ("1412.9999v12", "1412.9999", 12),  # last month with four digits
    ("1501.00001v3", "1501.00001", 3),  # first month with five digits
    ("2610.26648v999", "2610.26648", 999),  # largest version accepted
    ("9912.12345v2", "9912.12345", 2),  # arXiv's own example: a month that has not come yet
    ("hep-ph/0404175v2", "hep-ph/0404175", 2),
    ("hep-th/9107001", "hep-th/9107001", None),  # first month of the old scheme as arXiv states it
    ("hep-th/9108001", "hep-th/9108001", None),
    ("math/0703999", "math/0703999", None),  # last month of the old scheme
    ("  arXiv:2610.26648v1 ", "2610.26648", 1),
    ("ARXIV:hep-ph/0404175", "hep-ph/0404175", None),
]

INVALID = [
    "",
    "   ",
    "not an id",
    "2610.2664",  # four digits after 2015-01
    "1412.12345",  # five digits before 2015-01
    "2613.12345",  # month 13
    "2600.12345",  # month 00
    "0703.1234",  # new scheme before it started
    "2610.26648v0",
    "2610.26648v",
    "2610.26648 v1",
    "2610.26648v1.2",
    "https://arxiv.org/abs/2610.26648",
    "abs/2610.26648",
    "hep-ph/040417",  # six digits
    "hep-ph/0704001",  # old scheme after it ended
    "hep-ph/9013001",  # month 13
    "HEP-PH/0404175",
    "math.GT/0309136",  # subject-class form is not accepted
    "2610.26648v1000",  # more than three version digits
    "2610.26648v9999",
    "0704.0000",  # sequence numbers start at 1
    "2610.00000",
    "hep-ph/0404000",
    "hep-th/9106001",  # before the first month of the old scheme
    "hep-th/9101001",
    "foo/0404175",  # not an arXiv archive
    "abc-def/0404175",
    "stat/0703001",  # stat opened together with the new scheme
    "test/0404175",  # arXiv's internal archive
]


def in_other_digits(text: str, zero: str) -> str:
    """Rewrite the ASCII digits of `text` in another script, given that script's zero."""
    return "".join(chr(ord(zero) + int(char)) if char in "0123456789" else char for char in text)


FULLWIDTH_ZERO = "\uff10"
ARABIC_INDIC_ZERO = "\u0660"
DEVANAGARI_ZERO = "\u0966"

# int() and `\d` both take these for digits; an identifier written with them is not one.
NOT_ASCII = [
    in_other_digits("2610.26648", FULLWIDTH_ZERO),
    in_other_digits("2610.26648", ARABIC_INDIC_ZERO),
    in_other_digits("hep-ph/0404175", FULLWIDTH_ZERO),
    "26" + in_other_digits("10", DEVANAGARI_ZERO) + ".26648",  # one field only
    "2610.26648v1" + in_other_digits("2", ARABIC_INDIC_ZERO),  # inside the version
]

# Longer than int() converts by default (4300 digits): must be a rejection, not a crash.
ENDLESS_VERSION = pytest.param("2610.26648v" + "9" * 5000, id="version-of-5000-digits")


@pytest.mark.parametrize(("text", "base", "version"), VALID)
def test_valid_identifier_is_split_into_base_and_version(text, base, version):
    parsed = parse_arxiv_id(text)
    assert (parsed.base, parsed.version) == (base, version)


@pytest.mark.parametrize("text", [*INVALID, *NOT_ASCII, ENDLESS_VERSION])
def test_invalid_identifier_raises_invalid_id_and_keeps_the_input(text):
    with pytest.raises(SourceError) as caught:
        parse_arxiv_id(text)
    assert caught.value.kind is ErrorKind.INVALID_ID
    assert caught.value.detail == text


def test_str_gives_back_the_normalized_identifier():
    assert str(parse_arxiv_id(" arXiv:1402.6703v2 ")) == "1402.6703v2"
    assert str(parse_arxiv_id("1402.6703")) == "1402.6703"


def test_every_listed_archive_is_accepted_in_an_old_identifier():
    # 34 in arXiv's taxonomy. The count catches an accidental edit of the list,
    # the loop catches a name that the pattern for old identifiers cannot match.
    assert len(OLD_SCHEME_ARCHIVES) == 34
    for archive in sorted(OLD_SCHEME_ARCHIVES):
        assert parse_arxiv_id(f"{archive}/0001001").base == f"{archive}/0001001"


def read_target_ids() -> list[str]:
    lines = TARGET_LIST.read_text(encoding="utf-8").splitlines()
    return [line.strip() for line in lines if line.strip() and not line.lstrip().startswith("#")]


def test_target_list_is_version_pinned_and_has_no_duplicates():
    ids = read_target_ids()
    assert ids, "the target list is empty"
    assert len(ids) == len(set(ids))
    for text in ids:
        parsed = parse_arxiv_id(text)
        assert parsed.version is not None, f"{text}: version is not pinned"
        assert str(parsed) == text, f"{text}: not in normalized form"
