"""Loaders for source code and structured config (registered in `loaders.LOADERS`).

Each loader splits a file into segments along its natural structure and records the symbol path
in `Segment.section` (e.g. "Enemy > take_damage"), so citations can say *which function* as well as
which lines. This is deliberately not full AST-aware chunking: segments are whole symbols and the
generic line chunker still splits any oversized one.

Untrusted input: nothing here executes or imports uploaded code. Python is parsed with `ast.parse`
(parse only), and GDScript/YAML are scanned line by line.
"""

import ast
import json
import re

from app.ingestion.errors import InvalidDocumentError
from app.ingestion.textutil import decode_text, segment_from_lines, stem
from app.ingestion.types import ExtractedDocument, Segment

_MAX_SECTION = 300


def _plain(lines: list[str], filename: str) -> ExtractedDocument:
    """Fallback when structure cannot be determined: the whole file as one segment."""
    seg = segment_from_lines(lines, 1, len(lines), None)
    if seg is None:
        raise InvalidDocumentError("File contains no text")
    return ExtractedDocument(title=stem(filename), segments=[seg])


def _from_starts(
    lines: list[str], starts: list[tuple[int, str | None]], filename: str
) -> ExtractedDocument:
    """Build segments from (start_line, section) markers. Each runs to the next marker, and the
    first is stretched to line 1 so every line of the file belongs to exactly one segment."""
    if not starts:
        return _plain(lines, filename)
    starts = [(1, starts[0][1]), *starts[1:]]
    segments: list[Segment] = []
    for i, (first, section) in enumerate(starts):
        last = starts[i + 1][0] - 1 if i + 1 < len(starts) else len(lines)
        if seg := segment_from_lines(
            lines, first, last, section[:_MAX_SECTION] if section else None
        ):
            segments.append(seg)
    if not segments:
        raise InvalidDocumentError("File contains no text")
    return ExtractedDocument(title=stem(filename), segments=segments)


def _attach_comments(lines: list[str], line: int, floor: int, markers: str) -> int:
    """Move a symbol's start line up over the comment/annotation lines directly above it."""
    while line > floor and lines[line - 2].lstrip().startswith(tuple(markers)):
        line -= 1
    return line


# --------------------------------------------------------------------------- Python


def load_python(content: bytes, filename: str) -> ExtractedDocument:
    text = decode_text(content)
    lines = text.split("\n")
    try:
        tree = ast.parse(text)
    except (SyntaxError, ValueError, RecursionError):
        # Broken or hostile-deep source is still searchable text; just without symbol structure.
        return _plain(lines, filename)

    starts: list[tuple[int, str | None]] = []

    def visit(body: list[ast.stmt], prefix: str) -> None:
        for node in body:
            if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
                first = min([node.lineno, *(d.lineno for d in node.decorator_list)])
                floor = starts[-1][0] + 1 if starts else 1
                first = _attach_comments(lines, first, floor, "#")
                name = f"{prefix}{node.name}"
                starts.append((first, name))
                if isinstance(node, ast.ClassDef):
                    visit(node.body, f"{name} > ")
            elif not prefix and (not starts or starts[-1][1] != "module"):
                # Imports/constants between symbols form one "module" segment.
                starts.append((node.lineno, "module"))

    visit(tree.body, "")
    return _from_starts(lines, starts, filename)


# --------------------------------------------------------------------------- GDScript

_GD_CLASS_NAME = re.compile(r"^class_name\s+(\w+)")
_GD_INNER_CLASS = re.compile(r"^class\s+(\w+)")
_GD_FUNC = re.compile(r"^(?:static\s+)?func\s+(\w+)")
_GD_DECL = re.compile(r"^(?:@\w+(?:\([^)]*\))?\s+)*(?:static\s+)?(?:signal|var|const|enum)\s+(\w+)")


def _indent(line: str) -> int:
    return len(line) - len(line.lstrip(" \t"))


_GD_ANNOTATION_ONLY = re.compile(r"^@\w+(?:\(.*\))?$")


def _is_marker(line: str) -> bool:
    """Comment or annotation-only line (attaches to the declaration below it)."""
    stripped = line.strip()
    return stripped.startswith("#") or bool(_GD_ANNOTATION_ONLY.match(stripped))


def load_gdscript(content: bytes, filename: str) -> ExtractedDocument:
    lines = decode_text(content).split("\n")
    class_name = next((m.group(1) for line in lines if (m := _GD_CLASS_NAME.match(line))), None)
    segments: list[Segment] = []

    def emit(first: int, last: int, section: str | None) -> None:
        section = section[:_MAX_SECTION] if section else None
        if seg := segment_from_lines(lines, first, last, section):
            segments.append(seg)

    def scan(lo: int, hi: int, base: int, prefix: str) -> None:
        """Split 1-based inclusive lines [lo, hi] whose members sit at indent `base`."""
        heads = [
            n
            for n in range(lo, hi + 1)
            if lines[n - 1].strip()
            and _indent(lines[n - 1]) == base
            and not _is_marker(lines[n - 1])
        ]
        if not heads:
            emit(lo, hi, prefix.removesuffix(" > ") or None)
            return

        # Pass 1: a block runs from its head (pulled up over comments/annotations) to the next.
        firsts = [lo] + [
            _attach_comments(lines, head, prev + 1, "#@")
            for prev, head in zip(heads, heads[1:], strict=False)
        ]
        blocks = []  # (first, last, head, kind, name)
        for i, head in enumerate(heads):
            last = firsts[i + 1] - 1 if i + 1 < len(firsts) else hi
            text = lines[head - 1].strip()
            if m := _GD_FUNC.match(text):
                blocks.append((firsts[i], last, head, "func", m.group(1)))
            elif m := _GD_INNER_CLASS.match(text):
                blocks.append((firsts[i], last, head, "class", m.group(1)))
            else:
                decl = _GD_DECL.match(text)
                blocks.append((firsts[i], last, head, "decl", decl.group(1) if decl else ""))

        # Pass 2: functions and classes get their own segment; runs of one-line declarations
        # (signals, vars, consts, enums, extends...) merge so we don't emit tiny useless chunks.
        i = 0
        while i < len(blocks):
            first, last, head, kind, name = blocks[i]
            if kind == "func":
                emit(first, last, f"{prefix}{name}")
            elif kind == "class":
                path = f"{prefix}{name}"
                emit(first, head, path)
                body = next(
                    (
                        n
                        for n in range(head + 1, last + 1)
                        if lines[n - 1].strip() and not _is_marker(lines[n - 1])
                    ),
                    None,
                )
                if body is not None and _indent(lines[body - 1]) > base:
                    scan(head + 1, last, _indent(lines[body - 1]), f"{path} > ")
                else:
                    emit(head + 1, last, path)
            else:
                j = i
                names: list[str] = []
                while j < len(blocks) and blocks[j][3] == "decl":
                    if blocks[j][4]:
                        names.append(blocks[j][4])
                    j += 1
                label = f"{prefix}declarations: {', '.join(names)}" if names else f"{prefix}header"
                emit(first, blocks[j - 1][1], label)
                i = j
                continue
            i += 1

    scan(1, len(lines), 0, f"{class_name} > " if class_name else "")
    if not segments:
        raise InvalidDocumentError("File contains no text")
    return ExtractedDocument(title=class_name or stem(filename), segments=segments)


# --------------------------------------------------------------------------- YAML / JSON

_YAML_KEY = re.compile(r"""^(?![-#%\s])(?!---|\.\.\.)("[^"]+"|'[^']+'|[^:#]+?)\s*:(?:\s|$)""")


def load_yaml(content: bytes, filename: str) -> ExtractedDocument:
    """Sections are top-level keys. No YAML parser: we index text, we don't interpret it."""
    lines = decode_text(content).split("\n")
    keys = [
        (n, m.group(1).strip("\"'"))
        for n, line in enumerate(lines, 1)
        if (m := _YAML_KEY.match(line))
    ]
    if len(keys) < 2:
        return _plain(lines, filename)
    starts: list[tuple[int, str | None]] = []
    for n, key in keys:
        floor = starts[-1][0] + 1 if starts else 1
        starts.append((_attach_comments(lines, n, floor, "#"), key))
    return _from_starts(lines, starts, filename)


def _json_top_level_keys(text: str) -> list[tuple[int, str]]:
    """(line, key) for each key of the root object. `text` must already be valid JSON."""
    keys: list[tuple[int, str]] = []
    depth = 0
    line = 1
    expect_key = False
    i, n = 0, len(text)
    while i < n:
        ch = text[i]
        if ch == "\n":
            line += 1
        elif ch == '"':
            start = i
            i += 1
            while text[i] != '"':
                i += 2 if text[i] == "\\" else 1
            if depth == 1 and expect_key:
                keys.append((line, json.loads(text[start : i + 1])))
                expect_key = False
        elif ch in "{[":
            depth += 1
            expect_key = ch == "{" and depth == 1
        elif ch in "}]":
            depth -= 1
        elif ch == "," and depth == 1:
            expect_key = True
        i += 1
    return keys


def load_json(content: bytes, filename: str) -> ExtractedDocument:
    text = decode_text(content)
    try:
        root = json.loads(text)
    except (ValueError, RecursionError) as exc:
        raise InvalidDocumentError("File is not valid JSON") from exc
    lines = text.split("\n")
    if not isinstance(root, dict):
        return _plain(lines, filename)
    by_line: dict[int, list[str]] = {}
    for n, key in _json_top_level_keys(text):
        by_line.setdefault(n, []).append(key)
    if len(by_line) < 2:  # minified or tiny: nothing to split on
        return _plain(lines, filename)
    return _from_starts(lines, [(n, ", ".join(ks)) for n, ks in by_line.items()], filename)
