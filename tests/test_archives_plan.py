"""The plan and the pre-registration of the second evaluation, held to the repository.

Both were committed before any paper of the evaluation was fetched, and are fixed since.
The plan is held by its SHA-256. Of the pre-registration, Sections 1 to 15 are held by
theirs, with the digest of the question file put back to the words that stood for it:
that digest is the one thing that is put in later, by the commit that adds the file.
What turns out otherwise goes under Deviations (Section 16), which is not held.

The other tests read the numbers of the pre-registration off the plan and the code: a
sentence that names a count, a version or a digest has to be the one that the files of
the repository give. No network.
"""

import collections
import hashlib
import importlib.util
import inspect
import json
import re
from pathlib import Path

import pytest

from hepph_paper_miner.agent.prompt import ANSWER_TOOL
from hepph_paper_miner.drafting import assemble, assign, checks, draft, review, sift
from hepph_paper_miner.drafting.papers import draw_places, drawing_of, load_archives_plan
from hepph_paper_miner.drafting.places import KINDS, LEAST_CHARS
from hepph_paper_miner.eval import judge, run
from hepph_paper_miner.eval.conditions import CONDITIONS, of_the_code
from hepph_paper_miner.eval.paired import NOT_WORSE, adjusted_wald, reading
from hepph_paper_miner.eval.report import PRICES
from hepph_paper_miner.server import SECTION_CHAR_LIMIT
from hepph_paper_miner.survey.sample import read_sample

ROOT = Path(__file__).resolve().parent.parent
EVAL_DATA = ROOT / "eval_data"
PLAN = EVAL_DATA / "archives_plan.json"
QUESTIONS = EVAL_DATA / "questions_archives.jsonl"
SURVEY_PLAN = EVAL_DATA / "survey_plan.json"
POPULATION = ROOT / "results" / "survey" / "population.jsonl"
SURVEY_SAMPLE = ROOT / "results" / "survey" / "sample.jsonl"
EVAL_RUNS = ROOT / "results" / "runs" / "eval"

TEXT = (EVAL_DATA / "PREREGISTRATION_2.md").read_text(encoding="utf-8")
# The same without its line breaks, so that a sentence is found wherever it is wrapped.
FLAT = " ".join(TEXT.split())

# Do not change these to make a test pass. The plan and Sections 1 to 15 of the
# pre-registration are fixed: another stretch of the order or another count is another
# plan under another name, and what turns out otherwise is written under Deviations.
PLAN_SHA256 = "fdd8388ed4939257bf2d5ace2fd05bbd0874114396a612f0d58dd91655721906"
SECTIONS_SHA256 = "38aee8853f724d78ed438e3b1f8a4560755f70d0b6ff22d1c13965a87737d66e"

# What stands where the digest of the question file is put, in Section 9 and in the
# command of Section 10.
TO_COME = "<SHA-256 of the question file>"
DEVIATIONS = "\n## 16. Deviations\n"

WORDS = {2: "two", 3: "three", 4: "four", 5: "five", 12: "twelve", 16: "sixteen", 60: "sixty"}


def digest_of(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def section(number):
    """The text of one numbered section of the pre-registration."""
    found = re.search(rf"^## {number}\. .*?(?=^## \d+\. |\Z)", TEXT, flags=re.MULTILINE | re.DOTALL)
    return found.group(0)


@pytest.fixture(scope="module")
def plan():
    return load_archives_plan(PLAN)


# --- what is fixed ------------------------------------------------------------------------


def test_the_plan_is_the_file_that_was_committed_before_its_papers_were_fetched():
    assert digest_of(PLAN) == PLAN_SHA256


def test_sections_1_to_15_are_as_they_were_committed():
    assert TEXT.count(DEVIATIONS) == 1
    fixed = TEXT.split(DEVIATIONS)[0]
    assert re.findall(r"^## (\d+)\. ", TEXT, flags=re.MULTILINE) == [str(n) for n in range(1, 17)]
    # The digest of the question file, once it is there, is read as the words it replaced.
    as_committed = re.sub(r"\b[0-9a-f]{64}\b", TO_COME, fixed)
    assert hashlib.sha256(as_committed.encode("utf-8")).hexdigest() == SECTIONS_SHA256


def test_the_question_file_is_named_by_its_digest_once_it_is_there():
    # The commit that adds the file puts its digest where the words stand, in both places.
    named = re.findall(r"\b[0-9a-f]{64}\b", TEXT)
    if QUESTIONS.exists():
        assert named == [digest_of(QUESTIONS)] * 2 and TO_COME not in TEXT
    else:
        assert named == [] and TEXT.count(TO_COME) == 2
        assert f"--questions-sha256 {TO_COME}" in TEXT


# --- the papers ---------------------------------------------------------------------------


def test_the_plan_takes_places_41_to_100_of_four_archives_from_the_list_of_the_survey(plan):
    assert (plan.name, plan.first, plan.last, plan.per_archive) == ("archives-1", 41, 100, 60)
    assert plan.archives == ("hep-ph", "hep-th", "hep-ex", "astro-ph")
    # Refused unless the plan names the survey's plan and its list as they lie on the disk.
    drawing = drawing_of(plan, SURVEY_PLAN, POPULATION)
    drawn = draw_places(drawing.papers, drawing.survey_plan, plan.archives, plan.first, plan.last)
    for archive in plan.archives:
        ranks = sorted(paper.rank for paper in drawn if paper.archive == archive)
        assert ranks == list(range(plan.first, plan.last + 1))
    # None of them is a paper that the survey drew, and so none that the parser was fitted to.
    survey = {paper.arxiv_id for paper in read_sample(SURVEY_SAMPLE).papers}
    assert not survey & {paper.arxiv_id for paper in drawn}
    said = f"places {plan.first} to {plan.last} of the four archives, {len(drawn)} papers"
    assert len(drawn) == 240 and said in FLAT
    assert f"None of the {len(drawn)} had been fetched when this was written" in FLAT
    assert f"(SHA-256 beginning `{plan.population_sha256[:16]}`)" in FLAT
    assert f"`{drawing.survey_plan.seed}:<identifier without its version>`" in FLAT
    assert f"({', '.join(plan.archives)})" in FLAT


# --- the places and the questions ---------------------------------------------------------


def test_a_place_is_given_out_for_every_paper(plan):
    # Five kinds of twelve are the sixty papers of an archive.
    assert assign.PER_KIND * len(KINDS) == plan.per_archive
    of_a_kind, papers = WORDS[assign.PER_KIND], WORDS[plan.per_archive]
    in_all = assign.PER_KIND * len(KINDS) * len(plan.archives)
    said = f"{of_a_kind} places are given out for each kind and archive: {in_all} in all at most"
    assert said in FLAT
    assert f"Where the {papers} papers of an archive do not hold {of_a_kind} places" in FLAT
    # The order in which a paper is given a kind.
    assert "still lacks: " + ", ".join(f"`{kind}`" for kind in KINDS) + "." in FLAT


def test_the_count_of_the_places_is_what_the_share_of_the_last_round_gives():
    accepted, places, kept = 8, 27, 11
    assert f"an accepted draft in {accepted} of its {places} places" in FLAT
    first, now = 120, assign.PER_KIND * len(KINDS) * 4
    assert (
        f"{first} places leave about {round(first * accepted / places)} accepted drafts "
        f"and {now} about {round(now * accepted / places)}"
    ) in FLAT
    # The counts of that round, as Section 8 gives them, add up.
    assert f"It had {places} places on 11 papers: in 14 " in FLAT and 14 + 2 + kept == places
    assert f"The maintainer accepted {accepted} of the {kept}." in FLAT
    assert accepted / kept >= 2 / 3


def test_four_questions_of_a_kind_and_archive_and_80_in_all_at_most(plan):
    cell = assemble.PER_CELL
    of_a_kind = cell * len(plan.archives)
    in_all = of_a_kind * len(KINDS)
    assert (
        f"{WORDS[cell]} questions of each kind from each archive, {WORDS[of_a_kind]} of a kind "
        f"and {in_all} in all, each about a paper of its own"
    ) in FLAT
    # A kind that falls short is filled from named_first, so only the sum has a bound.
    assert f"where a kind and archive has fewer than {WORDS[cell]}, further questions" in FLAT
    assert f"Where a kind and archive has fewer than {WORDS[cell]} accepted drafts" in FLAT
    assert f"the first {WORDS[cell]} accepted drafts in the order of the walk" in FLAT
    assert f"named `archives-01`, `archives-02` and so on: {in_all} at most" in FLAT
    assert f"each run once: {2 * in_all} cells at most" in FLAT
    assert f"Here up to {2 * in_all} answers follow the review" in FLAT
    rehearsal = WORDS[assemble.REHEARSAL_PER_KIND]
    assert f"with {rehearsal} of a kind where it says {WORDS[cell]}" in FLAT


def test_the_numbers_of_the_places_the_drafts_and_the_checks_are_those_of_the_code():
    assert f"which is at most {SECTION_CHAR_LIMIT:,} characters" in FLAT
    assert f"a part of fewer than {LEAST_CHARS:,} characters" in FLAT
    assert f"up to {WORDS[draft.MAX_DRAFTS]} drafts for each place" in FLAT
    assert f"the first {WORDS[draft.MAX_DRAFTS]} drafts of a reply are read" in FLAT
    assert checks.QUESTION_CHARS == checks.ANSWER_CHARS
    low, high = checks.ANCHOR_CHARS
    assert f"at most {checks.QUESTION_CHARS} characters each, the anchor {low} to {high}" in FLAT
    assert f"with {WORDS[checks.LEAST_DIGITS]} or more significant digits" in FLAT
    # The checks are numbered as the code holds them, one line of the list for each.
    numbered = re.findall(r"^(\d+)\. ", section(5), flags=re.MULTILINE)
    assert numbered == [str(n) for n in range(1, len(checks.CHECKS) + 1)]
    assert f"A rejection names one of {WORDS[len(review.REASONS)]} kinds" in FLAT
    for reason in review.REASONS:
        assert f"(`{reason}`)" in FLAT
    assert f"{WORDS[judge.REPEATS]} requests for every answer" in FLAT


# --- the texts, the conditions and the prices ---------------------------------------------


def test_the_texts_are_named_by_their_digests():
    drafter = f"name `{draft.DRAFTER_VERSION}` (SHA-256 beginning `{draft.texts_digest()[:16]}`)"
    sifter = f"name `{sift.SIFT_VERSION}` (SHA-256 beginning `{sift.texts_digest()[:16]}`)"
    grader = f"`{judge.JUDGE_VERSION}` (texts SHA-256 beginning `{judge.texts_digest()[:16]}`)"
    assert drafter in FLAT and sifter in FLAT and f"The judge {grader}" in FLAT


def test_the_models_that_draft_and_sift_are_set_as_the_text_says():
    settings = draft.DRAFTING
    assert (
        f"The model is `{settings['model']}` with `max_tokens` {settings['max_tokens']}, "
        f"adaptive thinking and effort `{settings['effort']}`, without a cache"
    ) in FLAT
    # "The summary of its thinking is returned", and for the filters it is not.
    assert settings["thinking"] == {"type": "adaptive", "display": "summarized"}
    assert sift.SIFTING == {**settings, "thinking": {"type": "adaptive"}}
    assert "cache_control" not in settings


def test_the_runs_are_made_under_the_conditions_that_the_code_has():
    name = of_the_code()
    held = CONDITIONS[name]
    texts, model, limits = held["toolset_version"], held["model"], held["limits"]
    assert f"under the conditions `{name}` of" in FLAT
    assert (
        f"tool texts `{texts['staged']}` and `{texts['flat']}`, prompt "
        f"`{held['prompt_version']}`, parser `{held['parser']}`, model `{model['model']}` with "
        f"`max_tokens` {model['max_tokens']}, adaptive thinking, effort `{model['effort']}`, "
        f"prompt cache `{model['cache_control']['type']}` and {model['max_retries']} retries of "
        f"{model['request_seconds']:.0f} s; at most {limits['max_turns']} responses, "
        f"{limits['tool_seconds']:.0f} s per tool call and {limits['run_seconds']:.0f} s per run"
    ) in FLAT
    assert model["thinking"] == {"type": "adaptive"}


def test_the_prices_are_those_the_report_works_the_cost_out_with():
    price = PRICES[CONDITIONS[of_the_code()]["model"]["model"]]
    assert (
        f"USD {price['input']:g} of input, {price['cache_write_5m']:.2f} written to the cache, "
        f"{price['cache_read']:.2f} read from it, {price['output']:g} of output"
    ) in FLAT


def test_the_command_of_the_runs_is_one_that_the_runner_takes():
    command = re.search(r"^uv run python -m (\S+) (.+)$", section(10), flags=re.MULTILINE)
    module, arguments = command.groups()
    assert module == run.__name__
    options = re.findall(r"--[a-z0-9-]+", arguments)
    assert options == ["--questions", "--out", "--repeats", "--questions-sha256"]
    source = inspect.getsource(run)
    for option in options:
        assert f'"{option}"' in source
    assert f"--questions {QUESTIONS.relative_to(ROOT).as_posix()} --out " in arguments
    # One run for a cell, where the runner makes three unless it is told.
    assert "--repeats 1 " in arguments and run.REPEATS == 3


def test_a_cell_is_run_three_times_at_most_and_then_given_up():
    # The first run of a cell and at most two more (eval/run.py): with one run for a cell,
    # a cell that is given up leaves its question without a pair.
    assert run.TRIES == 3
    said = "run again after the pass, at most twice; a cell that is spoilt three times is given up"
    assert said in FLAT
    assert "it is left out of H1 and H2, and the report names it" in FLAT


def test_what_the_text_names_of_the_code_is_there():
    package = ROOT / "src" / "hepph_paper_miner"
    files = set(re.findall(r"`((?:eval|drafting|survey)/[a-z_]+\.py)`", TEXT))
    assert {"drafting/checks.py", "eval/grade.py", "eval/paired.py", "eval/report.py"} <= files
    for name in files:
        assert (package / name).is_file(), name
    assert (ROOT / "src/hepph_paper_miner/eval/conditions.py").is_file()
    assert "`src/hepph_paper_miner/eval/conditions.py`" in TEXT
    modules = set(re.findall(r"`((?:eval|drafting|survey)\.[a-z_]+)`", TEXT))
    assert {"drafting.papers", "survey.run", "drafting.draft", "drafting.sift"} <= modules
    assert {"drafting.assemble", "eval.sheet", "eval.grade"} <= modules
    for name in modules:
        assert importlib.util.find_spec(f"hepph_paper_miner.{name}") is not None, name


# --- what the text says of the first evaluation, and of what fewer questions show ---------


def test_the_three_runs_of_a_cell_of_the_first_evaluation_called_the_tools_alike_in_26_of_40():
    calls = collections.defaultdict(list)
    for path in sorted(EVAL_RUNS.glob("*.jsonl")):
        lines = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
        # The call that hands in the answer is the loop's own, and no two answers are alike.
        made = [
            (tool["name"], json.dumps(tool["arguments"], sort_keys=True))
            for line in lines
            if line["record"] == "turn"
            for tool in line.get("tools") or []
            if tool["name"] != ANSWER_TOOL["name"]
        ]
        calls[lines[0]["question_id"], lines[0]["toolset"]].append(made)
    assert {len(runs) for runs in calls.values()} == {3}
    alike = sum(1 for runs in calls.values() if all(run == runs[0] for run in runs))
    assert (alike, len(calls)) == (26, 40)
    assert f"argument for argument, in {alike} of the {len(calls)} cells" in FLAT


def most_that_may_differ(questions):
    """The most questions on which the layouts may differ, half of them each way, for the
    interval to say "not worse by more than 10 points"; None when no such table says it."""
    found = [
        differing
        for differing in range(0, questions + 1, 2)
        if reading(*adjusted_wald(differing // 2, differing // 2, questions)[1:], 0.10) == NOT_WORSE
    ]
    return max(found) if found else None


def test_what_fewer_questions_can_show_is_what_the_interval_gives():
    counts = (80, 70, 60, 50, 40, 30)
    assert "| questions | " + " | ".join(str(n) for n in counts) + " |" in TEXT
    most = " | ".join(str(most_that_may_differ(n)) for n in counts)
    assert f"| of them differ, at most | {most} |" in TEXT
    least = min(n for n in range(1, 81) if most_that_may_differ(n) is not None)
    assert f"With fewer than {least} questions not even a table" in FLAT
    assert "with 80 questions or fewer no table makes them both hold" in FLAT
