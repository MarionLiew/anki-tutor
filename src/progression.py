"""Small, deterministic gate between a concept and the next question.

The assistant judges the answer; this module checks that the resulting move
honours first-attempt grading and a required changed-context transfer check.
It does not store progress or schedule reviews.
"""
from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class Decision:
    action: str
    grade: Optional[int] = None


def decide_next(first_attempt: str, latest: str, transfer: str,
                extension: str = "same_concept", budget_exhausted: bool = False,
                transfer_first_failed: bool = False, hints_used: bool = False,
                objective: str = "L1") -> Decision:
    """Choose a route, never award Good for a hinted or failed first attempt.

    first_attempt: correct, partial, wrong ("I don't know" counts as wrong).
    latest: correct, partial, wrong. transfer: not_needed, not_asked, failed,
    passed (independently correct) or assisted_correct (correct only after a
    hint — the transfer requirement is NOT met). extension: same_concept or
    new_concept.
    """
    if first_attempt not in {"correct", "partial", "wrong"}:
        raise ValueError("invalid first_attempt")
    if latest not in {"correct", "partial", "wrong"}:
        raise ValueError("invalid latest")
    if transfer not in {"not_needed", "not_asked", "failed", "passed", "assisted_correct"}:
        raise ValueError("invalid transfer")
    if extension not in {"same_concept", "new_concept"}:
        raise ValueError("invalid extension")
    if objective not in {"L0", "L1", "L2", "L3"}:
        raise ValueError("invalid objective")

    grade = 1 if transfer_first_failed or hints_used or first_attempt == "wrong" else 2 if first_attempt == "partial" else 3
    transfer_ok = transfer == "passed"

    # Route for the evidence as it stands, ignoring the session budget.
    if latest != "correct":
        route = Decision("repair_current" if (transfer == "failed" or latest == "wrong") else "probe_current")
    elif (objective in {"L2", "L3"} or first_attempt != "correct" or hints_used) and not transfer_ok:
        route = Decision("ask_transfer")
    elif transfer == "failed":
        route = Decision("repair_current")
    else:
        route = Decision("close_then_introduce" if extension == "new_concept" else "close_concept", grade)

    if budget_exhausted:
        # The budget limits the SESSION, it is not evidence about the learner.
        # Only a genuinely unfinished concept closes with a declared gap; when
        # the target evidence is already satisfied the earned grade stands, so
        # a correct 8th question is never forced to Again (§4/§9.1).
        if route.action in ("close_concept", "close_then_introduce"):
            return Decision("close_concept", grade)
        return Decision("close_with_gap", 1)
    return route
