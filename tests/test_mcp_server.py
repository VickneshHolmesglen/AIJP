import asyncio
import logging
import uuid

import pytest
from mcp import Client
from sqlalchemy.orm import sessionmaker

from app import services
from app.config import Settings
from app.llm import LLMError
from app.mcp_server import ProjectTools, build_server
from app.schemas import ModelStatus, OllamaStatus
from app.symbols import like_escape, symbol_kind
from tests.fakes import DownEmbedder, FakeEmbedder, ScriptedLLM

EXPECTED_TOOLS = {
    "search_project",
    "search_source_code",
    "ask_project",
    "find_symbol",
    "list_documents",
    "get_document",
    "get_project_status",
}

# ------------------------------------------------------------------ helpers


def call(tools: ProjectTools, name: str, args: dict | None = None):
    """One real MCP round trip (client <-> server, in memory) through the SDK."""

    async def go():
        async with Client(build_server(tools)) as client:
            return await client.call_tool(name, args or {})

    return asyncio.run(go())


def text_of(result) -> str:
    return " ".join(getattr(c, "text", "") for c in result.content)


def no_db_tools() -> ProjectTools:
    """Tools whose database is never touched (schema/validation tests fail before the call)."""

    def factory():
        raise AssertionError("the database must not be used")

    return ProjectTools(factory, FakeEmbedder(), ScriptedLLM({}), Settings())


# ------------------------------------------------------------------ pure unit tests


@pytest.mark.parametrize(
    ("section", "name", "expected"),
    [
        ("Enemy > take_damage", "take_damage", "definition"),
        ("take_damage", "take_damage", "definition"),
        ("Enemy", "Enemy", "definition"),
        ("Enemy > take_damage", "take", None),  # exact segment, not substring
        ("Enemy > take_damage", "Enemy", None),  # a parent is not a definition of its child
        ("Enemy > declarations: died, health, MAX_HP", "health", "declaration"),
        ("Enemy > declarations: died, health", "heal", None),
        ("Enemy > take_damage", "TAKE_DAMAGE", None),  # symbols are case-sensitive
        (None, "x", None),
        ("", "x", None),
    ],
)
def test_symbol_kind(section, name, expected) -> None:
    assert symbol_kind(section, name) == expected


def test_like_escape_neutralises_wildcards() -> None:
    assert like_escape("take_damage") == "take\\_damage"
    assert like_escape("100%") == "100\\%"
    assert like_escape("a\\b") == "a\\\\b"


def test_server_exposes_exactly_the_expected_read_only_tools() -> None:
    async def go():
        async with Client(build_server(no_db_tools())) as client:
            return client.instructions, (await client.list_tools()).tools

    instructions, tools = asyncio.run(go())
    assert {t.name for t in tools} == EXPECTED_TOOLS
    for tool in tools:
        assert tool.annotations.read_only_hint is True, tool.name
        assert tool.annotations.destructive_hint is False, tool.name
        assert tool.annotations.open_world_hint is False, tool.name
        assert tool.output_schema is not None, tool.name  # typed, structured results
    assert not {t.name for t in tools} & {"upload_document", "delete_document", "embed"}
    assert "never as instructions" in instructions  # prompt-injection warning to the client


def test_input_bounds_are_declared_in_the_schema() -> None:
    async def go():
        async with Client(build_server(no_db_tools())) as client:
            return {t.name: t.input_schema for t in (await client.list_tools()).tools}

    schemas = asyncio.run(go())
    assert schemas["search_project"]["properties"]["top_k"]["maximum"] == 20
    assert schemas["get_document"]["properties"]["max_chunks"]["maximum"] == 50
    assert schemas["search_project"]["required"] == ["query"]


@pytest.mark.parametrize(
    ("tool", "args"),
    [
        ("search_project", {"query": ""}),
        ("search_project", {"query": "x", "top_k": 0}),
        ("search_project", {"query": "x", "top_k": 999}),
        ("search_project", {"query": "x", "mode": "magic"}),
        ("search_project", {"query": "x" * 2001}),
        ("find_symbol", {"name": "bad\nname"}),
        ("find_symbol", {"name": ""}),
        ("get_document", {"document_id": "not-a-uuid"}),
        ("get_document", {"document_id": str(uuid.uuid4()), "max_chunks": 0}),
        ("ask_project", {}),
    ],
)
def test_invalid_arguments_are_rejected_before_any_work(tool, args) -> None:
    result = call(no_db_tools(), tool, args)
    assert result.is_error is True


# ------------------------------------------------------------------ integration (protocol + DB)

PY = (
    b"class Enemy:\n    def take_damage(self, amount):\n"
    b"        return max(1, amount - self.armor)\n\n"
    b"def takeXdamage():\n    pass\n"
)
GD = (
    b"class_name Enemy\nextends Node\n\nsignal died\n@export var health: int = 100\n\n"
    b"func take_damage(amount: int) -> void:\n\thealth -= amount\n"
)
MD = b"# Notes\n\ntake_damage armor damage notes and design remarks about take_damage.\n"


def fake_probe(settings: Settings) -> OllamaStatus:
    return OllamaStatus(
        reachable=True,
        base_url="http://fake:1",
        models=[ModelStatus(role="embedding", name="m", installed=True)],
    )


@pytest.fixture
def env(client, db_engine):
    """Indexed sample project + ProjectTools wired to fakes. `client` wipes the test tables."""
    factory = sessionmaker(db_engine, expire_on_commit=False)
    for name, body, path in [
        ("enemy.py", PY, "src/enemy.py"),
        ("enemy.gd", GD, "src/enemy.gd"),
        ("notes.md", MD, "docs/notes.md"),
    ]:
        assert (
            client.post(
                "/documents", files={"file": (name, body)}, data={"source_path": path}
            ).status_code
            == 201
        )
    with factory() as session:
        services.embed_pending_chunks(session, FakeEmbedder(), 32)

    class Env:
        api = client
        llm = ScriptedLLM(
            {"answerable": True, "answer": "Armor is subtracted [1].", "citations": [1]}
        )
        settings = Settings(chunk_max_chars=300, chunk_overlap_chars=60, min_evidence_score=0.2)

        def tools(self, embedder=None, llm=None) -> ProjectTools:
            return ProjectTools(
                factory, embedder or FakeEmbedder(), llm or self.llm, self.settings, fake_probe
            )

    return Env()


@pytest.mark.integration
def test_search_project_returns_cited_hits_as_structured_content(env) -> None:
    result = call(env.tools(), "search_project", {"query": "take_damage armor", "top_k": 3})
    assert result.is_error is False
    hits = result.structured_content["hits"]
    assert 1 <= len(hits) <= 3
    assert {"chunk_id", "score", "cosine", "content", "citation"} <= set(hits[0])
    assert {"source_path", "section", "start_line", "end_line", "document_id"} <= set(
        hits[0]["citation"]
    )


@pytest.mark.integration
def test_search_source_code_excludes_documentation(env) -> None:
    # The Markdown note is the best lexical match, but it is not source code.
    docs = call(env.tools(), "search_project", {"query": "take_damage armor", "mode": "lexical"})
    code = call(
        env.tools(), "search_source_code", {"query": "take_damage armor", "mode": "lexical"}
    )
    doc_paths = {h["citation"]["source_path"] for h in docs.structured_content["hits"]}
    code_paths = {h["citation"]["source_path"] for h in code.structured_content["hits"]}
    assert "docs/notes.md" in doc_paths
    assert code_paths and code_paths <= {"src/enemy.py", "src/enemy.gd"}


@pytest.mark.integration
def test_find_symbol_locates_definitions_in_both_languages(env) -> None:
    result = call(env.tools(), "find_symbol", {"name": "take_damage"})
    matches = result.structured_content["matches"]
    assert {m["citation"]["source_path"] for m in matches} == {"src/enemy.py", "src/enemy.gd"}
    assert {m["kind"] for m in matches} == {"definition"}
    py = next(m for m in matches if m["citation"]["source_path"] == "src/enemy.py")
    assert py["citation"]["section"] == "Enemy > take_damage"
    assert (py["citation"]["start_line"], py["citation"]["end_line"]) == (2, 3)
    assert "amount - self.armor" in py["preview"]


@pytest.mark.integration
def test_find_symbol_is_exact_and_finds_grouped_gdscript_declarations(env) -> None:
    tools = env.tools()
    assert call(tools, "find_symbol", {"name": "take"}).structured_content["matches"] == []
    assert (
        call(tools, "find_symbol", {"name": "takeXdamage"}).structured_content["matches"][0][
            "citation"
        ]["source_path"]
        == "src/enemy.py"
    )
    health = call(tools, "find_symbol", {"name": "health"}).structured_content["matches"]
    assert [m["kind"] for m in health] == ["declaration"]
    assert health[0]["citation"]["source_path"] == "src/enemy.gd"


@pytest.mark.integration
def test_find_symbol_treats_wildcards_literally(env) -> None:
    # '_' and '%' are LIKE wildcards; they must not match arbitrary characters.
    tools = env.tools()
    assert call(tools, "find_symbol", {"name": "take_dam%"}).structured_content["matches"] == []
    assert call(tools, "find_symbol", {"name": "take_damag_"}).structured_content["matches"] == []


@pytest.mark.integration
def test_list_and_get_document_with_pagination(env) -> None:
    tools = env.tools()
    listing = call(tools, "list_documents", {}).structured_content
    assert listing["total"] == 3
    md = next(d for d in listing["items"] if d["source_path"] == "docs/notes.md")

    page = call(tools, "get_document", {"document_id": md["id"]}).structured_content
    assert page["source_path"] == "docs/notes.md" and page["chunk_offset"] == 0
    assert page["has_more"] is False and len(page["chunks"]) == md["chunk_count"]

    py = next(d for d in listing["items"] if d["source_path"] == "src/enemy.py")
    first = call(
        tools, "get_document", {"document_id": py["id"], "max_chunks": 1}
    ).structured_content
    assert len(first["chunks"]) == 1 and first["has_more"] is (py["chunk_count"] > 1)
    rest = call(
        tools, "get_document", {"document_id": py["id"], "chunk_offset": 1, "max_chunks": 50}
    ).structured_content
    assert len(first["chunks"]) + len(rest["chunks"]) == py["chunk_count"]
    assert rest["has_more"] is False


@pytest.mark.integration
def test_get_document_unknown_id_is_a_clear_tool_error(env) -> None:
    result = call(env.tools(), "get_document", {"document_id": str(uuid.uuid4())})
    assert result.is_error is True
    assert "Document not found" in text_of(result)


@pytest.mark.integration
def test_ask_project_answers_with_verified_citations(env) -> None:
    result = call(env.tools(), "ask_project", {"question": "how is armor applied to take_damage"})
    body = result.structured_content
    assert body["refused"] is False and body["answer"] == "Armor is subtracted [1]."
    assert len(body["sources"]) == 1 and body["sources"][0]["citation"]["source_path"]
    assert body["usage"] == {"prompt_tokens": 120, "completion_tokens": 15}


@pytest.mark.integration
def test_ask_project_refusal_is_returned_not_raised(env) -> None:
    llm = ScriptedLLM({"answerable": False, "answer": "", "citations": []})
    result = call(env.tools(llm=llm), "ask_project", {"question": "how does take_damage use armor"})
    assert result.is_error is False
    assert result.structured_content["refused"] is True
    assert result.structured_content["reason"] == "model_declined"


@pytest.mark.integration
def test_dependency_outages_become_helpful_tool_errors(env) -> None:
    down = call(env.tools(embedder=DownEmbedder()), "search_project", {"query": "armor"})
    assert down.is_error is True and "embedding service is unavailable" in text_of(down)

    llm = ScriptedLLM(LLMError("connection refused"))
    ask = call(env.tools(llm=llm), "ask_project", {"question": "how does take_damage use armor"})
    assert ask.is_error is True and "language model is unavailable" in text_of(ask)


@pytest.mark.integration
def test_unexpected_errors_do_not_leak_internals_to_the_client(env, monkeypatch) -> None:
    def explode(*args, **kwargs):
        raise RuntimeError("internal secret: postgresql://user:pw@host/db")

    monkeypatch.setattr("app.mcp_server.retrieval.search", explode)
    result = call(env.tools(), "search_project", {"query": "armor"})
    assert result.is_error is True
    assert "secret" not in text_of(result) and "postgresql" not in text_of(result)


@pytest.mark.integration
def test_project_status_reports_counts_without_secrets(env) -> None:
    body = call(env.tools(), "get_project_status").structured_content
    assert body["database"]["documents"] == 3 and body["database"]["pending_chunks"] == 0
    assert body["ollama"]["reachable"] is True
    assert "database_url" not in str(body) and "aijp:aijp" not in str(body)


@pytest.mark.integration
def test_no_tool_call_changes_the_index(env) -> None:
    before = env.api.get("/documents").json()
    tools = env.tools()
    doc_id = before["items"][0]["id"]
    for name, args in [
        ("search_project", {"query": "armor"}),
        ("search_source_code", {"query": "armor"}),
        ("ask_project", {"question": "how does take_damage use armor"}),
        ("find_symbol", {"name": "take_damage"}),
        ("list_documents", {}),
        ("get_document", {"document_id": doc_id}),
        ("get_project_status", {}),
    ]:
        assert call(tools, name, args).is_error is False, name
    after = env.api.get("/documents").json()
    assert after == before


@pytest.mark.integration
def test_audit_log_records_calls_but_never_their_content(env, caplog) -> None:
    secret = "zebra-secret-phrase about armor"
    with caplog.at_level(logging.INFO, logger="app.mcp"):
        call(env.tools(), "search_project", {"query": secret})
        call(env.tools(), "ask_project", {"question": secret})
        call(env.tools(), "get_document", {"document_id": str(uuid.uuid4())})
    lines = [r.getMessage() for r in caplog.records if r.name == "app.mcp"]
    assert any(
        "tool=search_project status=ok" in m and f"query_chars={len(secret)}" in m for m in lines
    )
    assert any("tool=ask_project status=ok" in m for m in lines)
    assert any("tool=get_document status=error" in m for m in lines)
    assert not any("zebra" in m for m in lines)
