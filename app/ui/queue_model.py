"""Table model for the batch queue."""
from __future__ import annotations

from PySide6.QtCore import QAbstractTableModel, QModelIndex, QSortFilterProxyModel, Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QStyle, QStyledItemDelegate, QStyleOptionProgressBar, QApplication

from app.core.job import Job
from app.ui import theme

COLUMNS = ["", "File", "Folder", "Mode", "Profile", "Voice / Voices", "Duration", "Progress", "Status", "Error"]
COL_CHECK, COL_FILE, COL_FOLDER, COL_MODE, COL_PROFILE, COL_VOICES, COL_DURATION, COL_PROGRESS, COL_STATUS, COL_ERROR = range(10)


def fmt_duration(seconds: float | None) -> str:
    if not seconds:
        return ""
    m, s = divmod(int(round(seconds)), 60)
    h, m = divmod(m, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


class QueueModel(QAbstractTableModel):
    check_changed = Signal()

    def __init__(self, jobs_provider, parent=None) -> None:
        super().__init__(parent)
        self._jobs = jobs_provider  # callable → list[Job]
        self._row_of: dict[str, int] = {}

    @property
    def jobs(self) -> list[Job]:
        return self._jobs()

    def reset(self) -> None:
        self.beginResetModel()
        self._row_of = {j.id: i for i, j in enumerate(self.jobs)}
        self.endResetModel()

    def refresh_job(self, job_id: str) -> None:
        row = self._row_of.get(job_id)
        if row is None or row >= len(self.jobs) or self.jobs[row].id != job_id:
            self.reset()
            return
        self.dataChanged.emit(self.index(row, 0), self.index(row, len(COLUMNS) - 1))

    def rowCount(self, parent=QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self.jobs)

    def columnCount(self, parent=QModelIndex()) -> int:
        return len(COLUMNS)

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if orientation == Qt.Orientation.Horizontal and role == Qt.ItemDataRole.DisplayRole:
            return COLUMNS[section]
        return None

    def flags(self, index):
        f = Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
        if index.column() == COL_CHECK:
            f |= Qt.ItemFlag.ItemIsUserCheckable
        return f

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        job = self.jobs[index.row()]
        col = index.column()
        if role == Qt.ItemDataRole.CheckStateRole and col == COL_CHECK:
            return Qt.CheckState.Checked if job.checked else Qt.CheckState.Unchecked
        if role == Qt.ItemDataRole.DisplayRole:
            return {
                COL_FILE: job.file_name,
                COL_FOLDER: job.folder,
                COL_MODE: job.mode_label,
                COL_PROFILE: job.profile_name + (" + folder config" if job.note else ""),
                COL_VOICES: job.voices,
                COL_DURATION: fmt_duration(job.duration_s),
                COL_PROGRESS: job.progress,
                COL_STATUS: job.status,
                COL_ERROR: job.error,
            }.get(col)
        if role == Qt.ItemDataRole.UserRole:  # sort/filter key
            return {COL_PROGRESS: job.progress, COL_DURATION: job.duration_s or 0}.get(col, self.data(index))
        if role == Qt.ItemDataRole.ForegroundRole and col == COL_STATUS:
            return QColor(theme.color(theme.STATUS_COLORS.get(job.status, "text")))
        if role == Qt.ItemDataRole.ToolTipRole:
            if col == COL_ERROR and job.error:
                return job.error
            if col in (COL_FILE, COL_FOLDER):
                tip = job.source
                if job.output_path:
                    tip += f"\n→ {job.output_path}"
                return tip
            if col == COL_VOICES:
                return job.voices
        return None

    def setData(self, index, value, role=Qt.ItemDataRole.EditRole) -> bool:
        if index.column() == COL_CHECK and role == Qt.ItemDataRole.CheckStateRole:
            self.jobs[index.row()].checked = Qt.CheckState(value) == Qt.CheckState.Checked
            self.dataChanged.emit(index, index)
            self.check_changed.emit()
            return True
        return False

    def job_at(self, row: int) -> Job:
        return self.jobs[row]


class QueueFilterProxy(QSortFilterProxyModel):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.search = ""
        self.status = ""
        self.mode = ""
        self.setSortRole(Qt.ItemDataRole.UserRole)
        self.setSortCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)

    def set_filter(self, search: str, status: str, mode: str) -> None:
        self.search, self.status, self.mode = search.casefold(), status, mode
        self.invalidateFilter()

    def filterAcceptsRow(self, row: int, parent) -> bool:
        job: Job = self.sourceModel().job_at(row)  # type: ignore[attr-defined]
        if self.search and self.search not in job.relative_path.casefold():
            return False
        if self.status and job.status != self.status:
            return False
        if self.mode:
            effective = job.detected_mode if job.mode == "auto" else job.mode
            if effective != self.mode:
                return False
        return True


class ProgressDelegate(QStyledItemDelegate):
    def paint(self, painter, option, index) -> None:
        value = index.data(Qt.ItemDataRole.DisplayRole) or 0
        opt = QStyleOptionProgressBar()
        opt.rect = option.rect.adjusted(4, 6, -4, -6)
        opt.minimum, opt.maximum = 0, 100
        opt.progress = int(value)
        opt.text = f"{int(value)}%"
        opt.textVisible = True
        QApplication.style().drawControl(QStyle.ControlElement.CE_ProgressBar, opt, painter)
