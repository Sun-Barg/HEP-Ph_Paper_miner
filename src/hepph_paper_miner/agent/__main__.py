"""Ask one question, with the real model and the real arXiv.

    python -m hepph_paper_miner.agent --question-id dev-01
    python -m hepph_paper_miner.agent --question-id dev-01 --toolset flat
    python -m hepph_paper_miner.agent --question "Which paper ...?"

Needs the API key in the environment variable ANTHROPIC_API_KEY, and is to be run
from the repository folder (the question file is looked for under eval_data/).
Every run costs money and sends requests to arXiv.

The server is not started as a separate process here: it is built in this process
and reached through the SDK's in-memory client, with the same protocol in between.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Sequence
from pathlib import Path

import anyio
from mcp import Client

from hepph_paper_miner import __version__
from hepph_paper_miner.agent.loop import EndReason, Limits, Outcome, run
from hepph_paper_miner.agent.model import ClaudeModel
from hepph_paper_miner.agent.origin import file_digest
from hepph_paper_miner.agent.trace import Trace, default_private_dir, new_run_id
from hepph_paper_miner.eval.questions import QuestionFileError, load_questions
from hepph_paper_miner.http import Fetcher, default_cache_dir
from hepph_paper_miner.server import SERVER_NAME, TOOLSET_VERSION, build_server
from hepph_paper_miner.sources.arxiv import ArxivSource


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m hepph_paper_miner.agent",
        description="Ask one question and write the record of the run.",
    )
    which = parser.add_mutually_exclusive_group(required=True)
    which.add_argument("--question-id", help="the id of a question in the question file")
    which.add_argument("--question", help="a question of your own, in quotes")
    parser.add_argument(
        "--questions",
        type=Path,
        default=Path("eval_data/questions_dev.jsonl"),
        help="the question file (default: %(default)s)",
    )
    parser.add_argument("--toolset", choices=sorted(TOOLSET_VERSION), default="staged")
    parser.add_argument("--model", default="claude-sonnet-5-5")
    parser.add_argument(
        "--effort", default="high", choices=["low", "medium", "high", "xhigh", "max"]
    )
    parser.add_argument(
        "--cache",
        action="store_true",
        help="have the API keep the conversation between the turns of the run "
        "(cheaper for a long run, dearer for a short one: see the README)",
    )
    parser.add_argument(
        "--show-thinking",
        action="store_true",
        help="have the API return a summary of the model's thinking, for the private "
        "record only (the model reads and pays the same: see the README)",
    )
    parser.add_argument(
        "--no-answer-format",
        action="store_true",
        help="for a diagnosis, not for an evaluation: do not hold the final text to the "
        "form of an answer (such a run can end as 'no_answer': see the README)",
    )
    parser.add_argument("--max-turns", type=int, default=Limits().max_turns)
    parser.add_argument(
        "--repeat",
        type=int,
        help="which repetition of the question this run is (1, 2, ...), for the record",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=Path("results/runs"),
        help="folder for the public record, without paper text (default: %(default)s)",
    )
    parser.add_argument(
        "--private",
        type=Path,
        default=default_private_dir(),
        help="folder for the private record, with paper text (default: %(default)s)",
    )
    arguments = parser.parse_args(argv)

    # A Windows console that cannot show a character must not end the run.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="backslashreplace")

    if not os.environ.get("ANTHROPIC_API_KEY"):
        print(
            "ANTHROPIC_API_KEY is not set in this shell, so the model cannot be asked.",
            file=sys.stderr,
        )
        return 2

    if arguments.question is not None:
        question_id, question, questions = "adhoc", arguments.question, None
    else:
        try:
            known = {item.id: item for item in load_questions(arguments.questions)}
        except (OSError, QuestionFileError) as error:
            print(f"cannot read the questions: {error}", file=sys.stderr)
            return 2
        if arguments.question_id not in known:
            print(
                f"no question {arguments.question_id!r}; there are: {', '.join(known)}",
                file=sys.stderr,
            )
            return 2
        question_id, question = arguments.question_id, known[arguments.question_id].question
        # A record names its question by id, and an id says nothing once the file has
        # been edited. So the record also names the file as it lay on the disk.
        questions = {"file": arguments.questions.name, "sha256": file_digest(arguments.questions)}

    try:
        limits = Limits(max_turns=arguments.max_turns)
    except ValueError as error:
        print(f"--max-turns {arguments.max_turns}: {error}", file=sys.stderr)
        return 2
    if arguments.repeat is not None and arguments.repeat < 1:
        print(f"--repeat {arguments.repeat}: repetitions are counted from 1", file=sys.stderr)
        return 2
    model = ClaudeModel(
        arguments.model,
        effort=arguments.effort,
        cache=arguments.cache,
        show_thinking=arguments.show_thinking,
        answer_format=not arguments.no_answer_format,
    )
    # The files of the record are made last, when nothing can refuse the run any more:
    # a file without an "end" line reads as a run that died.
    trace = Trace(
        new_run_id(question_id, arguments.toolset),
        arguments.out,
        arguments.private,
        labels={
            "question_id": question_id,
            "toolset": arguments.toolset,
            "repeat": arguments.repeat,
            "questions": questions,
        },
    )
    print(f"run       {trace.run_id}")
    outcome = anyio.run(_ask, question, arguments.toolset, model, trace, limits)

    print(f"ended     {outcome.reason.value}" + (f" ({outcome.detail})" if outcome.detail else ""))
    print(f"turns     {outcome.turns}")
    if outcome.answer is not None:
        print(f"found     {outcome.answer['found']}")
        print(f"answer    {outcome.answer['answer']}")
        cited = [f"{item['arxiv_id']} {item['section_id']}" for item in outcome.answer["evidence"]]
        print(f"evidence  {'; '.join(cited) or '(none)'}")
    last = json.loads(trace.public_path.read_text(encoding="utf-8").splitlines()[-1])
    print(
        f"read      {last['tool_result_chars']} characters in {last['tool_calls']} tool results; "
        f"{last['input_tokens']} input and {last['output_tokens']} output tokens"
    )
    written, reread = last["cache_creation_input_tokens"], last["cache_read_input_tokens"]
    if written or reread:
        # With the cache on, these are input tokens too: "input" above is the rest.
        print(f"cache     {written} tokens written to it, {reread} read from it")
    print(f"public    {trace.public_path}")
    print(f"private   {trace.private_path}")
    return 0 if outcome.reason is EndReason.ANSWERED else 1


async def _ask(
    question: str, toolset: str, model: ClaudeModel, trace: Trace, limits: Limits
) -> Outcome:
    fetcher = Fetcher(default_cache_dir(), user_agent=f"{SERVER_NAME}/{__version__}")
    async with Client(build_server(ArxivSource(fetcher), toolset)) as client:
        return await run(question, client=client, model=model, trace=trace, limits=limits)


if __name__ == "__main__":
    sys.exit(main())
