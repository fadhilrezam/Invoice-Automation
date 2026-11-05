from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from .utils import parse_iso_date


@dataclass
class Project:
    id: int
    name: str
    client_name: str = ""
    client_address: str = ""
    po_prefix: str = "VXN-"
    vehicle_type: str = ""
    invoice_date: str = ""
    created_at: str = ""

    @property
    def date_obj(self) -> date:
        return parse_iso_date(self.invoice_date)

    @classmethod
    def from_row(cls, row) -> "Project":
        return cls(
            id=row["id"],
            name=row["name"],
            client_name=row["client_name"] or "",
            client_address=row["client_address"] or "",
            po_prefix=row["po_prefix"] or "",
            vehicle_type=row["vehicle_type"] or "",
            invoice_date=row["invoice_date"] or "",
            created_at=row["created_at"] or "",
        )


@dataclass
class VehicleType:
    id: int
    project_id: int
    name: str
    unit_count: int = 0
    sort_order: int = 0
    po_prefix: str = ""

    @classmethod
    def from_row(cls, row) -> "VehicleType":
        keys = row.keys()
        return cls(
            id=row["id"],
            project_id=row["project_id"],
            name=row["name"] or "",
            unit_count=int(row["unit_count"] or 0),
            sort_order=int(row["sort_order"] or 0),
            po_prefix=(row["po_prefix"] or "") if "po_prefix" in keys else "",
        )


@dataclass
class Vehicle:
    id: int
    project_id: int
    plate: str
    vehicle_type: str = ""
    sort_order: int = 0
    vehicle_type_id: int | None = None
    unit_no: int = 0
    type_name: str = ""

    @property
    def display_name(self) -> str:
        if self.plate:
            return self.plate
        type_name = (self.type_name or self.vehicle_type or "Kendaraan").title()
        if self.unit_no:
            return f"{type_name} #{self.unit_no}"
        return type_name

    @classmethod
    def from_row(cls, row) -> "Vehicle":
        keys = row.keys()
        return cls(
            id=row["id"],
            project_id=row["project_id"],
            plate=row["plate"] or "",
            vehicle_type=row["vehicle_type"] or "",
            sort_order=row["sort_order"] or 0,
            vehicle_type_id=(
                int(row["vehicle_type_id"])
                if "vehicle_type_id" in keys and row["vehicle_type_id"] is not None
                else None
            ),
            unit_no=int(row["unit_no"] or 0) if "unit_no" in keys else 0,
            type_name=(row["type_name"] or "") if "type_name" in keys else "",
        )


@dataclass
class Term:
    id: int
    project_id: int
    name: str
    seq: int
    invoice_date: str | None = None
    discount_percent: float = 0.0
    locked: bool = False

    @property
    def date_obj(self) -> date | None:
        if not self.invoice_date:
            return None
        return parse_iso_date(self.invoice_date)

    @classmethod
    def from_row(cls, row) -> "Term":
        discount = row["discount_percent"]
        if discount is None:
            discount = row["discount"] if "discount" in row.keys() else 0
        return cls(
            id=row["id"],
            project_id=row["project_id"],
            name=row["name"] or "",
            seq=row["seq"] or 0,
            invoice_date=row["invoice_date"],
            discount_percent=float(discount or 0),
            locked=bool(row["locked"]),
        )


@dataclass
class Item:
    id: int
    project_id: int
    row_no: int
    name: str
    unit: str = ""
    unit_price: int = 0
    total_qty: int = 0
    vehicle_type_id: int | None = None
    type_name: str = ""

    @classmethod
    def from_row(cls, row) -> "Item":
        keys = row.keys()
        return cls(
            id=row["id"],
            project_id=row["project_id"],
            row_no=row["row_no"] or 0,
            name=row["name"] or "",
            unit=row["unit"] or "",
            unit_price=int(round(row["unit_price"] or 0)),
            total_qty=int(round(row["total_qty"] or 0)),
            vehicle_type_id=(
                int(row["vehicle_type_id"])
                if "vehicle_type_id" in keys and row["vehicle_type_id"] is not None
                else None
            ),
            type_name=(row["type_name"] or "") if "type_name" in keys else "",
        )


@dataclass
class ParsedGroup:
    """Satu blok jenis kendaraan pada RAB (mis. 'YAMAHA VIXION (3 Unit)')."""

    name: str
    unit_count: int
    items: list["ParsedItem"] = field(default_factory=list)
    source_row: int = 0


@dataclass
class ParsedItem:
    """Item hasil parsing RAB sebelum disimpan."""

    name: str
    unit: str
    unit_price: int
    total_qty: int
    term_qty: list[int] = field(default_factory=list)
    source_row: int = 0


@dataclass
class AllocIssue:
    item_name: str
    message: str
    row_no: int = 0
