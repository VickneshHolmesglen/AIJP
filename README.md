# Project Intelligence RAG

A production-oriented AI knowledge system that understands technical documentation and source
code, answers questions with verifiable citations, detects insufficient evidence, and measures its
own retrieval and answer quality.

> **Status: feature-complete portfolio project.** Ingestion, embeddings, hybrid retrieval, grounded
> Q&A with verified citations, evaluation, web UI, MCP server, agent workflows, containers and CI,
> API-key authentication, migrations and an optional reranker are implemented and tested. Every
> published number comes from the evaluation tooling (`eval/results/`); the "Known limitations"
> section lists what is small, approximate or unverified.

## Why

Most RAG demos are "chat with a PDF". This one targets software projects: design docs, READMEs,
and eventually source code, so it can answer "where is enemy health calculated?" with a citation to
a file and line range.

## Current capabilities

- A web UI at `/ui/` (run the API, open http://localhost:8000): ask with clickable footnote
  citations that open the exact cited lines, compare retrieval modes, upload files or a whole
  project folder, browse evaluation reports and check system health. No build step or framework;
  uploaded and model-generated text is only ever rendered as text, under a strict CSP
- A design-vs-code consistency check: state a claim, get evidence from the design docs and from
  the code/config side by side, and a verdict of consistent, potential discrepancy or
  insufficient evidence. It can only *draft* a follow-up task; a human approves it (see "Agent
  workflows" below)
- An MCP server (`uv run python -m app.mcp_server`) so Claude or any MCP client can search the
  project, find where a symbol is defined, read documents and ask grounded questions. It is
  read-only by design and every result carries a citation (see "Use from Claude" below)
- Vector, lexical (PostgreSQL full-text) and hybrid (Reciprocal Rank Fusion) retrieval, compared
  by a reproducible benchmark (`uv run python -m eval.retrieval`, results in `eval/results/`)
- Answer-quality evaluation (`uv run python -m eval.qa`): correctness, citation accuracy, refusal
  accuracy, LLM-judged faithfulness (the judge is validated on hand-labelled cases), latency,
  tokens and cost; every published number comes from that run
- Upload PDF, TXT, Markdown, Python, GDScript, JSON and YAML files (`POST /documents`); source
  files are split by symbol so citations name the function or class, not just the file
- Validation: extension allowlist, size limit, content sniffing, filename and path sanitisation
- Provenance-preserving extraction: PDF page numbers, Markdown heading paths, line ranges
- Line-aware chunking with overlap; every chunk maps to an exact citable location
- Duplicate detection by SHA-256 (409 with the existing document id)
- List / get / delete documents (chunks cascade)

## Run locally

Requires Python 3.11+, [uv](https://docs.astral.sh/uv/), Docker and [Ollama](https://ollama.com/).

```bash
docker compose up -d db
ollama pull nomic-embed-text            # embeddings; the answer model defaults to qwen3.5
uv sync
uv run uvicorn app.main:app --reload   # UI at http://localhost:8000, API docs at /docs
uv run pytest
```

### In containers

```bash
docker compose up -d --build db api     # API + UI on http://127.0.0.1:8000, Postgres on 127.0.0.1:5432
```

The API container calls Ollama on your host by default. It runs as a non-root user with a read-only
filesystem and no Linux capabilities, logs one JSON object per line with a request id, and exposes
Prometheus metrics at `/metrics`. Everything binds to loopback. **API-key authentication is on by
default** (roles reader < editor < approver), so create a key first:

```bash
docker compose exec api python -m app.keys create --name me --role approver   # token is shown once
uv run python -m app.keys create --name me --role approver                     # without Docker
curl -H "Authorization: Bearer aijp_..." http://127.0.0.1:8000/documents
```

The web UI asks for the key on first load. For a throwaway local run, `AIJP_AUTH_ENABLED=false`
turns it off (with a startup warning and a banner in the UI). See [docs/deployment.md](docs/deployment.md)
for configuration, security checklist, monitoring and alerts, backup and restore, CI, a cloud
reference architecture (designed, not deployed) and an explicit list of what has and has not been
verified. CI (`.github/workflows/ci.yml`) runs lint, types, the full test suite against a real
database (failing if any test is skipped), a container smoke test and a dependency audit.

## Use from Claude (MCP)

The MCP server speaks stdio and needs Postgres and Ollama running, like the API. Tools (all
read-only, all annotated as such): `search_project`, `search_source_code`, `ask_project`,
`find_symbol`, `list_documents`, `get_document`, `get_project_status`.

```bash
# Claude Code
claude mcp add project-intelligence -- uv run --directory /path/to/AIJP python -m app.mcp_server
```

```jsonc
// Claude Desktop: claude_desktop_config.json
{ "mcpServers": { "project-intelligence": {
    "command": "uv",
    "args": ["run", "--directory", "/path/to/AIJP", "python", "-m", "app.mcp_server"]
} } }
```

Safety properties, each covered by tests: no tool can change the index; tool results are marked as
untrusted document text in the server instructions; unexpected errors never leak internals to the
client; the audit log (stderr) records tool, status, duration and argument sizes, never content.

## API examples

```bash
curl -F "file=@design/towers.md" -F "source_path=design/towers.md" localhost:8000/documents
curl localhost:8000/documents
curl localhost:8000/documents/<id>
curl -X DELETE localhost:8000/documents/<id>
```

## Agent workflows

`POST /agent/consistency-checks {"claim": "..."}` (or the **Verify** page) runs a fixed workflow:
search design docs, search code and config, look up any code identifiers named in the claim, apply
an evidence gate, ask the model to judge, validate the verdict, and draft an action.

There is deliberately no free-form loop where a model picks its own next tool. Code decides the
sequence; the model only fills the judging step, and its output is validated:

- A verdict must cite evidence on **both** the design and the code side, or it is downgraded to
  "insufficient evidence" (the model's citations are checked against what was actually retrieved).
- Every step is written to an audit trail as it finishes: name, duration, and the *locations* of
  evidence, never document text.
- A potential discrepancy only **drafts** a task. Nothing is created until a person approves it.
  Approval takes no payload (what runs is exactly what the server stored), only registered action
  kinds can execute, and the action row is locked so two approvals cannot both run.
- The result always carries a disclaimer: this is triage from retrieved passages, not proof.

Measured on a corpus with six deliberately seeded design/code mismatches, six consistent claims and
four unsupported ones (the first of three claim sets, 60 claims in all; see `docs/deployment.md` and
`eval/results/compare-judge-persource-*.md` for the pooled results and the opt-in per-source judge) (`uv run python -m eval.consistency`, report in
`eval/results/consistency-2026-09-20.md`, local `qwen3.5`): 4 of 6 seeded mismatches found, 0 of 6
false alarms, 6 of 6 consistent claims confirmed, 3 of 4 unsupported claims correctly left
undecided, median 29 s per check. The misses are informative, not hidden: the model sometimes
compares numbers wrongly even when its own explanation states both, and once judged a claim
"potential discrepancy" while its explanation said the evidence was missing. The approval gate is
what stops such a verdict from becoming a real task. 16 claims written by the project author is a
small sample; treat the percentages as indicative.

## Architecture

```text
Upload -> validate -> extract (per-format loader) -> chunk (line-aware) -> PostgreSQL + pgvector
Question -> embed -> retrieve (vector | lexical | hybrid) -> evidence gate -> LLM (JSON)
         -> verify citations against what was retrieved -> answer with sources, or refuse
Interfaces: HTTP API + web UI (app/api, app/static) and MCP server (app/mcp_server.py)
```

| Piece | Why |
|---|---|
| FastAPI + Pydantic | Typed request/response schemas, automatic OpenAPI docs |
| PostgreSQL + pgvector | One store for documents, chunks, vectors and full-text search, so provenance and retrieval share transactions |
| SQLAlchemy 2 | Explicit, typed models without hiding SQL |
| pypdf | Pure-Python PDF text extraction, no system dependencies |
| httpx | HTTP client for Ollama (embeddings, generation, health probe) |
| mcp (official SDK) | The MCP protocol is JSON-RPC with capability negotiation; hand-rolling it would be worse than depending on the reference implementation |
| Ollama (external) | Local embedding and answer models: no API keys, no data leaves the machine |
| No LangChain / LlamaIndex | The pipeline is written explicitly so each stage can be explained and tested |

## Known limitations

- Scanned (image-only) PDFs are rejected; OCR is out of scope
- Migrations are Alembic (applied at startup, see docs/deployment.md), but only the baseline
  exists and there is no rollback plan beyond a backup. There is no "project" concept yet (one
  shared corpus); adding it is now a migration rather than a rewrite
- Authentication is API keys managed by CLI: no users, SSO, per-project permissions or key-rotation
  UI. Keys are not rate-limited (do that at the proxy). The MCP server is local stdio and bypasses
  API auth, so it inherits the trust of whoever launches it
- Retrieval: an optional LLM reranker exists (`AIJP_RERANK_ENABLED`, off by default). It ranks
  the right chunk first more often (MRR@10 0.875 -> 0.911 on vector, 0.769 -> 0.926 on hybrid) but
  did not improve answers end to end (34/36 -> 33/36 correct) and more than doubled the latency, so it
  stays off (`eval/results/rerank-*.md`, `qa-*-rerank.md`). Hybrid search did not beat vector-only
  either, so vector is the default. The evidence gate only stops off-topic questions; near-miss
  questions rely on the model declining
- Evaluation datasets are small and self-authored over one small synthetic project: a first set
  (36 answerable + 12 unanswerable) and a harder second set (36 + 14) written after seeing the
  first, both by the AI assistant that built the project, not an independent party. Every
  proportion is reported with a 95% interval; at this size, differences of a few points are noise.
  The faithfulness judge is the same local model that answers: it scored 12/12 on easy validation
  cases but 12/14 on harder ones, and it marks correct derived numbers as unsupported
- On the harder sets the weak point is the answer model's multi-step reasoning, not retrieval
  (right chunks retrieved, wrong formula or wrong sum), which is why reranking improves ranking
  (MRR@10 0.56 -> 0.68) without improving answers (59/72 correct pooled, with and without it).
  Two fixes were built and measured on a held-out set: a server-side calculator (opt-in,
  `AIJP_ASK_CALCULATOR`) made answers much WORSE (the local model does not reliably delegate its
  arithmetic), while letting the model think first (opt-in, `AIJP_LLM_THINK`) helped (40 -> 46 of
  64 correct pooled, p=0.07) at about 6x the latency. Both are off by default
- Source-code chunking is symbol-level, not AST-aware; the GDScript scanner is approximate
- The consistency check only sees retrieved passages. It can miss a mismatch when the model
  compares values badly, and a constant that is defined but no longer used looks "consistent" to
  it. Checks are synchronous (about 30 s locally). Approvals record which key decided, but
  self-approval is allowed by design

## Roadmap

Done: 1-2 ingestion, 3 embeddings + search, 4 grounded Q&A, 5 source code, 6 hybrid retrieval,
7 evaluation, 8 UI, 9 MCP, 10 agent workflows, 11 containers, CI and monitoring, 12 authentication
and accountability, 13 database migrations (Alembic), 14 reranking (built and measured; off by
default because the end-to-end eval did not justify it), 15 a harder second evaluation set with
confidence intervals and paired significance tests, 16 a calculator and a thinking mode, measured
on a held-out set (calculator rejected, thinking kept as an option). Open follow-ups:
a cheaper way to get the benefit of thinking, a consistency judge that does not trust a config value over the code, recalibrating the
consistency gate on both question sets, multi-project support, and an actual cloud deployment.
