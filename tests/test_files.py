"""Scanning, encodings, output paths and existing-file behaviour."""
from pathlib import Path

import pytest

from app.core.output_paths import build_output_path, resolve_existing, sanitize_filename
from app.utils.file_scanner import scan_txt_files
from app.utils.text_io import TextDecodeError, read_text_file


@pytest.fixture
def tree(tmp_path: Path) -> Path:
    (tmp_path / "lesson1" / "deep").mkdir(parents=True)
    (tmp_path / "lesson2").mkdir()
    (tmp_path / "story1.txt").write_text("a", encoding="utf-8")
    (tmp_path / "story2.TXT").write_text("b", encoding="utf-8")
    (tmp_path / "lesson1" / "conversation1.txt").write_text("c", encoding="utf-8")
    (tmp_path / "lesson1" / "deep" / "x.txt").write_text("d", encoding="utf-8")
    (tmp_path / "lesson2" / "Bài đọc số 1.txt").write_text("đ", encoding="utf-8")
    (tmp_path / "lesson2" / "notes.md").write_text("ignored", encoding="utf-8")
    return tmp_path


def test_recursive_scan_finds_all_txt(tree: Path):
    found = scan_txt_files(tree)
    rel = sorted(str(f.relative_path).replace("\\", "/") for f in found)
    assert rel == sorted([
        "story1.txt", "story2.TXT", "lesson1/conversation1.txt",
        "lesson1/deep/x.txt", "lesson2/Bài đọc số 1.txt",
    ])


def test_scan_relative_folder(tree: Path):
    found = {f.path.name: f.relative_folder for f in scan_txt_files(tree)}
    assert found["story1.txt"] == ""
    assert found["x.txt"].replace("\\", "/") == "lesson1/deep"


def test_non_recursive_scan(tree: Path):
    names = {f.path.name for f in scan_txt_files(tree, recursive=False)}
    assert names == {"story1.txt", "story2.TXT"}


def test_unicode_filename_output(tree: Path):
    src = tree / "lesson2" / "Bài đọc số 1.txt"
    out = build_output_path(src, tree, "same_folder", "", "mp3")
    assert out == tree / "lesson2" / "Bài đọc số 1.mp3"


def test_same_folder_output(tree: Path):
    src = tree / "lesson1" / "conversation1.txt"
    assert build_output_path(src, tree, "same_folder", "", "mp3") == src.with_suffix(".mp3")


def test_custom_folder_preserves_subfolders(tree: Path, tmp_path_factory):
    out_root = tmp_path_factory.mktemp("out")
    src = tree / "lesson1" / "deep" / "x.txt"
    out = build_output_path(src, tree, "custom_folder", str(out_root), "mp3")
    assert out == out_root / "lesson1" / "deep" / "x.mp3"


def test_sanitize_only_invalid_chars():
    assert sanitize_filename('Bài: "1"?') == "Bài_ _1__"
    assert sanitize_filename("Tiếng Việt ổn") == "Tiếng Việt ổn"
    assert sanitize_filename("CON") == "_CON"
    assert sanitize_filename("name. ") == "name"


def test_skip_existing(tmp_path: Path):
    out = tmp_path / "story1.mp3"
    out.write_bytes(b"x")
    assert resolve_existing(out, "skip") == (None, "skip")
    assert resolve_existing(out, "overwrite") == (out, "overwrite")
    assert resolve_existing(out, "ask") == (None, "ask")
    path, decision = resolve_existing(out, "suffix")
    assert decision == "suffix" and path.name == "story1_001.mp3"
    path.write_bytes(b"y")
    assert resolve_existing(out, "suffix")[0].name == "story1_002.mp3"


def test_new_file_is_written(tmp_path: Path):
    out = tmp_path / "new.mp3"
    assert resolve_existing(out, "skip") == (out, "new")


@pytest.mark.parametrize("encoding", ["utf-8", "utf-8-sig", "utf-16"])
def test_read_encodings(tmp_path: Path, encoding: str):
    p = tmp_path / "t.txt"
    p.write_text("Xin chào thế giới", encoding=encoding)
    text, _ = read_text_file(p)
    assert text == "Xin chào thế giới"


def test_undecodable_file_reports_error(tmp_path: Path):
    p = tmp_path / "bad.txt"
    p.write_bytes(b"\xff\xfe\xfa\xfb\x80\x81" * 3 + b"abc")  # starts like UTF-16 BOM
    try:
        read_text_file(p)
    except TextDecodeError:
        pass
    p.write_bytes(b"caf\xe9 \x81\x8d")  # invalid UTF-8, not UTF-16
    with pytest.raises(TextDecodeError):
        read_text_file(p)
