import json
import uuid
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import projects
from app.agent import actions
from app.agent.consistency import (
    DISCLAIMER,
    Evidence,
    Finding,
    build_judge_prompt,
    draft_task_payload,
    validate_verdict,
)
from app.api.ask import get_llm
from app.api.search import get_embedder
from app.config import Settings, get_settings
from app.llm import LLMError
from app.main import app
from app.models import AgentAction, AgentRun, Task
from app.symbols import extract_identifiers
from tests.fakes import DownEmbedder, FakeEmbedder, ScriptedLLM

STEP_NAMES = [
    "search_design",
    "search_implementation",
    "lookup_symbols",
    "evidence_gate",
    "judge",
    "validate_verdict",
    "draft_action",
]

# ------------------------------------------------------------------ pure unit tests


def verdict_json(
    verdict="potential_discrepancy", explanation="Differs [D1] [C1].", d=("D1",), c=("C1",)
):
    return json.dumps(
        {
            "verdict": verdict,
            "explanation": explanation,
            "design_refs": list(d),
            "implementation_refs": list(c),
        }
    )


D, C = {"D1", "D2"}, {"C1"}


def test_valid_verdicts_are_accepted() -> None:
    f = validate_verdict(verdict_json("consistent"), D, C)
    assert (f.verdict, f.design_refs, f.implementation_refs, f.downgrade_reason) == (
        "consistent",
        ["D1"],
        ["C1"],
        None,
    )
    assert validate_verdict(verdict_json("potential_discrepancy"), D, C).verdict == (
        "potential_discrepancy"
    )


@pytest.mark.parametrize(
    ("raw", "reason"),
    [
        (verdict_json(d=()), "missing_citations_on_both_sides"),
        (verdict_json(c=()), "missing_citations_on_both_sides"),
        (verdict_json(d=("D99",)), "missing_citations_on_both_sides"),  # hallucinated ref
        (
            verdict_json(c=("D1",)),
            "missing_citations_on_both_sides",
        ),  # design ref on the wrong side
        (verdict_json(explanation="  "), "empty_explanation"),
        ("not json", "model_output_invalid"),
        ("[]", "model_output_invalid"),
        (json.dumps({"verdict": "proven"}), "model_output_invalid"),  # not an allowed verdict
        (json.dumps({"explanation": "x"}), "model_output_invalid"),
    ],
)
def test_unsupported_verdicts_are_downgraded_never_trusted(raw, reason) -> None:
    f = validate_verdict(raw, D, C)
    assert f.verdict == "insufficient_evidence" and f.downgrade_reason == reason


def test_insufficient_evidence_needs_no_citations() -> None:
    f = validate_verdict(verdict_json("insufficient_evidence", "Cannot tell.", (), ()), D, C)
    assert f.verdict == "insufficient_evidence" and f.downgrade_reason is None


def test_unknown_and_duplicate_refs_are_dropped_and_explanation_is_capped() -> None:
    raw = verdict_json("consistent", "x" * 5000, d=("D1", "D1", "D7", 5), c=("C1", "Z"))
    f = validate_verdict(raw, D, C)
    assert f.design_refs == ["D1"] and f.implementation_refs == ["C1"]
    assert len(f.explanation) == 1500


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("POISON_MAX_STACKS should be 3", ["POISON_MAX_STACKS"]),
        ("take_damage calls WaveSpawner and take_damage", ["take_damage", "WaveSpawner"]),
        ("poison stacks up to three times", []),  # plain words are not identifiers
        ("Towers cost 50 gold", []),
        ("a_b c_d e_f g_h i_j k_l", ["a_b", "c_d", "e_f", "g_h", "i_j"]),  # capped at 5
    ],
)
def test_extract_identifiers(text, expected) -> None:
    assert extract_identifiers(text) == expected


def fake_evidence(ref, side, content="SECRET DOC TEXT", path="a.md") -> Evidence:
    chunk = SimpleNamespace(
        id=uuid.uuid4(), section="S > x", start_line=1, end_line=3, content=content
    )
    doc = SimpleNamespace(id=uuid.uuid4(), source_path=path)
    return Evidence(ref, side, "search", chunk, doc, 0.5, 0.6)  # type: ignore[arg-type]


def test_judge_prompt_labels_both_sides_and_marks_empty_ones() -> None:
    prompt = build_judge_prompt(
        "poison stacks 3",
        [
            fake_evidence("D1", "design", "Poison stacks up to 3"),
            fake_evidence("C1", "implementation", "MAX = 5"),
        ],
    )
    assert "[D1] (path: a.md, section: S > x, lines: 1-3)" in prompt and "[C1]" in prompt
    assert prompt.rstrip().endswith("CLAIM: poison stacks 3")
    assert "(none)" in build_judge_prompt("x", [fake_evidence("D1", "design")])  # no code side


def test_drafted_task_is_deterministic_cited_only_and_carries_no_document_text() -> None:
    evidence = [
        fake_evidence("D1", "design", "SECRET DOC TEXT"),
        fake_evidence("D2", "design", "OTHER SECRET"),
        fake_evidence("C1", "implementation", "SECRET CODE"),
    ]
    finding = Finding("potential_discrepancy", "Code caps at 5 [C1].", ["D1"], ["C1"])
    payload = draft_task_payload("  poison   stacks up to 3  ", finding, evidence)
    assert payload["title"] == "Possible design/code mismatch: poison stacks up to 3"
    assert [e["ref"] for e in payload["evidence"]] == ["D1", "C1"]  # D2 was not cited
    assert DISCLAIMER in payload["description"]
    assert "SECRET" not in json.dumps(payload)
    long = draft_task_payload("word " * 100, finding, evidence)
    assert len(long["title"]) <= 120


# ------------------------------------------------------------------ integration


DESIGN = b"# Towers\n\n## Poison\nPoison stacks up to 3 times.\n"
CODE = (
    b"MAX_POISON_STACKS = 5\n\n\ndef apply_poison(enemy):\n"
    b"    enemy.poison = min(enemy.poison + 1, MAX_POISON_STACKS)\n"
)
CLAIM = "poison stacks up to 3 times"


@pytest.fixture
def env(client):
    app.dependency_overrides[get_embedder] = FakeEmbedder
    app.dependency_overrides[get_settings] = lambda: Settings(
        chunk_max_chars=300, chunk_overlap_chars=60, consistency_min_cosine=0.05
    )
    for name, body, path in [
        ("towers.md", DESIGN, "docs/towers.md"),
        ("enemy.py", CODE, "src/enemy.py"),
    ]:
        assert (
            client.post(
                "/documents", files={"file": (name, body)}, data={"source_path": path}
            ).status_code
            == 201
        )
    assert client.post("/embeddings").status_code == 200

    def install(reply):
        llm = ScriptedLLM(reply)
        app.dependency_overrides[get_llm] = lambda: llm
        return llm

    ns = SimpleNamespace(api=client, install=install)
    ns.check = lambda claim=CLAIM: client.post("/agent/consistency-checks", json={"claim": claim})
    yield ns
    app.dependency_overrides.pop(get_llm, None)
    app.dependency_overrides.pop(get_embedder, None)


DISCREPANCY = {
    "verdict": "potential_discrepancy",
    "explanation": "The design says 3 but the retrieved code appears to cap stacks at 5 [D1] [C1].",
    "design_refs": ["D1"],
    "implementation_refs": ["C1"],
}


@pytest.mark.integration
def test_discrepancy_run_records_every_step_and_only_drafts_an_action(env) -> None:
    env.install(DISCREPANCY)
    response = env.check()
    assert response.status_code == 201
    run = response.json()

    assert run["status"] == "awaiting_approval" and run["verdict"] == "potential_discrepancy"
    assert [s["name"] for s in run["steps"]] == STEP_NAMES
    assert [s["seq"] for s in run["steps"]] == list(range(1, 8))
    assert all(s["status"] in ("ok", "skipped") and s["duration_ms"] >= 0 for s in run["steps"])
    assert next(s for s in run["steps"] if s["name"] == "lookup_symbols")["status"] == "skipped"

    result = run["result"]
    assert result["disclaimer"] == DISCLAIMER
    assert [e["path"] for e in result["design_evidence"] if e["cited"]] == ["docs/towers.md"]
    assert [e["path"] for e in result["implementation_evidence"] if e["cited"]] == ["src/enemy.py"]

    [action] = run["actions"]
    assert action["kind"] == "create_task" and action["status"] == "pending"
    # The whole point of the gate: drafting created NO task.
    assert env.api.get("/agent/tasks").json() == {"items": [], "total": 0}


@pytest.mark.integration
def test_audit_trail_records_locations_never_document_text(env) -> None:
    env.install(DISCREPANCY)
    run = env.check().json()
    audit = json.dumps({"steps": run["steps"], "result": run["result"]})
    assert "stacks up to 3 times" not in audit and "MAX_POISON_STACKS" not in audit
    assert "docs/towers.md" in audit  # but it does say where the evidence is


@pytest.mark.integration
def test_approval_executes_exactly_the_drafted_task_once(env) -> None:
    env.install(DISCREPANCY)
    run = env.check().json()
    action_id = run["actions"][0]["id"]

    approved = env.api.post(f"/agent/actions/{action_id}/approve")
    assert approved.status_code == 200
    assert approved.json()["status"] == "executed" and approved.json()["result"]["task_id"]

    [task] = env.api.get("/agent/tasks").json()["items"]
    assert task["title"] == "Possible design/code mismatch: poison stacks up to 3 times"
    assert task["source_run_id"] == run["id"] and task["status"] == "open"
    assert {e["path"] for e in task["evidence"]} == {"docs/towers.md", "src/enemy.py"}

    after = env.api.get(f"/agent/runs/{run['id']}").json()
    assert after["status"] == "completed"
    assert after["steps"][-1]["name"] == "human_decision"
    assert after["steps"][-1]["input"]["decision"] == "approved"

    # A decided action can never be decided again, so it cannot create a second task.
    assert env.api.post(f"/agent/actions/{action_id}/approve").status_code == 409
    assert env.api.post(f"/agent/actions/{action_id}/reject").status_code == 409
    assert env.api.get("/agent/tasks").json()["total"] == 1


@pytest.mark.integration
def test_rejection_creates_nothing(env) -> None:
    env.install(DISCREPANCY)
    run = env.check().json()
    rejected = env.api.post(f"/agent/actions/{run['actions'][0]['id']}/reject")
    assert rejected.status_code == 200 and rejected.json()["status"] == "rejected"
    assert env.api.get("/agent/tasks").json()["total"] == 0
    assert env.api.get(f"/agent/runs/{run['id']}").json()["status"] == "completed"


@pytest.mark.integration
def test_approval_takes_no_payload_so_the_client_cannot_alter_it(env) -> None:
    env.install(DISCREPANCY)
    action_id = env.check().json()["actions"][0]["id"]
    tampered = {"title": "DROP EVERYTHING", "payload": {"title": "evil"}, "kind": "delete"}
    assert env.api.post(f"/agent/actions/{action_id}/approve", json=tampered).status_code == 200
    [task] = env.api.get("/agent/tasks").json()["items"]
    assert "evil" not in task["title"] and "DROP" not in task["title"]


@pytest.mark.integration
def test_simultaneous_approvals_execute_once(env) -> None:
    env.install(DISCREPANCY)
    action_id = env.check().json()["actions"][0]["id"]

    def approve(_):
        return TestClient(app).post(f"/agent/actions/{action_id}/approve").status_code

    with ThreadPoolExecutor(2) as pool:
        codes = sorted(pool.map(approve, range(2)))
    assert codes == [200, 409]
    assert env.api.get("/agent/tasks").json()["total"] == 1


@pytest.mark.integration
def test_decide_rereads_an_action_the_session_already_loaded(env, db_engine) -> None:
    # The race above, made deterministic: the approve route reads the action (unlocked) to check
    # its project, then decide() locks it. If another request approved and committed in between,
    # the locked SELECT must see that, not the stale copy already in the session's identity map.
    env.install(DISCREPANCY)
    action_id = uuid.UUID(env.check().json()["actions"][0]["id"])
    with Session(db_engine) as late, Session(db_engine) as first:
        # Keep a strong reference, as the route does: the identity map is weak, an unreferenced
        # object would be garbage-collected and simply reloaded.
        stale = late.get(AgentAction, action_id)
        assert stale is not None and stale.status == "pending"
        actions.decide(first, action_id, True)
        with pytest.raises(actions.ActionConflictError):
            actions.decide(late, action_id, True)
    assert env.api.get("/agent/tasks").json()["total"] == 1


@pytest.mark.integration
def test_unknown_action_id_is_404(env) -> None:
    assert env.api.post(f"/agent/actions/{uuid.uuid4()}/approve").status_code == 404
    assert env.api.post(f"/agent/actions/{uuid.uuid4()}/reject").status_code == 404


@pytest.mark.integration
def test_action_kinds_outside_the_registry_are_never_executed(env, db_engine) -> None:
    with Session(db_engine) as session:
        run = AgentRun(
            project_id=projects.get_or_create_default(session).id,
            workflow="consistency_check",
            input={"claim": "x"},
            status="awaiting_approval",
        )
        session.add(run)
        session.flush()
        bad = AgentAction(run_id=run.id, kind="delete_everything", payload={})
        session.add(bad)
        session.commit()
        bad_id = bad.id
    response = env.api.post(f"/agent/actions/{bad_id}/approve")
    assert response.status_code == 200
    assert response.json()["status"] == "failed"
    assert "Unknown action kind" in response.json()["result"]["error"]


@pytest.mark.integration
def test_a_failing_executor_is_recorded_not_raised_and_creates_nothing(env, monkeypatch) -> None:
    def broken(session, action):
        raise RuntimeError("disk on fire")

    monkeypatch.setitem(actions.ACTION_REGISTRY, "create_task", broken)
    env.install(DISCREPANCY)
    action_id = env.check().json()["actions"][0]["id"]
    response = env.api.post(f"/agent/actions/{action_id}/approve")
    assert response.status_code == 200 and response.json()["status"] == "failed"
    assert "disk on fire" not in json.dumps(response.json())  # internals stay in the server log
    assert env.api.get("/agent/tasks").json()["total"] == 0


@pytest.mark.integration
def test_consistent_verdict_completes_without_drafting_anything(env) -> None:
    env.install({**DISCREPANCY, "verdict": "consistent", "explanation": "They agree [D1] [C1]."})
    run = env.check().json()
    assert run["status"] == "completed" and run["verdict"] == "consistent"
    assert run["actions"] == []
    assert next(s for s in run["steps"] if s["name"] == "draft_action")["status"] == "skipped"


@pytest.mark.integration
def test_irrelevant_claim_is_stopped_by_the_gate_without_calling_the_model(env) -> None:
    app.dependency_overrides[get_settings] = lambda: Settings(
        chunk_max_chars=300, chunk_overlap_chars=60, consistency_min_cosine=0.9
    )
    llm = env.install(DISCREPANCY)
    run = env.check("zebra quantum spaghetti").json()
    assert run["verdict"] == "insufficient_evidence" and run["status"] == "completed"
    assert run["result"]["downgrade_reason"] == "evidence_gate"
    assert llm.calls == []  # the model was never consulted
    judge = next(s for s in run["steps"] if s["name"] == "judge")
    assert judge["status"] == "skipped" and "model was not consulted" in judge["output"]["reason"]


@pytest.mark.integration
def test_verdict_without_citations_on_both_sides_is_downgraded_and_drafts_nothing(env) -> None:
    env.install({**DISCREPANCY, "implementation_refs": []})
    run = env.check().json()
    assert run["verdict"] == "insufficient_evidence"
    assert run["result"]["downgrade_reason"] == "missing_citations_on_both_sides"
    assert run["actions"] == []


@pytest.mark.integration
def test_unparseable_model_output_becomes_insufficient_evidence(env) -> None:
    env.install("I think they differ.")
    run = env.check().json()
    assert run["verdict"] == "insufficient_evidence"
    assert run["result"]["downgrade_reason"] == "model_output_invalid"
    assert run["status"] == "completed"


@pytest.mark.integration
def test_a_code_identifier_in_the_claim_adds_symbol_evidence(env) -> None:
    # With one passage per side, this claim's wording ("MAX_POISON_STACKS 5 5 5") makes search
    # return the module-level constant chunk, so the apply_poison function can only arrive through
    # the symbol lookup.
    app.dependency_overrides[get_settings] = lambda: Settings(
        chunk_max_chars=300,
        chunk_overlap_chars=60,
        consistency_min_cosine=0.05,
        consistency_top_k=1,
    )
    env.install(DISCREPANCY)
    run = env.check("MAX_POISON_STACKS 5 5 5 apply_poison").json()
    step = next(s for s in run["steps"] if s["name"] == "lookup_symbols")
    assert step["status"] == "ok"
    assert step["input"]["identifiers"] == ["MAX_POISON_STACKS", "apply_poison"]
    evidence = run["result"]["implementation_evidence"]
    assert [e["origin"] for e in evidence] == ["search", "symbol"]
    assert evidence[1]["section"] == "apply_poison" and evidence[1]["ref"] == "C2"
    assert evidence[1]["score"] is None  # found by name, not by similarity


@pytest.mark.integration
def test_a_symbol_already_found_by_search_is_not_added_twice(env) -> None:
    env.install(DISCREPANCY)
    run = env.check("apply_poison should stack up to 3 times").json()
    evidence = run["result"]["implementation_evidence"]
    assert len({e["chunk_id"] for e in evidence}) == len(evidence)  # no duplicates


@pytest.mark.integration
def test_model_outage_fails_the_run_but_keeps_the_audit_trail(env) -> None:
    env.install(LLMError("Ollama request failed: connection refused"))
    response = env.check()
    assert response.status_code == 201  # the record is the deliverable
    run = response.json()
    assert run["status"] == "failed" and "connection refused" in run["error"]
    names = [s["name"] for s in run["steps"]]
    assert names[:4] == STEP_NAMES[:4] and names[-1] == "judge"
    assert run["steps"][-1]["status"] == "error"
    assert run["actions"] == [] and run["result"] is None


@pytest.mark.integration
def test_embedding_outage_fails_the_run_at_the_first_step(env) -> None:
    app.dependency_overrides[get_embedder] = DownEmbedder
    env.install(DISCREPANCY)
    run = env.check().json()
    assert run["status"] == "failed"
    assert [s["name"] for s in run["steps"]] == ["search_design"]
    assert run["steps"][0]["status"] == "error"
    assert "connection refused" in run["steps"][0]["output"]["error"]


@pytest.mark.integration
def test_runs_can_be_listed_and_fetched(env) -> None:
    env.install(DISCREPANCY)
    first = env.check().json()
    env.install({**DISCREPANCY, "verdict": "consistent"})
    second = env.check("poison stacks again").json()
    listing = env.api.get("/agent/runs").json()
    assert listing["total"] == 2
    assert [r["id"] for r in listing["items"]] == [second["id"], first["id"]]  # newest first
    assert (
        listing["items"][1]["claim"] == CLAIM
        and listing["items"][1]["verdict"] == "potential_discrepancy"
    )
    assert env.api.get(f"/agent/runs/{first['id']}").json()["id"] == first["id"]
    assert env.api.get(f"/agent/runs/{uuid.uuid4()}").status_code == 404


@pytest.mark.integration
@pytest.mark.parametrize("claim", ["", "ab", "x" * 1001])
def test_claim_length_is_validated(env, claim) -> None:
    assert env.check(claim).status_code == 422


@pytest.mark.integration
def test_deleting_a_run_source_document_does_not_break_stored_runs(env) -> None:
    env.install(DISCREPANCY)
    run = env.check().json()
    doc = env.api.get("/documents").json()["items"][0]
    assert env.api.delete(f"/documents/{doc['id']}").status_code == 204
    # Evidence is stored as citations, so the run still reads back, just pointing at a gone file.
    assert env.api.get(f"/agent/runs/{run['id']}").status_code == 200


@pytest.mark.integration
def test_task_survives_deletion_of_its_run(env, db_engine) -> None:
    env.install(DISCREPANCY)
    run = env.check().json()
    env.api.post(f"/agent/actions/{run['actions'][0]['id']}/approve")
    with Session(db_engine) as session:
        session.delete(session.get(AgentRun, uuid.UUID(run["id"])))
        session.commit()
        tasks = list(session.scalars(select(Task)))
    assert len(tasks) == 1 and tasks[0].source_run_id is None  # SET NULL, not cascade


# ------------------------------------------------------------------ per-source judge (M19)


@pytest.mark.integration
def test_per_source_mode_lets_contradicting_code_override_an_agreeing_source(env) -> None:
    app.dependency_overrides[get_settings] = lambda: Settings(
        chunk_max_chars=300,
        chunk_overlap_chars=60,
        consistency_min_cosine=0.05,
        consistency_judge="per_source",
    )
    llm = env.install(
        {
            "design": [{"ref": "D1", "stance": "states"}],
            "implementation": [
                {"ref": "C1", "stance": "contradicts", "evidence": "poison_stacks = 1"}
            ],
            "explanation": "Design says stacks accumulate; code appears to reset [D1] [C1].",
        }
    )
    run = env.check().json()
    assert run["verdict"] == "potential_discrepancy" and run["status"] == "awaiting_approval"
    assert "ONE SOURCE AT A TIME" in llm.calls[0][0]  # the per-source prompt was used
    judge = next(s for s in run["steps"] if s["name"] == "judge")
    assert judge["input"]["mode"] == "per_source"
    assert run["result"]["implementation_evidence"][0]["cited"] is True
    assert len(run["actions"]) == 1  # still only a draft: a human approves it


@pytest.mark.integration
def test_default_mode_is_unchanged_and_uses_the_original_prompt(env) -> None:
    llm = env.install(DISCREPANCY)
    run = env.check().json()
    assert run["verdict"] == "potential_discrepancy"
    assert "ONE SOURCE AT A TIME" not in llm.calls[0][0]
    assert Settings().consistency_judge == "verdict"
