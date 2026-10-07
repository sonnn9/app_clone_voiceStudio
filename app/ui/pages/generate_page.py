"""Generate page: one script (pasted text or a single TXT) → one audio file."""
from __future__ import annotations

import time
from pathlib import Path

from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from app.core.job import Job, JobStatus
from app.core.job_processor import JobControl, ProcessContext, prepare_job, process_job
from app.parsers.base import ScriptMode
from app.parsers.detect import detect_mode
from app.parsers.conversation_parser import detect_speakers
from app.ui.context import AppContext
from app.ui.dialogs import TextPreviewDialog
from app.ui.pages.batch_page import MODES
from app.ui.widgets import PlayerBar, muted, page_header, primary
from app.ui.workers import run_async
from app.utils.paths import preview_dir
from app.utils.text_io import read_text_file


class GeneratePage(QWidget):
    def __init__(self, ctx: AppContext, parent=None) -> None:
        super().__init__(parent)
        self.ctx = ctx
        self._source_file: Path | None = None
        self._source_text = ""
        self._control: JobControl | None = None
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 16)
        root.addWidget(page_header("Generate", "Generate a single script – paste text or open one TXT file."))

        split = QSplitter()
        left = QWidget()
        ll = QVBoxLayout(left)
        ll.setContentsMargins(0, 0, 0, 0)
        bar = QHBoxLayout()
        open_btn = QPushButton("Open TXT…")
        self.file_label = muted("Unsaved text")
        bar.addWidget(open_btn)
        bar.addWidget(self.file_label, 1)
        ll.addLayout(bar)
        self.editor = QPlainTextEdit()
        self.editor.setPlaceholderText("Paste a story or a conversation here…\n\n[ANNA]\nHi Tom!\n\n[TOM]\nHello Anna.")
        ll.addWidget(self.editor, 1)
        split.addWidget(left)

        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(8, 0, 0, 0)
        g = QGroupBox("Options")
        f = QFormLayout(g)
        self.profile = QComboBox()
        self.mode = QComboBox()
        for label, value in MODES:
            self.mode.addItem(label, value)
        self.detected = muted("–")
        f.addRow("Profile", self.profile)
        f.addRow("Mode", self.mode)
        f.addRow("Detected", self.detected)
        rl.addWidget(g)
        row = QHBoxLayout()
        self.preview_btn = QPushButton("Preview text…")
        self.gen_btn = primary("Generate…")
        self.stop_btn = QPushButton("Stop")
        self.stop_btn.setEnabled(False)
        row.addWidget(self.preview_btn)
        row.addWidget(self.gen_btn)
        row.addWidget(self.stop_btn)
        rl.addLayout(row)
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        rl.addWidget(self.progress)
        self.status = muted("")
        rl.addWidget(self.status)
        self.player = PlayerBar()
        rl.addWidget(self.player)
        self.out_label = QLabel("")
        self.out_label.setWordWrap(True)
        rl.addWidget(self.out_label)
        rl.addStretch(1)
        split.addWidget(right)
        split.setSizes([700, 380])
        root.addWidget(split, 1)

        open_btn.clicked.connect(self._open)
        self.editor.textChanged.connect(self._text_changed)
        self.preview_btn.clicked.connect(self._preview)
        self.gen_btn.clicked.connect(self._generate)
        self.stop_btn.clicked.connect(self._stop)
        ctx.profiles_changed.connect(self._fill_profiles)
        self._fill_profiles()

    def _fill_profiles(self) -> None:
        cur = self.profile.currentText() or self.ctx.settings.last_profile
        self.profile.clear()
        self.profile.addItems(self.ctx.profiles.names())
        self.profile.setCurrentIndex(max(0, self.profile.findText(cur)))

    def open_file(self, path: Path) -> None:
        try:
            text, enc = read_text_file(path)
        except Exception as e:
            QMessageBox.warning(self, "Open", str(e))
            return
        self._source_file = path
        self._source_text = text
        self.editor.setPlainText(text)
        self.file_label.setText(f"{path}  ({enc})")

    def _open(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Open TXT", self.ctx.settings.last_folder, "Text files (*.txt)")
        if path:
            self.open_file(Path(path))

    def _text_changed(self) -> None:
        text = self.editor.toPlainText()
        if self._source_file and text != self._source_text:
            self.file_label.setText(f"{self._source_file.name} (edited – the file itself is not changed)")
        mode = detect_mode(text)
        if mode == ScriptMode.CONVERSATION:
            self.detected.setText("Conversation: " + ", ".join(detect_speakers(text)))
        else:
            self.detected.setText("Story" if text.strip() else "–")

    def _make_job(self) -> Job | None:
        text = self.editor.toPlainText()
        if not text.strip():
            QMessageBox.information(self, "Generate", "Enter or open some text first.")
            return None
        if self._source_file and text == self._source_text:
            src = self._source_file  # real file → its folder tts_config.json applies
        else:
            src = preview_dir() / "generate_input.txt"
            src.write_text(text, encoding="utf-8")
        return Job(source=str(src), root=str(src.parent), profile_name=self.profile.currentText(),
                   mode=self.mode.currentData())

    def _preview(self) -> None:
        job = self._make_job()
        if job is None:
            return
        try:
            prepared = prepare_job(job, self.ctx.profiles, self.ctx.settings, self.ctx.pronunciation.rules)
        except Exception as e:
            QMessageBox.warning(self, "Preview", str(e))
            return
        TextPreviewDialog(job, prepared, self).exec()

    def _generate(self) -> None:
        if not self.ctx.connected:
            QMessageBox.warning(self, "Not connected", "Connect to AudioStudio first (Settings).")
            return
        job = self._make_job()
        if job is None:
            return
        fmt = self.ctx.settings.output_format
        default_dir = self._source_file.parent if self._source_file else Path(self.ctx.settings.last_folder or Path.home())
        default_name = (self._source_file.stem if self._source_file else "speech") + f".{fmt}"
        out, _ = QFileDialog.getSaveFileName(self, "Save audio as", str(default_dir / default_name),
                                             "MP3 (*.mp3);;WAV (*.wav);;FLAC (*.flac)")
        if not out:
            return
        out_path = Path(out)
        if out_path.suffix.lower() not in (".mp3", ".wav", ".flac"):
            out_path = out_path.with_suffix(f".{fmt}")
        if out_path.suffix.lower() in (".mp3", ".flac") and not self.ctx.ffmpeg():
            QMessageBox.warning(self, "ffmpeg missing", "MP3/FLAC output needs ffmpeg. Choose .wav or install ffmpeg.")
            return
        job.output_override = str(out_path)
        self.player.release()
        self._control = JobControl()
        self.ctx.adapter.reset_cancel()
        ctx = ProcessContext(
            adapter=self.ctx.adapter, settings=self.ctx.settings, store=self.ctx.profiles,
            global_rules=list(self.ctx.pronunciation.rules), control=self._control,
            ffmpeg=self.ctx.ffmpeg(), cache=self.ctx.batch.cache,
            on_progress=lambda j: None,
        )
        self.gen_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self.progress.setValue(0)
        self.status.setText("Generating…")
        started = time.monotonic()
        self._job = job

        def tick():
            if self._control is not None:
                self.progress.setValue(job.progress)

        from PySide6.QtCore import QTimer

        self._timer = QTimer(self)
        self._timer.timeout.connect(tick)
        self._timer.start(300)

        def done(_):
            self._timer.stop()
            self._control = None
            self.gen_btn.setEnabled(True)
            self.stop_btn.setEnabled(False)
            self.progress.setValue(job.progress)
            if job.status == JobStatus.COMPLETED.value:
                self.status.setText(f"Done in {time.monotonic() - started:.1f}s · audio {job.duration_s or 0:.1f}s")
                self.out_label.setText(f"Saved: {job.output_path}")
                self.player.load(Path(job.output_path))
            else:
                self.status.setText(f"{job.status}: {job.error}")
                if job.status == JobStatus.FAILED.value:
                    QMessageBox.warning(self, "Generation failed", job.error)

        run_async(lambda: process_job(job, ctx), done, lambda e: done(None))

    def _stop(self) -> None:
        if self._control:
            self._control.cancel()
            if not self.ctx.batch.is_running:  # don't abort a running batch's request
                self.ctx.adapter.cancel()
