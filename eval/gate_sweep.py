"""Pooled evidence-gate sweep for the consistency check, from existing result files.

    uv run python -m eval.gate_sweep RESULT.json [RESULT.json ...] [--out report.md]

The gate lets a claim reach the judge only if the best design passage AND the best implementation
passage (or a symbol match) reach a cosine threshold. This pools the per-claim cosines recorded by
`eval.consistency` across question sets and shows, for each threshold, how many claims WITH real
evidence still get through and how many UNSUPPORTED claims are blocked, with confidence intervals.
Nothing is re-run: every number comes from the result files.

Pass each claim set ONCE (any judge variant's file for that set is fine: the cosines come from
retrieval, not from the judge).
"""

import argparse
import json
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path

from eval.metrics import wilson_interval

Record = Mapping[str, object]
THRESHOLDS = [round(0.30 + 0.05 * i, 2) for i in range(11)]  # 0.30 .. 0.80


def passes(record: Record, threshold: float) -> bool:
    """Would the gate let this claim through at `threshold`? Mirrors the workflow: a symbol found in
    the code counts as implementation evidence regardless of its cosine."""
    design, impl = record.get("design_best"), record.get("implementation_best")
    design_ok = isinstance(design, int | float) and design >= threshold
    impl_ok = bool(record.get("symbol_matches")) or (
        isinstance(impl, int | float) and impl >= threshold
    )
    return design_ok and impl_ok


def sweep(
    records: Sequence[Record], thresholds: Sequence[float] = THRESHOLDS
) -> list[tuple[float, int, int, int, int]]:
    """Per threshold: (t, with-evidence let through, with-evidence total, unsupported blocked,
    unsupported total). "With evidence" = the seeded and consistent claims."""
    real = [r for r in records if r["kind"] in ("seeded", "consistent")]
    unsupported = [r for r in records if r["kind"] == "unsupported"]
    return [
        (
            t,
            sum(passes(r, t) for r in real),
            len(real),
            sum(not passes(r, t) for r in unsupported),
            len(unsupported),
        )
        for t in thresholds
    ]


def _cell(k: int, n: int) -> str:
    lo, hi = wilson_interval(k, n)
    return f"{100 * k / n:.0f}% ({k}/{n}; {100 * lo:.0f}-{100 * hi:.0f}%)"


def report(records: Sequence[Record], current: float, sources: Sequence[str]) -> str:
    rows = sweep(records)
    out = [
        "# Consistency gate: pooled sweep",
        "",
        f"Pooled from: {', '.join(sources)}.",
        "",
        "| threshold | claims with evidence let through | unsupported claims blocked |",
        "|---|---|---|",
    ]
    for t, through, real, blocked, unsupported in rows:
        mark = "  <- current default" if abs(t - current) < 1e-9 else ""
        out.append(f"| {t:.2f} | {_cell(through, real)} | {_cell(blocked, unsupported)}{mark} |")
    out += [
        "",
        "A higher threshold blocks more unsupported claims but starts losing real ones. The "
        "unsupported set is small and half of it is on-topic near-misses, which score high "
        "because they are about the right subject; a cosine gate cannot tell 'about the right "
        "subject' from 'contains the answer'. Read the intervals: with about a dozen unsupported "
        "claims a difference of one or two is noise.",
    ]
    return "\n".join(out) + "\n"


def load(paths: Sequence[Path]) -> list[Record]:
    records: list[Record] = []
    for path in paths:
        records += json.loads(path.read_text(encoding="utf-8"))["records"]
    return records


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("files", nargs="+", type=Path)
    parser.add_argument("--current", type=float, default=0.60, help="threshold to mark")
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    if not all(p.exists() for p in args.files):
        sys.exit("A result file does not exist.")
    text = report(load(args.files), args.current, [p.name for p in args.files])
    print(text)
    if args.out:
        args.out.write_text(text, encoding="utf-8")


if __name__ == "__main__":
    main()
