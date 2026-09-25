from typing import Protocol

import httpx


class EmbeddingError(Exception):
    """The embedding provider is unreachable or returned something unusable."""


class EmbeddingProvider(Protocol):
    """Anything that turns texts into fixed-size vectors.

    A Protocol (structural typing) rather than a base class: tests pass a deterministic fake and a
    future OpenAI/Voyage provider drops in without inheriting from anything.
    """

    @property
    def dimension(self) -> int: ...

    def embed(self, texts: list[str]) -> list[list[float]]:
        """Return one vector per input text, in order."""
        ...


def embedding_input(content: str, source_path: str, section: str | None, *, with_path: bool) -> str:
    """The text a chunk's VECTOR is computed from. `Chunk.content` (what the model reads and what
    is cited) never changes; only the embedding input can carry the chunk's location.

    Why: a rule chunk ("Each upgrade level adds 25 percent...") or a data chunk (raw JSON counts)
    shares no words with a question that names an entity, so it ranks 9-25 (v5 diagnosis). Its
    file path and heading path ("docs/design/towers.md", "Towers > Upgrades and selling") do.
    """
    if not with_path:
        return content
    # Location first (titles lead in the text the model was trained on), then a newline so it does
    # not read as part of the first sentence. data/waves.json has only "waves" as its section, so
    # the file path is kept: for data files it is the only extra signal.
    location = f"{source_path} > {section}" if section else source_path
    return f"{location}\n{content}"


class OllamaEmbedder:
    def __init__(
        self,
        base_url: str,
        model: str,
        dimension: int,
        timeout: float = 60.0,
        client: httpx.Client | None = None,
    ) -> None:
        self._client = client or httpx.Client(base_url=base_url, timeout=timeout)
        self._model = model
        self._dimension = dimension

    @property
    def dimension(self) -> int:
        return self._dimension

    def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        try:
            response = self._client.post("/api/embed", json={"model": self._model, "input": texts})
            response.raise_for_status()
            vectors = response.json()["embeddings"]
        except httpx.HTTPError as exc:
            raise EmbeddingError(f"Ollama request failed: {exc}") from exc
        except (KeyError, ValueError) as exc:
            raise EmbeddingError("Unexpected response from Ollama /api/embed") from exc

        if len(vectors) != len(texts):
            raise EmbeddingError(f"Expected {len(texts)} embeddings, got {len(vectors)}")
        # A wrong-sized vector would be rejected by pgvector anyway; fail early with a clear cause.
        for vector in vectors:
            if len(vector) != self._dimension:
                raise EmbeddingError(
                    f"Model '{self._model}' returned {len(vector)}-d vectors, "
                    f"but the schema expects {self._dimension}"
                )
        return [[float(x) for x in vector] for vector in vectors]
