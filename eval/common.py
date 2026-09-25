"""Small helpers shared by the evaluation runners."""

from pathlib import Path

from app.config import Settings


def dataset_tag(path: Path, default_stem: str) -> str:
    """'' for the original dataset, '-v2' for `<default_stem>_v2.json`, and so on.

    Keeps a run on a new dataset from overwriting the published report of the original one."""
    stem = path.stem
    if stem == default_stem:
        return ""
    return "-" + stem.removeprefix(default_stem + "_").replace("_", "-")


def embedding_input_label(settings: Settings) -> str:
    """Report-header value: what each chunk's vector was computed from."""
    return "file + heading path + text" if settings.embed_section_path else "text only"


def embedding_tag(settings: Settings) -> str:
    """Filename tag, so a run with section-path embeddings never overwrites a baseline report."""
    return "-sectionpath" if settings.embed_section_path else ""
