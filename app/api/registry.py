"""TTS engine registry – the single place where adapters are listed.

To add a new local engine later (Kokoro, XTTS, F5-TTS …), implement
:class:`~app.api.base_tts_adapter.BaseTTSAdapter` and add it here.
"""
from __future__ import annotations

from typing import Callable

from app.api.audiostudio_adapter import AudioStudioAdapter
from app.api.base_tts_adapter import BaseTTSAdapter

ADAPTERS: dict[str, Callable[[], BaseTTSAdapter]] = {
    "audiostudio": AudioStudioAdapter,
}


def create_adapter(engine_family: str = "audiostudio") -> BaseTTSAdapter:
    factory = ADAPTERS.get(engine_family) or ADAPTERS["audiostudio"]
    return factory()
