"""Light / dark theme (Fusion style + a small stylesheet)."""
from __future__ import annotations

from PySide6.QtGui import QColor, QFont, QPalette
from PySide6.QtWidgets import QApplication

PALETTES = {
    "light": {
        "bg": "#f4f5f7", "surface": "#ffffff", "surface2": "#f0f2f5", "border": "#dfe3e8",
        "text": "#1f2328", "muted": "#667085", "accent": "#2563eb", "accent_text": "#ffffff",
        "sidebar": "#ffffff", "sidebar_sel": "#e8efff", "danger": "#dc2626", "ok": "#16a34a",
        "warn": "#d97706",
    },
    "dark": {
        "bg": "#1a1c20", "surface": "#23262b", "surface2": "#2b2f35", "border": "#363b42",
        "text": "#e6e8eb", "muted": "#9aa3ad", "accent": "#3b82f6", "accent_text": "#ffffff",
        "sidebar": "#202327", "sidebar_sel": "#2c3a55", "danger": "#ef4444", "ok": "#22c55e",
        "warn": "#f59e0b",
    },
}

STATUS_COLORS = {
    "Pending": "muted", "Processing": "accent", "Completed": "ok",
    "Skipped": "warn", "Failed": "danger", "Cancelled": "muted",
}

_current = "light"


def color(name: str) -> str:
    return PALETTES[_current][name]


def current_theme() -> str:
    return _current


def apply_theme(app: QApplication, theme: str) -> None:
    global _current
    _current = theme if theme in PALETTES else "light"
    c = PALETTES[_current]
    app.setStyle("Fusion")
    font = QFont("Segoe UI", 10)  # full Vietnamese coverage on Windows
    font.setStyleHint(QFont.StyleHint.SansSerif)
    app.setFont(font)
    pal = QPalette()
    pal.setColor(QPalette.ColorRole.Window, QColor(c["bg"]))
    pal.setColor(QPalette.ColorRole.WindowText, QColor(c["text"]))
    pal.setColor(QPalette.ColorRole.Base, QColor(c["surface"]))
    pal.setColor(QPalette.ColorRole.AlternateBase, QColor(c["surface2"]))
    pal.setColor(QPalette.ColorRole.Text, QColor(c["text"]))
    pal.setColor(QPalette.ColorRole.Button, QColor(c["surface"]))
    pal.setColor(QPalette.ColorRole.ButtonText, QColor(c["text"]))
    pal.setColor(QPalette.ColorRole.Highlight, QColor(c["accent"]))
    pal.setColor(QPalette.ColorRole.HighlightedText, QColor(c["accent_text"]))
    pal.setColor(QPalette.ColorRole.ToolTipBase, QColor(c["surface"]))
    pal.setColor(QPalette.ColorRole.ToolTipText, QColor(c["text"]))
    pal.setColor(QPalette.ColorRole.PlaceholderText, QColor(c["muted"]))
    pal.setColor(QPalette.ColorRole.Link, QColor(c["accent"]))
    for role in (QPalette.ColorRole.Text, QPalette.ColorRole.ButtonText, QPalette.ColorRole.WindowText):
        pal.setColor(QPalette.ColorGroup.Disabled, role, QColor(c["muted"]))
    app.setPalette(pal)
    app.setStyleSheet(_stylesheet(c))


def _stylesheet(c: dict[str, str]) -> str:
    return f"""
    QWidget {{ font-size: 10pt; }}
    QToolTip {{ background: {c['surface']}; color: {c['text']}; border: 1px solid {c['border']}; padding: 4px; }}
    #Sidebar {{ background: {c['sidebar']}; border-right: 1px solid {c['border']}; }}
    #Sidebar QListWidget {{ background: transparent; border: none; outline: none; }}
    #Sidebar QListWidget::item {{ padding: 9px 14px; margin: 2px 8px; border-radius: 6px; color: {c['text']}; }}
    #Sidebar QListWidget::item:selected {{ background: {c['sidebar_sel']}; color: {c['accent']}; font-weight: 600; }}
    #Sidebar QListWidget::item:hover:!selected {{ background: {c['surface2']}; }}
    #AppTitle {{ font-size: 12pt; font-weight: 700; padding: 16px 16px 4px 16px; }}
    #AppSubtitle {{ color: {c['muted']}; padding: 0 16px 12px 16px; font-size: 9pt; }}
    #PageTitle {{ font-size: 15pt; font-weight: 600; }}
    #Muted {{ color: {c['muted']}; }}
    #Card {{ background: {c['surface']}; border: 1px solid {c['border']}; border-radius: 10px; }}
    #StatValue {{ font-size: 16pt; font-weight: 600; }}
    QGroupBox {{ background: {c['surface']}; border: 1px solid {c['border']}; border-radius: 8px;
                 margin-top: 14px; padding: 12px 10px 10px 10px; font-weight: 600; }}
    QGroupBox::title {{ subcontrol-origin: margin; left: 12px; padding: 0 4px; }}
    QToolButton {{ background: {c['surface']}; border: 1px solid {c['border']}; border-radius: 6px;
                   padding: 5px 10px; }}
    QToolButton:hover {{ border-color: {c['accent']}; }}
    QToolButton::menu-indicator {{ image: none; width: 0; }}
    QPushButton {{ background: {c['surface']}; border: 1px solid {c['border']}; border-radius: 6px;
                   padding: 5px 12px; min-height: 20px; }}
    QPushButton:hover {{ border-color: {c['accent']}; }}
    QPushButton:disabled {{ color: {c['muted']}; background: {c['surface2']}; }}
    QPushButton#Primary {{ background: {c['accent']}; color: {c['accent_text']}; border-color: {c['accent']}; font-weight: 600; }}
    QPushButton#Primary:disabled {{ background: {c['border']}; border-color: {c['border']}; color: {c['muted']}; }}
    QPushButton#Danger {{ color: {c['danger']}; }}
    QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox, QPlainTextEdit, QTextEdit {{
        background: {c['surface']}; border: 1px solid {c['border']}; border-radius: 6px; padding: 4px 6px; }}
    QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus, QPlainTextEdit:focus {{ border-color: {c['accent']}; }}
    QTableView, QTreeView, QListView {{ background: {c['surface']}; border: 1px solid {c['border']}; border-radius: 8px;
        gridline-color: {c['border']}; selection-background-color: {c['sidebar_sel']}; selection-color: {c['text']}; }}
    QHeaderView::section {{ background: {c['surface2']}; border: none; border-bottom: 1px solid {c['border']};
        padding: 6px; font-weight: 600; }}
    QProgressBar {{ border: 1px solid {c['border']}; border-radius: 6px; background: {c['surface2']};
        text-align: center; min-height: 16px; }}
    QProgressBar::chunk {{ background: {c['accent']}; border-radius: 5px; }}
    QTabWidget::pane {{ border: 1px solid {c['border']}; border-radius: 8px; background: {c['surface']}; }}
    QTabBar::tab {{ padding: 6px 14px; }}
    QTabBar::tab:selected {{ color: {c['accent']}; font-weight: 600; }}
    QScrollArea {{ border: none; background: transparent; }}
    """
