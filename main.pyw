from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QFont, QPainter, QPixmap, QColor
from PySide6.QtWidgets import QApplication, QSplashScreen

from core.reporting import SOFTWARE_VERSION, REPORT_SCHEMA_VERSION


def _create_splash() -> QSplashScreen:
    """Create a compact branded startup screen using the bundled application logo."""
    pixmap = QPixmap(620, 320)
    pixmap.fill(QColor("#101820"))
    painter = QPainter(pixmap)
    try:
        logo_path = Path(__file__).resolve().parent / "resources" / "godas_logo.png"
        if logo_path.exists():
            logo = QPixmap(str(logo_path)).scaled(108, 108, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
            painter.drawPixmap(42, 54, logo)

        painter.setPen(QColor("#ffffff"))
        title_font = QFont("Segoe UI", 24, QFont.Weight.Bold)
        painter.setFont(title_font)
        painter.drawText(175, 92, "GODAS")

        product_font = QFont("Segoe UI", 18, QFont.Weight.DemiBold)
        painter.setFont(product_font)
        painter.setPen(QColor("#d9e7f0"))
        painter.drawText(175, 126, "Regional Data Tool")

        small_font = QFont("Segoe UI", 10)
        painter.setFont(small_font)
        painter.setPen(QColor("#aebfca"))
        painter.drawText(175, 158, f"Version {SOFTWARE_VERSION}   |   Report Schema {REPORT_SCHEMA_VERSION}")
        painter.drawText(175, 182, "Regional ocean data • analysis • visualization • reproducible outputs")

        painter.setPen(QColor("#7f9aaa"))
        painter.drawText(42, 270, "Starting application …")
        painter.drawText(42, 294, "Loading scientific modules and user interface")
    finally:
        painter.end()

    splash = QSplashScreen(pixmap, Qt.WindowType.SplashScreen | Qt.WindowType.FramelessWindowHint)
    splash.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, False)
    return splash


def _launch_without_console() -> bool:
    """On Windows, relaunch through pythonw so a console window disappears immediately."""
    if os.name != "nt" or os.environ.get("GODAS_GUI_CHILD") == "1":
        return False

    exe = Path(sys.executable)
    if exe.name.lower() != "python.exe":
        return False

    pythonw = exe.with_name("pythonw.exe")
    script = Path(__file__).resolve()
    if not pythonw.exists():
        return False

    env = os.environ.copy()
    env["GODAS_GUI_CHILD"] = "1"
    flags = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) | getattr(subprocess, "CREATE_NO_WINDOW", 0)
    subprocess.Popen([str(pythonw), str(script)], env=env, creationflags=flags, close_fds=True)
    return True


def _run_gui() -> int:
    app = QApplication(sys.argv)
    app.setStyle("Fusion")

    # Show the branded splash before importing/building the heavier main-window module.
    # This removes the visible startup gap after the console handoff.
    splash = _create_splash()
    splash.show()
    app.processEvents()
    splash_started = time.monotonic()

    from gui.main_window import MainWindow

    window = MainWindow()
    # Start the application maximized for the intended full-workspace desktop layout.
    window.showMaximized()
    window.raise_()
    window.activateWindow()
    app.processEvents()

    # Keep the branded splash visible for about 3.0 seconds total, while allowing
    # the main window to finish constructing underneath it.
    remaining_ms = max(0, int(3000 - (time.monotonic() - splash_started) * 1000))
    QTimer.singleShot(remaining_ms, lambda: splash.finish(window))
    return app.exec()


if __name__ == "__main__":
    if _launch_without_console():
        raise SystemExit(0)
    raise SystemExit(_run_gui())
