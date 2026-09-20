import json
import logging
import re

import pytest
from fastapi.testclient import TestClient
from prometheus_client import REGISTRY

from app import main as app_main
from app.api.ask import get_llm
from app.api.search import get_embedder
from app.config import Settings, get_settings
from app.llm import LLMError
from app.main import app
from app.observability import JsonFormatter, request_id_var
from tests.fakes import DownEmbedder, FakeEmbedder, ScriptedLLM


def sample(name: str, **labels: str) -> float:
    return REGISTRY.get_sample_value(name, labels) or 0.0


# ------------------------------------------------------------------ JSON logging


def _record(msg="hello", exc_info=None, **extra) -> logging.LogRecord:
    logger = logging.getLogger("test.observability")
    record = logger.makeRecord(
        "test.observability", logging.INFO, __file__, 1, msg, (), exc_info, extra=extra
    )
    return record


def test_json_formatter_emits_valid_json_with_context_and_extras() -> None:
    token = request_id_var.set("req-abc12345")
    try:
        line = JsonFormatter().format(_record("request", method="GET", status=200, duration_ms=1.5))
    finally:
        request_id_var.reset(token)
    data = json.loads(line)  # one line, valid JSON
    assert "\n" not in line
    assert data["msg"] == "request" and data["level"] == "INFO"
    assert data["request_id"] == "req-abc12345"
    assert (data["method"], data["status"], data["duration_ms"]) == ("GET", 200, 1.5)
    assert data["ts"].endswith("+00:00")


def test_json_formatter_includes_exceptions_without_breaking_the_line() -> None:
    try:
        raise ValueError("boom\nwith newline")
    except ValueError:
        import sys

        line = JsonFormatter().format(_record("failed", exc_info=sys.exc_info()))
    assert "\n" not in line  # the traceback is a JSON string, not extra log lines
    assert "ValueError: boom" in json.loads(line)["exc"]


# ------------------------------------------------------------------ request context


def test_every_response_carries_a_generated_request_id() -> None:
    response = TestClient(app).get("/health")
    assert re.fullmatch(r"[0-9a-f]{32}", response.headers["x-request-id"])


def test_a_safe_incoming_request_id_is_echoed() -> None:
    response = TestClient(app).get("/health", headers={"X-Request-ID": "trace-1234.abc_9"})
    assert response.headers["x-request-id"] == "trace-1234.abc_9"


@pytest.mark.parametrize(
    "bad", ["short", "has space in it 123", "semi;colon;12345", "x" * 65, "é" * 10]
)
def test_an_unsafe_incoming_request_id_is_replaced_not_logged(bad, caplog) -> None:
    with caplog.at_level(logging.INFO, logger="app.request"):
        response = TestClient(app).get("/health", headers={"X-Request-ID": bad.encode("latin-1")})
    assert response.headers["x-request-id"] != bad
    assert re.fullmatch(r"[0-9a-f]{32}", response.headers["x-request-id"])


def test_a_request_is_logged_once_with_route_status_and_duration(caplog) -> None:
    with caplog.at_level(logging.INFO, logger="app.request"):
        TestClient(app).get("/health")
    [record] = [r for r in caplog.records if r.name == "app.request"]
    assert (record.method, record.route, record.status) == ("GET", "/health", 200)
    assert record.duration_ms >= 0


def test_query_strings_and_bodies_never_reach_the_logs(caplog) -> None:
    with caplog.at_level(logging.INFO, logger="app.request"):
        TestClient(app).get("/health?secret=hunter2&q=my+private+question")
    text = " ".join(json.dumps(r.__dict__, default=str) for r in caplog.records)
    assert "hunter2" not in text and "private" not in text


# ------------------------------------------------------------------ HTTP metrics


def test_http_metrics_count_by_route_template_and_status_class() -> None:
    labels = {"method": "GET", "route": "/eval/reports/{name}", "status": "4xx"}
    before = sample("http_requests_total", **labels)
    client = TestClient(app)
    for name in ("nope", "nada", "nothing"):  # three different ids, one label
        assert client.get(f"/eval/reports/{name}").status_code == 404
    assert sample("http_requests_total", **labels) == before + 3
    count = sample(
        "http_request_duration_seconds_count", method="GET", route="/eval/reports/{name}"
    )
    assert count >= 3


def test_unmatched_paths_share_one_label_so_scanners_cannot_explode_cardinality() -> None:
    labels = {"method": "GET", "route": "unmatched", "status": "4xx"}
    before = sample("http_requests_total", **labels)
    client = TestClient(app)
    for path in ("/wp-login.php", "/.env", "/admin/../x"):
        client.get(path)
    assert sample("http_requests_total", **labels) == before + 3
    exposition = client.get("/metrics").text
    assert "wp-login" not in exposition and ".env" not in exposition


def test_metrics_endpoint_serves_prometheus_text_and_is_not_in_the_api_docs() -> None:
    response = TestClient(app).get("/metrics")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/plain")
    for family in ("http_requests_total", "ask_outcomes_total", "llm_tokens_total"):
        assert f"# TYPE {family}" in response.text
    assert "/metrics" not in app.openapi()["paths"]


def test_metrics_can_be_switched_off(monkeypatch) -> None:
    monkeypatch.setattr(app_main, "get_settings", lambda: Settings(metrics_enabled=False))
    assert TestClient(app).get("/metrics").status_code == 404


# ------------------------------------------------------------------ domain metrics (integration)

MD = b"# Towers\n\n## Poison\nPoison stacks up to 3 times.\n"


@pytest.fixture
def env(client):
    app.dependency_overrides[get_embedder] = FakeEmbedder
    app.dependency_overrides[get_settings] = lambda: Settings(
        chunk_max_chars=300, chunk_overlap_chars=60, min_evidence_score=0.2
    )
    client.post("/documents", files={"file": ("t.md", MD)}, data={"source_path": "d/t.md"})
    client.post("/embeddings")

    def install(reply):
        llm = ScriptedLLM(reply)
        app.dependency_overrides[get_llm] = lambda: llm
        return llm

    yield type("Env", (), {"api": client, "install": staticmethod(install)})
    app.dependency_overrides.pop(get_llm, None)
    app.dependency_overrides.pop(get_embedder, None)


@pytest.mark.integration
def test_ask_outcomes_and_tokens_are_counted(env) -> None:
    answered = {"outcome": "answered", "reason": "none"}
    gate = {"outcome": "refused", "reason": "insufficient_evidence"}
    declined = {"outcome": "refused", "reason": "model_declined"}
    before = {
        k: sample("ask_outcomes_total", **v)
        for k, v in {"a": answered, "g": gate, "d": declined}.items()
    }
    tokens_before = sample("llm_tokens_total", kind="prompt", source="ask")

    env.install({"answerable": True, "answer": "3 [1]", "citations": [1]})
    assert env.api.post("/ask", json={"question": "poison stack limit"}).status_code == 200
    env.api.post("/ask", json={"question": "zebra quantum spaghetti"})  # stopped by the gate
    env.install({"answerable": False, "answer": "", "citations": []})
    env.api.post("/ask", json={"question": "poison stack limit"})

    assert sample("ask_outcomes_total", **answered) == before["a"] + 1
    assert sample("ask_outcomes_total", **gate) == before["g"] + 1
    assert sample("ask_outcomes_total", **declined) == before["d"] + 1
    # Only the two calls that reached the model spent tokens (120 each from the scripted LLM).
    assert sample("llm_tokens_total", kind="prompt", source="ask") == tokens_before + 240


@pytest.mark.integration
def test_dependency_failures_are_counted_by_dependency(env) -> None:
    emb, llm = {"dependency": "embedding"}, {"dependency": "llm"}
    before = (sample("dependency_errors_total", **emb), sample("dependency_errors_total", **llm))

    app.dependency_overrides[get_embedder] = DownEmbedder
    assert env.api.post("/search", json={"query": "poison"}).status_code == 503
    app.dependency_overrides[get_embedder] = FakeEmbedder
    env.install(LLMError("connection refused"))
    assert env.api.post("/ask", json={"question": "poison stack limit"}).status_code == 503

    assert sample("dependency_errors_total", **emb) == before[0] + 1
    assert sample("dependency_errors_total", **llm) == before[1] + 1


@pytest.mark.integration
def test_agent_runs_and_human_decisions_are_counted(env) -> None:
    verdict = {"workflow": "consistency_check", "verdict": "consistent"}
    approved = {"kind": "create_task", "status": "executed"}
    before = (sample("agent_runs_total", **verdict), sample("agent_actions_total", **approved))

    env.install(
        {
            "verdict": "consistent",
            "explanation": "ok [D1] [C1]",
            "design_refs": ["D1"],
            "implementation_refs": ["C1"],
        }
    )
    app.dependency_overrides[get_settings] = lambda: Settings(
        chunk_max_chars=300, chunk_overlap_chars=60, consistency_min_cosine=0.0
    )
    env.api.post(
        "/documents",
        files={"file": ("e.py", b"def apply_poison():\n    pass\n")},
        data={"source_path": "src/e.py"},
    )
    env.api.post("/embeddings")
    run = env.api.post("/agent/consistency-checks", json={"claim": "poison stacks up to 3 times"})
    assert run.status_code == 201 and run.json()["verdict"] == "consistent"
    assert sample("agent_runs_total", **verdict) == before[0] + 1

    env.install(
        {
            "verdict": "potential_discrepancy",
            "explanation": "differs [D1] [C1]",
            "design_refs": ["D1"],
            "implementation_refs": ["C1"],
        }
    )
    action_id = env.api.post(
        "/agent/consistency-checks", json={"claim": "poison stacks up to 3 times"}
    ).json()["actions"][0]["id"]
    assert env.api.post(f"/agent/actions/{action_id}/approve").status_code == 200
    assert sample("agent_actions_total", **approved) == before[1] + 1


def test_the_container_log_config_is_valid_and_uses_the_json_formatter() -> None:
    import importlib
    from pathlib import Path

    config = json.loads((Path(app_main.__file__).parent / "uvicorn_logging.json").read_text())
    assert config["version"] == 1
    module, _, cls = config["formatters"]["json"]["()"].rpartition(".")
    assert getattr(importlib.import_module(module), cls) is JsonFormatter
    assert config["loggers"]["uvicorn"]["handlers"] == ["stdout"]
    assert config["handlers"]["stdout"]["stream"] == "ext://sys.stdout"  # never stderr-mixed


def test_json_formatter_drops_uvicorns_ansi_colour_duplicate() -> None:
    line = JsonFormatter().format(_record("Started", color_message="\x1b[36mStarted\x1b[0m"))
    assert "color_message" not in json.loads(line) and "\x1b" not in line
