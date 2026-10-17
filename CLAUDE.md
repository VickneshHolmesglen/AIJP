# Project Intelligence RAG

Portfolio project: a RAG system that understands software project docs and source code, answers
with verifiable citations, and refuses when evidence is insufficient. Full spec and milestones are
in `Claude Code Handoff — AI Project Intelligence Portfolio.md`. Read it before large changes.

## Commands
- `uv sync` — install deps
- `docker compose up -d db` — PostgreSQL 16 + pgvector (also creates the `aijp_test` database)
- `uv run uvicorn app.main:app --reload` — run the API (docs at /docs); applies migrations at start
- `uv run alembic revision --autogenerate -m "..."` — new migration after a model change (then read
  and edit the file); `uv run python -m app.migrate current|check|upgrade`
- `uv run python -m app.projects create|list|delete` — projects; `python -m app.keys create --project SLUG` confines a key
- `uv run pytest` — tests; DB integration tests skip automatically if Postgres is down
- `uv run ruff check . && uv run ruff format . && uv run mypy app` — lint, format, types
- `uv run python -m eval.consistency` — design-vs-code check on the seeded corpus (16 claims,
  ~9 min: each check takes ~30 s locally); run detached, machine otherwise idle
- `uv run python -m eval.qa` — answer-quality eval (needs Postgres + Ollama; ~15-20 min with the
  local model; `--limit N` for a smoke run); writes `eval/results/qa-<date>.md`
- `uv run python -m eval.compare BASE.json OTHER.json [BASE2.json OTHER2.json]` — paired, pooled
  comparison of two qa runs (CIs + sign test). Run any eval on the v2 set with e.g.
  `--dataset eval/datasets/retrieval_v2.json` (qa: `--retrieval-dataset ... --qa-dataset
  ...qa_v2.json --judge-dataset ...judge_validation_v2.json`; consistency: `--dataset
  ...consistency_v2.json`); reports get a `-v2` tag
- `uv run python -m eval.retrieval` — retrieval benchmark (needs Postgres + Ollama); wipes and
  reuses the `aijp_test` DB, refuses to touch `aijp`; writes `eval/results/retrieval-<date>.md`

## Rules
- NO LangChain / LlamaIndex. Keep the RAG pipeline explicit and explainable in an interview.
- Every significant dependency must have a "why is this here?" answer.
- Citations (path, page, section, line range) are part of the data model; never drop provenance.
- Never invent benchmark numbers; only publish output from the evaluation tooling.
- Untrusted input: uploaded files are validated (type, size, content sniffing) before parsing.
- Add new file formats by adding a loader to `app/ingestion/loaders.py`, not by special-casing.
- After each milestone, explain: what, why, alternatives, tradeoffs, interview takeaways.

## Layout
- `app/ingestion/` — validation, loaders (bytes -> Segments with provenance), chunker
- `app/services.py` — ingestion orchestration + document queries
- `app/api/` — FastAPI routers; `app/models.py` — SQLAlchemy models (Chunk.embedding is pgvector)
- `app/retrieval.py` — vector / lexical (Postgres FTS) / hybrid (RRF) search, all return `Hit`
- `app/agent/` — fixed workflows + audit + approval: `consistency.py` (design-vs-code check),
  `recorder.py` (per-step audit rows), `actions.py` (registry + human approval). `app/symbols.py`
  is the shared symbol lookup (MCP `find_symbol` and the workflow). `app/api/agent.py` is the API.
- `app/static/` — the UI: vanilla ES modules, no build step, no framework, self-hosted fonts
  (`fonts/`, OFL). Served at `/ui/` (`/` redirects) with a strict CSP set in `app/main.py`.
  `app/api/system.py` (`GET /status`) and `app/api/evaluation.py` (`/eval/reports`) exist for it.
- `eval/` — benchmark: `corpus/` (fixed synthetic project; ruff-excluded), `datasets/`,
  `metrics.py` (pure, unit-tested), `retrieval.py` + `qa.py` (runners), `judge.py` (LLM
  faithfulness judge + its own validation), `results/` (generated reports; `qa-run.log/.err` are
  scratch output of a detached run)
- `tests/` — unit tests need no DB; `@pytest.mark.integration` tests need Postgres
- `docs/evaluation.md` — the evaluation story for readers (only numbers from eval/results reports);
  `docs/images/` — README screenshots of the real UI (Playwright + Edge from the scratchpad, demo
  project `shardfall` in the dev DB `aijp` loaded from eval/corpus; keys used were revoked).
  `demo.gif` (README top, 2026-10-18): Playwright `recordVideo` of a real session, ffmpeg to GIF
  (8 fps, 800 px, 96 colours, 4.1 MB); the two model waits are 5x speed WITH an on-screen label,
  the rest is real time. Questions: Venom Tower damage + poison stacks (cited), multiplayer
  modes (model_declined). Script/filter lived in that session's scratchpad.

## Status (last updated 2026-10-01)
- Milestones 1-11 are complete and verified (foundation, ingestion, embeddings + semantic search,
  grounded Q&A, source code ingestion, hybrid retrieval, evaluation, UI, MCP, agent workflows,
  containers/CI/monitoring), plus M12 authentication (see below). THE ROADMAP IN THE HANDOFF DOC IS
  DONE. Ruff, mypy pass. Tests: 602
  pass, 0 skipped (real Postgres/pgvector; embedder and LLM faked in tests; the pipeline, UI, MCP
  server, agent workflow and the containers were also exercised end to end against real Ollama
  nomic-embed-text + qwen3.5).
- M11 (user chose: portable containers + cloud reference docs only, Prometheus + structured logs,
  host Ollama with an optional container profile): `Dockerfile` (multi-stage, uv pinned to 0.11.7
  = lockfile producer, non-root uid 10001, healthcheck, JSON uvicorn logs via
  `app/uvicorn_logging.json`); `docker-compose.yml` (db + api, optional `ollama` profile, all ports
  on 127.0.0.1, read-only fs, cap_drop ALL, no-new-privileges); `.github/workflows/ci.yml` (quality
  job with a guard that FAILS ON ANY SKIPPED TEST, container smoke job, pip-audit job) +
  dependabot; `app/observability.py` (JSON logs, request id, pure-ASGI middleware),
  `app/metrics.py` (prometheus-client, the only new dependency: http, ask outcomes by reason, LLM
  tokens, dependency errors, agent runs/actions), `/metrics` (reader key since M12, AIJP_METRICS_ENABLED);
  `docs/deployment.md` (config, security checklist, monitoring/alerts, backup/restore, CI, cloud
  sketch, and an explicit verified/NOT-verified list). Query strings and bodies are never logged.
  NOT verified: the GitHub Actions workflow on GitHub (see M17), the `ollama`
  profile image, GPU passthrough, Linux hosts, any cloud deployment, load. Backup/restore WAS tested
  with real embedded data (identical MD5 of text and vectors, all 4 indexes restored).
- M10 design (user chose: fixed workflows, design-vs-code headline, approval on task creation):
  `POST /agent/consistency-checks` runs search_design -> search_implementation -> lookup_symbols ->
  evidence_gate -> judge -> validate_verdict -> draft_action. Verdicts: consistent |
  potential_discrepancy | insufficient_evidence; a verdict needs valid citations on BOTH sides or it
  is downgraded. Tables: agent_runs, agent_steps (audit, committed per step), agent_actions
  (drafts), tasks (created only on approval). Approval (`/agent/actions/{id}/approve|reject`) takes
  NO payload, locks the row (FOR UPDATE), only executes kinds in `ACTION_REGISTRY`, and every
  decision is an audit step. Settings: `consistency_top_k` (4), `consistency_min_cosine` (0.60, raised from 0.55 by user decision
  2026-09-20 from the sweep below; the M10 report was generated at 0.55).
  NOT exposed over MCP on purpose: it writes audit rows, and the MCP server is read-only.
- M10 results (eval/results/consistency-2026-09-20.md, 16 claims, seeded corpus = eval/corpus +
  eval/seeded_patches, real models): 4/6 seeded mismatches found, 0/6 false alarms, 6/6 consistent
  confirmed, 3/4 unsupported left undecided, 12/12 verdicts cite a correct source on both sides,
  median 29.1 s, p95 41.3 s, ~1100 tokens/call. Failures are model reasoning, not retrieval: s3
  (1.25 vs 50 percent) the model wrote both numbers and still said consistent; s1 (poison replaces
  instead of stacking) it cited the constant/config not the function; u3 (unsupported) it returned
  potential_discrepancy while its own explanation said the evidence was missing, which is exactly
  the bogus task the approval gate exists to stop. Gate sweep: at 0.60 all 12 with-evidence claims
  pass and all 4 unsupported are blocked (incl. u3); at 0.55 (current) only 50% blocked. Margin is
  thin and n=16, so 0.60 is a candidate, not adopted. Do NOT tune the judge prompt on these 16
  claims and report the improved score (overfitting); grow the dataset first.
- M7 results (eval/results/qa-2026-09-20.md, 36 answerable + 12 unanswerable, vector mode, real
  models, a clean run with nothing else using the machine): correct 34/36, citation accuracy
  34/36, 0 false refusals, refused 11/12 unanswerable (all by the MODEL, none by the gate; the one
  it answered was near-miss u11), judge-flagged unsupported 5/36 answered, median latency 7.5 s,
  p95 21.1 s, ~673 tokens/query, cost $0 (local). CAVEATS found on review: the 2 "incorrect" are
  keyword-check misses on plausible answers (c04, c06); the judge looks wrong on p04 and i03 (cited
  text does support them) but right on u11, n08 (self-contradicting 262 vs 187 gold) and c08; the
  judge's 12/12 validation was on easy cases, so extend `judge_validation.json` with hard ones.
- Gate calibration finding (same report): unanswerable top-cosines span 0.527-0.777, near-misses
  0.68-0.78, HIGHER than the lowest answerable (0.583). A cosine gate can only stop off-topic
  questions (which the model already refuses); it cannot stop near-misses. At 0.55 all answerable
  pass and 25% of unanswerable are blocked; at 0.60 8.3% of answerable are lost. DECISION
  (user, 2026-09-20): default raised 0.5 -> 0.55. The M7 report was REGENERATED at 0.55 during M14
  (same 34/36 correct, 0 false refusals, 11/12 refused, 3 of 48 stopped by the gate itself).
- M9 MCP: `app/mcp_server.py` (official `mcp` SDK v2.x: `MCPServer`, NOT the v1 `FastMCP`; `mcp.Client(server)`
  gives in-memory protocol tests). Run `uv run python -m app.mcp_server` (stdio). 7 read-only tools:
  search_project, search_source_code, ask_project, find_symbol, list_documents, get_document,
  get_project_status. `ProjectTools` holds the logic with injected deps; `build_server` registers
  them. Expected failures raise `ToolError` (message reaches the client); unexpected ones are hidden
  by the SDK. Audit log to stderr = tool/status/ms/argument SIZES only, never content (stdout is the
  protocol channel: never print). Verified over real stdio with real models. Shared plumbing:
  `app/providers.py` (Ollama providers), `app/presenters.py` (domain -> response schemas),
  `app/system_status.py`; `retrieval.search` gained a `file_types` filter (SQL-level).
  NOT built (no real backing yet): find_design_requirement, generate_project_report.
- M8 UI: `/ui/` (see Layout). Views: Ask (footnote chips always shown, even if the model places no
  inline [n]), Search (mode compare), Documents (files/folder upload, embed banner), Evaluation
  (renders eval/results/*.md), System (/status). Projects were added in M20.
- M5 design: `app/ingestion/code_loaders.py` (registered in `loaders.LOADERS`): Python via stdlib
  `ast` (parse only, never executed), GDScript via an indentation-aware line scanner (approximate,
  no parser), YAML by top-level key (line scan, no parser), JSON by top-level key (validated with
  json.loads). Symbol path goes in `Chunk.section` ("Enemy > take_damage"); no schema change.
  Supported extensions: .pdf .txt .md .py .gd .json .yaml .yml. Syntax-broken Python falls back to
  one plain segment. Known limits: GDScript multi-line strings at column 0 can split a function
  early; chunk text is embedded without its section name (worth testing in the eval milestone).
- M4 design: `app/llm.py` (LLMProvider Protocol + OllamaLLM), `app/qa.py` (retrieve -> retrieval
  gate `is_evidence_sufficient` -> JSON-mode LLM -> server-side citation verification), `POST /ask`.
  Refusal reasons: insufficient_evidence (LLM not called), model_declined, uncited_answer. (Later: calculation_failed,
  ungrounded_number (M16), answer_truncated (M22 fix).)
  Sources are labelled untrusted in the prompt (prompt-injection defence).
- M3 design: `app/embeddings.py` (EmbeddingProvider Protocol + OllamaEmbedder), embedding is a
  separate step (`POST /embeddings`), `POST /search` returns hits with full citations, HNSW cosine
  index created in `init_db`. `nomic-embed-text` is pulled in Ollama and verified (768-d).
- Search scores are raw cosine similarity, NOT calibrated. Any refusal threshold must come from
  the evaluation tooling, not a guess.
- M6 design: `/search` takes `mode` (vector|lexical|hybrid); `settings.retrieval_mode` is the
  default for `/search` and `/ask` and STAYS `vector`. Lexical = Postgres FTS (OR-ed terms, section
  path indexed, GIN index in `init_db`); hybrid = RRF (k=60, pool 20 each). Hits carry `cosine`
  separately from `score`; the evidence gate uses best cosine because RRF scores have no fixed scale.
- M6 benchmark (eval/results/retrieval-2026-09-20.md, 37 questions, 73 chunks, real Ollama
  embeddings): vector MRR@10 0.875, hybrid 0.749, lexical 0.591; hybrid recall@10 1.000 vs vector
  0.973. Hybrid was better on 4 questions, worse on 11. Untuned equal-weight RRF hurt top-1 rank:
  the right chunk is usually in hybrid's top 5 but not first, which is the case a reranker helps.
  Do NOT tune RRF weights on this same 37-question set (overfitting); grow the dataset first.
- M14 (NOT in the handoff doc; user chose the reranker). `app/rerank.py`: `LLMReranker` grades the
  top-10 candidates 0-3 in ONE local-model call (no new dependency; alternatives rejected: a
  cross-encoder = torch, one call per candidate = 10x calls, asking for a full ordering = the model
  can drop/repeat ids). It only REORDERS (cannot add/drop/edit chunks), strict reply validation,
  ties keep retrieval order, ANY failure -> original order (`safe_rerank`, metric
  `rerank_total{outcome=ok|fallback}`). Wired opt-in (`AIJP_RERANK_ENABLED=false`,
  `AIJP_RERANK_POOL=10`) into `/search` (hits get `rerank_grade`) and `qa.ask`. The evidence gate
  runs FIRST on the plain-retrieval top_k, so reranking never changes which questions are refused
  and a refused question makes no rerank call. `get_llm`/`LLMDep` moved to `app/api/search.py`
  (re-exported from ask.py) to avoid an import cycle. NOT on MCP or the consistency workflow.
  Protocol fixed BEFORE running (prompt and pool not tuned on the 37 questions).
  RESULTS: `eval/results/rerank-2026-09-20.md` (ranking, 37 q): vector MRR@10 0.875 -> 0.911
  (4 better / 0 worse), hybrid 0.769 -> 0.926 (10 / 0), recall@1 vector 0.811 -> 0.865, +1.7-1.8 s
  per query. `qa-2026-09-20.md` (rerank OFF, regenerated at the 0.55 gate) vs
  `qa-2026-09-20-rerank.md` (ON), 36+12 questions: correct 34/36 -> 33/36, citation precision
  83.3% -> 81.0%, everything else identical, median latency 1.1 s -> 2.9 s. The one regression
  (c02, `_load_waves` chunk fell out of the cited set) is 1 question = noise, but there was NO
  gain anywhere. DECISION: stays off by default; better ranking did not become better answers
  because the answer model already sees 5 chunks and recall@5 is 97%. Reranker tokens are not in
  `llm_tokens_total`. Do not tune the reranker prompt on these questions; write new ones first.
  Caveat: the regenerated baseline's median latency (1.1 s) is far below the old M7 report's 7.5 s;
  the machine state differed, so do not compare latency across report dates.
- M12 (NOT in the handoff doc; user chose: authentication and accountability, API keys, roles
  reader < editor < approver, self-approval allowed but recorded). ON BY DEFAULT is MY decision, not
  the user's: `AIJP_AUTH_ENABLED=false` opts out (loud startup warning, UI banner, anonymous actor).
  `app/auth.py`: key `aijp_<8hex prefix>_<43 char secret>`, only SHA-256(secret) stored, constant-time
  compare with a dummy compare for unknown prefixes, one generic 401 for every failure (reason goes
  to log + `auth_failures_total`), 403 for a too-low role. `RequestGateMiddleware` rejects
  unauthenticated mutating requests and oversized Content-Length BEFORE the body is parsed (FastAPI
  parses bodies before resolving dependencies); it does not verify keys, so fake well-formed tokens
  and chunked bodies still reach the parser (proxy cap needed). Middleware order: context outermost.
  `app/keys.py` is the ONLY key management (CLI create/list/revoke; no HTTP endpoints).
  `app/audit.py` `record_event` -> `audit_events` (identifiers/counts only, never text). New columns
  `requested_by`, `decided_by`, `created_by` (added to old DBs by `_LEGACY_ADDITIVE` in `app/migrate.py`). `/auth/config` public, `/auth/me`, `/metrics` needs reader. MCP stdio
  BYPASSES API auth (local trust). UI: key in memory, opt-in sessionStorage; `ctx.can(role)` hides
  controls but the server is the authority. `tests/conftest.py` sets AIJP_AUTH_ENABLED=false for the
  legacy suites; `tests/test_auth.py` has a role matrix + a guard that every route is covered.
  CI container job now has separate public-endpoint and auth smoke steps (`curl -I` sends HEAD and
  the GET-only route answers 405: use `curl -D - -o /dev/null`). NOT verified: GitHub Actions itself.
- M13 (NOT in the handoff doc; user chose Alembic migrations). Schema is now owned by Alembic:
  `app/migrations/versions/0001_baseline.py` is HAND-WRITTEN DDL (not `create_all`, which would
  change meaning as models change), incl. the HNSW + FTS indexes; `app/migrate.py` `upgrade()` runs
  at startup (`db.init_db` delegates to it) under a pg advisory lock; CLI `python -m app.migrate
  upgrade|current|check`; `alembic.ini` exists only for `uv run alembic revision --autogenerate`.
  Three cases: empty DB -> all revisions; LEGACY DB (tables, no alembic_version) -> `_LEGACY_ADDITIVE`
  ALTERs then stamp 0001 (the real dev DB `aijp` was adopted this way, data intact); versioned ->
  pending revisions. `tests/test_migrations.py` uses throwaway databases: fresh==models drift guard
  (mutation-verified: adding a model column fails it), idempotent, downgrade, legacy adoption with
  data, 4 concurrent starters, `check` exit codes. `include_object` ignores the two unmodelled
  indexes. Embedding dim is read from settings when the baseline runs. Only the baseline exists;
  downgrade drops everything; backup is the real rollback. CI runs `app.migrate check` in the
  container job. NOT verified: a data-changing migration (none written yet), GitHub Actions.
  Gotcha: importing `app/migrations/env.py` runs it (needs alembic context), so shared helpers live
  in `app/migrate.py`.
- M15 (NOT in the handoff doc; user chose bigger, harder evals). Second question sets over the
  SAME corpus, written by the AI assistant (not independent) AFTER v1 results were known, so they
  target v1's weak spots; not used to tune anything. Files: `eval/datasets/{retrieval,qa}_v2.json`
  (36 answerable: multi_hop 11, negation 5, paraphrase_hard 8, code_reasoning 7, identifier 5; 14
  unanswerable, 10 near-miss), `judge_validation_v2.json` (14 subtle cases), `consistency_v2.json`
  + overlay `eval/seeded_patches_v2/` (6 NEW mismatches, each with a config value still agreeing
  with the design; 8 seeded/8 consistent/8 unsupported, half of the unsupported are on-topic).
  Runner changes: `require_all` labels (multi-hop credited only when ALL sources are retrieved,
  `metrics.full_coverage_rank`), `dataset_tag` so v2 reports never overwrite v1 (`*-v2-<date>`),
  dataset field `patches_dir`, Wilson 95% CIs on every qa proportion (`metrics.wilson_interval`),
  sign-test p on paired tables (`metrics.sign_test_p`), and `eval/compare.py` (paired, POOLED
  comparison of two qa runs; report `eval/results/compare-rerank-2026-09-20.md`).
  `tests/test_eval_datasets.py` guards structure (labels name real files, overlay changes exactly
  what `seeded_changes` documents, judge sets are balanced). The runner's label check caught 3
  wrong section labels on the first v2 run (fixed): keep it.
  FINDINGS (v2, real models, one run each; all reports in eval/results/*-v2-*):
  * v2 is much harder: vector MRR@10 0.562 (v1 0.875), recall@1 0.333 (0.811).
  * Reranker, held-out ranking: vector MRR 0.562 -> 0.679, 11 better / 0 worse (p=0.001); hybrid
    0.550 -> 0.600, 10/0 (p=0.002). So the M14 ranking gain REPLICATES on new questions.
  * Reranker, end to end, POOLED 72 answerable: 59/72 correct with and without it; gained 2, lost
    2 (p=1.0); latency 1.2 -> 2.9-3.0 s. M14's decision (off by default) is CONFIRMED with twice
    the data. Caveat: 72 questions cannot detect a difference of a few points either way.
  * WHY reranking doesn't help: v2 answer failures (25/36 correct) are model REASONING, not
    retrieval. multi_hop is 4/11 correct: m02 said 48 damage (12*1.5=18), m11 said 1250 (rank 1!),
    m10 said 360 (435), m03/m04 wrong sums. The right chunks were retrieved; qwen3.5 does the
    arithmetic badly. Also 3 false refusals from the gate/model (h03, h07: insufficient_evidence).
  * Judge validation: 12/12 on v1's easy cases but 12/14 (85.7%) on v2's subtle ones (1 false
    supported, 1 false unsupported), so its faithfulness numbers are less trustworthy than v1
    implied. It also flags correct DERIVED numbers (e.g. 180 for m01) as unsupported: v2's
    unsupported rate (26.5%) is inflated by that; do not compare it with v1's 13.5%.
  * Consistency v2: seeded found 4/6, false alarms 1/8 (y5), confirmed 7/8, unsupported left
    undecided 7/8 (x5 got a verdict), verdict accuracy 18/22. Misses z4/z6: the model cited the
    config that still agrees with the design and answered `consistent`, and for z4 its own
    reasoning found the 0.6 vs 0.3 mismatch and it still said consistent (same failure as v1 s1/s3).
  * GATE: the consistency gate 0.60 was chosen on v1 (blocked 4/4 unsupported). On v2 it blocks
    only 4/8 (on-topic near-misses have high cosine) and the sweep shows 0.65 already loses 14% of
    with-evidence claims. The v1 calibration does NOT generalise; the value is UNCHANGED pending
    a user decision (do not tune it on v2 alone; v1+v2 pooled would be the basis).
  Not done: re-run of the v1 qa/retrieval reports with CIs (their files predate the CI columns).
- M16 (NOT in the handoff doc; user chose "fix the answer bottleneck"). Hypothesis from M15:
  the model can't do arithmetic. Built `app/calc.py` (hand-written recursive-descent parser, NO
  eval/ast, exact Decimal, + - * / ( ) min max round int abs and c1.. references; 60 tests incl. a
  hostile-input suite) and an OPT-IN calculator mode in `qa.ask` (`AIJP_ASK_CALCULATOR`): the model
  writes `calculations`, refers to results as `{c1}`, the server evaluates and substitutes; new
  refusal reasons `calculation_failed` and `ungrounded_number` (a number in the answer that is not
  in the cited passages, the question or a calculation); `calculations` shown in the response and
  the UI. Also an opt-in `AIJP_LLM_THINK` (answer model reasons before replying; the eval judge
  never thinks). BOTH DEFAULT OFF.
  PROTOCOL: v2 = DEV set (2 calculator rounds + think arms allowed), v3 = HELD-OUT TEST set
  (`{retrieval,qa}_v3.json`, 28 computation questions + 6 near-miss, written BEFORE the calculator
  existed, answers computed by code with derivations stored, whole-number `#N` matching), every arm
  run ONCE, all reported. v3 is now SPENT for tuning: any further change needs new questions (v4).
  RESULTS (answerable correct; reports `qa-*-v3-*`, `compare-{think,calc}-2026-09-20.md`):
  * v3 held-out: baseline 15/28, calculator 5/28 (0 gained, 10 lost, p=0.002), thinking 20/28
    (5 gained, 0 lost, p=0.062), calculator+thinking 18/28. Median latency 1.7 s / 2.3 s / 9.9 s /
    7.9 s. Dev v2: baseline 25/36, calc r1 23, calc r2 21, think 26, calc+think 26.
  * POOLED v2+v3 (64): baseline 40, THINK 46 (7 gained, 1 lost, p=0.070), calculator 26 (0/14,
    p<0.001). Near-miss refusals with think 11/16 -> 15/16.
  * WHY the calculator failed (diagnosed, not tuned): (1) the arithmetic was never the only
    problem: the calculator computed every expression right, but the model wrote WRONG FORMULAS
    (off-by-one upgrade levels, forgot the flawless bonus, used another question's formula);
    (2) qwen3.5 at temp 0 without thinking does not reliably follow the delegate-your-arithmetic
    protocol: it types its own number (c24 wrote 400 for 60+35+300; c26 wrote a correct 170 with no
    calculation). The ungrounded_number check then WITHHOLDS those (15 of 28 on v3), correctly per
    its design, which is why the mode looks so bad. So the M15 claim "it's the arithmetic" was
    incomplete: it is formulation + instruction-following, and reasoning (think) helps more.
  * think is NOT enabled by default: p=0.07 is borderline, 6x latency, the sample is small. Enable
    per deployment with AIJP_LLM_THINK=true if accuracy matters more than latency.
  * The judge's unsupported rate fell 56.7% -> 4.0% on v3 with think, but the judge is known to
    flag correct derived numbers (M15), so do not read that as a 50-point faithfulness gain.
  * Reranker tokens / think tokens: think's extra tokens are not in `usage` (Ollama reports them
    separately), so its cost is understated.
- M17 (NOT in the handoff doc; user chose "push to GitHub + CI", then chose LOCAL COMMIT ONLY
  for now, PRIVATE when it is pushed, and to KEEP the existing git identity). Done: `git init -b
  main`, one commit (`f5926a1`, 194 files, identity from the global config = Vicknesh / GitHub
  noreply, which differs from the session email: ask before changing),
  `.gitattributes` (`* text=auto eol=lf`, so Linux CI and the Dockerfile see LF; many working files
  were CRLF and git normalises them; the eval corpus was already LF, which matters because its
  content is benchmark input), `.gitignore` extended, a stray empty file `Bearer` removed, secret
  scan clean. VERIFIED FROM A FRESH CLONE (scratchpad `clone/`): locked install, format, lint, mypy,
  457 tests + the ci.yml skip guard verbatim, image build, hardened container smoke, pip-audit, and
  `actionlint` on the workflow. PUSHED LATER (see GITHUB below); the first Actions runs have not
  been reviewed.
  Gotchas: in Git Bash `docker run ... --tmpfs /tmp` needs `MSYS_NO_PATHCONV=1` or the path is
  rewritten to `C:/...`; a clone runs the same shared `aijp_test` database, so still never run two
  test/eval processes at once.
- M19 (NOT in the handoff doc; user chose "consistency gate + judge fix"). DECISIONS (user):
  KEEP the gate at 0.60; KEEP the per-source judge OPT-IN (`AIJP_CONSISTENCY_JUDGE=per_source`).
  Built: `decide_from_stances` + `JUDGE_PER_SOURCE_SYSTEM` in `app/agent/consistency.py`: the model
  gives a stance per source (design states/contradicts/unrelated; implementation
  supports/contradicts/unrelated), CODE applies the rule "any contradicting implementation source
  => potential_discrepancy even if a config value agrees" (invented refs ignored, odd stance words
  = unrelated, no usable output => insufficient_evidence, verdict needs a design side); step
  `judge` records `mode`. Tools: `eval/gate_sweep.py` (pooled sweep with CIs, from result files),
  `eval/compare.py` now also compares consistency runs. Consistency runner: `judge mode` and
  `judge thinking` in the report, `-persource`/`-think` in the filename, `think` honoured.
  PROTOCOL: v3 consistency set (`consistency_v3.json` + `seeded_patches_v3/`: 6 new mismatches,
  code-only x2, behavioural x2, config-only x2; 8 consistent; 8 unsupported, 4 near-miss) was
  COMMITTED BEFORE the judge existed (git c1823dc). v1+v2 were the dev sets (judge prompt frozen
  after 1 round). v3 is now SPENT. Each arm run once.
  RESULTS: held-out v3 (22 claims): current judge 17/22, per-source 20/22 (3 gained, 0 lost,
  p=0.25), current+think 18/22, per-source+think 19/22 (median 21 s and 54 s vs 2.4 s). POOLED
  v1+v2+v3 (60): 49 -> 53 correct (5 gained, 1 lost, p=0.22); seeded found 12 -> 14 of 18,
  unsupported left undecided 16 -> 19 of 20, consistent confirmed 21 -> 20 of 22; +~1 s/check.
  Direction consistent, NOT significant. Thinking adds little for its cost here.
  WHY the target failure only half-fixed: per-source fixes "config outvotes code" STRUCTURALLY but
  the model still mislabels a single source (v2 z4: it called code multiplying speed by 0.6
  "supports" a 30% slow, a 2-step inference) and sometimes the contradicting chunk is not among the
  4 retrieved (z6). So the remaining limits are per-source reasoning and retrieval coverage.
  GATE (pooled 60 claims, `gate-sweep-consistency-2026-09-20.md`): 0.60 lets 39/40 real claims
  through and blocks 13/20 unsupported; 0.65: 32/40 and 18/20; 0.55: 40/40 and 6/20. The v1-only
  "4/4 blocked" was luck (on-topic near-misses score high). The M10 report was REGENERATED at 0.60
  (v1: 4/6 seeded found, 0/6 false alarms, 6/6 confirmed, 4/4 undecided).
- M20 (NOT in the handoff doc; user chose multi-project support). Model: `projects(id, slug
  unique, name)`; `project_id` NOT NULL on documents / agent_runs / tasks; `api_keys.project_id`
  NULLABLE (NULL = every project); unique(sha256) became unique(project_id, sha256) so one file can
  live in two projects. Migration `0002_projects.py` is a real DATA migration (default project,
  backfill, then NOT NULL + FKs, ON DELETE CASCADE everywhere, INCLUDING keys: a deletion must never
  widen a scoped key to all projects). ISOLATION BY CONSTRUCTION: `retrieval.*`, `symbols.
  find_symbols`, `qa.ask`, `services.*` take a REQUIRED `project_id` (None = "all", explicit, used
  only by the single-project eval scratch DBs), so mypy lists every unscoped call site. API:
  `app/api/scope.py` `ProjectDep` resolves `?project=<slug>` AND authorises it in ONE place (a
  confined key defaults to its own project; wrong project == unauthorised project == same 404).
  By-id routes (document/run/action) authorise by the caller's own scope, not the query param.
  `app/projects.py` (domain + CLI create|list|delete --yes), `app/api/projects.py` (GET list;
  POST create = unscoped approver only), `keys create --project`, `AIJP_MCP_PROJECT` (MCP serves one
  launcher-chosen project; the model never picks). `default` is created on demand. UI: switcher in
  the sidebar (`api.js` `project`, adds `?project=` except /auth /projects /health /eval), a
  confined key sees its project name instead of a dropdown. Audit detail carries `project`.
  TESTS: `tests/test_projects.py` (41: every read/write path across a boundary, both key kinds,
  CLIs, cascade, MCP) + 4 new migration tests (backfill, per-project uniqueness, guarded
  downgrade, real legacy adoption); MUTATION-VERIFIED: 13 enforcement points removed one at a time,
  every one caught (`scratchpad/mutate_projects.py` idea: break, run test_projects, restore).
  VERIFIED for real: 0002 on a DB holding the real embedded corpus (identical text+vector md5, all
  in default, HNSW/FTS kept); real stack with two projects and real models; Playwright session
  switching projects and as a confined key; CI container job (now includes project checks).
  BUGS FOUND ALONG THE WAY (all fixed): (1) THE ROUTE-GUARD TEST IN test_auth.py WAS VACUOUS: newer
  FastAPI hides included routers behind `_IncludedRouter` objects with path '', so `for route in
  app.routes` saw none of the API and the guard passed while checking nothing (possibly since M12).
  Now `all_routes()` walks `original_router` + `include_context.prefix`, with a non-vacuity test
  (>=20 routes, known routes present) and a check that a newly added route is seen. (2) `re.match(
  r"^..$")` accepts a trailing newline ("a\n"): slug validation, the API-key format, the calculator
  id and the X-Request-ID check all switched to `fullmatch` (request id + slug have tests). (3) the CI
  public-endpoints step piped curl into `grep -q` (exit 23 under pipefail when grep closes early):
  headers are captured first. (4) the UI probed /status while signed out (a needless 401).
  Gotchas: in Git Bash `MSYS_NO_PATHCONV=1` (needed for `docker run --tmpfs /tmp`) breaks curl's
  `-o /dev/null` (exit 23): unset it for the CI-step emulation; heredocs also collapse `\\r\\n` in
  YAML/Python written through Bash, so patch those with the Edit tool or chr(92).
  NOT verified: GitHub Actions itself (still not pushed). NOT built: per-project roles/members,
  moving a document between projects, project rename, an HTTP delete (CLI only, on purpose).
- M21 (NOT in the handoff doc; user chose "cheaper thinking (v4 eval)"). RESULT: escalation ON BY
  DEFAULT (`AIJP_LLM_ESCALATION=derived`, USER DECISION). How it works (`qa.ask`, `_escalate`): the
  first answer is produced without thinking; if it contains a number that is not in the cited
  passages or the question (`ungrounded_numbers`, reused from M16) it is re-asked with a THINKING
  model capped at 1500 tokens (`llm_escalation_tokens`) and 45 s (`llm_escalation_timeout_seconds`);
  the second answer replaces the first and faces the SAME citation checks; if it is truncated
  (`Completion.truncated`, from Ollama's done_reason "length"), errors or times out, the FIRST answer
  stands (`escalated: "fallback"`). Modes off | derived | always. Response field `escalated`, metric
  `escalation_total{outcome}`, UI note "re-checked with reasoning". `OllamaLLM(max_tokens, timeout)`.
  PROTOCOL: v4 (`{retrieval,qa}_v4.json`: 18 computational + 12 plain lookups + 8 unanswerable) was
  COMMITTED BEFORE the feature (git 42f99cb); arms run once each; then replicated on v2 and v3.
  Design constraint found first: qwen3.5 IGNORES thinking levels (think low/medium/True are
  identical, 11,027 tokens / 161 s on one probe), so the only "budget" is a token cap.
  RESULTS (answerable correct): held-out v4 (30): baseline 17, derived 23 (6 gained/0 lost,
  p=0.031), always-capped 26 (9/0, p=0.004), always-think uncapped 27 (10/0, p=0.002). Median
  latency 1.3 s / 1.5 s / 6.4 s / 6.1 s. On v4 derived escalated 13 of 30, ALL computational, none of
  the 12 lookups; it misses computational questions whose WRONG first answer quotes source numbers
  (k06 50=the interest cap, k11, k12). Replication baseline -> derived: v3 15 -> 19 (4/0), v2 25 ->
  27 (2/0). POOLED v2+v3+v4 (94): 57 -> 69, 12 gained / 0 lost, p~0.0005; refusals unchanged 21/28
  (`compare-escalation-2026-09-21.md`). Cost: latency is unchanged for lookups but numeric answers
  take ~7-25 s (v3, 68% numeric: median 1.7 -> 7.2 s, p95 44 s), ~65% more tokens on average.
  cap works (1 of 29 always-capped calls truncated; worst case 35 s uncapped -> 24 s).
  HARDWARE CAVEAT: all latencies were measured on an IDLE machine. A game (Diablo IV) later held
  the GPU and generation fell from ~68 to ~8 tokens/s: 1500 tokens then took ~195 s, so a TOKEN cap
  is not a TIME cap. The 45 s timeout was added AFTER seeing that (verified on the real stack: 160 s
  -> 50.8 s, correct first answer kept). It is a safety net above the 25 s idle worst case, so it
  did not affect the reported accuracy.
  CONSEQUENCES OF THE NEW DEFAULT: `tests/conftest.py` sets AIJP_LLM_ESCALATION=off (older suites use
  one scripted model); `eval.qa` baselines MUST now set AIJP_LLM_ESCALATION=off explicitly (filenames
  carry `-escalate-<mode>` so runs cannot be confused); `eval/results/qa-*` before M21 were baselines.
  `Answer.escalated`, `eval/qa.py` report row "answers re-checked with thinking".
- M22 (NOT in the handoff doc; user chose "escalation blind spot (v5 eval)"). PARTLY FINISHED: the
  user stopped the work at the replication stage. DEFAULT UNCHANGED (`derived`); two new opt-in
  modes exist. Goal: M21's `derived` trigger misses computational questions whose WRONG first answer
  quotes a source number (v4 k06/k11/k12). Built in `qa.ask`: mode `cue` = derived OR the question
  contains arithmetic cue words (`_ARITHMETIC_CUES`: total, combined, after, per second, percent(age),
  times, more, less, remain, left, extra, increase, lose, earned, refund, "in N seconds"...); mode
  `classify` = derived OR a cheap NON-thinking call (`CLASSIFIER_SYSTEM`, `_needs_calculation`) says
  the question needs a calculation. Both apply only when the first answer contains a number (citation
  markers like [1] excluded: a test caught the bug where they were counted). A failed or garbled
  classifier means "no" (never slower or riskier). `EscalationMode` type in config; classifier tokens
  are added to usage. Tests: 35 in tests/test_escalation.py incl. the regexes on lookup wording, the
  classifier failure paths; MUTATION-CHECKED (one survivor, the classifier LLMError path, got a test).
  PROTOCOL: v5 (`{retrieval,qa}_v5.json`: 20 computational questions whose tempting wrong answer is a
  source number + 14 lookups, 8 phrased "how much/how many") was COMMITTED BEFORE the triggers (git
  7a5f053; 2 duplicated questions reworded in 5d8c7b7 before any run); the cue regex and classifier
  prompt were FROZEN before v5 ran and not tuned on it. Each arm run once.
  RESULTS on held-out v5 (34 answerable; baseline = AIJP_LLM_ESCALATION=off): baseline 21; derived 24
  (+3/0); cue 25 (+4/0); classify 26 (+5/0, p=0.062); always-capped 26 (+5/0, p=0.062).
  Computational 7 / 10 / 11 / 12 / 12 of 20. Lookups escalated (WASTED thinking): derived 0, cue 3
  (d05 "times", d06 "per second", d12 "percentage": the cue words are too broad, as predicted),
  classify 0, always 14. Median latency 1.1 / 1.2 / 1.8 / 1.6 / 5.7 s; tokens/query 632 / 868 / 1012 /
  1041 / 1342. So `classify` REACHED THE ALWAYS-THINK CEILING with no waste and about 1/3 of its
  latency. derived -> classify: +2/0 (p=0.5, not significant). On v4 (dev for this feature: its misses
  inspired the triggers, so NOT independent): derived 23 -> classify 26, 16 escalations, all on
  computational questions.
  NOT DONE (stopped by the user): replication of `classify` on v3 and v2 (v4 finished, v3/v2 runs were
  killed and left no files); no default change (evidence: one held-out set, p=0.062, replication
  missing; the user was not asked). The 8 computational questions all arms still get wrong (c01 c02
  c05 c12 c14 c15 c17 c18) fail even with always-thinking, so they are NOT a trigger problem: candidates
  are the 1500-token cap (4 fallbacks per thinking arm), retrieval of waves.json for the bounty
  questions, or model ability. Not investigated.
  REPLICATION DONE 2026-09-25 (`qa-v{3,2}-2026-09-25-escalate-classify`, idle GPU logged per minute;
  a first attempt was contaminated by a game started mid-run: 34 re-checks hit the 45 s timeout,
  exit 0, visible only in latency; those files are NOT results). derived -> classify, paired:
  v3 19 -> 19 (+c05/-c07), v2 27 -> 26 (-m10), v5 24 -> 26. POOLED 97: 70 -> 71, 3 gained / 2 lost,
  p=1.0 (`compare-escalation-classify-pooled-2026-09-25.md`). v5's gain did NOT replicate. Both
  losses were the 1500-token cap truncating classify's re-check where derived's re-check had
  finished (m10 derived took 25 s), i.e. cap variance, not the trigger. DEFAULT STAYS `derived`.
  8-FAILURE DIAGNOSIS (v5 always-think misses, from result files): 5 retrieval (c01 c02 c14: the
  `waves.json` counts are not in the top 5; c05 c18: "Upgrades and selling" is missing, so declining
  is right), 1 token cap (c17: perfect retrieval, re-check truncated), 2 dataset wording (c12 c15:
  "by how much" is fairly answered with "20/30 percent"; NOT re-scored, v5 is held out). Every v5
  fallback is a truncation (22-23 s), never the 45 s timeout. c14's wrong "60" escaped `derived` because
  60 is in the sources (Grunt health). Bridge facts (raw JSON, sections that never name the entity)
  are the retrieval weak spot. VERIFIED by ranking the whole corpus (vector): the entity chunk
  ranks 1-2 every time, the bridge chunk ranks 9-25 (cos 0.49-0.60): waves.json 15/25/9 for
  c01/c02/c14 (c01 also misses Runner at 17), Upgrades and selling 17/23 for c05/c18. So a
  reranker over the top 10 cannot fix 4 of 5: the fix has to change what is retrieved.
  BUG FOUND AND FIXED (2026-09-25): the FIRST answer call had no token cap. v3 c02 ("sell
  a level 3 Cannon Tower") deterministically makes qwen3.5 (think off) reason inside the JSON answer
  string for 15,665 tokens / 227 s (done_reason=length); the client times out at 180 s -> LLMError ->
  the API request fails after 3 minutes and holds the GPU. It took 1808 tokens / 33 s on 2026-09-20,
  so the behaviour drifted. FIX (user chose 1024 + a new reason): `AIJP_LLM_MAX_TOKENS=1024` on the
  shared model (`providers.answer_token_cap`; 0 = none; NOT applied with llm_think, as thinking counts
  toward num_predict); `qa.ask` refuses a truncated first answer as `answer_truncated` BEFORE parsing
  (a cut-off answer that happens to parse and cite was previously SHOWN and re-checked), no re-check.
  Reranker/classifier/consistency judge share the cap; each already fails safe on bad output. eval.qa
  uses the same cap and prints it in the header. tests/test_answer_cap.py (6). VERIFIED on the real
  model: c02 -> answer_truncated in 14.9 s (was a 180 s error), a lookup unaffected (1.0 s). LIMIT: a
  token cap is not a time cap: with a game on the GPU (~5 tok/s) 1024 tokens took 201 s, still past the
  180 s client timeout (-> error). A shorter wall-clock limit on the first answer was NOT added (it
  would also refuse slow correct answers on a busy machine; ask the user). Eval reports before this
  fix ran uncapped.
  PROCESS NOTES: (1) the GPU was shared with a game (Diablo IV) for part of the session: generation
  was 4-20 tokens/s vs ~70 idle. After the game exited Ollama needed a few warm calls to recover
  (measure with eval_count/eval_duration from /api/chat, not wall clock). The v5 runs were started
  only after speed recovered (~74 tok/s); (2) a commit went through with a failing test because
  `pytest | tail` hides the exit code: use `pytest -q; echo $?` or `set -o pipefail` before committing.
- M23 (NOT in the handoff doc; user chose "bridge-fact retrieval", approach "section-path prefix",
  format "path first with a newline"). NEGATIVE RESULT, feature stays OFF (default already off).
  Built: `embedding_input` in app/embeddings.py ("<file> > <heading path>
<text>"; off = the text
  unchanged), `AIJP_EMBED_SECTION_PATH` (default false), `services.embed_pending_chunks(section_path=)`
  (fetches the document path in the same query), eval reports print "embedding input" and carry a
  `-sectionpath` tag. Chunk.content/citations/queries untouched. Flipping it on a populated DB needs a
  full re-embed (documented, no automatic path). tests/test_embedding_input.py (7).
  PROTOCOL: v6 (`{retrieval,qa}_v6.json`: 20 bridge questions = entity chunk + a rule/data/code chunk
  that never names the entity, require_all; 12 lookups; 8 unanswerable) COMMITTED BEFORE the feature
  (git eecefc2; labels checked offline against the real chunker, which caught 3 bad labels BEFORE any
  run); feature committed before any run (cfe061a); each arm once; GPU logged idle.
  RESULTS (pre-registered primary = bridge full-coverage recall@5, vector): 14/20 -> 10/20, 0 gained
  / 4 lost (b08 b10 b12 b13, ALL waves.json questions), p=0.125. Hybrid 13 -> 9 (0/4). Lookup MRR
  0.958 -> 0.926. END TO END (production defaults, only the embedding input differs): 24/32 -> 17/32
  correct, 1 gained / 8 lost, p=0.039 (`compare-sectionpath-v6-2026-09-25.md`); bridges 13 -> 7 of 20.
  WHY (diagnosed on the prefixed index, not tuned): the prefix lifts EVERY chunk whose path shares a
  question word, and the code is named after the same entities: all `src/enemies/enemy.gd > Enemy >`
  chunks gain "enemy", all `wave_spawner.gd > WaveSpawner >` chunks gain "wave". The one short
  waves.json chunk gains as much as each of them, so it fell from rank 5 to outside the top 12. A
  path prefix is a blunt tool in a corpus whose file names echo its domain words; the retrieval weak
  spot stays open (next candidates: a second retrieval hop keyed on the entities of the first, or
  reserving slots for data/rule chunks; both need a NEW held-out set, v6 is spent).
  FOUND ALONG THE WAY (FIXED 2026-09-26, see below): lexical search ordered by `ts_rank_cd DESC, Chunk.id`, and Chunk.id
  is a random UUID per ingest, so lexical TIES are broken by coin flip, differently in every eval run
  (9 of 32 v6 lexical ranks changed between two runs that differ only in embeddings). All lexical and
  hybrid eval numbers since M6 carry this run-to-run noise; vector is unaffected.
  FIX: lexical ORDER BY rank DESC, source_path, chunk_index, Chunk.id (id last: two documents may
  share a path across projects); hybrid RRF ties sorted by the same key (they used str(chunk id)).
  Vector search deliberately NOT changed: pgvector uses the HNSW index only for ORDER BY <distance>
  LIMIT n, extra sort keys would make every vector query a full scan, and float cosine ties do not
  occur with real embeddings. tests/test_retrieval_ties.py (ids chosen to sort OPPOSITE to the path
  order; mutation-checked: restoring either old order fails its test). VERIFIED: two v6 retrieval
  runs now give 0 rank differences in all modes, vector identical to the published baseline.
  Also fixed: `lexical_search(query_vector=None)` emitted invalid SQL `null()` (func.null instead of
  sqlalchemy.null); no caller passed None, so it was latent. Published lexical/hybrid reports before
  this fix are ONE draw of the tie order; they were not regenerated.
- M24 (NOT in the handoff doc; user chose "second retrieval hop with a v7 set", then "LLM sub-queries"
  after the cheap hops failed). STOPPED IN THE DEV PHASE, NOTHING SHIPPED, v7 NOT RUN (still unspent).
  v7 (`{retrieval,qa}_v7.json`: 20 bridge incl. 3-4-chunk ones, 12 lookups, 8 unanswerable; keys
  avoid numbers stated in the sources) was COMMITTED BEFORE any hop code (git 8af1a12). Design was
  done on v5+v6 as DEV (34 multi-source + 32 lookup questions), vector baseline full-coverage@5 23/34.
  DEV NUMBERS (scratch harness, NOT published reports): residual query r=q-(q.h1)h1 with 1/2 reserved
  slots 20 / 18 (0 gained); feedback query (question + top hit text) 20 / 19 (0 gained); lexical as the
  hop 19 / 18 (0 gained); LLM sub-queries (one non-thinking call, <=2 queries, one reserved slot each)
  round 1 16/34 (+1 -8), round 2 (no entity names, "general mechanism" wording) 17/34 (+2 -8).
  Lookups were never hurt (their chunk is rank 1). WHY every hop fails: (1) the waves.json chunk is
  UNREACHABLE by embeddings: even ideal generic sub-queries ("total enemy health per wave") never put it
  in their top 20 (its vector is dominated by JSON syntax); (2) the rule chunk "Upgrades and selling"
  reached at best rank 12-14; (3) the model ignores "no names" half the time and never answers "no
  extra fact needed", so every question pays for the evicted rank-4/5 chunk.
  MOST PROMISING NEXT (not built): make DATA files retrievable at ingest, e.g. a JSON/YAML loader that
  renders records as sentences ("Wave 2: 8 grunt, 3 runner") while keeping line provenance; that is a
  loader change (the rule: formats go in app/ingestion/loaders.py). Then run v7, which is unspent.
- M25 (NOT in the handoff doc; user chose "data file loader change", then allowed a 3rd dev round).
  NEUTRAL IN DEV, ALL CODE REVERTED, v7 STILL UNSPENT. Dev = v5+v6 multi-source questions, vector
  full-coverage@5 (old loader: v5 9/14, v6 14/20); dev numbers are scratch runs, NOT published.
  Round 1, JSON arrays of records split into one segment per record (verbatim lines, section
  "waves > #N", header line joined to record 1; needed a label migration section -> section_prefix
  "waves" in v2-v7, also reverted): v5 10, v6 13. Round 2, + embed JSON chunks as table name + keys and
  values in plain words (stored text unchanged): v5 10, v6 12. Round 3, UNSPLIT table + that
  flattened input: v5 10, v6 14 (0 gained / 0 lost vs baseline). WHAT WAS LEARNED: (1) flattening DOES
  make data reachable (split records went from outside the top 20 to ranks 1-6; unsplit c02 25 -> 10);
  (2) splitting a table whose records differ only by a number creates near-duplicate vectors that
  CROWD the top 5 and push out the other chunk the question needs (embeddings barely separate "wave
  3" from "wave 5"); (3) the remaining data-question failures (v6 b09 b11) are the ENTITY chunk
  missing ("health of every enemy" pulls many enemy chunks), not the data. So retrieval of these
  questions is now limited by a top-5 budget shared between 2-4 needed chunks, not by any one chunk
  being unreachable. Candidates not tried: a larger k only for multi-part questions, or result
  diversity (MMR); both need v7 (unspent) as the test.
- M26 (user chose "MMR diversity on the dev sets"). NEGATIVE IN DEV, nothing built, v7 unspent.
  Settings FIXED before running: pool 20 (vector), lambda 0.7 primary, 0.5/0.85 sensitivity; plain
  index (re-ingested and checked identical to the published v6 baseline). Multi-source full-coverage
  @5 on v5+v6 (34): baseline 23; MMR 0.7 22 (+0 -1); 0.85 22 (+0 -1); 0.5 17 (+0 -6, and one lookup
  lost its chunk from the top 5). Rank 1 never changes (MMR's first pick is the most relevant). WHY:
  crowding by near-duplicates only existed with M25's split records (reverted); on the plain index
  the top 5 holds DIFFERENT but wrong chunks, and the missing ones (ranks 9-30, low relevance) cannot
  be lifted by a diversity bonus without also discarding good chunks. Scratch harness, not published.
  SUMMARY M23-M26: 11 retrieval variants (path prefix, 3 embedding hops, lexical hop, 2 LLM
  sub-query rounds, 3 data-file variants, MMR) were ALL neutral or worse for multi-source
  questions; the bottleneck is a 5-chunk budget and an embedding model that does not connect a
  question's entity to rules/data that never name it.
- M27 (user chose "larger k for multi-part questions on dev"). STOPPED AT THE CEILING CHECK, nothing
  built, v7 unspent. Candidates fixed before running: k=8, k=10. Full-coverage@k (vector, plain index)
  on v5+v6 multi-source (34): k5 23, k6 23, k8 24, k10 25, k12 25, k15 25, k20 27, k30 33; lookups
  32/32 at every k. Of the 11 misses at k=5 only 2 are covered by k=10 (v6 b14 at 8, v5 c14 at 9); the
  rest need k=17-43. So even a perfect detector + perfect answering gains at most +2/34 on dev (about
  +1 of v7's 20 bridges, undetectable) for 2x prompt size + a detector call: not worth building.
  INSIGHT: the missing chunks are spread through the middle of a 73-chunk corpus, not just behind the
  cutoff; at k=30 the prompt holds ~40% of the corpus. For a corpus this small (~13 KB) sending all of
  it (long context) is the honest alternative to RAG; RAG earns its keep only when the corpus is too
  big to send. That is the end of the M23-M27 retrieval line (12 variants, none helped).
- M28 (NOT in the handoff doc; user chose "OpenAI-compatible provider", to close the "LLM APIs" job
  gap at no cost). `OpenAICompatibleLLM` in app/llm.py (Chat Completions over httpx, NO new
  dependency); `AIJP_LLM_PROVIDER=ollama|openai` (default ollama, unchanged); `openai_base_url` defaults
  to local Ollama's /v1; `openai_api_key` is a SecretStr sent only as a Bearer header (not in repr,
  errors carry the HTTP status only, never the body). `providers.make_llm(settings, think, max_tokens,
  timeout)` is now the ONLY place a chat client is built: API (`llm`, `escalation_llm`), MCP, and
  eval/qa, rerank, consistency (they built OllamaLLM directly before, so a provider switch would have
  silently missed them). eval/qa reports carry "llm api" and a `-openai` filename tag.
  PROBED BEFORE CODING (Ollama 0.34.4 /v1, 2026-09-27): `reasoning_effort: none` turns thinking off,
  but `think: false` is SILENTLY IGNORED (thinks, returns empty content); `max_tokens` caps, but
  `max_completion_tokens` is SILENTLY IGNORED (191 tokens for a cap of 5); JSON mode via
  `response_format` works; truncation = finish_reason "length"; unknown model = 404. Hence the
  configurable `openai_token_param` and `openai_send_reasoning_effort` (a plain hosted chat model may
  reject reasoning_effort). tests/test_openai_llm.py (17): exact request body, Bearer only with a key,
  every failure -> LLMError without the key, truncation, factory. VERIFIED on the real model through
  /v1: c02 -> answer_truncated at exactly 1024 tokens, a lookup answered (27 tokens); native and /v1
  generate at the same speed (244 tokens, 22.5 s each, measured side by side). SIDE-BY-SIDE EVAL
  (v1 qa, 36+12, production defaults, idle GPU logged): native vs /v1 IDENTICAL -- 48/48 answers
  word for word, same refusals, 33/36 correct both, 34,341 tokens both, median 1.1 s both
  (`qa-2026-09-27-escalate-derived` vs `qa-2026-09-27-openai-escalate-derived`,
  `compare-provider-2026-09-27.md`). NOT DONE: a hosted API (needs a key; Anthropic's Messages API
  is a different shape and would need its own provider).
  eval/ is not under mypy (19 pre-existing errors, none from this change).
- PORTFOLIO PASS (2026-09-27, user: "this is just a job application demo portfolio"): README rewritten
  for a hiring manager (pitch, screenshot, what it does, results table, skills-to-job-ads table, mermaid
  diagram, quick start; detail below), long eval narrative moved to docs/evaluation.md. Every number
  checked against its report; M24-M27 (dev-only scratch runs) described WITHOUT numbers. CI is
  described as verified from a fresh clone, NOT as run on GitHub (it has not been).
- GITHUB (2026-10-01): remote `origin` = github.com/VickneshHolmesglen/AIJP, PRIVATE; the user pushed
  `main` themselves. The user's personal email had been written into CLAUDE.md (M17 note) and
  pushed; it was SCRUBBED: `git filter-branch` changed exactly that one line in 24 commits (each
  verified to differ by 1 line, nothing else), force-pushed with a lease, and 5 Dependabot branches
  built on the old history were deleted (Dependabot recreates them). The email is reachable from no
  branch; GitHub still keeps the closed Dependabot PRs' old commits (private repo, owner only; purge
  needs GitHub Support or a recreated repo before going public). A pre-rewrite bundle exists only in
  that session's scratchpad. NEVER write personal emails or names into tracked files. Standing
  permission: commit and push routine work to this private repo without asking; ask before any
  force-push or making it public. CI ON GITHUB VERIFIED 2026-10-17 (gh CLI installed at
  `C:\Program Files\GitHub CLI\gh.exe`, logged in as the repo owner): every run since the push had
  failed ONLY in the pip-audit job (pyjwt 2.14.0 CVE-2026-101918, via mcp[crypto]); quality (601
  tests, skip guard) and container jobs were already green on the GitHub runner. Fixed by
  `uv lock --upgrade-package pyjwt` (2.15.1, commit 866d60e); run 39006969435 is all green.
  Rebasing the 5 Dependabot PRs (#6-#10) then exposed TWO FLAKY FAILURES unrelated to the bumps:
  (1) A REAL BUG: two simultaneous approvals of one action BOTH executed (two tasks). The API's
  project check `session.get`s the action first; the later `SELECT ... FOR UPDATE` did wait for the
  other request's commit, but SQLAlchemy keeps an object already in the identity map and ignored
  the fresh row (ORM "pending", DB "executed"). Fix: `populate_existing=True` on the locked select
  in `actions.decide`. Deterministic test `test_decide_rereads_an_action_the_session_already_loaded`
  (no threads; it MUST hold a strong reference to the pre-loaded object: the identity map is weak,
  an unreferenced one is garbage-collected and reloaded, which made the first version pass
  vacuously). Threaded test went from failing 5/6 locally to 20/20. Introduced in M20 (the
  pre-check), passed by timing luck until then. (2) The container auth smoke step still piped
  `curl | grep -q` (/metrics body > pipe buffer -> curl exit 23 under pipefail; the M20 fix covered
  only the public step); bodies are now captured first everywhere. All 5 PRs were then merged one
  at a time (squash, `--match-head-commit`, main CI green after each): ruff 0.17.0, mypy 2.4.0,
  mcp 2.3.0, fastapi 0.143.0, sqlalchemy 2.1.4; 602 tests pass locally on the new lock. The assistant may post
  `@dependabot rebase` when the user asks (it was blocked once when unasked). Warnings left:
  actions/checkout@v4 + setup-uv@v5 target Node 20; ubuntu-latest moves to Ubuntu 26 on
  2026-10-19. Dependabot proposed Python 3.11 -> 3.14 (base image): a deliberate decision, do not merge
  blindly.
- PUBLIC (2026-10-18, user chose "fresh repo"): the old private repo was renamed to
  `AIJP-archive` (remote `archive`; it keeps closed Dependabot PRs #1-#5 whose old commits contain
  the scrubbed email, so it must NEVER be made public) and a NEW public `AIJP` was created and
  `main` pushed to it (history scanned first: noreply identities only, no secret patterns). The
  standing push permission was for a PRIVATE repo: ask before pushing now. TDEF scanned clean
  (noreply identities, no PR refs, no secret patterns) but making it public was blocked by the
  permission classifier: the user does it (`gh repo edit VickneshHolmesglen/TDEF --visibility public
  --accept-visibility-change-consequences`). Local Windows username appears in paths in both repos.
- PORTFOLIO MATERIAL: an interview cheat sheet exists as a Claude Doc (claude.ai artifact
  aec0b8cc-69f1-4dbd-af0f-942c7fafa982); `docs/portfolio-brief.md` (UNTRACKED on purpose: it describes
  the user's other repos) holds the survey of the game project Sanctuary Defenders (G:\TDef,
  github.com/VickneshHolmesglen/TDEF, PRIVATE as of 2026-10-17); a README/LICENSE/screenshot brief
  was left at G:\TDef\portfolio-readme-brief.md for Claude in that folder. CROSS-LINKED 2026-10-17:
  each README ends with an "Other project" section linking the other (TDEF commit 378dc3d, only
  README.md committed: that repo had another session's uncommitted work). BOTH REPOS ARE PRIVATE, so
  the links 404 for anyone else until the user makes them public (their decision; this repo still
  needs the Dependabot-PR history purge noted under GITHUB before going public).
- NEXT STEP on resume: the handoff roadmap (M1-M11) plus M12-M17 are complete, so ask the user what
  next. Open follow-ups, roughly by value: (1) CI is green on GitHub and the Dependabot backlog is
  merged and actions bumped to Node 24 (checkout v7, setup-uv v10.3.0, 2026-10-17) and the READMEs are cross-linked; left: making the
  repos public (user decision) and checking CI on the Ubuntu 26 runner image (from 2026-10-19); (2) remaining M15 findings: the consistency judge misses code-only discrepancies when a
  config agrees with the design (M19 fixed it only structurally, opt-in), the faithfulness judge
  mishandles derived numbers, and reasoning (AIJP_LLM_THINK) is
  the one lever that helped answers, so a cheaper way to get it (a smaller reasoning budget, or
  thinking only for questions that need arithmetic) is worth testing on a NEW set (v4);
  (3) per-project roles or moving documents between projects if users need them; (4) M22/M23 are finished; bridge-fact retrieval is still open (the section-path prefix FAILED,
  see M23) and every hop tried in M24 and every data-file change in M25 was neutral or worse on dev; v7 is
  UNSPENT; MMR (M26) and a larger k (M27, ceiling +2/34) also failed: the retrieval line is closed; (5) an actual cloud deployment (needs an account and
  a decision on where the models run).
  Docker Desktop must be running first, then `docker compose up -d db`.

## Local environment notes (Windows)
- `docker` is not on PATH. It lives in
  `C:\Users\Shaukan\AppData\Local\Programs\DockerDesktop\resources\bin`; add it to PATH or call it
  by full path. Docker Desktop must be running (engine up) before `docker compose`.
- WSL2 was missing and was installed on 2026-09-20; a restart was needed before Docker Desktop
  could start. Docker Desktop previously failed with "unable to start" for that reason.
- Use the Write/Edit tools for files; long shell heredocs failed in the Bash tool. In Bash
  heredocs a doubled backslash (`\\n`) collapses to one, silently turning "\n" string escapes
  into real newlines and breaking Python files: never patch code that way, use the Edit tool.
- NEVER run `pytest` (integration tests) or `eval.retrieval`/`eval.qa` concurrently: they share
  the `aijp_test` database and each wipes its tables. Running pytest mid-eval corrupts the eval.
- Do not run browsers, the UI server or any model call while `eval.qa` is running: it measures
  latency, and contention (seen once: one question took 66 s instead of ~12 s) invalidates it.
- UI testing: Chrome is not installed, Edge is. Drive it with `playwright-core` installed in the
  scratchpad (`chromium.launch({executablePath: '...\\msedge.exe'})`); nothing is added to the repo.
- UI rule: text from uploads or the LLM must only ever reach the DOM via `textContent`/text nodes
  (`app/static/js/dom.js`). Never `innerHTML`; the CSP also forbids inline script/style.
- UI gotcha: native `Element.append(null)` renders the literal text "null". Build children with
  `h()` or dom.js `append()`, which filter null/false. (This shipped once and was caught only by
  looking at a real screenshot.)
- Use `127.0.0.1`, NOT `localhost`, for the database (and Ollama) from the host. Compose publishes
  Postgres on IPv4 loopback only; on Docker Desktop `localhost` resolves to `::1` first, which is
  silently dropped, so EVERY new connection stalls 20-30 s before falling back (measured: 0.02 s
  vs 30 s). I introduced this by hardening the port binding and only noticed because a script
  "hung"; all defaults now use 127.0.0.1. Symptom to recognise: fast queries but slow connects.
- Windows tooling: find a server by its LISTENING port (`Get-NetTCPConnection -LocalPort N`), not by
  command-line pattern; the launcher's command line differs (`uvicorn.exe app.main:app`). A
  PowerShell command containing `Remove-Item` near the project dir can be refused as a whole, so
  nothing after it runs; check state before assuming a cleanup happened.
- GPU CONTENTION IS NOT ALWAYS VISIBLE AS LOAD: Firefox once held 5.85 GB of the RX 6800 XT's 16 GB
  VRAM with ~0% utilisation, and the model ran at 11-20 tok/s (normal ~75) even at "100% GPU" in
  /api/ps. Check per-process `\GPU Process Memory(*)\Dedicated Usage`, not only utilisation; after
  freeing VRAM, unload the model (`keep_alive: 0`) so it reloads cleanly. Games seen: Diablo IV,
  Moonlighter 2, Guildrun.
- Available: Python 3.11, uv, git, Ollama. Docker engine 29.8.0 and the pgvector/pgvector:pg16
  image are verified working (2026-09-20). Start Docker Desktop via Start-Process on its exe.
