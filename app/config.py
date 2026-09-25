from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

EscalationMode = Literal["off", "derived", "cue", "classify", "always"]


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
    # Embed each chunk WITH its file and heading path (app/embeddings.py `embedding_input`); the
    # stored text and citations are unchanged. EXPERIMENTAL, off until the v6 eval says otherwise.
    # Changing it on a database that already has vectors needs a full re-embed: the two kinds of
    # vector must never share an index (there is no automatic re-embed yet).
    embed_section_path: bool = False
    # Hard cap on the tokens one non-thinking call may generate (0 = no cap). Answers are 50-300
    # tokens, but on v3 c02 the model reasoned inside its JSON answer for 15,665 tokens / 227 s and
    # the request failed on the 180 s client timeout. A cut-off answer is refused as
    # `answer_truncated`. Not applied when llm_think is on: Ollama counts thinking toward the cap.
    llm_max_tokens: int = 1024
    # Escalation (app/qa.py): answer normally first, then re-ask WITH thinking only when it pays.
    # "off"; "derived": the first answer contains a number that is not in the cited passages or the
    # question (a computed number, where non-thinking answers go wrong); "cue": that, OR the
    # question contains arithmetic cue words; "classify": that, OR a cheap non-thinking call
    # says the question needs a calculation; "always": every answer. Cue and classify also
    # require the first answer to contain a number.
    # The thinking call is capped at `llm_escalation_tokens` and falls back to the first answer if
    # it is cut off or fails. DEFAULT "derived" (user decision after eval/results/
    # compare-escalation-*.md: 57 -> 69 of 94 correct, 12 gained / 0 lost, refusals unchanged).
    # Evaluation baselines must now set AIJP_LLM_ESCALATION=off explicitly.
    llm_escalation: EscalationMode = "derived"
    llm_escalation_tokens: int = 1500
    # A token cap is not a time cap: on a loaded machine 1,500 tokens took ~195 s. The re-check
    # also has a wall-clock limit, after which the first answer is returned. (A safety net, set
    # above the ~25 s worst case measured on an idle machine, so it did not affect the results.)
    llm_escalation_timeout_seconds: float = 45.0
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
    # the model is asked to judge. 0.60 was first picked from 16 claims (all 4 unsupported blocked)
    # and CONFIRMED on the pooled sweep over 60 claims, eval/results/gate-sweep-consistency-*.md:
    # it lets 39 of 40 claims with real evidence through and blocks 13 of 20 unsupported ones (the
    # v1-only "4 of 4" was luck: on-topic near-misses score high). 0.65 would block 18 of 20 but
    # lose 8 of 40 real claims. Kept by the user's decision; revisit if the embedding model changes.
    consistency_top_k: int = 4
    consistency_min_cosine: float = 0.60
    # How the consistency check reaches a verdict. "verdict": the model picks one (the original).
    # "per_source": the model states a stance for EVERY source and code decides, so one agreeing
    # config value cannot hide code that disagrees. See eval/results/consistency-v3-*.md.
    consistency_judge: Literal["verdict", "per_source"] = "verdict"
    # The MCP server (local stdio) serves ONE project, chosen by whoever launches it. It never
    # takes a project from the model, which reads untrusted document text.
    mcp_project: str = "default"
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
