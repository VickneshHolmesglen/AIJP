import json
import types
import uuid

import httpx
import pytest

from app.llm import LLMError, OllamaLLM
from app.qa import Evidence, _parse, build_context, is_evidence_sufficient


def _evidence(ref: int, score: float, **chunk_fields) -> Evidence:
    fields = {
        "content": "Poison stacks up to 3.",
        "section": None,
        "page": None,
        "start_line": None,
        "end_line": None,
    } | chunk_fields
    chunk = types.SimpleNamespace(**fields)
    doc = types.SimpleNamespace(id=uuid.uuid4(), source_path="design/towers.md")
    return Evidence(ref, chunk, doc, score, score)  # type: ignore[arg-type]


def test_sufficient_uses_best_hit_against_threshold() -> None:
    assert is_evidence_sufficient([_evidence(1, 0.6), _evidence(2, 0.1)], 0.5)
    assert not is_evidence_sufficient([_evidence(1, 0.49)], 0.5)
    assert not is_evidence_sufficient([], 0.5)


def test_context_numbers_sources_and_includes_provenance() -> None:
    ctx = build_context(
        [
            _evidence(1, 0.9, section="Towers > Poison", start_line=4, end_line=5),
            _evidence(2, 0.8, page=3),
        ]
    )
    assert "[1] (path: design/towers.md, section: Towers > Poison, lines: 4-5)" in ctx
    assert "[2] (path: design/towers.md, page: 3)" in ctx


def test_parse_valid() -> None:
    raw = json.dumps({"answerable": True, "answer": " 3 [1] ", "citations": [1, 1, 2]})
    assert _parse(raw) == (True, "3 [1]", [1, 1, 2])


@pytest.mark.parametrize(
    "raw",
    [
        "not json",
        "[]",
        json.dumps({"answerable": "yes", "answer": "x", "citations": [1]}),
        json.dumps({"answerable": False, "answer": "", "citations": []}),
    ],
)
def test_parse_malformed_or_declined_is_not_answerable(raw: str) -> None:
    assert _parse(raw)[0] is False


def test_parse_drops_non_integer_citations() -> None:
    raw = json.dumps({"answerable": True, "answer": "a", "citations": [1, "2", True, 1.5, None]})
    assert _parse(raw)[2] == [1]


def _llm(handler) -> OllamaLLM:
    client = httpx.Client(base_url="http://ollama", transport=httpx.MockTransport(handler))
    return OllamaLLM("http://ollama", "m", client=client)


def test_ollama_llm_returns_content_and_sends_system_prompt() -> None:
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update(json.loads(request.content))
        return httpx.Response(
            200,
            json={"message": {"content": "{}"}, "prompt_eval_count": 7, "eval_count": 3},
        )

    completion = _llm(handler).generate("sys", "usr")
    assert completion.text == "{}"
    assert (completion.prompt_tokens, completion.completion_tokens) == (7, 3)
    assert [m["role"] for m in seen["messages"]] == ["system", "user"]
    assert seen["options"]["temperature"] == 0


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(500),
        httpx.Response(200, json={"nope": 1}),
        httpx.Response(200, json={"message": {"content": "  "}}),
    ],
)
def test_ollama_llm_errors(response: httpx.Response) -> None:
    with pytest.raises(LLMError):
        _llm(lambda r: response).generate("s", "u")
