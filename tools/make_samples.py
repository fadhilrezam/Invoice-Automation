"""Buat file contoh RAB dan daftar kendaraan (data dummy)."""
from __future__ import annotations

from pathlib import Path

import openpyxl
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "sample"

ITEMS = [
    ("Service", "unit", 240_000, [5, 5, 5, 5]),
    ("Oli Mesin", "liter", 100_000, [5, 5, 5, 5]),
    ("Kampas Rem Depan", "set", 100_000, [2, 2, 2, 2]),
    ("Kampas Rem Belakang", "set", 100_000, [2, 2, 2, 2]),
    ("Kampas Kopling", "set", 330_000, [1, 1, 1, 1]),
    ("Bohlam Depan", "pcs", 65_000, [2, 2, 1, 1]),
    ("Bohlam Belakang", "pcs", 20_000, [1, 2, 1, 2]),
    ("Busi", "pcs", 30_000, [3, 3, 2, 2]),
    ("Filter Udara", "pcs", 70_000, [2, 2, 1, 1]),
    ("Lager Roda Belakang", "pcs", 113_000, [0, 1, 1, 2]),
    ("Rantai & Gir", "set", 250_000, [0, 1, 1, 1]),
    ("Air Radiator", "liter", 35_000, [1, 1, 2, 1]),
]

VEHICLES = [
    ("D 1001 ABC", "Yamaha Vixion"),
    ("D 1002 ABC", "Yamaha Vixion"),
    ("D 1003 ABC", "Yamaha Vixion"),
    ("D 1004 ABC", "Yamaha Vixion"),
    ("D 1005 ABC", "Yamaha Vixion"),
]

THIN = Side(style="thin", color="D9D9D9")
BORDER = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)
HEAD_FILL = PatternFill("solid", fgColor="C0392B")
HEAD_FONT = Font(name="Arial", size=10, bold=True, color="FFFFFF")


def build_rab() -> Path:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "RAB"
    ws["A1"] = "RAB PEMELIHARAAN KENDARAAN - CONTOH"
    ws["A1"].font = Font(name="Arial", size=14, bold=True)
    ws["A2"] = "Proyek: Pemeliharaan Kendaraan Dinas"
    ws["A3"] = "Format: No | Nama Barang | Satuan | Harga Satuan | Qty Total | Termin 1..4"

    headers = [
        "No",
        "Nama Barang",
        "Satuan",
        "Harga Satuan",
        "Qty Total",
        "Termin 1",
        "Termin 2",
        "Termin 3",
        "Termin 4",
    ]
    header_row = 5
    for index, header in enumerate(headers, start=1):
        cell = ws.cell(row=header_row, column=index, value=header)
        cell.font = HEAD_FONT
        cell.fill = HEAD_FILL
        cell.alignment = Alignment(horizontal="center", vertical="center")
        cell.border = BORDER

    for index, (name, unit, price, terms) in enumerate(ITEMS, start=1):
        row = header_row + index
        values = [index, name, unit, price, sum(terms), *terms]
        for col, value in enumerate(values, start=1):
            cell = ws.cell(row=row, column=col, value=value)
            cell.font = Font(name="Arial", size=10)
            cell.border = BORDER
            if col == 4:
                cell.number_format = '#,##0'
            if col >= 5:
                cell.alignment = Alignment(horizontal="right")

    total_row = header_row + len(ITEMS) + 1
    ws.cell(row=total_row, column=2, value="TOTAL").font = Font(bold=True)
    ws.cell(row=total_row, column=5, value=sum(sum(t) for _n, _u, _p, t in ITEMS))
    widths = {"A": 5, "B": 28, "C": 10, "D": 15, "E": 10, "F": 10, "G": 10, "H": 10, "I": 10}
    for col, width in widths.items():
        ws.column_dimensions[col].width = width
    ws.freeze_panes = "A6"

    OUT.mkdir(exist_ok=True)
    path = OUT / "rab_sample.xlsx"
    wb.save(path)
    return path


def build_vehicles() -> Path:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Kendaraan"
    ws["A1"] = "Daftar Kendaraan - Contoh"
    ws["A1"].font = Font(size=14, bold=True)
    ws["A3"] = "No"
    ws["B3"] = "No Kendaraan"
    ws["C3"] = "Tipe Kendaraan"
    for col in ("A", "B", "C"):
        ws[f"{col}3"].font = HEAD_FONT
        ws[f"{col}3"].fill = HEAD_FILL
        ws[f"{col}3"].border = BORDER
        ws[f"{col}3"].alignment = Alignment(horizontal="center")
    for index, (plate, vehicle_type) in enumerate(VEHICLES, start=1):
        row = 3 + index
        ws.cell(row=row, column=1, value=index).border = BORDER
        ws.cell(row=row, column=2, value=plate).border = BORDER
        ws.cell(row=row, column=3, value=vehicle_type).border = BORDER
    ws.column_dimensions["A"].width = 5
    ws.column_dimensions["B"].width = 22
    ws.column_dimensions["C"].width = 24

    OUT.mkdir(exist_ok=True)
    path = OUT / "kendaraan_sample.xlsx"
    wb.save(path)
    return path


if __name__ == "__main__":
    print(build_rab())
    print(build_vehicles())
