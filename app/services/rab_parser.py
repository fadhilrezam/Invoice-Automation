"""Parser Excel RAB yang fleksibel.

Format RAB tidak dikunci mati: aplikasi mendeteksi header secara otomatis,
lalu user bisa mengoreksi pemetaan kolom lewat dialog.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

import openpyxl
from openpyxl.utils import get_column_letter

from ..models import ParsedGroup, ParsedItem

ROLE_IGNORE = "ignore"
ROLE_NAME = "name"
ROLE_UNIT = "unit"
ROLE_PRICE = "price"
ROLE_TOTAL_QTY = "total_qty"
ROLE_TERM = "term"

ROLE_LABELS = {
    ROLE_IGNORE: "Abaikan",
    ROLE_NAME: "Nama Barang",
    ROLE_UNIT: "Satuan",
    ROLE_PRICE: "Harga Satuan",
    ROLE_TOTAL_QTY: "Qty Total",
    ROLE_TERM: "Termin",
}

TERM_RE = re.compile(
    r"^(?:qty\s+)?(?:termin|term|tahap|bap|pembayaran)\s*(?:ke\s*)?[-:#.]?\s*"
    r"(\d+|[ivxlcdm]+)\b",
    re.IGNORECASE,
)
ROMAN_RE = re.compile(r"^[ivxlcdm]+$", re.IGNORECASE)
ROMAN_MAP = {"i": 1, "v": 5, "x": 10, "l": 50, "c": 100, "d": 500, "m": 1000}

NAME_KEYS = ("nama barang", "uraian", "deskripsi", "pekerjaan", "item", "barang")
UNIT_KEYS = ("satuan", "unit", "uom")
PRICE_KEYS = ("harga satuan", "harga", "unit price", "harga unit")
QTY_KEYS = ("qty", "quantity", "volume", "jumlah", "banyak")
AMOUNT_KEYS = (
    "jumlah harga",
    "total harga",
    "jumlah biaya",
    "amount",
    "nilai",
    "subtotal",
    "biaya",
)
SUMMARY_RE = re.compile(
    r"^(sub\s*total|subtotal|total|grand\s*total|jumlah|ppn|pajak|"
    r"catatan|keterangan|rekap|ringkasan|biaya\s+lain)\b",
    re.IGNORECASE,
)
SECTION_RE = re.compile(
    r"^(?P<name>.+?)\s*\(?\s*(?P<count>\d+)\s*unit\s*\)?\s*$",
    re.IGNORECASE,
)


class RabParseError(Exception):
    pass


@dataclass
class MappedColumn:
    col: int
    role: str = ROLE_IGNORE
    term_name: str = ""


@dataclass
class RabMapping:
    sheet: str
    header_row: int
    columns: list[MappedColumn]
    single_term_name: str = "Termin 1"

    def by_role(self, role: str) -> list[MappedColumn]:
        return [c for c in self.columns if c.role == role]

    def first(self, role: str) -> MappedColumn | None:
        found = self.by_role(role)
        return found[0] if found else None

    def terms(self) -> list[MappedColumn]:
        return sorted(self.by_role(ROLE_TERM), key=lambda c: c.col)

    def validate(self) -> str | None:
        if not self.first(ROLE_NAME):
            return "Pilih satu kolom untuk Nama Barang."
        if not self.first(ROLE_PRICE):
            return "Pilih satu kolom untuk Harga Satuan."
        if not self.first(ROLE_TOTAL_QTY) and not self.terms():
            return "Pilih minimal satu kolom Termin atau satu kolom Qty Total."
        for role, label in (
            (ROLE_NAME, "Nama Barang"),
            (ROLE_PRICE, "Harga Satuan"),
            (ROLE_UNIT, "Satuan"),
            (ROLE_TOTAL_QTY, "Qty Total"),
        ):
            if len(self.by_role(role)) > 1:
                return f"Kolom {label} hanya boleh dipilih satu."
        names = [c.term_name.strip() for c in self.terms()]
        if any(not n for n in names):
            return "Nama termin tidak boleh kosong."
        if len(names) != len(set(names)):
            return "Nama termin tidak boleh sama."
        return None


@dataclass
class ParseResult:
    groups: list[ParsedGroup] = field(default_factory=list)
    term_names: list[str] = field(default_factory=list)
    issues: list[str] = field(default_factory=list)
    decimal_rows: list[int] = field(default_factory=list)
    skipped_rows: list[int] = field(default_factory=list)

    @property
    def items(self) -> list[ParsedItem]:
        return [item for group in self.groups for item in group.items]

    @property
    def is_grouped(self) -> bool:
        return len(self.groups) > 1 or (
            bool(self.groups) and self.groups[0].unit_count > 0
        )


def normalize_header(text) -> str:
    return re.sub(r"\s+", " ", str(text or "").strip().lower())


def roman_to_int(text: str) -> int:
    text = text.lower()
    total = 0
    prev = 0
    for ch in reversed(text):
        value = ROMAN_MAP.get(ch, 0)
        if value < prev:
            total -= value
        else:
            total += value
            prev = value
    return total


def term_label_from_header(text: str) -> str | None:
    raw = str(text or "").strip()
    match = TERM_RE.match(raw)
    if not match:
        return None
    token = match.group(1)
    number = roman_to_int(token) if ROMAN_RE.match(token) else int(token)
    return f"Termin {number}"


def classify_header(text) -> tuple[str, str]:
    """Kembalikan (role, nama termin)."""
    raw = str(text or "").strip()
    h = normalize_header(raw)
    if not h:
        return ROLE_IGNORE, ""
    if any(key in h for key in AMOUNT_KEYS):
        return ROLE_IGNORE, ""
    label = term_label_from_header(raw)
    if label:
        return ROLE_TERM, label
    if any(key in h for key in PRICE_KEYS):
        return ROLE_PRICE, ""
    if h in ("no", "nomor", "no.", "#", "urut"):
        return ROLE_IGNORE, ""
    if any(key in h for key in NAME_KEYS):
        return ROLE_NAME, ""
    if any(key in h for key in UNIT_KEYS):
        return ROLE_UNIT, ""
    if any(key in h for key in QTY_KEYS):
        return ROLE_TOTAL_QTY, ""
    return ROLE_IGNORE, ""


def cell_text(ws, row: int, col: int) -> str:
    value = ws.cell(row=row, column=col).value
    if value is None:
        return ""
    return str(value).strip()


def _merged_anchor_value(ws, row: int, col: int):
    """Nilai sel di titik jangkar merge yang mencakup (row, col)."""
    for merged in ws.merged_cells.ranges:
        if (
            merged.min_row <= row <= merged.max_row
            and merged.min_col <= col <= merged.max_col
        ):
            return ws.cell(merged.min_row, merged.min_col).value
    return ws.cell(row=row, column=col).value


def _base_header_text(ws, header_row: int, col: int) -> str:
    """Header baris yang dipilih; kosong bila sel adalah lanjutan merge vertikal."""
    for merged in ws.merged_cells.ranges:
        if (
            merged.min_row <= header_row <= merged.max_row
            and merged.min_col <= col <= merged.max_col
        ):
            if merged.min_row < header_row:
                return ""
            break
    value = ws.cell(row=header_row, column=col).value
    return "" if value is None else str(value).strip()


def _parent_header_text(ws, header_row: int, col: int) -> str:
    if header_row <= 1:
        return ""
    value = _merged_anchor_value(ws, header_row - 1, col)
    return "" if value is None else str(value).strip()


def header_text(ws, header_row: int, col: int) -> str:
    """Teks header gabungan untuk tampilan dialog pemetaan."""
    base = _base_header_text(ws, header_row, col)
    parent = _parent_header_text(ws, header_row, col)
    if parent and base and normalize_header(parent) != normalize_header(base):
        return f"{parent} — {base}"
    return base or parent


def _classify_grouped(parent: str, base: str) -> tuple[str, str]:
    parent_term = term_label_from_header(parent)
    if parent_term:
        text = normalize_header(base)
        if any(key in text for key in ("volume", "qty", "quantity")):
            return ROLE_TERM, parent_term
        return ROLE_IGNORE, ""
    return classify_header(base or parent)


def detect_grouped_columns(
    ws, header_row: int
) -> list[MappedColumn] | None:
    """Deteksi header dua tingkat: grup TERMIN di atas kolom VOLUME.

    Format contoh: baris 1 berisi ``TERMIN 1`` (merge H:J), baris 2 berisi
    ``VOLUME / HARGA SATUAN / JUMLAH BIAYA``.
    """
    if header_row < 2:
        return None
    max_col = min(ws.max_column or 0, 100)
    base_texts = [
        normalize_header(_base_header_text(ws, header_row, col))
        for col in range(1, max_col + 1)
    ]
    parents = [
        _parent_header_text(ws, header_row, col)
        for col in range(1, max_col + 1)
    ]
    if not any(text == "satuan" for text in base_texts):
        return None
    if not any("harga satuan" in text for text in base_texts):
        return None
    if not any("volume" in text or "qty" in text for text in base_texts):
        return None
    if not any(term_label_from_header(parent) for parent in parents):
        return None

    columns: list[MappedColumn] = []
    for col in range(1, max_col + 1):
        role, term_name = _classify_grouped(
            _parent_header_text(ws, header_row, col),
            _base_header_text(ws, header_row, col),
        )
        columns.append(MappedColumn(col=col, role=role, term_name=term_name))
    roles = [column.role for column in columns]
    if (
        ROLE_NAME not in roles
        or ROLE_PRICE not in roles
        or (ROLE_TOTAL_QTY not in roles and ROLE_TERM not in roles)
    ):
        return None
    if len([c for c in columns if c.role == ROLE_PRICE]) > 1:
        return None
    return columns


def detect_columns(ws, header_row: int) -> list[MappedColumn]:
    grouped = detect_grouped_columns(ws, header_row)
    if grouped is not None:
        return grouped
    columns: list[MappedColumn] = []
    max_col = min(ws.max_column or 0, 100)
    for col in range(1, max_col + 1):
        role, term_name = classify_header(cell_text(ws, header_row, col))
        columns.append(MappedColumn(col=col, role=role, term_name=term_name))
    return columns


def detect_best_header(ws, max_scan: int = 40) -> tuple[int, list[MappedColumn]]:
    best_row = 1
    best_score = -1
    best_columns: list[MappedColumn] = []
    for row in range(1, min(ws.max_row or 1, max_scan) + 1):
        columns = detect_columns(ws, row)
        roles = [c.role for c in columns]
        term_count = roles.count(ROLE_TERM)
        has_name = ROLE_NAME in roles
        has_price = ROLE_PRICE in roles
        has_qty = ROLE_TOTAL_QTY in roles
        if not (has_name and has_price and (term_count or has_qty)):
            continue
        score = 10 + term_count * 4 + (3 if has_qty else 0)
        if ROLE_UNIT in roles:
            score += 1
        if score > best_score:
            best_score = score
            best_row = row
            best_columns = columns
    if best_score < 0:
        # Kembalikan baris pertama yang punya teks agar user tetap bisa mapping manual
        for row in range(1, min(ws.max_row or 1, max_scan) + 1):
            texts = [cell_text(ws, row, c) for c in range(1, min(ws.max_column or 0, 30) + 1)]
            if sum(1 for t in texts if t) >= 2:
                return row, detect_columns(ws, row)
        return 1, detect_columns(ws, 1)
    return best_row, best_columns


def to_number(value) -> float | None:
    """Konversi angka Excel / teks Indonesia ('1.000,50') ke float."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float, Decimal)):
        return float(value)
    text = str(value).strip()
    if not text or text in ("-", "–", "—"):
        return None
    text = (
        text.replace("\xa0", "")
        .replace("Rp", "")
        .replace("rp", "")
        .replace("IDR", "")
        .replace(" ", "")
    )
    negative = text.startswith("(") and text.endswith(")")
    if negative:
        text = text[1:-1]
    text = text.rstrip("%")
    if both := ("." in text and "," in text):
        if text.rfind(",") > text.rfind("."):
            text = text.replace(".", "").replace(",", ".")
        else:
            text = text.replace(",", "")
    elif "." in text:
        if re.fullmatch(r"[+-]?\d{1,3}(\.\d{3})+", text):
            text = text.replace(".", "")
    elif "," in text:
        if re.fullmatch(r"[+-]?\d{1,3}(,\d{3})+", text):
            text = text.replace(",", "")
        else:
            text = text.replace(",", ".")
    text = re.sub(r"[^0-9eE+\-.]", "", text)
    if text in ("", ".", "-", "+"):
        return None
    try:
        number = float(text)
    except ValueError:
        return None
    return -number if negative else number


def _is_decimal(number: float) -> bool:
    return abs(number - round(number)) > 1e-9


def _round_qty(value: float) -> int:
    """Bulatkan qty ke bilangan bulat terdekat, 0,5 selalu ke atas."""
    return int(Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _formula_without_cache(values_wb, formula_wb, sheet: str, row: int, col: int) -> bool:
    try:
        value = values_wb[sheet].cell(row=row, column=col).value
        formula = formula_wb[sheet].cell(row=row, column=col).value
    except Exception:
        return False
    return value is None and isinstance(formula, str) and formula.startswith("=")


def match_section_header(text: str) -> tuple[str, int] | None:
    """Kenali penanda blok jenis kendaraan, mis. ``YAMAHA VIXION (3 Unit)``."""
    raw = (text or "").strip()
    if not raw or SUMMARY_RE.match(raw):
        return None
    match = SECTION_RE.match(raw)
    if not match:
        return None
    name = match.group("name").strip(" -:.")
    count = int(match.group("count"))
    if not name or count <= 0:
        return None
    return name, count


def parse_rab(
    path: str | Path,
    mapping: RabMapping,
    *,
    single_term_name: str = "Termin 1",
) -> ParseResult:
    path = str(path)
    try:
        values_wb = openpyxl.load_workbook(path, data_only=True)
        formula_wb = openpyxl.load_workbook(path, data_only=False)
    except Exception as exc:  # noqa: BLE001
        raise RabParseError(f"File tidak bisa dibuka: {exc}") from exc

    if mapping.sheet not in values_wb.sheetnames:
        raise RabParseError(f"Sheet '{mapping.sheet}' tidak ditemukan.")

    ws = values_wb[mapping.sheet]
    name_col = mapping.first(ROLE_NAME)
    price_col = mapping.first(ROLE_PRICE)
    unit_col = mapping.first(ROLE_UNIT)
    total_col = mapping.first(ROLE_TOTAL_QTY)
    term_cols = mapping.terms()

    if name_col is None or price_col is None:
        raise RabParseError("Kolom Nama Barang dan Harga Satuan wajib dipilih.")

    if term_cols:
        term_names = [c.term_name.strip() for c in term_cols]
    else:
        term_names = [single_term_name.strip() or "Termin 1"]
    # Pastikan unik
    seen: dict[str, int] = {}
    unique_names: list[str] = []
    for name in term_names:
        count = seen.get(name, 0) + 1
        seen[name] = count
        unique_names.append(name if count == 1 else f"{name} ({count})")
    term_names = unique_names

    result = ParseResult(term_names=term_names)
    formula_warned: set[tuple[int, int]] = set()
    last_data_row = ws.max_row or mapping.header_row

    current_group: ParsedGroup | None = None
    group_names: dict[str, int] = {}

    def ensure_group(name: str = "", count: int = 0, source_row: int = 0) -> None:
        nonlocal current_group
        label = (name or "").strip()
        if label:
            seen_count = group_names.get(label.casefold(), 0) + 1
            group_names[label.casefold()] = seen_count
            if seen_count > 1:
                result.issues.append(
                    f"Jenis kendaraan '{label}' muncul lebih dari sekali; "
                    f"blok ke-{seen_count} diberi nama '{label} ({seen_count})'."
                )
                label = f"{label} ({seen_count})"
        current_group = ParsedGroup(
            name=label,
            unit_count=max(0, int(count)),
            source_row=source_row,
        )
        result.groups.append(current_group)

    def row_has_numeric(row: int) -> bool:
        columns = ([price_col] if price_col else []) + (
            [total_col] if total_col else []
        ) + list(term_cols)
        for mapped in columns:
            value = to_number(ws.cell(row=row, column=mapped.col).value)
            if value not in (None, 0):
                return True
        return False

    for row in range(mapping.header_row + 1, last_data_row + 1):
        name = cell_text(ws, row, name_col.col)
        if not name:
            continue

        section = match_section_header(name)
        if section is not None and not row_has_numeric(row):
            ensure_group(section[0], section[1], row)
            continue

        if SUMMARY_RE.match(name) or re.fullmatch(r"[\d\s.,%-]+", name):
            result.skipped_rows.append(row)
            continue

        price_value = to_number(ws.cell(row=row, column=price_col.col).value)
        unit = cell_text(ws, row, unit_col.col) if unit_col else ""
        term_values: list[float] = []
        for mapped in term_cols:
            number = to_number(ws.cell(row=row, column=mapped.col).value)
            term_values.append(number or 0.0)
            if number is not None and _is_decimal(number):
                result.decimal_rows.append(row)

        if total_col:
            total_value = to_number(ws.cell(row=row, column=total_col.col).value)
            if total_value is not None and _is_decimal(total_value):
                result.decimal_rows.append(row)
        else:
            total_value = None

        sum_terms = sum(term_values)
        if not term_cols:
            term_values = [total_value or 0.0]
            sum_terms = term_values[0]

        if total_value is None:
            total_value = sum_terms

        # Baris judul bagian / catatan: tidak ada angka sama sekali
        if (
            price_value in (None, 0)
            and total_value == 0
            and sum_terms == 0
            and not unit
        ):
            result.skipped_rows.append(row)
            continue

        if current_group is None:
            ensure_group("", 0, row)

        item_label = (
            f"{current_group.name} / {name}"
            if current_group is not None and current_group.name
            else name
        )

        # Formula yang belum punya nilai tersimpan
        for mapped in ([price_col] + term_cols + ([total_col] if total_col else [])):
            key = (row, mapped.col)
            if key not in formula_warned and _formula_without_cache(
                values_wb, formula_wb, mapping.sheet, row, mapped.col
            ):
                formula_warned.add(key)
                result.issues.append(
                    f"Baris {row}: sel {get_column_letter(mapped.col)}"
                    f"{row} berisi formula tanpa nilai tersimpan. Buka file di Excel "
                    "lalu simpan, atau isi nilainya manual."
                )

        for number in term_values:
            if number < 0:
                result.issues.append(
                    f"Baris {row} ({item_label}): qty termin negatif ({number:g})."
                )
        if total_value < 0:
            result.issues.append(
                f"Baris {row} ({item_label}): qty RAB negatif ({total_value:g})."
            )
        if price_value is not None and price_value < 0:
            result.issues.append(
                f"Baris {row} ({item_label}): harga satuan negatif ({price_value:g})."
            )
        if price_value in (None, 0) and total_value:
            result.issues.append(
                f"Baris {row} ({item_label}): harga satuan kosong/0."
            )
        if abs(sum_terms - total_value) > 1e-9:
            result.issues.append(
                f"Baris {row} ({item_label}): total qty termin ({sum_terms:g}) tidak "
                f"sama dengan qty RAB ({total_value:g})."
            )

        assert current_group is not None
        current_group.items.append(
            ParsedItem(
                name=name,
                unit=unit,
                unit_price=int(
                    Decimal(str(price_value or 0)).quantize(
                        Decimal("1"), rounding=ROUND_HALF_UP
                    )
                ),
                total_qty=_round_qty(total_value),
                term_qty=[_round_qty(v) for v in term_values],
                source_row=row,
            )
        )

    if not result.items:
        raise RabParseError(
            "Tidak ada item yang terbaca. Periksa baris header dan pemetaan kolom."
        )

    if result.decimal_rows:
        rows = sorted(set(result.decimal_rows))
        preview = ", ".join(str(r) for r in rows[:10])
        more = "..." if len(rows) > 10 else ""
        result.issues.append(
            f"Qty desimal ditemukan di baris {preview}{more}. "
            "Nilai akan dibulatkan ke bilangan bulat terdekat."
        )
    return result


def list_sheets(path: str | Path) -> list[str]:
    try:
        wb = openpyxl.load_workbook(str(path), read_only=True)
        names = list(wb.sheetnames)
        wb.close()
        return names
    except Exception as exc:  # noqa: BLE001
        raise RabParseError(f"File tidak bisa dibuka: {exc}") from exc


def read_header_preview(
    path: str | Path, sheet: str, header_row: int, max_rows: int = 12
) -> tuple[list[dict[int, str]], int]:
    """Ambil teks beberapa baris untuk preview di dialog mapping."""
    try:
        wb = openpyxl.load_workbook(str(path), data_only=True, read_only=True)
    except Exception as exc:  # noqa: BLE001
        raise RabParseError(f"File tidak bisa dibuka: {exc}") from exc
    try:
        ws = wb[sheet]
        max_col = min(ws.max_column or 1, 40)
        rows: list[dict[int, str]] = []
        for row in range(header_row, min(ws.max_row or header_row, header_row + max_rows) + 1):
            values: dict[int, str] = {}
            for col in range(1, max_col + 1):
                value = ws.cell(row=row, column=col).value
                if value is not None:
                    values[col] = str(value)
            rows.append(values)
        return rows, max_col
    finally:
        wb.close()
