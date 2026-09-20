"""Reranking wired into /search and /ask (off by default), with fake embedder and model."""

import json
import re

import pytest

from app.api.ask import get_llm
from app.api.search import get_embedder
from app.config import Settings, get_settings
from app.llm import Completion
from app.main import app
from tests.fakes import FakeEmbedder

pytestmark = pytest.mark.integration

MD = (
    b"# Towers\nOverview of towers.\n\n## Poison\nPoison stacks up to 3 times.\n\n"
    b"## Fire\nFire burns for 5 seconds.\n"
)
QUESTION = "poison stack limit"  # plain retrieval puts the Poison chunk first


class RoutingLLM:
    """Plays both roles. As the reranker it grades the chunk containing `favourite` 3 and the rest
    0; as the answerer it cites source 1."""

    def __init__(self, favourite: str = "Fire burns", rerank_reply: str | None = None) -> None:
        self.favourite = favourite
        self.rerank_reply = rerank_reply
        self.rerank_calls = 0
        self.answer_prompts: list[str] = []

    def generate(self, system: str, user: str) -> Completion:
        if system.startswith("You grade"):
            self.rerank_calls += 1
            if self.rerank_reply is not None:
                return Completion(self.rerank_reply)
            blocks = re.split(r"\n\n(?=\[\d+\] )", user)
            grades = {
                str(n): 3 if self.favourite in block else 0
                for n, block in enumerate(blocks[1:], start=1)
            }
            return Completion(json.dumps({"grades": grades}))
        self.answer_prompts.append(user)
        return Completion(
            json.dumps({"answerable": True, "answer": "See [1].", "citations": [1]}),
            prompt_tokens=10,
            completion_tokens=5,
        )


@pytest.fixture
def stack(client):
    def start(rerank: bool, llm: RoutingLLM) -> RoutingLLM:
        app.dependency_overrides[get_settings] = lambda: Settings(
            chunk_max_chars=300,
            chunk_overlap_chars=60,
            min_evidence_score=0.2,
            rerank_enabled=rerank,
        )
        app.dependency_overrides[get_llm] = lambda: llm
        return llm

    app.dependency_overrides[get_embedder] = FakeEmbedder
    app.dependency_overrides[get_settings] = lambda: Settings(
        chunk_max_chars=300, chunk_overlap_chars=60
    )
    client.post("/documents", files={"file": ("towers.md", MD)}, data={"source_path": "d/t.md"})
    client.post("/embeddings")
    yield start
    app.dependency_overrides.pop(get_embedder, None)
    app.dependency_overrides.pop(get_llm, None)


def sections(body: dict) -> list[str]:
    return [h["citation"]["section"] for h in body["hits"]]


def test_search_is_unchanged_and_makes_no_model_call_when_reranking_is_off(client, stack):
    llm = stack(False, RoutingLLM())
    body = client.post("/search", json={"query": QUESTION, "top_k": 3}).json()
    assert sections(body)[0] == "Towers > Poison"
    assert all(h["rerank_grade"] is None for h in body["hits"])
    assert llm.rerank_calls == 0


def test_search_reorders_by_the_rerankers_grades_and_keeps_provenance(client, stack):
    llm = stack(True, RoutingLLM(favourite="Fire burns"))
    plain = client.post("/search", json={"query": QUESTION, "top_k": 3}).json()
    stack(False, RoutingLLM())
    baseline = client.post("/search", json={"query": QUESTION, "top_k": 3}).json()
    assert sections(baseline)[0] == "Towers > Poison"
    assert plain["hits"][0]["citation"]["section"] == "Towers > Fire"
    assert plain["hits"][0]["rerank_grade"] == 3
    # Same chunks, same citations; only the order changed.
    assert sorted(sections(plain)) == sorted(sections(baseline))
    by_chunk = {h["chunk_id"]: h["citation"] for h in baseline["hits"]}
    assert all(by_chunk[h["chunk_id"]] == h["citation"] for h in plain["hits"])
    assert llm.rerank_calls == 1


def test_search_respects_top_k_after_reranking(client, stack):
    stack(True, RoutingLLM(favourite="Fire burns"))
    body = client.post("/search", json={"query": QUESTION, "top_k": 1}).json()
    assert sections(body) == ["Towers > Fire"]  # pool of 10 was reranked, then cut to 1


def test_a_failing_reranker_degrades_to_retrieval_order(client, stack):
    stack(False, RoutingLLM())
    baseline = client.post("/search", json={"query": QUESTION, "top_k": 3}).json()
    stack(True, RoutingLLM(rerank_reply="this is not json"))
    body = client.post("/search", json={"query": QUESTION, "top_k": 3})
    assert body.status_code == 200
    assert sections(body.json()) == sections(baseline)
    assert all(h["rerank_grade"] is None for h in body.json()["hits"])


def test_ask_numbers_sources_in_reranked_order(client, stack):
    llm = stack(True, RoutingLLM(favourite="Fire burns"))
    body = client.post("/ask", json={"question": QUESTION}).json()
    assert body["refused"] is False
    assert body["sources"][0]["citation"]["section"] == "Towers > Fire"  # cited [1]
    assert "[1] (path: d/t.md, section: Towers > Fire" in llm.answer_prompts[0]


def test_ask_without_reranking_keeps_retrieval_order(client, stack):
    llm = stack(False, RoutingLLM(favourite="Fire burns"))
    body = client.post("/ask", json={"question": QUESTION}).json()
    assert body["sources"][0]["citation"]["section"] == "Towers > Poison"
    assert llm.rerank_calls == 0


def test_the_evidence_gate_refuses_before_any_reranking_call(client, stack):
    app.dependency_overrides[get_settings] = lambda: Settings(
        chunk_max_chars=300, min_evidence_score=0.99, rerank_enabled=True
    )
    llm = RoutingLLM()
    app.dependency_overrides[get_llm] = lambda: llm
    body = client.post("/ask", json={"question": QUESTION}).json()
    assert body["refused"] is True and body["reason"] == "insufficient_evidence"
    assert llm.rerank_calls == 0 and llm.answer_prompts == []


def test_rerank_outcomes_are_counted(client, stack):
    from prometheus_client import REGISTRY

    def count(outcome: str) -> float:
        return REGISTRY.get_sample_value("rerank_total", {"outcome": outcome}) or 0.0

    ok, fallback = count("ok"), count("fallback")
    stack(True, RoutingLLM())
    client.post("/search", json={"query": QUESTION})
    stack(True, RoutingLLM(rerank_reply="nope"))
    client.post("/search", json={"query": QUESTION})
    assert (count("ok") - ok, count("fallback") - fallback) == (1, 1)
