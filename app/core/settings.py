"""Persistent application settings (``%APPDATA%\\AudioStudioBatchTTS\\settings.json``)."""
from __future__ import annotations

import logging
from dataclasses import asdict, dataclass, field, fields
from enum import Enum
from typing import Any

from app.utils.paths import resource_dir, settings_file
from app.utils.text_io import load_json, save_json

log = logging.getLogger("core.settings")


class OutputMode(str, Enum):
    SAME_FOLDER = "same_folder"
    CUSTOM_FOLDER = "custom_folder"


class ExistingBehavior(str, Enum):
    SKIP = "skip"
    OVERWRITE = "overwrite"
    ASK = "ask"
    SUFFIX = "suffix"


@dataclass
class PreprocessOptions:
    collapse_spaces: bool = True
    normalize_line_endings: bool = True
    remove_extra_blank_lines: bool = True
    convert_smart_quotes: bool = False
    apply_pronunciation: bool = True


@dataclass
class AppSettings:
    # Connection
    engine_family: str = "audiostudio"
    api_base_url: str = ""
    api_discovery_candidates: list[str] = field(default_factory=list)
    timeout_s: float = 300.0
    retry_count: int = 3
    retry_delays_s: list[float] = field(default_factory=lambda: [1.0, 3.0, 5.0])

    # Output
    output_mode: str = OutputMode.SAME_FOLDER.value
    custom_output_dir: str = ""
    existing_behavior: str = ExistingBehavior.SKIP.value
    output_format: str = "mp3"
    mp3_bitrate_kbps: int = 192
    normalize_volume: bool = False
    write_metadata: bool = True
    ffmpeg_path: str = ""

    # Processing
    concurrency: int = 1
    max_chunk_chars: int = 600
    min_chunk_chars: int = 40
    sentence_aware: bool = True
    cache_enabled: bool = True
    use_folder_config: bool = True
    inherit_parent_folder_config: bool = True
    preprocess: PreprocessOptions = field(default_factory=PreprocessOptions)

    # Session memory
    last_engine: str = ""
    last_profile: str = ""
    last_mode: str = "auto"
    last_folder: str = ""
    theme: str = "light"
    window_geometry: str = ""
    ui_scale: float = 1.0

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "AppSettings":
        s = cls()
        known = {f.name for f in fields(cls)}
        for key, value in (data or {}).items():
            if key not in known:
                continue
            if key == "preprocess" and isinstance(value, dict):
                pp_known = {f.name for f in fields(PreprocessOptions)}
                s.preprocess = PreprocessOptions(**{k: v for k, v in value.items() if k in pp_known})
            else:
                setattr(s, key, value)
        s.concurrency = max(1, min(4, int(s.concurrency)))
        s.retry_count = max(0, min(10, int(s.retry_count)))
        s.mp3_bitrate_kbps = int(s.mp3_bitrate_kbps) if int(s.mp3_bitrate_kbps) in (128, 192, 256, 320) else 192
        return s

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def retry_delay(self, attempt: int) -> float:
        """Delay before retry number *attempt* (1-based), increasing."""
        delays = self.retry_delays_s or [1.0, 3.0, 5.0]
        if attempt <= len(delays):
            return float(delays[attempt - 1])
        return float(delays[-1]) + 2.0 * (attempt - len(delays))


def load_settings() -> AppSettings:
    defaults = load_json(resource_dir() / "default_settings.json", {})
    user = load_json(settings_file(), {})
    merged = {**defaults, **user}
    return AppSettings.from_dict(merged)


def save_settings(settings: AppSettings) -> None:
    try:
        save_json(settings_file(), settings.to_dict())
    except OSError as e:
        log.error("Could not save settings: %s", e)
