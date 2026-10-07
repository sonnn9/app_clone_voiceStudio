"""Robust reading of user TXT files (UTF-8, UTF-8 BOM, UTF-16)."""
from __future__ import annotations

import codecs
import json
import os
import tempfile
from pathlib import Path
from typing import Any


class TextDecodeError(Exception):
    """Raised when a TXT file cannot be decoded with any supported encoding."""


def read_text_file(path: Path) -> tuple[str, str]:
    """Return ``(text, encoding)``.

    Detection order: BOMs (UTF-8 / UTF-16 LE/BE), strict UTF-8, a UTF-16
    heuristic for BOM-less files (many NUL bytes), then cp1258/cp1252 is NOT
    attempted silently – a clear error is raised instead so the user knows.
    """
    data = Path(path).read_bytes()
    try:
        if data.startswith(codecs.BOM_UTF8):
            return data[len(codecs.BOM_UTF8):].decode("utf-8"), "utf-8-sig"
        if data.startswith(codecs.BOM_UTF16_LE) or data.startswith(codecs.BOM_UTF16_BE):
            return data.decode("utf-16"), "utf-16"
    except UnicodeDecodeError as e:
        raise TextDecodeError(
            f"'{Path(path).name}' has a Unicode BOM but invalid content ({e.reason}). Re-save it as UTF-8."
        ) from e
    try:
        return data.decode("utf-8"), "utf-8"
    except UnicodeDecodeError:
        pass
    if data and data.count(b"\x00") > len(data) // 4:
        for enc in ("utf-16-le", "utf-16-be"):
            try:
                return data.decode(enc), enc
            except UnicodeDecodeError:
                continue
    raise TextDecodeError(
        f"Cannot decode '{Path(path).name}'. Save the file as UTF-8 (or UTF-16) and retry."
    )


def atomic_write_text(path: Path, text: str) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=path.name, suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(text)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def load_json(path: Path, default: Any) -> Any:
    path = Path(path)
    if not path.exists():
        return default
    try:
        text, _ = read_text_file(path)
        return json.loads(text)
    except (OSError, ValueError, TextDecodeError):
        return default


def save_json(path: Path, data: Any) -> None:
    atomic_write_text(Path(path), json.dumps(data, ensure_ascii=False, indent=2))
