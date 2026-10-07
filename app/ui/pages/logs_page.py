"""Logs page: view recent log lines and open the logs folder."""
from __future__ import annotations

import os

from PySide6.QtGui import QFont
from PySide6.QtWidgets import QComboBox, QHBoxLayout, QPlainTextEdit, QPushButton, QVBoxLayout, QWidget

from app.ui.context import AppContext
from app.ui.widgets import page_header
from app.utils.paths import logs_dir


def open_path(path) -> None:
    if os.name == "nt":
        os.startfile(str(path))  # type: ignore[attr-defined]
    else:
        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QDesktopServices

        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))


class LogsPage(QWidget):
    def __init__(self, ctx: AppContext, parent=None) -> None:
        super().__init__(parent)
        self.ctx = ctx
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 16)
        root.addWidget(page_header("Logs", f"Stored in {logs_dir()}"))
        row = QHBoxLayout()
        self.file = QComboBox()
        self.file.setMinimumWidth(260)
        refresh = QPushButton("↻ Refresh")
        open_btn = QPushButton("Open Logs Folder")
        row.addWidget(self.file)
        row.addWidget(refresh)
        row.addStretch(1)
        row.addWidget(open_btn)
        root.addLayout(row)
        self.view = QPlainTextEdit()
        self.view.setReadOnly(True)
        self.view.setFont(QFont("Consolas", 9))
        self.view.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        root.addWidget(self.view, 1)
        refresh.clicked.connect(self.refresh)
        open_btn.clicked.connect(lambda: open_path(logs_dir()))
        self.file.currentIndexChanged.connect(lambda _i: self._load())

    def refresh(self) -> None:
        cur = self.file.currentText()
        files = sorted((p.name for p in logs_dir().glob("*.log")), reverse=True)
        files.sort(key=lambda n: n != "app.log")
        self.file.blockSignals(True)
        self.file.clear()
        self.file.addItems(files)
        self.file.setCurrentIndex(max(0, self.file.findText(cur)))
        self.file.blockSignals(False)
        self._load()

    def _load(self) -> None:
        name = self.file.currentText()
        if not name:
            self.view.setPlainText("")
            return
        path = logs_dir() / name
        try:
            with open(path, "rb") as fh:
                fh.seek(0, 2)
                size = fh.tell()
                fh.seek(max(0, size - 400_000))
                text = fh.read().decode("utf-8", "replace")
        except OSError as e:
            text = str(e)
        self.view.setPlainText(text)
        self.view.verticalScrollBar().setValue(self.view.verticalScrollBar().maximum())

    def showEvent(self, event) -> None:
        self.refresh()
        super().showEvent(event)
