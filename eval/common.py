"""Small helpers shared by the evaluation runners."""

from pathlib import Path


def dataset_tag(path: Path, default_stem: str) -> str:
    """'' for the original dataset, '-v2' for `<default_stem>_v2.json`, and so on.

    Keeps a run on a new dataset from overwriting the published report of the original one."""
    stem = path.stem
    if stem == default_stem:
        return ""
    return "-" + stem.removeprefix(default_stem + "_").replace("_", "-")
