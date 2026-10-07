"""Dashboard: connection status and quick start."""
from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QComboBox, QFormLayout, QGridLayout, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from app.api.models import HealthInfo
from app.ui.context import AppContext
from app.ui.pages.batch_page import MODES
from app.ui.pages.logs_page import open_path
from app.ui.widgets import Card, StatusDot, muted, page_header, primary
from app.utils.paths import app_data_dir, logs_dir


class DashboardPage(QWidget):
    select_folder = Signal()
    select_file = Signal()
    open_settings = Signal()

    def __init__(self, ctx: AppContext, parent=None) -> None:
        super().__init__(parent)
        self.ctx = ctx
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 16)
        root.setSpacing(12)
        root.addWidget(page_header("Dashboard", "Start AudioStudio, choose a profile, select a folder, press Start."))

        top = QHBoxLayout()
        # ---- server card
        server = Card()
        h = QHBoxLayout()
        self.dot = StatusDot()
        title = QLabel("<b>AudioStudio</b>")
        self.state = QLabel("Checking…")
        h.addWidget(self.dot)
        h.addWidget(title)
        h.addStretch(1)
        h.addWidget(self.state)
        server.lay.addLayout(h)
        self.details = muted("")
        server.lay.addWidget(self.details)
        btns = QHBoxLayout()
        self.reconnect = QPushButton("Reconnect")
        settings = QPushButton("Settings…")
        btns.addWidget(self.reconnect)
        btns.addWidget(settings)
        btns.addStretch(1)
        server.lay.addLayout(btns)
        top.addWidget(server, 1)

        # ---- quick start card
        quick = Card()
        quick.lay.addWidget(QLabel("<b>Quick start</b>"))
        form = QFormLayout()
        self.profile = QComboBox()
        self.model = QComboBox()
        self.model.setToolTip("Engine used by the selected profile")
        self.mode = QComboBox()
        for label, value in MODES:
            self.mode.addItem(label, value)
        form.addRow("Profile", self.profile)
        form.addRow("Model", self.model)
        form.addRow("Mode", self.mode)
        quick.lay.addLayout(form)
        qb = QHBoxLayout()
        self.file_btn = QPushButton("Select File…")
        self.folder_btn = primary("Select Folder…")
        qb.addStretch(1)
        qb.addWidget(self.file_btn)
        qb.addWidget(self.folder_btn)
        quick.lay.addLayout(qb)
        top.addWidget(quick, 1)
        root.addLayout(top)

        # ---- stats
        stats = Card()
        stats.lay.addWidget(QLabel("<b>Current queue</b>"))
        grid = QGridLayout()
        self.stat_labels: dict[str, QLabel] = {}
        for i, (key, label) in enumerate((("total", "Files"), ("completed", "Completed"), ("failed", "Failed"),
                                          ("skipped", "Skipped"), ("remaining", "Remaining"))):
            v = QLabel("0")
            v.setObjectName("StatValue")
            grid.addWidget(v, 0, i)
            grid.addWidget(muted(label), 1, i)
            self.stat_labels[key] = v
        stats.lay.addLayout(grid)
        root.addWidget(stats)

        links = QHBoxLayout()
        logs = QPushButton("Open Logs Folder")
        data = QPushButton("Open App Data Folder")
        links.addWidget(logs)
        links.addWidget(data)
        links.addStretch(1)
        root.addLayout(links)
        root.addStretch(1)

        self.reconnect.clicked.connect(lambda: ctx.refresh_connection(full=True))
        settings.clicked.connect(self.open_settings.emit)
        self.folder_btn.clicked.connect(self.select_folder.emit)
        self.file_btn.clicked.connect(self.select_file.emit)
        logs.clicked.connect(lambda: open_path(logs_dir()))
        data.clicked.connect(lambda: open_path(app_data_dir()))
        self.profile.currentTextChanged.connect(self._profile_changed)
        self.model.activated.connect(self._model_changed)
        self.mode.currentIndexChanged.connect(self._mode_changed)
        ctx.connection_changed.connect(self.show_health)
        ctx.engines_changed.connect(lambda _e: self._fill_models())
        ctx.profiles_changed.connect(self._fill_profiles)
        ctx.settings_changed.connect(self._sync_from_settings)
        ctx.batch.stats_changed.connect(self._stats)
        self._fill_profiles()
        self._fill_models()
        self._sync_from_settings()

    def show_health(self, h: HealthInfo) -> None:
        if h.connected:
            self.dot.set_state("ok")
            self.state.setText("<b>● Connected</b>")
            parts = [f"Version {h.version}", h.device]
            if h.gpu_name:
                parts.append(f"{h.gpu_name}, {h.vram_gb:.0f} GB VRAM")
            if h.active_engine:
                parts.append(f"active engine: {h.active_engine}")
            if h.model_status:
                parts.append(f"model: {h.model_status}")
            self.details.setText(" · ".join(p for p in parts if p))
        else:
            self.dot.set_state("danger")
            self.state.setText("<b>Not connected</b>")
            self.details.setText(h.message or "Start AudioStudio and check Settings → API Base URL.")

    def _fill_profiles(self) -> None:
        self.profile.blockSignals(True)
        self.profile.clear()
        self.profile.addItems(self.ctx.profiles.names())
        self.profile.setCurrentIndex(max(0, self.profile.findText(self.ctx.settings.last_profile)))
        self.profile.blockSignals(False)
        self._fill_models()

    def _fill_models(self) -> None:
        p = self.ctx.profiles.get(self.profile.currentText())
        self.model.clear()
        for e in self.ctx.available_engines():
            self.model.addItem(f"{e.label} [{e.id}]", e.id)
        if p is not None:
            idx = self.model.findData(p.engine)
            if idx < 0:
                self.model.addItem(p.engine, p.engine)
                idx = self.model.count() - 1
            self.model.setCurrentIndex(idx)

    def _sync_from_settings(self) -> None:
        s = self.ctx.settings
        if self.profile.currentText() != s.last_profile and self.profile.findText(s.last_profile) >= 0:
            self.profile.blockSignals(True)
            self.profile.setCurrentText(s.last_profile)
            self.profile.blockSignals(False)
            self._fill_models()
        self.mode.blockSignals(True)
        self.mode.setCurrentIndex(max(0, self.mode.findData(s.last_mode)))
        self.mode.blockSignals(False)

    def _profile_changed(self, name: str) -> None:
        self.ctx.settings.last_profile = name
        self._fill_models()
        self.ctx.save_settings()

    def _model_changed(self) -> None:
        p = self.ctx.profiles.get(self.profile.currentText())
        engine = self.model.currentData()
        if p is not None and engine and engine != p.engine:
            p.engine = engine
            self.ctx.profiles.upsert(p)
            self.ctx.profiles_changed.emit()

    def _mode_changed(self) -> None:
        self.ctx.settings.last_mode = self.mode.currentData()
        self.ctx.save_settings()

    def _stats(self, st: dict) -> None:
        for k, lbl in self.stat_labels.items():
            lbl.setText(str(st.get(k, 0)))
