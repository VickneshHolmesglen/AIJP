# Deployment guide

How to run Project Intelligence RAG in containers, configure it, watch it, and what to think about
before putting it anywhere other people can reach. It ends with an honest list of what has and has
not been verified.

## 1. What runs

| Service | Image | Purpose | Port (host, loopback only) |
|---|---|---|---|
| `db` | `pgvector/pgvector:pg16` | PostgreSQL with vectors, full-text search and all application data | 5432 |
| `api` | built from `Dockerfile` | FastAPI app, web UI at `/ui/`, `/metrics`, and the MCP server (on demand) | 8000 |
| `ollama` | `ollama/ollama` (optional profile) | Embedding and answer models, for hosts without a native Ollama | 11434 |

State lives only in PostgreSQL (the `pgdata` volume). The API container is stateless and can be
replaced at any time.

## 2. Quick start

Prerequisites: Docker with Compose, and Ollama with the two models pulled.

```bash
ollama pull nomic-embed-text
ollama pull qwen3.5
docker compose up -d --build db api
curl http://127.0.0.1:8000/health/ready     # {"status":"ready"}
open http://127.0.0.1:8000/                 # the UI
```

By default the API container calls **Ollama on your host** (`host.docker.internal:11434`), so it
uses your GPU. To run Ollama in a container instead (CPU unless you add GPU settings):

```bash
AIJP_OLLAMA_BASE_URL=http://ollama:11434 docker compose --profile ollama up -d --build
docker compose exec ollama ollama pull nomic-embed-text
docker compose exec ollama ollama pull qwen3.5
```

Pin `OLLAMA_IMAGE` to a tested tag rather than `latest` for anything you rely on.

### The MCP server in a container

The MCP server speaks stdio, so it is launched on demand rather than run as a service:

```bash
docker compose run --rm -T --no-deps api python -m app.mcp_server
```

Point an MCP client at that command (`docker` with those arguments) instead of `uv run`.

## 3. Configuration

Every setting has a default in `app/config.py` and is overridden with an `AIJP_` environment
variable; `.env.example` lists them all. Compose reads a `.env` file next to `docker-compose.yml`.

| Variable | Default | Notes |
|---|---|---|
| `POSTGRES_PASSWORD` | `aijp` | Compose only. **Change before exposing anything.** On an existing volume, also run `ALTER USER aijp PASSWORD '...'` because the image only applies it at first initialisation |
| `AIJP_DATABASE_URL` | `127.0.0.1` dev URL | Compose builds this for the container. **Use `127.0.0.1`, not `localhost`**, when connecting from the host (see below) |
| `AIJP_OLLAMA_BASE_URL` | `http://127.0.0.1:11434` | Compose sets `host.docker.internal` |
| `AIJP_EMBEDDING_MODEL` / `AIJP_EMBEDDING_DIM` | `nomic-embed-text` / `768` | The dimension is baked into the table; changing it needs a migration and re-embedding |
| `AIJP_LLM_MODEL` | `qwen3.5` | Answer and judge model |
| `AIJP_MIN_EVIDENCE_SCORE` | `0.55` | Evidence gate for `/ask`, chosen from `eval/results/qa-*.md` |
| `AIJP_CONSISTENCY_MIN_COSINE` | `0.60` | Gate for the consistency check. Pooled over 60 claims it lets 39/40 claims with evidence through and blocks 13/20 unsupported ones (`eval/results/gate-sweep-consistency-*.md`); 0.65 loses 20% of real claims |
| `AIJP_CONSISTENCY_JUDGE` | `verdict` | `per_source` makes the model judge each source separately and code decide (any contradicting code source means a discrepancy). Held-out: 20/22 vs 17/22; pooled 53/60 vs 49/60 (p=0.22, not significant); about +1 s per check |
| `AIJP_RETRIEVAL_MODE` | `vector` | `hybrid` did not beat it on the benchmark |
| `AIJP_LLM_ESCALATION` | `derived` | Answer without thinking first; re-ask WITH thinking only when the answer contains a number that is not in the cited passages or the question. Pooled over 94 questions: 57 -> 69 correct, 12 gained / 0 lost, refusals unchanged. `off` disables it, `always` re-checks every answer (about 5x latency, not recommended). Two more modes are opt-in and less tested: `classify` (also re-check when a cheap extra model call says the question needs a calculation: on the v5 test set 26 of 34 correct against 24 for `derived` and 21 for `off`, no wasted re-checks on lookups, but one set only and the difference from `derived` is not statistically significant) and `cue` (also re-check when the question contains arithmetic words such as total or after: it wasted re-checks on 3 of 14 lookups, so `classify` is preferred). Numeric questions then take about 7-25 s (p95 22-44 s) and use about 65% more tokens; plain lookups are unaffected |
| `AIJP_LLM_ESCALATION_TOKENS` / `AIJP_LLM_ESCALATION_TIMEOUT_SECONDS` | `1500` / `45` | Caps on the thinking re-check. A token cap is not a time cap (on a loaded GPU 1,500 tokens took ~195 s), so both apply; hitting either keeps the first answer. Allow for about 50 s worst case in any proxy timeout on `/ask` |
| `AIJP_LLM_MAX_TOKENS` | `1024` | Cap on what one non-thinking model call may generate (0 = none). Answers are 50-300 tokens; one question made the model reason inside its answer for 15,665 tokens / 227 s until the request failed on the 180 s client timeout. Now it stops at the cap (~15 s on an idle GPU) and is refused as `answer_truncated`. Not applied when `AIJP_LLM_THINK` is on (thinking counts toward the cap). A token cap is not a time cap: on a GPU shared with a game (~5 tok/s) 1024 tokens took ~200 s |
| `AIJP_EMBED_SECTION_PATH` | `false` | EXPERIMENTAL, do not enable: embeds each chunk with its file and heading path. On the held-out v6 set it made retrieval of multi-source questions worse (14 -> 10 of 20) and answers worse (24 -> 17 of 32, p=0.039), because file names echo the question words. Changing it on a populated database needs a full re-embed |
| `AIJP_LLM_THINK` | `false` | The answer model reasons before replying. Pooled over 64 held-out and dev questions it got 46 right versus 40 (p=0.07), at about 6x the median latency (1.7 s to 9.9 s). Its extra tokens are not in `llm_tokens_total`. Allow for p95 latencies of 30-40 s in any proxy timeout |
| `AIJP_ASK_CALCULATOR` | `false` | The model writes arithmetic and the server computes it. **Not recommended**: with `qwen3.5` it made answers much worse on the held-out set (5/28 vs 15/28 correct) because the model does not reliably follow the protocol; it may suit a stronger model. See `eval/results/compare-calc-*.md` |
| `AIJP_MCP_PROJECT` | `default` | The one project the local MCP server serves. Chosen by whoever launches it; the model never picks a project |
| `AIJP_RERANK_ENABLED` / `AIJP_RERANK_POOL` | `false` / `10` | One extra model call per `/ask` or `/search` that reorders the top candidates. See `eval/results/rerank-*.md` before enabling; it adds latency and its own model tokens (not in `llm_tokens_total`) |
| `AIJP_MAX_UPLOAD_BYTES` | 10 MiB | Rejected before parsing |
| `AIJP_LOG_LEVEL` / `AIJP_LOG_FORMAT` | `INFO` / `plain` | The container sets `json` |
| `AIJP_METRICS_ENABLED` | `true` | `/metrics` needs a reader key while authentication is on |
| `AIJP_AUTH_ENABLED` | `true` | Secure by default. `false` opens everything to anyone who can reach the port and logs a warning at startup |

**Changing a gate or the embedding model invalidates its calibration.** Re-run the evaluations
(`eval.qa`, `eval.consistency`) and choose again from the sweep tables. Do not carry the numbers over.

## 4. Security checklist

**Authentication is on by default.** Every endpoint except `/health`, `/health/ready`,
`/auth/config` and the static UI needs an API key (`Authorization: Bearer aijp_...`). Roles are
hierarchical: `reader` (ask, search, read, status, metrics) < `editor` (+ upload, delete, embed, run
consistency checks) < `approver` (+ approve or reject drafted actions). Self-approval is allowed
but every decision records who made it (`decided_by`, plus an audit event).

Keys are managed only from the command line, so there is no HTTP surface for minting credentials:

```bash
docker compose exec api python -m app.keys create --name alice --role approver   # token shown once
docker compose exec api python -m app.keys create --name grafana --role reader --expires-days 90
docker compose exec api python -m app.keys list
docker compose exec api python -m app.keys revoke alice                            # effective on the next request
```

**Projects.** Documents, chunks, agent runs and tasks each belong to one project, and every
retrieval is filtered by project in SQL, so one project's text cannot reach another's search
results, prompts, answers, runs or counts. A request names its project with `?project=<slug>`
(default: `default`). A key created with `--project` is confined to it and defaults to it; a key
without is unscoped and may use every project. A wrong project and a project the key may not use
give the same 404, so a confined key cannot probe which projects exist.

```bash
docker compose exec api python -m app.projects create --slug shardfall --name "Shardfall"
docker compose exec api python -m app.projects list
docker compose exec api python -m app.keys create --name alice --role editor --project shardfall
docker compose exec api python -m app.projects delete shardfall --yes   # removes EVERYTHING in it
```

Only an unscoped approver key can create a project over the API (`POST /projects`); deleting one
is CLI-only and cascades to its documents, runs, tasks and confined keys (a key is never widened
to all projects by a deletion). Project roles are not per-project: a key has one role everywhere it
can go. Back up before deleting.

Only a SHA-256 of the secret is stored, so a lost key cannot be recovered, only replaced (rotate by
creating a new key, switching clients, then revoking the old one). Prometheus must scrape `/metrics`
with a reader key (`authorization: {credentials: aijp_...}` in the scrape config).

Before exposing it beyond one machine:

- [ ] Put it behind a reverse proxy that terminates TLS, rate-limits, and caps request body size.
      The app authenticates but does not do those. A pre-body gate refuses unauthenticated writes
      and oversized declared `Content-Length` before parsing, yet a well-formed fake token or a
      chunked body still reaches the parser, so the proxy cap matters. Do not publish port 8000
      directly. Never run with `AIJP_AUTH_ENABLED=false` on a reachable host.
- [ ] Set a real `POSTGRES_PASSWORD`; keep the database port unpublished (drop the `ports:` entry
      for `db`) or on loopback.
- [ ] Block `/metrics` and `/docs` at the proxy, or set `AIJP_METRICS_ENABLED=false`. Metrics show
      traffic patterns; `/docs` shows the whole API.
- [ ] Keep the container hardening: non-root user, read-only root filesystem, no capabilities,
      `no-new-privileges` (all set in `docker-compose.yml` and asserted in CI).
- [ ] Treat everything indexed as untrusted input. The prompts tell the model to ignore
      instructions inside documents, and the UI renders all such text as text under a strict CSP,
      but a prompt-injection defence is never absolute. Do not index documents from people you
      do not trust into a deployment that others rely on.
- [ ] Give people the lowest role they need; issue expiring keys for anything automated. The audit
      trail (`audit_events`) stores identifiers and counts, never document text.
- [ ] The MCP server is local stdio and **bypasses API authentication**: it inherits the trust of
      whoever launches it, and it is read-only. Do not expose it over a network.

## 5. Monitoring

### Endpoints

| Path | Use |
|---|---|
| `/health` | Liveness: the process is up. Used by the container `HEALTHCHECK` |
| `/health/ready` | Readiness: database reachable and pgvector installed. Use for load balancer checks |
| `/status` | Human-oriented: database counts, Ollama reachability, models installed, gate settings |
| `/metrics` | Prometheus exposition |

### Metrics

Labels are always small fixed sets (route *templates*, refusal reasons, verdicts), never user input.

| Metric | Labels | What it tells you |
|---|---|---|
| `http_requests_total` | method, route, status (`2xx`...) | Traffic and error rate |
| `http_request_duration_seconds` | method, route | Latency. Buckets reach 80 s because `/ask` and consistency checks call a local model |
| `ask_outcomes_total` | outcome, reason | Answered vs refused, and why (`insufficient_evidence`, `model_declined`, `uncited_answer`, `calculation_failed`, `ungrounded_number`, `answer_truncated`). A rising `answer_truncated` rate means the model is rambling: look at the questions, do not just raise the cap |
| `llm_tokens_total` | kind, source | Prompt and completion tokens, for `ask` and `agent` |
| `dependency_errors_total` | dependency | Embedding or LLM failures (each also returns 503) |
| `escalation_total` | outcome (`used`, `fallback`) | Answers re-checked with thinking. A rising `fallback` share means the re-check is being cut off (slow GPU, contention) and numeric answers are silently back to the first, weaker answer |
| `rerank_total` | outcome (`ok`, `fallback`) | Reranker calls; a rising `fallback` share means the model is returning unusable grades and search is silently back to plain retrieval order |
| `agent_runs_total` | workflow, verdict | Consistency-check outcomes (or `failed`) |
| `agent_actions_total` | kind, status | Human decisions on drafted actions |

Metrics are per process, so run **one uvicorn worker per container** and scale by adding
containers (Prometheus scrapes each), as the image does.

```yaml
# prometheus.yml
scrape_configs:
  - job_name: project-intelligence
    metrics_path: /metrics
    static_configs:
      - targets: ["api:8000"]
```

### Alerts worth having

```promql
# Server errors above 5% of requests for 10 minutes
sum(rate(http_requests_total{status="5xx"}[10m])) / sum(rate(http_requests_total[10m])) > 0.05

# /ask p95 latency above 60 s (a local model is slow; this catches a stuck or overloaded one)
histogram_quantile(0.95, sum by (le) (rate(http_request_duration_seconds_bucket{route="/ask"}[15m]))) > 60

# A dependency is failing
sum by (dependency) (increase(dependency_errors_total[10m])) > 0

# Refusals jumped: documents not embedded, model swapped, or the corpus drifted
sum(rate(ask_outcomes_total{outcome="refused"}[1h])) / sum(rate(ask_outcomes_total[1h])) > 0.5
```

The refusal ratio has no universal threshold. Use the refusal rates in your own evaluation reports
as the baseline and alert on a sustained departure from it.

### Logs

Every line on stdout is one JSON object. Application lines carry a `request_id`; the same id is
returned in the `X-Request-ID` response header and appears on the lines for the calls made to Ollama
during that request, so a single id traces a slow request end to end:

```bash
docker compose logs api --no-log-prefix | jq 'select(.request_id == "e2e-0002")'
docker compose logs api --no-log-prefix | jq 'select(.route == "/ask") | .duration_ms'
```

Request lines record method, route, status and duration. **They never record query strings or
bodies**, because those contain questions and document text.

## 6. Operations

### Backup and restore

All state is in PostgreSQL:

```bash
docker compose exec -T db pg_dump -U aijp -d aijp -Fc > aijp-$(date +%F).dump
docker compose exec -T db createdb -U aijp aijp_restored
docker compose exec -T db pg_restore -U aijp -d aijp_restored < aijp-2026-09-20.dump
```

Embeddings are part of the dump, so restoring does not require re-embedding. Test a restore before
you rely on backups.

Verified with real data: after a dump and a restore into a fresh database, the row counts, an MD5
over all passage text, an MD5 over all embedding vectors, and all four indexes (primary key,
document id, HNSW vector, full-text) were identical. In PowerShell, write the dump inside the
container (`pg_dump ... -f /tmp/aijp.dump`, then `docker cp`) because PowerShell's `>` redirection
corrupts binary output; the commands above are for a POSIX shell. Restoring into a *fresh*
database (`createdb`, then `pg_restore -d <new>`) was tested; restoring over a live database with
`--clean` was not.

### Upgrades and schema changes

The schema is managed by **Alembic** (`app/migrations/`). On start the app applies any pending
migrations under a PostgreSQL advisory lock, so replicas booting together do not race. Manual
control:

```bash
docker compose exec api python -m app.migrate current   # revision the database is at
docker compose exec api python -m app.migrate check     # exit 1 if it is behind (CI runs this)
docker compose exec api python -m app.migrate upgrade   # what startup does
```

- A database created before Alembic (tables, no `alembic_version`) is adopted automatically: its
  columns are brought up to date, then it is stamped as the baseline `0001`. No data is touched.
- **Back up before any release that adds a revision** (`pg_dump`, section above). Migrations run
  in one transaction per revision and can fail half-way through a data change; a backup is the
  rollback plan. `downgrade` exists for the baseline only and drops all tables.
- Changing a model without a revision fails a test (`tests/test_migrations.py` compares the
  migrated schema with the models). To write one: edit `app/models.py`, then
  `uv run alembic revision --autogenerate -m "what changed"`, **read and edit the generated
  file** (autogenerate misses renames and data moves), and run `uv run pytest`.
- Revision `0002` (projects) is a DATA migration: it creates a `default` project, moves every
  existing document, run and task into it, then replaces the global unique(sha256) with
  unique(project_id, sha256). Existing keys stay unscoped. **Back up first** (`pg_dump`, above).
  Downgrading is refused while the same file exists in two projects.
- The embedding dimension is read from settings when the baseline runs. Changing it later is a
  data migration (new column, re-embed, swap), not an automatic one.

### Changing the embedding model

Vectors from different models are not comparable. Changing `AIJP_EMBEDDING_MODEL` means: pick a
model with the same dimension (or migrate the column), clear the embeddings, run `POST /embeddings`,
then re-run the evaluations and recalibrate both gates.

### Troubleshooting

| Symptom | Check |
|---|---|
| `/status` shows Ollama unreachable | From the container: is `host.docker.internal` resolving (Linux needs the `extra_hosts` entry, already set)? Is Ollama listening on all interfaces, not only localhost? |
| Ask and search return 503 | `dependency_errors_total{dependency=...}` says which one; `/status` lists installed models |
| Everything is refused | Documents are stored but not embedded (`/status` shows pending passages; the UI Documents page has an Embed button) |
| Ask takes 10 to 40 s | Expected with a local 10B model. See the latency figures in `eval/results` |
| API restarts in a loop | `docker compose logs api`: usually the database is not ready or the password does not match the volume |
| Every new database connection from the host takes 20 to 30 s | Use `127.0.0.1`, not `localhost`. Compose publishes the database on IPv4 loopback only, and on Docker Desktop `localhost` resolves to `::1` first, which is silently dropped, so each new connection waits for that attempt to time out before falling back to IPv4. (Measured here: 0.02 s via `127.0.0.1`, 30 s via `localhost`.) The defaults already use `127.0.0.1`; only an old `.env` needs changing |

## 7. CI

`.github/workflows/ci.yml` runs three jobs on every push and pull request:

1. **Lint, types, tests**: `ruff format --check`, `ruff check`, `mypy`, and the full test suite
   against a real pgvector database. A final step **fails the build if any test was skipped**,
   because the integration tests skip themselves when the database is unreachable and CI must not
   go green while testing nothing.
2. **Container**: builds the image, starts the real stack, and smoke-tests health, readiness, the
   UI, `/metrics`, the request-id header, JSON logs and the container security posture (non-root,
   read-only filesystem, no capabilities).
3. **Dependency audit**: `pip-audit` over exactly the locked runtime dependencies.

Actions are referenced by major version tag. Pinning to commit SHAs is stronger against
supply-chain attacks; Dependabot (configured in `.github/dependabot.yml`) is set up to keep whatever
is pinned current.

The repository is a local git repository (one commit) that has not been pushed anywhere, so the
workflow itself has not run on GitHub. What was done instead (see section 9): `actionlint` passes,
and all three jobs' steps were run from a fresh `git clone` of the commit, which proves nothing the
working directory supplied silently (an ignored file, a stale virtualenv) is needed.

To publish it (create an EMPTY repository on GitHub first, private is a sensible default):

```bash
git remote add origin https://github.com/<you>/<repo>.git
git push -u origin main
```

Then open the repository's **Actions** tab. Expect the first run to be the real test: differences
between this Windows machine and GitHub's Ubuntu runners (paths, the Docker `host-gateway` entry,
action versions) are the most likely place for a surprise, and only that run can show them.

There is deliberately no deploy job yet: nothing is published to a registry automatically. To
publish by hand: `docker build -t <registry>/project-intelligence:<tag> .` then `docker push`.

## 8. Cloud reference architecture (designed, not deployed)

I have no cloud account here, so **nothing in this section has been deployed or tested**. It is a
design to evaluate, not a recipe known to work.

### The constraint that shapes everything: the language models

The API, database and UI are ordinary and easy to host. The hard part is the models. Ollama running
a 10-billion-parameter model wants a GPU or a lot of memory, and an always-on GPU host is the main
cost driver by a wide margin. There are two honest options:

1. **Run Ollama on a GPU VM** and point `AIJP_OLLAMA_BASE_URL` at it. Nothing in the code changes.
2. **Use a hosted model API** (Azure OpenAI, AWS Bedrock, or similar). This is a small code change
   because both model dependencies are `Protocol`s (`EmbeddingProvider`, `LLMProvider`): write one
   provider class each. It is *not* a small operational change: a different embedding model changes
   the vector dimension and every similarity score, so you must migrate the column, re-embed, re-run
   both evaluations and recalibrate both gates. Hosted models also send document text to a third
   party, which may not be acceptable for the documents you index.

### Azure sketch

- **API**: Azure Container Apps (one container, scale on HTTP concurrency; keep one uvicorn worker per replica).
- **Database**: Azure Database for PostgreSQL Flexible Server with the `vector` extension allow-listed and enabled.
- **Secrets**: Key Vault, injected as environment variables.
- **Auth**: Container Apps built-in authentication (Microsoft Entra ID) in front of the app.
- **Observability**: Log Analytics for the JSON logs; Azure Monitor managed Prometheus to scrape `/metrics`.

### AWS sketch

- **API**: ECS on Fargate (or App Runner) behind an Application Load Balancer.
- **Database**: RDS for PostgreSQL with the `pgvector` extension.
- **Secrets**: Secrets Manager. **Auth**: ALB with Cognito or OIDC.
- **Observability**: CloudWatch Logs for the JSON logs; Amazon Managed Service for Prometheus.

### Cost drivers (no prices quoted)

Prices change and depend on region and commitment, so use each provider's calculator. What to
estimate: always-on compute for the API; the managed database (size, storage, backups); the model
(GPU hours for self-hosting, or tokens for a hosted API; `llm_tokens_total` and the per-query token
counts in the evaluation reports give you real volumes to plug in); log ingestion and retention;
and egress. If you only need a portfolio demo, the cheapest real deployment is probably the same
compose stack on a single small VM behind a TLS-terminating, authenticating proxy, with the model
question answered by either a GPU VM you start on demand or a hosted API.

### Scaling notes

- The API keeps no state between requests, so it scales by adding replicas.
- Each request that calls the model holds a worker thread for 10 to 40 seconds, so concurrency is
  limited by threads and by the model host, not by CPU in the API. Watch the latency metrics.
- Checks and asks are synchronous. Long work would need a queue, which does not exist yet.

## 9. What has and has not been verified

Verified on this machine (Windows, Docker Desktop, real Ollama models):

- The image builds from the pinned `uv` and the lockfile; it is 335 MB.
- The stack starts and both containers report healthy; ports are bound to loopback only.
- Inside the running container: uid 10001, read-only root filesystem (writes to `/srv` fail),
  zero effective capabilities, `no-new-privileges` set.
- The container reaches host Ollama; a real question uploaded, embedded and asked through the
  container returned a cited answer, and `/metrics` recorded the outcome and token counts.
- Every log line is JSON, and the request id links the request line to the Ollama calls it made.
- The MCP server runs over stdio inside the container with all seven tools.
- The CI job commands run locally, including the skip guard, which passes with a healthy database
  (565 tests, 0 skipped) and fails when the database is unreachable (skips).
- **From a fresh `git clone` of the commit** (no `.venv`, no caches, only tracked files): the
  locked install, `ruff format --check`, `ruff check`, `mypy`, all 457 tests with the skip guard
  taken verbatim from `ci.yml`, the image build, the container under the compose hardening (uid
  10001, read-only filesystem, healthy, `/health` and `/health/ready` answer, an unauthenticated
  request gets 401, `app.migrate check` reports the latest revision, every log line is JSON), and
  `pip-audit` (no known vulnerabilities). `actionlint` reports no problems in the workflow.
- Authentication against the real stack: 401 without a key (including a body-less write rejected
  before parsing), role checks (reader gets 403 on writes), a revoked key stops working on the next
  request, and the same steps as the CI auth smoke test pass in the container. A real browser
  session was driven through sign-in as reader and as approver.
- Projects, against the real stack with real models: the same question about the same file path
  answered from each project's own text (`PINEAPPLE-42` versus `ZUCCHINI-7`), a confined key
  refused with an identical 404 for another project and for a nonexistent one, its uploads into
  another project refused, another project's document not readable or deletable by id, and a
  browser session switching projects and signing in with a confined key.
- The `0002` migration on a database holding the real embedded corpus (73 chunks): text and
  vectors have an identical fingerprint before and after, every document lands in the default
  project, vector search still works, and the HNSW and full-text indexes are intact.
- Escalation, real stack and real models: a numeric question and two plain lookups (only the numeric one
  attempted a re-check); the token cap stops generation exactly at the cap; on a GPU shared with a
  game the re-check timed out after 45 s (total 50.8 s instead of 160 s) and the correct first answer
  was returned. Latency figures elsewhere were measured on an idle machine and will be worse under
  load.
- `pip-audit` reports no known vulnerabilities in the 50 locked runtime packages, as of the run.

**Not** verified:

- The `classify` and `cue` escalation modes beyond one held-out set (v5) and one non-independent one (v4); the planned replication on the other sets was not run.

- The GitHub Actions workflow has never run on GitHub (its steps were reproduced locally, and
  `actionlint` is clean, but the Ubuntu runners themselves are untested).
- The optional `ollama` compose profile: its configuration renders, but the image was not pulled or run.
- GPU passthrough for the Ollama container, and Linux hosts (the `host-gateway` entry is standard but untested here).
- Any cloud deployment, in any form.
- Behaviour under concurrent load. No load test has been run.
