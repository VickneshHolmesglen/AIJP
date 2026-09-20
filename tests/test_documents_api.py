import uuid

import pytest

from tests.pdf_helper import make_pdf

pytestmark = pytest.mark.integration

MD = (
    b"# Towers\nOverview of towers.\n\n## Poison\nPoison stacks up to 3 times.\n\n"
    b"## Fire\nFire burns for 5 seconds.\n"
)


def upload(client, name="towers.md", content=MD, **data):
    return client.post("/documents", files={"file": (name, content)}, data=data)


def test_upload_markdown_returns_chunks_with_provenance(client):
    response = upload(client, source_path="design/towers.md")
    assert response.status_code == 201
    body = response.json()
    assert body["source_path"] == "design/towers.md"
    assert body["file_type"] == "md"
    assert body["title"] == "Towers"
    assert body["chunk_count"] == len(body["chunks"]) == 3
    poison = next(c for c in body["chunks"] if c["section"] == "Towers > Poison")
    assert "stacks up to 3" in poison["content"]
    assert (poison["start_line"], poison["end_line"]) == (4, 5)


def test_source_path_defaults_to_filename(client):
    assert upload(client).json()["source_path"] == "towers.md"


def test_upload_txt_and_pdf(client):
    txt = upload(client, "notes.txt", b"plain notes\nsecond line")
    assert txt.status_code == 201 and txt.json()["file_type"] == "txt"

    pdf = upload(client, "spec.pdf", make_pdf(["Enemy health is 100", "Towers cost 50 gold"]))
    assert pdf.status_code == 201
    body = pdf.json()
    assert body["file_type"] == "pdf" and body["page_count"] == 2
    assert sorted(c["page"] for c in body["chunks"]) == [1, 2]


def test_long_document_is_split_into_multiple_chunks(client):
    content = "\n".join(f"line {i}: " + "word " * 10 for i in range(1, 40)).encode()
    body = upload(client, "long.txt", content).json()
    assert body["chunk_count"] > 3
    assert [c["chunk_index"] for c in body["chunks"]] == list(range(body["chunk_count"]))


def test_duplicate_upload_is_rejected_with_existing_id(client):
    first = upload(client).json()
    second = upload(client, "renamed.md")
    assert second.status_code == 409
    assert second.json()["detail"]["document_id"] == first["id"]
    assert client.get("/documents").json()["total"] == 1


@pytest.mark.parametrize(
    ("name", "content", "status"),
    [
        pytest.param("evil.exe", b"MZ", 415, id="unsupported-extension"),
        pytest.param("noext", b"hi", 415, id="no-extension"),
        pytest.param("empty.txt", b"  \n", 422, id="empty"),
        pytest.param("fake.pdf", b"not a pdf", 422, id="fake-pdf"),
        pytest.param("corrupt.pdf", b"%PDF-1.4\ngarbage", 422, id="corrupt-pdf"),
        pytest.param("blank.pdf", make_pdf([""]), 422, id="pdf-without-text"),
        pytest.param("binary.txt", b"a\x00b", 422, id="binary-as-text"),
        pytest.param("latin1.txt", b"caf\xe9", 422, id="not-utf8"),
        pytest.param("huge.txt", b"x" * 60_000, 413, id="too-large"),
    ],
)
def test_malformed_uploads_are_rejected(client, name, content, status):
    assert upload(client, name, content).status_code == status
    assert client.get("/documents").json()["total"] == 0


@pytest.mark.parametrize("bad_path", ["../x.md", "/etc/passwd", "C:/x.md"])
def test_unsafe_source_path_rejected(client, bad_path):
    assert upload(client, source_path=bad_path).status_code == 422


def test_filename_is_sanitised(client):
    body = upload(client, "../../evil/notes.txt", b"hello").json()
    assert body["filename"] == "notes.txt"


def test_list_get_and_pagination(client):
    ids = [upload(client, f"d{i}.txt", f"doc {i}".encode()).json()["id"] for i in range(3)]

    page = client.get("/documents", params={"limit": 2}).json()
    assert page["total"] == 3 and len(page["items"]) == 2
    assert all(item["chunk_count"] == 1 for item in page["items"])
    assert len(client.get("/documents", params={"limit": 2, "offset": 2}).json()["items"]) == 1

    detail = client.get(f"/documents/{ids[0]}")
    assert detail.status_code == 200 and detail.json()["id"] == ids[0]
    assert client.get("/documents", params={"limit": 0}).status_code == 422


def test_get_and_delete_unknown_id_404(client):
    missing = uuid.uuid4()
    assert client.get(f"/documents/{missing}").status_code == 404
    assert client.delete(f"/documents/{missing}").status_code == 404
    assert client.get("/documents/not-a-uuid").status_code == 422


def test_delete_removes_document_and_chunks(client, db_engine):
    from sqlalchemy import func, select

    from app.models import Chunk

    doc_id = upload(client).json()["id"]
    assert client.delete(f"/documents/{doc_id}").status_code == 204
    assert client.get(f"/documents/{doc_id}").status_code == 404
    with db_engine.connect() as conn:
        assert conn.scalar(select(func.count()).select_from(Chunk)) == 0
    # Same bytes can be ingested again after deletion.
    assert upload(client).status_code == 201


def test_upload_python_records_symbol_sections_and_line_ranges(client):
    src = b"import math\n\n\nclass Enemy:\n    def take_damage(self, n):\n        return n\n"
    body = upload(client, "enemy.py", src, source_path="src/enemy.py").json()
    assert body["file_type"] == "py"
    by_section = {c["section"]: c for c in body["chunks"]}
    method = by_section["Enemy > take_damage"]
    assert (method["start_line"], method["end_line"]) == (5, 6)
    assert "return n" in method["content"]


def test_upload_gdscript_and_yaml_and_json(client):
    gd = upload(client, "enemy.gd", b"class_name Enemy\n\nfunc take_damage(n):\n\tpass\n")
    assert gd.status_code == 201
    assert {c["section"] for c in gd.json()["chunks"]} >= {"Enemy > take_damage"}

    yml = upload(client, "cfg.yml", b"a: 1\nb: 2\n")
    assert yml.status_code == 201 and yml.json()["file_type"] == "yaml"

    js = upload(client, "cfg.json", b'{\n  "a": 1,\n  "b": 2\n}\n')
    assert js.status_code == 201
    assert [c["section"] for c in js.json()["chunks"]] == ["a", "b"]


def test_invalid_json_is_rejected_with_422(client):
    assert upload(client, "bad.json", b'{"a": ').status_code == 422
    assert client.get("/documents").json()["total"] == 0
