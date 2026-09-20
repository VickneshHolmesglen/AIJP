import pytest

from app.ingestion.errors import FileTooLargeError, InvalidDocumentError, UnsupportedFileTypeError
from app.ingestion.validation import sanitize_filename, sanitize_source_path, validate_upload


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("notes.txt", "notes.txt"),
        ("../../etc/passwd.txt", "passwd.txt"),
        ("C:\\Users\\me\\doc.md", "doc.md"),
        ("bad\x00name\n.txt", "badname.txt"),
        ("   ", ""),
    ],
)
def test_sanitize_filename(raw, expected):
    assert sanitize_filename(raw) == expected


def test_sanitize_source_path_normalises():
    assert sanitize_source_path("design\\towers.md") == "design/towers.md"
    assert sanitize_source_path("./src//enemy.gd") == "src/enemy.gd"


@pytest.mark.parametrize("bad", ["../secret.md", "/etc/passwd", "C:/x.md", "a/../../b.md", " / "])
def test_sanitize_source_path_rejects_unsafe(bad):
    with pytest.raises(InvalidDocumentError):
        sanitize_source_path(bad)


def test_validate_upload_accepts_supported_types():
    assert validate_upload("a.TXT", b"hi", 100) == "txt"
    assert validate_upload("a.md", b"# hi", 100) == "md"
    assert validate_upload("a.pdf", b"%PDF-1.4 ...", 100) == "pdf"


def test_validate_upload_rejections():
    with pytest.raises(UnsupportedFileTypeError):
        validate_upload("a.exe", b"hi", 100)
    with pytest.raises(UnsupportedFileTypeError):
        validate_upload("noextension", b"hi", 100)
    with pytest.raises(FileTooLargeError):
        validate_upload("a.txt", b"x" * 101, 100)
    with pytest.raises(InvalidDocumentError):
        validate_upload("a.txt", b"   \n", 100)
    with pytest.raises(InvalidDocumentError):
        validate_upload("a.pdf", b"just text pretending", 100)
    with pytest.raises(InvalidDocumentError):
        validate_upload("a.txt", b"bin\x00ary", 100)
    with pytest.raises(InvalidDocumentError):
        validate_upload("", b"hi", 100)


@pytest.mark.parametrize(
    "name,expected",
    [("a.py", "py"), ("a.GD", "gd"), ("a.json", "json"), ("a.yaml", "yaml"), ("a.yml", "yaml")],
)
def test_code_and_config_extensions_are_accepted(name, expected):
    assert validate_upload(name, b"x", 100) == expected


def test_source_file_with_null_bytes_is_rejected():
    with pytest.raises(InvalidDocumentError):
        validate_upload("evil.py", b"print(1)\x00", 100)
