import json
from pathlib import Path

import pytest
from sqlalchemy.orm import Session

from app import projects, services
from app.agent.claims import CLAIMS_SYSTEM
from app.config import Settings
from app.design_audit import ingest_tree, run_audit
from app.llm import Completion, LLMError
from tests.fakes import FakeEmbedder

DESIGN = (
    "# Towers\n\n## Poison\nPoison stacks up to 3 times.\n\n"
    "## Frost\nFrost slows enemies by 30 percent for 2 seconds.\n"
)
CODE = "def apply_poison(enemy):\n    enemy.poison = min(enemy.poison + 1, 5)\n"
RESOURCE = (
    '[gd_resource type="Resource" script_class="Tower" format=3]\n\n[resource]\ntower_id = &"t"\n'
)


class RoutingLLM:
    """Claim extraction and judging are both model calls: answer each by its system prompt."""

    def __init__(self, loop_on: str | None = None) -> None:
        self.loop_on = loop_on

    def generate(self, system: str, user: str) -> Completion:
        if system.startswith(CLAIMS_SYSTEM[:40]):
            if self.loop_on and self.loop_on in user:
                raise LLMError("Ollama request failed: HTTP 500 (token repeat limit reached)")
            quote = "Poison stacks up to 3 times." if "Poison" in user else "slows enemies by 30"
            claim = {"claim": f"apply_poison: {quote}", "quote": quote}
            return Completion(json.dumps({"claims": [claim]}))
        verdict = {
            "verdict": "potential_discrepancy",
            "explanation": "Design says 3, code caps at 5.",
            "design_refs": ["D1"],
            "implementation_refs": ["C1"],
        }
        return Completion(json.dumps(verdict))


@pytest.fixture
def project(client, db_engine, tmp_path: Path):  # client: wipes the tables first
    root = tmp_path / "game"
    (root / "design").mkdir(parents=True)
    (root / "src").mkdir()
    (root / "design" / "towers.md").write_text(DESIGN)
    (root / "design" / "notes-review.md").write_text("# Review\nignore me\n")
    (root / "src" / "enemy.py").write_text(CODE)
    (root / "src" / "tower.tres").write_text(RESOURCE)
    (root / "src" / "icon.png").write_bytes(b"\x89PNG")
    (root / "src" / "fake.tres").write_text("not a resource\n")
    settings = Settings(chunk_max_chars=300, chunk_overlap_chars=60)
    with Session(db_engine, expire_on_commit=False) as session:
        p = projects.create_project(session, "game", "Game")
        counts = ingest_tree(session, settings, p.id, root, ["design", "src"], ["*-review.md"])
        services.embed_pending_chunks(session, FakeEmbedder(), 32, project_id=p.id)
        yield session, settings, p, counts


@pytest.mark.integration
def test_ingest_counts_every_kind_of_file(project) -> None:
    _, _, _, counts = project
    assert counts == {"ingested": 3, "skipped_type": 1, "excluded": 1, "rejected": 1}


@pytest.mark.integration
def test_audit_ties_each_claim_to_its_line_and_its_run(project) -> None:
    session, settings, p, _ = project
    report = run_audit(
        session, FakeEmbedder(), RoutingLLM(), settings, p.id, "design/towers.md",
        section_filter=None, claims_per_passage=2, max_claims=10,
    )  # fmt: skip
    assert [c["line"] for c in report["claims"]] == [4, 7]
    assert all(c["verdict"] == "potential_discrepancy" for c in report["claims"])
    first = report["claims"][0]
    assert (
        first["design_evidence"] and first["implementation_evidence"][0]["path"] == "src/enemy.py"
    )
    assert "min(enemy.poison + 1, 5)" in first["implementation_evidence"][0]["text"]
    assert report["counts"] == {"potential_discrepancy": 2} and report["passages_failed"] == []


@pytest.mark.integration
def test_a_passage_the_model_fails_on_is_skipped_and_reported(project) -> None:
    session, settings, p, _ = project
    report = run_audit(
        session, FakeEmbedder(), RoutingLLM(loop_on="Poison"), settings, p.id, "design/towers.md",
        section_filter=None, claims_per_passage=2, max_claims=10,
    )  # fmt: skip
    assert [c["line"] for c in report["claims"]] == [7]
    [failed] = report["passages_failed"]
    assert "repeat limit" in failed["error"]


@pytest.mark.integration
def test_section_filter_and_claim_cap(project) -> None:
    session, settings, p, _ = project
    only_frost = run_audit(
        session, FakeEmbedder(), RoutingLLM(), settings, p.id, "design/towers.md",
        section_filter="frost", claims_per_passage=2, max_claims=10,
    )  # fmt: skip
    assert [c["line"] for c in only_frost["claims"]] == [7]
    capped = run_audit(
        session, FakeEmbedder(), RoutingLLM(), settings, p.id, "design/towers.md",
        section_filter=None, claims_per_passage=2, max_claims=1,
    )  # fmt: skip
    # the bare "# Towers" heading passage yields nothing; reading stops once the cap is hit
    assert len(capped["claims"]) == 1 and capped["passages_read"] == 2


@pytest.mark.integration
def test_unknown_document_is_an_error(project) -> None:
    session, settings, p, _ = project
    with pytest.raises(SystemExit):
        run_audit(
            session, FakeEmbedder(), RoutingLLM(), settings, p.id, "design/nope.md",
            section_filter=None, claims_per_passage=2, max_claims=1,
        )  # fmt: skip
