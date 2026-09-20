from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="AIJP_", extra="ignore")

    # 127.0.0.1, not localhost: compose publishes the database on IPv4 loopback only, and on
    # Docker Desktop "localhost" resolves to ::1 first, which hangs ~20-30 s per new connection
    # before falling back to IPv4.
    database_url: str = "postgresql+psycopg://aijp:aijp@127.0.0.1:5432/aijp"
    max_upload_bytes: int = 10 * 1024 * 1024
    chunk_max_chars: int = 1200
    chunk_overlap_chars: int = 150
    # Fixed at schema creation; matches nomic-embed-text (Ollama). Changing it needs a migration.
    embedding_dim: int = 768
    embedding_model: str = "nomic-embed-text"
    ollama_base_url: str = "http://127.0.0.1:11434"
    embed_batch_size: int = 32
    # Default stays "vector" until the retrieval benchmark (eval/) shows hybrid is better.
    retrieval_mode: Literal["vector", "lexical", "hybrid"] = "vector"
    retrieval_pool: int = 20  # candidates taken from each retriever before fusion
    rrf_k: int = 60
    llm_model: str = "qwen3.5"
    # Let the ANSWER model reason before it replies (slower; see eval/results/qa-*-think.md).
    llm_think: bool = False
    # Where the evaluation runners write reports; the UI lists and serves them read-only.
    eval_results_dir: Path = Path(__file__).resolve().parents[1] / "eval" / "results"
    ask_top_k: int = 5
    # Reranking (app/rerank.py) reorders the top `rerank_pool` candidates with one extra model
    # call. OFF by default: eval/results/rerank-*.md shows better ranking but it adds about 1.7 s
    # per query, and its effect on answer quality has not been measured end to end yet.
    rerank_enabled: bool = False
    # Calculator mode (app/calc.py): the model writes arithmetic, code evaluates it exactly.
    # OFF by default until the held-out evaluation (eval/results/qa-v3-*) says otherwise.
    ask_calculator: bool = False
    rerank_pool: int = 10
    # Secure by default: every endpoint except health probes and the static UI needs an API key.
    # Turning this off makes the whole API (uploads, deletes, approvals) open; only do it on a
    # machine nobody else can reach. Keys are managed with `python -m app.keys`.
    auth_enabled: bool = True
    log_level: str = "INFO"
    log_format: Literal["json", "plain"] = "plain"  # containers set json
    # /metrics is unauthenticated, like the rest of the API: keep it off the public internet
    # (see docs/deployment.md), or set this to false.
    metrics_enabled: bool = True
    # Consistency check: passages fetched per side, and the best cosine each side must reach before
    # the model is asked to judge. 0.60 was chosen from the sweep in
    # eval/results/consistency-2026-09-20.md (16 claims): every claim with real evidence still
    # passed and all four unsupported claims were blocked, where 0.55 blocked only half. The margin
    # is thin (the weakest real-evidence claim sits between 0.60 and 0.65), so revisit it as the
    # dataset grows or the embedding model changes.
    consistency_top_k: int = 4
    consistency_min_cosine: float = 0.60
    # Raw cosine similarity below which we refuse without calling the LLM. Chosen from the
    # threshold table in eval/results/qa-2026-09-20.md (nomic-embed-text, 48 questions): at 0.55
    # every answerable question still passed and 25% of unanswerable ones were blocked. That
    # dataset is small and self-authored, and the gate only stops off-topic questions (near-misses
    # score higher than some answerable ones), so revisit it if the embedding model or data change.
    min_evidence_score: float = 0.55

    @model_validator(mode="after")
    def _check_chunk_settings(self) -> "Settings":
        if self.chunk_max_chars < 100:
            raise ValueError("chunk_max_chars must be at least 100")
        if not 0 <= self.chunk_overlap_chars <= self.chunk_max_chars // 2:
            raise ValueError("chunk_overlap_chars must be between 0 and chunk_max_chars / 2")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
