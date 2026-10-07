"""Global pronunciation dictionary."""
from __future__ import annotations

from PySide6.QtWidgets import QHBoxLayout, QLabel, QLineEdit, QPushButton, QVBoxLayout, QWidget

from app.core.pronunciation import apply_rules
from app.ui.context import AppContext
from app.ui.pages.profiles_page import RulesTable
from app.ui.widgets import Card, muted, page_header, primary


class PronunciationPage(QWidget):
    def __init__(self, ctx: AppContext, parent=None) -> None:
        super().__init__(parent)
        self.ctx = ctx
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 16)
        root.addWidget(page_header(
            "Pronunciation",
            "Global replacement rules applied to every script before it is sent to AudioStudio "
            "(profiles can add their own rules). Your TXT files are never modified."))
        self.table = RulesTable()
        root.addWidget(self.table, 1)
        row = QHBoxLayout()
        add = QPushButton("Add rule")
        rm = QPushButton("Remove selected")
        save = primary("Save rules")
        row.addWidget(add)
        row.addWidget(rm)
        row.addStretch(1)
        row.addWidget(save)
        root.addLayout(row)

        test = Card()
        test.lay.addWidget(QLabel("Test"))
        self.test_in = QLineEdit("WSC and EC students joined PECC1.")
        self.test_out = muted("")
        test.lay.addWidget(self.test_in)
        test.lay.addWidget(self.test_out)
        root.addWidget(test)

        add.clicked.connect(lambda: self.table.add_rule())
        rm.clicked.connect(self.table.remove_selected)
        save.clicked.connect(self._save)
        self.test_in.textChanged.connect(self._test)
        self.table.itemChanged.connect(lambda _i: self._test())
        self.table.set_rules(ctx.pronunciation.rules)
        self._test()

    def _save(self) -> None:
        self.ctx.pronunciation.rules = self.table.rules()
        self.ctx.pronunciation.save()
        self._test()

    def _test(self) -> None:
        self.test_out.setText("→ " + apply_rules(self.test_in.text(), self.table.rules()))
