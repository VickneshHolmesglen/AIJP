"""Does reranking help? Retrieval with and without the LLM reranker, on the M6 question set.

    uv run python -m eval.rerank

Protocol, fixed BEFORE the first run: the reranker prompt and the candidate pool (top 10) are not
tuned on these questions. This file is run as-is and its report published whatever it says. If the
prompt is changed afterwards, the old questions are spent: new ones must be written to judge it,
otherwise the improvement measured would be the prompt fitting this set, not reranking helping.

Each base mode (vector, hybrid) is run once and its top 10 are reranked, so every comparison is
paired on identical candidates and recall@10 cannot change (reranking only reorders). Uses the
scratch database like eval.retrieval and refuses to touch the dev one.
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

from app import retrieval, services
from app.config import Settings
from app.db import init_db
from app.embeddings import OllamaEmbedder
from app.llm import Completion, LLMProvider, OllamaLLM
from app.models import Chunk
from app.rerank import LLMReranker, safe_rerank
from eval.common import dataset_tag
from eval.metrics import (
    Retrieved,
    mean_reciprocal_rank,
    paired_comparison,
    recall_at_k,
    sign_test_p,
)
from eval.retrieval import (
    DEFAULT_DB,
    ROOT,
    check_labels,
    ingest_corpus,
    load_dataset,
    rank_of_question,
)

BASES: list[retrieval.RetrievalMode] = ["vector", "hybrid"]
KS = (1, 3, 5, 10)
POOL = 10  # candidates handed to the reranker; also the depth measured (see module docstring)


class CountingLLM:
    """Wraps a provider to total the tokens the reranker spends."""

    def __init__(self, inner: LLMProvider) -> None:
        self._inner = inner
        self.prompt_tokens = 0
        self.completion_tokens = 0

    def generate(self, system: str, user: str) -> Completion:
        completion = self._inner.generate(system, user)
        self.prompt_tokens += completion.prompt_tokens or 0
        self.completion_tokens += completion.completion_tokens or 0
        return completion


def fmt(x: float) -> str:
    return f"{x:.3f}"


def rank_of(hits: list[retrieval.Hit], question: dict) -> int | None:
    got: list[Retrieved] = [(h.document.source_path, h.chunk.section) for h in hits]
    return rank_of_question(got, question)


def run(
    session: Session,
    embedder: OllamaEmbedder,
    reranker: LLMReranker,
    questions: list[dict],
    settings: Settings,
) -> dict:
    out: dict = {}
    for mode in BASES:
        before: list[int | None] = []
        after: list[int | None] = []
        base_ms: list[float] = []
        rerank_ms: list[float] = []
        fallbacks: list[str] = []
        for q in questions:
            t0 = time.perf_counter()
            hits = retrieval.search(
                session,
                embedder,
                q["question"],
                mode=mode,
                top_k=POOL,
                pool=settings.retrieval_pool,
                rrf_k=settings.rrf_k,
                project_id=None,  # the scratch database holds a single project
            )
            base_ms.append((time.perf_counter() - t0) * 1000)
            t1 = time.perf_counter()
            reranked, ok = safe_rerank(reranker, q["question"], hits)
            rerank_ms.append((time.perf_counter() - t1) * 1000)
            if not ok:
                fallbacks.append(q["id"])
            before.append(rank_of(hits, q))
            after.append(rank_of(reranked, q))
            print(f"  {mode} {q['id']}: {before[-1]} -> {after[-1]} ({rerank_ms[-1] / 1000:.1f}s)")
        out[mode] = {
            "before": before,
            "after": after,
            "base_ms": base_ms,
            "rerank_ms": rerank_ms,
            "fallbacks": fallbacks,
        }
    return out


def build_report(questions: list[dict], results: dict, meta: dict[str, str]) -> str:
    out = ["# Reranking benchmark", ""] + [f"- {k}: {v}" for k, v in meta.items()] + [""]
    out += [
        "## Overall",
        "",
        "| arm | " + " | ".join(f"recall@{k}" for k in KS) + " | MRR@10 | extra latency (ms) |",
        "|---|" + "---|" * (len(KS) + 2),
    ]
    for mode in BASES:
        r = results[mode]
        for label, ranks, extra in (
            (mode, r["before"], "0"),
            (f"{mode} + rerank", r["after"], f"{statistics.fmean(r['rerank_ms']):.0f}"),
        ):
            cells = [fmt(recall_at_k(ranks, k)) for k in KS]
            out.append(
                f"| {label} | " + " | ".join(cells) + f" | {fmt(mean_reciprocal_rank(ranks))} "
                f"| {extra} |"
            )
    out += [
        "",
        "recall@10 is identical by construction: the reranker only reorders the top 10.",
        "",
    ]

    out += ["## Paired comparison (rank of first correct chunk, rerank vs the same base)", ""]
    out += [
        "| base | better | worse | tied | sign-test p | reranker fallbacks |",
        "|---|---|---|---|---|---|",
    ]
    for mode in BASES:
        r = results[mode]
        b, w, t = paired_comparison(r["before"], r["after"])
        out.append(
            f"| {mode} | {b} | {w} | {t} | {sign_test_p(b, w):.3f} | {len(r['fallbacks'])} |"
        )

    out += ["", "## By question kind (MRR@10 before -> after)", ""]
    out += ["| kind | n | " + " | ".join(BASES) + " |", "|---|---|" + "---|" * len(BASES)]
    for kind in dict.fromkeys(q["kind"] for q in questions):
        idx = [i for i, q in enumerate(questions) if q["kind"] == kind]
        cells = []
        for mode in BASES:
            b = mean_reciprocal_rank([results[mode]["before"][i] for i in idx])
            a = mean_reciprocal_rank([results[mode]["after"][i] for i in idx])
            cells.append(f"{fmt(b)} -> {fmt(a)}")
        out.append(f"| {kind} | {len(idx)} | " + " | ".join(cells) + " |")

    out += ["", "## Questions whose rank changed", ""]
    out += ["| id | question | " + " | ".join(BASES) + " |", "|---|---|" + "---|" * len(BASES)]
    for i, q in enumerate(questions):
        cells = []
        changed = False
        for mode in BASES:
            b, a = results[mode]["before"][i], results[mode]["after"][i]
            changed = changed or b != a
            cells.append(f"{b or 'miss'} -> {a or 'miss'}" if b != a else "same")
        if changed:
            out.append(f"| {q['id']} | {q['question']} | " + " | ".join(cells) + " |")

    out += [
        "",
        "## Caveats",
        "",
        f"- {len(questions)} questions over a small synthetic corpus written by the project "
        "author; a difference of one or two questions is noise. Read the paired table.",
        "- The prompt and pool size were fixed before this run and not tuned on these questions.",
        "- The reranker is the same local model that answers questions. Its grades are graded "
        "against labels that were written by hand, not by any model.",
        "- Latency is one local model call on this machine's hardware, measured in isolation.",
    ]
    return "\n".join(out) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, default=ROOT / "datasets" / "retrieval.json")
    parser.add_argument("--corpus", type=Path, default=ROOT / "corpus")
    parser.add_argument("--out-dir", type=Path, default=ROOT / "results")
    parser.add_argument("--limit", type=int, default=None, help="only the first N questions")
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
    llm = CountingLLM(OllamaLLM(settings.ollama_base_url, settings.llm_model))
    questions = load_dataset(args.dataset)[: args.limit]

    with Session(engine) as session:
        n_files = ingest_corpus(session, args.corpus, settings)
        services.embed_pending_chunks(
            session, embedder, settings.embed_batch_size, section_path=settings.embed_section_path
        )
        n_chunks = session.scalar(select(func.count()).select_from(Chunk)) or 0
        check_labels(session, questions)
        print(f"Ingested {n_files} files, {n_chunks} chunks.")
        results = run(session, embedder, LLMReranker(llm), questions, settings)

    calls = sum(len(results[m]["rerank_ms"]) for m in BASES)
    meta = {
        "date": date.today().isoformat(),
        "corpus": f"{n_files} files, {n_chunks} chunks (eval/corpus)",
        "questions": str(len(questions)),
        "reranker": f"{settings.llm_model}, one call grading the top {POOL} 0-3",
        "embedding model": settings.embedding_model,
        "tokens per rerank call": (
            f"{llm.prompt_tokens // max(calls, 1)} prompt + "
            f"{llm.completion_tokens // max(calls, 1)} completion (mean)"
        ),
        "platform": platform.platform(),
    }
    report = build_report(questions, results, meta)
    args.out_dir.mkdir(parents=True, exist_ok=True)
    stem = f"rerank{dataset_tag(args.dataset, 'retrieval')}-{meta['date']}" + (
        "-smoke" if args.limit else ""
    )
    (args.out_dir / f"{stem}.md").write_text(report, encoding="utf-8")
    (args.out_dir / f"{stem}.json").write_text(
        json.dumps({"meta": meta, "results": results}, indent=2), encoding="utf-8"
    )
    print("\n" + report)
    print(f"Wrote {args.out_dir / (stem + '.md')}")


if __name__ == "__main__":
    main()
