"""Application data locations.

All editable data (settings, profiles, logs, cache, session) lives under
``%APPDATA%\\AudioStudioBatchTTS`` so the portable EXE never needs write access
to its own folder. ``AUDIOSTUDIO_BATCH_TTS_HOME`` overrides the location
(used by tests and portable setups).
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

from app.version import APP_ID

_ENV_OVERRIDE = "AUDIOSTUDIO_BATCH_TTS_HOME"


def app_data_dir() -> Path:
    override = os.environ.get(_ENV_OVERRIDE)
    if override:
        base = Path(override)
    elif os.name == "nt" and os.environ.get("APPDATA"):
        base = Path(os.environ["APPDATA"]) / APP_ID
    else:
        base = Path.home() / ".config" / APP_ID
    base.mkdir(parents=True, exist_ok=True)
    return base


def _sub(name: str) -> Path:
    p = app_data_dir() / name
    p.mkdir(parents=True, exist_ok=True)
    return p


def logs_dir() -> Path:
    return _sub("logs")


def cache_dir() -> Path:
    return _sub("cache")


def work_dir() -> Path:
    """Per-job temporary segment folders (kept on failure for resume)."""
    return _sub("work")


def preview_dir() -> Path:
    return _sub("preview")


def session_dir() -> Path:
    return _sub("session")


def settings_file() -> Path:
    return app_data_dir() / "settings.json"


def profiles_file() -> Path:
    return app_data_dir() / "profiles.json"


def pronunciation_file() -> Path:
    return app_data_dir() / "pronunciation.json"


def resource_dir() -> Path:
    """Bundled read-only resources (works from source and from PyInstaller)."""
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS) / "app" / "resources"  # type: ignore[attr-defined]
    return Path(__file__).resolve().parent.parent / "resources"


def executable_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent.parent
