"""The sample of the survey, split again by parser 5: the file, and what is said of it.

results/survey/outcomes.jsonl is what came back for the 520 papers of the sample with
parser 4. It is the result of the survey, and the check of the outlines is of it
(tests/test_survey_outcomes.py, tests/test_survey_checks.py). The parser was changed
afterwards. results/survey/outcomes-parser5.jsonl is what one run of the same command
wrote for the same papers on 2026-11-25 (UTC), by the code that has parser 5.

What would be read from the two files, line against line, was written down before that
run, in the plan of results/runs/more-sections/README.md. These tests hold the new file
against the sample and against the outcomes of parser 4, apply that reading, and hold
up what the READMEs say of the two files.

From here on the new file is fixed as well (CLAUDE.md, "The survey"): the survey command
would write it anew, with other times in its first line.

No network and no LLM. The file holds identifiers, categories, counts and the sentences
of the parser, and nothing of the text of a paper; one of the tests says so.
"""

from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path

from test_section_questions import LEFT_OUT, PAPERS
from test_survey_outcomes import KEYS, NO_TEX, SENTENCES

from hepph_paper_miner.agent.origin import file_digest
from hepph_paper_miner.survey.plan import load_plan
from hepph_paper_miner.survey.run import OK, branch, read_outcomes, tally
from hepph_paper_miner.survey.sample import read_sample

ROOT = Path(__file__).parent.parent
HERE = ROOT / "results" / "survey"
SAMPLE = HERE / "sample.jsonl"
OF_4, OF_5 = HERE / "outcomes.jsonl", HERE / "outcomes-parser5.jsonl"
PLAN = ROOT / "eval_data" / "survey_plan.json"
WRITTEN_UP = ROOT / "results" / "runs" / "more-sections" / "README.md"

# The file as the command wrote it on the maintainer's computer.
SHA256 = "4443c1ae83eae0d934bc292e45d2a5f1c1e6251d207c4a4c909f682ce2934dff"
# The commit that made it: the one that brought the plan of these runs, with parser 5.
RAN = "44bca1f"
# What a line of a paper that was split says of it. The plan: papers whose line differs
# "in the number of sections or subsections, in the characters, in the largest piece or in
# having no section heading".
SHAPE = ("sections", "subsections", "chars", "largest", "no_headings")
LIMIT = 20_000


def lines_of(path: Path) -> list[dict]:
    return read_outcomes(path)[1]


def pairs() -> list[tuple[dict, dict]]:
    """The line of each paper in the file of parser 4 and in that of parser 5."""
    return list(zip(lines_of(OF_4), lines_of(OF_5), strict=True))


def split_by_both() -> list[tuple[dict, dict]]:
    return [(old, new) for old, new in pairs() if old["outcome"] == new["outcome"] == OK]


def flat(path: Path) -> str:
    """A README with every run of white space as one blank, as a sentence is looked for."""
    return " ".join(path.read_text(encoding="utf-8").split())


def test_the_file_is_the_bytes_that_were_written():
    assert file_digest(OF_5) == SHA256


def test_it_names_the_sample_and_the_plan_of_the_survey_and_the_code_with_parser_5():
    old, new = read_outcomes(OF_4)[0], read_outcomes(OF_5)[0]
    assert set(new) == set(old)
    for name in ("record", "sample", "plan", "section_char_limit", "papers", "unanswered"):
        assert new[name] == old[name], name
    assert new["sample"] == {"file": SAMPLE.name, "sha256": read_sample(SAMPLE).sha256}
    assert (new["papers"], new["unanswered"], new["section_char_limit"]) == (520, 0, LIMIT)
    assert (old["parser_version"], new["parser_version"]) == ("4", "5")
    # No file the repository keeps was changed, so the commit names the code.
    assert new["code"]["commit"].startswith(RAN) and new["code"]["modified"] is False
    began, ended = (datetime.fromisoformat(new[name]) for name in ("began", "ended"))
    assert (f"{began:%Y-%m-%d %H:%M}", f"{ended:%H:%M}") == ("2026-11-25 10:46", "10:47")
    assert ended - began == timedelta(seconds=19)
    assert began > datetime.fromisoformat(old["ended"])


def test_it_has_a_line_for_every_paper_of_the_sample_in_its_order_and_no_text_of_a_paper():
    drawn = [(p.archive, p.rank, p.arxiv_id, p.primary) for p in read_sample(SAMPLE).papers]
    lines = lines_of(OF_5)
    assert [(x["archive"], x["rank"], x["id"], x["primary"]) for x in lines] == drawn
    assert len(drawn) == 520
    for line in lines:
        assert set(line) == KEYS[line["outcome"]]
        if line["outcome"] == OK:
            assert all(type(line[name]) is int for name in SHAPE[:4])
            assert type(line["no_headings"]) is bool
            assert line["sections"] >= 1 and 0 < line["largest"] <= line["chars"]
        else:
            # A sentence of the source, word for word, and none of a paper.
            assert line["outcome"] == NO_TEX and line["detail"] == SENTENCES[line["branch"]]
            assert branch(NO_TEX, line["detail"]) == line["branch"]


def test_parser_5_split_every_paper_that_parser_4_split_and_191_lines_differ():
    # The reading that was fixed before the run, point by point.
    both = pairs()
    assert [new["id"] for old, new in both if old["outcome"] == OK != new["outcome"]] == []
    assert Counter(new["outcome"] for _, new in both) == {OK: 494, NO_TEX: 26}
    # The papers without a TeX source have the line they had.
    assert all(old == new for old, new in both if old["outcome"] != OK)

    split = split_by_both()
    differ = [(old, new) for old, new in split if old != new]
    assert (len(split), len(differ)) == (494, 191)
    in_field = {name: sum(1 for old, new in differ if old[name] != new[name]) for name in SHAPE}
    assert in_field == {
        "sections": 191,
        "subsections": 0,
        "chars": 191,
        "largest": 39,
        "no_headings": 17,
    }
    # A line that differs does so in what it says of the split, and in nothing else.
    assert all(
        {name: old[name] for name in old if name not in SHAPE}
        == {name: new[name] for name in new if name not in SHAPE}
        for old, new in differ
    )


def test_the_two_shapes_beside_the_26_and_the_125_of_parser_4():
    old, new = tally(lines_of(OF_4)), tally(lines_of(OF_5))
    assert (old.no_headings, new.no_headings) == (26, 9)
    assert (old.over_limit, new.over_limit) == (125, 108)
    split = split_by_both()

    def both_shapes(line: dict) -> bool:
        return line["no_headings"] and line["largest"] > LIMIT

    assert [sum(both_shapes(pair[n]) for pair in split) for n in (0, 1)] == [22, 7]

    # The 17 that left the first count. No paper came into it.
    left = [(o, n) for o, n in split if o["no_headings"] and not n["no_headings"]]
    assert not [1 for o, n in split if n["no_headings"] and not o["no_headings"]]
    now = Counter(n["sections"] for _, n in left)
    assert len(left) == 17 and now[2] == 4
    assert sorted(count for count in now if count != 2) == [6, 7, 8, 9, 12, 14]
    assert sum(papers for count, papers in now.items() if count != 2) == 13
    # The four with two sections: the larger of the two is nearly what the one was.
    two = [(o, n) for o, n in left if n["sections"] == 2]
    assert all(o["largest"] == o["chars"] > n["largest"] > LIMIT for o, n in two)
    assert sorted(o["largest"] - n["largest"] for o, n in two) == [334, 742, 782, 787]

    # The second count: 18 left it, and one came into it.
    left = [o["id"] for o, n in split if o["largest"] > LIMIT >= n["largest"]]
    came = [
        (n["id"], o["largest"], n["largest"])
        for o, n in split
        if o["largest"] <= LIMIT < n["largest"]
    ]
    assert len(left) == 18 and 125 - 18 + 1 == 108
    paper, before_chars = PAPERS[LEFT_OUT]
    assert came == [(paper, 7_721, 24_532)]
    # It is the paper whose letter parser 4 left out: the letter is the piece.
    (old_line, new_line) = next((o, n) for o, n in split if o["id"] == paper)
    assert (old_line["chars"], new_line["chars"]) == (before_chars, 58_526)
    assert new_line["archive"] == "hep-ex"


def test_no_paper_has_fewer_sections_and_one_has_more_characters():
    differ = [(old, new) for old, new in split_by_both() if old != new]
    more = Counter(new["sections"] - old["sections"] for old, new in differ)
    assert min(more) == 1 and max(more) == 13 and more[1] == 167
    assert sum(papers for gain, papers in more.items() if gain > 1) == 24
    split = split_by_both()
    assert [sum(pair[n]["sections"] for pair in split) for n in (0, 1)] == [3_980, 4_300]
    assert [sum(pair[n]["subsections"] for pair in split) for n in (0, 1)] == [4_135, 4_135]
    # The characters: more in the paper whose letter came back, fewer in every other.
    gained = [
        (new["id"], new["chars"] - old["chars"])
        for old, new in differ
        if new["chars"] > old["chars"]
    ]
    assert gained == [(PAPERS[LEFT_OUT][0], 27_275)]
    lost = [old["chars"] - new["chars"] for old, new in differ if new["chars"] < old["chars"]]
    assert (len(lost), min(lost), max(lost)) == (190, 2, 394)
    assert [new["id"] for old, new in differ if new["largest"] > old["largest"]] == [
        PAPERS[LEFT_OUT][0]
    ]


def test_the_six_papers_of_the_questions_are_split_as_the_plan_of_the_runs_says():
    # The plan gave the sizes under parser 5 from the code and said that this file would
    # hold them: for the five letters the papers are cut, and none has a piece above the
    # limit of a call any more.
    by_id = {new["id"]: (old, new) for old, new in split_by_both()}
    sections = {}
    for name, (paper, before_chars) in PAPERS.items():
        old, new = by_id[paper]
        assert old["chars"] == before_chars
        sections[name] = (old["sections"], new["sections"])
        if name != LEFT_OUT:
            assert (old["no_headings"], new["no_headings"]) == (True, False)
            assert old["largest"] == before_chars > LIMIT > new["largest"]
    assert sections == {
        "sec-01": (10, 11),
        "sec-02": (1, 14),
        "sec-03": (1, 8),
        "sec-04": (1, 6),
        "sec-05": (1, 9),
        "sec-06": (1, 12),
    }


def test_what_the_readmes_say_of_the_two_files_is_what_the_files_say():
    split = split_by_both()
    old, new = tally(lines_of(OF_4)), tally(lines_of(OF_5))
    differ = sum(1 for o, n in split if o != n)

    # Where the plan was, what came back is written up.
    _, heading, text = WRITTEN_UP.read_text(encoding="utf-8").partition("\n# What came back\n")
    assert heading
    written_up = " ".join(text.split())
    assert (
        f"`survey.run` went through the 520 papers again with the code of `{RAN}`, in 19 seconds."
        in written_up
    )
    assert (
        "None, as expected. The same 494 papers were split by both, and the lines of the 26 "
        "without a TeX source are the same in both files." in written_up
    )
    assert (
        f"{differ} of the 494. All {differ} differ in the number of sections and in the "
        "characters, 39 in the largest piece, 17 in having no section heading, and none in the "
        "number of subsections." in written_up
    )
    for row in (
        "| papers that were split | 494 | 494 |",
        f"| without any section heading | {old.no_headings} | {new.no_headings} |",
        f"| with a piece of more than 20,000 characters | {old.over_limit} | {new.over_limit} |",
        "| both | 22 | 7 |",
    ):
        assert row in text
    assert (
        "Thirteen of them have 6 to 14 sections now. Four have two, and in each of the four the "
        "largest piece is still above 20,000 characters, 334 to 787 fewer than it was" in written_up
    )
    assert (
        "Eighteen papers left it and one came into it, `2610.39042v1`: its letter, which parser "
        "`4` left out, is one piece of 24,532 characters." in written_up
    )
    assert (
        "Of the 191, 167 have one more and 24 have 2 to 13 more; the 494 papers have 4,300 "
        "sections where they had 3,980, and 4,135 subsections in both files." in written_up
    )
    assert (
        "Parser `5` counts 27,275 characters more in `2610.39042v1`, and 2 to 394 fewer in each "
        "of the 190 others." in written_up
    )

    # The README of the folder: the file, the run, and the two shapes archive by archive.
    folder = flat(HERE / "README.md")
    assert (
        "what came back for the same 520 papers when parser `5` split them again: the file "
        f"that one run of `survey.run` wrote on 2026-11-25, by `{RAN}`" in folder
    )
    assert (
        "The run began at 10:46 UTC and ended within a minute, and left no paper unanswered."
        in folder
    )
    assert (
        "The same 494 papers were split, and the same 26 have no TeX source. Of the 494, the "
        f"lines of {differ} differ." in folder
    )
    archives = list(load_plan(PLAN).archives)
    for archive in (*archives, "all"):
        own = [(o, n) for o, n in split if archive in (o["archive"], "all")]
        cells = [
            len(own),
            sum(1 for o, n in own if o != n),
            sum(1 for o, _ in own if o["no_headings"]),
            sum(1 for _, n in own if n["no_headings"]),
            sum(1 for o, _ in own if o["largest"] > LIMIT),
            sum(1 for _, n in own if n["largest"] > LIMIT),
        ]
        assert f"| {archive} | " + " | ".join(str(cell) for cell in cells) + " |" in folder
    assert (
        "Eighteen papers left that count, and one came into it: `2610.39042v1` of hep-ex, whose "
        "letter parser `4` had left out and parser `5` returns as one piece of 24,532 characters."
        in folder
    )

    # The README of the repository, and the README of all results.
    readme = flat(ROOT / "README.md")
    # A number about the papers that were read stands beside the papers left unanswered.
    assert (new.unanswered, new.count(OK), new.count(NO_TEX), new.papers) == (0, 494, 26, 520)
    assert (
        "No paper was left unanswered. The same 494 papers were split, and the same 26 have "
        f"no TeX source. The lines of {differ} of the 494 differ. **A piece of more than "
        f"20,000 characters is in {new.over_limit} papers, where it was in "
        f"{old.over_limit}**, and {new.no_headings} have no section heading at all, where "
        f"{old.no_headings} had none." in readme
    )
    assert (
        f"counted on the 494 papers that were split: {old.over_limit} with parser `4`, "
        f"{new.over_limit} with parser `5`" in readme
    )
    assert (
        f"The other count, {old.no_headings} and then {new.no_headings} papers without any "
        "section heading, falls as soon as a paper gets one section" in readme
    )
    assert (
        "One more file holds what came back when parser `5` split the same papers again that day."
        in flat(ROOT / "results" / "README.md")
    )
