"""Application bootstrap."""
from __future__ import annotations

import logging
import sys
import traceback

from app.utils.logger import setup_logging
from app.version import APP_ID, APP_NAME, APP_VERSION


def run() -> int:
    setup_logging()
    log = logging.getLogger("app")
    log.info("%s %s starting", APP_NAME, APP_VERSION)

    import os

    from app.core.settings import load_settings

    scale = load_settings().ui_scale
    if scale and abs(scale - 1.0) > 0.01 and "QT_SCALE_FACTOR" not in os.environ:
        os.environ["QT_SCALE_FACTOR"] = f"{scale:.2f}"

    from PySide6.QtCore import Qt
    from PySide6.QtGui import QGuiApplication, QIcon
    from PySide6.QtWidgets import QApplication, QMessageBox

    QGuiApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    if sys.platform == "win32":
        try:  # own taskbar icon instead of python.exe's
            import ctypes

            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_ID)
        except Exception:
            pass

    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setOrganizationName(APP_ID)
    app.setApplicationVersion(APP_VERSION)

    from app.ui.main_window import MainWindow
    from app.utils.paths import resource_dir

    icon_path = resource_dir() / "icon.png"
    if icon_path.exists():
        app.setWindowIcon(QIcon(str(icon_path)))

    def excepthook(exc_type, exc, tb):  # never die silently
        log.critical("Unhandled exception:\n%s", "".join(traceback.format_exception(exc_type, exc, tb)))
        QMessageBox.critical(None, APP_NAME, f"Unexpected error:\n{exc}\n\nDetails were written to the log.")

    sys.excepthook = excepthook

    window = MainWindow()
    window.show()
    window.after_show()
    return app.exec()
