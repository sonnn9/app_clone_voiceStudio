"""Batch Folder page: queue table, filters and run controls."""
from __future__ import annotations

import os
from pathlib import Path

from PySide6.QtCore import QModelIndex, Qt, QUrl
from PySide6.QtGui import QAction, QDesktopServices
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QComboBox,
    QFileDialog,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMenu,
    QMessageBox,
    QProgressBar,
    QProgressDialog,
    QPushButton,
    QTableView,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from app.core.job import Job, JobStatus
from app.core.job_processor import analyze_job, prepare_job
from app.core.report import summarize
from app.core.settings import ExistingBehavior, OutputMode
from app.ui.context import AppContext
from app.ui.dialogs import AskExistingDialog, SummaryDialog, TextPreviewDialog, export_report
from app.ui.queue_model import (
    COL_CHECK,
    COL_FILE,
    COL_DURATION,
    COL_FOLDER,
    COL_MODE,
    COL_PROFILE,
    COL_PROGRESS,
    COL_STATUS,
    COL_VOICES,
    ProgressDelegate,
    QueueFilterProxy,
    QueueModel,
)
from app.ui.widgets import Card, muted, page_header, primary
from app.utils.file_scanner import scan_txt_files

MODES = [("Auto detect", "auto"), ("Story", "story"), ("Conversation", "conversation")]
EXISTING = [("Skip", ExistingBehavior.SKIP.value), ("Overwrite", ExistingBehavior.OVERWRITE.value),
            ("Ask", ExistingBehavior.ASK.value), ("Generate with suffix", ExistingBehavior.SUFFIX.value)]


class BatchPage(QWidget):
    def __init__(self, ctx: AppContext, parent=None) -> None:
        super().__init__(parent)
        self.ctx = ctx
        self.batch = ctx.batch
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 16)
        root.setSpacing(10)
        root.addWidget(page_header("Batch Folder",
                                   "Select a folder – every TXT in it and in all subfolders is queued. "
                                   "Audio is saved next to each TXT file."))

        # ---- source / options card
        card = Card()
        grid = QGridLayout()
        grid.setHorizontalSpacing(10)
        self.profile_combo = QComboBox()
        self.profile_combo.setMinimumWidth(200)
        self.mode_combo = QComboBox()
        for label, value in MODES:
            self.mode_combo.addItem(label, value)
        self.mode_combo.setToolTip("Auto detects [SPEAKER] tags or 'Name:' lines → Conversation, otherwise Story.")
        self.existing_combo = QComboBox()
        for label, value in EXISTING:
            self.existing_combo.addItem(label, value)
        self.existing_combo.setToolTip("What to do when the output audio file already exists.")
        self.output_combo = QComboBox()
        self.output_combo.addItem("Same folder as TXT", OutputMode.SAME_FOLDER.value)
        self.output_combo.addItem("Custom folder (keep structure)…", OutputMode.CUSTOM_FOLDER.value)
        self.apply_btn = QPushButton("Apply to selected")
        self.apply_btn.setToolTip("Apply the chosen profile and mode to the selected rows")
        grid.addWidget(QLabel("Profile"), 0, 0)
        grid.addWidget(self.profile_combo, 0, 1)
        grid.addWidget(QLabel("Mode"), 0, 2)
        grid.addWidget(self.mode_combo, 0, 3)
        grid.addWidget(self.apply_btn, 0, 4)
        grid.addWidget(QLabel("If output exists"), 1, 0)
        grid.addWidget(self.existing_combo, 1, 1)
        grid.addWidget(QLabel("Save to"), 1, 2)
        grid.addWidget(self.output_combo, 1, 3, 1, 2)
        grid.setColumnStretch(5, 1)
        card.lay.addLayout(grid)
        src = QHBoxLayout()
        self.output_hint = muted("")
        self.file_btn = QPushButton("Select File…")
        self.folder_btn = primary("Select Folder…")
        src.addWidget(self.output_hint, 1)
        src.addWidget(self.file_btn)
        src.addWidget(self.folder_btn)
        card.lay.addLayout(src)
        root.addWidget(card)

        # ---- filters / selection tools
        tools = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("Filter by file name…")
        self.search.setMinimumWidth(200)
        self.search.setClearButtonEnabled(True)
        self.status_filter = QComboBox()
        self.status_filter.addItem("All statuses", "")
        for st in JobStatus:
            self.status_filter.addItem(st.value, st.value)
        self.mode_filter = QComboBox()
        self.mode_filter.addItem("All modes", "")
        self.mode_filter.addItem("Story", "story")
        self.mode_filter.addItem("Conversation", "conversation")
        tools.addWidget(self.search, 2)
        tools.addWidget(self.status_filter)
        tools.addWidget(self.mode_filter)
        tools.addSpacing(12)
        self.check_btn = QToolButton()
        self.check_btn.setText("Check ▾")
        self.check_btn.setToolTip("Tick / untick the files that will be processed")
        self.check_btn.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        check_menu = QMenu(self.check_btn)
        self.act_all = check_menu.addAction("Select all")
        self.act_none = check_menu.addAction("Select none")
        self.act_failed = check_menu.addAction("Select failed")
        self.check_btn.setMenu(check_menu)
        self.remove_btn = QPushButton("Remove selected")
        self.retry_sel_btn = QPushButton("Retry selected")
        self.more_btn = QToolButton()
        self.more_btn.setText("More ▾")
        self.more_btn.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        more_menu = QMenu(self.more_btn)
        self.act_report = more_menu.addAction("Export report (CSV)…")
        self.act_clear = more_menu.addAction("Clear queue")
        self.more_btn.setMenu(more_menu)
        for b in (self.check_btn, self.remove_btn, self.retry_sel_btn, self.more_btn):
            tools.addWidget(b)
        root.addLayout(tools)

        # ---- table
        self.model = QueueModel(lambda: self.batch.jobs, self)
        self.proxy = QueueFilterProxy(self)
        self.proxy.setSourceModel(self.model)
        self.table = QTableView()
        self.table.setModel(self.proxy)
        self.table.setSortingEnabled(True)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.setAlternatingRowColors(True)
        self.table.setItemDelegateForColumn(COL_PROGRESS, ProgressDelegate(self.table))
        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        hh.setStretchLastSection(True)
        for col, w in ((COL_CHECK, 34), (COL_FILE, 210), (COL_FOLDER, 110), (COL_MODE, 150), (COL_PROFILE, 140),
                       (COL_VOICES, 240), (COL_DURATION, 70), (COL_PROGRESS, 100), (COL_STATUS, 90)):
            self.table.setColumnWidth(col, w)
        hh.setSortIndicator(-1, Qt.SortOrder.AscendingOrder)  # keep folder order until the user sorts
        self.empty_hint = muted("Drop TXT files or folders here, or click “Select Folder…”.")
        self.empty_hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        root.addWidget(self.table, 1)
        root.addWidget(self.empty_hint)

        # ---- progress & controls
        bottom = Card()
        row1 = QHBoxLayout()
        self.overall_label = QLabel("Overall: 0 / 0 files")
        self.overall_label.setMinimumWidth(170)
        self.overall_bar = QProgressBar()
        self.overall_bar.setRange(0, 100)
        row1.addWidget(self.overall_label)
        row1.addWidget(self.overall_bar, 1)
        bottom.lay.addLayout(row1)
        row2 = QHBoxLayout()
        self.current_label = muted("Current file: –")
        self.stats_label = QLabel("")
        row2.addWidget(self.current_label, 1)
        row2.addWidget(self.stats_label)
        bottom.lay.addLayout(row2)
        row3 = QHBoxLayout()
        self.start_btn = primary("▶  Start")
        self.pause_btn = QPushButton("Pause")
        self.resume_btn = QPushButton("▶  Resume")
        self.cancel_btn = QPushButton("■  Cancel")
        self.cancel_btn.setObjectName("Danger")
        self.retry_failed_btn = QPushButton("↻  Retry failed")
        for b in (self.start_btn, self.pause_btn, self.resume_btn, self.cancel_btn, self.retry_failed_btn):
            row3.addWidget(b)
        row3.addStretch(1)
        self.conc_label = muted("")
        row3.addWidget(self.conc_label)
        bottom.lay.addLayout(row3)
        root.addWidget(bottom)

        # ---- wiring
        self.folder_btn.clicked.connect(self.choose_folder)
        self.file_btn.clicked.connect(self.choose_files)
        self.apply_btn.clicked.connect(self.apply_to_selected)
        self.existing_combo.currentIndexChanged.connect(self._existing_changed)
        self.output_combo.activated.connect(self._output_changed)
        self.profile_combo.currentIndexChanged.connect(self._profile_changed)
        self.mode_combo.currentIndexChanged.connect(self._mode_changed)
        self.search.textChanged.connect(self._filter)
        self.status_filter.currentIndexChanged.connect(self._filter)
        self.mode_filter.currentIndexChanged.connect(self._filter)
        self.act_all.triggered.connect(lambda: self._check(lambda j: True))
        self.act_none.triggered.connect(lambda: self._check(lambda j: False))
        self.act_failed.triggered.connect(lambda: self._check(lambda j: j.status == JobStatus.FAILED.value))
        self.remove_btn.clicked.connect(self.remove_selected)
        self.retry_sel_btn.clicked.connect(self.retry_selected)
        self.act_clear.triggered.connect(self.clear_queue)
        self.act_report.triggered.connect(lambda: export_report(self, self.batch.jobs) if self.batch.jobs else None)
        self.start_btn.clicked.connect(self.start)
        self.pause_btn.clicked.connect(self.batch.pause)
        self.resume_btn.clicked.connect(self.batch.resume)
        self.cancel_btn.clicked.connect(self.cancel)
        self.retry_failed_btn.clicked.connect(self.retry_failed)
        self.table.doubleClicked.connect(self._preview_index)
        self.table.customContextMenuRequested.connect(self._context_menu)
        self.model.check_changed.connect(self._update_stats)

        self.batch.job_updated.connect(self.model.refresh_job)
        self.batch.stats_changed.connect(self._show_stats)
        self.batch.current_file_changed.connect(
            lambda f: self.current_label.setText(f"Current file: {f}" if f else "Current file: –"))
        self.batch.running_changed.connect(self._update_buttons)
        self.batch.paused_changed.connect(lambda _p: self._update_buttons())
        self.batch.batch_finished.connect(self._finished)
        self.batch.ask_existing.connect(self._ask_existing)
        ctx.profiles_changed.connect(self.reload_profiles)
        ctx.settings_changed.connect(self._load_settings)

        self.reload_profiles()
        self._load_settings()
        self.model.reset()
        self._update_buttons()
        self._update_stats()

    # ------------------------------------------------------------- settings
    def _load_settings(self) -> None:
        s = self.ctx.settings
        self.existing_combo.blockSignals(True)
        self.existing_combo.setCurrentIndex(max(0, self.existing_combo.findData(s.existing_behavior)))
        self.existing_combo.blockSignals(False)
        self.output_combo.setCurrentIndex(max(0, self.output_combo.findData(s.output_mode)))
        self.mode_combo.blockSignals(True)
        self.mode_combo.setCurrentIndex(max(0, self.mode_combo.findData(s.last_mode)))
        self.mode_combo.blockSignals(False)
        self._update_output_hint()
        self.conc_label.setText(f"Concurrent jobs: {s.concurrency}  ·  Format: {s.output_format.upper()}"
                                + (f" {s.mp3_bitrate_kbps} kbps" if s.output_format == "mp3" else ""))

    def _update_output_hint(self) -> None:
        s = self.ctx.settings
        if s.output_mode == OutputMode.CUSTOM_FOLDER.value and s.custom_output_dir:
            self.output_hint.setText(f"Output root: {s.custom_output_dir} (source subfolders are recreated)")
        else:
            self.output_hint.setText("Each audio file is written next to its TXT file (story1.txt → story1.mp3).")

    def reload_profiles(self) -> None:
        current = self.profile_combo.currentText() or self.ctx.settings.last_profile
        self.profile_combo.blockSignals(True)
        self.profile_combo.clear()
        self.profile_combo.addItems(self.ctx.profiles.names())
        idx = self.profile_combo.findText(current)
        self.profile_combo.setCurrentIndex(max(0, idx))
        self.profile_combo.blockSignals(False)

    def _profile_changed(self) -> None:
        self.ctx.settings.last_profile = self.profile_combo.currentText()
        self.ctx.save_settings()

    def _mode_changed(self) -> None:
        self.ctx.settings.last_mode = self.mode_combo.currentData()
        self.ctx.save_settings()

    def _existing_changed(self) -> None:
        self.ctx.settings.existing_behavior = self.existing_combo.currentData()
        self.ctx.save_settings()

    def _output_changed(self) -> None:
        s = self.ctx.settings
        mode = self.output_combo.currentData()
        if mode == OutputMode.CUSTOM_FOLDER.value:
            d = QFileDialog.getExistingDirectory(self, "Choose output root folder", s.custom_output_dir or s.last_folder)
            if not d:
                self.output_combo.setCurrentIndex(self.output_combo.findData(s.output_mode))
                return
            s.custom_output_dir = d
        s.output_mode = mode
        self.ctx.save_settings()
        self._refresh_outputs()

    def _refresh_outputs(self) -> None:
        if self.batch.is_running:
            return
        for j in self.batch.jobs:
            if not JobStatus(j.status).is_final:
                analyze_job(j, self.ctx.profiles, self.ctx.settings)
        self.model.reset()

    # --------------------------------------------------------------- adding
    def choose_folder(self) -> None:
        d = QFileDialog.getExistingDirectory(self, "Select folder with TXT scripts", self.ctx.settings.last_folder)
        if d:
            self.add_paths([Path(d)])

    def choose_files(self) -> None:
        files, _ = QFileDialog.getOpenFileNames(self, "Select TXT files", self.ctx.settings.last_folder,
                                                "Text files (*.txt);;All files (*.*)")
        if files:
            self.add_paths([Path(f) for f in files])

    def add_paths(self, paths: list[Path]) -> None:
        scanned = []
        for p in paths:
            if p.is_dir():
                scanned.extend(scan_txt_files(p))
                self.ctx.settings.last_folder = str(p)
            elif p.is_file() and p.suffix.lower() == ".txt":
                scanned.extend(scan_txt_files(p))
                self.ctx.settings.last_folder = str(p.parent)
        self.ctx.save_settings()
        if not scanned:
            QMessageBox.information(self, "No TXT files", "No .txt files were found.")
            return
        profile = self.profile_combo.currentText()
        mode = self.mode_combo.currentData()
        jobs = [Job(source=str(f.path), root=str(f.root), profile_name=profile, mode=mode) for f in scanned]
        jobs = self.batch.add_jobs(jobs)
        dlg = QProgressDialog("Analysing scripts…", "Stop", 0, len(jobs), self)
        dlg.setWindowModality(Qt.WindowModality.WindowModal)
        dlg.setMinimumDuration(400)
        for i, j in enumerate(jobs):
            analyze_job(j, self.ctx.profiles, self.ctx.settings)
            if i % 20 == 0:
                dlg.setValue(i)
                QApplication.processEvents()
                if dlg.wasCanceled():
                    break
        dlg.setValue(len(jobs))
        self.model.reset()
        self.batch.mark_dirty()
        self._update_buttons()
        if jobs:
            conv = sum(1 for j in jobs if j.detected_mode == "conversation")
            self.current_label.setText(f"Added {len(jobs)} file(s): {len(jobs) - conv} story, {conv} conversation.")

    # ---------------------------------------------------------- selection
    def _filter(self) -> None:
        self.proxy.set_filter(self.search.text().strip(), self.status_filter.currentData() or "",
                              self.mode_filter.currentData() or "")

    def _check(self, pred) -> None:
        visible = {self.proxy.mapToSource(self.proxy.index(r, 0)).row() for r in range(self.proxy.rowCount())}
        for i, j in enumerate(self.batch.jobs):
            if i in visible:
                j.checked = bool(pred(j))
        self.model.reset()
        self.batch.mark_dirty()

    def selected_jobs(self) -> list[Job]:
        rows = {self.proxy.mapToSource(i).row() for i in self.table.selectionModel().selectedRows()}
        return [self.batch.jobs[r] for r in sorted(rows)]

    def apply_to_selected(self) -> None:
        jobs = self.selected_jobs()
        if not jobs:
            QMessageBox.information(self, "Apply", "Select one or more rows first.")
            return
        for j in jobs:
            if j.status == JobStatus.PROCESSING.value:
                continue
            j.profile_name = self.profile_combo.currentText()
            j.mode = self.mode_combo.currentData()
            analyze_job(j, self.ctx.profiles, self.ctx.settings)
        self.model.reset()
        self.batch.mark_dirty()

    def _set_mode(self, mode: str) -> None:
        for j in self.selected_jobs():
            if j.status != JobStatus.PROCESSING.value:
                j.mode = mode
                analyze_job(j, self.ctx.profiles, self.ctx.settings)
        self.model.reset()
        self.batch.mark_dirty()

    def remove_selected(self) -> None:
        ids = {j.id for j in self.selected_jobs()}
        if ids:
            self.batch.remove_jobs(ids)
            self.model.reset()
            self._update_buttons()

    def clear_queue(self) -> None:
        if self.batch.is_running or not self.batch.jobs:
            return
        if QMessageBox.question(self, "Clear queue", "Remove all files from the queue?") == QMessageBox.StandardButton.Yes:
            self.batch.clear()
            self.model.reset()
            self._update_buttons()

    # -------------------------------------------------------------- running
    def _preflight(self) -> bool:
        if not self.ctx.connected:
            QMessageBox.warning(self, "Not connected",
                                "AudioStudio is not connected. Start the AudioStudio server and check "
                                "Settings → API Base URL, then press Test Connection.")
            return False
        fmt = self.ctx.settings.output_format
        if fmt in ("mp3", "flac") and not self.ctx.ffmpeg():
            QMessageBox.warning(self, "ffmpeg missing",
                                f"{fmt.upper()} output needs ffmpeg, which was not found.\n\n"
                                "Install it (winget install Gyan.FFmpeg), place ffmpeg.exe next to the app, "
                                "set its path in Settings, or choose WAV output.")
            return False
        return True

    def start(self) -> None:
        if not self._preflight():
            return
        n = self.batch.start()
        if n == 0:
            QMessageBox.information(self, "Nothing to do",
                                    "No checked files are pending. Use “Retry failed” or check some files.")

    def retry_failed(self) -> None:
        ids = {j.id for j in self.batch.jobs if j.status in (JobStatus.FAILED.value, JobStatus.CANCELLED.value)}
        if ids and self._preflight():
            self.batch.start(retry_ids=ids)

    def retry_selected(self) -> None:
        ids = {j.id for j in self.selected_jobs() if j.status != JobStatus.COMPLETED.value}
        if ids and self._preflight():
            self.batch.start(retry_ids=ids)

    def cancel(self) -> None:
        if QMessageBox.question(self, "Cancel batch",
                                "Stop the batch? Completed files are kept; the current file is discarded "
                                "safely and can be retried later.") == QMessageBox.StandardButton.Yes:
            self.batch.cancel()

    def _ask_existing(self, job_id: str, path: str) -> None:
        dlg = AskExistingDialog(path, self)
        dlg.exec()
        self.batch.answer_existing(dlg.answer, dlg.all.isChecked())

    def _finished(self, stats: dict) -> None:
        self.model.reset()
        if stats["total"]:
            SummaryDialog(stats, self.batch.jobs, self).exec()

    # ----------------------------------------------------------------- view
    def _update_buttons(self, *_args) -> None:
        running = self.batch.is_running
        paused = self.batch.is_paused
        has_jobs = bool(self.batch.jobs)
        self.start_btn.setEnabled(not running and has_jobs)
        self.pause_btn.setEnabled(running and not paused)
        self.resume_btn.setEnabled(running and paused)
        self.cancel_btn.setEnabled(running)
        self.retry_failed_btn.setEnabled(not running and any(
            j.status in (JobStatus.FAILED.value, JobStatus.CANCELLED.value) for j in self.batch.jobs))
        self.retry_sel_btn.setEnabled(not running)
        self.act_clear.setEnabled(not running)
        for w in (self.folder_btn, self.file_btn, self.apply_btn, self.output_combo):
            w.setEnabled(not running)
        self.empty_hint.setVisible(not has_jobs)
        if paused:
            self.current_label.setText("Paused – the current segment finishes, then processing waits.")

    def _update_stats(self) -> None:
        self._show_stats(summarize(self.batch.jobs))

    def _show_stats(self, st: dict) -> None:
        total = st["total"]
        self.overall_label.setText(f"Overall: {st['done']} / {total} files")
        cur = sum(j.progress for j in self.batch.jobs if j.checked and j.status == JobStatus.PROCESSING.value) / 100
        self.overall_bar.setValue(int((st["done"] + cur) / total * 100) if total else 0)
        self.stats_label.setText(
            f"<span>Completed <b>{st['completed']}</b> · Failed <b>{st['failed']}</b> · "
            f"Skipped <b>{st['skipped']}</b> · Remaining <b>{st['remaining']}</b></span>")
        self._update_buttons()

    # ---------------------------------------------------------- context menu
    def _preview_index(self, index: QModelIndex) -> None:
        if index.column() == COL_CHECK:
            return
        self.preview_job(self.batch.jobs[self.proxy.mapToSource(index).row()])

    def preview_job(self, job: Job) -> None:
        try:
            caps = self.ctx.capabilities(job.model or "omnivoice")
            prepared = prepare_job(job, self.ctx.profiles, self.ctx.settings, self.ctx.pronunciation.rules,
                                   caps.max_input_chars)
        except Exception as e:
            QMessageBox.warning(self, "Preview", f"Cannot read this file:\n{e}")
            return
        TextPreviewDialog(job, prepared, self).exec()

    def _context_menu(self, pos) -> None:
        jobs = self.selected_jobs()
        if not jobs:
            return
        menu = QMenu(self)
        job = jobs[0]
        menu.addAction("Preview text…", lambda: self.preview_job(job))
        if job.output_path and Path(job.output_path).exists():
            menu.addAction("Play output", lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(job.output_path)))
        menu.addAction("Open containing folder", lambda: _open_folder(job.source_path.parent))
        menu.addSeparator()
        mode_menu = menu.addMenu("Set mode")
        for label, value in MODES:
            act = QAction(label, mode_menu)
            act.triggered.connect(lambda _=False, v=value: self._set_mode(v))
            mode_menu.addAction(act)
        menu.addAction(f"Apply profile “{self.profile_combo.currentText()}”", self.apply_to_selected)
        menu.addSeparator()
        running = self.batch.is_running
        a = menu.addAction("Retry selected", self.retry_selected)
        a.setEnabled(not running)
        menu.addAction("Remove selected", self.remove_selected)
        menu.exec(self.table.viewport().mapToGlobal(pos))


def _open_folder(path: Path) -> None:
    if os.name == "nt":
        os.startfile(str(path))  # type: ignore[attr-defined]
    else:
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))
