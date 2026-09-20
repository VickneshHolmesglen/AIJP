"""Retrieval benchmark: vector vs lexical vs hybrid on a labelled question set.

    uv run python -m eval.retrieval

Ingests eval/corpus into a scratch database (default: the *test* database, never the dev one),
embeds it with the real embedding model, runs every question in every mode and writes a report to
eval/results/. Every number in that report comes from this run; nothing is hand-edited.
"""

import argparse
import json
import os
import platform
import statistics
import sys
import time
from datetime import date
from pathlib import Path

from sqlalchemy import create_engine, func, select
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from app import projects, retrieval, services
from app.config import Settings
from app.db import init_db
from app.embeddings import OllamaEmbedder
from app.ingestion.errors import IngestionError
from app.models import Base, Chunk, Document
from eval.common import dataset_tag
from eval.metrics import (
    Expected,
    Retrieved,
    first_hit_rank,
    full_coverage_rank,
    mean_reciprocal_rank,
    paired_comparison,
    recall_at_k,
    sign_test_p,
)

ROOT = Path(__file__).parent
MODES: list[retrieval.RetrievalMode] = ["vector", "lexical", "hybrid"]
KS = (1, 3, 5, 10)
DEFAULT_DB = "postgresql+psycopg://aijp:aijp@127.0.0.1:5432/aijp_test"


def load_dataset(path: Path) -> list[dict]:
    return json.loads(path.read_text(encoding="utf-8"))["questions"]


def expected_of(question: dict) -> list[Expected]:
    return [Expected(**e) for e in question["expected"]]


def rank_of_question(got: list[Retrieved], question: dict) -> int | None:
    """Rank the retrieval is credited with: any expected source, or, for a question marked
    `"require_all": true` (multi-hop), the rank by which all of them have appeared."""
    expected = expected_of(question)
    if question.get("require_all"):
        return full_coverage_rank(got, expected)
    return first_hit_rank(got, expected)


def ingest_corpus(session: Session, corpus: Path, settings: Settings) -> int:
    for table in reversed(Base.metadata.sorted_tables):
        session.execute(table.delete())
    session.commit()
    project_id = projects.get_or_create_default(session).id  # scratch DB: exactly one project
    count = 0
    for file in sorted(p for p in corpus.rglob("*") if p.is_file()):
        rel = file.relative_to(corpus).as_posix()
        try:
            services.ingest_document(
                session,
                project_id=project_id,
                raw_filename=file.name,
                content=file.read_bytes(),
                source_path=rel,
                settings=settings,
            )
        except IngestionError as exc:
            sys.exit(f"Could not ingest corpus file {rel}: {exc}")
        count += 1
    return count


def check_labels(session: Session, questions: list[dict]) -> None:
    """Every expected source must match at least one real chunk, or the label is a typo and would
    silently depress every mode's score."""
    chunks: list[Retrieved] = [
        (path, section)
        for path, section in session.execute(
            select(Document.source_path, Chunk.section).join(
                Chunk, Chunk.document_id == Document.id
            )
        ).all()
    ]
    bad = [
        f"{q['id']}: {e}"
        for q in questions
        for e in expected_of(q)
        if first_hit_rank(chunks, [e]) is None
    ]
    if bad:
        sys.exit("Dataset labels match no chunk in the corpus:\n  " + "\n  ".join(bad))


def run_mode(
    session: Session,
    embedder: OllamaEmbedder,
    questions: list[dict],
    mode: retrieval.RetrievalMode,
    settings: Settings,
    top_k: int,
) -> tuple[list[int | None], list[float], list[list[Retrieved]]]:
    ranks: list[int | None] = []
    latencies: list[float] = []
    returned: list[list[Retrieved]] = []
    for q in questions:
        start = time.perf_counter()
        hits = retrieval.search(
            session,
            embedder,
            q["question"],
            mode=mode,
            top_k=top_k,
            pool=settings.retrieval_pool,
            rrf_k=settings.rrf_k,
            project_id=None,  # the scratch database holds a single project
        )
        latencies.append((time.perf_counter() - start) * 1000)
        got = [(h.document.source_path, h.chunk.section) for h in hits]
        returned.append(got)
        ranks.append(rank_of_question(got, q))
    return ranks, latencies, returned


def fmt(x: float) -> str:
    return f"{x:.3f}"


def build_report(
    questions: list[dict],
    results: dict[str, tuple[list[int | None], list[float], list[list[Retrieved]]]],
    meta: dict[str, str],
) -> str:
    n = len(questions)
    out = ["# Retrieval benchmark", ""]
    out += [f"- {k}: {v}" for k, v in meta.items()] + [""]
    out += [
        "## Overall",
        "",
        "| mode | " + " | ".join(f"recall@{k}" for k in KS) + " | MRR@10 | mean latency (ms) |",
    ]
    out += ["|---|" + "---|" * (len(KS) + 2)]
    for mode in MODES:
        ranks, lat, _ = results[mode]
        cells = [fmt(recall_at_k(ranks, k)) for k in KS]
        out.append(
            f"| {mode} | " + " | ".join(cells) + f" | {fmt(mean_reciprocal_rank(ranks))} | "
            f"{statistics.fmean(lat):.0f} |"
        )
    out += ["", "Latency includes embedding the query (same cost in every mode).", ""]

    out += [
        "## By question kind (recall@3 / MRR@10)",
        "",
        "| kind | n | " + " | ".join(MODES) + " |",
    ]
    out += ["|---|---|" + "---|" * len(MODES)]
    for kind in dict.fromkeys(q["kind"] for q in questions):
        idx = [i for i, q in enumerate(questions) if q["kind"] == kind]
        cells = []
        for mode in MODES:
            ranks = [results[mode][0][i] for i in idx]
            cells.append(f"{fmt(recall_at_k(ranks, 3))} / {fmt(mean_reciprocal_rank(ranks))}")
        out.append(f"| {kind} | {len(idx)} | " + " | ".join(cells) + " |")

    out += ["", "## Paired comparison against vector-only (by rank of first correct chunk)", ""]
    out += ["| mode | better | worse | tied | sign-test p |", "|---|---|---|---|---|"]
    for mode in ("lexical", "hybrid"):
        b, w, t = paired_comparison(results["vector"][0], results[mode][0])
        out.append(f"| {mode} | {b} | {w} | {t} | {sign_test_p(b, w):.3f} |")

    out += ["", "## Questions where the modes disagree", ""]
    out += ["| id | question | vector | lexical | hybrid |", "|---|---|---|---|---|"]
    for i, q in enumerate(questions):
        ranks = [results[m][0][i] for m in MODES]
        if len(set(ranks)) > 1:
            cells = [str(r) if r is not None else "miss" for r in ranks]
            out.append(f"| {q['id']} | {q['question']} | " + " | ".join(cells) + " |")

    out += [
        "",
        "## Caveats",
        "",
        f"- {n} questions over a small synthetic corpus written by the project author. Treat "
        "differences of a few points as noise; the paired table shows how broad any gain is.",
        "- Ranks are of the first *correct* chunk; a cell of `miss` means none in the top 10.",
        "- Thresholds and reranking are not evaluated here.",
    ]
    return "\n".join(out) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, default=ROOT / "datasets" / "retrieval.json")
    parser.add_argument("--corpus", type=Path, default=ROOT / "corpus")
    parser.add_argument("--out-dir", type=Path, default=ROOT / "results")
    parser.add_argument("--top-k", type=int, default=10)
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
    questions = load_dataset(args.dataset)

    with Session(engine) as session:
        n_files = ingest_corpus(session, args.corpus, settings)
        embedded = services.embed_pending_chunks(session, embedder, settings.embed_batch_size)
        n_chunks = session.scalar(select(func.count()).select_from(Chunk)) or 0
        check_labels(session, questions)
        print(f"Ingested {n_files} files, {n_chunks} chunks ({embedded} embedded).")
        results = {}
        for mode in MODES:
            print(f"Running {mode}...")
            results[mode] = run_mode(session, embedder, questions, mode, settings, args.top_k)

    meta = {
        "date": date.today().isoformat(),
        "corpus": f"{n_files} files, {n_chunks} chunks (eval/corpus)",
        "questions": str(len(questions)),
        "embedding model": settings.embedding_model,
        "chunking": f"{settings.chunk_max_chars} chars, {settings.chunk_overlap_chars} overlap",
        "hybrid": f"RRF k={settings.rrf_k}, pool={settings.retrieval_pool} per retriever",
        "top_k": str(args.top_k),
        "platform": platform.platform(),
    }
    report = build_report(questions, results, meta)
    args.out_dir.mkdir(parents=True, exist_ok=True)
    stem = f"retrieval{dataset_tag(args.dataset, 'retrieval')}-{meta['date']}"
    (args.out_dir / f"{stem}.md").write_text(report, encoding="utf-8")
    (args.out_dir / f"{stem}.json").write_text(
        json.dumps(
            {
                "meta": meta,
                "per_question": [
                    {"id": q["id"], "kind": q["kind"]} | {m: results[m][0][i] for m in MODES}
                    for i, q in enumerate(questions)
                ],
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    print("\n" + report)
    print(f"Wrote {args.out_dir / (stem + '.md')}")


if __name__ == "__main__":
    main()
