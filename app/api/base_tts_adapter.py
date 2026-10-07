"""Engine-independent TTS adapter interface.

The batch engine, UI and profiles only talk to :class:`BaseTTSAdapter`.
Adding another local engine (Kokoro, XTTS, F5-TTS …) means writing one new
subclass and registering it in :mod:`app.api.registry`.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from app.api.models import EngineCapabilities, EngineInfo, HealthInfo, VoiceInfo, VoiceSelection


class BaseTTSAdapter(ABC):
    #: Human readable backend family name shown in the "TTS Engine" selector.
    display_name: str = "TTS"

    @abstractmethod
    def configure(self, base_url: str, timeout_s: float) -> None:
        """Apply connection settings (may be called repeatedly)."""

    @abstractmethod
    def connect(self) -> HealthInfo:
        """Quick reachability check."""

    @abstractmethod
    def health_check(self) -> HealthInfo:
        """Detailed status: version, device/GPU, loaded model …"""

    @abstractmethod
    def get_models(self) -> list[EngineInfo]:
        """Engines/models the backend can synthesise with."""

    @abstractmethod
    def get_voices(self, model: str | None = None, refresh: bool = False) -> list[VoiceInfo]:
        """All voices usable with *model* (dynamic, never hard-coded)."""

    @abstractmethod
    def get_capabilities(self, model: str, offline: bool = False) -> EngineCapabilities:
        """Parameters and limits supported by *model*.

        With ``offline=True`` no network request may be made (use cached data).
        """

    @abstractmethod
    def generate(
        self,
        text: str,
        voice: VoiceSelection,
        model: str,
        parameters: dict[str, Any],
        response_format: str = "wav",
    ) -> bytes:
        """Synthesise *text* and return encoded audio bytes."""

    @abstractmethod
    def cancel(self) -> None:
        """Abort in-flight requests (best effort)."""

    def reset_cancel(self) -> None:
        """Allow new requests after :meth:`cancel`."""

    def default_language_suggestions(self) -> list[str]:
        return []
