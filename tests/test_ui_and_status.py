import pytest
from fastapi.testclient import TestClient

from app.api.system import get_ollama_probe
from app.config import Settings, get_settings
from app.main import app
from app.schemas import ModelStatus, OllamaStatus

# ------------------------------------------------------------------ static UI (no database)


def test_root_redirects_to_ui() -> None:
    response = TestClient(app).get("/", follow_redirects=False)
    assert response.status_code in (302, 307)
    assert response.headers["location"] == "/ui/"


def test_ui_index_is_served_with_strict_csp() -> None:
    response = TestClient(app).get("/ui/")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    csp = response.headers["content-security-policy"]
    assert "default-src 'self'" in csp and "script-src 'self'" in csp
    assert "unsafe-inline" not in csp and "unsafe-eval" not in csp
    assert "frame-ancestors 'none'" in csp
    assert response.headers["x-content-type-options"] == "nosniff"


def test_ui_page_has_no_inline_script_or_style() -> None:
    html = TestClient(app).get("/ui/").text.lower()
    assert "<style" not in html and " style=" not in html and "onclick=" not in html
    scripts = html.count("<script")
    assert scripts >= 1 and html.count("<script") == html.count('src="')  # every script is external


def test_ui_assets_carry_the_csp_too() -> None:
    response = TestClient(app).get("/ui/style.css")
    assert response.status_code == 200
    assert "content-security-policy" in response.headers


def test_api_docs_are_not_restricted_by_the_ui_csp() -> None:
    assert "content-security-policy" not in TestClient(app).get("/docs").headers


# ------------------------------------------------------------------ evaluation reports


@pytest.fixture
def reports_dir(tmp_path):
    (tmp_path / "qa-2026-09-20.md").write_text("# QA\n| a | b |\n", encoding="utf-8")
    (tmp_path / "retrieval-2026-09-19.md").write_text("# Retrieval\n", encoding="utf-8")
    (tmp_path / "qa-2026-09-20-smoke.md").write_text("# smoke\n", encoding="utf-8")
    (tmp_path / "consistency-2026-09-20.md").write_text("# Consistency\n", encoding="utf-8")
    (tmp_path / "qa-run.log").write_text("scratch", encoding="utf-8")
    (tmp_path / "notes.md").write_text("not a report", encoding="utf-8")
    app.dependency_overrides[get_settings] = lambda: Settings(eval_results_dir=tmp_path)
    yield tmp_path
    app.dependency_overrides.clear()


def test_lists_only_real_reports_newest_first(reports_dir) -> None:
    items = TestClient(app).get("/eval/reports").json()["items"]
    assert [i["name"] for i in items] == [
        "qa-2026-09-20-smoke",
        "qa-2026-09-20",
        "consistency-2026-09-20",
        "retrieval-2026-09-19",
    ]
    assert items[0]["smoke"] is True and items[1]["kind"] == "qa"


def test_report_content_is_returned(reports_dir) -> None:
    body = TestClient(app).get("/eval/reports/qa-2026-09-20").json()
    assert body["markdown"].startswith("# QA")


@pytest.mark.parametrize(
    "name",
    [
        "notes",
        "qa-run",
        "..%2Fsecret",
        "qa-2026-09-20.md",
        "qa-2026-9-20",
        "qa-2026-09-20%2F..",
        "missing",
    ],
)
def test_report_names_outside_the_allowlist_are_404(reports_dir, name) -> None:
    assert TestClient(app).get(f"/eval/reports/{name}").status_code == 404


def test_missing_results_directory_lists_nothing(tmp_path) -> None:
    app.dependency_overrides[get_settings] = lambda: Settings(eval_results_dir=tmp_path / "nope")
    try:
        assert TestClient(app).get("/eval/reports").json() == {"items": []}
    finally:
        app.dependency_overrides.clear()


# ------------------------------------------------------------------ /status


def _probe(reachable: bool):
    def probe(settings: Settings) -> OllamaStatus:
        return OllamaStatus(
            reachable=reachable,
            base_url=settings.ollama_base_url,
            models=[ModelStatus(role="embedding", name="m", installed=reachable)],
        )

    return lambda: probe


@pytest.mark.integration
def test_status_reports_counts_and_pending_embeddings(client) -> None:
    app.dependency_overrides[get_ollama_probe] = _probe(True)
    try:
        client.post("/documents", files={"file": ("a.md", b"# A\nhello\n\n## B\nworld\n")})
        body = client.get("/status").json()
    finally:
        app.dependency_overrides.pop(get_ollama_probe, None)
    assert body["database"]["reachable"] and body["database"]["pgvector"]
    assert body["database"]["documents"] == 1
    assert body["database"]["chunks"] == body["database"]["pending_chunks"] == 2
    assert body["database"]["embedded_chunks"] == 0
    assert body["ollama"]["reachable"] is True
    assert body["config"]["retrieval_mode"] == "vector"
    assert "database_url" not in str(body)  # never leak connection strings


@pytest.mark.integration
def test_status_stays_200_when_ollama_is_down(client) -> None:
    app.dependency_overrides[get_ollama_probe] = _probe(False)
    try:
        response = client.get("/status")
    finally:
        app.dependency_overrides.pop(get_ollama_probe, None)
    assert response.status_code == 200
    assert response.json()["ollama"]["reachable"] is False
