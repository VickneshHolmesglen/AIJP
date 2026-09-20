"""Evaluation of the design-vs-code consistency check on a corpus with SEEDED discrepancies.

    uv run python -m eval.consistency            # full run (~16 claims, real local model)
    uv run python -m eval.consistency --limit 3  # smoke run

The corpus is eval/corpus with eval/seeded_patches overlaid: six deliberate mismatches were
introduced into code/config while the design docs stay untouched (see the dataset for the list).
The runner never approves the drafted actions: it measures the check, not the approval gate.
Every number in the report comes from this run.
"""

import argparse
import json
import os
import platform
import shutil
import statistics
import sys
import tempfile
import time
from dataclasses import asdict, dataclass, field
from datetime import date
from pathlib import Path

from sqlalchemy import create_engine, func, select
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from app import services
from app.agent.consistency import run_consistency_check
from app.config import Settings
from app.db import init_db
from app.embeddings import OllamaEmbedder
from app.llm import OllamaLLM
from app.models import Chunk, Document
from app.presenters import to_run_detail
from eval.common import dataset_tag
from eval.metrics import confusion_matrix, gate_sweep, percentile
from eval.retrieval import DEFAULT_DB, ingest_corpus

ROOT = Path(__file__).parent
VERDICTS = ["potential_discrepancy", "consistent", "insufficient_evidence"]
THRESHOLDS = [round(0.30 + 0.05 * i, 2) for i in range(11)]  # 0.30 .. 0.80


@dataclass
class Record:
    id: str
    kind: str  # seeded | consistent | unsupported
    claim: str
    expected: str
    verdict: str | None = None
    status: str | None = None
    downgrade_reason: str | None = None
    explanation: str | None = None
    design_cited: list[str] = field(default_factory=list)
    implementation_cited: list[str] = field(default_factory=list)
    evidence_ok: bool | None = None  # cited a correct source on BOTH sides (labelled claims only)
    design_best: float | None = None
    implementation_best: float | None = None
    symbol_matches: int = 0
    action_drafted: bool = False
    latency_ms: float = 0.0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    error: str | None = None


def row(label: str, value: str) -> str:
    return f"| {label} | {value} |"


def pct(x: float) -> str:
    return f"{100 * x:.1f}%"


def ratio(n: int, d: int) -> str:
    return f"{pct(n / d)} ({n}/{d})" if d else "n/a"


def build_corpus(dest: Path, patches_dir: str = "seeded_patches") -> list[str]:
    """Base corpus + a seeded-patch overlay. Returns the patched relative paths."""
    overlay = ROOT / patches_dir
    shutil.copytree(ROOT / "corpus", dest, dirs_exist_ok=True)
    patched = sorted(p.relative_to(overlay).as_posix() for p in overlay.rglob("*") if p.is_file())
    shutil.copytree(overlay, dest, dirs_exist_ok=True)
    return patched


def check_labels(session: Session, claims: list[dict]) -> None:
    paths = set(session.scalars(select(Document.source_path)))
    bad = sorted({p for c in claims for p in c["design"] + c["implementation"] if p not in paths})
    if bad:
        sys.exit(f"Dataset labels name files that are not in the corpus: {bad}")


def evaluate(record: Record, claim: dict, detail) -> None:
    record.status, record.verdict = detail.status, detail.verdict
    record.error = detail.error
    if detail.result is None:
        return
    r = detail.result
    record.downgrade_reason = r.downgrade_reason
    record.explanation = r.explanation
    record.design_cited = sorted({e.path for e in r.design_evidence if e.cited})
    record.implementation_cited = sorted({e.path for e in r.implementation_evidence if e.cited})
    record.action_drafted = bool(detail.actions)
    record.prompt_tokens, record.completion_tokens = (
        r.usage.prompt_tokens,
        r.usage.completion_tokens,
    )
    if claim["design"] and claim["implementation"]:
        record.evidence_ok = bool(
            set(record.design_cited) & set(claim["design"])
            and set(record.implementation_cited) & set(claim["implementation"])
        )
    gate = next((s for s in detail.steps if s.name == "evidence_gate"), None)
    if gate:
        record.design_best = gate.output.get("design_best_cosine")
        record.implementation_best = gate.output.get("implementation_best_cosine")
        record.symbol_matches = gate.output.get("symbol_matches", 0)


def build_report(records: list[Record], meta: dict[str, str], patched: list[str]) -> str:
    ok = [r for r in records if r.error is None]
    errored = [r for r in records if r.error is not None]
    seeded = [r for r in ok if r.kind == "seeded"]
    consistent = [r for r in ok if r.kind == "consistent"]
    unsupported = [r for r in ok if r.kind == "unsupported"]
    out = ["# Design-vs-code consistency evaluation", ""]
    out += [f"- {k}: {v}" for k, v in meta.items()]
    out += [f"- patched files: {', '.join(patched)}", ""]
    if errored:
        out += [
            f"**{len(errored)} claim(s) errored and are excluded:** "
            + ", ".join(r.id for r in errored),
            "",
        ]

    def hit(group: list[Record], verdict: str) -> int:
        return sum(r.verdict == verdict for r in group)

    n_found = hit(seeded, "potential_discrepancy")
    n_alarm = hit(consistent, "potential_discrepancy")
    n_confirmed = hit(consistent, "consistent")
    n_undecided = hit(unsupported, "insufficient_evidence")
    labelled = [r for r in ok if r.evidence_ok is not None and r.verdict != "insufficient_evidence"]
    n_cited = sum(bool(r.evidence_ok) for r in labelled)
    n_right = sum(r.verdict == r.expected for r in ok)

    out += ["## Headline", "", "| metric | value |", "|---|---|"]
    out.append(row("seeded discrepancies found (recall)", ratio(n_found, len(seeded))))
    out.append(row("false alarms on consistent claims", ratio(n_alarm, len(consistent))))
    out.append(row("consistent claims confirmed", ratio(n_confirmed, len(consistent))))
    out.append(row("unsupported claims left undecided", ratio(n_undecided, len(unsupported))))
    out.append(
        row(
            "unsupported claims given a verdict anyway",
            ratio(len(unsupported) - n_undecided, len(unsupported)),
        )
    )
    out.append(row("verdicts citing a correct source on both sides", ratio(n_cited, len(labelled))))
    out.append(row("overall verdict accuracy", ratio(n_right, len(ok))))

    pairs = [(r.expected, r.verdict or "none") for r in ok]
    labels = [*VERDICTS, "none"]
    matrix = confusion_matrix(pairs, labels)
    out += ["", "## Confusion matrix (rows: expected, columns: got)", ""]
    out += ["| expected \\ got | " + " | ".join(VERDICTS) + " |", "|---|" + "---|" * len(VERDICTS)]
    for e in VERDICTS:
        out.append(f"| {e} | " + " | ".join(str(matrix[(e, g)]) for g in VERDICTS) + " |")

    reasons: dict[str, int] = {}
    for r in ok:
        if r.downgrade_reason:
            reasons[r.downgrade_reason] = reasons.get(r.downgrade_reason, 0) + 1
    out += [
        "",
        "Downgrades: " + (", ".join(f"{k} = {v}" for k, v in sorted(reasons.items())) or "none"),
        "",
    ]
    drafted = sum(r.action_drafted for r in ok)
    out += [
        f"Tasks drafted (this runner never approves them): {drafted}, one per discrepancy "
        "that survived validation.",
        "",
    ]

    misses = [r for r in ok if r.verdict != r.expected]
    if misses:
        out += ["## Where the check disagreed with the label", ""]
        for r in misses:
            out.append(
                f"- `{r.id}` ({r.kind}) expected {r.expected}, got {r.verdict}"
                f"{' [' + r.downgrade_reason + ']' if r.downgrade_reason else ''}: {r.claim}"
            )
            if r.explanation:
                out.append(f"  - model: {r.explanation}")
        out.append("")

    lat = [r.latency_ms / 1000 for r in ok]
    called = [r for r in ok if r.prompt_tokens or r.completion_tokens]
    out += ["## Latency and tokens", "", "| metric | value |", "|---|---|"]
    out.append(f"| median latency | {percentile(lat, 50):.1f} s |")
    out.append(f"| p95 latency | {percentile(lat, 95):.1f} s |")
    out.append(f"| runs that consulted the model | {ratio(len(called), len(ok))} |")
    if called:
        mean_tokens = statistics.fmean(r.prompt_tokens + r.completion_tokens for r in called)
        out.append(row("mean tokens per model call", f"{mean_tokens:.0f}"))
    out.append("")

    def weakest(r: Record) -> float | None:
        sides = [r.design_best, r.implementation_best]
        return None if any(s is None for s in sides) else min(sides)  # type: ignore[type-var]

    out += [
        "## Evidence-gate calibration",
        "",
        "Each side's best cosine must reach the threshold (a symbol found by name also counts for "
        "the implementation side). Here: the weaker of the two sides, for claims that HAVE "
        "evidence (seeded + consistent) versus claims that do not (unsupported).",
        "",
        "| threshold | with-evidence let through | unsupported blocked |",
        "|---|---|---|",
    ]
    with_ev = [weakest(r) for r in seeded + consistent]
    without = [weakest(r) for r in unsupported]
    if with_ev and without:
        current = float(meta["consistency_min_cosine"])
        for t, passed, blocked in gate_sweep(with_ev, without, THRESHOLDS):
            mark = "  <- current default" if abs(t - current) < 1e-9 else ""
            out.append(f"| {t:.2f} | {pct(passed)} | {pct(blocked)}{mark} |")
    out += [
        "",
        "## Caveats",
        "",
        f"- {len(ok)} claims over a small synthetic corpus, written by the project author, who "
        "also chose where to seed the mismatches. Treat small differences as noise.",
        "- Seeded mismatches are mostly changed numbers, which are easier to spot than subtle "
        "behavioural differences; only one (poison replacing instead of stacking) is behavioural.",
        "- The same local model that judges here also answers questions elsewhere.",
        "- A verdict is triage from retrieved passages, not proof of program behaviour.",
    ]
    return "\n".join(out) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, default=ROOT / "datasets" / "consistency.json")
    parser.add_argument("--out-dir", type=Path, default=ROOT / "results")
    parser.add_argument(
        "--limit", type=int, help="only the first N claims of each kind (smoke run)"
    )
    args = parser.parse_args()

    db_url = os.environ.get("AIJP_EVAL_DATABASE_URL", DEFAULT_DB)
    if make_url(db_url).database == "aijp":
        sys.exit("Refusing to wipe the dev database 'aijp'. Set AIJP_EVAL_DATABASE_URL.")

    settings = Settings()
    engine = create_engine(db_url)
    init_db(engine)
    embedder = OllamaEmbedder(
        settings.ollama_base_url, settings.embedding_model, settings.embedding_dim
    )
    llm = OllamaLLM(settings.ollama_base_url, settings.llm_model)
    data = json.loads(args.dataset.read_text("utf-8"))
    claims = data["claims"]
    if args.limit:
        claims = [
            c
            for kind in ("seeded", "consistent", "unsupported")
            for c in [x for x in claims if x["kind"] == kind][: args.limit]
        ]

    with tempfile.TemporaryDirectory() as tmp, Session(engine) as session:
        patched = build_corpus(Path(tmp) / "corpus", data.get("patches_dir", "seeded_patches"))
        n_files = ingest_corpus(session, Path(tmp) / "corpus", settings)
        services.embed_pending_chunks(session, embedder, settings.embed_batch_size)
        n_chunks = session.scalar(select(func.count()).select_from(Chunk)) or 0
        check_labels(session, claims)
        print(f"Ingested {n_files} files ({len(patched)} patched), {n_chunks} chunks.")

        records = []
        for n, claim in enumerate(claims, start=1):
            rec = Record(claim["id"], claim["kind"], claim["claim"], claim["expected"])
            start = time.perf_counter()
            run = run_consistency_check(session, embedder, llm, settings, claim["claim"])
            rec.latency_ms = (time.perf_counter() - start) * 1000
            evaluate(rec, claim, to_run_detail(run))
            secs = rec.latency_ms / 1000
            print(f"[{n}/{len(claims)}] {rec.id} {rec.kind}: {rec.verdict} ({secs:.1f}s)")
            records.append(rec)

    meta = {
        "date": date.today().isoformat(),
        "corpus": (
            f"{n_files} files, {n_chunks} chunks "
            f"(eval/corpus + eval/{data.get('patches_dir', 'seeded_patches')})"
        ),
        "claims": f"{len(claims)}",
        "retrieval mode": settings.retrieval_mode,
        "passages per side": str(settings.consistency_top_k),
        "consistency_min_cosine": str(settings.consistency_min_cosine),
        "embedding model": settings.embedding_model,
        "judge model": settings.llm_model,
        "platform": platform.platform(),
    }
    report = build_report(records, meta, patched)
    args.out_dir.mkdir(parents=True, exist_ok=True)
    stem = f"consistency{dataset_tag(args.dataset, 'consistency')}-{meta['date']}" + (
        "-smoke" if args.limit else ""
    )
    (args.out_dir / f"{stem}.md").write_text(report, encoding="utf-8")
    (args.out_dir / f"{stem}.json").write_text(
        json.dumps({"meta": meta, "records": [asdict(r) for r in records]}, indent=2),
        encoding="utf-8",
    )
    print("\n" + report)
    print(f"Wrote {args.out_dir / (stem + '.md')}")


if __name__ == "__main__":
    main()
