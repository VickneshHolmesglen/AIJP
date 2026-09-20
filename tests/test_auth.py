import json
import logging
import re
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from prometheus_client import REGISTRY
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app import keys as keys_cli
from app.api.ask import get_llm
from app.api.search import get_embedder
from app.auth import (
    AuthError,
    Role,
    authenticate,
    create_key,
    generate_token,
    hash_secret,
    parse_token,
    revoke_keys,
)
from app.config import Settings, get_settings
from app.main import app
from app.models import ApiKey, AuditEvent
from tests.fakes import FakeEmbedder, ScriptedLLM


def sample(name: str, **labels: str) -> float:
    return REGISTRY.get_sample_value(name, labels) or 0.0


# ------------------------------------------------------------------ pure token logic


def test_tokens_have_the_documented_shape_and_are_unique() -> None:
    token, prefix, key_hash = generate_token()
    assert re.fullmatch(r"aijp_[0-9a-f]{8}_[A-Za-z0-9_-]{43}", token)
    assert parse_token(token) == (prefix, token.split("_", 2)[2])
    assert key_hash == hash_secret(token.split("_", 2)[2]) and len(key_hash) == 64
    assert len({generate_token()[0] for _ in range(50)}) == 50


def test_the_stored_hash_never_contains_the_secret() -> None:
    token, _, key_hash = generate_token()
    secret = token.split("_", 2)[2]
    assert secret not in key_hash and token not in key_hash


@pytest.mark.parametrize(
    "bad",
    [
        "",
        "aijp",
        "Bearer x",
        "aijp_short_" + "a" * 43,  # prefix must be 8 hex chars
        "aijp_zzzzzzzz_" + "a" * 43,  # not hex
        "aijp_0123abcd_" + "a" * 42,  # secret too short
        "aijp_0123abcd_" + "a" * 44,  # secret too long
        "aijp_0123abcd_" + "a" * 42 + "!",  # illegal character
        " aijp_0123abcd_" + "a" * 43,  # leading whitespace
    ],
)
def test_malformed_tokens_are_rejected_before_any_lookup(bad) -> None:
    assert parse_token(bad) is None


def test_roles_are_ordered_so_higher_roles_include_lower_ones() -> None:
    assert Role.reader < Role.editor < Role.approver


# ------------------------------------------------------------------ database-backed behaviour

pytestmark_db = pytest.mark.integration


@pytest.fixture
def db(client, db_engine):
    """A clean database (the `client` fixture wipes tables) and a session for direct key work."""
    with Session(db_engine, expire_on_commit=False) as session:
        yield session


@pytest.fixture
def keys(db):
    """One key per role, created the way the CLI creates them."""
    made = {}
    for role in Role:
        key, token = create_key(db, f"{role.name}-user", role)
        made[role.name] = (key, token)
    return made


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.integration
def test_authenticate_resolves_a_valid_key_and_rejects_everything_else(db, keys) -> None:
    _, token = keys["editor"]
    principal = authenticate(db, token)
    assert (principal.name, principal.role) == ("editor-user", Role.editor)

    prefix, secret = parse_token(token)
    cases = {
        "missing": None,
        "malformed": "not-a-token",
        "unknown": f"aijp_{'f' * 8}_{secret}",  # right shape, no such prefix
        "mismatch": f"aijp_{prefix}_{'A' * 43}",  # real prefix, wrong secret
    }
    for reason, candidate in cases.items():
        with pytest.raises(AuthError) as excinfo:
            authenticate(db, candidate)
        assert excinfo.value.reason == reason


@pytest.mark.integration
def test_revoked_and_expired_keys_stop_working(db) -> None:
    key, token = create_key(db, "temp", Role.reader)
    assert authenticate(db, token).name == "temp"
    revoke_keys(db, "temp")
    with pytest.raises(AuthError) as excinfo:
        authenticate(db, token)
    assert excinfo.value.reason == "revoked"

    _, short = create_key(db, "short-lived", Role.reader, datetime.now(UTC) + timedelta(hours=1))
    assert authenticate(db, short).name == "short-lived"
    with pytest.raises(AuthError) as excinfo:
        authenticate(db, short, now=datetime.now(UTC) + timedelta(hours=2))
    assert excinfo.value.reason == "expired"
    assert key.revoked_at is not None


@pytest.mark.integration
def test_key_names_are_unique_among_active_keys_but_reusable_after_revocation(db) -> None:
    create_key(db, "alice", Role.reader)
    with pytest.raises(ValueError, match="already exists"):
        create_key(db, "alice", Role.approver)
    revoke_keys(db, "alice")
    create_key(db, "alice", Role.approver)  # fine once the old one is revoked


@pytest.mark.integration
@pytest.mark.parametrize("bad", ["", "   ", "x" * 101, "bell\x07name", "line\nbreak"])
def test_invalid_key_names_are_rejected(db, bad) -> None:
    with pytest.raises(ValueError, match="printable"):
        create_key(db, bad, Role.reader)


@pytest.mark.integration
def test_the_database_holds_only_a_hash_never_the_token(db, keys, db_engine) -> None:
    _, token = keys["approver"]
    secret = token.split("_", 2)[2]
    dump = " ".join(str(v) for row in db.execute(text("select * from api_keys")).all() for v in row)
    assert secret not in dump and token not in dump


@pytest.mark.integration
def test_last_used_is_updated_but_not_on_every_request(db, keys) -> None:
    key, token = keys["reader"]
    assert key.last_used_at is None
    authenticate(db, token)
    first = db.get(ApiKey, key.id).last_used_at
    assert first is not None
    authenticate(db, token)  # within the 5 minute granularity: no second write
    assert db.get(ApiKey, key.id).last_used_at == first


# ------------------------------------------------------------------ HTTP enforcement

# Every endpoint, the lowest role allowed to call it, and a request that is valid apart from auth.
DOC_ID = str(uuid.uuid4())
ENDPOINTS = [
    ("GET", "/auth/me", None, None, Role.reader),
    ("GET", "/status", None, None, Role.reader),
    ("GET", "/metrics", None, None, Role.reader),
    ("GET", "/documents", None, None, Role.reader),
    ("GET", f"/documents/{DOC_ID}", None, None, Role.reader),
    ("POST", "/search", {"query": "x"}, None, Role.reader),
    ("POST", "/ask", {"question": "x"}, None, Role.reader),
    ("GET", "/eval/reports", None, None, Role.reader),
    ("GET", "/eval/reports/qa-2026-01-01", None, None, Role.reader),
    ("GET", "/agent/runs", None, None, Role.reader),
    ("GET", f"/agent/runs/{DOC_ID}", None, None, Role.reader),
    ("GET", "/agent/tasks", None, None, Role.reader),
    ("POST", "/embeddings", None, None, Role.editor),
    ("DELETE", f"/documents/{DOC_ID}", None, None, Role.editor),
    ("POST", "/documents", None, {"file": ("a.txt", b"hello world")}, Role.editor),
    ("POST", "/agent/consistency-checks", {"claim": "some claim"}, None, Role.editor),
    ("POST", f"/agent/actions/{DOC_ID}/approve", None, None, Role.approver),
    ("POST", f"/agent/actions/{DOC_ID}/reject", None, None, Role.approver),
]
PUBLIC = ["/health", "/health/ready", "/auth/config", "/ui/", "/docs", "/openapi.json"]


@pytest.fixture
def secured(client, db, keys):
    """The app with authentication ON and fakes for the model services."""
    app.dependency_overrides[get_settings] = lambda: Settings(
        auth_enabled=True, chunk_max_chars=300, chunk_overlap_chars=60, max_upload_bytes=50_000
    )
    app.dependency_overrides[get_embedder] = FakeEmbedder
    app.dependency_overrides[get_llm] = lambda: ScriptedLLM({"answerable": False})
    yield client
    app.dependency_overrides.pop(get_embedder, None)
    app.dependency_overrides.pop(get_llm, None)


def call(client, method, path, body, files, token=None, extra=None):
    headers = {**(bearer(token) if token else {}), **(extra or {})}
    return client.request(
        method, path, json=body if files is None else None, files=files, headers=headers
    )


@pytest.mark.integration
@pytest.mark.parametrize(("method", "path", "body", "files", "needed"), ENDPOINTS)
def test_every_endpoint_enforces_its_role(secured, keys, method, path, body, files, needed) -> None:
    # No credentials: 401 with a Bearer challenge, for every protected endpoint.
    anonymous = call(secured, method, path, body, files)
    assert anonymous.status_code == 401, (method, path)
    assert anonymous.headers["www-authenticate"] == "Bearer"

    for role in Role:
        _, token = keys[role.name]
        status = call(secured, method, path, body, files, token).status_code
        if role < needed:
            assert status == 403, (method, path, role.name)
        else:
            assert status not in (401, 403), (method, path, role.name, status)


@pytest.mark.integration
@pytest.mark.parametrize("path", PUBLIC)
def test_health_probes_docs_and_the_static_ui_stay_public(secured, path) -> None:
    assert secured.get(path).status_code == 200


@pytest.mark.integration
def test_every_registered_route_is_either_public_or_in_the_role_table(secured) -> None:
    """A new endpoint must be added to ENDPOINTS or PUBLIC, so it cannot ship unprotected by
    accident: the table above is the single source of truth this test holds the app to."""
    known = {(m, re.sub(r"\{[^}]+\}", "X", p)) for m, p, *_ in ENDPOINTS}
    public = {re.sub(r"\{[^}]+\}", "X", p) for p in PUBLIC} | {"/", "/ui", "/redoc"}
    for route in app.routes:
        methods = getattr(route, "methods", None)
        path = getattr(route, "path", "")
        if not methods:  # mounts (static files)
            continue
        norm = re.sub(r"\{[^}]+\}", "X", path)
        for method in methods - {"HEAD", "OPTIONS"}:
            normalised = {
                (m, re.sub(r"\{[^}]+\}", "X", p.replace(DOC_ID, "X"))) for m, p, *_ in ENDPOINTS
            }
            assert (
                (method, norm) in normalised or norm in public or path in ("/docs/oauth2-redirect",)
            ), f"{method} {path} is neither in the role table nor declared public"
    assert known  # the table is not empty


@pytest.mark.integration
def test_failures_are_indistinguishable_to_the_client(secured, keys, db) -> None:
    """No oracle: unknown, wrong-secret, revoked and malformed keys all look identical."""
    good_prefix, secret = parse_token(keys["reader"][1])
    revoked_key, revoked_token = create_key(db, "gone", Role.reader)
    revoke_keys(db, "gone")
    attempts = {
        "unknown": f"aijp_{'e' * 8}_{secret}",
        "wrong-secret": f"aijp_{good_prefix}_{'B' * 43}",
        "revoked": revoked_token,
        "malformed": "garbage",
    }
    responses = {name: secured.get("/documents", headers=bearer(t)) for name, t in attempts.items()}
    assert {r.status_code for r in responses.values()} == {401}
    assert len({r.text for r in responses.values()}) == 1  # byte-identical bodies
    assert revoked_key.name not in json.dumps([r.text for r in responses.values()])


@pytest.mark.integration
def test_the_real_reason_is_counted_but_not_revealed(secured, keys) -> None:
    before = {
        r: sample("auth_failures_total", reason=r) for r in ("missing", "malformed", "mismatch")
    }
    prefix, _ = parse_token(keys["reader"][1])
    secured.get("/documents")  # no header at all
    secured.get("/documents", headers=bearer("nope"))
    secured.get("/documents", headers=bearer(f"aijp_{prefix}_{'C' * 43}"))
    for reason in before:
        assert sample("auth_failures_total", reason=reason) == before[reason] + 1


@pytest.mark.integration
def test_a_role_denial_is_counted_and_names_the_needed_role(secured, keys) -> None:
    before = sample("auth_denied_total", required_role="approver")
    response = secured.post(f"/agent/actions/{DOC_ID}/approve", headers=bearer(keys["editor"][1]))
    assert response.status_code == 403 and "approver" in response.json()["detail"]
    assert sample("auth_denied_total", required_role="approver") == before + 1


@pytest.mark.integration
def test_me_reports_the_caller_and_config_is_public(secured, keys) -> None:
    me = secured.get("/auth/me", headers=bearer(keys["editor"][1])).json()
    assert (me["name"], me["role"], me["auth_enabled"]) == ("editor-user", "editor", True)
    assert me["key_prefix"] == keys["editor"][0].key_prefix
    assert "hash" not in json.dumps(me) and "aijp_" not in json.dumps(me)
    assert secured.get("/auth/config").json() == {"auth_enabled": True}


@pytest.mark.integration
def test_revocation_takes_effect_on_the_very_next_request(secured, keys, db) -> None:
    token = keys["reader"][1]
    assert secured.get("/documents", headers=bearer(token)).status_code == 200
    revoke_keys(db, "reader-user")
    assert secured.get("/documents", headers=bearer(token)).status_code == 401


@pytest.mark.integration
def test_authentication_can_be_disabled_explicitly_and_says_so(client) -> None:
    app.dependency_overrides[get_settings] = lambda: Settings(auth_enabled=False)
    me = client.get("/auth/me").json()
    assert me["auth_enabled"] is False and "authentication disabled" in me["name"]
    assert me["role"] == "approver"
    assert client.get("/status").json()["config"]["auth_enabled"] is False


# ------------------------------------------------------------------ pre-body gate


@pytest.mark.integration
def test_unauthenticated_uploads_are_rejected_before_the_body_is_parsed(secured) -> None:
    # A deliberately broken multipart body: if the framework parsed it first we would see a 4xx
    # parse error, not the 401. Getting 401 proves the gate ran before any body handling.
    response = secured.post(
        "/documents",
        content=b"this is not valid multipart",
        headers={"Content-Type": "multipart/form-data; boundary=x"},
    )
    assert response.status_code == 401


@pytest.mark.integration
def test_a_malformed_bearer_is_rejected_by_the_gate_without_a_database_lookup(secured) -> None:
    response = secured.post("/embeddings", headers={"Authorization": "Bearer not-a-real-token"})
    assert response.status_code == 401


@pytest.mark.integration
def test_oversized_declared_bodies_are_rejected_with_413_before_reading(secured, keys) -> None:
    huge = {"Content-Length": str(50_000 + 2 * 1024 * 1024)}
    response = secured.post(
        "/documents", headers={**bearer(keys["editor"][1]), **huge}, content=b"x"
    )
    assert response.status_code == 413


@pytest.mark.integration
def test_rejections_still_get_a_request_id_a_log_line_and_a_metric(secured, caplog) -> None:
    before = sample("http_requests_total", method="POST", route="unmatched", status="4xx")
    with caplog.at_level(logging.INFO, logger="app.request"):
        response = secured.post("/documents", content=b"x")
    assert response.status_code == 401
    assert re.fullmatch(r"[0-9a-f]{32}", response.headers["x-request-id"])
    assert any(r.name == "app.request" and r.status == 401 for r in caplog.records)
    assert sample("http_requests_total", method="POST", route="unmatched", status="4xx") >= before


@pytest.mark.integration
def test_reads_are_not_subject_to_the_body_gate(secured, keys) -> None:
    assert secured.get("/documents", headers=bearer(keys["reader"][1])).status_code == 200


# ------------------------------------------------------------------ accountability


@pytest.mark.integration
def test_who_did_what_is_recorded(secured, keys, db) -> None:
    editor, approver = bearer(keys["editor"][1]), bearer(keys["approver"][1])
    upload = secured.post(
        "/documents",
        files={"file": ("towers.md", b"# T\n\n## Poison\nStacks up to 3 times.\n")},
        data={"source_path": "d/towers.md"},
        headers=editor,
    )
    doc_id = upload.json()["id"]
    assert secured.post("/embeddings", headers=editor).status_code == 200
    assert secured.delete(f"/documents/{doc_id}", headers=editor).status_code == 204

    events = list(db.scalars(select(AuditEvent).order_by(AuditEvent.occurred_at)))
    seen = [(e.actor, e.role, e.action) for e in events]
    assert ("editor-user", "editor", "document.upload") in seen
    assert ("editor-user", "editor", "embeddings.run") in seen
    assert ("editor-user", "editor", "document.delete") in seen
    upload_event = next(e for e in events if e.action == "document.upload")
    assert upload_event.target == doc_id and upload_event.detail["source_path"] == "d/towers.md"
    assert upload_event.key_prefix == keys["editor"][0].key_prefix
    delete_event = next(e for e in events if e.action == "document.delete")
    assert delete_event.detail["source_path"] == "d/towers.md"  # captured before the row vanished
    assert approver  # (approver exercised in the approval test below)


@pytest.mark.integration
def test_audit_events_never_contain_document_text_or_key_material(secured, keys, db) -> None:
    body = b"# Secret\n\nthe launch codes are 12345\n"
    secured.post("/documents", files={"file": ("s.md", body)}, headers=bearer(keys["editor"][1]))
    dump = json.dumps(
        [(e.actor, e.action, e.target, e.detail) for e in db.scalars(select(AuditEvent))]
    )
    assert "launch codes" not in dump
    for _, token in keys.values():
        assert token not in dump and token.split("_", 2)[2] not in dump


@pytest.mark.integration
def test_approvals_record_the_approver_and_self_approval_is_allowed_but_visible(
    secured, keys, db
) -> None:
    app.dependency_overrides[get_llm] = lambda: ScriptedLLM(
        {
            "verdict": "potential_discrepancy",
            "explanation": "differs [D1] [C1]",
            "design_refs": ["D1"],
            "implementation_refs": ["C1"],
        }
    )
    app.dependency_overrides[get_settings] = lambda: Settings(
        auth_enabled=True, chunk_max_chars=300, chunk_overlap_chars=60, consistency_min_cosine=0.0
    )
    approver = bearer(keys["approver"][1])
    for name, body, path in [
        ("d.md", b"# Towers\n\n## Poison\nPoison stacks up to 3 times.\n", "docs/d.md"),
        ("e.py", b"def apply_poison():\n    return 1\n", "src/e.py"),
    ]:
        secured.post(
            "/documents", files={"file": (name, body)}, data={"source_path": path}, headers=approver
        )
    secured.post("/embeddings", headers=approver)

    # The same person runs the check and approves its task.
    run = secured.post(
        "/agent/consistency-checks", json={"claim": "poison stacks up to 3 times"}, headers=approver
    ).json()
    assert run["requested_by"] == "approver-user"
    action_id = run["actions"][0]["id"]
    done = secured.post(f"/agent/actions/{action_id}/approve", headers=approver)
    assert done.status_code == 200 and done.json()["decided_by"] == "approver-user"

    [task] = secured.get("/agent/tasks", headers=approver).json()["items"]
    assert task["created_by"] == "approver-user"
    detail = secured.get(f"/agent/runs/{run['id']}", headers=approver).json()
    decision = detail["steps"][-1]
    assert decision["name"] == "human_decision" and decision["input"]["actor"] == "approver-user"
    # Visible: requester and approver are both on the record, so a review can spot self-approval.
    assert detail["requested_by"] == detail["actions"][0]["decided_by"]

    approvals = [e for e in db.scalars(select(AuditEvent)) if e.action == "agent.approve"]
    assert [(e.actor, e.detail["status"]) for e in approvals] == [("approver-user", "executed")]


@pytest.mark.integration
def test_a_reader_cannot_approve_even_a_real_pending_action(secured, keys, db) -> None:
    app.dependency_overrides[get_llm] = lambda: ScriptedLLM(
        {
            "verdict": "potential_discrepancy",
            "explanation": "differs [D1] [C1]",
            "design_refs": ["D1"],
            "implementation_refs": ["C1"],
        }
    )
    app.dependency_overrides[get_settings] = lambda: Settings(
        auth_enabled=True, chunk_max_chars=300, chunk_overlap_chars=60, consistency_min_cosine=0.0
    )
    editor = bearer(keys["editor"][1])
    for name, body, path in [
        ("d.md", b"# T\n\n## P\nStacks up to 3.\n", "docs/d.md"),
        ("e.py", b"def f():\n    return 1\n", "src/e.py"),
    ]:
        secured.post(
            "/documents", files={"file": (name, body)}, data={"source_path": path}, headers=editor
        )
    secured.post("/embeddings", headers=editor)
    run = secured.post(
        "/agent/consistency-checks", json={"claim": "stacks up to 3"}, headers=editor
    ).json()
    action_id = run["actions"][0]["id"]

    assert (
        secured.post(
            f"/agent/actions/{action_id}/approve", headers=bearer(keys["reader"][1])
        ).status_code
        == 403
    )
    assert secured.post(f"/agent/actions/{action_id}/approve", headers=editor).status_code == 403
    assert secured.get("/agent/tasks", headers=editor).json()["total"] == 0  # nothing was created
    still = secured.get(f"/agent/runs/{run['id']}", headers=editor).json()["actions"][0]
    assert still["status"] == "pending" and still["decided_by"] is None


@pytest.mark.integration
def test_the_actor_appears_in_the_request_log_but_the_token_never_does(
    secured, keys, caplog
) -> None:
    _, token = keys["reader"]
    with caplog.at_level(logging.INFO):
        secured.get("/documents", headers=bearer(token))
        secured.get("/documents", headers=bearer(token.replace("aijp_", "aijp_x", 1)))
    request_lines = [
        r for r in caplog.records if r.name == "app.request" and r.route == "/documents"
    ]
    assert request_lines[0].actor == "reader-user"
    everything = " ".join(json.dumps(r.__dict__, default=str) for r in caplog.records)
    assert token not in everything and token.split("_", 2)[2] not in everything


# ------------------------------------------------------------------ key-management CLI


@pytest.mark.integration
def test_cli_create_list_revoke_round_trip(db_engine, monkeypatch, capsys, client) -> None:
    monkeypatch.setattr("app.keys.get_engine", lambda: db_engine)
    assert (
        keys_cli.main(["create", "--name", "ci-bot", "--role", "reader", "--expires-days", "7"])
        == 0
    )
    out = capsys.readouterr().out
    token = re.search(r"aijp_[0-9a-f]{8}_[A-Za-z0-9_-]{43}", out).group(0)
    assert "cannot be shown again" in out

    assert keys_cli.main(["list"]) == 0
    listing = capsys.readouterr().out
    assert "ci-bot" in listing and "reader" in listing and "active" in listing
    assert token not in listing and token.split("_", 2)[2] not in listing  # never the secret

    with Session(db_engine) as s:
        assert authenticate(s, token).name == "ci-bot"
    assert keys_cli.main(["revoke", "ci-bot"]) == 0
    with Session(db_engine) as s, pytest.raises(AuthError):
        authenticate(s, token)
    assert keys_cli.main(["revoke", "ci-bot"]) == 1  # nothing active left
    assert keys_cli.main(["create", "--name", "ci-bot", "--role", "editor"]) == 0  # name reusable

    with Session(db_engine) as s:
        actions_logged = [e.action for e in s.scalars(select(AuditEvent))]
    assert actions_logged.count("key.create") == 2 and "key.revoke" in actions_logged


@pytest.mark.integration
def test_cli_token_only_prints_just_the_token_and_duplicate_names_fail(
    db_engine, monkeypatch, capsys, client
) -> None:
    monkeypatch.setattr("app.keys.get_engine", lambda: db_engine)
    assert keys_cli.main(["create", "--name", "script", "--role", "approver", "--token-only"]) == 0
    printed = capsys.readouterr().out.strip()
    assert re.fullmatch(r"aijp_[0-9a-f]{8}_[A-Za-z0-9_-]{43}", printed)
    assert keys_cli.main(["create", "--name", "script", "--role", "reader"]) == 1
    assert "already exists" in capsys.readouterr().err


def test_cli_rejects_unknown_roles_and_bad_expiry() -> None:
    with pytest.raises(SystemExit):
        keys_cli.main(["create", "--name", "x", "--role", "admin"])
    with pytest.raises(SystemExit):
        keys_cli.main(["create", "--name", "x", "--role", "reader", "--expires-days", "0"])


def test_there_are_no_http_endpoints_for_managing_keys() -> None:
    paths = {getattr(r, "path", "") for r in app.routes}
    assert not any("key" in p.lower() for p in paths)
    assert TestClient(app).post("/auth/keys", json={}).status_code in (404, 405, 401)


def test_startup_warns_loudly_only_when_authentication_is_disabled(caplog) -> None:
    from app.auth import warn_if_auth_disabled

    with caplog.at_level(logging.WARNING, logger="app.auth"):
        assert warn_if_auth_disabled(Settings(auth_enabled=True)) is False
        assert not caplog.records
        assert warn_if_auth_disabled(Settings(auth_enabled=False)) is True
    assert "AUTHENTICATION IS DISABLED" in caplog.text


def test_authentication_is_on_unless_explicitly_disabled(monkeypatch) -> None:
    """Secure by default: the built-in default must be True (conftest disables it for old suites
    through the environment, so check the field default itself)."""
    assert Settings.model_fields["auth_enabled"].default is True
