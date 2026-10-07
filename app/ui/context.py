"""Shared application state for all pages."""
from __future__ import annotations

import logging

from PySide6.QtCore import QObject, QTimer, Signal

from app.api.models import EngineCapabilities, EngineInfo, HealthInfo, VoiceInfo
from app.api.registry import create_adapter
from app.audio.ffmpeg import find_ffmpeg
from app.core.batch_manager import BatchManager
from app.core.profiles import ProfileStore
from app.core.pronunciation import PronunciationStore
from app.core.settings import AppSettings, load_settings, save_settings
from app.ui.workers import run_async

log = logging.getLogger("ui.context")


class AppContext(QObject):
    connection_changed = Signal(object)      # HealthInfo
    engines_changed = Signal(list)           # list[EngineInfo]
    voices_changed = Signal(str)             # engine id
    profiles_changed = Signal()
    settings_changed = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.settings: AppSettings = load_settings()
        self.profiles = ProfileStore()
        self.pronunciation = PronunciationStore()
        self.adapter = create_adapter(self.settings.engine_family)
        self.adapter.configure(self.settings.api_base_url, self.settings.timeout_s)
        self.batch = BatchManager(self.adapter, self.settings, self.profiles, self.pronunciation, self)
        self.health: HealthInfo | None = None
        self.engines: list[EngineInfo] = []
        self.voices: dict[str, list[VoiceInfo]] = {}
        self._voices_loading: set[str] = set()
        self._checking = False

        # Keep the connection indicator fresh.
        self._poll = QTimer(self)
        self._poll.setInterval(30_000)
        self._poll.timeout.connect(self.refresh_connection)
        self._poll.start()

    # ------------------------------------------------------------- settings
    def save_settings(self) -> None:
        save_settings(self.settings)
        self.settings_changed.emit()

    def apply_connection_settings(self) -> None:
        self.adapter.configure(self.settings.api_base_url, self.settings.timeout_s)
        self.voices.clear()
        self.engines = []
        self.save_settings()
        self.refresh_connection(full=True)

    @property
    def connected(self) -> bool:
        return bool(self.health and self.health.connected)

    def ffmpeg(self) -> str | None:
        return find_ffmpeg(self.settings.ffmpeg_path)

    # ----------------------------------------------------------- connection
    def refresh_connection(self, full: bool = False) -> None:
        if self._checking or not self.settings.api_base_url:
            if not self.settings.api_base_url:
                self.health = HealthInfo(connected=False, message="API URL not configured")
                self.connection_changed.emit(self.health)
            return
        self._checking = True
        need_engines = full or not self.engines

        def work():
            health = self.adapter.health_check() if full or not self.connected else self.adapter.connect()
            if self.connected and not full and health.connected and self.health:
                # keep details from the last full check
                health.gpu_name = health.gpu_name or self.health.gpu_name
                health.vram_gb = health.vram_gb or self.health.vram_gb
                health.model_status = health.model_status or self.health.model_status
                health.active_engine = health.active_engine or self.health.active_engine
                health.active_model = health.active_model or self.health.active_model
                health.details = health.details or self.health.details
            engines = None
            if health.connected and need_engines:
                engines = self.adapter.get_models()
                self.adapter.get_capabilities("omnivoice")  # prefetch the request schema
            return health, engines

        def done(result):
            self._checking = False
            health, engines = result
            was = self.connected
            self.health = health
            self.connection_changed.emit(health)
            if engines is not None:
                self.engines = engines
                self.engines_changed.emit(engines)
            if health.connected and not was:
                log.info("Connected to AudioStudio %s at %s", health.version, self.settings.api_base_url)

        def failed(exc):
            self._checking = False
            self.health = HealthInfo(connected=False, message=str(exc))
            self.connection_changed.emit(self.health)

        run_async(work, done, failed)

    # --------------------------------------------------------------- engines
    def available_engines(self) -> list[EngineInfo]:
        return [e for e in self.engines if e.available]

    def engine(self, engine_id: str) -> EngineInfo | None:
        return next((e for e in self.engines if e.id == engine_id), None)

    def capabilities(self, engine_id: str) -> EngineCapabilities:
        return self.adapter.get_capabilities(engine_id, offline=True)

    # ---------------------------------------------------------------- voices
    def voices_for(self, engine_id: str) -> list[VoiceInfo]:
        return self.voices.get(engine_id, [])

    def load_voices(self, engine_id: str, refresh: bool = False) -> None:
        if not self.connected or engine_id in self._voices_loading:
            return
        if engine_id in self.voices and not refresh:
            self.voices_changed.emit(engine_id)
            return
        self._voices_loading.add(engine_id)

        def done(voices):
            self._voices_loading.discard(engine_id)
            self.voices[engine_id] = voices
            self.voices_changed.emit(engine_id)

        def failed(exc):
            self._voices_loading.discard(engine_id)
            log.warning("Loading voices failed: %s", exc)

        run_async(lambda: self.adapter.get_voices(engine_id, refresh=refresh), done, failed)

    def voice_display(self, key: str, engine_id: str) -> str:
        v = next((v for v in self.voices_for(engine_id) if v.key == key), None)
        return v.name if v else key
