"""Entry point aplikasi Invoice Automation."""
from __future__ import annotations

import sys
import traceback
from datetime import datetime

from PySide6.QtWidgets import QApplication, QMessageBox

from app.config import APP_TITLE, db_path, log_path
from app.db import Database
from app.ui.main_window import MainWindow
from app.ui.style import APP_STYLESHEET, app_icon


def _install_excepthook() -> None:
    def handle(exc_type, exc_value, exc_tb):
        text = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
        try:
            with open(log_path(), "a", encoding="utf-8") as handle_file:
                handle_file.write(f"\n[{datetime.now():%Y-%m-%d %H:%M:%S}]\n{text}\n")
        except Exception:
            pass
        try:
            QMessageBox.critical(
                None,
                "Terjadi kesalahan",
                "Aplikasi mengalami kesalahan tak terduga.\n\n"
                f"{exc_value}\n\nDetail disimpan di:\n{log_path()}",
            )
        except Exception:
            pass

    sys.excepthook = handle


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("Invoice Automation")
    app.setApplicationDisplayName(APP_TITLE)
    app.setOrganizationName("InvoiceAutomation")
    app.setStyle("Fusion")
    app.setStyleSheet(APP_STYLESHEET)
    app.setWindowIcon(app_icon())
    _install_excepthook()

    db = Database(db_path())
    window = MainWindow(db)
    window.show()
    exit_code = app.exec()
    db.close()
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
