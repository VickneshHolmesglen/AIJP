"""Design audit: check a game's design document against its code and data, claim by claim.

    python -m app.design_audit ingest --project SLUG --root DIR --include design/gdd src assets/data
    python -m app.design_audit run --project SLUG --doc design/gdd/tower.md --out audit.json
    python -m app.design_audit render audit.json --out audit.html

`ingest` loads a project folder (supported types only; every file still goes through the normal
upload validation) and embeds it. `run` walks one ingested design document passage by passage:
the model proposes checkable claims (app/agent/claims.py, each tied to a quoted line), and every
claim goes through the existing consistency workflow, so each verdict has its own audit trail in
agent_runs and a potential discrepancy becomes a DRAFT task a person must approve in the UI.
`render` turns the JSON into one static HTML page (app/audit_report.py) that needs no server.
"""

import argparse
import fnmatch
import json
import sys
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import projects, services
from app.agent.claims import extract_claims
from app.agent.consistency import run_consistency_check
from app.config import Settings, get_settings
from app.embeddings import EmbeddingProvider
from app.ingestion.errors import IngestionError
from app.ingestion.validation import ALLOWED_EXTENSIONS
from app.llm import LLMError, LLMProvider
from app.models import Chunk, Document

_MAX_SNIPPET_LINES = 40


def ingest_tree(
    session: Session,
    settings: Settings,
    project_id: uuid.UUID,
    root: Path,
    include: list[str],
    exclude: list[str],
) -> dict[str, int]:
    """Ingest every supported file under root/<include> whose path matches no exclude glob."""
    counts = {"ingested": 0, "skipped_type": 0, "excluded": 0, "rejected": 0}
    files = sorted({p for inc in include for p in (root / inc).rglob("*") if p.is_file()})
    for file in files:
        rel = file.relative_to(root).as_posix()
        if any(fnmatch.fnmatch(rel, pattern) for pattern in exclude):
            counts["excluded"] += 1
        elif file.suffix.lower() not in ALLOWED_EXTENSIONS:
            counts["skipped_type"] += 1
        else:
            try:
                services.ingest_document(
                    session,
                    project_id=project_id,
                    raw_filename=file.name,
                    content=file.read_bytes(),
                    source_path=rel,
                    settings=settings,
                )
                counts["ingested"] += 1
            except IngestionError as exc:
                counts["rejected"] += 1
                print(f"  rejected {rel}: {exc}", file=sys.stderr)
    return counts


def _snippet(session: Session, chunk_id: str) -> str:
    chunk = session.get(Chunk, uuid.UUID(chunk_id))
    if chunk is None:
        return ""
    lines = chunk.content.split("\n")
    more = len(lines) - _MAX_SNIPPET_LINES
    text = "\n".join(lines[:_MAX_SNIPPET_LINES])
    return text + (f"\n… ({more} more lines)" if more > 0 else "")


def _cited(session: Session, evidence: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "path": e["path"],
            "section": e["section"],
            "start_line": e["start_line"],
            "end_line": e["end_line"],
            "text": _snippet(session, e["chunk_id"]),
        }
        for e in evidence
        if e.get("cited")
    ]


def run_audit(
    session: Session,
    embedder: EmbeddingProvider,
    llm: LLMProvider,
    settings: Settings,
    project_id: uuid.UUID,
    doc_path: str,
    *,
    section_filter: str | None,
    claims_per_passage: int,
    max_claims: int,
) -> dict[str, Any]:
    document = session.scalars(
        select(Document).where(Document.project_id == project_id, Document.source_path == doc_path)
    ).first()
    if document is None:
        raise SystemExit(f"error: {doc_path} is not ingested in this project")
    passages = session.scalars(
        select(Chunk).where(Chunk.document_id == document.id).order_by(Chunk.chunk_index)
    ).all()
    if section_filter:
        needle = section_filter.lower()
        passages = [p for p in passages if p.section and needle in p.section.lower()]

    results: list[dict[str, Any]] = []
    failed_passages: list[dict[str, Any]] = []
    started = time.monotonic()
    read = 0
    for passage in passages:
        if len(results) >= max_claims:
            break
        read += 1
        try:
            claims = extract_claims(
                llm, passage.content, passage.section, passage.start_line or 1, claims_per_passage
            )
        except LLMError as exc:  # e.g. the model looped on this passage: skip it, keep going
            failed_passages.append({"section": passage.section, "error": str(exc)[:200]})
            print(f"  skipped passage {passage.section!r}: {exc}", flush=True)
            continue
        for claim in claims[: max_claims - len(results)]:
            t0 = time.monotonic()
            run = run_consistency_check(
                session,
                embedder,
                llm,
                settings,
                claim.text,
                project_id=project_id,
                requested_by="design-audit",
                source_chunk_id=passage.id,
            )
            result = run.result or {}
            results.append(
                {
                    "claim": claim.text,
                    "quote": claim.quote,
                    "line": claim.line,
                    "section": passage.section,
                    "run_id": str(run.id),
                    "status": run.status,
                    "verdict": run.verdict or "failed",
                    "explanation": result.get("explanation") or run.error or "",
                    "downgrade_reason": result.get("downgrade_reason"),
                    "design_evidence": _cited(session, result.get("design_evidence", [])),
                    "implementation_evidence": _cited(
                        session, result.get("implementation_evidence", [])
                    ),
                    "seconds": round(time.monotonic() - t0, 1),
                }
            )
            print(f"  [{len(results)}] {results[-1]['verdict']:22} {claim.text[:70]}", flush=True)

    verdicts = [r["verdict"] for r in results]
    return {
        "document": doc_path,
        "section_filter": section_filter,
        "generated": datetime.now(UTC).isoformat(timespec="seconds"),
        "model": settings.llm_model,
        "embedding_model": settings.embedding_model,
        "judge_mode": settings.consistency_judge,
        "evidence_gate": settings.consistency_min_cosine,
        "passages_read": read,
        "passages_failed": failed_passages,
        "minutes": round((time.monotonic() - started) / 60, 1),
        "counts": {v: verdicts.count(v) for v in dict.fromkeys(verdicts)},
        "claims": results,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.design_audit", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    ing = sub.add_parser("ingest", help="ingest and embed a project folder")
    ing.add_argument("--project", required=True)
    ing.add_argument("--root", required=True, type=Path)
    ing.add_argument("--include", nargs="+", required=True, help="folders under --root")
    ing.add_argument("--exclude", nargs="*", default=[], help="globs on the relative path")
    run = sub.add_parser("run", help="audit one ingested design document")
    run.add_argument("--project", required=True)
    run.add_argument("--doc", required=True, help="the document's source path")
    run.add_argument("--section", help="only passages whose heading path contains this")
    run.add_argument("--claims-per-passage", type=int, default=3)
    run.add_argument("--max-claims", type=int, default=20)
    run.add_argument("--out", required=True, type=Path)
    ren = sub.add_parser("render", help="write the static HTML report")
    ren.add_argument("reports", type=Path, nargs="+")
    ren.add_argument("--out", required=True, type=Path)
    ren.add_argument("--title", default="Design audit")
    ren.add_argument("--intro", default="")
    ren.add_argument("--footer", default="")
    ren.add_argument("--link", action="append", default=[], help='"Label=https://..." (repeat)')
    args = parser.parse_args(argv)

    if args.command == "render":
        from app.audit_report import render_html

        reports = [json.loads(p.read_text(encoding="utf-8")) for p in args.reports]
        links = [tuple(item.split("=", 1)) for item in args.link]
        if any(len(pair) != 2 for pair in links):
            parser.error('--link must look like "Label=https://..."')
        page = render_html(reports, args.title, args.intro, args.footer, links)
        args.out.write_text(page, encoding="utf-8")
        print(f"wrote {args.out}")
        return 0

    from app.db import get_engine, init_db
    from app.providers import embedder, make_llm

    settings = get_settings()
    engine = get_engine()
    init_db(engine)
    with Session(engine, expire_on_commit=False) as session:
        project = projects.get_by_slug(session, args.project)
        if project is None:
            print(
                f"error: no project '{args.project}' (python -m app.projects create)",
                file=sys.stderr,
            )
            return 1
        if args.command == "ingest":
            counts = ingest_tree(
                session, settings, project.id, args.root, args.include, args.exclude
            )
            print(f"files: {counts}")
            n = services.embed_pending_chunks(
                session, embedder(), settings.embed_batch_size, project_id=project.id
            )
            print(f"embedded {n} chunks")
            return 0
        llm = make_llm(settings, think=settings.llm_think, max_tokens=None)
        report = run_audit(
            session,
            embedder(),
            llm,
            settings,
            project.id,
            args.doc,
            section_filter=args.section,
            claims_per_passage=args.claims_per_passage,
            max_claims=args.max_claims,
        )
        report["project"] = project.slug
        args.out.write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(f"wrote {args.out}: {report['counts']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
