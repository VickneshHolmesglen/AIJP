import hashlib
import json
import math
import re

from app.embeddings import EmbeddingError
from app.llm import Completion

DIM = 768


class FakeEmbedder:
    """Bag-of-words hashed into DIM buckets: shared words => higher cosine similarity."""

    dimension = DIM

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [self._one(t) for t in texts]

    @staticmethod
    def _one(text: str) -> list[float]:
        vec = [0.0] * DIM
        for word in re.findall(r"[a-z0-9]+", text.lower()):
            vec[int(hashlib.md5(word.encode()).hexdigest(), 16) % DIM] += 1.0
        norm = math.sqrt(sum(x * x for x in vec)) or 1.0
        return [x / norm for x in vec]


class DownEmbedder:
    dimension = DIM

    def embed(self, texts: list[str]) -> list[list[float]]:
        raise EmbeddingError("Ollama request failed: connection refused")


class ScriptedLLM:
    def __init__(self, reply: dict | str | Exception, *, truncated: bool = False) -> None:
        self.reply = reply
        self.truncated = truncated
        self.calls: list[tuple[str, str]] = []

    def generate(self, system: str, user: str) -> Completion:
        self.calls.append((system, user))
        if isinstance(self.reply, Exception):
            raise self.reply
        text = self.reply if isinstance(self.reply, str) else json.dumps(self.reply)
        return Completion(text, prompt_tokens=120, completion_tokens=15, truncated=self.truncated)
