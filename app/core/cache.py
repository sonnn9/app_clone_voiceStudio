"""Content-addressed cache of generated segments."""
from __future__ import annotations

import hashlib
import json
import logging
import os
import shutil
from pathlib import Path
from typing import Any

from app.utils.paths import cache_dir

log = logging.getLogger("core.cache")

CACHE_VERSION = 1


def segment_key(text: str, voice_key: str, voice_instruct: str, model: str, params: dict[str, Any]) -> str:
    """Stable SHA-256 over everything that changes the generated audio."""
    payload = {
        "v": CACHE_VERSION,
        "text": text,
        "voice": voice_key,
        "voice_instruct": voice_instruct,
        "model": model,
        "params": {k: params[k] for k in sorted(params) if params[k] is not None},
    }
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


class AudioCache:
    def __init__(self, directory: Path | None = None) -> None:
        self.directory = Path(directory) if directory else cache_dir()

    def _path(self, key: str) -> Path:
        return self.directory / key[:2] / f"{key}.wav"

    def get(self, key: str) -> Path | None:
        p = self._path(key)
        return p if p.is_file() and p.stat().st_size > 44 else None

    def put(self, key: str, source: Path) -> None:
        dest = self._path(key)
        try:
            dest.parent.mkdir(parents=True, exist_ok=True)
            tmp = dest.with_suffix(".part")
            shutil.copyfile(source, tmp)
            os.replace(tmp, dest)
        except OSError as e:
            log.warning("Cache write failed: %s", e)

    def size_bytes(self) -> int:
        return sum(f.stat().st_size for f in self.directory.rglob("*.wav") if f.is_file())

    def clear(self) -> None:
        for child in self.directory.iterdir():
            if child.is_dir():
                shutil.rmtree(child, ignore_errors=True)
            else:
                try:
                    child.unlink()
                except OSError:
                    pass
