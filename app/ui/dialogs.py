"""Dialogs: text preview, batch summary, existing-file question."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QHeaderView,
)

from app.core.job import Job
from app.core.job_processor import PreparedJob
from app.core.report import export_csv
from app.parsers.base import ScriptMode
from app.ui.widgets import muted


class TextPreviewDialog(QDialog):
    """Original vs processed text, detected speakers and their voices (read-only)."""

    def __init__(self, job: Job, prepared: PreparedJob, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"Preview – {job.file_name}")
        self.resize(900, 640)
        lay = QVBoxLayout(self)
        profile = prepared.profile
        info = (f"Mode: <b>{prepared.script.mode.value.capitalize()}</b> &nbsp;·&nbsp; Profile: <b>{profile.name}</b>"
                f" &nbsp;·&nbsp; Engine: <b>{profile.engine}</b> &nbsp;·&nbsp; Segments: <b>{len(prepared.segments)}</b>"
                f" &nbsp;·&nbsp; Characters: <b>{len(prepared.processed_text)}</b>")
        lay.addWidget(QLabel(info))
        if prepared.config_files:
            lay.addWidget(muted("Folder config applied: " + ", ".join(str(p) for p in prepared.config_files)))

        tabs = QTabWidget()
        for title, text in (("Original text", prepared.original_text), ("Processed text", prepared.processed_text)):
            ed = QPlainTextEdit(text)
            ed.setReadOnly(True)
            tabs.addTab(ed, title)

        table = QTableWidget(0, 2)
        table.setHorizontalHeaderLabels(["Speaker", "Voice"])
        table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        table.verticalHeader().setVisible(False)
        if prepared.script.mode == ScriptMode.CONVERSATION:
            speakers = prepared.script.speakers
        else:
            speakers = ["(narrator)"]
        for spk in speakers:
            r = table.rowCount()
            table.insertRow(r)
            v = profile.voice if spk == "(narrator)" else profile.voice_for(spk)
            table.setItem(r, 0, QTableWidgetItem(spk))
            mapped = spk in profile.speaker_voices
            table.setItem(r, 1, QTableWidgetItem(v.name + ("" if mapped or spk == "(narrator)" else "  (default voice)")))
        tabs.addTab(table, f"Speakers & voices ({len(speakers)})")

        seg_table = QTableWidget(0, 4)
        seg_table.setHorizontalHeaderLabels(["#", "Pause before", "Voice", "Text"])
        seg_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        seg_table.verticalHeader().setVisible(False)
        for s in prepared.segments:
            r = seg_table.rowCount()
            seg_table.insertRow(r)
            seg_table.setItem(r, 0, QTableWidgetItem(str(s.index + 1)))
            seg_table.setItem(r, 1, QTableWidgetItem(f"{s.silence_before_ms} ms"))
            seg_table.setItem(r, 2, QTableWidgetItem(s.voice.name))
            seg_table.setItem(r, 3, QTableWidgetItem(s.text))
        tabs.addTab(seg_table, f"Segments ({len(prepared.segments)})")
        lay.addWidget(tabs, 1)
        lay.addWidget(muted("The original TXT file is never modified."))
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)


class SummaryDialog(QDialog):
    def __init__(self, stats: dict, jobs: list[Job], parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Batch finished")
        self.jobs = jobs
        lay = QVBoxLayout(self)
        grid = QGridLayout()
        rows = [("Completed", stats["completed"]), ("Failed", stats["failed"]),
                ("Skipped", stats["skipped"]), ("Cancelled", stats["cancelled"]),
                ("Remaining", stats["pending"])]
        for i, (k, v) in enumerate(rows):
            grid.addWidget(QLabel(f"{k}:"), i, 0)
            val = QLabel(f"<b>{v}</b>")
            grid.addWidget(val, i, 1)
        lay.addLayout(grid)
        failed = [j for j in jobs if j.status == "Failed"]
        if failed:
            lay.addWidget(QLabel("Failed files:"))
            box = QPlainTextEdit("\n".join(f"{j.relative_path}: {j.error}" for j in failed))
            box.setReadOnly(True)
            box.setMinimumSize(560, 140)
            lay.addWidget(box)
        h = QHBoxLayout()
        export = QPushButton("Export batch_report.csv…")
        export.clicked.connect(self._export)
        h.addWidget(export)
        h.addStretch(1)
        close = QPushButton("Close")
        close.clicked.connect(self.accept)
        h.addWidget(close)
        lay.addLayout(h)

    def _export(self) -> None:
        export_report(self, self.jobs)


def export_report(parent, jobs: list[Job]) -> None:
    start = Path(jobs[0].root or jobs[0].source_path.parent) / "batch_report.csv" if jobs else Path("batch_report.csv")
    path, _ = QFileDialog.getSaveFileName(parent, "Export report", str(start), "CSV files (*.csv)")
    if path:
        export_csv(jobs, Path(path))


class AskExistingDialog(QDialog):
    def __init__(self, path: str, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Output already exists")
        self.answer = "skip"
        lay = QVBoxLayout(self)
        lay.addWidget(QLabel(f"This file already exists:\n{path}\n\nWhat should be done?"))
        self.all = QCheckBox("Apply to all remaining files in this batch")
        lay.addWidget(self.all)
        h = QHBoxLayout()
        for label, ans in (("Skip", "skip"), ("Overwrite", "overwrite"), ("Save with suffix (_001)", "suffix")):
            b = QPushButton(label)
            b.clicked.connect(lambda _=False, a=ans: self._done(a))
            h.addWidget(b)
        lay.addLayout(h)

    def _done(self, answer: str) -> None:
        self.answer = answer
        self.accept()
