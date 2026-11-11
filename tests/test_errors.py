"""SourceError has to survive a trip between processes. No network, no MCP."""

import copy
import pickle

import pytest

from hepph_paper_miner.sources.base import ErrorKind, SourceError


@pytest.mark.parametrize("kind", list(ErrorKind))
def test_source_error_survives_pickle_and_copy(kind):
    # A process pool pickles a worker's exception and rebuilds it in the parent.
    # If that fails, one expected failure takes the whole pool down with it.
    original = SourceError(kind, "2610.26648v1")

    clones = [
        pickle.loads(pickle.dumps(original)),
        copy.copy(original),
        copy.deepcopy(original),
    ]

    for clone in clones:
        assert type(clone) is SourceError
        assert clone.kind is kind
        assert clone.detail == "2610.26648v1"
        assert str(clone) == str(original)


def test_source_error_without_detail_survives_pickle():
    clone = pickle.loads(pickle.dumps(SourceError(ErrorKind.TIMEOUT)))
    assert (clone.kind, clone.detail) == (ErrorKind.TIMEOUT, "")


def test_str_names_the_kind_and_the_detail():
    assert str(SourceError(ErrorKind.NOT_FOUND, "2610.26648v9")) == "not_found: 2610.26648v9"
