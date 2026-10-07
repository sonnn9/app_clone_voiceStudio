"""Generation profiles (presets) persisted to ``profiles.json``."""
from __future__ import annotations

import copy
import logging
from dataclasses import dataclass, field
from typing import Any

from app.api.models import VoiceSelection
from app.core.pronunciation import PronunciationRule
from app.utils.paths import profiles_file, resource_dir
from app.utils.text_io import load_json, save_json

log = logging.getLogger("core.profiles")


@dataclass
class SilenceSettings:
    turn_ms: int = 300          # between dialogue turns
    paragraph_ms: int = 600     # between paragraphs
    narrator_ms: int = 600      # before a narrator section (conversation mode)
    sentence_ms: int = 0        # between sentences (story mode; 0 = natural)

    @classmethod
    def from_dict(cls, d: dict[str, Any] | None) -> "SilenceSettings":
        d = d or {}
        return cls(
            turn_ms=int(d.get("turn_ms", 300)),
            paragraph_ms=int(d.get("paragraph_ms", 600)),
            narrator_ms=int(d.get("narrator_ms", 600)),
            sentence_ms=int(d.get("sentence_ms", 0)),
        )

    def to_dict(self) -> dict[str, int]:
        return {"turn_ms": self.turn_ms, "paragraph_ms": self.paragraph_ms,
                "narrator_ms": self.narrator_ms, "sentence_ms": self.sentence_ms}


NARRATOR_NAMES = {"NARRATOR", "NARRATION", "NGƯỜI DẪN CHUYỆN", "DẪN CHUYỆN", "NGƯỜI KỂ"}


@dataclass
class GenerationProfile:
    name: str
    engine: str = "omnivoice"
    mode: str = "auto"
    voice: VoiceSelection = field(default_factory=VoiceSelection)
    speaker_voices: dict[str, VoiceSelection] = field(default_factory=dict)
    # Only parameters advertised by the backend for `engine` are sent.
    params: dict[str, Any] = field(default_factory=lambda: {"speed": 1.0})
    silence: SilenceSettings = field(default_factory=SilenceSettings)
    pronunciation: list[PronunciationRule] = field(default_factory=list)
    output_format: str = ""  # "" = use global setting
    description: str = ""

    def voice_for(self, speaker: str | None) -> VoiceSelection:
        if speaker:
            v = self.speaker_voices.get(speaker.upper())
            if v is not None and v.key:
                return v
        return self.voice

    def voices_summary(self, speakers: list[str] | None = None) -> str:
        if not speakers:
            return self.voice.name
        return ", ".join(f"{s}→{self.voice_for(s).name}" for s in speakers)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "engine": self.engine,
            "mode": self.mode,
            "voice": self.voice.to_dict(),
            "speaker_voices": {k: v.to_dict() for k, v in self.speaker_voices.items()},
            "params": dict(self.params),
            "silence": self.silence.to_dict(),
            "pronunciation": [r.to_dict() for r in self.pronunciation],
            "output_format": self.output_format,
            "description": self.description,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "GenerationProfile":
        return cls(
            name=str(d.get("name") or "Unnamed"),
            engine=str(d.get("engine") or "omnivoice"),
            mode=str(d.get("mode") or "auto"),
            voice=VoiceSelection.from_any(d.get("voice")),
            speaker_voices={str(k).upper(): VoiceSelection.from_any(v)
                            for k, v in (d.get("speaker_voices") or {}).items()},
            params=dict(d.get("params") or {"speed": 1.0}),
            silence=SilenceSettings.from_dict(d.get("silence")),
            pronunciation=[PronunciationRule.from_dict(r) for r in d.get("pronunciation") or []],
            output_format=str(d.get("output_format") or ""),
            description=str(d.get("description") or ""),
        )

    def clone(self, new_name: str | None = None) -> "GenerationProfile":
        p = GenerationProfile.from_dict(copy.deepcopy(self.to_dict()))
        if new_name:
            p.name = new_name
        return p


class ProfileStore:
    def __init__(self) -> None:
        self.profiles: list[GenerationProfile] = []
        self.load()

    def load(self) -> None:
        data = load_json(profiles_file(), None)
        if data is None:
            data = load_json(resource_dir() / "default_profiles.json", [])
        self.profiles = [GenerationProfile.from_dict(d) for d in data if isinstance(d, dict)]
        if not self.profiles:
            self.profiles = [GenerationProfile(name="Default")]

    def save(self) -> None:
        try:
            save_json(profiles_file(), [p.to_dict() for p in self.profiles])
        except OSError as e:
            log.error("Could not save profiles: %s", e)

    def names(self) -> list[str]:
        return [p.name for p in self.profiles]

    def get(self, name: str | None) -> GenerationProfile | None:
        return next((p for p in self.profiles if p.name == name), None)

    def get_or_first(self, name: str | None) -> GenerationProfile:
        return self.get(name) or self.profiles[0]

    def unique_name(self, base: str) -> str:
        names = set(self.names())
        if base not in names:
            return base
        i = 2
        while f"{base} ({i})" in names:
            i += 1
        return f"{base} ({i})"

    def upsert(self, profile: GenerationProfile, old_name: str | None = None) -> None:
        key = old_name or profile.name
        for i, p in enumerate(self.profiles):
            if p.name == key:
                self.profiles[i] = profile
                self.save()
                return
        self.profiles.append(profile)
        self.save()

    def delete(self, name: str) -> None:
        self.profiles = [p for p in self.profiles if p.name != name]
        if not self.profiles:
            self.profiles = [GenerationProfile(name="Default")]
        self.save()

    def duplicate(self, name: str) -> GenerationProfile | None:
        src = self.get(name)
        if src is None:
            return None
        copy_ = src.clone(self.unique_name(f"{src.name} copy"))
        self.profiles.append(copy_)
        self.save()
        return copy_
