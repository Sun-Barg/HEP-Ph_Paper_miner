"""The pre-registration names the question file that the evaluation asks, by its digest.

A question changed after the pre-registration was written would be asked under a digest
that no longer stands in it, and the runner, started as the pre-registration says, would
refuse the file. This test says so before any run.
"""

import hashlib
import re
from pathlib import Path

EVAL_DATA = Path(__file__).parent.parent / "eval_data"


def test_the_preregistration_names_the_digest_of_the_question_file():
    text = (EVAL_DATA / "PREREGISTRATION.md").read_text(encoding="utf-8")
    digest = hashlib.sha256((EVAL_DATA / "questions_eval.jsonl").read_bytes()).hexdigest()
    named = set(re.findall(r"\b[0-9a-f]{64}\b", text))
    assert named == {digest}
