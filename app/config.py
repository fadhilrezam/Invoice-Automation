"""Konfigurasi path aplikasi."""
from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

APP_NAME = "InvoiceAutomation"
APP_TITLE = "Invoice Automation - Pembagian RAB ke Kendaraan"


def app_data_dir() -> Path:
    """Folder data aplikasi. Bisa dioverride lewat env INVOICE_APP_DATA."""
    override = os.environ.get("INVOICE_APP_DATA")
    if override:
        path = Path(override).expanduser()
    elif sys.platform == "win32":
        base = os.environ.get("APPDATA") or str(Path.home())
        path = Path(base) / APP_NAME
    else:
        path = Path.home() / f".{APP_NAME.lower()}"
    path.mkdir(parents=True, exist_ok=True)
    return path


def db_path() -> Path:
    return app_data_dir() / "data.db"


def log_path() -> Path:
    return app_data_dir() / "error.log"


def bundled_template_path() -> Path:
    """Template bawaan yang ikut dipaketkan bersama aplikasi."""
    if getattr(sys, "frozen", False):
        base = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    else:
        base = Path(__file__).resolve().parent
    return base / "resources" / "invoice_template.xlsx"


def user_template_path() -> Path:
    """Salinan template di folder data agar bisa diedit user."""
    target = app_data_dir() / "invoice_template.xlsx"
    if not target.exists():
        source = bundled_template_path()
        if source.exists():
            shutil.copyfile(source, target)
    return target


def default_template_path() -> Path:
    bundled = bundled_template_path()
    user = user_template_path()
    if user.exists():
        return user
    return bundled
