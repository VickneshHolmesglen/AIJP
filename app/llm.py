from dataclasses import dataclass
from typing import Literal, Protocol

import httpx
from pydantic import SecretStr


class LLMError(Exception):
    """The language model is unreachable or returned something unusable."""


@dataclass(frozen=True)
class Completion:
    text: str
    # Token counts as reported by the provider (None if it did not report them). Never estimated.
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    # True when the provider stopped because it hit the token cap, not because the model finished.
    # Whatever text came back may be a fragment: callers must not trust it.
    truncated: bool = False


class LLMProvider(Protocol):
    """Anything that completes a system+user prompt with text. Same Protocol idea as embeddings."""

    def generate(self, system: str, user: str) -> Completion: ...


class OllamaLLM:
    def __init__(
        self,
        base_url: str,
        model: str,
        timeout: float = 180.0,
        client: httpx.Client | None = None,
        think: bool = False,
        max_tokens: int | None = None,
    ) -> None:
        self._client = client or httpx.Client(base_url=base_url, timeout=timeout)
        self._model = model
        # Reasoning models can "think" before answering: slower and costlier, and off by default.
        self._think = think
        # A hard cap on generated tokens (thinking included). Unbounded thinking is unpredictable:
        # one probe ran 11,027 tokens / 160 s on a single question. None: no cap.
        self._max_tokens = max_tokens

    def generate(self, system: str, user: str) -> Completion:
        payload = {
            "model": self._model,
            "stream": False,
            # Constrains output to valid JSON; the grounded prompt asks for a specific shape.
            "format": "json",
            # Reasoning models otherwise spend the budget on hidden thinking; low temperature keeps
            # answers reproducible enough to evaluate.
            "think": self._think,
            "options": {
                "temperature": 0,
                **({"num_predict": self._max_tokens} if self._max_tokens else {}),
            },
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        }
        try:
            response = self._client.post("/api/chat", json=payload)
            response.raise_for_status()
            body = response.json()
            content = body["message"]["content"]
        except httpx.HTTPError as exc:
            raise LLMError(f"Ollama request failed: {exc}") from exc
        except (KeyError, ValueError) as exc:
            raise LLMError("Unexpected response from Ollama /api/chat") from exc
        if not isinstance(content, str) or not content.strip():
            raise LLMError("Ollama returned an empty completion")
        return Completion(
            content,
            truncated=body.get("done_reason") == "length",
            prompt_tokens=_count(body.get("prompt_eval_count")),
            completion_tokens=_count(body.get("eval_count")),
        )


def _count(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


class OpenAICompatibleLLM:
    """The OpenAI Chat Completions API, the de facto standard many servers speak: OpenAI, Azure
    OpenAI, Groq, vLLM, LM Studio, and Ollama's own /v1 endpoint (the default base URL, so this is
    exercised with the local model at no cost). Switching servers is configuration, not code.

    "Compatible" is not "identical": probed on Ollama's /v1, `think: false` and
    `max_completion_tokens` are SILENTLY ignored (the model thinks anyway; the cap does nothing).
    So thinking is controlled with `reasoning_effort` and the token parameter's name is set per
    server (`max_tokens` for Ollama and most servers; `max_completion_tokens` for newer OpenAI
    reasoning models, which reject the old name)."""

    def __init__(
        self,
        base_url: str,
        model: str,
        api_key: SecretStr | None = None,
        timeout: float = 180.0,
        client: httpx.Client | None = None,
        think: bool = False,
        max_tokens: int | None = None,
        token_param: Literal["max_tokens", "max_completion_tokens"] = "max_tokens",
        send_reasoning_effort: bool = True,
    ) -> None:
        # The key lives only in the client's default headers, never in an attribute that a repr,
        # a log line or an error message could print.
        headers = {"Authorization": f"Bearer {api_key.get_secret_value()}"} if api_key else {}
        self._client = client or httpx.Client(base_url=base_url, timeout=timeout, headers=headers)
        if client is not None and api_key:
            self._client.headers.update(headers)
        self.model = model
        self.timeout = timeout
        self.think = think
        self.max_tokens = max_tokens
        self.token_param = token_param
        self._send_reasoning_effort = send_reasoning_effort

    def __repr__(self) -> str:
        return f"OpenAICompatibleLLM(model={self.model!r}, think={self.think})"

    def generate(self, system: str, user: str) -> Completion:
        payload: dict[str, object] = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": 0,
            # JSON mode: the grounded prompt asks for a specific JSON shape.
            "response_format": {"type": "json_object"},
        }
        if self._send_reasoning_effort:
            payload["reasoning_effort"] = "medium" if self.think else "none"
        if self.max_tokens:
            payload[self.token_param] = self.max_tokens
        try:
            response = self._client.post("chat/completions", json=payload)
            response.raise_for_status()
            body = response.json()
            choice = body["choices"][0]
            content = choice["message"]["content"]
        except httpx.HTTPStatusError as exc:
            # Status only: a provider's error body can echo request details.
            raise LLMError(f"LLM request failed: HTTP {exc.response.status_code}") from None
        except httpx.HTTPError as exc:
            raise LLMError(f"LLM request failed: {type(exc).__name__}") from None
        except (KeyError, IndexError, TypeError, ValueError):
            raise LLMError("Unexpected response from the chat completions API") from None
        if not isinstance(content, str) or not content.strip():
            raise LLMError("The chat completions API returned an empty completion")
        usage = body.get("usage") or {}
        return Completion(
            content,
            truncated=choice.get("finish_reason") == "length",
            prompt_tokens=_count(usage.get("prompt_tokens")),
            completion_tokens=_count(usage.get("completion_tokens")),
        )
