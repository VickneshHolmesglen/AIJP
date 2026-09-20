from dataclasses import dataclass
from typing import Protocol

import httpx


class LLMError(Exception):
    """The language model is unreachable or returned something unusable."""


@dataclass(frozen=True)
class Completion:
    text: str
    # Token counts as reported by the provider (None if it did not report them). Never estimated.
    prompt_tokens: int | None = None
    completion_tokens: int | None = None


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
    ) -> None:
        self._client = client or httpx.Client(base_url=base_url, timeout=timeout)
        self._model = model
        # Reasoning models can "think" before answering: slower and costlier, and off by default.
        self._think = think

    def generate(self, system: str, user: str) -> Completion:
        payload = {
            "model": self._model,
            "stream": False,
            # Constrains output to valid JSON; the grounded prompt asks for a specific shape.
            "format": "json",
            # Reasoning models otherwise spend the budget on hidden thinking; low temperature keeps
            # answers reproducible enough to evaluate.
            "think": self._think,
            "options": {"temperature": 0},
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
            prompt_tokens=_count(body.get("prompt_eval_count")),
            completion_tokens=_count(body.get("eval_count")),
        )


def _count(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None
