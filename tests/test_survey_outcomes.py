"""What came back for the papers of the survey, and what the READMEs say of it.

results/survey/outcomes.jsonl is the file the survey wrote on 2026-11-25 (UTC), in the
run after which no paper was left unanswered. It took three runs: outcomes-first-run.jsonl
and outcomes-second-run.jsonl are the files of the two before, of 2026-11-24, which left
67 papers and 3 papers. These tests hold the three files against the sample, against the plan and
against each other, and hold up what the README of the repository and the README of the
folder say of them: the table of the archives, the kinds, the two shapes, how the runs
went and the weighted share.

From here on the outcomes are fixed (CLAUDE.md, "The survey"). The check of the outlines
names the file by its SHA-256, and the survey command would write it anew.

No network and no LLM. The files hold identifiers, categories, counts and the sentences
of the parser, and nothing of the text of a paper; one of the tests says so.
"""

from collections import Counter
from datetime import datetime, timedelta
from functools import cache
from pathlib import Path

from hepph_paper_miner.agent.origin import file_digest
from hepph_paper_miner.server import SECTION_CHAR_LIMIT
from hepph_paper_miner.survey.plan import load_plan
from hepph_paper_miner.survey.run import OK, OUTCOMES, UNANSWERED, branch, read_outcomes, tally
from hepph_paper_miner.survey.sample import read_sample

ROOT = Path(__file__).parent.parent
PLAN = ROOT / "eval_data" / "survey_plan.json"
HERE = ROOT / "results" / "survey"
SAMPLE = HERE / "sample.jsonl"
FIRST_RUN, SECOND_RUN = HERE / "outcomes-first-run.jsonl", HERE / "outcomes-second-run.jsonl"
LAST_RUN = HERE / "outcomes.jsonl"
RUNS = (FIRST_RUN, SECOND_RUN, LAST_RUN)

# The commit that brought the sample. All three runs were made from it, and the files name
# it in full.
RAN = "ceea850"
# The version of the parser that split the papers. It stays the version of these outcomes
# when the parser of the code moves on.
PARSER = "4"

# The three files as the command wrote them on the maintainer's computer.
SHA256 = {
    FIRST_RUN: "4bb7ecc3f580629ed82be735bfe59701b412a1afb12cf30b8986cdc2370bbc8b",
    SECOND_RUN: "f98c650da5f1311da898c8248bea94b056510a0753f82439efc431071dd79c8c",
    LAST_RUN: "95b8db1bf379ac688b6e825a221480c1914a1558f1494b0b28cc9d7527783b13",
}

NO_TEX = "no_full_text"
# What a line holds, by how the paper came back. No name leaves room for a title.
PAPER = {"record", "archive", "rank", "id", "primary", "outcome"}
KEYS = {
    OK: PAPER | {"sections", "subsections", "chars", "largest", "no_headings"},
    NO_TEX: PAPER | {"branch", "detail"},
    UNANSWERED: PAPER | {"kind", "detail"},
}
# The two things the source says of a paper without a TeX source: its own sentence, or
# nothing (arXiv has nothing to download).
SENTENCES = {"not_tex": "the source is a PDF, PostScript or DVI file", "no_source": ""}
# The days of the runs: the first two, and the third.
DAYS = ("2026-11-24", "2026-11-24", "2026-11-25")


@cache
def outcomes(path: Path = LAST_RUN):
    """The first line of an outcomes file and its paper lines."""
    return read_outcomes(path)


def left_by(path: Path) -> list:
    """The papers a run left unanswered."""
    return [line for line in outcomes(path)[1] if line["outcome"] == UNANSWERED]


def times_of(path: Path) -> tuple[datetime, datetime]:
    head = outcomes(path)[0]
    return datetime.fromisoformat(head["began"]), datetime.fromisoformat(head["ended"])


def minutes(path: Path) -> int:
    began, ended = times_of(path)
    return round((ended - began).total_seconds() / 60)


def flat(path: Path) -> str:
    """A README with every run of white space as one blank, as a sentence is looked for."""
    return " ".join(path.read_text(encoding="utf-8").split())


def weighted_share():
    """The share that was split with each archive weighted by its papers in the list.

    And the standard error of that share: the archives are drawn apart, each without
    putting a paper back, so the variances of their shares add up with the squares of
    the weights, each with the correction for an archive that is not endless.
    """
    sample, (_, papers) = read_sample(SAMPLE), outcomes()
    size = {archive: count["primary"] for archive, count in sample.counts.items()}
    listed = sum(size.values())
    share = variance = 0.0
    for archive, in_the_list in size.items():
        own = [line for line in papers if line["archive"] == archive]
        drawn = len(own)
        split = sum(1 for line in own if line["outcome"] == OK) / drawn
        weight = in_the_list / listed
        share += weight * split
        variance += weight**2 * (1 - drawn / in_the_list) * split * (1 - split) / (drawn - 1)
    return share, variance**0.5


def test_the_three_files_are_the_bytes_that_were_written():
    # Also on Windows: the check of the outlines names the outcomes by this hash.
    for path in RUNS:
        assert file_digest(path) == SHA256[path]


def test_every_file_names_the_sample_the_plan_and_the_commit_it_was_made_from():
    sample = read_sample(SAMPLE)
    heads = [outcomes(path)[0] for path in RUNS]

    for head in heads:
        assert set(head) == {
            "record",
            "sample",
            "plan",
            "code",
            "parser_version",
            "section_char_limit",
            "began",
            "ended",
            "papers",
            "unanswered",
        }
        assert head["sample"] == {"file": SAMPLE.name, "sha256": sample.sha256}
        assert head["plan"] == sample.head["plan"]
        # No file the repository keeps was changed, so the commit names the code.
        assert head["code"]["commit"].startswith(RAN) and head["code"]["modified"] is False
        assert head["parser_version"] == PARSER
        assert head["section_char_limit"] == 20_000
    assert heads[0]["code"] == heads[1]["code"] == heads[2]["code"]
    # The limit of a call is still the one the pieces were held against.
    assert SECTION_CHAR_LIMIT == 20_000

    # One run after the other, each on the day the READMEs name for it.
    times = [moment for path in RUNS for moment in times_of(path)]
    assert times == sorted(times) and len(set(times)) == 6
    assert {moment.utcoffset() for moment in times} == {timedelta(0)}
    for path, day in zip(RUNS, DAYS, strict=True):
        assert {f"{moment:%Y-%m-%d}" for moment in times_of(path)} == {day}


def test_each_file_has_a_line_for_every_paper_of_the_sample_in_its_order():
    sample = read_sample(SAMPLE)
    drawn = [(paper.archive, paper.rank, paper.arxiv_id, paper.primary) for paper in sample.papers]

    for path in RUNS:
        head, papers = outcomes(path)
        assert [(p["archive"], p["rank"], p["id"], p["primary"]) for p in papers] == drawn
        left = len(left_by(path))
        assert (head["papers"], head["unanswered"]) == (len(papers), left) == (len(drawn), left)
    assert len(drawn) == 520


def test_the_files_hold_nothing_of_the_text_of_a_paper():
    for path in RUNS:
        for line in outcomes(path)[1]:
            assert set(line) == KEYS[line["outcome"]]
            if line["outcome"] == OK:
                counts = [line[name] for name in ("sections", "subsections", "chars", "largest")]
                assert all(type(count) is int for count in counts)
                assert type(line["no_headings"]) is bool
            elif line["outcome"] == NO_TEX:
                # A sentence of the source, word for word, and none of a paper.
                assert line["detail"] == SENTENCES[line["branch"]]
                assert branch(NO_TEX, line["detail"]) == line["branch"]
            else:
                assert line["kind"] in ("upstream_busy", "timeout") and line["detail"] == ""


def test_no_paper_is_left_unanswered_and_none_came_back_in_a_third_way():
    head, papers = outcomes()
    found = tally(papers)

    assert head["unanswered"] == found.unanswered == 0
    # The READMEs have a sentence for these two outcomes and say that there is no other.
    assert {name for name in OUTCOMES if found.count(name)} == {OK, NO_TEX}
    assert found.count(OK) + found.count(NO_TEX) == found.papers == 520
    assert sum(found.branches[NO_TEX].values()) == found.count(NO_TEX)
    assert set(found.branches) == {NO_TEX}


def test_the_counts_of_a_paper_that_was_split_fit_together():
    _, papers = outcomes()
    split = [line for line in papers if line["outcome"] == OK]

    for line in split:
        assert line["sections"] >= 1 and line["subsections"] >= 0
        assert 0 < line["largest"] <= line["chars"]
        if line["no_headings"]:
            # One piece, and it is the whole paper.
            assert (line["sections"], line["subsections"]) == (1, 0)
            assert line["largest"] == line["chars"]
    found = tally(papers)
    assert found.no_headings == sum(1 for line in split if line["no_headings"])
    assert found.over_limit == sum(1 for line in split if line["largest"] > 20_000)


def test_the_first_run_left_67_papers_unanswered_in_two_stretches_of_the_walk():
    plan = load_plan(PLAN)
    left = left_by(FIRST_RUN)

    assert len(left) == 67
    assert Counter(line["kind"] for line in left) == {"upstream_busy": 63, "timeout": 4}
    # The walk takes the first paper of every archive, then the second: a stretch of it
    # is a few ranks, in every archive.
    assert sorted({line["rank"] for line in left}) == [5, 6, 7, 8, 9, 18, 19, 20]
    lost = Counter(line["archive"] for line in left)
    assert set(lost) == set(plan.archives) and max(lost.values()) == 6
    # The other papers had come back as they did in the end: in the two ways, no third.
    assert {line["outcome"] for line in outcomes(FIRST_RUN)[1]} == {OK, NO_TEX, UNANSWERED}


def test_the_second_run_left_the_first_three_of_them_in_the_order_of_the_walk():
    plan = load_plan(PLAN)
    archives = list(plan.archives)
    first, second = left_by(FIRST_RUN), left_by(SECOND_RUN)

    def place(line):
        return line["rank"], archives.index(line["archive"])

    assert [line["id"] for line in second] == [line["id"] for line in sorted(first, key=place)[:3]]
    assert [(line["archive"], line["rank"]) for line in second] == [(a, 5) for a in archives[:3]]
    assert {line["kind"] for line in second} == {"timeout"}
    assert {line["outcome"] for line in outcomes(SECOND_RUN)[1]} == {OK, NO_TEX, UNANSWERED}


def test_asking_again_changed_no_line_that_had_an_outcome():
    filled = []
    for at, path in enumerate(RUNS[:-1]):
        had = [line for line in outcomes(path)[1] if line["outcome"] != UNANSWERED]
        filled.append(len(had))
        for later in RUNS[at + 1 :]:
            now = {line["id"]: line for line in outcomes(later)[1]}
            assert all(now[line["id"]] == line for line in had)

    assert filled == [453, 517]


def test_what_the_readme_says_of_the_outcomes_is_what_the_files_say():
    plan, sample = load_plan(PLAN), read_sample(SAMPLE)
    head, papers = outcomes()
    found = tally(papers)
    readme = flat(ROOT / "README.md")

    # Where the survey stands. The check of the outlines comes in a later commit, and
    # then these sentences have to go.
    checked = (HERE / "outline-check.jsonl").exists()
    outlines = len(plan.archives) * plan.outline_per_archive
    assert (
        f"the {found.papers} papers have been fetched and counted, the {outlines} outlines "
        "have not been held against the papers yet" in readme
    ) == (not checked)
    assert (
        "**It has been run, and its outlines have not been checked by hand yet.**" in readme
    ) == (not checked)
    assert "It has not been run" not in readme and "has not been run yet" not in readme

    # The three runs.
    (began_1, ended_1), (began_2, ended_2), (began, ended) = (times_of(path) for path in RUNS)
    first, second = left_by(FIRST_RUN), left_by(SECOND_RUN)
    kinds = Counter(line["kind"] for line in first)
    assert (
        f"The command was run three times by `{RAN}`, the commit that brought the sample: "
        f"twice on {DAYS[0]} and once on {DAYS[2]} (UTC)." in readme
    )
    assert (
        f"The first run, from {began_1:%H:%M} to {ended_1:%H:%M} UTC, left {len(first)} of the "
        f"{found.papers} papers unanswered (`upstream_busy` {kinds['upstream_busy']}, "
        f"`timeout` {kinds['timeout']})." in readme
    )
    assert (
        f"The second, from {began_2:%H:%M} to {ended_2:%H:%M} UTC, got an outcome for "
        f"{len(first) - len(second)} of them and left {len(second)} (`timeout`)." in readme
    )
    assert (
        f"The third, from {began:%H:%M} to {ended:%H:%M} UTC the next day, got an outcome for "
        f"those {len(second)}, so no paper is left unanswered." in readme
    )
    assert (began.date() - began_2.date()).days == 1
    assert "A line that a run had filled is the same line in the file of every run after" in readme

    # The table: every archive of the plan in its order, and the sample as a whole.
    assert "| Archive | Papers | Split into sections | No TeX source |" in readme
    assert list(found.by_archive) == list(plan.archives)
    for archive, counts in found.by_archive.items():
        assert sum(counts.values()) == plan.per_archive
        assert f"| {archive} | {plan.per_archive} | {counts[OK]} | {counts[NO_TEX]} |" in readme
    assert f"| all | {found.papers} | {found.count(OK)} | {found.count(NO_TEX)} |" in readme

    # The outcomes nobody came back with, and the kinds of the one that failed.
    for absent in ("parse_error", "not_found", "unexpected"):
        assert found.count(absent) == 0
    assert (
        "No paper was turned away by the parser (`parse_error`), none was missing from arXiv "
        "(`not_found`), and none came back in a way nobody foresaw (`unexpected`)." in readme
    )
    said = found.branches[NO_TEX]
    assert set(said) == {"not_tex", "no_source"}
    assert (
        f"Of the {found.count(NO_TEX)} papers without a TeX source, arXiv has {said['not_tex']} "
        "as a PDF, PostScript or DVI file (`not_tex`) and nothing to download for "
        f"{said['no_source']} (`no_source`)." in readme
    )

    # The two shapes.
    split = [line for line in papers if line["outcome"] == OK]
    both = sum(1 for line in split if line["no_headings"] and line["largest"] > 20_000)
    assert (
        f"Of the {len(split)} papers that were split, {found.no_headings} have no section "
        f"heading and come back as one piece, and {found.over_limit} have a piece of more than "
        "20,000 characters, which takes more than one call of `read_section`; "
        f"{both} papers are both." in readme
    )

    # How far the numbers go. Forty of forty: what a share of 93% gives one time in twenty.
    assert "an archive of which 93% can be gives forty of forty about one time in twenty" in readme
    assert plan.per_archive == 40 and 1 / 25 < 0.93**plan.per_archive < 1 / 15
    size = {archive: sample.counts[archive]["primary"] for archive in plan.archives}
    assert f"(forty papers of {min(size.values()):,} and forty of {max(size.values()):,})" in readme
    share, error = weighted_share()
    plain = found.count(OK) / found.papers
    assert (
        f"the share that was split is {share:.0%}, with a standard error of about "
        f"{100 * error:.0f} points; unweighted it is {plain:.0%} ({found.count(OK)} of "
        f"{found.papers})" in readme
    )
    # The weights are the list's, and the list was committed before the survey was run.
    assert sum(size.values()) == sample.head["population"]["papers"]
    assert head["papers"] == found.papers
    # When the owner said so is in no file: between the second run and the third. How
    # many papers had an outcome by then is in the file of the second run.
    assert (
        "That a weighted share is given was decided after the second run, when the outcomes "
        f"of {found.papers - len(second)} papers had been seen." in readme
    )


def test_what_the_readme_of_the_folder_says_is_what_the_files_say():
    plan, sample = load_plan(PLAN), read_sample(SAMPLE)
    head, papers = outcomes()
    found = tally(papers)
    readme = flat(HERE / "README.md")
    listed = sample.head["population"]["papers"]
    archives = list(plan.archives)

    # What the files are.
    assert f"the {listed:,} papers that arXiv listed for the plan on 2026-11-23 UTC" in readme
    assert (
        f"the {found.papers} papers that the rule of the plan draws from that list, "
        f"{plan.per_archive} of each of the {len(archives)} archives" in readme
    )
    (began_1, ended_1), (began_2, ended_2), (began, ended) = (times_of(path) for path in RUNS)
    first, second = left_by(FIRST_RUN), left_by(SECOND_RUN)
    assert f"the file that the third run of `survey.run` wrote on {DAYS[2]}" in readme
    assert (
        f"the files that the two runs before it wrote, with {len(first)} papers and with "
        f"{len(second)} papers unanswered" in readme
    )

    # How the runs went.
    assert (
        f"All three were made on the maintainer's computer by `{RAN}`, the commit that brought "
        f"the sample, with no file of the repository changed, and with version "
        f"{head['parser_version']} of the parser." in readme
    )
    assert (
        f"The first run began at {began_1:%H:%M} UTC on {DAYS[0]} and ended at {ended_1:%H:%M}, "
        f"{minutes(FIRST_RUN)} minutes later." in readme
    )
    kinds = Counter(line["kind"] for line in first)
    assert (
        f"For {len(first)} papers arXiv gave no answer that could be used: "
        f"{kinds['upstream_busy']} came back as `upstream_busy` and {kinds['timeout']} as "
        "`timeout`." in readme
    )
    assert sorted({line["rank"] for line in first}) == [5, 6, 7, 8, 9, 18, 19, 20]
    assert f"these {len(first)} are papers 5 to 9 and 18 to 20 of their archives" in readme
    most = max(Counter(line["archive"] for line in first).values())
    assert f"no archive lost more than {most} of its {plan.per_archive} papers" in readme

    after_second = {line["id"]: line for line in outcomes(SECOND_RUN)[1]}
    came = Counter(after_second[line["id"]]["outcome"] for line in first)
    assert (
        f"The second run began at {began_2:%H:%M} UTC and ended at {ended_2:%H:%M}, "
        f"{minutes(SECOND_RUN)} minutes later. Of the {len(first)}, "
        f"{len(first) - len(second)} came back with an outcome: {came[OK]} were split and "
        f"{came[NO_TEX]} have no TeX source." in readme
    )
    assert came[UNANSWERED] == len(second) == 3
    assert (
        f"The {len(second)} that did not are the first {len(second)} of the {len(first)} in "
        f"the order of the walk, paper 5 of {archives[0]}, of {archives[1]} and of "
        f"{archives[2]}, each as `timeout`." in readme
    )
    now = {line["id"]: line for line in papers}
    came = Counter(now[line["id"]]["outcome"] for line in second)
    assert (
        f"The third run began at {began:%H:%M} UTC on {DAYS[2]} and ended within a minute. The "
        f"{len(second)} came back with an outcome: {came[OK]} were split and {came[NO_TEX]} has "
        "no TeX source." in readme
    )
    assert (came[OK], came[NO_TEX]) == (2, 1)
    assert ended - began < timedelta(minutes=1)
    assert (
        f"the {found.papers - len(first)} lines that the first run filled are the same in all "
        f"three files, and the {found.papers - len(second)} of the second are the same in the "
        "third" in readme
    )

    # The two shapes, archive by archive.
    split = [line for line in papers if line["outcome"] == OK]
    for archive in archives:
        own = [line for line in split if line["archive"] == archive]
        bare = sum(1 for line in own if line["no_headings"])
        large = sum(1 for line in own if line["largest"] > 20_000)
        assert f"| {archive} | {len(own)} | {bare} | {large} |" in readme
    assert f"| all | {len(split)} | {found.no_headings} | {found.over_limit} |" in readme

    # The weighted share, to one more digit than the README of the repository gives.
    size = {archive: sample.counts[archive]["primary"] for archive in archives}
    small, large = min(size, key=size.get), max(size, key=size.get)
    assert (
        f"{plan.per_archive} of the {size[small]:,} papers of {small}, and {plan.per_archive} "
        f"of the {size[large]:,} of {large}" in readme
    )
    share, error = weighted_share()
    assert f"So a share for the {listed:,} papers of the list is worked out" in readme
    assert (
        f"That gives {share:.1%}, where the unweighted count gives "
        f"{found.count(OK) / found.papers:.1%}." in readme
    )
    assert f"Its standard error is {100 * error:.1f} points." in readme
    assert "w² (1 − n/N) p (1 − p) / (n − 1)" in readme
    # "Somewhat too small": an archive whose papers were all split adds no variance.
    assert any(counts[OK] == plan.per_archive for counts in found.by_archive.values())

    # The README of all results points here.
    assert (
        f"what came back for its {found.papers} papers on {DAYS[0]} and {DAYS[2]}, with a "
        "README of their own" in flat(ROOT / "results" / "README.md")
    )
