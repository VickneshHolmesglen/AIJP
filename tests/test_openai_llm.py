"""OpenAI-compatible provider (Chat Completions): the request body is pinned exactly, because the
incompatibilities that matter are SILENT. Probed on Ollama's /v1 (2026-09-27): `think: false` is
ignored (the model thinks anyway and returns empty content) and `max_completion_tokens` is ignored
(the token cap does nothing). Only `reasoning_effort` and `max_tokens` work there."""

import json

import httpx
import pytest
from pydantic import SecretStr

from app import providers
from app.config import Settings
from app.llm import LLMError, OllamaLLM, OpenAICompatibleLLM

KEY = "sk-test-0123456789abcdef"


def reply(content='{"answerable": false}', finish="stop", usage=(40, 7)) -> dict:
    return {
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": content},
                "finish_reason": finish,
            }
        ],
        "usage": {"prompt_tokens": usage[0], "completion_tokens": usage[1]},
    }


def client(handler, **kwargs) -> OpenAICompatibleLLM:
    transport = httpx.MockTransport(handler)
    base = "http://server/v1"
    return OpenAICompatibleLLM(
        base, "m", client=httpx.Client(transport=transport, base_url=base), **kwargs
    )


def capture(**kwargs) -> tuple[dict, httpx.Request]:
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["request"] = request
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json=reply())

    client(handler, **kwargs).generate("SYS", "USER")
    return seen["body"], seen["request"]


def test_the_request_is_a_standard_chat_completion_with_json_mode_and_thinking_off() -> None:
    body, request = capture(max_tokens=1024)
    assert request.method == "POST" and request.url.path == "/v1/chat/completions"
    assert body == {
        "model": "m",
        "messages": [{"role": "system", "content": "SYS"}, {"role": "user", "content": "USER"}],
        "temperature": 0,
        "response_format": {"type": "json_object"},
        "reasoning_effort": "none",  # NOT `think: false`, which Ollama's /v1 silently ignores
        "max_tokens": 1024,
    }
    assert "authorization" not in request.headers  # no key configured: no header at all


def test_thinking_on_asks_for_reasoning_and_no_cap_sends_no_token_parameter() -> None:
    body, _ = capture(think=True)
    assert body["reasoning_effort"] == "medium"
    assert "max_tokens" not in body and "max_completion_tokens" not in body


def test_servers_without_reasoning_support_get_no_reasoning_parameter() -> None:
    body, _ = capture(send_reasoning_effort=False)  # e.g. a plain hosted chat model: it would 400
    assert "reasoning_effort" not in body


def test_the_token_parameter_name_is_configurable_for_newer_openai_models() -> None:
    body, _ = capture(max_tokens=500, token_param="max_completion_tokens")
    assert body["max_completion_tokens"] == 500 and "max_tokens" not in body


def test_a_key_is_sent_as_a_bearer_header() -> None:
    _, request = capture(api_key=SecretStr(KEY))
    assert request.headers["authorization"] == f"Bearer {KEY}"


def test_text_usage_and_truncation_are_read_from_the_response() -> None:
    llm = client(lambda r: httpx.Response(200, json=reply('{"a": 1}', "stop", (40, 7))))
    done = llm.generate("s", "u")
    assert (done.text, done.prompt_tokens, done.completion_tokens, done.truncated) == (
        '{"a": 1}',
        40,
        7,
        False,
    )
    cut = client(lambda r: httpx.Response(200, json=reply('{"a":', "length"))).generate("s", "u")
    assert cut.truncated is True  # the same signal the 1024 cap and the escalation rely on


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(401, json={"error": {"message": "bad key"}}),
        httpx.Response(404, json={"error": {"message": "model not found"}}),
        httpx.Response(500, text="boom"),
        httpx.Response(200, text="not json"),
        httpx.Response(200, json={"choices": []}),
        httpx.Response(200, json=reply(content="")),
        httpx.Response(200, json=reply(content=None)),  # e.g. a refusal or a tool call
    ],
    ids=["401", "404", "500", "not-json", "no-choices", "empty", "null-content"],
)
def test_every_failure_is_an_llm_error(response: httpx.Response) -> None:
    llm = client(lambda r: response, api_key=SecretStr(KEY))
    with pytest.raises(LLMError) as err:
        llm.generate("s", "u")
    assert KEY not in str(err.value)  # an error message must never carry the key


def test_a_timeout_is_an_llm_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow", request=request)

    with pytest.raises(LLMError):
        client(handler).generate("s", "u")


def test_the_key_never_appears_in_the_provider_repr_or_settings_repr() -> None:
    llm = OpenAICompatibleLLM("http://server/v1", "m", api_key=SecretStr(KEY))
    assert KEY not in repr(llm) and KEY not in repr(vars(llm))
    assert KEY not in repr(Settings(openai_api_key=KEY))


# ------------------------------------------------------------------ one factory for every caller


def test_the_factory_builds_the_configured_provider_with_the_callers_limits() -> None:
    ollama = providers.make_llm(Settings(), think=False, max_tokens=1024)
    assert isinstance(ollama, OllamaLLM)  # the shipped default is unchanged
    openai = providers.make_llm(
        Settings(llm_provider="openai", openai_token_param="max_completion_tokens"),
        think=True,
        max_tokens=1500,
        timeout=45.0,
    )
    assert isinstance(openai, OpenAICompatibleLLM)
    assert (openai.model, openai.think, openai.max_tokens, openai.token_param, openai.timeout) == (
        "qwen3.5",
        True,
        1500,
        "max_completion_tokens",
        45.0,
    )


def test_the_default_openai_base_url_is_the_local_ollama_compatibility_endpoint() -> None:
    assert Settings().openai_base_url == "http://127.0.0.1:11434/v1"
    assert Settings.model_fields["llm_provider"].default == "ollama"
