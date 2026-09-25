"""End-to-end answer evaluation: retrieval, answers, citations, refusals, faithfulness, cost.

    uv run python -m eval.qa            # full run (slow: real local LLM, ~50 answers + judging)
    uv run python -m eval.qa --limit 5  # quick smoke run

Uses the same corpus and scratch database as eval.retrieval, the real embedding model and the real
answer model. Every number in the report comes from this run.
"""

import argparse
import json
import os
import platform
import statistics
import sys
import time
from dataclasses import asdict, dataclass, field
from datetime import date
from pathlib import Path

from sqlalchemy import create_engine, func, select
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from app import qa, retrieval, services
from app.config import Settings
from app.db import init_db
from app.embeddings import OllamaEmbedder
from app.llm import LLMError, OllamaLLM
from app.models import Chunk
from app.providers import answer_token_cap
from app.rerank import LLMReranker
from eval.common import dataset_tag
from eval.judge import JudgeValidation, judge_supported, validate_judge
from eval.metrics import (
    Retrieved,
    citation_scores,
    gate_sweep,
    keyword_correct,
    percentile,
    precision_at_k,
    recall_at_k,
    wilson_interval,
)
from eval.retrieval import DEFAULT_DB, check_labels, expected_of, ingest_corpus, rank_of_question

ROOT = Path(__file__).parent
THRESHOLDS = [round(0.30 + 0.05 * i, 2) for i in range(11)]  # 0.30 .. 0.80


@dataclass
class Record:
    id: str
    kind: str  # "answerable" | "far" | "near"
    question: str
    refused: bool = False
    reason: str | None = None
    answer: str | None = None
    correct: bool | None = None  # answerable + answered only
    cited: list[Retrieved] = field(default_factory=list)
    citation_any: bool | None = None
    citation_precision: float | None = None
    retrieval_rank: int | None = None  # answerable only
    precision_at_k: float | None = None  # answerable only
    top_cosine: float | None = None
    latency_ms: float = 0.0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cited_text: str = ""  # the cited chunks' text; what the faithfulness judge sees
    faithful: bool | None = None  # answered only; None also if the judge failed
    escalated: str | None = None  # "used" / "fallback" when the thinking re-check applied
    error: str | None = None


def pct(x: float) -> str:
    return f"{100 * x:.1f}%"


def ratio(n: int, d: int) -> str:
    """'94.4% (34/36, 95% CI 81-98%)': the interval is the honest size of the claim."""
    if not d:
        return "n/a"
    low, high = wilson_interval(n, d)
    return f"{pct(n / d)} ({n}/{d}, 95% CI {100 * low:.0f}-{100 * high:.0f}%)"


def run_question(
    session: Session,
    embedder: OllamaEmbedder,
    llm: OllamaLLM,
    settings: Settings,
    mode: retrieval.RetrievalMode,
    top_k: int,
    min_score: float,
    record: Record,
    escalation_llm: OllamaLLM | None = None,
) -> None:
    for attempt in (1, 2):  # one retry: local models occasionally time out under load
        try:
            start = time.perf_counter()
            result = qa.ask(
                session,
                embedder,
                llm,
                record.question,
                top_k=top_k,
                min_score=min_score,
                mode=mode,
                pool=settings.retrieval_pool,
                rrf_k=settings.rrf_k,
                project_id=None,  # the scratch database holds a single project
                reranker=LLMReranker(llm) if settings.rerank_enabled else None,
                rerank_pool=settings.rerank_pool,
                calculator=settings.ask_calculator,
                escalation=settings.llm_escalation,
                escalation_llm=escalation_llm,
            )
            record.latency_ms = (time.perf_counter() - start) * 1000
            break
        except LLMError as exc:
            if attempt == 2:
                record.error = str(exc)
                return
    record.refused, record.reason, record.answer = result.refused, result.reason, result.answer
    record.escalated = result.escalated
    record.top_cosine = result.top_score
    record.prompt_tokens, record.completion_tokens = result.prompt_tokens, result.completion_tokens
    record.cited = [(e.document.source_path, e.chunk.section) for e in result.sources]
    record.cited_text = "\n\n".join(f"[{e.ref}] {e.chunk.content}" for e in result.sources)


def row(label: str, value: str) -> str:
    return f"| {label} | {value} |"


def count_by_reason(records: list[Record]) -> str:
    counts: dict[str, int] = {}
    for r in records:
        if r.refused and r.reason:
            counts[r.reason] = counts.get(r.reason, 0) + 1
    return ", ".join(f"{k} = {v}" for k, v in sorted(counts.items())) or "none"


def mean_pct(values: list[float]) -> str:
    return pct(statistics.fmean(values)) if values else "n/a"


def build_report(
    records: list[Record],
    validation: JudgeValidation | None,
    meta: dict[str, str],
    prices: tuple[float, float],
) -> str:
    ok = [r for r in records if r.error is None]
    errored = [r for r in records if r.error is not None]
    ans_q = [r for r in ok if r.kind == "answerable"]
    unans = [r for r in ok if r.kind != "answerable"]
    answered = [r for r in ok if not r.refused]
    answered_a = [r for r in ans_q if not r.refused]

    out = ["# Answer-quality evaluation", ""]
    out += [f"- {k}: {v}" for k, v in meta.items()] + [""]
    if errored:
        ids = ", ".join(r.id for r in errored)
        out += [f"**{len(errored)} question(s) errored and are excluded:** {ids}", ""]

    out += ["## Answerable questions", "", "| metric | value |", "|---|---|"]
    ranks = [r.retrieval_rank for r in ans_q]
    for k in (1, 3, 5):
        out.append(row(f"retrieval recall@{k}", pct(recall_at_k(ranks, k))))
    out.append(
        row(
            f"retrieval precision@{meta['top_k']} (mean)",
            mean_pct([r.precision_at_k or 0.0 for r in ans_q]),
        )
    )
    n_correct = sum(bool(r.correct) for r in ans_q)
    n_correct_answered = sum(bool(r.correct) for r in answered_a)
    n_cited_ok = sum(bool(r.citation_any) for r in answered_a)
    out.append(row("answered (not refused)", ratio(len(answered_a), len(ans_q))))
    out.append(row("false refusals", ratio(len(ans_q) - len(answered_a), len(ans_q))))
    out.append(row("correct overall (a refusal counts as wrong)", ratio(n_correct, len(ans_q))))
    out.append(row("correct when answered", ratio(n_correct_answered, len(answered_a))))
    out.append(
        row("citation accuracy (a cited source is correct)", ratio(n_cited_ok, len(answered_a)))
    )
    out.append(
        row(
            "citation precision (mean share of cited sources that are correct)",
            mean_pct([r.citation_precision or 0.0 for r in answered_a]),
        )
    )
    out += ["", f"False-refusal reasons: {count_by_reason(ans_q)}", ""]

    out += ["## Unanswerable questions (correct behaviour = refuse)", ""]
    out += ["| set | refused | answered anyway |", "|---|---|---|"]
    groups = (
        ("all", unans),
        ("far (off-topic)", [r for r in unans if r.kind == "far"]),
        ("near (on-topic, fact absent)", [r for r in unans if r.kind == "near"]),
    )
    for label, group in groups:
        refused = sum(r.refused for r in group)
        out.append(
            f"| {label} | {ratio(refused, len(group))} | "
            f"{ratio(len(group) - refused, len(group))} |"
        )
    out += ["", f"Refusal layer: {count_by_reason(unans)}", ""]

    judged = [r for r in answered if r.faithful is not None]
    unsupported = [r for r in judged if r.faithful is False]
    out += ["## Faithfulness (LLM judge)", "", "| metric | value |", "|---|---|"]
    out.append(row("answers judged", f"{len(judged)} of {len(answered)} answered"))
    out.append(
        row("supported by their cited sources", ratio(len(judged) - len(unsupported), len(judged)))
    )
    out.append(row("**unsupported answer rate**", ratio(len(unsupported), len(judged))))
    if validation is not None:
        v = validation
        flag = "" if v.accuracy >= 0.8 else "  **(below 80%: treat faithfulness as unreliable)**"
        out += [
            "",
            f"Judge validated on {v.total} hand-labelled cases: accuracy {pct(v.accuracy)} "
            f"({v.correct}/{v.total}); approved an unfaithful answer {v.false_supported}x, "
            f"rejected a faithful one {v.false_unsupported}x, unparseable {v.unparseable}x.{flag}",
        ]
    if unsupported:
        out += ["", "Answers the judge marked unsupported:", ""]
        out += [f"- `{r.id}` ({r.kind}): {r.answer}" for r in unsupported]

    lat = [r.latency_ms / 1000 for r in ok]
    llm_calls = [r for r in ok if r.prompt_tokens or r.completion_tokens]
    tokens_in = sum(r.prompt_tokens for r in ok)
    tokens_out = sum(r.completion_tokens for r in ok)
    cost = (tokens_in * prices[0] + tokens_out * prices[1]) / 1_000_000
    out += ["", "## Latency, tokens, cost", "", "| metric | value |", "|---|---|"]
    out.append(row("median latency (retrieval + generation)", f"{percentile(lat, 50):.1f} s"))
    out.append(row("p95 latency", f"{percentile(lat, 95):.1f} s"))
    out.append(row("queries that called the LLM", ratio(len(llm_calls), len(ok))))
    escalated = [r for r in ok if r.escalated]
    if escalated:
        used = sum(r.escalated == "used" for r in escalated)
        out.append(
            row(
                "answers re-checked with thinking",
                f"{ratio(len(escalated), len(ok))}: {used} used, "
                f"{len(escalated) - used} fell back to the first answer",
            )
        )
    if llm_calls:
        mean_in = statistics.fmean(r.prompt_tokens for r in llm_calls)
        mean_out = statistics.fmean(r.completion_tokens for r in llm_calls)
        out.append(row("mean prompt tokens per LLM call", f"{mean_in:.0f}"))
        out.append(row("mean completion tokens per LLM call", f"{mean_out:.0f}"))
    out.append(
        row("mean tokens per query (all queries)", f"{(tokens_in + tokens_out) / len(ok):.0f}")
    )
    out.append(row("estimated cost per query", f"${cost / len(ok):.4f}"))
    out += [
        "",
        "Token counts are as reported by Ollama. Cost = tokens x configured prices "
        f"(${prices[0]}/1M input, ${prices[1]}/1M output). The default of 0 reflects a local "
        "model: $0.0000 means 'free to run locally', not 'cheap in production'.",
        "",
    ]

    out += [
        "## Evidence-gate calibration",
        "",
        "The gate alone: refuse when the best chunk cosine is below the threshold. Shows what each "
        "candidate threshold would let through / block, before the LLM's own judgement.",
        "",
        "| threshold | answerable let through | unanswerable blocked |",
        "|---|---|---|",
    ]
    sweep = gate_sweep([r.top_cosine for r in ans_q], [r.top_cosine for r in unans], THRESHOLDS)
    for t, passed, blocked in sweep:
        mark = "  <- current default" if abs(t - float(meta["min_evidence_score"])) < 1e-9 else ""
        out.append(f"| {t:.2f} | {pct(passed)} | {pct(blocked)}{mark} |")

    out += [
        "",
        "## Caveats",
        "",
        f"- {len(ans_q)} answerable + {len(unans)} unanswerable questions over a small synthetic "
        "corpus written by the project author; treat small differences as noise.",
        "- Correctness is a keyword check (required facts present), not a judgement of prose.",
        "- Faithfulness is judged by the same local model that answers; see the judge validation.",
        "- Generation uses temperature 0, but local inference is not guaranteed bit-identical.",
    ]
    return "\n".join(out) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--retrieval-dataset", type=Path, default=ROOT / "datasets" / "retrieval.json"
    )
    parser.add_argument("--qa-dataset", type=Path, default=ROOT / "datasets" / "qa.json")
    parser.add_argument(
        "--judge-dataset", type=Path, default=ROOT / "datasets" / "judge_validation.json"
    )
    parser.add_argument("--corpus", type=Path, default=ROOT / "corpus")
    parser.add_argument("--out-dir", type=Path, default=ROOT / "results")
    parser.add_argument(
        "--limit", type=int, help="only the first N of each question set (smoke run)"
    )
    parser.add_argument("--skip-judge", action="store_true")
    parser.add_argument("--price-in", type=float, default=0.0, help="USD per 1M input tokens")
    parser.add_argument("--price-out", type=float, default=0.0, help="USD per 1M output tokens")
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
    llm = OllamaLLM(settings.ollama_base_url, settings.llm_model)  # judge: never thinks
    answer_llm = OllamaLLM(  # capped exactly like the API's model, so the eval measures it
        settings.ollama_base_url,
        settings.llm_model,
        think=settings.llm_think,
        max_tokens=answer_token_cap(settings),
    )
    escalation_llm = (
        None
        if settings.llm_escalation == "off"
        else OllamaLLM(
            settings.ollama_base_url,
            settings.llm_model,
            think=True,
            max_tokens=settings.llm_escalation_tokens,
            timeout=settings.llm_escalation_timeout_seconds,
        )
    )

    retrieval_qs = {
        q["id"]: q for q in json.loads(args.retrieval_dataset.read_text("utf-8"))["questions"]
    }
    qa_data = json.loads(args.qa_dataset.read_text("utf-8"))
    answerable = [(retrieval_qs[i], groups) for i, groups in qa_data["answerable"].items()]
    unanswerable = qa_data["unanswerable"]
    if args.limit:
        answerable, unanswerable = answerable[: args.limit], unanswerable[: args.limit]

    mode, top_k, min_score = (
        settings.retrieval_mode,
        settings.ask_top_k,
        settings.min_evidence_score,
    )
    with Session(engine) as session:
        n_files = ingest_corpus(session, args.corpus, settings)
        services.embed_pending_chunks(session, embedder, settings.embed_batch_size)
        n_chunks = session.scalar(select(func.count()).select_from(Chunk)) or 0
        check_labels(session, [q for q, _ in answerable])
        print(f"Ingested {n_files} files, {n_chunks} chunks.")
        print(f"mode={mode} top_k={top_k} gate={min_score}")

        validation = None
        if not args.skip_judge:
            cases = json.loads(args.judge_dataset.read_text("utf-8"))["cases"]
            print(f"Validating judge on {len(cases)} labelled cases...")
            validation = validate_judge(llm, cases)
            print(f"  judge accuracy {validation.correct}/{validation.total}")

        records: list[Record] = []
        todo = [(q["id"], "answerable", q["question"], q, groups) for q, groups in answerable] + [
            (u["id"], u["kind"], u["question"], None, None) for u in unanswerable
        ]
        for n, (qid, kind, question, rq, groups) in enumerate(todo, start=1):
            rec = Record(qid, kind, question)
            run_question(
                session, embedder, answer_llm, settings, mode, top_k, min_score, rec, escalation_llm
            )
            if rec.error is None and rq is not None:
                expected = expected_of(rq)
                hits = retrieval.search(
                    session,
                    embedder,
                    question,
                    mode=mode,
                    top_k=10,
                    pool=settings.retrieval_pool,
                    rrf_k=settings.rrf_k,
                    project_id=None,
                )
                got = [(h.document.source_path, h.chunk.section) for h in hits]
                rec.retrieval_rank = rank_of_question(got, rq)
                rec.precision_at_k = precision_at_k(got, expected, top_k)
                if not rec.refused:
                    rec.correct = keyword_correct(rec.answer or "", groups)
                    rec.citation_any, rec.citation_precision = citation_scores(rec.cited, expected)
            if rec.error is None and not rec.refused and not args.skip_judge:
                rec.faithful = judge_supported(llm, question, rec.answer or "", rec.cited_text)
            state = (
                "ERROR"
                if rec.error
                else ("refused:" + str(rec.reason) if rec.refused else "answered")
            )
            print(f"[{n}/{len(todo)}] {qid} {kind}: {state} ({rec.latency_ms / 1000:.1f}s)")
            records.append(rec)

    meta = {
        "date": date.today().isoformat(),
        "corpus": f"{n_files} files, {n_chunks} chunks (eval/corpus)",
        "questions": f"{len(answerable)} answerable + {len(unanswerable)} unanswerable",
        "retrieval mode": mode,
        "top_k": str(top_k),
        "min_evidence_score": str(min_score),
        "reranking": (
            f"ON (top {settings.rerank_pool}; its tokens are NOT in the tokens/query figures; "
            "the retrieval rank and precision rows describe plain retrieval, before reranking)"
            if settings.rerank_enabled
            else "off"
        ),
        "calculator": "ON (the model writes arithmetic, code evaluates it)"
        if settings.ask_calculator
        else "off",
        "answer model thinking": "ON (the judge never thinks)" if settings.llm_think else "off",
        "answer token cap": f"{answer_token_cap(settings) or 'none'} (a cut-off answer is refused)",
        "escalation": (
            f"{settings.llm_escalation} (thinking re-check capped at "
            f"{settings.llm_escalation_tokens} tokens, first answer kept on failure)"
            if settings.llm_escalation != "off"
            else "off"
        ),
        "embedding model": settings.embedding_model,
        "answer + judge model": settings.llm_model,
        "platform": platform.platform(),
    }
    report = build_report(records, validation, meta, (args.price_in, args.price_out))
    args.out_dir.mkdir(parents=True, exist_ok=True)
    stem = (
        f"qa{dataset_tag(args.qa_dataset, 'qa')}-{meta['date']}"
        + ("-rerank" if settings.rerank_enabled else "")
        + ("-calc" if settings.ask_calculator else "")
        + ("-think" if settings.llm_think else "")
        + (f"-escalate-{settings.llm_escalation}" if settings.llm_escalation != "off" else "")
        + ("-smoke" if args.limit else "")
    )
    (args.out_dir / f"{stem}.md").write_text(report, encoding="utf-8")
    (args.out_dir / f"{stem}.json").write_text(
        json.dumps(
            {
                "meta": meta,
                "validation": asdict(validation) if validation else None,
                "records": [asdict(r) for r in records],
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    print("\n" + report)
    print(f"Wrote {args.out_dir / (stem + '.md')}")


if __name__ == "__main__":
    main()
