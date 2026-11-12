"""Download and split every paper in eval_data/target_papers.txt, and print one line per paper.

    uv run python scripts/check_targets.py

Sends real requests to arXiv, three seconds apart (two per paper the first time,
none once the answers are cached). Prints identifiers, counts and titles only: no
paper text. The output can be pasted into an issue or a chat as it is.
"""

from __future__ import annotations

import sys
from pathlib import Path

from hepph_paper_miner.http import Fetcher, default_cache_dir
from hepph_paper_miner.sources.arxiv import ArxivSource
from hepph_paper_miner.sources.base import SourceError, parse_arxiv_id

TARGETS = Path(__file__).parent.parent / "eval_data" / "target_papers.txt"


def main() -> int:
    lines = TARGETS.read_text(encoding="utf-8").splitlines()
    targets = [line.strip() for line in lines if line.strip() and not line.lstrip().startswith("#")]
    source = ArxivSource(Fetcher(default_cache_dir(), user_agent="hepph-paper-miner/check-targets"))
    print(f"cache: {default_cache_dir()}")
    print(
        f"{'identifier':<14} {'result':<14} {'sections':>8} {'subs':>5} {'chars':>8} {'largest':>8}  title"
    )

    split = 0
    for target in targets:
        try:
            paper = source.paper(parse_arxiv_id(target))
        except SourceError as error:
            print(
                f"{target:<14} {error.kind.value:<14} {'-':>8} {'-':>5} {'-':>8} {'-':>8}  {error.detail[:60]}"
            )
            continue
        split += 1
        top = [section for section in paper.sections if section.level == 1]
        largest = max(
            section.chars for section in paper.sections if section.level == 2 or section in top
        )
        print(
            f"{paper.meta.arxiv_id:<14} {'ok':<14} {len(top):>8} {len(paper.sections) - len(top):>5} "
            f"{paper.chars:>8} {largest:>8}  {paper.meta.title[:60]}"
        )
    print(f"\nsplit into sections: {split} of {len(targets)}")
    return 0 if split == len(targets) else 1


if __name__ == "__main__":
    sys.exit(main())
