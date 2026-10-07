# PyInstaller spec – build with:  pyinstaller --noconfirm AudioStudioBatchTTS.spec
# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path

ROOT = Path(SPECPATH)

a = Analysis(
    [str(ROOT / "main.py")],
    pathex=[str(ROOT)],
    datas=[(str(ROOT / "app" / "resources"), "app/resources")],
    hiddenimports=["PySide6.QtMultimedia"],
    excludes=["tkinter", "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets", "PySide6.Qt3DCore",
              "PySide6.QtQuick", "PySide6.QtQml", "PySide6.QtPdf", "PySide6.QtCharts", "PySide6.QtDataVisualization"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="AudioStudioBatchTTS",
    icon=str(ROOT / "app" / "resources" / "icon.ico"),
    console=False,
    upx=False,
    version=None,
)
