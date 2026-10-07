"""Locate and run ffmpeg (bundled beside the EXE, configured path, or PATH)."""
from __future__ import annotations

import logging
import os
import shutil
import subprocess
from pathlib import Path

from app.utils.paths import executable_dir

log = logging.getLogger("audio.ffmpeg")

_CREATE_NO_WINDOW = 0x08000000 if os.name == "nt" else 0


class FFmpegMissingError(RuntimeError):
    def __init__(self) -> None:
        super().__init__(
            "ffmpeg was not found. Install ffmpeg (e.g. `winget install Gyan.FFmpeg`), put ffmpeg.exe "
            "next to AudioStudioBatchTTS.exe, or set its path in Settings. WAV output works without it."
        )


def find_ffmpeg(configured: str = "") -> str | None:
    exe = "ffmpeg.exe" if os.name == "nt" else "ffmpeg"
    candidates: list[Path] = []
    if configured:
        p = Path(configured)
        candidates.append(p / exe if p.is_dir() else p)
    base = executable_dir()
    candidates += [base / exe, base / "ffmpeg" / exe, base / "ffmpeg" / "bin" / exe]
    for c in candidates:
        if c.is_file():
            return str(c)
    return shutil.which("ffmpeg")


def run_ffmpeg(ffmpeg: str, args: list[str], timeout: float = 600.0) -> subprocess.CompletedProcess:
    cmd = [ffmpeg, "-hide_banner", "-nostdin", "-y", *args]
    log.debug("ffmpeg %s", " ".join(args))
    proc = subprocess.run(
        cmd,
        capture_output=True,
        timeout=timeout,
        creationflags=_CREATE_NO_WINDOW,
    )
    if proc.returncode != 0:
        err = proc.stderr.decode("utf-8", "replace")[-1500:]
        raise RuntimeError(f"ffmpeg failed ({proc.returncode}): {err}")
    return proc


def ffmpeg_version(ffmpeg: str) -> str:
    try:
        proc = subprocess.run([ffmpeg, "-version"], capture_output=True, timeout=10, creationflags=_CREATE_NO_WINDOW)
        return proc.stdout.decode("utf-8", "replace").splitlines()[0]
    except (OSError, subprocess.SubprocessError, IndexError):
        return ""
