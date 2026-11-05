from __future__ import annotations

from ..db import Database
from ..models import AllocIssue, Item, Term, Vehicle


def _item_label(item: Item) -> str:
    return f"{item.type_name} / {item.name}" if item.type_name else item.name


def validate_project(db: Database, project_id: int) -> list[AllocIssue]:
    """Validasi F3: total qty semua termin harus sama dengan qty RAB per item."""
    items = db.list_items(project_id)
    terms = db.list_terms(project_id)
    issues: list[AllocIssue] = []

    if not items:
        issues.append(AllocIssue("", "RAB belum diimpor atau tidak berisi item."))
    if not terms:
        issues.append(AllocIssue("", "Belum ada termin. Impor RAB atau tambah termin."))
    if not items or not terms:
        return issues

    term_qty = db.get_project_term_qty(project_id)
    for item in items:
        label = _item_label(item)
        if item.total_qty < 0:
            issues.append(
                AllocIssue(
                    label,
                    f"Qty RAB negatif ({item.total_qty}).",
                    item.row_no,
                )
            )
        total_terms = sum(
            term_qty.get((term.id, item.id), 0) for term in terms
        )
        if total_terms != item.total_qty:
            issues.append(
                AllocIssue(
                    label,
                    f"Total qty termin ({total_terms}) tidak sama dengan qty RAB "
                    f"({item.total_qty}). Selisih {total_terms - item.total_qty:+d}.",
                    item.row_no,
                )
            )
        for term in terms:
            qty = term_qty.get((term.id, item.id), 0)
            if qty < 0:
                issues.append(
                    AllocIssue(
                        label,
                        f"Qty {term.name} negatif ({qty}).",
                        item.row_no,
                    )
                )
    return issues


def validate_term(
    db: Database,
    term: Term,
    items: list[Item] | None = None,
    vehicles: list[Vehicle] | None = None,
) -> list[AllocIssue]:
    """Validasi invarian: jumlah alokasi semua kendaraan = qty termin."""
    items = items if items is not None else db.list_items(term.project_id)
    vehicles = vehicles if vehicles is not None else db.list_vehicles(term.project_id)
    issues: list[AllocIssue] = []

    if not vehicles:
        issues.append(AllocIssue("", "Belum ada kendaraan pada proyek ini."))
        return issues
    if not items:
        issues.append(AllocIssue("", "Belum ada item RAB pada proyek ini."))
        return issues

    term_qty = db.get_term_qty(term.id)
    allocations = db.get_term_allocations(term.id)
    by_item: dict[int, int] = {}
    for (item_id, _vehicle_id), qty in allocations.items():
        by_item[item_id] = by_item.get(item_id, 0) + qty

    type_ids = {item.vehicle_type_id for item in items if item.vehicle_type_id}
    missing_types: set[int] = set()
    for type_id in type_ids:
        if not any(v.vehicle_type_id == type_id for v in vehicles):
            missing_types.add(type_id)
            name = next(
                (item.type_name for item in items if item.vehicle_type_id == type_id),
                f"Jenis #{type_id}",
            )
            issues.append(
                AllocIssue(
                    name,
                    "Jenis kendaraan ini belum punya unit/kendaraan. "
                    "Tambahkan kendaraan atau import ulang RAB.",
                )
            )

    for item in items:
        if item.vehicle_type_id in missing_types:
            continue
        target = term_qty.get(item.id, 0)
        actual = by_item.get(item.id, 0)
        if actual != target:
            problem = "Kurang" if actual < target else "Lebih"
            issues.append(
                AllocIssue(
                    _item_label(item),
                    f"{problem} {abs(actual - target)} unit di {term.name} "
                    f"(teralokasi {actual}, seharusnya {target}).",
                    item.row_no,
                )
            )
    return issues


def term_totals(
    db: Database, term: Term, items: list[Item] | None = None
) -> dict[str, int | float]:
    items = items if items is not None else db.list_items(term.project_id)
    term_qty = db.get_term_qty(term.id)
    allocations = db.get_term_allocations(term.id)
    allocated_by_item: dict[int, int] = {}
    for (item_id, _vid), qty in allocations.items():
        allocated_by_item[item_id] = allocated_by_item.get(item_id, 0) + qty
    total_qty = sum(term_qty.values())
    allocated = sum(allocated_by_item.values())
    value = sum(
        allocated_by_item.get(item.id, 0) * item.unit_price for item in items
    )
    return {
        "total_qty": total_qty,
        "allocated": allocated,
        "remaining": total_qty - allocated,
        "value": int(value),
    }
