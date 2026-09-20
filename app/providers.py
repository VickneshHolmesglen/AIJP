"""The real (Ollama-backed) embedding and LLM providers, built once and shared.

Kept out of the API modules so the HTTP API and the MCP server construct the same objects the same
way. Tests never call these: they inject fakes through FastAPI dependency overrides or through the
`ProjectTools` constructor.
"""

from functools import lru_cache

from app.config import get_settings
from app.embeddings import OllamaEmbedder
from app.llm import OllamaLLM


@lru_cache
def embedder() -> OllamaEmbedder:
    settings = get_settings()
    return OllamaEmbedder(
        settings.ollama_base_url, settings.embedding_model, settings.embedding_dim
    )


@lru_cache
def llm() -> OllamaLLM:
    settings = get_settings()
    return OllamaLLM(settings.ollama_base_url, settings.llm_model, think=settings.llm_think)
