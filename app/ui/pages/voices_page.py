"""Voices page: every voice the local AudioStudio offers, with filters and preview."""
from __future__ import annotations

import time

from PySide6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from app.api.errors import TTSError
from app.api.models import VoiceInfo
from app.ui.context import AppContext
from app.ui.widgets import PlayerBar, VoiceBrowser, muted, page_header, primary
from app.ui.workers import run_async
from app.utils.paths import preview_dir


def clean_preview_dir(keep: int = 0) -> None:
    files = sorted(preview_dir().glob("*.wav"), key=lambda p: p.stat().st_mtime, reverse=True)
    for f in files[keep:]:
        try:
            f.unlink()
        except OSError:
            pass  # still open in the player – removed next time


class VoicesPage(QWidget):
    def __init__(self, ctx: AppContext, parent=None) -> None:
        super().__init__(parent)
        self.ctx = ctx
        self._busy = False
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 16)
        root.addWidget(page_header("Voices", "All voices loaded live from your local AudioStudio installation."))

        top = QHBoxLayout()
        top.addWidget(QLabel("Engine"))
        self.engine = QComboBox()
        self.engine.setMinimumWidth(320)
        top.addWidget(self.engine)
        self.refresh_btn = QPushButton("↻ Refresh voices")
        top.addWidget(self.refresh_btn)
        top.addStretch(1)
        self.status = muted("")
        top.addWidget(self.status)
        root.addLayout(top)

        split = QSplitter()
        self.browser = VoiceBrowser()
        split.addWidget(self.browser)

        side = QWidget()
        sl = QVBoxLayout(side)
        sl.setContentsMargins(8, 0, 0, 0)
        info = QGroupBox("Selected voice")
        self.info_form = QFormLayout(info)
        self.labels: dict[str, QLabel] = {}
        for key in ("Name", "Voice ID", "Gender", "Language", "Accent", "Age", "Pitch", "Category", "Type",
                    "Voice design"):
            lbl = QLabel("–")
            lbl.setWordWrap(True)
            self.labels[key] = lbl
            self.info_form.addRow(key, lbl)
        sl.addWidget(info)

        prev = QGroupBox("Preview")
        pl = QVBoxLayout(prev)
        self.text = QLineEdit("Hello. This is a voice preview.")
        pl.addWidget(self.text)
        row = QHBoxLayout()
        self.preview_btn = primary("Preview Voice")
        row.addWidget(self.preview_btn)
        row.addStretch(1)
        pl.addLayout(row)
        self.player = PlayerBar()
        pl.addWidget(self.player)
        self.preview_status = muted("")
        pl.addWidget(self.preview_status)
        sl.addWidget(prev)

        self.save_btn = QPushButton("Save designed voice as AudioStudio profile…")
        self.save_btn.setToolTip("Renders a reference sample on the server so the voice keeps an identical "
                                 "identity everywhere (POST /archetypes/{id}/use).")
        sl.addWidget(self.save_btn)
        sl.addStretch(1)
        split.addWidget(side)
        split.setSizes([760, 360])
        root.addWidget(split, 1)

        self.engine.currentIndexChanged.connect(self._engine_changed)
        self.refresh_btn.clicked.connect(lambda: self.ctx.load_voices(self._engine_id(), refresh=True))
        self.browser.selection_changed.connect(self._show)
        self.browser.activated.connect(lambda _v: self.preview())
        self.preview_btn.clicked.connect(self.preview)
        self.save_btn.clicked.connect(self._save_archetype)
        ctx.engines_changed.connect(lambda _e: self._fill_engines())
        ctx.voices_changed.connect(self._voices_loaded)
        ctx.connection_changed.connect(lambda _h: self._update_status())
        self._fill_engines()
        self._show(None)
        clean_preview_dir()

    def _engine_id(self) -> str:
        return self.engine.currentData() or "omnivoice"

    def _fill_engines(self) -> None:
        cur = self.engine.currentData() or self.ctx.settings.last_engine
        self.engine.blockSignals(True)
        self.engine.clear()
        for e in self.ctx.available_engines():
            self.engine.addItem(f"{e.label}  [{e.id}]" + ("  ✓ active" if e.is_active else ""), e.id)
        idx = self.engine.findData(cur)
        if idx < 0 and self.ctx.health:
            idx = self.engine.findData(self.ctx.health.active_engine)
        self.engine.setCurrentIndex(max(0, idx))
        self.engine.blockSignals(False)
        self._engine_changed()

    def _engine_changed(self) -> None:
        if self.engine.count():
            self.ctx.settings.last_engine = self._engine_id()
            self.browser.set_voices(self.ctx.voices_for(self._engine_id()))
            self.ctx.load_voices(self._engine_id())
        self._update_status()

    def _voices_loaded(self, engine: str) -> None:
        if engine == self._engine_id():
            self.browser.set_voices(self.ctx.voices_for(engine))
        self._update_status()

    def _update_status(self) -> None:
        if not self.ctx.connected:
            self.status.setText("Not connected – configure the API URL in Settings.")
        else:
            n = len(self.ctx.voices_for(self._engine_id()))
            self.status.setText(f"{n} voices" if n else "Loading voices…")

    def _show(self, v: VoiceInfo | None) -> None:
        if v is None:
            for lbl in self.labels.values():
                lbl.setText("–")
            self.save_btn.setEnabled(False)
            return
        source = {"profile": "Saved voice profile", "archetype": "Designed voice (archetype)",
                  "default": "Engine default"}.get(v.source, v.source)
        vals = {"Name": v.name, "Voice ID": v.voice_id or v.key, "Gender": v.gender, "Language": v.language,
                "Accent": v.accent, "Age": v.age, "Pitch": v.pitch, "Category": v.style.capitalize(),
                "Type": source + (f" ({v.kind})" if v.kind and v.source == "profile" else ""),
                "Voice design": v.instruct}
        for k, val in vals.items():
            self.labels[k].setText(val or "–")
        self.save_btn.setEnabled(v.source == "archetype" and self.ctx.connected)

    def preview(self) -> None:
        v = self.browser.current()
        if v is None or self._busy:
            return
        if not self.ctx.connected:
            QMessageBox.warning(self, "Preview", "Not connected to AudioStudio.")
            return
        text = self.text.text().strip() or "Hello. This is a voice preview."
        engine = self._engine_id()
        caps = self.ctx.capabilities(engine)
        params = {"speed": 1.0} if caps.supports("speed") else {}
        self._busy = True
        self.preview_btn.setEnabled(False)
        self.preview_status.setText(f"Generating preview with “{v.name}”… (the first request may load the model)")
        self.player.release()
        clean_preview_dir()
        self.ctx.adapter.reset_cancel()
        started = time.monotonic()

        def work():
            data = self.ctx.adapter.generate(text, v.selection(), engine, params, "wav")
            path = preview_dir() / f"preview_{int(time.time() * 1000)}.wav"
            path.write_bytes(data)
            return path

        def done(path):
            self._busy = False
            self.preview_btn.setEnabled(True)
            self.preview_status.setText(f"Generated in {time.monotonic() - started:.1f}s")
            self.player.load(path)

        def failed(exc):
            self._busy = False
            self.preview_btn.setEnabled(True)
            msg = exc.human() + "\n\n" + exc.hint if isinstance(exc, TTSError) else str(exc)
            self.preview_status.setText("Preview failed")
            QMessageBox.warning(self, "Preview failed", msg)

        run_async(work, done, failed)

    def _save_archetype(self) -> None:
        v = self.browser.current()
        if v is None or v.source != "archetype":
            return
        name, ok = QInputDialog.getText(self, "Save as profile", "Profile name in AudioStudio:", text=v.name)
        if not ok:
            return
        self.save_btn.setEnabled(False)
        adapter = self.ctx.adapter

        def work():
            return adapter.save_archetype_as_profile(v.voice_id, name.strip() or None)  # type: ignore[attr-defined]

        def done(_res):
            self.save_btn.setEnabled(True)
            QMessageBox.information(self, "Saved", f"“{name}” is now available under My profiles.")
            self.ctx.load_voices(self._engine_id(), refresh=True)

        def failed(exc):
            self.save_btn.setEnabled(True)
            QMessageBox.warning(self, "Save failed", str(exc))

        run_async(work, done, failed)
