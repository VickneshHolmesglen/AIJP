"""Section-path embeddings: a chunk's VECTOR may be computed from its file + heading path + text,
while the stored text (what the model reads and what is cited) stays exactly the chunk."""

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.search import get_embedder
from app.config import Settings, get_settings
from app.embeddings import embedding_input
from app.main import app
from app.models import Chunk
from tests.fakes import FakeEmbedder

TEXT = "Each upgrade level adds 25 percent to the tower's base damage."
PATH, SECTION = "docs/design/towers.md", "Towers > Upgrades and selling"


def test_off_is_exactly_the_chunk_text() -> None:
    assert embedding_input(TEXT, PATH, SECTION, with_path=False) == TEXT
    assert embedding_input(TEXT, PATH, None, with_path=False) == TEXT


def test_on_carries_the_file_the_heading_path_and_the_whole_text() -> None:
    out = embedding_input(TEXT, PATH, SECTION, with_path=True)
    assert PATH in out and SECTION in out and TEXT in out


def test_on_without_a_section_still_carries_the_file_and_never_the_word_none() -> None:
    out = embedding_input('{"waves": []}', "data/waves.json", None, with_path=True)
    assert "data/waves.json" in out and '{"waves": []}' in out and "None" not in out


def test_it_is_deterministic() -> None:  # the same chunk must always get the same vector
    once = embedding_input(TEXT, PATH, SECTION, with_path=True)
    assert once == embedding_input(TEXT, PATH, SECTION, with_path=True)


class Recording(FakeEmbedder):
    def __init__(self) -> None:
        self.seen: list[str] = []

    def embed(self, texts: list[str]) -> list[list[float]]:
        self.seen.extend(texts)
        return super().embed(texts)


MD = b"# Towers\nOverview.\n\n## Upgrades and selling\n" + TEXT.encode() + b"\n"


@pytest.mark.integration
@pytest.mark.parametrize("on", [False, True], ids=["off", "on"])
def test_the_embed_step_uses_the_setting_and_never_touches_the_stored_text(client, db_engine, on):
    recorder = Recording()
    app.dependency_overrides[get_embedder] = lambda: recorder
    app.dependency_overrides[get_settings] = lambda: Settings(
        chunk_max_chars=300, embed_section_path=on
    )
    try:
        client.post("/documents", files={"file": ("towers.md", MD)}, data={"source_path": PATH})
        assert client.post("/embeddings").json()["embedded"] >= 1
    finally:
        app.dependency_overrides.pop(get_embedder, None)
    with Session(db_engine) as session:
        (stored,) = session.scalars(
            select(Chunk.content).where(Chunk.content.contains("25 percent"))
        ).all()
    assert TEXT in stored  # citations and answers read this, and embedding never alters it
    upgrade = next(s for s in recorder.seen if TEXT in s)
    assert stored in upgrade
    assert (upgrade != stored) is on and (PATH in upgrade) is on


def test_the_shipped_default_is_off() -> None:
    assert Settings.model_fields["embed_section_path"].default is False
