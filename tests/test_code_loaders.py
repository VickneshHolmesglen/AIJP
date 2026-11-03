import pytest

from app.ingestion.errors import InvalidDocumentError
from app.ingestion.loaders import extract
from app.ingestion.types import ExtractedDocument

PY = b'''"""Enemy module."""
import math

MAX_HP = 100


# Damage is reduced by armor.
@staticmethod
def calc_damage(raw, armor):
    return max(0, raw - armor)


class Enemy:
    """A basic enemy."""
    speed = 3

    def __init__(self, hp):
        self.hp = hp

    async def take_damage(self, amount):
        self.hp -= amount

    class Boss:
        def enrage(self):
            pass


TAIL = 1
'''

GD = b"""class_name Enemy
extends CharacterBody2D

signal died
signal damaged(amount)

const MAX_HP := 100
@export var health: int = 100
@export_range(0, 10)
var speed: float = 3.0

enum State { IDLE, CHASE }

# Applies damage and emits died.
func take_damage(amount: int) -> void:
\thealth -= amount
\tif health <= 0:
\t\tdied.emit()

static func make() -> Enemy:
\treturn Enemy.new()

class Loot:
\tvar gold = 5

\tfunc drop():
\t\treturn gold
"""

YAML = b"""# service config
version: "3"
services:
  web:
    image: nginx
# database section
database:
  host: db
"""

JSON = b"""{
  "name": "towers",
  "stats": {
    "hp": 10,
    "note": "a \\"quoted\\": thing, ok"
  },
  "tags": ["a", "b"]
}
"""


def sections(doc: ExtractedDocument) -> list[str | None]:
    return [s.section for s in doc.segments]


def ranges(doc: ExtractedDocument) -> list[tuple[int, int]]:
    return [(s.start_line, s.start_line + s.text.count("\n")) for s in doc.segments]


def assert_no_line_lost(doc: ExtractedDocument, source: bytes) -> None:
    """Segments must be contiguous and cover the whole file, or citations would skip content."""
    total = source.decode().count("\n") + 1
    spans = ranges(doc)
    assert spans[0][0] == 1 and spans[-1][1] == total
    assert all(prev[1] + 1 == nxt[0] for prev, nxt in zip(spans, spans[1:], strict=False))


# ------------------------------------------------------------------ Python


def test_python_symbols_and_line_ranges() -> None:
    doc = extract("py", PY, "enemy.py")
    assert sections(doc) == [
        "module",
        "calc_damage",
        "Enemy",
        "Enemy > __init__",
        "Enemy > take_damage",
        "Enemy > Boss",
        "Enemy > Boss > enrage",
        "module",
    ]
    # The comment and decorator above calc_damage belong to it, not to the module segment.
    assert ranges(doc)[:2] == [(1, 6), (7, 12)]
    assert doc.segments[1].text.lstrip().startswith("# Damage is reduced")
    assert_no_line_lost(doc, PY)


def test_python_syntax_error_falls_back_to_plain_text() -> None:
    doc = extract("py", b"def broken(:\n    pass\n", "bad.py")
    assert len(doc.segments) == 1 and doc.segments[0].section is None


def test_python_pathologically_deep_nesting_does_not_crash() -> None:
    doc = extract("py", b"x = " + b"(" * 5000 + b"1" + b")" * 5000 + b"\n", "deep.py")
    assert doc.segments


def test_python_without_symbols_is_one_module_segment() -> None:
    doc = extract("py", b"import os\nprint(os.name)\n", "s.py")
    assert sections(doc) == ["module"]


# ------------------------------------------------------------------ GDScript


def test_gdscript_symbols_and_line_ranges() -> None:
    doc = extract("gd", GD, "enemy.gd")
    assert doc.title == "Enemy"
    assert sections(doc) == [
        "Enemy > declarations: died, damaged, MAX_HP, health, speed, State",
        "Enemy > take_damage",
        "Enemy > make",
        "Enemy > Loot",
        "Enemy > Loot > declarations: gold",
        "Enemy > Loot > drop",
    ]
    assert ranges(doc)[1] == (14, 19)  # includes the comment above `func take_damage`
    assert_no_line_lost(doc, GD)


def test_gdscript_annotation_line_attaches_to_next_declaration() -> None:
    src = b'func a():\n\tpass\n\n@rpc("any", "call_local")\nfunc b():\n\tpass\n'
    doc = extract("gd", src, "n.gd")
    assert sections(doc) == ["a", "b"]
    assert doc.segments[1].text.startswith("@rpc")


def test_gdscript_without_class_name_uses_bare_symbol_names() -> None:
    doc = extract("gd", b"extends Node\n\nfunc _ready():\n\tpass\n", "main.gd")
    assert doc.title == "main"
    assert sections(doc) == ["header", "_ready"]


def test_gdscript_comment_only_file_is_single_segment() -> None:
    doc = extract("gd", b"# nothing here yet\n", "empty.gd")
    assert len(doc.segments) == 1


# ------------------------------------------------------------------ YAML


def test_yaml_sections_are_top_level_keys() -> None:
    doc = extract("yaml", YAML, "c.yml")
    assert sections(doc) == ["version", "services", "database"]
    assert ranges(doc) == [(1, 2), (3, 5), (6, 9)]  # comment attaches to the key below it
    assert_no_line_lost(doc, YAML)


def test_yaml_nested_keys_and_list_items_are_not_top_level() -> None:
    src = b"- name: a\n  value: 1\n- name: b\n  value: 2\n"
    assert sections(extract("yaml", src, "list.yaml")) == [None]


def test_yaml_with_a_single_key_is_one_segment() -> None:
    assert sections(extract("yaml", b"only: 1\n", "o.yaml")) == [None]


# ------------------------------------------------------------------ JSON


def test_json_sections_are_top_level_keys() -> None:
    doc = extract("json", JSON, "t.json")
    assert sections(doc) == ["name", "stats", "tags"]  # nested "hp"/"note" are not sections
    assert ranges(doc) == [(1, 2), (3, 6), (7, 9)]
    assert_no_line_lost(doc, JSON)


def test_json_invalid_is_rejected() -> None:
    with pytest.raises(InvalidDocumentError, match="not valid JSON"):
        extract("json", b'{"a": ', "bad.json")


def test_json_non_object_and_minified_are_single_segments() -> None:
    assert sections(extract("json", b"[1, 2, 3]", "a.json")) == [None]
    assert sections(extract("json", b'{"a": 1, "b": 2}', "m.json")) == [None]


def test_json_deep_nesting_is_rejected_not_crashed() -> None:
    with pytest.raises(InvalidDocumentError):
        extract("json", b"[" * 100_000 + b"]" * 100_000, "deep.json")


# ------------------------------------------------------------------ Godot .tres

TRES = b"""[gd_resource type="Resource" script_class="TowerBlueprintData" load_steps=3 format=3]

[ext_resource type="Script" path="res://src/core/tower/tower_blueprint_data.gd" id="1"]

[sub_resource type="Resource" id="Weapon_arcane"]
component_id = "weap_arcane_t3"
weapon_damage = 30.0

[resource]
script = ExtResource("1")
tower_id = &"arcane_lance"
display_name = "Arcane Lance"
weapon = SubResource("Weapon_arcane")
"""


def test_tres_is_one_segment_named_after_its_resource_id() -> None:
    doc = extract("tres", TRES, "blueprint_arcane_lance.tres")
    assert sections(doc) == ["TowerBlueprintData > arcane_lance"]
    seg = doc.segments[0]
    assert seg.start_line == 1 and seg.text.rstrip().endswith(
        'weapon = SubResource("Weapon_arcane")'
    )
    assert seg.text.startswith("[gd_resource")
    assert "weapon_damage = 30.0" in seg.text and "Arcane Lance" in seg.text


def test_tres_without_an_id_falls_back_to_the_script_class_then_none() -> None:
    no_id = (
        b'[gd_resource type="Resource" script_class="AudioCueEntry" format=3]\n\n'
        b'[resource]\nbus = &"UI"\n'
    )
    assert sections(extract("tres", no_id, "cue.tres")) == ["AudioCueEntry"]
    bare = b'[gd_resource type="Theme" format=3]\n\n[resource]\nfoo = 1\n'
    assert sections(extract("tres", bare, "t.tres")) == [None]


def test_tres_sub_resource_ids_do_not_name_the_file() -> None:
    # component_id lives in a sub-resource; only the [resource] block names the file.
    src = TRES.replace(b'tower_id = &"arcane_lance"\n', b"")
    assert sections(extract("tres", src, "b.tres")) == ["TowerBlueprintData"]


def test_tres_must_look_like_a_godot_resource() -> None:
    with pytest.raises(InvalidDocumentError, match="Godot"):
        extract("tres", b"a = 1\nb = 2\n", "fake.tres")


# ------------------------------------------------------------------ shared


@pytest.mark.parametrize("file_type", ["py", "gd", "yaml", "json", "tres"])
def test_whitespace_only_file_has_no_text(file_type: str) -> None:
    with pytest.raises(InvalidDocumentError):
        extract(file_type, b"  \n\n", f"x.{file_type}")


@pytest.mark.parametrize("file_type", ["py", "gd", "yaml", "tres"])
def test_non_utf8_is_rejected(file_type: str) -> None:
    with pytest.raises(InvalidDocumentError, match="UTF-8"):
        extract(file_type, b"\xff\xfe\x00bad", f"x.{file_type}")
