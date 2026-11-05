"""Parser daftar kendaraan dari Excel."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import openpyxl

PLATE_KEYS = (
    "plat",
    "nopol",
    "nomor polisi",
    "no polisi",
    "nomor kendaraan",
    "no kendaraan",
    "no. kendaraan",
    "plate",
)
TYPE_KEYS = ("tipe", "jenis", "model", "merk", "merek")


class VehicleParseError(Exception):
    pass


@dataclass
class VehicleParseResult:
    vehicles: list[tuple[str, str]] = field(default_factory=list)
    issues: list[str] = field(default_factory=list)
    sheet: str = ""
    header_row: int = 0


def _norm(text) -> str:
    return re.sub(r"\s+", " ", str(text or "").strip().lower())


def _cell(ws, row: int, col: int) -> str:
    value = ws.cell(row=row, column=col).value
    if value is None:
        return ""
    return str(value).strip()


def _find_header(ws) -> tuple[int, int | None, int | None]:
    """Return (header_row, plate_col, type_col)."""
    for row in range(1, min(ws.max_row or 1, 30) + 1):
        plate_col = None
        type_col = None
        for col in range(1, min(ws.max_column or 1, 30) + 1):
            text = _norm(_cell(ws, row, col))
            if not text:
                continue
            if plate_col is None and (
                any(key in text for key in PLATE_KEYS) or text == "kendaraan"
            ):
                plate_col = col
            elif type_col is None and any(key in text for key in TYPE_KEYS):
                type_col = col
        if plate_col is not None:
            return row, plate_col, type_col
    return 0, None, None


def parse_vehicle_file(path: str | Path) -> VehicleParseResult:
    try:
        wb = openpyxl.load_workbook(str(path), data_only=True, read_only=True)
    except Exception as exc:  # noqa: BLE001
        raise VehicleParseError(f"File tidak bisa dibuka: {exc}") from exc

    try:
        ws = wb.active
        result = VehicleParseResult(sheet=ws.title)
        header_row, plate_col, type_col = _find_header(ws)

        if plate_col is None:
            # Tanpa header: pakai kolom pertama yang berisi data, kolom kedua = tipe
            plate_col = 1
            for col in range(1, min(ws.max_column or 1, 10) + 1):
                has_data = any(
                    _cell(ws, row, col)
                    for row in range(1, min(ws.max_row or 1, 10) + 1)
                )
                if has_data:
                    plate_col = col
                    break
            type_col = plate_col + 1 if (ws.max_column or 1) >= plate_col + 1 else None
            header_row = 0
            result.issues.append(
                "Header tidak terdeteksi; kolom pertama dibaca sebagai nomor kendaraan "
                "dan kolom kedua sebagai tipe."
            )
        else:
            result.header_row = header_row

        seen: set[str] = set()
        for row in range(header_row + 1, (ws.max_row or 0) + 1):
            plate = _cell(ws, row, plate_col)
            if not plate:
                continue
            if _norm(plate) in ("total", "jumlah", "subtotal", "kendaraan"):
                continue
            vehicle_type = _cell(ws, row, type_col) if type_col else ""
            key = plate.upper()
            if key in seen:
                result.issues.append(f"Baris {row}: nomor kendaraan duplikat ({plate}) dilewati.")
                continue
            seen.add(key)
            result.vehicles.append((plate, vehicle_type))

        if not result.vehicles:
            raise VehicleParseError(
                "Tidak ada nomor kendaraan yang terbaca. Pastikan ada kolom "
                "'No Kendaraan'/'Plat' dan data di bawahnya."
            )
        return result
    finally:
        wb.close()
