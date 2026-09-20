"""Symbol lookup over indexed source code (Python and GDScript).

Shared by the MCP `find_symbol` tool and the consistency-check workflow. Symbols are found through
the section path the loaders record ("Enemy > take_damage"), not by parsing code again.
"""

import re
import uuid
from dataclasses import dataclass
from typing import Literal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Chunk, Document

CODE_FILE_TYPES = ("py", "gd")
SymbolKind = Literal["definition", "declaration"]
_DECLARATIONS = "declarations: "  # section label the GDScript loader gives grouped declarations
_CANDIDATE_LIMIT = 500

# snake_case with an underscore, SCREAMING_CASE with an underscore, or CamelCase.
_IDENTIFIER = re.compile(r"\b(?:[A-Za-z]+(?:_[A-Za-z0-9]+)+|[A-Z][a-z0-9]+(?:[A-Z][a-z0-9]+)+)\b")


@dataclass(frozen=True)
class SymbolHit:
    kind: SymbolKind
    chunk: Chunk
    document: Document


def symbol_kind(section: str | None, name: str) -> SymbolKind | None:
    """How `section` (a symbol path like "Enemy > take_damage") relates to the symbol `name`.

    Exact-segment matching, so "take" does not match "take_damage". A GDScript group
    "Enemy > declarations: died, health" matches each name it lists."""
    if not section:
        return None
    last = section.split(" > ")[-1]
    if last == name:
        return "definition"
    if last.startswith(_DECLARATIONS):
        listed = [n.strip() for n in last.removeprefix(_DECLARATIONS).split(",")]
        if name in listed:
            return "declaration"
    return None


def like_escape(text: str) -> str:
    """Escape LIKE wildcards; symbol names are full of underscores, which LIKE treats as 'any'."""
    return text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def find_symbols(
    session: Session, name: str, limit: int, *, project_id: uuid.UUID | None
) -> list[SymbolHit]:
    """Definitions first, then grouped-declaration mentions; otherwise path/line order."""
    stmt = (
        select(Chunk, Document)
        .join(Document, Document.id == Chunk.document_id)
        .where(Document.file_type.in_(CODE_FILE_TYPES))
        .where(Chunk.section.like(f"%{like_escape(name)}%", escape="\\"))
        .order_by(Document.source_path, Chunk.chunk_index)
        .limit(_CANDIDATE_LIMIT)  # SQL narrows candidates; exact segment matching happens below
    )
    if project_id is not None:  # the project boundary: another project's code is never returned
        stmt = stmt.where(Document.project_id == project_id)
    rows = session.execute(stmt).all()
    hits = [
        SymbolHit(kind, chunk, doc)
        for chunk, doc in rows
        if (kind := symbol_kind(chunk.section, name)) is not None
    ]
    hits.sort(key=lambda h: h.kind != "definition")
    return hits[:limit]


def extract_identifiers(text: str, limit: int = 5) -> list[str]:
    """Code-looking identifiers mentioned in free text, in order, without duplicates.

    Plain words ("poison") are deliberately not identifiers; only names that look like code
    (take_damage, POISON_MAX_STACKS, WaveSpawner)."""
    seen: dict[str, None] = {}
    for match in _IDENTIFIER.finditer(text):
        seen.setdefault(match.group(0), None)
    return list(seen)[:limit]
