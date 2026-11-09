from __future__ import annotations

from pathlib import Path

from ..db import Database
from ..models import Item, Project, Term, Vehicle
from ..utils import format_date_id, format_rupiah
from .invoice_export import InvoiceData, InvoiceLine


def build_invoice_data(
    db: Database,
    project: Project,
    term: Term,
    vehicle: Vehicle,
    items: list[Item] | None = None,
    company_name: str = "",
    company_address: str = "",
    template_path: str | Path = "",
) -> InvoiceData | None:
    if items is None:
        items = db.list_items(project.id, vehicle.vehicle_type_id)
    allocations = db.get_term_allocations(term.id)
    lines: list[InvoiceLine] = []
    for item in items:
        qty = allocations.get((item.id, vehicle.id), 0)
        if qty > 0:
            lines.append(
                InvoiceLine(name=item.name, qty=qty, unit_price=item.unit_price)
            )
    if not lines:
        return None

    invoice_date = term.date_obj or project.date_obj
    date_format = term.date_format or project.date_format or "full"
    invoice_date_text = format_date_id(invoice_date, date_format)
    label = vehicle.plate or vehicle.display_name
    po_prefix = vehicle.po_prefix or project.po_prefix or ""
    po_number = f"{po_prefix}{label}"
    vehicle_type = vehicle.type_name or vehicle.vehicle_type or project.vehicle_type
    return InvoiceData(
        plate=vehicle.plate,
        label=label,
        vehicle_type=vehicle_type,
        client_name=project.client_name,
        client_address=project.client_address,
        company_name=company_name,
        company_address=company_address,
        po_number=po_number,
        invoice_date=invoice_date,
        invoice_date_text=invoice_date_text,
        lines=lines,
        discount_percent=term.discount_percent,
        term_name=term.name,
        project_name=project.name,
    )


def invoice_summary_text(invoice: InvoiceData) -> str:
    return (
        f"{invoice.label or invoice.plate}: {len(invoice.lines)} item, "
        f"total {format_rupiah(invoice.total)}"
    )
