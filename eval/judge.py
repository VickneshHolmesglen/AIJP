"""LLM-as-judge for answer faithfulness, plus a validation harness for the judge itself.

A judge is a measuring instrument, and instruments need calibrating. Here the same local model that
writes answers also judges them, which biases it toward approving its own style of answer. So we
never report faithfulness without first reporting the judge's accuracy on hand-labelled cases
(eval/datasets/judge_validation.json).
"""

import json
from dataclasses import dataclass

from app.llm import LLMError, LLMProvider

JUDGE_SYSTEM = """\
You check whether an ANSWER is faithful to the SOURCES it cites.

The answer is SUPPORTED only if every factual claim in it is stated in, or follows directly from, \
the SOURCES. If it contains a different number, a claim the sources never make, or outside \
knowledge, it is NOT supported. Ignore writing style and length.

Respond with a single JSON object and nothing else:
{"supported": true|false, "reason": "<one short sentence>"}
"""


def judge_supported(llm: LLMProvider, question: str, answer: str, sources: str) -> bool | None:
    """True/False verdict, or None if the judge failed or returned something unparseable."""
    user = f"SOURCES:\n{sources}\n\nQUESTION: {question}\n\nANSWER: {answer}"
    try:
        raw = llm.generate(JUDGE_SYSTEM, user).text
    except LLMError:
        return None
    try:
        verdict = json.loads(raw).get("supported")
    except (ValueError, AttributeError):
        return None
    return verdict if isinstance(verdict, bool) else None


@dataclass(frozen=True)
class JudgeValidation:
    total: int
    correct: int
    unparseable: int
    false_supported: int  # judge approved an unfaithful answer (the dangerous error)
    false_unsupported: int  # judge rejected a faithful answer

    @property
    def accuracy(self) -> float:
        return self.correct / self.total


def validate_judge(llm: LLMProvider, cases: list[dict]) -> JudgeValidation:
    correct = unparseable = false_supported = false_unsupported = 0
    for case in cases:
        verdict = judge_supported(llm, case["question"], case["answer"], case["sources"])
        if verdict is None:
            unparseable += 1
        elif verdict == case["supported"]:
            correct += 1
        elif verdict:
            false_supported += 1
        else:
            false_unsupported += 1
    return JudgeValidation(len(cases), correct, unparseable, false_supported, false_unsupported)
