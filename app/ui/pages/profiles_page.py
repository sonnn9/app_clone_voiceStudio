"""Profiles page: create, edit, duplicate and delete generation profiles."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLineEdit,
    QListWidget,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.api.models import VoiceSelection
from app.core.profiles import GenerationProfile, SilenceSettings
from app.core.pronunciation import PronunciationRule
from app.parsers.conversation_parser import detect_speakers
from app.ui.context import AppContext
from app.ui.pages.batch_page import MODES
from app.ui.widgets import ParamForm, VoiceButton, muted, page_header, primary
from app.utils.text_io import read_text_file


class SpeakerTable(QTableWidget):
    """Speaker → voice mapping rows, each with a VoiceButton."""

    def __init__(self, voices_provider, parent=None) -> None:
        super().__init__(0, 3, parent)
        self._provider = voices_provider
        self.setHorizontalHeaderLabels(["Speaker", "Voice", ""])
        self.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.setColumnWidth(0, 160)
        self.setColumnWidth(2, 40)
        self.verticalHeader().setVisible(False)
        self.setMinimumHeight(150)

    def set_mapping(self, mapping: dict[str, VoiceSelection]) -> None:
        self.setRowCount(0)
        for spk, sel in mapping.items():
            self.add_speaker(spk, sel)

    def add_speaker(self, name: str, sel: VoiceSelection | None = None) -> None:
        name = name.strip().upper()
        if not name or name in self.mapping():
            return
        r = self.rowCount()
        self.insertRow(r)
        self.setItem(r, 0, QTableWidgetItem(name))
        btn = VoiceButton(self._provider)
        btn.set_selection(sel or VoiceSelection())
        self.setCellWidget(r, 1, btn)
        rm = QPushButton("✕")
        rm.setToolTip("Remove speaker")
        rm.clicked.connect(lambda _=False, b=rm: self._remove(b))
        self.setCellWidget(r, 2, rm)

    def _remove(self, button: QPushButton) -> None:
        for r in range(self.rowCount()):
            if self.cellWidget(r, 2) is button:
                self.removeRow(r)
                return

    def mapping(self) -> dict[str, VoiceSelection]:
        out: dict[str, VoiceSelection] = {}
        for r in range(self.rowCount()):
            item = self.item(r, 0)
            btn = self.cellWidget(r, 1)
            if item and isinstance(btn, VoiceButton) and item.text().strip():
                out[item.text().strip().upper()] = btn.selection()
        return out


class RulesTable(QTableWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(0, 4, parent)
        self.setHorizontalHeaderLabels(["Original text", "Spoken as", "Whole word", "Match case"])
        self.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.verticalHeader().setVisible(False)

    def set_rules(self, rules: list[PronunciationRule]) -> None:
        self.setRowCount(0)
        for rule in rules:
            self.add_rule(rule)

    def add_rule(self, rule: PronunciationRule | None = None) -> None:
        rule = rule or PronunciationRule("", "")
        r = self.rowCount()
        self.insertRow(r)
        self.setItem(r, 0, QTableWidgetItem(rule.original))
        self.setItem(r, 1, QTableWidgetItem(rule.replacement))
        for col, val in ((2, rule.whole_word), (3, rule.case_sensitive)):
            it = QTableWidgetItem()
            it.setFlags(Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEnabled)
            it.setCheckState(Qt.CheckState.Checked if val else Qt.CheckState.Unchecked)
            self.setItem(r, col, it)
        if not rule.original:
            self.editItem(self.item(r, 0))

    def remove_selected(self) -> None:
        for r in sorted({i.row() for i in self.selectedIndexes()}, reverse=True):
            self.removeRow(r)

    def rules(self) -> list[PronunciationRule]:
        out = []
        for r in range(self.rowCount()):
            orig = (self.item(r, 0).text() if self.item(r, 0) else "").strip()
            if not orig:
                continue
            out.append(PronunciationRule(
                original=orig,
                replacement=self.item(r, 1).text() if self.item(r, 1) else "",
                whole_word=self.item(r, 2).checkState() == Qt.CheckState.Checked,
                case_sensitive=self.item(r, 3).checkState() == Qt.CheckState.Checked,
            ))
        return out


class ProfilesPage(QWidget):
    def __init__(self, ctx: AppContext, parent=None) -> None:
        super().__init__(parent)
        self.ctx = ctx
        self._editing: str | None = None
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 16)
        root.addWidget(page_header("Profiles", "Reusable generation presets. Only parameters supported by the "
                                               "selected AudioStudio engine are shown and saved."))
        split = QSplitter()
        # ---- list
        left = QWidget()
        ll = QVBoxLayout(left)
        ll.setContentsMargins(0, 0, 0, 0)
        self.list = QListWidget()
        ll.addWidget(self.list, 1)
        lb = QHBoxLayout()
        self.new_btn = QPushButton("New")
        self.dup_btn = QPushButton("Duplicate")
        self.del_btn = QPushButton("Delete")
        self.del_btn.setObjectName("Danger")
        for b in (self.new_btn, self.dup_btn, self.del_btn):
            lb.addWidget(b)
        ll.addLayout(lb)
        split.addWidget(left)

        # ---- editor
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        editor = QWidget()
        el = QVBoxLayout(editor)
        el.setContentsMargins(4, 0, 8, 0)

        g = QGroupBox("General")
        f = QFormLayout(g)
        self.name = QLineEdit()
        self.desc = QLineEdit()
        self.engine = QComboBox()
        self.engine.setToolTip("AudioStudio TTS engine (only installed/available engines are listed).")
        self.mode = QComboBox()
        for label, value in MODES:
            self.mode.addItem(label, value)
        self.voice = VoiceButton(self._voices)
        self.speed = QDoubleSpinBox()
        self.speed.setRange(0.25, 4.0)
        self.speed.setSingleStep(0.05)
        self.language = QComboBox()
        self.language.setEditable(True)
        self.language.setToolTip("ISO 639-1 code (en, vi, …). Empty = automatic.")
        self.instruct = QLineEdit()
        self.instruct.setPlaceholderText("e.g. calm, storytelling  (optional)")
        self.instruct.setToolTip("Style instruction sent as `instruct`. For designed voices it is appended to "
                                 "the voice design prompt.")
        self.out_fmt = QComboBox()
        self.out_fmt.addItem("Use global setting", "")
        for fmt in ("mp3", "wav", "flac"):
            self.out_fmt.addItem(fmt.upper(), fmt)
        f.addRow("Name", self.name)
        f.addRow("Description", self.desc)
        f.addRow("Engine / model", self.engine)
        f.addRow("Default mode", self.mode)
        f.addRow("Narrator / main voice", self.voice)
        self.speed_label = "Speed"
        f.addRow("Speed", self.speed)
        f.addRow("Language", self.language)
        f.addRow("Style instruction", self.instruct)
        f.addRow("Output format", self.out_fmt)
        el.addWidget(g)

        g2 = QGroupBox("Engine parameters")
        g2l = QVBoxLayout(g2)
        self.params = ParamForm()
        g2l.addWidget(self.params)
        self.caps_note = muted("")
        g2l.addWidget(self.caps_note)
        el.addWidget(g2)

        g3 = QGroupBox("Pauses")
        f3 = QFormLayout(g3)
        self.turn_ms, self.para_ms, self.narr_ms, self.sent_ms = (self._ms() for _ in range(4))
        f3.addRow("Between dialogue turns", self.turn_ms)
        f3.addRow("Between paragraphs", self.para_ms)
        f3.addRow("Before narrator sections", self.narr_ms)
        f3.addRow("Between sentences (story)", self.sent_ms)
        self.sent_ms.setToolTip("0 = natural flow. Above 0, each sentence is generated separately "
                                "and this silence is inserted between them.")
        el.addWidget(g3)

        g4 = QGroupBox("Conversation speakers → voices")
        g4l = QVBoxLayout(g4)
        self.speakers = SpeakerTable(self._voices)
        g4l.addWidget(self.speakers)
        sb = QHBoxLayout()
        add_spk = QPushButton("Add speaker…")
        detect = QPushButton("Detect from TXT file…")
        sb.addWidget(add_spk)
        sb.addWidget(detect)
        sb.addStretch(1)
        g4l.addLayout(sb)
        g4l.addWidget(muted("Unmapped speakers use the narrator / main voice."))
        el.addWidget(g4)

        g5 = QGroupBox("Profile pronunciation rules")
        g5l = QVBoxLayout(g5)
        self.rules = RulesTable()
        self.rules.setMinimumHeight(120)
        g5l.addWidget(self.rules)
        rb = QHBoxLayout()
        add_rule = QPushButton("Add rule")
        rm_rule = QPushButton("Remove selected")
        rb.addWidget(add_rule)
        rb.addWidget(rm_rule)
        rb.addStretch(1)
        g5l.addLayout(rb)
        el.addWidget(g5)

        save_row = QHBoxLayout()
        save_row.addStretch(1)
        self.save_btn = primary("Save profile")
        save_row.addWidget(self.save_btn)
        el.addLayout(save_row)
        el.addStretch(1)
        scroll.setWidget(editor)
        split.addWidget(scroll)
        split.setSizes([240, 760])
        root.addWidget(split, 1)

        self.list.currentTextChanged.connect(self._load)
        self.new_btn.clicked.connect(self._new)
        self.dup_btn.clicked.connect(self._duplicate)
        self.del_btn.clicked.connect(self._delete)
        self.save_btn.clicked.connect(self._save)
        self.engine.currentIndexChanged.connect(self._engine_changed)
        add_spk.clicked.connect(self._add_speaker)
        detect.clicked.connect(self._detect_speakers)
        add_rule.clicked.connect(lambda: self.rules.add_rule())
        rm_rule.clicked.connect(self.rules.remove_selected)
        ctx.engines_changed.connect(lambda _e: self._fill_engines())
        ctx.voices_changed.connect(lambda _e: None)

        self.language.addItems(ctx.adapter.default_language_suggestions())
        self._fill_engines()
        self.reload()

    @staticmethod
    def _ms() -> QSpinBox:
        s = QSpinBox()
        s.setRange(0, 10_000)
        s.setSingleStep(50)
        s.setSuffix(" ms")
        return s

    def _voices(self):
        engine = self.engine.currentData() or "omnivoice"
        self.ctx.load_voices(engine)
        return self.ctx.voices_for(engine)

    def _fill_engines(self) -> None:
        cur = self.engine.currentData()
        self.engine.blockSignals(True)
        self.engine.clear()
        engines = self.ctx.available_engines()
        for e in engines:
            self.engine.addItem(f"{e.label}  [{e.id}]" + ("  ✓ active" if e.is_active else ""), e.id)
        if not engines:
            self.engine.addItem("omnivoice (not connected)", "omnivoice")
        if cur:
            idx = self.engine.findData(cur)
            if idx < 0:
                self.engine.addItem(f"{cur} (unavailable)", cur)
                idx = self.engine.count() - 1
            self.engine.setCurrentIndex(idx)
        self.engine.blockSignals(False)

    # ------------------------------------------------------------- list ops
    def reload(self, select: str | None = None) -> None:
        select = select or (self.list.currentItem().text() if self.list.currentItem() else None)
        self.list.blockSignals(True)
        self.list.clear()
        self.list.addItems(self.ctx.profiles.names())
        self.list.blockSignals(False)
        items = self.list.findItems(select, Qt.MatchFlag.MatchExactly) if select else []
        if items:
            self.list.setCurrentItem(items[0])
        elif self.list.count():
            self.list.setCurrentRow(0)
        self._load(self.list.currentItem().text() if self.list.currentItem() else "")

    def _load(self, name: str) -> None:
        p = self.ctx.profiles.get(name)
        if p is None:
            return
        self._editing = p.name
        self.name.setText(p.name)
        self.desc.setText(p.description)
        idx = self.engine.findData(p.engine)
        if idx < 0:
            self.engine.addItem(f"{p.engine} (unavailable)", p.engine)
            idx = self.engine.count() - 1
        self.engine.blockSignals(True)
        self.engine.setCurrentIndex(idx)
        self.engine.blockSignals(False)
        self.mode.setCurrentIndex(max(0, self.mode.findData(p.mode)))
        self.voice.set_selection(p.voice)
        self.speed.setValue(float(p.params.get("speed") or 1.0))
        self.language.setCurrentText(str(p.params.get("language") or ""))
        self.instruct.setText(str(p.params.get("instruct") or ""))
        self.out_fmt.setCurrentIndex(max(0, self.out_fmt.findData(p.output_format)))
        self.turn_ms.setValue(p.silence.turn_ms)
        self.para_ms.setValue(p.silence.paragraph_ms)
        self.narr_ms.setValue(p.silence.narrator_ms)
        self.sent_ms.setValue(p.silence.sentence_ms)
        self.speakers.set_mapping(p.speaker_voices)
        self.rules.set_rules(p.pronunciation)
        self._build_params(p.params)

    def _engine_changed(self) -> None:
        self._build_params(self.params.values())
        self.ctx.load_voices(self.engine.currentData() or "omnivoice")

    def _build_params(self, values: dict) -> None:
        engine = self.engine.currentData() or "omnivoice"
        caps = self.ctx.capabilities(engine)
        self.params.build(caps, values)
        self.speed.setEnabled(caps.supports("speed"))
        self.language.setEnabled(caps.supports("language"))
        self.instruct.setEnabled(caps.supports("instruct"))
        info = self.ctx.engine(engine)
        notes = [f"Max {caps.max_input_chars} characters per request."]
        if info and not info.supports_emotion:
            notes.append("This engine has no emotion control – use the style instruction instead.")
        if not caps.supports_voice_design:
            notes.append("Designed (archetype) voices are not available for this engine.")
        self.caps_note.setText(" ".join(notes))

    def _collect(self) -> GenerationProfile | None:
        name = self.name.text().strip()
        if not name:
            QMessageBox.warning(self, "Profile", "Please enter a profile name.")
            return None
        engine = self.engine.currentData() or "omnivoice"
        caps = self.ctx.capabilities(engine)
        params = {k: v for k, v in self.params.values().items() if v is not None}
        if caps.supports("speed"):
            params["speed"] = round(self.speed.value(), 2)
        lang = self.language.currentText().strip()
        if lang and caps.supports("language"):
            params["language"] = lang
        if self.instruct.text().strip() and caps.supports("instruct"):
            params["instruct"] = self.instruct.text().strip()
        return GenerationProfile(
            name=name,
            engine=engine,
            mode=self.mode.currentData(),
            voice=self.voice.selection(),
            speaker_voices=self.speakers.mapping(),
            params=params,
            silence=SilenceSettings(self.turn_ms.value(), self.para_ms.value(), self.narr_ms.value(),
                                    self.sent_ms.value()),
            pronunciation=self.rules.rules(),
            output_format=self.out_fmt.currentData(),
            description=self.desc.text().strip(),
        )

    def _save(self) -> None:
        p = self._collect()
        if p is None:
            return
        if p.name != self._editing and self.ctx.profiles.get(p.name):
            QMessageBox.warning(self, "Profile", f"A profile named “{p.name}” already exists.")
            return
        self.ctx.profiles.upsert(p, old_name=self._editing)
        self._editing = p.name
        self.reload(select=p.name)
        self.ctx.profiles_changed.emit()

    def _new(self) -> None:
        name, ok = QInputDialog.getText(self, "New profile", "Profile name:")
        if ok and name.strip():
            p = GenerationProfile(name=self.ctx.profiles.unique_name(name.strip()),
                                  engine=self.engine.currentData() or "omnivoice")
            self.ctx.profiles.upsert(p)
            self.reload(select=p.name)
            self.ctx.profiles_changed.emit()

    def _duplicate(self) -> None:
        if self._editing:
            p = self.ctx.profiles.duplicate(self._editing)
            if p:
                self.reload(select=p.name)
                self.ctx.profiles_changed.emit()

    def _delete(self) -> None:
        if self._editing and QMessageBox.question(
                self, "Delete profile", f"Delete profile “{self._editing}”?") == QMessageBox.StandardButton.Yes:
            self.ctx.profiles.delete(self._editing)
            self._editing = None
            self.reload()
            self.ctx.profiles_changed.emit()

    def _add_speaker(self) -> None:
        name, ok = QInputDialog.getText(self, "Add speaker", "Speaker tag (e.g. ANNA):")
        if ok and name.strip():
            self.speakers.add_speaker(name)

    def _detect_speakers(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Choose a conversation TXT", self.ctx.settings.last_folder,
                                              "Text files (*.txt)")
        if not path:
            return
        try:
            text, _ = read_text_file(Path(path))
        except Exception as e:
            QMessageBox.warning(self, "Detect speakers", str(e))
            return
        found = detect_speakers(text)
        for spk in found:
            self.speakers.add_speaker(spk)
        QMessageBox.information(self, "Detect speakers",
                                f"Found: {', '.join(found)}" if found else "No speaker tags found.")
