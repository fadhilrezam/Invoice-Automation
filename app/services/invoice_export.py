"""Export invoice per kendaraan berdasarkan invoice_template.xlsx."""
from __future__ import annotations

from copy import copy
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Iterable, Sequence

import openpyxl
from openpyxl import Workbook
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.properties import PageSetupProperties

from ..utils import sanitize_filename, unique_path


class InvoiceExportError(Exception):
    pass


@dataclass
class InvoiceLine:
    name: str
    qty: int
    unit_price: int

    @property
    def amount(self) -> int:
        return int(self.qty) * int(self.unit_price)


@dataclass
class InvoiceData:
    plate: str
    vehicle_type: str
    client_name: str
    client_address: str
    company_name: str
    company_address: str
    po_number: str
    invoice_date: date
    lines: list[InvoiceLine] = field(default_factory=list)
    discount_percent: float = 0.0
    term_name: str = ""
    label: str = ""

    @property
    def subtotal(self) -> int:
        return sum(line.amount for line in self.lines)

    @property
    def discount_amount(self) -> int:
        percent = max(0.0, min(100.0, float(self.discount_percent or 0)))
        return int(round(self.subtotal * percent / 100.0))

    @property
    def total(self) -> int:
        return self.subtotal - self.discount_amount


def _copy_style(src, dst) -> None:
    """Salin style antar-workbook dengan aman.

    Menyalin ``_style`` mentah tidak bisa dipakai lintas workbook karena
    indeks style-nya berbeda. Salin tiap komponen style agar openpyxl
    mendaftarkannya ke workbook tujuan.
    """
    dst.value = src.value
    if not src.has_style:
        return
    dst.font = copy(src.font)
    dst.fill = copy(src.fill)
    dst.border = copy(src.border)
    dst.alignment = copy(src.alignment)
    dst.protection = copy(src.protection)
    dst.number_format = src.number_format


def _clone_block(ws, tpl_ws, rows: range, cols: range) -> None:
    for row in rows:
        for col in cols:
            src = tpl_ws.cell(row=row, column=col)
            dst = ws.cell(row=row, column=col)
            _copy_style(src, dst)


def _clone_row_style(ws, tpl_ws, src_row: int, dst_row: int, cols: range) -> None:
    for col in cols:
        src = tpl_ws.cell(row=src_row, column=col)
        dst = ws.cell(row=dst_row, column=col)
        _copy_style(src, dst)
        dst.value = None


def _set_style_only(ws, tpl_ws, coord: str, dst_coord: str) -> None:
    src = tpl_ws[coord]
    dst = ws[dst_coord]
    _copy_style(src, dst)


def _unique_sheet_name(wb: Workbook, desired: str) -> str:
    cleaned = "".join(
        ch for ch in str(desired or "Invoice") if ch not in '[]:*?/\\'
    ).strip()
    cleaned = cleaned[:31] or "Invoice"
    name = cleaned
    index = 2
    while name in wb.sheetnames:
        suffix = f" {index}"
        name = cleaned[: 31 - len(suffix)] + suffix
        index += 1
    return name


def _valid_template(tpl_ws) -> bool:
    try:
        return (
            str(tpl_ws["A10"].value or "").strip().lower() == "qty"
            and str(tpl_ws["B10"].value or "").strip().lower() == "nama barang"
        )
    except Exception:
        return False


def build_invoice_workbook(
    template_path: str | Path,
    invoice: InvoiceData,
    workbook: Workbook | None = None,
    sheet_name: str | None = None,
) -> Workbook:
    """Bangun workbook invoice dengan layout & style dari template."""
    template_path = Path(template_path)
    if not template_path.exists():
        raise InvoiceExportError(
            f"Template invoice tidak ditemukan: {template_path}"
        )
    try:
        tpl_wb = openpyxl.load_workbook(str(template_path), data_only=False)
    except Exception as exc:  # noqa: BLE001
        raise InvoiceExportError(f"Template tidak bisa dibuka: {exc}") from exc

    tpl_ws = tpl_wb.worksheets[0]
    if not _valid_template(tpl_ws):
        raise InvoiceExportError(
            "Template invoice tidak sesuai. Pastikan baris 10 berisi header "
            "'Qty' dan 'Nama Barang'."
        )

    if workbook is None:
        wb = Workbook()
        default = wb.active
        wb.remove(default)
    else:
        wb = workbook

    title = _unique_sheet_name(wb, sheet_name or invoice.label or invoice.plate or "Invoice")
    ws = wb.create_sheet(title=title)

    # Lebar kolom & tinggi baris
    for key, dim in tpl_ws.column_dimensions.items():
        if dim.width:
            ws.column_dimensions[key].width = dim.width
    for row in range(1, 11):
        height = tpl_ws.row_dimensions[row].height
        if height:
            ws.row_dimensions[row].height = height

    # Salin area header (baris 1-10) termasuk merge
    _clone_block(ws, tpl_ws, range(1, 11), range(1, 6))
    for merged in tpl_ws.merged_cells.ranges:
        if merged.min_row <= 10 and merged.max_row <= 10:
            ws.merge_cells(str(merged))

    # Isi header
    invoice_date = invoice.invoice_date
    if isinstance(invoice_date, date) and not isinstance(invoice_date, datetime):
        invoice_date = datetime(invoice_date.year, invoice_date.month, invoice_date.day)

    ws["A1"] = "INVOICE"
    ws["C1"] = invoice.company_name or "CV. PANJI PERKASA"
    ws["C2"] = invoice.company_address or ""
    ws["B4"] = invoice.po_number
    ws["B5"] = invoice_date
    ws["D4"] = invoice.client_name
    ws["D5"] = invoice.client_address
    ws["D6"] = invoice.plate
    ws["D7"] = invoice.vehicle_type

    # Tabel item
    lines = invoice.lines or []
    first_row = 11
    for index, line in enumerate(lines):
        row = first_row + index
        _clone_row_style(ws, tpl_ws, 11, row, range(1, 5))
        ws.cell(row=row, column=1, value=int(line.qty))
        ws.cell(row=row, column=2, value=line.name)
        ws.cell(row=row, column=3, value=int(line.unit_price))
        ws.cell(row=row, column=4, value=line.amount)
        height = tpl_ws.row_dimensions[11].height
        ws.row_dimensions[row].height = height or 15

    subtotal_row = first_row + len(lines)
    discount_row = subtotal_row + 1
    total_row = subtotal_row + 2

    # Sub total
    _clone_row_style(ws, tpl_ws, 21, subtotal_row, range(1, 5))
    _set_style_only(ws, tpl_ws, "A21", f"A{subtotal_row}")
    ws[f"A{subtotal_row}"] = "* harga sudah termasuk pajak"
    ws[f"C{subtotal_row}"] = "Sub Total"
    ws[f"D{subtotal_row}"] = invoice.subtotal

    # Diskon (%)
    _clone_row_style(ws, tpl_ws, 22, discount_row, range(1, 5))
    ws[f"C{discount_row}"] = "Disc %"
    if invoice.discount_percent:
        ws[f"D{discount_row}"] = float(invoice.discount_percent)
    else:
        ws[f"D{discount_row}"] = None

    # Total
    _clone_row_style(ws, tpl_ws, 23, total_row, range(1, 5))
    ws[f"C{total_row}"] = "TOTAL"
    ws[f"D{total_row}"] = invoice.total

    # Footer tanda tangan
    signature_row = total_row + 3
    company_row = total_row + 6
    for src_row, dst_row, text in (
        (26, signature_row, "Hormat Kami,"),
        (29, company_row, invoice.company_name or "CV. PANJI PERKASA"),
    ):
        _clone_row_style(ws, tpl_ws, src_row, dst_row, range(3, 5))
        ws.merge_cells(
            start_row=dst_row, start_column=3, end_row=dst_row, end_column=4
        )
        ws.cell(row=dst_row, column=3, value=text)

    # Print setup
    try:
        ws.page_margins = copy(tpl_ws.page_margins)
    except Exception:
        pass
    ws.sheet_properties.pageSetUpPr = PageSetupProperties(fitToPage=True)
    ws.page_setup.orientation = "portrait"
    ws.page_setup.fitToWidth = 1
    ws.page_setup.fitToHeight = 0
    ws.print_area = f"A1:D{company_row}"

    tpl_wb.close()
    return wb


def invoice_filename(invoice: InvoiceData) -> str:
    term = sanitize_filename(invoice.term_name or "Termin")
    plate = sanitize_filename(invoice.label or invoice.plate or "Kendaraan")
    return f"Invoice {term} - {plate}.xlsx"


def export_invoices(
    template_path: str | Path,
    invoices: Sequence[InvoiceData],
    output_dir: str | Path,
    *,
    mode: str = "files",
    overwrite: bool = False,
) -> list[Path]:
    """Export invoice.

    mode='files'    : satu file Excel per kendaraan
    mode='workbook' : satu workbook, satu sheet per kendaraan
    """
    if not invoices:
        raise InvoiceExportError("Tidak ada invoice yang akan diekspor.")
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)

    if mode == "workbook":
        wb = Workbook()
        wb.remove(wb.active)
        for invoice in invoices:
            build_invoice_workbook(
                template_path,
                invoice,
                workbook=wb,
                sheet_name=invoice.label or invoice.plate,
            )
        term_name = sanitize_filename(invoices[0].term_name or "Termin")
        path = output / f"Invoice {term_name} - Semua Kendaraan.xlsx"
        if not overwrite:
            path = unique_path(path)
        try:
            wb.save(path)
        except Exception as exc:  # noqa: BLE001
            raise InvoiceExportError(f"Gagal menyimpan workbook: {exc}") from exc
        return [path]

    paths: list[Path] = []
    for invoice in invoices:
        wb = build_invoice_workbook(template_path, invoice)
        path = output / invoice_filename(invoice)
        if not overwrite:
            path = unique_path(path)
        try:
            wb.save(path)
        except Exception as exc:  # noqa: BLE001
            raise InvoiceExportError(
                f"Gagal menyimpan invoice {invoice.label or invoice.plate}: {exc}"
            ) from exc
        paths.append(path)
    return paths
