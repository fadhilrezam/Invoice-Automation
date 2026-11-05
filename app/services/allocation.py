"""Logika inti pembagian qty RAB ke kendaraan.

Modul ini sengaja tidak bergantung pada UI maupun database agar mudah diuji.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RemainderPlan:
    item_id: int
    qty: int
    base: int
    remainder: int
    vehicle_ids: tuple[int, ...]
    suggested: tuple[int, ...]


def split_qty(qty: int, vehicle_count: int) -> tuple[int, int]:
    """Kembalikan (dasar, sisa) = divmod(qty, jumlah kendaraan)."""
    qty = int(qty)
    if vehicle_count <= 0:
        raise ValueError("Jumlah kendaraan harus lebih dari 0")
    if qty < 0:
        raise ValueError("Qty tidak boleh negatif")
    return divmod(qty, vehicle_count)


def rank_vehicles(
    vehicle_ids: list[int],
    history: dict[int, int],
    order: dict[int, int] | None = None,
) -> list[int]:
    """Urutkan kendaraan: paling sedikit menerima item ini dulu, lalu urutan tetap."""
    order = order or {}
    return sorted(
        vehicle_ids,
        key=lambda vid: (history.get(vid, 0), order.get(vid, 0), vid),
    )


def allocate_item(
    qty: int,
    vehicle_ids: list[int],
    history: dict[int, int] | None = None,
    order: dict[int, int] | None = None,
) -> dict[int, int]:
    """Bagi qty; sisa diberikan ke kendaraan dengan riwayat paling sedikit.

    Untuk kasus yang butuh pilihan user, hasil ini dipakai sebagai *saran*.
    """
    history = history or {}
    qty = int(qty)
    if qty < 0:
        raise ValueError("Qty tidak boleh negatif")
    if not vehicle_ids:
        raise ValueError("Daftar kendaraan kosong")
    base, remainder = divmod(qty, len(vehicle_ids))
    result = {vid: base for vid in vehicle_ids}
    if remainder:
        for vid in rank_vehicles(vehicle_ids, history, order)[:remainder]:
            result[vid] += 1
    return result


def build_remainder_plan(
    item_id: int,
    qty: int,
    vehicle_ids: list[int],
    history: dict[int, int] | None = None,
    order: dict[int, int] | None = None,
) -> RemainderPlan:
    history = history or {}
    base, remainder = split_qty(qty, len(vehicle_ids))
    suggested = tuple(
        rank_vehicles(vehicle_ids, history, order)[:remainder]
    )
    return RemainderPlan(
        item_id=item_id,
        qty=int(qty),
        base=base,
        remainder=remainder,
        vehicle_ids=tuple(vehicle_ids),
        suggested=suggested,
    )


def validate_choice(plan: RemainderPlan, chosen_vehicle_ids: list[int]) -> str | None:
    """Kembalikan pesan error, atau None jika pilihan valid."""
    chosen = set(chosen_vehicle_ids)
    unknown = chosen - set(plan.vehicle_ids)
    if unknown:
        return "Ada kendaraan yang tidak dikenal."
    if len(chosen) != plan.remainder:
        return (
            f"Pilih tepat {plan.remainder} kendaraan untuk menerima tambahan 1, "
            f"saat ini {len(chosen)}."
        )
    return None


def allocations_for_choice(
    plan: RemainderPlan, chosen_vehicle_ids: list[int]
) -> dict[int, int]:
    chosen = set(chosen_vehicle_ids)
    return {
        vid: plan.base + (1 if vid in chosen else 0)
        for vid in plan.vehicle_ids
    }
