"""Output path generation and existing-file policy."""
from __future__ import annotations

import re
from pathlib import Path

from app.core.settings import ExistingBehavior, OutputMode

_INVALID_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_RESERVED = {
    "CON", "PRN", "AUX", "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}


def sanitize_filename(name: str) -> str:
    """Replace only characters Windows forbids; Unicode is preserved."""
    cleaned = _INVALID_CHARS.sub("_", name).rstrip(" .")
    if not cleaned:
        cleaned = "output"
    if cleaned.split(".")[0].upper() in _RESERVED:
        cleaned = f"_{cleaned}"
    return cleaned


def build_output_path(
    source: Path,
    root: Path | None,
    output_mode: str,
    custom_dir: str,
    extension: str,
) -> Path:
    """``story1.txt`` → ``story1.mp3`` beside it, or mirrored under *custom_dir*."""
    source = Path(source)
    stem = sanitize_filename(source.stem)
    ext = extension.lstrip(".").lower()
    if output_mode == OutputMode.CUSTOM_FOLDER.value and custom_dir:
        base = Path(custom_dir)
        if root is not None:
            try:
                rel_parent = source.parent.resolve().relative_to(Path(root).resolve())
            except ValueError:
                rel_parent = Path()
        else:
            rel_parent = Path()
        return base / rel_parent / f"{stem}.{ext}"
    return source.parent / f"{stem}.{ext}"


def suffixed_path(path: Path, max_tries: int = 999) -> Path:
    """``story1.mp3`` → first free ``story1_001.mp3``."""
    for i in range(1, max_tries + 1):
        candidate = path.with_name(f"{path.stem}_{i:03d}{path.suffix}")
        if not candidate.exists():
            return candidate
    raise FileExistsError(f"No free suffix for {path}")


def resolve_existing(path: Path, behavior: str) -> tuple[Path | None, str]:
    """Apply the existing-file policy.

    Returns ``(path_to_write, decision)`` where decision is one of
    ``"new"``, ``"skip"``, ``"overwrite"``, ``"suffix"``, ``"ask"``.
    ``path_to_write`` is ``None`` for skip/ask.
    """
    if not path.exists():
        return path, "new"
    if behavior == ExistingBehavior.OVERWRITE.value:
        return path, "overwrite"
    if behavior == ExistingBehavior.SUFFIX.value:
        return suffixed_path(path), "suffix"
    if behavior == ExistingBehavior.ASK.value:
        return None, "ask"
    return None, "skip"
