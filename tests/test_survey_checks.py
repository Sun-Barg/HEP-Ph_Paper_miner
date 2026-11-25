"""What was found when outlines were held against the papers, and what the READMEs say of it.

results/survey/outline-check.jsonl is the file that survey.sheet wrote on 2026-11-25 (UTC)
from the sheet: for each of 65 papers two verdicts and a note. A Claude session had filled
in a draft of the sheet, and the maintainer had held the draft against each paper.
outline-check-first.jsonl is what the same command had written from the sheet earlier
that day. These tests hold the two files against the outcomes, the sample and the plan
they name and against each other, and hold up what the README of the repository and the
README of the folder say of them.

What they cannot hold up is the verdicts themselves. Whether an outline is the outline
of its paper is what was seen with the paper open, and no file here has the headings of
a paper to look it up in. Nor can they hold up who filled in the sheet and who looked.

From here on the two files are fixed (CLAUDE.md, "The survey").

No network and no LLM. The files hold identifiers, verdicts and notes, and no title of a
paper or of a section; one of the tests says so.
"""

from collections import Counter
from datetime import datetime
from functools import cache
from pathlib import Path

from hepph_paper_miner.agent.origin import file_digest
from hepph_paper_miner.survey.plan import load_plan
from hepph_paper_miner.survey.records import as_bytes, read_lines
from hepph_paper_miner.survey.run import OK, read_outcomes
from hepph_paper_miner.survey.sample import read_sample
from hepph_paper_miner.survey.sheet import VERDICTS, Check, check_lines, to_check

ROOT = Path(__file__).parent.parent
PLAN = ROOT / "eval_data" / "survey_plan.json"
HERE = ROOT / "results" / "survey"
SAMPLE = HERE / "sample.jsonl"
OUTCOMES = HERE / "outcomes.jsonl"
CHECKS = HERE / "outline-check.jsonl"
FIRST = HERE / "outline-check-first.jsonl"

# The files as the command wrote them on the maintainer's computer: the second time it
# read the sheet, and the first.
SHA256 = {
    CHECKS: "0395ca98f7694f56349c283ceb30cbf28875f63393e3c7c08b6bbd98aebaa2bc",
    FIRST: "8e50609fcd69e8e93b618d111d1c5cccc048a83aac00e1d8e9327af76147d94b",
}
# The commit whose code read the sheet: the one that brought the outcomes. The files name
# it in full.
READ_BY = "2293bd3"
DAY = "2026-11-25"

# The six sentences the notes are put together from, each with the verdict it explains,
# in the order of the table of the folder's README. None of them is a heading of a paper.
NO_ROW_FOR_THANKS = "an acknowledgements heading that stands on a line of its own has no row"
THANKS_RUN_IN = (
    "an acknowledgements title run into the head of a paragraph has no row (not counted: it "
    "stands below the section headings of the paper)"
)
TITLES_RUN_IN = (
    "titles run into the head of paragraphs are the top division of the paper and have no rows"
)
NO_ROWS_AFTER_REFERENCES = (
    "section headings of supplementary material after the reference list have no rows"
)
NO_ROWS_BELOW_THEM = (
    "subsection headings of supplementary material after the reference list have no rows"
)
ROWS_UNDER_ANOTHER_SECTION = (
    "subsection headings that the paper prints after the reference list are rows under the "
    "last section before it"
)
EXPLAINS = {
    NO_ROW_FOR_THANKS: "sections",
    # Noted and not counted: it explains no `differ`, and both verdicts stay `same`.
    THANKS_RUN_IN: None,
    TITLES_RUN_IN: "sections",
    NO_ROWS_AFTER_REFERENCES: "sections",
    NO_ROWS_BELOW_THEM: "subsections",
    ROWS_UNDER_ANOTHER_SECTION: "subsections",
}
LEVELS = ("sections", "subsections")


@cache
def checks(path: Path = CHECKS):
    """The first line of a file of the check and its paper lines."""
    lines, _ = read_lines(path, "outline_check")
    return lines[0], lines[1:]


def said(line) -> list[str]:
    """The sentences of a note."""
    return [sentence for sentence in line["note"].split("; ") if sentence]


def verdicts(line) -> tuple[str, str]:
    return line["sections"], line["subsections"]


def changed() -> tuple[list, list, list]:
    """What the second reading of the sheet has otherwise than the first, paper by paper.

    The pairs (line of the first file, line of the second) that are not the same, those
    of them whose verdicts changed, and those where only the note did.
    """
    _, papers = checks()
    _, first = checks(FIRST)
    moved = [(old, new) for old, new in zip(first, papers, strict=True) if old != new]
    turned = [(old, new) for old, new in moved if verdicts(old) != verdicts(new)]
    return moved, turned, [pair for pair in moved if pair not in turned]


def flat(path: Path) -> str:
    """A README with every run of white space as one blank, as a sentence is looked for."""
    return " ".join(path.read_text(encoding="utf-8").split())


def test_the_files_are_the_bytes_that_were_written():
    for path, digest in SHA256.items():
        assert file_digest(path) == digest


def test_the_first_line_names_the_outcomes_the_sample_the_plan_and_the_code():
    plan, sample = load_plan(PLAN), read_sample(SAMPLE)
    ran, _ = read_outcomes(OUTCOMES)

    for path in (CHECKS, FIRST):
        head, papers = checks(path)
        assert set(head) == {
            "record",
            "outcomes",
            "sample",
            "plan",
            "code",
            "per_archive",
            "unanswered_passed_over",
            "written",
            "papers",
            "same",
        }
        assert head["outcomes"] == {"file": OUTCOMES.name, "sha256": file_digest(OUTCOMES)}
        assert head["sample"] == {"file": SAMPLE.name, "sha256": sample.sha256} == ran["sample"]
        assert head["plan"] == sample.head["plan"] == ran["plan"]
        assert head["plan"]["sha256"] == plan.sha256
        # No file the repository keeps was changed when the sheet was read.
        assert head["code"]["commit"].startswith(READ_BY) and head["code"]["modified"] is False
        assert head["per_archive"] == plan.outline_per_archive
        # No paper was passed over: the survey had left none unanswered.
        assert head["unanswered_passed_over"] == ran["unanswered"] == 0
        assert head["papers"] == len(papers)
        # The verdicts were written after the last run of the survey had ended.
        written = datetime.fromisoformat(head["written"])
        assert f"{written:%Y-%m-%d}" == DAY
        assert written > datetime.fromisoformat(ran["ended"])


def test_the_papers_are_the_ones_the_plan_fixes_in_their_order():
    plan = load_plan(PLAN)
    _, papers = checks()
    _, came_back = read_outcomes(OUTCOMES)

    chosen, waiting = to_check(came_back, plan.outline_per_archive)
    assert waiting == []
    assert [(line["archive"], line["rank"], line["id"]) for line in papers] == [
        (line["archive"], line["rank"], line["id"]) for line in chosen
    ]
    # Five of every archive, each a paper that was split, and none in front of them that
    # was split and is not there.
    assert Counter(line["archive"] for line in papers) == dict.fromkeys(
        plan.archives, plan.outline_per_archive
    )
    assert len(papers) == len(plan.archives) * plan.outline_per_archive
    by_id = {line["id"]: line for line in came_back}
    for line in papers:
        assert by_id[line["id"]]["outcome"] == OK
        ahead = [
            other
            for other in came_back
            if other["archive"] == line["archive"]
            and other["rank"] < line["rank"]
            and other["outcome"] == OK
        ]
        assert all(other["id"] in {each["id"] for each in papers} for other in ahead)


def test_every_paper_has_two_verdicts_and_every_difference_a_note():
    for path in (CHECKS, FIRST):
        _, papers = checks(path)
        for line in papers:
            assert set(line) == {
                "record",
                "archive",
                "rank",
                "id",
                "sections",
                "subsections",
                "note",
            }
            assert line["record"] == "paper"
            assert line["sections"] in VERDICTS and line["subsections"] in VERDICTS
            # The command asks for a note where something differs. A note where nothing
            # differs is the one sentence that is noted and not counted, and nothing else.
            if "differ" in verdicts(line):
                assert line["note"]
            elif line["note"]:
                assert said(line) == [THANKS_RUN_IN]


def test_the_files_are_what_the_command_writes_for_these_verdicts():
    for path in (CHECKS, FIRST):
        head, papers = checks(path)
        found = [
            Check(
                line["archive"],
                line["rank"],
                line["id"],
                line["sections"],
                line["subsections"],
                line["note"],
            )
            for line in papers
        ]
        named = {
            name: value for name, value in head.items() if name not in ("record", "papers", "same")
        }
        # The count of the first line too: the papers where nothing was counted as a
        # difference.
        assert as_bytes(check_lines(found, named)) == path.read_bytes()
        assert head["same"] == sum(1 for line in papers if verdicts(line) == ("same", "same"))


def test_the_notes_are_six_sentences_and_fit_the_verdicts():
    _, came_back = read_outcomes(OUTCOMES)
    by_id = {line["id"]: line for line in came_back}

    for path in (CHECKS, FIRST):
        _, papers = checks(path)
        for line in papers:
            sentences = said(line)
            # No sentence twice, and none that is not one of the six: so no heading of a
            # paper, which the files must not hold, is in a note.
            assert len(sentences) == len(set(sentences))
            assert set(sentences) <= set(EXPLAINS)
            # A verdict is `differ` exactly when a sentence of the note is about that level.
            for level in LEVELS:
                about = any(EXPLAINS[sentence] == level for sentence in sentences)
                assert (line[level] == "differ") == about
            # The headings below the supplementary sections are only missing where those are.
            if NO_ROWS_BELOW_THEM in sentences:
                assert NO_ROWS_AFTER_REFERENCES in sentences
            # The acknowledgements of a paper have a heading of one kind. The title that
            # is not counted is one of a paper that came back with section headings.
            assert not {NO_ROW_FOR_THANKS, THANKS_RUN_IN} <= set(sentences)
            if THANKS_RUN_IN in sentences:
                assert not by_id[line["id"]]["no_headings"]
                assert by_id[line["id"]]["sections"] > 1


def test_what_the_second_reading_of_the_sheet_has_otherwise_than_the_first():
    head, papers = checks()
    first_head, first = checks(FIRST)
    moved, turned, noted = changed()

    # The same papers in the same order, and one sheet: only when it was read, and how
    # many papers have nothing counted, is otherwise in the first line.
    assert [(line["archive"], line["rank"], line["id"]) for line in first] == [
        (line["archive"], line["rank"], line["id"]) for line in papers
    ]
    assert {name for name in head if head[name] != first_head[name]} == {"written", "same"}
    assert datetime.fromisoformat(first_head["written"]) < datetime.fromisoformat(head["written"])

    # Neither sentence about a title run into a paragraph was on the sheet the first time.
    assert not any({THANKS_RUN_IN, TITLES_RUN_IN} & set(said(line)) for line in first)

    # A verdict that changed went from `same` to `differ` under `sections`, in a paper
    # that had no note, and for the titles that are its top division.
    for old, new in turned:
        assert (*verdicts(old), old["note"]) == ("same", "same", "")
        assert verdicts(new) == ("differ", "same")
        assert said(new) == [TITLES_RUN_IN]
    assert len(turned) == first_head["same"] - head["same"] == 4

    # Where only the note changed, one of the two sentences was added to what was there,
    # and what was there stayed as it was.
    added = Counter()
    for old, new in noted:
        (sentence,) = [each for each in said(new) if each not in said(old)]
        assert [each for each in said(new) if each != sentence] == said(old)
        added[sentence] += 1
    assert added == {THANKS_RUN_IN: 6, TITLES_RUN_IN: 1}
    assert all(not said(old) for old, new in noted if THANKS_RUN_IN in said(new))
    assert len(papers) - len(moved) == 54


def test_what_the_readme_says_of_the_check_is_what_the_files_say():
    plan = load_plan(PLAN)
    head, papers = checks()
    first_head, _ = checks(FIRST)
    _, came_back = read_outcomes(OUTCOMES)
    by_id = {line["id"]: line for line in came_back}
    moved, turned, noted = changed()
    readme = flat(ROOT / "README.md")
    count = len(papers)

    # Where the survey stands.
    assert "Everything ticked under Status is done" in readme
    assert "- [ ]" not in readme
    assert (
        f"- [x] A survey of which papers the server can read, in thirteen archives: "
        f"{len(came_back)} papers fetched and counted, and {count} of their outlines held "
        "against the papers, from a draft by a model that the maintainer checked paper by paper"
        in readme
    )
    assert len(plan.archives) == 13
    assert (
        f"**It has been run, and {count} of its outlines have been held against the papers.**"
        in readme
    )
    assert "the outcomes before the verdicts were written" in readme
    assert "has not been made yet" not in readme and "It will say, once" not in readme

    # How it was made, when, by which code.
    assert (
        f"The check was made on {DAY}, and it was not made by hand alone, as the plan has it."
        in readme
    )
    assert (
        "A Claude session filled in a draft of it from the PDF or HTML pages of the papers. The "
        f"maintainer then opened each of the {count} papers and held the draft against it."
        in readme
    )
    assert (
        "`results/survey/outline-check.jsonl` is what the command wrote from the sheet in the "
        f"end, by `{READ_BY}`, the commit that brought the outcomes, and it names the file of the "
        f"outcomes by its SHA-256. All {count} papers have both verdicts." in readme
    )

    # The table.
    same = {level: [line for line in papers if line[level] == "same"] for level in LEVELS}
    both = [line for line in papers if verdicts(line) == ("same", "same")]
    for archive in plan.archives:
        own = [line for line in papers if line["archive"] == archive]
        cells = [
            len(own),
            sum(1 for line in own if line in same["sections"]),
            sum(1 for line in own if line in same["subsections"]),
            sum(1 for line in own if line in both),
        ]
        assert f"| {archive} | " + " | ".join(map(str, cells)) + " |" in readme
    assert (
        f"| all | {count} | {len(same['sections'])} | {len(same['subsections'])} | {len(both)} |"
        in readme
    )
    assert head["same"] == len(both)

    # The notes of what differs.
    differing = [line for line in papers if line not in both]
    assert (
        f"In {len(both)} of the {count} outlines nothing was counted as a difference. Each of "
        f"the other {len(differing)} has a note of what differs, and the notes say four things:"
        in readme
    )
    assert len(both) + len(differing) == count
    having = {
        sentence: [line for line in papers if sentence in said(line)] for sentence in EXPLAINS
    }
    thanks = having[NO_ROW_FOR_THANKS]
    alone = sum(1 for line in thanks if said(line) == [NO_ROW_FOR_THANKS])
    assert (
        f"- In {len(thanks)} papers a heading over the acknowledgements, on a line of its own, "
        f"has no row. In {alone} of them nothing else differs." in readme
    )
    titles = having[TITLES_RUN_IN]
    assert (
        f"- In {len(titles)} papers the main text is divided by titles that are run into the "
        "head of a paragraph, and the outline has no rows for them (the first reading below)."
        in readme
    )
    after = having[NO_ROWS_AFTER_REFERENCES]
    assert (
        f"- In {len(after)} papers the section headings of supplementary material, which the "
        "paper prints after its list of references, have no rows. In "
        f"{len(having[NO_ROWS_BELOW_THEM])} of the {len(after)} its subsection headings have "
        "none either." in readme
    )
    assert (
        f"- In {len(having[ROWS_UNDER_ANOTHER_SECTION])} paper subsections that the paper prints "
        "after its list of references are rows under the last section before the list." in readme
    )
    assert len(having[ROWS_UNDER_ANOTHER_SECTION]) == 1
    assert f"What in the sources of these {len(differing)} papers makes the difference" in readme

    # The two readings of a title that is run into the head of a paragraph.
    assert (
        "Two readings were settled on the day of the check, with outlines already in sight:"
        in readme
    )
    assert (
        f"so `sections` is `differ`. These are the {len(titles)} papers above. The reading had "
        "been put forward before the sheet was written, and it was settled only after the "
        f"command had read the sheet once: until then {len(turned)} of the {len(titles)} were "
        "`same`." in readme
    )
    assert all(new in titles for _, new in turned)
    run_in = having[THANKS_RUN_IN]
    assert all(line in both for line in run_in)
    assert (
        "the title stands below the section headings, as the title of a paragraph does, and it "
        f"is not counted. This is noted in {len(run_in)} papers, and both their verdicts are "
        "`same`. Counted as "
        f"differences, they would leave `sections` the same in "
        f"{len(same['sections']) - len(run_in)} papers and both verdicts in "
        f"{len(both) - len(run_in)}." in readme
    )

    # The two times the command read the sheet.
    written = datetime.fromisoformat(head["written"])
    first_written = datetime.fromisoformat(first_head["written"])
    assert (
        "The command read the sheet twice that day. `results/survey/outline-check-first.jsonl` "
        f"is what it wrote at {first_written:%H:%M} UTC, and the file above is what it wrote at "
        f"{written:%H:%M} UTC." in readme
    )
    already = [new for _, new in noted if TITLES_RUN_IN in said(new)]
    assert len(already) == 1 and len(noted) == len(run_in) + len(already)
    assert (
        f"the first reading turned `sections` from `same` to `differ` for {len(turned)} papers, "
        f"and {len(noted)} papers got a note or a longer one while their verdicts stayed: the "
        f"{len(run_in)} of the second reading, and {len(already)} of the {len(titles)} that "
        f"differed for another reason already. The lines of the other {count - len(moved)} "
        "papers are the same in both files." in readme
    )

    # The papers that came back as one piece.
    bare = [line for line in papers if by_id[line["id"]]["no_headings"]]
    where = Counter(line["archive"] for line in bare)
    assert where == {"hep-ex": 1, "nucl-ex": 2, "nucl-th": 1, "physics": 1}
    assert (
        f"Five of the {count} are papers that came back as one piece without a section heading "
        "(1 of hep-ex, 2 of nucl-ex, 1 of nucl-th, 1 of physics)." in readme
    )
    assert len(bare) == 5 and not any(line in both for line in bare)
    divided = [line for line in bare if line in titles]
    assert [said(line) for line in bare if line not in divided] == [[NO_ROW_FOR_THANKS]]
    (other,) = [line for line in titles if line not in bare]
    assert (
        f"None of them has both verdicts `same`: {len(divided)} are among the papers divided by "
        "titles run into paragraphs, and 1 has a heading over its acknowledgements on a line of "
        "its own. The fifth paper divided by such titles came back as "
        f"{by_id[other['id']]['sections']} sections." in readme
    )
    assert len(titles) == 5

    # How far it goes.
    assert "A model wrote the draft, and one person held it against the papers." in readme
    assert (
        "That person had the draft in sight when opening a paper, and nobody has looked a second "
        "time." in readme
    )
    assert "The two readings were made after outlines had been seen." in readme
    assert plan.outline_per_archive == 5
    assert "A row of the table is five outlines." in readme
    assert (
        "No note names a row that is no heading of the paper, another order or another title"
        in (readme)
    )
    assert (
        "the notes of the check of the outlines, and no title, abstract or text of a paper"
        in readme
    )


def test_what_the_readme_of_the_folder_says_of_the_check_is_what_the_files_say():
    plan = load_plan(PLAN)
    head, papers = checks()
    first_head, _ = checks(FIRST)
    ran, _ = read_outcomes(OUTCOMES)
    moved, turned, noted = changed()
    readme = flat(HERE / "README.md")
    count = len(papers)

    assert (
        f"| `outline-check.jsonl` | what was found when {count} outlines were held against the "
        "papers: for each paper two verdicts and a note. `survey.sheet` wrote it on "
        f"{DAY} from the sheet, which a Claude session had filled in as a draft and the "
        "maintainer had checked against each paper." in readme
    )
    assert (
        "| `outline-check-first.jsonl` | what the same command wrote when it first read the "
        "sheet, earlier that day. It is kept to show what was changed after it, and it is not "
        "the result |" in readme
    )
    assert (
        "`tests/test_survey_checks.py` does the same for the two files of the check of the "
        "outlines." in readme
    )
    assert (
        f"the first {plan.outline_per_archive} in the order of the sample were on the sheet: "
        f"{count} papers" in readme
    )
    assert (
        "A Claude session filled in a draft of the sheet from the PDF or HTML pages of the "
        "papers, and the maintainer opened each paper and held the draft against it." in readme
    )
    written = datetime.fromisoformat(head["written"])
    first_written = datetime.fromisoformat(first_head["written"])
    ended = datetime.fromisoformat(ran["ended"])
    assert (
        f"and `{READ_BY}`, the commit whose code read the sheet. It was written at "
        f"{written:%H:%M} UTC on {DAY}, after the last run of the survey had ended "
        f"({ended:%H:%M} UTC)." in readme
    )

    both = sum(1 for line in papers if verdicts(line) == ("same", "same"))
    with_note = [line for line in papers if line["note"]]
    assert (
        f"For {both} papers both verdicts are `same`, and {count - len(with_note)} of them have "
        f"no note. The notes of the other {len(with_note)} papers are put together from six "
        "sentences" in readme
    )
    assert len(EXPLAINS) == 6
    having = {
        sentence: [line for line in papers if sentence in said(line)] for sentence in EXPLAINS
    }
    # The table has the sentences by the number of their papers, which is their order here.
    table = [f"| {sentence} | {len(lines)} |" for sentence, lines in having.items()]
    assert " ".join(["| The note says | Papers |", "|---|---|", *table]) in readme
    assert [len(lines) for lines in having.values()] == sorted(map(len, having.values()))[::-1]
    assert list(EXPLAINS.values()) == [
        "sections",
        None,
        "sections",
        "sections",
        "subsections",
        "subsections",
    ]
    differ = {level: sum(1 for line in papers if line[level] == "differ") for level in LEVELS}
    of_sections = [sentence for sentence, level in EXPLAINS.items() if level == "sections"]
    twice = sum(1 for line in papers if sum(s in said(line) for s in of_sections) == 2)
    assert twice == 2
    run_in = having[THANKS_RUN_IN]
    assert all(said(line) == [THANKS_RUN_IN] for line in run_in)
    assert (
        "The first, the third and the fourth go with `differ` under `sections` "
        f"({differ['sections']} papers: two papers have two of them), the last two with `differ` "
        f"under `subsections` ({differ['subsections']} papers). The second goes with no "
        f"`differ`: it is the whole note of {len(run_in)} papers whose verdicts are both `same`"
        in readme
    )
    where = Counter(line["archive"] for line in having[NO_ROW_FOR_THANKS])
    assert len(where) == 11 and sorted(where.items(), key=lambda item: (-item[1], item[0])) == [
        ("hep-ph", 3),
        ("hep-lat", 2),
        ("quant-ph", 2),
        ("astro-ph", 1),
        ("cond-mat", 1),
        ("gr-qc", 1),
        ("hep-ex", 1),
        ("hep-th", 1),
        ("nucl-ex", 1),
        ("nucl-th", 1),
        ("physics", 1),
    ]
    assert (
        "The papers with the first sentence are of eleven archives: 3 of hep-ph, 2 of hep-lat "
        "and of quant-ph, and 1 of astro-ph, cond-mat, gr-qc, hep-ex, hep-th, nucl-ex, nucl-th "
        "and physics." in readme
    )

    # The first file.
    assert (
        "`outline-check-first.jsonl` is what the command wrote when it first read the sheet, at "
        f"{first_written:%H:%M} UTC. Both files have the same {count} papers, and the lines of "
        f"{count - len(moved)} of them are the same in both. For {len(turned)} papers `sections` "
        "went from `same` to `differ`, with the third sentence as their note. For "
        f"{len(noted)} papers only the note changed: the third sentence was added to the note of "
        f"{len(noted) - len(run_in)} paper, and the second sentence became the note of "
        f"{len(run_in)}. Those {len(run_in)} notes were put on the sheet by a Claude session"
        in readme
    )
    assert list(EXPLAINS)[1:3] == [THANKS_RUN_IN, TITLES_RUN_IN]
    assert "The draft was a model's, and the check of it one person's." in readme

    # The README of all results points here.
    assert (
        f"what was found on {DAY} when {count} of the outlines were held against the papers"
        in flat(ROOT / "results" / "README.md")
    )


def test_the_rules_for_agents_say_how_the_check_was_made_and_that_it_is_fixed():
    rules = flat(ROOT / "CLAUDE.md")
    _, papers = checks()

    assert (
        f"The outlines of {len(papers)} papers were held against the papers on {DAY}: a Claude "
        "session drafted the verdicts and notes, and the owner checked each against its paper. "
        "`results/survey/outline-check.jsonl` is fixed as well: `tests/test_survey_checks.py` "
        "holds it by its SHA-256." in rules
    )
    assert "An agent does not change a verdict or a note in it." in rules
    assert "it fills in a draft for the owner to check, and the README says who did what" in rules
    assert "the notes of the check of the outlines" in rules
