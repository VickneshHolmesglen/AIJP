"""Projects: isolation is the property that matters, so it is tested at every layer.

Two projects hold different secrets. Nothing one project stores may ever appear in the other's
search results, prompts, lists, runs, tasks, counts or documents, whichever way it is asked for.
"""

import uuid

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import keys as keys_cli
from app import projects, retrieval, symbols
from app.api.ask import get_llm
from app.api.search import get_embedder
from app.auth import Role, create_key
from app.config import Settings, get_settings
from app.main import app
from app.mcp_server import ProjectTools
from app.models import (
    AgentRun,
    ApiKey,
    AuditEvent,
    Chunk,
    Document,
    Project,
    Task,
)
from tests.fakes import FakeEmbedder, ScriptedLLM

ALPHA_NOTE = b"# Alpha\n\nThe alpha launch code is PINEAPPLE. Alpha towers cost 50 gold.\n"
BETA_NOTE = b"# Beta\n\nThe beta launch code is ZUCCHINI. Beta towers cost 90 gold.\n"
ALPHA_CODE = b"class Enemy:\n    def poison_stacks(self):\n        return 5\n"
DESIGN = b"# Poison\n\nPoison stacks up to 3 times.\n"
CLAIM = "Poison stacks up to 3 times"

pytestmark = pytest.mark.integration


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


class World:
    """Two projects, one key per (role, scope) we need, and helpers that upload as a given key."""

    def __init__(self, client, session: Session) -> None:
        self.client, self.session = client, session
        self.alpha = projects.create_project(session, "alpha", "Alpha")
        self.beta = projects.create_project(session, "beta", "Beta")
        make = lambda name, role, project=None: create_key(  # noqa: E731
            session, name, role, project_id=project.id if project else None
        )[1]
        self.admin = make("admin", Role.approver)  # every project
        self.alpha_editor = make("alpha-editor", Role.editor, self.alpha)
        self.alpha_approver = make("alpha-approver", Role.approver, self.alpha)
        self.beta_editor = make("beta-editor", Role.editor, self.beta)
        self.beta_approver = make("beta-approver", Role.approver, self.beta)
        self.beta_reader = make("beta-reader", Role.reader, self.beta)

    def upload(self, token: str, name: str, content: bytes, project: str | None = None):
        params = {"project": project} if project else {}
        return self.client.post(
            "/documents",
            files={"file": (name, content)},
            data={"source_path": name},
            params=params,
            headers=bearer(token),
        )

    def embed(self, token: str, project: str | None = None):
        params = {"project": project} if project else {}
        return self.client.post("/embeddings", params=params, headers=bearer(token))


@pytest.fixture
def db(client, db_engine):
    with Session(db_engine, expire_on_commit=False) as session:
        yield session


@pytest.fixture
def world(client, db):
    """Authentication ON, fake embedder, and a model that always cites source 1."""
    llm = ScriptedLLM({"answerable": True, "answer": "See [1].", "citations": [1]})
    app.dependency_overrides[get_settings] = lambda: Settings(
        auth_enabled=True,
        chunk_max_chars=300,
        chunk_overlap_chars=60,
        max_upload_bytes=50_000,
        min_evidence_score=0.1,
        consistency_min_cosine=0.05,
    )
    app.dependency_overrides[get_embedder] = FakeEmbedder
    app.dependency_overrides[get_llm] = lambda: llm
    w = World(client, db)
    w.llm = llm
    yield w
    app.dependency_overrides.pop(get_embedder, None)
    app.dependency_overrides.pop(get_llm, None)


@pytest.fixture
def filled(world):
    """Alpha and beta each hold their own secret, embedded."""
    assert world.upload(world.alpha_editor, "note.md", ALPHA_NOTE).status_code == 201
    assert world.upload(world.beta_editor, "note.md", BETA_NOTE).status_code == 201
    assert world.embed(world.alpha_editor).json()["embedded"] > 0
    assert world.embed(world.beta_editor).json()["embedded"] > 0
    return world


# ------------------------------------------------------------------ pure rules


@pytest.mark.parametrize("slug", ["a", "alpha", "team-42", "a" * 40, "x1"])
def test_valid_slugs(slug: str) -> None:
    assert projects.valid_slug(slug) == slug


@pytest.mark.parametrize(
    "slug", ["", "Alpha", "-a", "a-", "a b", "a_b", "a/b", "../x", "a" * 41, "é", "a\n"]
)
def test_invalid_slugs_are_rejected(slug: str) -> None:
    with pytest.raises(projects.ProjectError):
        projects.valid_slug(slug)


# ------------------------------------------------------------------ documents


def test_the_same_file_can_live_in_two_projects_but_only_once_in_each(filled) -> None:
    other = filled.upload(filled.beta_editor, "copy.md", ALPHA_NOTE)  # alpha's exact bytes
    assert other.status_code == 201  # a different project: fine
    again = filled.upload(filled.beta_editor, "copy2.md", ALPHA_NOTE)
    assert again.status_code == 409 and "document_id" in again.json()["detail"]


def test_a_scoped_key_lists_only_its_own_project_and_defaults_to_it(filled) -> None:
    mine = filled.client.get("/documents", headers=bearer(filled.alpha_editor)).json()
    assert [d["source_path"] for d in mine["items"]] == ["note.md"] and mine["total"] == 1
    beta = filled.client.get("/documents", headers=bearer(filled.beta_reader)).json()
    assert beta["total"] == 1
    assert {d["id"] for d in mine["items"]}.isdisjoint(d["id"] for d in beta["items"])


def test_documents_by_id_never_cross_a_scoped_key_boundary(filled, db) -> None:
    beta_doc = db.scalar(select(Document.id).join(Project).where(Project.slug == "beta"))
    alpha_doc = db.scalar(select(Document.id).join(Project).where(Project.slug == "alpha"))
    url = f"/documents/{beta_doc}"
    assert filled.client.get(url, headers=bearer(filled.alpha_editor)).status_code == 404
    assert filled.client.delete(url, headers=bearer(filled.alpha_editor)).status_code == 404
    assert db.get(Document, beta_doc) is not None  # the delete really did nothing
    # A key for that project, and an unscoped key, can both use it.
    assert filled.client.get(url, headers=bearer(filled.beta_reader)).status_code == 200
    assert (
        filled.client.get(f"/documents/{alpha_doc}", headers=bearer(filled.admin)).status_code
        == 200
    )


def test_an_unscoped_key_chooses_the_project_per_request(filled) -> None:
    for slug in ("alpha", "beta"):
        found = filled.client.get(
            "/documents", params={"project": slug}, headers=bearer(filled.admin)
        ).json()
        assert found["total"] == 1
    default = filled.client.get("/documents", headers=bearer(filled.admin)).json()
    assert default["total"] == 0  # 'default' is a third, empty project


def test_a_scoped_key_cannot_reach_another_project_and_cannot_tell_it_exists(filled) -> None:
    real = filled.client.get(
        "/documents", params={"project": "beta"}, headers=bearer(filled.alpha_editor)
    )
    fake = filled.client.get(
        "/documents", params={"project": "nope"}, headers=bearer(filled.alpha_editor)
    )
    assert real.status_code == fake.status_code == 404
    assert real.json() == fake.json()  # no oracle for which projects exist
    upload = filled.upload(filled.alpha_editor, "x.md", b"# x\n\nhello", project="beta")
    assert upload.status_code == 404


# ------------------------------------------------------------------ retrieval, ask, symbols


@pytest.mark.parametrize("mode", ["vector", "lexical", "hybrid"])
def test_search_in_every_mode_returns_only_the_projects_own_text(filled, mode) -> None:
    for key, mine, theirs in (
        (filled.alpha_editor, "PINEAPPLE", "ZUCCHINI"),
        (filled.beta_reader, "ZUCCHINI", "PINEAPPLE"),
    ):
        hits = filled.client.post(
            "/search", json={"query": "launch code", "mode": mode, "top_k": 10}, headers=bearer(key)
        ).json()["hits"]
        text = " ".join(h["content"] for h in hits)
        assert mine in text and theirs not in text


def test_the_core_retrieval_functions_enforce_the_boundary(filled, db) -> None:
    alpha_id = projects.get_by_slug(db, "alpha").id
    vec = FakeEmbedder().embed(["launch code"])[0]
    for hits in (
        retrieval.vector_search(db, vec, 10, project_id=alpha_id),
        retrieval.lexical_search(db, "launch code", vec, 10, project_id=alpha_id),
        retrieval.hybrid_search(db, "launch code", vec, 10, 20, 60, project_id=alpha_id),
    ):
        assert hits and all(h.document.project_id == alpha_id for h in hits)
    # None is the explicit "every project", used only by single-project tools (the eval runner).
    both = retrieval.vector_search(db, vec, 10, project_id=None)
    assert {h.document.project_id for h in both} == {alpha_id, projects.get_by_slug(db, "beta").id}


def test_the_model_only_ever_sees_its_own_projects_passages(filled) -> None:
    filled.llm.calls.clear()
    body = filled.client.post(
        "/ask", json={"question": "what is the launch code"}, headers=bearer(filled.alpha_editor)
    ).json()
    assert body["refused"] is False
    prompt = filled.llm.calls[0][1]
    assert "PINEAPPLE" in prompt and "ZUCCHINI" not in prompt
    assert {s["citation"]["source_path"] for s in body["sources"]} == {"note.md"}
    filled.llm.calls.clear()
    filled.client.post(
        "/ask",
        json={"question": "what is the launch code"},
        params={"project": "beta"},
        headers=bearer(filled.admin),
    )
    assert "ZUCCHINI" in filled.llm.calls[0][1] and "PINEAPPLE" not in filled.llm.calls[0][1]


def test_symbol_lookup_is_scoped(world, db) -> None:
    assert world.upload(world.alpha_editor, "enemy.py", ALPHA_CODE).status_code == 201
    alpha_id, beta_id = projects.get_by_slug(db, "alpha").id, projects.get_by_slug(db, "beta").id
    assert symbols.find_symbols(db, "poison_stacks", 5, project_id=alpha_id)
    assert symbols.find_symbols(db, "poison_stacks", 5, project_id=beta_id) == []


def test_embedding_a_project_leaves_the_others_chunks_alone(world, db) -> None:
    world.upload(world.alpha_editor, "note.md", ALPHA_NOTE)
    world.upload(world.beta_editor, "note.md", BETA_NOTE)
    assert world.embed(world.alpha_editor).json()["embedded"] > 0
    pending = (
        select(func.count())
        .select_from(Chunk)
        .join(Document)
        .join(Project)
        .where(Chunk.embedding.is_(None))
    )
    assert db.scalar(pending.where(Project.slug == "alpha")) == 0
    assert db.scalar(pending.where(Project.slug == "beta")) > 0  # untouched


def test_status_counts_describe_the_requested_project(filled) -> None:
    for slug in ("alpha", "beta"):
        body = filled.client.get(
            "/status", params={"project": slug}, headers=bearer(filled.admin)
        ).json()
        assert body["project"] == slug and body["database"]["documents"] == 1


# ------------------------------------------------------------------ agent runs, actions, tasks


@pytest.fixture
def checked(world):
    """Alpha has a design doc and code; a consistency check drafted a task-creating action."""
    world.upload(world.alpha_editor, "design.md", DESIGN)
    world.upload(world.alpha_editor, "enemy.py", ALPHA_CODE)
    world.embed(world.alpha_editor)
    world.llm.reply = {
        "verdict": "potential_discrepancy",
        "explanation": "Design says 3 but code returns 5 [D1] [C1].",
        "design_refs": ["D1"],
        "implementation_refs": ["C1"],
    }
    run = world.client.post(
        "/agent/consistency-checks", json={"claim": CLAIM}, headers=bearer(world.alpha_editor)
    ).json()
    assert run["status"] == "awaiting_approval"
    world.run = run
    world.action_id = run["actions"][0]["id"]
    return world


def test_runs_are_recorded_in_and_listed_by_their_project(checked, db) -> None:
    alpha_runs = checked.client.get("/agent/runs", headers=bearer(checked.alpha_editor)).json()
    beta_runs = checked.client.get("/agent/runs", headers=bearer(checked.beta_reader)).json()
    assert alpha_runs["total"] == 1 and beta_runs["total"] == 0
    assert (
        db.scalar(select(Project.slug).join(AgentRun).where(AgentRun.id == checked.run["id"]))
        == "alpha"
    )


def test_a_check_only_uses_evidence_from_its_own_project(world, db) -> None:
    # Beta holds the design AND code; alpha holds neither. A check in alpha must find nothing.
    world.upload(world.beta_editor, "design.md", DESIGN)
    world.upload(world.beta_editor, "enemy.py", ALPHA_CODE)
    world.embed(world.beta_editor)
    world.llm.reply = {
        "verdict": "consistent",
        "explanation": "x [D1] [C1]",
        "design_refs": ["D1"],
        "implementation_refs": ["C1"],
    }
    run = world.client.post(
        "/agent/consistency-checks", json={"claim": CLAIM}, headers=bearer(world.alpha_editor)
    ).json()
    assert run["verdict"] == "insufficient_evidence"  # nothing to compare in alpha
    assert world.llm.calls == []  # the model was never consulted, so nothing could leak in


def test_another_projects_run_and_action_are_invisible_and_untouchable(checked, db) -> None:
    foreign = bearer(checked.beta_approver)
    assert (
        checked.client.get(f"/agent/runs/{checked.run['id']}", headers=foreign).status_code == 404
    )
    for verb in ("approve", "reject"):
        response = checked.client.post(
            f"/agent/actions/{checked.action_id}/{verb}", headers=foreign
        )
        assert response.status_code == 404
    assert db.scalar(select(Task.id)) is None  # nothing was created
    from app.models import AgentAction

    assert db.get(AgentAction, uuid.UUID(checked.action_id)).status == "pending"


def test_an_approved_task_belongs_to_the_project_that_produced_it(checked, db) -> None:
    done = checked.client.post(
        f"/agent/actions/{checked.action_id}/approve", headers=bearer(checked.alpha_approver)
    )
    assert done.status_code == 200 and done.json()["status"] == "executed"
    alpha_tasks = checked.client.get("/agent/tasks", headers=bearer(checked.alpha_editor)).json()
    beta_tasks = checked.client.get("/agent/tasks", headers=bearer(checked.beta_reader)).json()
    assert alpha_tasks["total"] == 1 and beta_tasks["total"] == 0
    assert db.scalar(select(Project.slug).join(Task)) == "alpha"


# ------------------------------------------------------------------ the projects API


def test_listing_shows_a_scoped_key_only_its_own_project(world) -> None:
    mine = world.client.get("/projects", headers=bearer(world.beta_reader)).json()
    assert [p["slug"] for p in mine] == ["beta"]
    everything = world.client.get("/projects", headers=bearer(world.admin)).json()
    assert {p["slug"] for p in everything} >= {"alpha", "beta", "default"}


def test_only_an_unscoped_approver_can_create_a_project(world, db) -> None:
    body = {"slug": "gamma", "name": "Gamma"}
    assert world.client.post("/projects", json=body, headers=bearer(world.admin)).status_code == 201
    assert projects.get_by_slug(db, "gamma") is not None
    assert world.client.post("/projects", json=body, headers=bearer(world.admin)).status_code == 409
    for token in (world.alpha_approver, world.alpha_editor, world.beta_reader):
        denied = world.client.post(
            "/projects", json={"slug": "hijack", "name": "H"}, headers=bearer(token)
        )
        assert denied.status_code == 403  # a scoped approver, or too low a role
    bad = world.client.post(
        "/projects", json={"slug": "Bad Slug", "name": "x"}, headers=bearer(world.admin)
    )
    assert bad.status_code == 422
    assert projects.get_by_slug(db, "hijack") is None


def test_project_creation_is_audited_and_uploads_record_their_project(world, db) -> None:
    world.client.post("/projects", json={"slug": "gamma", "name": "G"}, headers=bearer(world.admin))
    world.upload(world.alpha_editor, "n.md", ALPHA_NOTE)
    events = {e.action: e for e in db.scalars(select(AuditEvent))}
    assert events["project.create"].target == "gamma"
    assert events["document.upload"].detail["project"] == "alpha"


# ------------------------------------------------------------------ deleting a project


def test_deleting_a_project_removes_only_that_projects_data_and_keys(filled, db) -> None:
    filled.upload(filled.beta_editor, "extra.md", b"# e\n\nmore beta text here")
    removed = projects.delete_project(db, "beta")
    assert removed.documents == 2
    assert projects.get_by_slug(db, "beta") is None
    assert db.scalar(select(func.count()).select_from(Document)) == 1  # alpha's is intact
    remaining = {k.name for k in db.scalars(select(ApiKey))}
    assert "beta-reader" not in remaining and "beta-editor" not in remaining  # scoped keys go too
    assert {"admin", "alpha-editor"} <= remaining  # everyone else's keys are untouched
    assert filled.client.get("/documents", headers=bearer(filled.beta_reader)).status_code == 401


def test_the_default_project_cannot_be_deleted_and_unknown_ones_are_reported(db) -> None:
    projects.get_or_create_default(db)
    with pytest.raises(projects.ProjectError, match="default"):
        projects.delete_project(db, "default")
    with pytest.raises(projects.ProjectError, match="no project"):
        projects.delete_project(db, "ghost")


# ------------------------------------------------------------------ CLIs


def test_projects_cli_create_list_delete(db_engine, db, monkeypatch, capsys) -> None:
    monkeypatch.setattr("app.projects.get_engine", lambda: db_engine)
    assert projects.main(["create", "--slug", "cli-proj", "--name", "CLI"]) == 0
    assert projects.main(["create", "--slug", "cli-proj", "--name", "CLI"]) == 1  # duplicate
    assert projects.main(["list"]) == 0
    assert "cli-proj" in capsys.readouterr().out
    assert projects.main(["delete", "cli-proj"]) == 2  # refuses without --yes
    assert projects.get_by_slug(db, "cli-proj") is not None
    assert projects.main(["delete", "cli-proj", "--yes"]) == 0
    db.expire_all()
    assert projects.get_by_slug(db, "cli-proj") is None


def test_key_cli_can_scope_a_key_and_rejects_an_unknown_project(
    db_engine, db, monkeypatch, capsys
) -> None:
    monkeypatch.setattr("app.keys.get_engine", lambda: db_engine)
    projects.create_project(db, "scoped", "Scoped")
    assert (
        keys_cli.main(["create", "--name", "cli-scoped", "--role", "reader", "--project", "scoped"])
        == 0
    )
    assert (
        keys_cli.main(["create", "--name", "cli-lost", "--role", "reader", "--project", "nope"])
        == 1
    )
    assert "no project" in capsys.readouterr().err
    db.expire_all()
    key = db.scalar(select(ApiKey).where(ApiKey.name == "cli-scoped"))
    assert key.project_id == projects.get_by_slug(db, "scoped").id
    assert keys_cli.main(["list"]) == 0
    assert "scoped" in capsys.readouterr().out


# ------------------------------------------------------------------ MCP


def test_the_mcp_server_serves_only_the_project_its_launcher_chose(filled, db_engine) -> None:
    def tools(slug: str) -> ProjectTools:
        return ProjectTools(
            lambda: Session(db_engine, expire_on_commit=False),
            FakeEmbedder(),
            ScriptedLLM({"answerable": False}),
            Settings(mcp_project=slug, min_evidence_score=0.1),
        )

    for slug, secret, other in (
        ("alpha", "PINEAPPLE", "ZUCCHINI"),
        ("beta", "ZUCCHINI", "PINEAPPLE"),
    ):
        t = tools(slug)
        assert t.list_documents(50, 0).total == 1
        found = t.search_project("launch code", 10, "vector")
        text = " ".join(h.content for h in found.hits)
        assert secret in text and other not in text
    with pytest.raises(Exception, match="does not exist"):
        tools("missing").list_documents(50, 0)
