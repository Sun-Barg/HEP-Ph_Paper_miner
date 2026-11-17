"""What every run of the evaluation is made with, in one place.

The evaluation compares the two tool layouts. Everything else about a run is to be the
same in all of its runs, and is written down here: the names of the texts a model
reads, the way an answer is handed in, the model with its settings, and the limits of
a run.

The texts stand where they are used, each under a name (TOOLSET_VERSION in server.py,
PROMPT_VERSION in agent/prompt.py, PARSER_VERSION in sources/arxiv_latex.py), and tests
hold every text to its name. This module says which names the evaluation uses. A text
that changes gets a new name, and a new name does not agree with this module any more,
so the texts of the evaluation cannot change without a change that is made here, on
purpose (tests/test_conditions.py).

These conditions were fixed while the repository held no question of the evaluation:
the commit that adds this file has the five development questions only. The tool texts
and the prompt were tuned on those five, and are not tuned on the questions they are
then measured with. What the runs on the development questions showed, and so why the
conditions are these, is in results/runs/dev/README.md.

The first line of a record says what its run was made with, in the same words as
below. So a record can be held against the conditions: see `differences`.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

# Laid out like the first line of a record, so that the two can be read side by side.
EVALUATION: dict[str, Any] = {
    # The tool texts of the two layouts that are compared.
    "toolset_version": {"staged": "staged-5", "flat": "flat-4"},
    # The answer is the arguments of a call of the loop's own tool, and the prompt is
    # the one that says so. Of the three ways to hand in an answer, this is the one with
    # which all thirty runs of the third diagnosis ended with an answer.
    "answer_channel": "tool",
    "prompt_version": "p2-tool",
    "model": {
        "model": "claude-sonnet-5-5",
        "max_tokens": 16000,
        # What the API does for this model anyway when a request leaves these two out.
        # Whether a request also asks for the summaries of the thinking is left open
        # here: the model reads the same with and without them (agent/model.py).
        "thinking": {"type": "adaptive"},
        "effort": "high",
        # No request holds a text to the form of an answer: the answer is no text.
        "answer_format": None,
        # Every request asks the API to keep the conversation so far. The model reads
        # the same either way: it is a matter of cost (agent/model.py). This is the one
        # condition that is not a default of the command, which leaves the cache off:
        # a run of the evaluation is started with --cache.
        "cache_control": {"type": "ephemeral"},
        "max_retries": 2,
        "request_seconds": 600.0,
    },
    "limits": {"max_turns": 12, "tool_seconds": 700.0, "run_seconds": 900.0},
}

# The parser that splits a paper into sections. The server names it in a result, and a
# record keeps the names in its last line.
PARSER = "4"

# What a record says of its model beside the settings above: which SDK sent the
# requests. That is no condition somebody chose. uv.lock fixes it, like the two
# packages that write a part of what a model reads ("packages" in a record).
_NAMED_ONLY = {"sdk"}

_ABSENT = object()


def differences(run: Mapping[str, Any], end: Mapping[str, Any] | None = None) -> list[str]:
    """Every point in which a run was not made under the conditions, one sentence each.

    `run` is the first line of the record of a run, `end` its last line. An empty list
    says that the record names the conditions of the evaluation and nothing else. It
    does not say which code ran, or which questions were asked: a record names those
    too ("code", "questions"), and they are no part of the conditions.
    """
    found: list[str] = []

    def hold(where: str, got: Any, wanted: Any) -> None:
        if got is _ABSENT:
            found.append(f"{where} is not in the record")
        elif got != wanted:
            found.append(f"{where} is {got!r}, not {wanted!r}")

    layouts = EVALUATION["toolset_version"]
    layout = run.get("toolset", _ABSENT)
    if isinstance(layout, str) and layout in layouts:
        hold("toolset_version", run.get("toolset_version", _ABSENT), layouts[layout])
    elif layout is _ABSENT:
        found.append("toolset is not in the record")
    else:
        found.append(f"toolset is {layout!r}, not one of the layouts: {', '.join(layouts)}")
    for name in ("answer_channel", "prompt_version"):
        hold(name, run.get(name, _ABSENT), EVALUATION[name])

    settings = run.get("model")
    if not isinstance(settings, Mapping):
        settings = {}
    for name, wanted in EVALUATION["model"].items():
        got = settings.get(name, _ABSENT)
        if name == "thinking" and isinstance(got, Mapping):
            # Asking for the summaries adds "display" to this setting, and is left open.
            got = {key: value for key, value in got.items() if key != "display"}
        hold(f"model.{name}", got, wanted)
    # A setting that the conditions do not know is a thing a request held and nobody
    # decided on.
    for name in sorted(set(settings) - set(EVALUATION["model"]) - _NAMED_ONLY):
        found.append(f"model.{name} is a setting that the conditions do not name")

    limits = run.get("limits")
    if not isinstance(limits, Mapping):
        limits = {}
    for name, wanted in EVALUATION["limits"].items():
        hold(f"limits.{name}", limits.get(name, _ABSENT), wanted)
    for name in sorted(set(limits) - set(EVALUATION["limits"])):
        found.append(f"limits.{name} is a limit that the conditions do not name")

    if end is not None:
        for name in end.get("parser_versions") or []:
            if name != PARSER:
                found.append(f"a result came from parser {name!r}, not {PARSER!r}")
    return found
