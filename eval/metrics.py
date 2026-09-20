"""Retrieval metrics. Pure functions, no I/O, so the scoring itself is unit-tested."""

import math
import re
from collections.abc import Sequence
from dataclasses import dataclass

Retrieved = tuple[str, str | None]  # (document source_path, chunk section)


@dataclass(frozen=True)
class Expected:
    path: str
    section: str | None = None  # exact section match
    section_prefix: str | None = None  # this section or anything nested under it ("A" or "A > b")


def matches(retrieved: Retrieved, expected: Expected) -> bool:
    path, section = retrieved
    if path != expected.path:
        return False
    if expected.section is not None:
        return section == expected.section
    if expected.section_prefix is not None:
        prefix = expected.section_prefix
        return section is not None and (section == prefix or section.startswith(prefix + " > "))
    return True


def first_hit_rank(retrieved: Sequence[Retrieved], expected: Sequence[Expected]) -> int | None:
    """1-based rank of the first retrieved chunk matching ANY expected source; None if absent."""
    for rank, item in enumerate(retrieved, start=1):
        if any(matches(item, e) for e in expected):
            return rank
    return None


def full_coverage_rank(retrieved: Sequence[Retrieved], expected: Sequence[Expected]) -> int | None:
    """For multi-hop questions: the rank by which EVERY expected source has been retrieved, i.e.
    the worst of the per-source first-hit ranks; None if any source is missing entirely.

    `first_hit_rank` gives credit for finding any one source, which flatters a system that finds
    half of what a two-fact question needs."""
    ranks = [first_hit_rank(retrieved, [e]) for e in expected]
    return None if any(r is None for r in ranks) else max(r for r in ranks if r is not None)


def recall_at_k(ranks: Sequence[int | None], k: int) -> float:
    """Fraction of questions with a correct chunk in the top k."""
    return sum(1 for r in ranks if r is not None and r <= k) / len(ranks)


def mean_reciprocal_rank(ranks: Sequence[int | None]) -> float:
    """Mean of 1/rank of the first correct chunk (0 when none was retrieved)."""
    return sum(1 / r for r in ranks if r is not None) / len(ranks)


def paired_comparison(
    baseline: Sequence[int | None], candidate: Sequence[int | None]
) -> tuple[int, int, int]:
    """(candidate_better, candidate_worse, tied) by rank per question. Missing = worst.

    With a few dozen questions, aggregate differences can be noise; counting per-question wins and
    losses shows whether an improvement is broad or driven by one or two questions.
    """
    inf = float("inf")
    better = worse = tied = 0
    for b, c in zip(baseline, candidate, strict=True):
        bv, cv = (b if b is not None else inf), (c if c is not None else inf)
        if cv < bv:
            better += 1
        elif cv > bv:
            worse += 1
        else:
            tied += 1
    return better, worse, tied


# ---------------------------------------------------------------- answer-level metrics


def precision_at_k(retrieved: Sequence[Retrieved], expected: Sequence[Expected], k: int) -> float:
    """Fraction of the top-k retrieved chunks that are correct sources (0 if nothing retrieved)."""
    top = retrieved[:k]
    if not top:
        return 0.0
    return sum(1 for item in top if any(matches(item, e) for e in expected)) / len(top)


def _number_in(text: str, number: str) -> bool:
    """True if `number` appears as a whole number: not inside a longer one ("18" in "180" or in
    "1.18"), and not just the integer part of a decimal ("14" in "14.4")."""
    return re.search(rf"(?<![\d.]){re.escape(number)}(?![\d]|\.\d)", text) is not None


def keyword_correct(answer: str, groups: Sequence[Sequence[str]]) -> bool:
    """Every group must be satisfied by at least one of its alternatives. An alternative is a
    case-insensitive substring, except that one starting with "#" is a WHOLE NUMBER ("#18" matches
    "deals 18 damage" but not "180" or "18.5"; thousands separators are ignored). Crude but
    deterministic: it checks that the required facts appear, not that the prose is good."""
    text = answer.lower()
    plain = re.sub(r"(?<=\d),(?=\d{3})", "", text)
    return all(
        any(
            _number_in(plain, alt[1:]) if alt.startswith("#") else alt.lower() in text
            for alt in group
        )
        for group in groups
    )


def citation_scores(cited: Sequence[Retrieved], expected: Sequence[Expected]) -> tuple[bool, float]:
    """(any_cited_source_is_correct, fraction_of_cited_sources_that_are_correct).

    Both are 0/False when nothing was cited."""
    if not cited:
        return False, 0.0
    correct = sum(1 for item in cited if any(matches(item, e) for e in expected))
    return correct > 0, correct / len(cited)


def percentile(values: Sequence[float], pct: float) -> float:
    """Nearest-rank percentile (pct in 0..100). Simple and needs no interpolation assumptions."""
    if not values:
        raise ValueError("percentile of empty sequence")
    ordered = sorted(values)
    rank = max(1, -(-len(ordered) * pct // 100))  # ceil
    return ordered[int(rank) - 1]


def gate_sweep(
    answerable: Sequence[float | None],
    unanswerable: Sequence[float | None],
    thresholds: Sequence[float],
) -> list[tuple[float, float, float]]:
    """For each threshold t: (t, share of answerable questions the gate lets through,
    share of unanswerable questions the gate blocks). A missing cosine is always blocked.

    This is the evidence gate *alone* (best cosine >= t); the LLM's own refusal is separate."""
    rows = []
    for t in thresholds:
        passed = sum(1 for s in answerable if s is not None and s >= t) / len(answerable)
        blocked = sum(1 for s in unanswerable if s is None or s < t) / len(unanswerable)
        rows.append((t, passed, blocked))
    return rows


def confusion_matrix(
    pairs: Sequence[tuple[str, str]], labels: Sequence[str]
) -> dict[tuple[str, str], int]:
    """Counts of (expected, got) over `pairs`; every label combination is present (0 if unseen)."""
    counts = {(e, g): 0 for e in labels for g in labels}
    for expected, got in pairs:
        counts[(expected, got)] = counts.get((expected, got), 0) + 1
    return counts


# ---------------------------------------------------------------- uncertainty


def wilson_interval(successes: int, total: int, z: float = 1.96) -> tuple[float, float]:
    """95% Wilson score interval for a proportion. Unlike the textbook normal interval it stays
    inside [0, 1] and behaves sensibly at 0% and 100%, which is where small evals often land.

    34/36 correct is "94%", but the interval (about 81% to 98%) is the honest statement: on this
    many questions a real difference of a few points cannot be told from luck."""
    if total <= 0:
        raise ValueError("total must be positive")
    p = successes / total
    denom = 1 + z * z / total
    centre = (p + z * z / (2 * total)) / denom
    half = z * math.sqrt(p * (1 - p) / total + z * z / (4 * total * total)) / denom
    return max(0.0, centre - half), min(1.0, centre + half)


def sign_test_p(better: int, worse: int) -> float:
    """Two-sided exact sign test on paired wins/losses (ties are ignored).

    Asks: if the two systems were really equal, how likely is a split at least this lopsided?
    4 wins to 0 losses gives p = 0.125, so even a clean sweep of 4 is NOT convincing evidence;
    10 to 0 gives p = 0.002. Small p means the difference is unlikely to be luck; it says nothing
    about whether the difference is large enough to matter."""
    n = better + worse
    if n == 0:
        return 1.0
    k = min(better, worse)
    tail = sum(math.comb(n, i) for i in range(k + 1)) / 2**n
    return min(1.0, 2 * tail)
