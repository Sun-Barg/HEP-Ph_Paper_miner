"""Print what the model thought in a run, turn by turn, beside the tools it asked for.

    uv run python scripts/show_thinking.py "results/runs/20261113T*.jsonl"
    uv run python scripts/show_thinking.py "results/runs/20261113T*.jsonl" --out thinking.txt

For runs made with --show-thinking. Name the public records (files, or a pattern with *
in quotes); the thinking is read from the private record of the same name, which is
looked for where the command that made the run puts it.

For every turn this prints what the API counted, the summary of each thinking block,
and each tool call with its arguments and the facts of the first line of its result.
It also prints the text of a response that was not read as the answer of the run: a
run made with --no-answer-format ends with such a text, and so can a run that was to
call the answer tool or to write JSON (--answer-channel). It prints no text that a tool
returned. A summary of thinking and a text are the model's own wording and can quote
a few words of a paper, so the output is something to read and to show, and not
something to commit.
"""

from __future__ import annotations

import argparse
import glob
import json
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from hepph_paper_miner.agent.trace import default_private_dir


def read(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def thoughts(private_turn: dict[str, Any] | None) -> list[str] | None:
    """The text of every thinking block of one response, or None without a private record."""
    if private_turn is None:
        return None
    blocks = (private_turn.get("reply") or {}).get("content") or []
    return [block.get("thinking") or "" for block in blocks if block.get("type") == "thinking"]


def texts(private_turn: dict[str, Any] | None) -> list[str]:
    """The text blocks of one response. Empty without a private record."""
    blocks = ((private_turn or {}).get("reply") or {}).get("content") or []
    return [block.get("text") or "" for block in blocks if block.get("type") == "text"]


def render(public: list[dict[str, Any]], private: list[dict[str, Any]] | None) -> list[str]:
    """One run as lines of text. `private` is None when its private record is not there."""
    if not public:
        return ["== (an empty record: a run that could not start, or died at once)"]
    run = public[0]
    code = run.get("code") or {}
    commit = (code.get("commit") or "unknown")[:7] + ("+changes" if code.get("modified") else "")
    shown = ((run.get("model") or {}).get("thinking") or {}).get("display") == "summarized"
    lines = [
        f"== {run.get('run_id')} | {run.get('question_id')} | {run.get('toolset_version')} "
        f"| repeat {run.get('repeat')} | code {commit} "
        f"| thinking {'shown' if shown else 'not asked for'}"
        # A record names the way its answer was to come in since there is more than one.
        + (f" | answer by {run['answer_channel']}" if run.get("answer_channel") else "")
    ]
    if private is None:
        lines.append("   (no private record of this name: the thinking cannot be shown)")
    private_turns = {line["turn"]: line for line in private or [] if line.get("record") == "turn"}
    # The text that was read as the answer is printed with the end of the run, below.
    # An answer that came as a call of the answer tool was no text: what the model wrote
    # beside that call is printed like any other text.
    answered_in = next(
        (line["turns"] for line in public if line["record"] == "end" and line.get("answer")), None
    )
    if run.get("answer_channel") == "tool":
        answered_in = None
    for line in public[1:]:
        if line["record"] == "turn":
            usage = line["usage"]
            thinking = (usage.get("output_tokens_details") or {}).get("thinking_tokens", 0)
            lines.append(
                f"turn {line['turn']} | {line['stop_reason']} | {', '.join(line['blocks'])} "
                f"| in {usage.get('input_tokens', 0)} "
                f"+ {usage.get('cache_creation_input_tokens', 0)} written "
                f"+ {usage.get('cache_read_input_tokens', 0)} read "
                f"| out {usage.get('output_tokens', 0)} (thinking {thinking})"
            )
            for thought in thoughts(private_turns.get(line["turn"])) or []:
                lines.append(f"   thought: {thought.strip() or '(no text)'}")
            if line["turn"] != answered_in:
                for text in texts(private_turns.get(line["turn"])):
                    lines.append(f"   text: {text.strip() or '(no text)'}")
            for tool in line["tools"]:
                facts = json.dumps(tool.get("first_line"), ensure_ascii=False)
                lines.append(
                    f"   asks: {tool['name']} {json.dumps(tool['arguments'], ensure_ascii=False)} "
                    f"-> {tool['status']}"
                    + (f" [{tool['error_kind']}]" if tool.get("error_kind") else "")
                    + (f", {tool['result_chars']} chars, {facts}" if "result_chars" in tool else "")
                )
        elif line["record"] == "end":
            answer = line.get("answer") or {}
            cited = "; ".join(
                f"{e['arxiv_id']} {e['section_id']}" for e in answer.get("evidence", [])
            )
            lines.append(
                f"end: {line['reason']} | {line['turns']} turns | {line['tool_result_chars']} "
                f"chars in {line['tool_calls']} results"
                + (f" | found {answer['found']} | evidence {cited or '(none)'}" if answer else "")
            )
            if answer:
                lines.append(f"   answer: {answer['answer']}")
    return lines


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument("records", nargs="+", help="public records, or a pattern in quotes")
    parser.add_argument("--private", type=Path, default=default_private_dir())
    parser.add_argument("--out", type=Path, help="write here (UTF-8) instead of printing")
    arguments = parser.parse_args(argv)

    # The shell of Windows hands a pattern over as it was typed, so it is opened here.
    paths = sorted({Path(found) for name in arguments.records for found in glob.glob(name)})
    if not paths:
        print(f"no record matches: {' '.join(arguments.records)}", file=sys.stderr)
        return 2
    lines: list[str] = []
    for path in paths:
        twin = arguments.private / path.name
        lines += render(read(path), read(twin) if twin.is_file() else None)
        lines.append("")
    text = "\n".join(lines)
    if arguments.out:
        arguments.out.write_text(text, encoding="utf-8", newline="\n")
        print(f"{len(paths)} run(s) written to {arguments.out}")
    else:
        if hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(errors="backslashreplace")
        print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
