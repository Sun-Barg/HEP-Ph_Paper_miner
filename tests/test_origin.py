"""Which code made a record: the commit, and whether a kept file had been changed.

Each test makes a small repository of its own with git, so nothing here depends on the
state of this one. Without git on the machine the tests are skipped; the last one shows
what a record then holds.
"""

import hashlib
import shutil
import subprocess

import pytest

from hepph_paper_miner.agent.origin import code_version, file_digest

needs_git = pytest.mark.skipif(shutil.which("git") is None, reason="git is not installed")


def git(folder, *arguments: str) -> str:
    # Nothing of the machine's own git settings: no signing, a name of its own.
    settings = ["-c", "user.name=Test", "-c", "user.email=test@example.invalid"]
    settings += ["-c", "commit.gpgsign=false", "-c", "core.autocrlf=false"]
    done = subprocess.run(
        ["git", "-C", str(folder), *settings, *arguments],
        capture_output=True,
        text=True,
        check=True,
    )
    return done.stdout.strip()


@pytest.fixture
def repository(tmp_path):
    """A repository with one commit that keeps code/loop.py."""
    folder = tmp_path / "repository"
    (folder / "code").mkdir(parents=True)
    (folder / "code" / "loop.py").write_text("x = 1\n", encoding="utf-8")
    git(folder, "init", "--quiet")
    git(folder, "add", "code/loop.py")
    git(folder, "commit", "--quiet", "-m", "first")
    return folder


@needs_git
def test_the_commit_is_named_and_unchanged_code_is_called_unchanged(repository):
    found = code_version(repository / "code" / "loop.py")
    assert found == {"commit": git(repository, "rev-parse", "HEAD"), "modified": False}
    assert len(found["commit"]) == 40


@needs_git
def test_a_change_to_a_kept_file_shows_wherever_in_the_repository_it_is(repository):
    (repository / "code" / "other.py").write_text("y = 1\n", encoding="utf-8")
    git(repository, "add", "code/other.py")
    git(repository, "commit", "--quiet", "-m", "second")
    (repository / "code" / "other.py").write_text("y = 2\n", encoding="utf-8")

    found = code_version(repository / "code" / "loop.py")

    assert found == {"commit": git(repository, "rev-parse", "HEAD"), "modified": True}


@needs_git
def test_a_new_file_that_the_repository_does_not_keep_is_no_change(repository):
    # A run writes its public record into the folder. That is not a change to the code.
    (repository / "results").mkdir()
    (repository / "results" / "run-1.jsonl").write_text("{}\n", encoding="utf-8")
    assert code_version(repository / "code" / "loop.py")["modified"] is False


@needs_git
def test_code_that_only_lies_inside_a_repository_is_not_named_by_its_commit(repository):
    # An installed copy in a virtual environment inside the folder, say: the commit of
    # the folder says nothing about it.
    copy = repository / ".venv" / "site-packages" / "loop.py"
    copy.parent.mkdir(parents=True)
    copy.write_text("x = 0\n", encoding="utf-8")
    assert code_version(copy) == {"commit": None, "modified": None}


@needs_git
def test_outside_a_repository_there_is_nothing_to_name(tmp_path):
    lone = tmp_path / "loop.py"
    lone.write_text("x = 1\n", encoding="utf-8")
    assert code_version(lone) == {"commit": None, "modified": None}


def test_without_git_the_record_says_that_it_does_not_know(repository_without_git):
    assert code_version(repository_without_git) == {"commit": None, "modified": None}


@pytest.fixture
def repository_without_git(tmp_path, monkeypatch):
    lone = tmp_path / "loop.py"
    lone.write_text("x = 1\n", encoding="utf-8")
    monkeypatch.setenv("PATH", str(tmp_path / "nowhere"))
    return lone


def test_the_code_that_runs_these_tests_is_named_like_any_other():
    # Whatever this checkout is (a clone, or an unpacked copy without git): the two
    # values are there, and they are of the kinds a record promises.
    found = code_version()
    assert set(found) == {"commit", "modified"}
    assert found["commit"] is None or len(found["commit"]) == 40
    assert found["modified"] in (None, True, False)
    assert (found["commit"] is None) == (found["modified"] is None)


def test_a_file_is_named_by_the_digest_of_its_bytes(tmp_path):
    path = tmp_path / "questions.jsonl"
    path.write_bytes(b'{"id": "q1"}\r\n')
    assert file_digest(path) == hashlib.sha256(b'{"id": "q1"}\r\n').hexdigest()
