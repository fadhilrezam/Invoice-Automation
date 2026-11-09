from __future__ import annotations

import re
from datetime import date, datetime
from pathlib import Path


def parse_iso_date(value: str | None, default: date | None = None) -> date:
    if value:
        try:
            return date.fromisoformat(str(value)[:10])
        except (TypeError, ValueError):
            pass
    return default or date.today()


def date_to_iso(value: date) -> str:
    return value.isoformat()


def parse_date_text(text: str, default: date | None = None) -> date | None:
    text = (text or "").strip()
    if not text:
        return default
    for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y", "%d %B %Y", "%d %b %Y"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return default


def format_date_id(value: date | None, fmt: str = "full") -> str:
    """Format tanggal ke bahasa Indonesia.

    fmt='full'        -> '1 Juli 2026'
    fmt='bulan_tahun' -> 'Juli 2026'
    """
    if value is None:
        return ""
    bulan = (
        "",
        "Januari",
        "Februari",
        "Maret",
        "April",
        "Mei",
        "Juni",
        "Juli",
        "Agustus",
        "September",
        "Oktober",
        "November",
        "Desember",
    )[value.month]
    if fmt == "bulan_tahun":
        return f"{bulan} {value.year}"
    return f"{value.day} {bulan} {value.year}"


def format_rupiah(value: float | int | None) -> str:
    value = int(round(value or 0))
    return f"Rp {value:,.0f}".replace(",", ".")


def format_number(value: float | int | None, decimals: int = 0) -> str:
    if value is None:
        return ""
    if decimals:
        text = f"{value:,.{decimals}f}"
    else:
        text = f"{round(value):,}"
    return text.replace(",", ".")


def sanitize_filename(name: str) -> str:
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "-", str(name or "")).strip()
    name = re.sub(r"\s+", " ", name)
    name = name.rstrip(". ")
    return name or "invoice"


def to_int(value: float | int | None, default: int = 0) -> int:
    if value is None:
        return default
    try:
        return int(round(float(value)))
    except (TypeError, ValueError):
        return default


def unique_path(path: Path) -> Path:
    """Kalau file sudah ada, tambahkan suffix (2), (3), dst."""
    if not path.exists():
        return path
    stem, suffix, parent = path.stem, path.suffix, path.parent
    index = 2
    while True:
        candidate = parent / f"{stem} ({index}){suffix}"
        if not candidate.exists():
            return candidate
        index += 1
