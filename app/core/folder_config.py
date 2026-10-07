"""Per-folder ``tts_config.json`` support.

Example::

    {
      "profile": "English Lesson",
      "mode": "conversation",
      "voice": "profile:demo0001",
      "speaker_voices": {"ANNA": "archetype:feat_00_the_librarian"},
      "speed": 0.9,
      "language": "en",
      "silence": {"turn_ms": 400, "paragraph_ms": 800},
      "output_format": "mp3",
      "inherit_parent": true
    }

The nearest config wins key-by-key; parent configs are merged underneath
unless a config sets ``"inherit_parent": false``.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from app.api.models import VoiceSelection
from app.core.profiles import GenerationProfile, ProfileStore, SilenceSettings
from app.utils.text_io import load_json

log = logging.getLogger("core.folder_config")

CONFIG_NAME = "tts_config.json"


def find_configs(folder: Path, root: Path | None, inherit: bool) -> list[tuple[Path, dict[str, Any]]]:
    """Configs from nearest to farthest (stopping at *root* or ``inherit_parent: false``)."""
    found: list[tuple[Path, dict[str, Any]]] = []
    folder = Path(folder).resolve()
    stop = Path(root).resolve() if root else folder
    current = folder
    while True:
        cfg_path = current / CONFIG_NAME
        if cfg_path.is_file():
            data = load_json(cfg_path, None)
            if isinstance(data, dict):
                found.append((cfg_path, data))
                if data.get("inherit_parent") is False:
                    break
            else:
                log.warning("Ignoring invalid %s", cfg_path)
        if not inherit or current == stop or current.parent == current:
            break
        try:
            current.relative_to(stop)
        except ValueError:
            break
        current = current.parent
    return found


def merged_config(folder: Path, root: Path | None, inherit: bool = True) -> tuple[dict[str, Any], list[Path]]:
    configs = find_configs(folder, root, inherit)
    merged: dict[str, Any] = {}
    for _, data in reversed(configs):  # farthest first, nearest overrides
        for k, v in data.items():
            if isinstance(v, dict) and isinstance(merged.get(k), dict):
                merged[k] = {**merged[k], **v}
            else:
                merged[k] = v
    return merged, [p for p, _ in configs]


def apply_folder_config(
    base: GenerationProfile,
    config: dict[str, Any],
    store: ProfileStore | None = None,
) -> GenerationProfile:
    """Return a copy of the effective profile for a file."""
    if not config:
        return base
    profile = base
    if store is not None and config.get("profile"):
        named = store.get(str(config["profile"]))
        if named is not None:
            profile = named
        else:
            log.warning("tts_config.json references unknown profile '%s'", config["profile"])
    p = profile.clone()
    if "engine" in config:
        p.engine = str(config["engine"])
    if "mode" in config:
        p.mode = str(config["mode"])
    if "voice" in config:
        p.voice = VoiceSelection.from_any(config["voice"])
    if isinstance(config.get("speaker_voices"), dict):
        for spk, v in config["speaker_voices"].items():
            p.speaker_voices[str(spk).upper()] = VoiceSelection.from_any(v)
    for key in ("speed", "language", "instruct", "seed"):
        if key in config:
            p.params[key] = config[key]
    if isinstance(config.get("params"), dict):
        p.params.update(config["params"])
    if isinstance(config.get("silence"), dict):
        merged = {**p.silence.to_dict(), **config["silence"]}
        p.silence = SilenceSettings.from_dict(merged)
    if config.get("output_format"):
        p.output_format = str(config["output_format"])
    return p
