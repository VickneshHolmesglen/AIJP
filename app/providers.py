"""The real (Ollama-backed) embedding and LLM providers, built once and shared.

Kept out of the API modules so the HTTP API and the MCP server construct the same objects the same
way. Tests never call these: they inject fakes through FastAPI dependency overrides or through the
`ProjectTools` constructor.
"""

from functools import lru_cache

from app.config import Settings, get_settings
from app.embeddings import OllamaEmbedder
from app.llm import LLMProvider, OllamaLLM, OpenAICompatibleLLM


@lru_cache
def embedder() -> OllamaEmbedder:
    settings = get_settings()
    return OllamaEmbedder(
        settings.ollama_base_url, settings.embedding_model, settings.embedding_dim
    )


def make_llm(
    settings: Settings, *, think: bool, max_tokens: int | None, timeout: float = 180.0
) -> LLMProvider:
    """The ONE place a chat model client is built: the API, the MCP server and every eval runner
    call this, so switching `llm_provider` can never leave one of them on the other API."""
    if settings.llm_provider == "openai":
        return OpenAICompatibleLLM(
            settings.openai_base_url,
            settings.llm_model,
            api_key=settings.openai_api_key,
            timeout=timeout,
            think=think,
            max_tokens=max_tokens,
            token_param=settings.openai_token_param,
            send_reasoning_effort=settings.openai_send_reasoning_effort,
        )
    return OllamaLLM(
        settings.ollama_base_url,
        settings.llm_model,
        timeout=timeout,
        think=think,
        max_tokens=max_tokens,
    )


@lru_cache
def escalation_llm() -> LLMProvider | None:
    """The capped, thinking model used to re-check some answers; None when escalation is off."""
    settings = get_settings()
    if settings.llm_escalation == "off":
        return None
    return make_llm(
        settings,
        think=True,
        max_tokens=settings.llm_escalation_tokens,
        timeout=settings.llm_escalation_timeout_seconds,
    )


def answer_token_cap(settings: Settings) -> int | None:
    """The num_predict cap for the shared model: none when it thinks (the reasoning counts toward
    the cap and 1024 would cut it off) or when the setting is 0."""
    if settings.llm_think or settings.llm_max_tokens <= 0:
        return None
    return settings.llm_max_tokens


@lru_cache
def llm() -> LLMProvider:
    settings = get_settings()
    return make_llm(settings, think=settings.llm_think, max_tokens=answer_token_cap(settings))
