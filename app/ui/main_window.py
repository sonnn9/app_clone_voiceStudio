"""Main window: sidebar navigation, pages, drag & drop, session restore."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QByteArray, Qt
from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QMainWindow,
    QMessageBox,
    QStackedWidget,
    QStatusBar,
    QVBoxLayout,
    QWidget,
)

from app.api.models import HealthInfo
from app.core.session import has_unfinished, load_session
from app.ui import theme
from app.ui.context import AppContext
from app.ui.pages.batch_page import BatchPage
from app.ui.pages.dashboard_page import DashboardPage
from app.ui.pages.generate_page import GeneratePage
from app.ui.pages.logs_page import LogsPage
from app.ui.pages.profiles_page import ProfilesPage
from app.ui.pages.pronunciation_page import PronunciationPage
from app.ui.pages.settings_page import SettingsPage
from app.ui.pages.voices_page import VoicesPage
from app.ui.widgets import StatusDot
from app.version import APP_NAME, APP_VERSION

PAGES = ["Dashboard", "Generate", "Batch Folder", "Profiles", "Voices", "Pronunciation", "Settings", "Logs"]


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.ctx = AppContext()
        theme.apply_theme(QApplication.instance(), self.ctx.settings.theme)
        self.setWindowTitle(APP_NAME)
        self.setAcceptDrops(True)
        self.resize(1280, 820)
        self.setMinimumSize(980, 640)

        central = QWidget()
        h = QHBoxLayout(central)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(0)

        sidebar = QWidget()
        sidebar.setObjectName("Sidebar")
        sidebar.setFixedWidth(210)
        sl = QVBoxLayout(sidebar)
        sl.setContentsMargins(0, 0, 0, 8)
        t = QLabel("AudioStudio")
        t.setObjectName("AppTitle")
        sub = QLabel(f"Batch TTS · v{APP_VERSION}")
        sub.setObjectName("AppSubtitle")
        sl.addWidget(t)
        sl.addWidget(sub)
        self.nav = QListWidget()
        self.nav.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        for name in PAGES:
            self.nav.addItem(name)
        sl.addWidget(self.nav, 1)
        conn = QHBoxLayout()
        conn.setContentsMargins(16, 0, 16, 4)
        self.side_dot = StatusDot()
        self.side_state = QLabel("Not connected")
        self.side_state.setObjectName("Muted")
        conn.addWidget(self.side_dot)
        conn.addWidget(self.side_state, 1)
        sl.addLayout(conn)
        h.addWidget(sidebar)

        self.stack = QStackedWidget()
        self.dashboard = DashboardPage(self.ctx)
        self.generate = GeneratePage(self.ctx)
        self.batch_page = BatchPage(self.ctx)
        self.profiles = ProfilesPage(self.ctx)
        self.voices = VoicesPage(self.ctx)
        self.pronunciation = PronunciationPage(self.ctx)
        self.settings_page = SettingsPage(self.ctx)
        self.logs = LogsPage(self.ctx)
        for w in (self.dashboard, self.generate, self.batch_page, self.profiles, self.voices,
                  self.pronunciation, self.settings_page, self.logs):
            self.stack.addWidget(w)
        h.addWidget(self.stack, 1)
        self.setCentralWidget(central)
        self.setStatusBar(QStatusBar())

        self.nav.currentRowChanged.connect(self.stack.setCurrentIndex)
        self.dashboard.select_folder.connect(lambda: (self.go("Batch Folder"), self.batch_page.choose_folder()))
        self.dashboard.select_file.connect(lambda: (self.go("Batch Folder"), self.batch_page.choose_files()))
        self.dashboard.open_settings.connect(lambda: self.go("Settings"))
        self.ctx.connection_changed.connect(self._connection)
        self.ctx.batch.running_changed.connect(
            lambda r: self.statusBar().showMessage("Batch running…" if r else "Batch idle", 4000))
        self.nav.setCurrentRow(0)

        geo = self.ctx.settings.window_geometry
        if geo:
            self.restoreGeometry(QByteArray.fromBase64(geo.encode()))

    def go(self, page: str) -> None:
        self.nav.setCurrentRow(PAGES.index(page))

    def after_show(self) -> None:
        """Startup actions once the window is visible."""
        if not self.ctx.settings.api_base_url:
            self.go("Settings")
            QMessageBox.information(
                self, APP_NAME,
                "Welcome! Enter the address of your local AudioStudio server (e.g. http://127.0.0.1:<port>) "
                "or press Detect, then Test Connection.")
        else:
            self.ctx.refresh_connection(full=True)
        self._offer_resume()

    def _offer_resume(self) -> None:
        jobs, meta = load_session()
        if not jobs or not has_unfinished(jobs):
            return
        done = sum(1 for j in jobs if j.status in ("Completed", "Skipped"))
        answer = QMessageBox.question(
            self, "Resume batch",
            f"An unfinished batch from {meta.get('saved_at', 'a previous session')} was found "
            f"({done} of {len(jobs)} files done).\n\nRestore it? Completed files will not be regenerated.")
        if answer != QMessageBox.StandardButton.Yes:
            return
        self.ctx.batch.jobs = jobs
        self.batch_page.model.reset()
        self.ctx.batch.mark_dirty()
        self.go("Batch Folder")

    def _connection(self, h: HealthInfo) -> None:
        self.side_dot.set_state("ok" if h.connected else "danger")
        self.side_state.setText("Connected" if h.connected else "Not connected")
        self.side_state.setToolTip(h.message)

    # ---------------------------------------------------------- drag & drop
    def dragEnterEvent(self, event) -> None:
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event) -> None:
        paths = [Path(u.toLocalFile()) for u in event.mimeData().urls() if u.isLocalFile()]
        paths = [p for p in paths if p.is_dir() or p.suffix.lower() == ".txt"]
        if not paths:
            return
        if self.stack.currentWidget() is self.generate and len(paths) == 1 and paths[0].is_file():
            self.generate.open_file(paths[0])
            return
        if self.ctx.batch.is_running:
            QMessageBox.information(self, APP_NAME, "Wait for the running batch to finish before adding files.")
            return
        self.go("Batch Folder")
        self.batch_page.add_paths(paths)

    # ---------------------------------------------------------------- close
    def closeEvent(self, event) -> None:
        if self.ctx.batch.is_running:
            answer = QMessageBox.question(
                self, APP_NAME, "A batch is running. Stop it and quit? You can resume it next time.")
            if answer != QMessageBox.StandardButton.Yes:
                event.ignore()
                return
            self.ctx.batch.cancel()
        self.ctx.batch.save_now()
        self.ctx.settings.window_geometry = bytes(self.saveGeometry().toBase64()).decode()
        self.ctx.save_settings()
        self.voices.player.release()
        self.generate.player.release()
        super().closeEvent(event)
