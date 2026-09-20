"""Paired comparison of two end-to-end QA runs, optionally pooled over several question sets.

    uv run python -m eval.compare BASE.json OTHER.json [BASE2.json OTHER2.json ...]

Each pair must come from the same questions (for example `qa-2026-09-20.json` without reranking
and `qa-2026-09-20-rerank.json` with it). Pairs are pooled, so v1 and v2 questions can be judged
together: more questions is the only honest way to see a small effect. Everything printed is
computed from the runs' own result files; nothing is entered by hand.
"""

import argparse
import json
import statistics
import sys
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path

from eval.metrics import sign_test_p, wilson_interval

Record = Mapping[str, object]
# (label, which records count, what counts as success)
METRICS: list[tuple[str, Callable[[Record], bool], Callable[[Record], bool]]] = [
    (
        "answerable: correct (a refusal counts as wrong)",
        lambda r: r["kind"] == "answerable",
        lambda r: bool(r["correct"]),
    ),
    (
        "answerable: a cited source is correct",
        lambda r: r["kind"] == "answerable",
        lambda r: bool(r["citation_any"]),
    ),
    (
        "unanswerable: refused (correct behaviour)",
        lambda r: r["kind"] != "answerable",
        lambda r: bool(r["refused"]),
    ),
    (
        "near-miss unanswerable: refused",
        lambda r: r["kind"] == "near",
        lambda r: bool(r["refused"]),
    ),
]


@dataclass
class Outcome:
    n: int = 0
    base_ok: int = 0
    other_ok: int = 0
    gained: int = 0  # right only in the second run
    lost: int = 0  # right only in the first run

    def add(self, more: "Outcome") -> None:
        self.n += more.n
        self.base_ok += more.base_ok
        self.other_ok += more.other_ok
        self.gained += more.gained
        self.lost += more.lost


def paired_outcomes(
    base: list[Record],
    other: list[Record],
    counts: Callable[[Record], bool],
    success: Callable[[Record], bool],
) -> Outcome:
    """Tally over the questions both runs answered without error and that `counts` selects."""
    other_by_id = {str(r["id"]): r for r in other}
    result = Outcome()
    for b in base:
        o = other_by_id.get(str(b["id"]))
        if o is None or not counts(b) or b.get("error") or o.get("error"):
            continue
        b_right, o_right = success(b), success(o)
        result.n += 1
        result.base_ok += b_right
        result.other_ok += o_right
        result.gained += o_right and not b_right
        result.lost += b_right and not o_right
    return result


def compare(pairs: list[tuple[list[Record], list[Record]]]) -> str:
    out = [
        "# Paired comparison of two QA runs",
        "",
        f"Pooled over {len(pairs)} question set(s). 'gained' = right only in the second run, "
        "'lost' = right only in the first. The sign test asks whether the gained/lost split "
        "could be luck.",
        "",
        "| metric | n | first | second | gained | lost | sign-test p |",
        "|---|---|---|---|---|---|---|",
    ]
    for label, counts, success in METRICS:
        total = Outcome()
        for base, other in pairs:
            total.add(paired_outcomes(base, other, counts, success))
        n = total.n
        if n == 0:
            out.append(f"| {label} | 0 | n/a | n/a | | | |")
            continue

        def cell(k: int, total: int = n) -> str:
            lo, hi = wilson_interval(k, total)
            return f"{k}/{total} ({100 * lo:.0f}-{100 * hi:.0f}%)"

        out.append(
            f"| {label} | {n} | {cell(total.base_ok)} | {cell(total.other_ok)} | "
            f"{total.gained} | {total.lost} | {sign_test_p(total.gained, total.lost):.3f} |"
        )
    lat = [
        (
            statistics.median(float(r["latency_ms"]) for r in base if r.get("latency_ms")),
            statistics.median(float(r["latency_ms"]) for r in other if r.get("latency_ms")),
        )
        for base, other in pairs
    ]
    out += ["", "Median latency per set (first -> second), seconds: "]
    out[-1] += ", ".join(f"{a / 1000:.1f} -> {b / 1000:.1f}" for a, b in lat)
    out += [
        "",
        "Intervals are 95% Wilson. A p above 0.05 means the difference is within what luck "
        "produces at this sample size, which is not the same as showing there is no difference.",
    ]
    return "\n".join(out) + "\n"


def load_records(path: Path) -> list[Record]:
    return list(json.loads(path.read_text(encoding="utf-8"))["records"])


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("files", nargs="+", type=Path, help="BASE OTHER [BASE OTHER ...]")
    parser.add_argument("--out", type=Path, help="also write the report to this file")
    args = parser.parse_args()
    if len(args.files) % 2:
        sys.exit("Give files in pairs: BASE OTHER [BASE OTHER ...]")
    pairs = [
        (load_records(args.files[i]), load_records(args.files[i + 1]))
        for i in range(0, len(args.files), 2)
    ]
    report = compare(pairs)
    print(report)
    if args.out:
        args.out.write_text(report, encoding="utf-8")


if __name__ == "__main__":
    main()
