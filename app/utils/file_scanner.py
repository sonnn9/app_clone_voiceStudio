"""Recursive discovery of TXT scripts."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

# Folders that never contain user scripts (and may be huge).
_SKIP_DIRS = {".git", "__pycache__", "node_modules", ".venv", "venv"}


@dataclass(frozen=True)
class ScannedFile:
    path: Path
    root: Path

    @property
    def relative_path(self) -> Path:
        return self.path.relative_to(self.root)

    @property
    def relative_folder(self) -> str:
        parent = self.relative_path.parent
        return "" if str(parent) == "." else str(parent)


def scan_txt_files(root: Path, recursive: bool = True) -> list[ScannedFile]:
    """Return every ``*.txt`` (case-insensitive) under *root*, sorted naturally."""
    root = Path(root).resolve()
    if root.is_file():
        return [ScannedFile(root, root.parent)] if root.suffix.lower() == ".txt" else []
    results: list[ScannedFile] = []
    for path in _walk(root, recursive):
        if path.suffix.lower() == ".txt" and path.is_file():
            results.append(ScannedFile(path, root))
    results.sort(key=lambda f: _natural_key(str(f.relative_path)))
    return results


def _walk(root: Path, recursive: bool) -> Iterable[Path]:
    try:
        entries = list(root.iterdir())
    except (PermissionError, OSError):
        return
    for entry in entries:
        if entry.is_dir():
            if recursive and entry.name not in _SKIP_DIRS:
                yield from _walk(entry, recursive)
        else:
            yield entry


def _natural_key(text: str) -> list:
    import re

    return [int(t) if t.isdigit() else t.casefold() for t in re.split(r"(\d+)", text)]
