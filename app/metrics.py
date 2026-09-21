"""Prometheus metrics, chosen to answer the questions this project already cares about.

Beyond generic HTTP timing, they track what the evaluation milestones measured: how often answers
are refused and why, how many tokens the model spends, how often a dependency fails, and what the
agent workflow decides. Label values are always from small fixed sets (route *templates*, refusal
reasons, verdicts): never user input, so cardinality stays bounded.

Single-process only. Run one uvicorn worker (or switch to prometheus multiprocess mode first).
"""

from prometheus_client import Counter, Histogram

from app.models import AgentAction, AgentRun
from app.qa import Answer

HTTP_REQUESTS = Counter(
    "http_requests_total",
    "HTTP requests by method, route template and status class.",
    ["method", "route", "status"],
)
HTTP_DURATION = Histogram(
    "http_request_duration_seconds",
    "HTTP request duration in seconds, by method and route template.",
    ["method", "route"],
    # Wide top end: /ask and consistency checks call a local LLM and take tens of seconds.
    buckets=(0.005, 0.025, 0.1, 0.5, 1, 2.5, 5, 10, 20, 40, 80),
)
ASK_OUTCOMES = Counter(
    "ask_outcomes_total",
    "Answers by outcome; refusals carry their reason (insufficient_evidence, model_declined, ...).",
    ["outcome", "reason"],
)
RERANKS = Counter(
    "rerank_total",
    "Reranker calls by outcome: ok, or fallback (it failed and retrieval order was kept).",
    ["outcome"],
)
ESCALATIONS = Counter(
    "escalation_total",
    "Answers re-checked with the thinking model, by outcome (used, fallback).",
    ["outcome"],
)
LLM_TOKENS = Counter(
    "llm_tokens_total", "Tokens reported by the language model provider.", ["kind", "source"]
)
DEPENDENCY_ERRORS = Counter(
    "dependency_errors_total",
    "Failures talking to a dependency (embedding or llm).",
    ["dependency"],
)
AGENT_RUNS = Counter(
    "agent_runs_total",
    "Agent workflow runs by workflow and final verdict (or 'failed').",
    ["workflow", "verdict"],
)
AGENT_ACTIONS = Counter(
    "agent_actions_total",
    "Human decisions on drafted actions, by action kind and resulting status.",
    ["kind", "status"],
)


AUTH_FAILURES = Counter(
    "auth_failures_total",
    "Rejected credentials by internal reason (missing, malformed, unknown, mismatch, revoked, "
    "expired). The client only ever sees one generic 401.",
    ["reason"],
)
AUTH_DENIED = Counter(
    "auth_denied_total",
    "Authenticated requests refused for lacking the required role.",
    ["required_role"],
)


def record_auth_failure(reason: str) -> None:
    AUTH_FAILURES.labels(reason=reason).inc()


def record_auth_denied(required_role: str) -> None:
    AUTH_DENIED.labels(required_role=required_role).inc()


def status_class(status: int) -> str:
    return f"{status // 100}xx"


def record_ask(result: Answer) -> None:
    ASK_OUTCOMES.labels(
        outcome="refused" if result.refused else "answered", reason=result.reason or "none"
    ).inc()
    if result.reranked is not None:
        record_rerank(result.reranked)
    if result.escalated is not None:
        ESCALATIONS.labels(outcome=result.escalated).inc()
    LLM_TOKENS.labels(kind="prompt", source="ask").inc(result.prompt_tokens)
    LLM_TOKENS.labels(kind="completion", source="ask").inc(result.completion_tokens)


def record_rerank(ok: bool) -> None:
    RERANKS.labels(outcome="ok" if ok else "fallback").inc()


def record_dependency_error(dependency: str) -> None:
    DEPENDENCY_ERRORS.labels(dependency=dependency).inc()


def record_agent_run(run: AgentRun) -> None:
    AGENT_RUNS.labels(workflow=run.workflow, verdict=run.verdict or run.status).inc()
    usage = (run.result or {}).get("usage") or {}
    LLM_TOKENS.labels(kind="prompt", source="agent").inc(usage.get("prompt_tokens", 0))
    LLM_TOKENS.labels(kind="completion", source="agent").inc(usage.get("completion_tokens", 0))


def record_action(action: AgentAction) -> None:
    AGENT_ACTIONS.labels(kind=action.kind, status=action.status).inc()
