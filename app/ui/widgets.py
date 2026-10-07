"""Reusable widgets."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from PySide6.QtCore import (
    QAbstractTableModel,
    QModelIndex,
    QSortFilterProxyModel,
    Qt,
    QUrl,
    Signal,
)
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from app.api.models import EngineCapabilities, ParamSpec, VoiceInfo, VoiceSelection
from app.ui import theme


# ---------------------------------------------------------------- basics
class StatusDot(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedSize(12, 12)
        self._color = "muted"

    def set_state(self, state: str) -> None:  # "ok" | "danger" | "warn" | "muted"
        self._color = state
        self.update()

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setBrush(QColor(theme.color(self._color)))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(1, 1, 10, 10)


class Card(QFrame):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("Card")
        self.lay = QVBoxLayout(self)
        self.lay.setContentsMargins(16, 14, 16, 14)
        self.lay.setSpacing(8)


def page_header(title: str, subtitle: str = "") -> QWidget:
    w = QWidget()
    lay = QVBoxLayout(w)
    lay.setContentsMargins(0, 0, 0, 6)
    lay.setSpacing(2)
    t = QLabel(title)
    t.setObjectName("PageTitle")
    lay.addWidget(t)
    if subtitle:
        s = QLabel(subtitle)
        s.setObjectName("Muted")
        s.setWordWrap(True)
        lay.addWidget(s)
    return w


def muted(text: str) -> QLabel:
    lbl = QLabel(text)
    lbl.setObjectName("Muted")
    lbl.setWordWrap(True)
    return lbl


def primary(text: str) -> QPushButton:
    b = QPushButton(text)
    b.setObjectName("Primary")
    return b


# ----------------------------------------------------------- voice table
VOICE_COLUMNS = ["Name", "Gender", "Language", "Accent", "Age", "Pitch", "Category", "Source", "Voice ID"]


class VoiceTableModel(QAbstractTableModel):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.voices: list[VoiceInfo] = []

    def set_voices(self, voices: list[VoiceInfo]) -> None:
        self.beginResetModel()
        self.voices = list(voices)
        self.endResetModel()

    def rowCount(self, parent=QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self.voices)

    def columnCount(self, parent=QModelIndex()) -> int:
        return len(VOICE_COLUMNS)

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if orientation == Qt.Orientation.Horizontal and role == Qt.ItemDataRole.DisplayRole:
            return VOICE_COLUMNS[section]
        return None

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        v = self.voices[index.row()]
        if role == Qt.ItemDataRole.DisplayRole:
            source = {"profile": "My profile", "archetype": "Designed", "default": "Engine", "alias": "Alias"}
            return [v.name, v.gender, v.language, v.accent, v.age, v.pitch, v.style.capitalize(),
                    source.get(v.source, v.source), v.voice_id][index.column()]
        if role == Qt.ItemDataRole.ToolTipRole:
            parts = [v.name]
            if v.instruct:
                parts.append(f"Voice design: {v.instruct}")
            if v.description:
                parts.append(v.description)
            return "\n".join(parts)
        if role == Qt.ItemDataRole.UserRole:
            return v
        return None


class VoiceFilterProxy(QSortFilterProxyModel):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.search = ""
        self.gender = ""
        self.language = ""
        self.category = ""
        self.source = ""
        self.setSortCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)

    def set_filter(self, **kw: str) -> None:
        for k, v in kw.items():
            setattr(self, k, v)
        self.invalidateFilter()

    def filterAcceptsRow(self, row: int, parent: QModelIndex) -> bool:
        model: VoiceTableModel = self.sourceModel()  # type: ignore[assignment]
        v = model.voices[row]
        if self.gender and v.gender.lower() != self.gender.lower():
            return False
        if self.language and v.language.lower() != self.language.lower():
            return False
        if self.category and v.style.lower() != self.category.lower():
            return False
        if self.source and v.source != self.source:
            return False
        if self.search and not v.matches(self.search):
            return False
        return True


class VoiceBrowser(QWidget):
    """Search box + filters + voice table."""

    selection_changed = Signal(object)  # VoiceInfo | None
    activated = Signal(object)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        bar = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search name, accent, description…")
        self.search.setClearButtonEnabled(True)
        self.gender = QComboBox()
        self.language = QComboBox()
        self.category = QComboBox()
        self.source = QComboBox()
        for combo, tip in ((self.gender, "Gender"), (self.language, "Language"),
                           (self.category, "Category / style"), (self.source, "Voice source")):
            combo.setToolTip(tip)
            combo.setMinimumWidth(110)
        bar.addWidget(self.search, 2)
        for w in (self.gender, self.language, self.category, self.source):
            bar.addWidget(w, 1)
        lay.addLayout(bar)
        self.count = muted("")
        lay.addWidget(self.count)

        self.model = VoiceTableModel(self)
        self.proxy = VoiceFilterProxy(self)
        self.proxy.setSourceModel(self.model)
        self.table = QTableView()
        self.table.setModel(self.proxy)
        self.table.setSortingEnabled(True)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.setAlternatingRowColors(True)
        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        hh.setStretchLastSection(True)
        self.table.setColumnWidth(0, 230)
        hh.setSortIndicator(-1, Qt.SortOrder.AscendingOrder)  # AudioStudio order (featured voices first)
        lay.addWidget(self.table, 1)

        self.search.textChanged.connect(lambda t: self._apply())
        for combo in (self.gender, self.language, self.category, self.source):
            combo.currentIndexChanged.connect(lambda _i: self._apply())
        self.table.selectionModel().selectionChanged.connect(lambda *_: self.selection_changed.emit(self.current()))
        self.table.doubleClicked.connect(lambda _i: self.activated.emit(self.current()))

    def set_voices(self, voices: list[VoiceInfo]) -> None:
        self.model.set_voices(voices)
        self._fill(self.gender, "All genders", sorted({v.gender for v in voices if v.gender}))
        self._fill(self.language, "All languages", sorted({v.language for v in voices if v.language}))
        self._fill(self.category, "All categories", sorted({v.style.capitalize() for v in voices if v.style}))
        sources = {"profile": "My profiles", "archetype": "Designed voices", "default": "Engine default"}
        self.source.blockSignals(True)
        cur = self.source.currentData()
        self.source.clear()
        self.source.addItem("All sources", "")
        for key in ("profile", "archetype", "default"):
            if any(v.source == key for v in voices):
                self.source.addItem(sources[key], key)
        idx = self.source.findData(cur)
        self.source.setCurrentIndex(max(0, idx))
        self.source.blockSignals(False)
        self._apply()

    @staticmethod
    def _fill(combo: QComboBox, all_label: str, values: list[str]) -> None:
        cur = combo.currentData()
        combo.blockSignals(True)
        combo.clear()
        combo.addItem(all_label, "")
        for v in values:
            combo.addItem(v, v)
        idx = combo.findData(cur)
        combo.setCurrentIndex(max(0, idx))
        combo.blockSignals(False)

    def _apply(self) -> None:
        self.proxy.set_filter(
            search=self.search.text().strip(),
            gender=self.gender.currentData() or "",
            language=self.language.currentData() or "",
            category=self.category.currentData() or "",
            source=self.source.currentData() or "",
        )
        self.count.setText(f"{self.proxy.rowCount()} of {self.model.rowCount()} voices")

    def current(self) -> VoiceInfo | None:
        idx = self.table.selectionModel().currentIndex() if self.table.selectionModel() else None
        if idx is None or not idx.isValid():
            rows = self.table.selectionModel().selectedRows()
            if not rows:
                return None
            idx = rows[0]
        return self.proxy.data(self.proxy.index(idx.row(), 0), Qt.ItemDataRole.UserRole)

    def select_key(self, key: str) -> None:
        for row in range(self.proxy.rowCount()):
            v = self.proxy.data(self.proxy.index(row, 0), Qt.ItemDataRole.UserRole)
            if v and v.key == key:
                self.table.selectRow(row)
                self.table.scrollTo(self.proxy.index(row, 0))
                return


class VoicePickerDialog(QDialog):
    def __init__(self, voices: list[VoiceInfo], current_key: str = "", title: str = "Choose voice", parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(900, 560)
        lay = QVBoxLayout(self)
        self.browser = VoiceBrowser(self)
        self.browser.set_voices(voices)
        if current_key:
            self.browser.select_key(current_key)
        lay.addWidget(self.browser)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        self.browser.activated.connect(lambda _v: self.accept())
        lay.addWidget(buttons)

    def selected(self) -> VoiceInfo | None:
        return self.browser.current()


class VoiceButton(QPushButton):
    """Shows the chosen voice; click to open the picker."""

    voice_changed = Signal(object)  # VoiceSelection

    def __init__(self, voices_provider, parent=None) -> None:
        super().__init__(parent)
        self._provider = voices_provider
        self._selection = VoiceSelection()
        self.setMinimumWidth(220)
        self.clicked.connect(self._pick)
        self._refresh()

    def selection(self) -> VoiceSelection:
        return self._selection

    def set_selection(self, sel: VoiceSelection) -> None:
        self._selection = sel
        self._refresh()

    def _refresh(self) -> None:
        self.setText(f"♫  {self._selection.name or self._selection.key}")
        tip = self._selection.key
        if self._selection.instruct:
            tip += f"\n{self._selection.instruct}"
        self.setToolTip(tip)

    def _pick(self) -> None:
        voices = self._provider()
        if not voices:
            from PySide6.QtWidgets import QMessageBox

            QMessageBox.information(self, "Voices", "No voices loaded yet. Connect to AudioStudio first (Settings).")
            return
        dlg = VoicePickerDialog(voices, self._selection.key, parent=self)
        if dlg.exec() == QDialog.DialogCode.Accepted and dlg.selected():
            self.set_selection(dlg.selected().selection())
            self.voice_changed.emit(self._selection)


# ------------------------------------------------- capability-based params
class ParamForm(QWidget):
    """Builds inputs only for parameters the selected engine supports."""

    # Parameters with dedicated controls elsewhere.
    EXCLUDE = {"speed", "language", "instruct"}

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.form = QFormLayout(self)
        self.form.setContentsMargins(0, 0, 0, 0)
        self._editors: dict[str, tuple[ParamSpec, QWidget, QCheckBox | None]] = {}
        self._empty = muted("This engine exposes no additional parameters.")

    def build(self, caps: EngineCapabilities, values: dict[str, Any]) -> None:
        while self.form.rowCount():
            self.form.removeRow(0)
        self._editors.clear()
        shown = [p for p in caps.params if p.name not in self.EXCLUDE]
        if not shown:
            self._empty = muted("This engine exposes no additional parameters.")
            self.form.addRow(self._empty)
            return
        for spec in shown:
            editor, use = self._make(spec, values.get(spec.name))
            row = QWidget()
            h = QHBoxLayout(row)
            h.setContentsMargins(0, 0, 0, 0)
            if use is not None:
                h.addWidget(use)
            h.addWidget(editor, 1)
            label = QLabel(spec.label)
            label.setToolTip(spec.description)
            editor.setToolTip(spec.description)
            self.form.addRow(label, row)
            self._editors[spec.name] = (spec, editor, use)

    def _make(self, spec: ParamSpec, value: Any) -> tuple[QWidget, QCheckBox | None]:
        use: QCheckBox | None = None
        if spec.nullable and spec.kind != "bool":
            use = QCheckBox("Set")
            use.setToolTip("Unchecked = let the engine use its own default")
            use.setChecked(value is not None)
        if spec.kind == "bool":
            w = QCheckBox()
            w.setChecked(bool(value if value is not None else spec.default))
        elif spec.kind == "int":
            w = QSpinBox()
            w.setRange(int(spec.minimum if spec.minimum is not None else -2**31 + 1),
                       int(spec.maximum if spec.maximum is not None else 2**31 - 1))
            w.setValue(int(value if value is not None else (spec.default if spec.default is not None else
                                                             (spec.minimum or 0))))
        elif spec.kind == "float":
            w = QDoubleSpinBox()
            w.setDecimals(2)
            w.setSingleStep(0.1)
            lo = spec.minimum if spec.minimum is not None else -1e6
            if spec.exclusive_minimum:
                lo += 0.01
            w.setRange(lo, spec.maximum if spec.maximum is not None else 1e6)
            w.setValue(float(value if value is not None else (spec.default if spec.default is not None else 1.0)))
        else:
            w = QLineEdit()
            w.setText(str(value or ""))
        if use is not None:
            w.setEnabled(use.isChecked())
            use.toggled.connect(w.setEnabled)
        return w, use

    def values(self) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for name, (spec, w, use) in self._editors.items():
            if use is not None and not use.isChecked():
                out[name] = None
                continue
            if isinstance(w, QCheckBox):
                out[name] = w.isChecked()
            elif isinstance(w, (QSpinBox, QDoubleSpinBox)):
                out[name] = w.value()
            elif isinstance(w, QLineEdit):
                out[name] = w.text().strip() or None
        return out


# ------------------------------------------------------------- audio player
try:
    from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer

    HAS_QT_MULTIMEDIA = True
except ImportError:  # pragma: no cover - depends on the PySide6 build
    HAS_QT_MULTIMEDIA = False


class PlayerBar(QWidget):
    """Play / Stop / Replay for a generated file (QtMultimedia, or the system player as fallback)."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._path: Path | None = None
        self.player = None
        if HAS_QT_MULTIMEDIA:
            self.player = QMediaPlayer(self)
            self.output = QAudioOutput(self)
            self.player.setAudioOutput(self.output)
            self.player.playbackStateChanged.connect(self._state)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.play_btn = QPushButton("▶  Play")
        self.stop_btn = QPushButton("■  Stop")
        self.replay_btn = QPushButton("↻  Replay")
        self.label = muted("No audio")
        for b in (self.play_btn, self.stop_btn, self.replay_btn):
            b.setEnabled(False)
            lay.addWidget(b)
        lay.addWidget(self.label, 1)
        self.play_btn.clicked.connect(self._toggle)
        self.stop_btn.clicked.connect(self.stop)
        self.replay_btn.clicked.connect(self.replay)

    def load(self, path: Path, autoplay: bool = True) -> None:
        self._path = Path(path)
        self.label.setText(self._path.name)
        self.play_btn.setEnabled(True)
        if self.player is None:
            if autoplay:
                self._system_play()
            return
        self.player.stop()
        self.player.setSource(QUrl())  # release the previous file handle
        self.player.setSource(QUrl.fromLocalFile(str(path)))
        self.stop_btn.setEnabled(True)
        self.replay_btn.setEnabled(True)
        if autoplay:
            self.player.play()

    def release(self) -> None:
        if self.player is not None:
            self.player.stop()
            self.player.setSource(QUrl())

    def stop(self) -> None:
        if self.player is not None:
            self.player.stop()

    def replay(self) -> None:
        if self.player is not None:
            self.player.setPosition(0)
            self.player.play()

    def _system_play(self) -> None:
        if self._path is None:
            return
        from PySide6.QtGui import QDesktopServices

        QDesktopServices.openUrl(QUrl.fromLocalFile(str(self._path)))

    def _toggle(self) -> None:
        if self.player is None:
            self._system_play()
        elif self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self.player.pause()
        else:
            self.player.play()

    def _state(self, state) -> None:
        playing = state == QMediaPlayer.PlaybackState.PlayingState
        self.play_btn.setText("Pause" if playing else "▶  Play")
