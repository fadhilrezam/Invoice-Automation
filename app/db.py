from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import date, datetime
from pathlib import Path
from typing import Iterable, Sequence

from .models import Item, ParsedGroup, ParsedItem, Project, Term, Vehicle, VehicleType
from .utils import date_to_iso

SCHEMA = """
CREATE TABLE IF NOT EXISTS projects (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    client_name TEXT NOT NULL DEFAULT '',
    client_address TEXT NOT NULL DEFAULT '',
    po_prefix TEXT NOT NULL DEFAULT '',
    vehicle_type TEXT NOT NULL DEFAULT '',
    invoice_date TEXT NOT NULL,
    date_format TEXT NOT NULL DEFAULT 'full',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS vehicle_types (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    unit_count INTEGER NOT NULL DEFAULT 0,
    sort_order INTEGER NOT NULL DEFAULT 0,
    po_prefix TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS vehicles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    plate TEXT NOT NULL,
    vehicle_type TEXT NOT NULL DEFAULT '',
    sort_order INTEGER NOT NULL DEFAULT 0,
    vehicle_type_id INTEGER REFERENCES vehicle_types(id) ON DELETE CASCADE,
    unit_no INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    row_no INTEGER NOT NULL DEFAULT 0,
    name TEXT NOT NULL,
    unit TEXT NOT NULL DEFAULT '',
    unit_price INTEGER NOT NULL DEFAULT 0,
    total_qty INTEGER NOT NULL DEFAULT 0,
    vehicle_type_id INTEGER REFERENCES vehicle_types(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS terms (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    seq INTEGER NOT NULL DEFAULT 0,
    invoice_date TEXT,
    date_format TEXT,
    discount_percent REAL NOT NULL DEFAULT 0,
    locked INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS term_qty (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    term_id INTEGER NOT NULL REFERENCES terms(id) ON DELETE CASCADE,
    item_id INTEGER NOT NULL REFERENCES items(id) ON DELETE CASCADE,
    qty INTEGER NOT NULL DEFAULT 0,
    UNIQUE(term_id, item_id)
);

CREATE TABLE IF NOT EXISTS allocations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    term_id INTEGER NOT NULL REFERENCES terms(id) ON DELETE CASCADE,
    item_id INTEGER NOT NULL REFERENCES items(id) ON DELETE CASCADE,
    vehicle_id INTEGER NOT NULL REFERENCES vehicles(id) ON DELETE CASCADE,
    qty INTEGER NOT NULL DEFAULT 0,
    UNIQUE(term_id, item_id, vehicle_id)
);

CREATE TABLE IF NOT EXISTS audit_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER REFERENCES projects(id) ON DELETE CASCADE,
    ts TEXT NOT NULL,
    action TEXT NOT NULL,
    detail TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL DEFAULT ''
);

CREATE INDEX IF NOT EXISTS idx_items_project ON items(project_id);
CREATE INDEX IF NOT EXISTS idx_terms_project ON terms(project_id);
CREATE INDEX IF NOT EXISTS idx_term_qty_term ON term_qty(term_id);
CREATE INDEX IF NOT EXISTS idx_alloc_term ON allocations(term_id);
CREATE INDEX IF NOT EXISTS idx_alloc_item ON allocations(item_id);
CREATE INDEX IF NOT EXISTS idx_vehicle_types_project ON vehicle_types(project_id);
"""


class Database:
    def __init__(self, path: str | Path):
        self.path = str(path)
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.path)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        self.conn.executescript(SCHEMA)
        self._migrate()
        self.conn.commit()

    def _columns(self, table: str) -> set[str]:
        rows = self.conn.execute(f"PRAGMA table_info({table})").fetchall()
        return {str(row["name"]) for row in rows}

    def _migrate(self) -> None:
        """Migrasi database lama ke model multi-jenis kendaraan."""
        item_columns = self._columns("items")
        vehicle_columns = self._columns("vehicles")
        if "vehicle_type_id" not in item_columns:
            self.conn.execute(
                "ALTER TABLE items ADD COLUMN vehicle_type_id INTEGER "
                "REFERENCES vehicle_types(id) ON DELETE CASCADE"
            )
        if "vehicle_type_id" not in vehicle_columns:
            self.conn.execute(
                "ALTER TABLE vehicles ADD COLUMN vehicle_type_id INTEGER "
                "REFERENCES vehicle_types(id) ON DELETE CASCADE"
            )
        if "unit_no" not in vehicle_columns:
            self.conn.execute(
                "ALTER TABLE vehicles ADD COLUMN unit_no INTEGER NOT NULL DEFAULT 0"
            )

        self.conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_items_type ON items(vehicle_type_id)"
        )
        self.conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_vehicles_type ON vehicles(vehicle_type_id)"
        )

        # Backfill proyek lama: semua item/kendaraan masuk satu jenis kendaraan.
        projects = self.conn.execute(
            "SELECT p.* FROM projects p "
            "WHERE EXISTS (SELECT 1 FROM items i WHERE i.project_id = p.id "
            "              AND i.vehicle_type_id IS NULL) "
            "   OR EXISTS (SELECT 1 FROM vehicles v WHERE v.project_id = p.id "
            "              AND v.vehicle_type_id IS NULL)"
        ).fetchall()
        for project in projects:
            project_id = int(project["id"])
            type_row = self.conn.execute(
                "SELECT * FROM vehicle_types WHERE project_id = ? "
                "ORDER BY sort_order, id LIMIT 1",
                (project_id,),
            ).fetchone()
            if type_row is None:
                name = (project["vehicle_type"] or "Kendaraan").strip() or "Kendaraan"
                vehicle_count = self.conn.execute(
                    "SELECT COUNT(*) FROM vehicles WHERE project_id = ?",
                    (project_id,),
                ).fetchone()[0]
                cur = self.conn.execute(
                    """INSERT INTO vehicle_types (project_id, name, unit_count, sort_order)
                       VALUES (?, ?, ?, 1)""",
                    (project_id, name, int(vehicle_count or 0)),
                )
                type_id = int(cur.lastrowid)
            else:
                type_id = int(type_row["id"])
            self.conn.execute(
                "UPDATE items SET vehicle_type_id = ? "
                "WHERE project_id = ? AND vehicle_type_id IS NULL",
                (type_id, project_id),
            )
            self.conn.execute(
                "UPDATE vehicles SET vehicle_type_id = ? "
                "WHERE project_id = ? AND vehicle_type_id IS NULL",
                (type_id, project_id),
            )
            # Isi unit_no bila belum ada.
            rows = self.conn.execute(
                "SELECT id FROM vehicles WHERE project_id = ? "
                "AND vehicle_type_id = ? ORDER BY sort_order, id",
                (project_id, type_id),
            ).fetchall()
            for index, row in enumerate(rows, start=1):
                self.conn.execute(
                    "UPDATE vehicles SET unit_no = ? WHERE id = ?",
                    (index, int(row["id"])),
                )

        # Migrasi: tambahkan kolom po_prefix ke vehicle_types
        if "po_prefix" not in self._columns("vehicle_types"):
            self.conn.execute(
                "ALTER TABLE vehicle_types ADD COLUMN po_prefix TEXT NOT NULL DEFAULT ''"
            )
        # Proyek lama dengan satu jenis kendaraan: wariskan prefix proyek.
        # Proyek multi-jenis tidak diisi otomatis agar tiap jenis diisi sendiri.
        self.conn.execute(
            """UPDATE vehicle_types SET po_prefix = (
               SELECT p.po_prefix FROM projects p WHERE p.id = vehicle_types.project_id
             ) WHERE po_prefix = '' AND (
               SELECT COUNT(*) FROM vehicle_types vt2
               WHERE vt2.project_id = vehicle_types.project_id
             ) = 1"""
        )

        # Migrasi: tambahkan kolom date_format ke projects dan terms
        if "date_format" not in self._columns("projects"):
            self.conn.execute(
                "ALTER TABLE projects ADD COLUMN date_format TEXT NOT NULL DEFAULT 'full'"
            )
        if "date_format" not in self._columns("terms"):
            self.conn.execute(
                "ALTER TABLE terms ADD COLUMN date_format TEXT"
            )

    # ------------------------------------------------------------------ utils
    def close(self) -> None:
        self.conn.close()

    @contextmanager
    def transaction(self):
        try:
            self.conn.execute("BEGIN")
            yield self.conn
            self.conn.commit()
        except Exception:
            self.conn.rollback()
            raise

    def _now(self) -> str:
        return datetime.now().isoformat(timespec="seconds")

    # --------------------------------------------------------------- projects
    def list_projects(self) -> list[Project]:
        rows = self.conn.execute(
            "SELECT * FROM projects ORDER BY id DESC"
        ).fetchall()
        return [Project.from_row(r) for r in rows]

    def get_project(self, project_id: int) -> Project | None:
        row = self.conn.execute(
            "SELECT * FROM projects WHERE id = ?", (project_id,)
        ).fetchone()
        return Project.from_row(row) if row else None

    def create_project(
        self,
        name: str,
        client_name: str = "",
        client_address: str = "",
        po_prefix: str = "",
        vehicle_type: str = "",
        invoice_date: date | None = None,
        date_format: str = "full",
    ) -> int:
        invoice_date = invoice_date or date.today()
        with self.transaction() as conn:
            cur = conn.execute(
                """INSERT INTO projects
                   (name, client_name, client_address, po_prefix, vehicle_type,
                    invoice_date, date_format, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    name.strip() or "Proyek Baru",
                    client_name,
                    client_address,
                    po_prefix,
                    vehicle_type,
                    date_to_iso(invoice_date),
                    date_format or "full",
                    self._now(),
                ),
            )
            project_id = int(cur.lastrowid)
            conn.execute(
                "INSERT INTO audit_log (project_id, ts, action, detail) VALUES (?, ?, ?, ?)",
                (project_id, self._now(), "buat_proyek", f"Proyek '{name}' dibuat"),
            )
        return project_id

    def update_project(
        self,
        project_id: int,
        *,
        name: str | None = None,
        client_name: str | None = None,
        client_address: str | None = None,
        po_prefix: str | None = None,
        vehicle_type: str | None = None,
        invoice_date: date | None = None,
        date_format: str | None = None,
    ) -> None:
        fields: list[str] = []
        values: list[object] = []
        for key, value in (
            ("name", name),
            ("client_name", client_name),
            ("client_address", client_address),
            ("po_prefix", po_prefix),
            ("vehicle_type", vehicle_type),
            ("date_format", date_format),
        ):
            if value is not None:
                fields.append(f"{key} = ?")
                values.append(value)
        if invoice_date is not None:
            fields.append("invoice_date = ?")
            values.append(date_to_iso(invoice_date))
        if not fields:
            return
        values.append(project_id)
        with self.transaction() as conn:
            conn.execute(
                f"UPDATE projects SET {', '.join(fields)} WHERE id = ?", values
            )

    def delete_project(self, project_id: int) -> None:
        with self.transaction() as conn:
            conn.execute("DELETE FROM projects WHERE id = ?", (project_id,))

    # ----------------------------------------------------------- vehicle types
    def list_vehicle_types(self, project_id: int) -> list[VehicleType]:
        rows = self.conn.execute(
            "SELECT * FROM vehicle_types WHERE project_id = ? ORDER BY sort_order, id",
            (project_id,),
        ).fetchall()
        return [VehicleType.from_row(r) for r in rows]

    def get_vehicle_type(self, type_id: int) -> VehicleType | None:
        row = self.conn.execute(
            "SELECT * FROM vehicle_types WHERE id = ?", (type_id,)
        ).fetchone()
        return VehicleType.from_row(row) if row else None

    def find_vehicle_type(self, project_id: int, name: str) -> VehicleType | None:
        target = (name or "").strip().casefold()
        if not target:
            return None
        for vehicle_type in self.list_vehicle_types(project_id):
            if vehicle_type.name.strip().casefold() == target:
                return vehicle_type
        return None

    def _next_type_order(self, project_id: int) -> int:
        return int(
            self.conn.execute(
                "SELECT COALESCE(MAX(sort_order), 0) + 1 FROM vehicle_types "
                "WHERE project_id = ?",
                (project_id,),
            ).fetchone()[0]
        )

    def _sync_type_vehicles(
        self,
        conn,
        type_id: int,
        project_id: int,
        type_name: str,
        unit_count: int,
    ) -> None:
        """Samakan jumlah slot kendaraan dengan unit_count, plat lama dipertahankan."""
        target = max(0, int(unit_count))
        rows = conn.execute(
            "SELECT id FROM vehicles WHERE vehicle_type_id = ? "
            "ORDER BY unit_no, sort_order, id",
            (type_id,),
        ).fetchall()
        for index in range(1, target + 1):
            if index <= len(rows):
                conn.execute(
                    "UPDATE vehicles SET unit_no = ?, sort_order = ?, "
                    "vehicle_type = ?, vehicle_type_id = ? WHERE id = ?",
                    (index, index, type_name, type_id, int(rows[index - 1]["id"])),
                )
            else:
                conn.execute(
                    """INSERT INTO vehicles
                       (project_id, plate, vehicle_type, sort_order,
                        vehicle_type_id, unit_no)
                       VALUES (?, '', ?, ?, ?, ?)""",
                    (project_id, type_name, index, type_id, index),
                )
        for row in rows[target:]:
            conn.execute("DELETE FROM vehicles WHERE id = ?", (int(row["id"]),))
        conn.execute(
            "UPDATE vehicle_types SET unit_count = ? WHERE id = ?",
            (target, type_id),
        )

    def add_vehicle_type(
        self, project_id: int, name: str, unit_count: int = 0
    ) -> int:
        name = (name or "").strip() or "Kendaraan"
        order = self._next_type_order(project_id)
        with self.transaction() as conn:
            cur = conn.execute(
                """INSERT INTO vehicle_types (project_id, name, unit_count, sort_order)
                   VALUES (?, ?, ?, ?)""",
                (project_id, name, max(0, int(unit_count)), order),
            )
            type_id = int(cur.lastrowid)
            self._sync_type_vehicles(
                conn, type_id, project_id, name, max(0, int(unit_count))
            )
        return type_id

    def update_vehicle_type(
        self,
        type_id: int,
        *,
        name: str | None = None,
        unit_count: int | None = None,
        po_prefix: str | None = None,
    ) -> None:
        current = self.get_vehicle_type(type_id)
        if current is None:
            return
        new_name = (name if name is not None else current.name).strip() or "Kendaraan"
        new_count = (
            max(0, int(unit_count))
            if unit_count is not None
            else current.unit_count
        )
        new_po_prefix = (
            (po_prefix if po_prefix is not None else current.po_prefix).strip()
            or ""
        )
        with self.transaction() as conn:
            conn.execute(
                "UPDATE vehicle_types SET name = ?, unit_count = ?, po_prefix = ? WHERE id = ?",
                (new_name, new_count, new_po_prefix, type_id),
            )
            self._sync_type_vehicles(
                conn, type_id, current.project_id, new_name, new_count
            )

    def update_vehicle_type_po_prefix(self, type_id: int, po_prefix: str) -> None:
        with self.transaction() as conn:
            conn.execute(
                "UPDATE vehicle_types SET po_prefix = ? WHERE id = ?",
                (po_prefix.strip() or "", type_id),
            )

    def delete_vehicle_type(self, type_id: int) -> None:
        with self.transaction() as conn:
            conn.execute("DELETE FROM vehicle_types WHERE id = ?", (type_id,))

    def _default_vehicle_type(self, project_id: int) -> VehicleType:
        types = self.list_vehicle_types(project_id)
        if types:
            return types[0]
        project = self.get_project(project_id)
        name = (project.vehicle_type if project else "") or "Kendaraan"
        type_id = self.add_vehicle_type(project_id, name, 0)
        found = self.get_vehicle_type(type_id)
        assert found is not None
        return found

    # --------------------------------------------------------------- vehicles
    def list_vehicles(
        self, project_id: int, vehicle_type_id: int | None = None
    ) -> list[Vehicle]:
        sql = """
            SELECT v.*, vt.name AS type_name, vt.po_prefix AS po_prefix
            FROM vehicles v
            LEFT JOIN vehicle_types vt ON vt.id = v.vehicle_type_id
            WHERE v.project_id = ?
        """
        params: list[object] = [project_id]
        if vehicle_type_id is not None:
            sql += " AND v.vehicle_type_id = ?"
            params.append(int(vehicle_type_id))
        sql += (
            " ORDER BY COALESCE(vt.sort_order, 0), v.unit_no, "
            "v.sort_order, v.id"
        )
        rows = self.conn.execute(sql, params).fetchall()
        return [Vehicle.from_row(r) for r in rows]

    def add_vehicle(
        self,
        project_id: int,
        plate: str,
        vehicle_type: str = "",
        vehicle_type_id: int | None = None,
    ) -> int:
        if vehicle_type_id is None:
            matched = self.find_vehicle_type(project_id, vehicle_type)
            if matched is not None:
                vehicle_type_id = matched.id
            else:
                vehicle_type_id = self._default_vehicle_type(project_id).id
        group = self.get_vehicle_type(int(vehicle_type_id))
        if group is None:
            group = self._default_vehicle_type(project_id)
            vehicle_type_id = group.id
        sort_order = int(
            self.conn.execute(
                "SELECT COALESCE(MAX(sort_order), 0) + 1 FROM vehicles "
                "WHERE project_id = ?",
                (project_id,),
            ).fetchone()[0]
        )
        unit_no = int(
            self.conn.execute(
                "SELECT COALESCE(MAX(unit_no), 0) + 1 FROM vehicles "
                "WHERE vehicle_type_id = ?",
                (int(vehicle_type_id),),
            ).fetchone()[0]
        )
        with self.transaction() as conn:
            cur = conn.execute(
                """INSERT INTO vehicles
                   (project_id, plate, vehicle_type, sort_order,
                    vehicle_type_id, unit_no)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    project_id,
                    (plate or "").strip(),
                    vehicle_type.strip() or group.name,
                    sort_order,
                    int(vehicle_type_id),
                    unit_no,
                ),
            )
            conn.execute(
                "UPDATE vehicle_types SET unit_count = ("
                "SELECT COUNT(*) FROM vehicles WHERE vehicle_type_id = ?"
                ") WHERE id = ?",
                (int(vehicle_type_id), int(vehicle_type_id)),
            )
            return int(cur.lastrowid)

    def update_vehicle(
        self,
        vehicle_id: int,
        plate: str,
        vehicle_type: str = "",
        vehicle_type_id: int | None = None,
    ) -> None:
        row = self.conn.execute(
            "SELECT * FROM vehicles WHERE id = ?", (vehicle_id,)
        ).fetchone()
        if row is None:
            return
        current_type_id = (
            int(row["vehicle_type_id"]) if row["vehicle_type_id"] is not None else None
        )
        target_type_id = (
            int(vehicle_type_id)
            if vehicle_type_id is not None
            else current_type_id
        )
        group = self.get_vehicle_type(target_type_id) if target_type_id else None
        type_label = (
            vehicle_type.strip()
            or (group.name if group else (row["vehicle_type"] or ""))
        )
        with self.transaction() as conn:
            conn.execute(
                "UPDATE vehicles SET plate = ?, vehicle_type = ?, "
                "vehicle_type_id = ? WHERE id = ?",
                (
                    (plate or "").strip(),
                    type_label,
                    target_type_id,
                    vehicle_id,
                ),
            )

    def delete_vehicle(self, vehicle_id: int) -> None:
        row = self.conn.execute(
            "SELECT vehicle_type_id FROM vehicles WHERE id = ?", (vehicle_id,)
        ).fetchone()
        with self.transaction() as conn:
            conn.execute("DELETE FROM vehicles WHERE id = ?", (vehicle_id,))
            if row is not None and row["vehicle_type_id"] is not None:
                type_id = int(row["vehicle_type_id"])
                conn.execute(
                    "UPDATE vehicle_types SET unit_count = ("
                    "SELECT COUNT(*) FROM vehicles WHERE vehicle_type_id = ?"
                    ") WHERE id = ?",
                    (type_id, type_id),
                )

    def replace_vehicles(
        self, project_id: int, vehicles: Sequence[tuple[str, str]]
    ) -> int:
        """Ganti seluruh daftar kendaraan. Return jumlah yang dimasukkan.

        Nama tipe dicocokkan ke jenis kendaraan yang ada; jika tidak cocok,
        kendaraan masuk ke jenis pertama.
        """
        types = self.list_vehicle_types(project_id)
        if not types:
            self._default_vehicle_type(project_id)
            types = self.list_vehicle_types(project_id)
        by_name = {vehicle_type.name.strip().casefold(): vehicle_type for vehicle_type in types}
        with self.transaction() as conn:
            conn.execute("DELETE FROM vehicles WHERE project_id = ?", (project_id,))
            counters = {vehicle_type.id: 0 for vehicle_type in types}
            for index, (plate, vehicle_type) in enumerate(vehicles, start=1):
                group = by_name.get((vehicle_type or "").strip().casefold())
                if group is None:
                    group = types[0]
                counters[group.id] = counters.get(group.id, 0) + 1
                conn.execute(
                    """INSERT INTO vehicles
                       (project_id, plate, vehicle_type, sort_order,
                        vehicle_type_id, unit_no)
                       VALUES (?, ?, ?, ?, ?, ?)""",
                    (
                        project_id,
                        (plate or "").strip(),
                        group.name,
                        index,
                        group.id,
                        counters[group.id],
                    ),
                )
            for vehicle_type in types:
                conn.execute(
                    "UPDATE vehicle_types SET unit_count = ? WHERE id = ?",
                    (counters.get(vehicle_type.id, 0), vehicle_type.id),
                )
        return len(vehicles)

    def assign_vehicle_plates(
        self,
        project_id: int,
        rows: Sequence[tuple[str, str]],
        default_type_id: int | None = None,
    ) -> tuple[int, int, int]:
        """Isi plat ke slot unit sesuai jenis kendaraan.

        Return (terpasang, tipe tidak dikenal, melebihi jumlah unit).
        Plat lama di seluruh proyek akan dikosongkan lebih dulu.
        """
        types = self.list_vehicle_types(project_id)
        if not types:
            self._default_vehicle_type(project_id)
            types = self.list_vehicle_types(project_id)
        by_name = {vehicle_type.name.strip().casefold(): vehicle_type for vehicle_type in types}
        default_type = None
        if default_type_id is not None:
            default_type = next(
                (item for item in types if item.id == int(default_type_id)), None
            )
        with self.transaction() as conn:
            conn.execute(
                "UPDATE vehicles SET plate = '' WHERE project_id = ?", (project_id,)
            )
            vehicle_ids: dict[int, list[int]] = {item.id: [] for item in types}
            for row in conn.execute(
                "SELECT id, vehicle_type_id FROM vehicles WHERE project_id = ? "
                "ORDER BY unit_no, sort_order, id",
                (project_id,),
            ).fetchall():
                type_id = row["vehicle_type_id"]
                if type_id is not None and int(type_id) in vehicle_ids:
                    vehicle_ids[int(type_id)].append(int(row["id"]))
            counters = {item.id: 0 for item in types}
            seen_plates: set[str] = set()
            assigned = 0
            unknown_types = 0
            overflow = 0
            for plate, type_name in rows:
                plate = (plate or "").strip()
                if not plate:
                    continue
                key = plate.casefold()
                if key in seen_plates:
                    continue
                seen_plates.add(key)
                group = by_name.get((type_name or "").strip().casefold())
                if group is None:
                    unknown_types += 1
                    group = default_type or types[0]
                index = counters.get(group.id, 0)
                ids = vehicle_ids.get(group.id, [])
                if index >= len(ids):
                    overflow += 1
                    continue
                conn.execute(
                    "UPDATE vehicles SET plate = ? WHERE id = ?",
                    (plate, ids[index]),
                )
                counters[group.id] = index + 1
                assigned += 1
        return assigned, unknown_types, overflow

    # ------------------------------------------------------------------ terms
    def list_terms(self, project_id: int) -> list[Term]:
        rows = self.conn.execute(
            "SELECT * FROM terms WHERE project_id = ? ORDER BY seq, id",
            (project_id,),
        ).fetchall()
        return [Term.from_row(r) for r in rows]

    def get_term(self, term_id: int) -> Term | None:
        row = self.conn.execute(
            "SELECT * FROM terms WHERE id = ?", (term_id,)
        ).fetchone()
        return Term.from_row(row) if row else None

    def add_term(
        self,
        project_id: int,
        name: str,
        invoice_date: date | None = None,
        discount_percent: float = 0.0,
        date_format: str | None = None,
    ) -> int:
        seq = self.conn.execute(
            "SELECT COALESCE(MAX(seq), 0) + 1 FROM terms WHERE project_id = ?",
            (project_id,),
        ).fetchone()[0]
        with self.transaction() as conn:
            cur = conn.execute(
                """INSERT INTO terms
                   (project_id, name, seq, invoice_date, date_format,
                    discount_percent, locked)
                   VALUES (?, ?, ?, ?, ?, ?, 0)""",
                (
                    project_id,
                    name.strip() or f"Termin {seq}",
                    seq,
                    date_to_iso(invoice_date) if invoice_date else None,
                    date_format or None,
                    float(discount_percent or 0),
                ),
            )
            return int(cur.lastrowid)

    def update_term(
        self,
        term_id: int,
        *,
        name: str | None = None,
        invoice_date: date | None = None,
        discount_percent: float | None = None,
        date_format: str | None = None,
        clear_date_format: bool = False,
    ) -> None:
        fields: list[str] = []
        values: list[object] = []
        if name is not None:
            fields.append("name = ?")
            values.append(name.strip())
        if invoice_date is not None:
            fields.append("invoice_date = ?")
            values.append(date_to_iso(invoice_date))
        if discount_percent is not None:
            fields.append("discount_percent = ?")
            values.append(float(discount_percent))
        if clear_date_format:
            fields.append("date_format = NULL")
        elif date_format is not None:
            fields.append("date_format = ?")
            values.append(date_format or None)
        if not fields:
            return
        values.append(term_id)
        with self.transaction() as conn:
            conn.execute(
                f"UPDATE terms SET {', '.join(fields)} WHERE id = ?", values
            )

    def set_term_locked(self, term_id: int, locked: bool) -> None:
        with self.transaction() as conn:
            conn.execute(
                "UPDATE terms SET locked = ? WHERE id = ?",
                (1 if locked else 0, term_id),
            )

    def delete_term(self, term_id: int) -> None:
        with self.transaction() as conn:
            conn.execute("DELETE FROM terms WHERE id = ?", (term_id,))

    # ------------------------------------------------------------------ items
    def list_items(
        self, project_id: int, vehicle_type_id: int | None = None
    ) -> list[Item]:
        sql = """
            SELECT i.*, vt.name AS type_name
            FROM items i
            LEFT JOIN vehicle_types vt ON vt.id = i.vehicle_type_id
            WHERE i.project_id = ?
        """
        params: list[object] = [project_id]
        if vehicle_type_id is not None:
            sql += " AND i.vehicle_type_id = ?"
            params.append(int(vehicle_type_id))
        sql += " ORDER BY COALESCE(vt.sort_order, 0), i.row_no, i.id"
        rows = self.conn.execute(sql, params).fetchall()
        return [Item.from_row(r) for r in rows]

    def replace_rab(
        self,
        project_id: int,
        term_names: Sequence[str],
        items: Sequence[ParsedItem] | None = None,
        *,
        groups: Sequence[ParsedGroup] | None = None,
    ) -> None:
        """Ganti RAB + termin sekaligus. Alokasi lama ikut terhapus.

        ``groups`` dipakai untuk RAB multi-jenis kendaraan. Pemanggil lama yang
        hanya mengirim ``items`` otomatis dibungkus menjadi satu jenis kendaraan.
        """
        if groups is None:
            project = self.get_project(project_id)
            default_name = (project.vehicle_type if project else "") or "Kendaraan"
            groups = [
                ParsedGroup(
                    name=default_name,
                    unit_count=0,
                    items=list(items or []),
                )
            ]
        project = self.get_project(project_id)
        default_group_name = (project.vehicle_type if project else "") or "Kendaraan"
        groups = [group for group in groups if group.items or group.unit_count > 0]
        old_terms = {t.name: t for t in self.list_terms(project_id)}
        existing_types = self.list_vehicle_types(project_id)
        by_name = {vt.name.strip().casefold(): vt for vt in existing_types}

        with self.transaction() as conn:
            conn.execute("DELETE FROM terms WHERE project_id = ?", (project_id,))
            conn.execute("DELETE FROM items WHERE project_id = ?", (project_id,))

            inserted: list[tuple[int, ParsedItem]] = []
            used_type_ids: set[int] = set()
            for order, group in enumerate(groups, start=1):
                name = group.name.strip() or default_group_name
                existing = by_name.get(name.casefold())
                if existing is not None:
                    type_id = existing.id
                    current_count = len(
                        self.list_vehicles(project_id, type_id)
                    )
                    unit_count = (
                        group.unit_count
                        if group.unit_count > 0
                        else max(existing.unit_count, current_count)
                    )
                    conn.execute(
                        "UPDATE vehicle_types SET name = ?, sort_order = ? WHERE id = ?",
                        (name, order, type_id),
                    )
                else:
                    cur = conn.execute(
                        """INSERT INTO vehicle_types
                           (project_id, name, unit_count, sort_order)
                           VALUES (?, ?, ?, ?)""",
                        (project_id, name, max(0, group.unit_count), order),
                    )
                    type_id = int(cur.lastrowid)
                    unit_count = max(0, group.unit_count)
                used_type_ids.add(int(type_id))
                self._sync_type_vehicles(
                    conn, int(type_id), project_id, name, int(unit_count)
                )

                for index, item in enumerate(group.items, start=1):
                    cur = conn.execute(
                        """INSERT INTO items
                           (project_id, row_no, name, unit, unit_price,
                            total_qty, vehicle_type_id)
                           VALUES (?, ?, ?, ?, ?, ?, ?)""",
                        (
                            project_id,
                            item.source_row or index,
                            item.name,
                            item.unit,
                            int(item.unit_price),
                            int(item.total_qty),
                            int(type_id),
                        ),
                    )
                    inserted.append((int(cur.lastrowid), item))

            for vehicle_type in existing_types:
                if vehicle_type.id not in used_type_ids:
                    conn.execute(
                        "DELETE FROM vehicle_types WHERE id = ?", (vehicle_type.id,)
                    )

            for seq, term_name in enumerate(term_names, start=1):
                old = old_terms.get(term_name)
                invoice_date = old.invoice_date if old else None
                discount = old.discount_percent if old else 0
                cur = conn.execute(
                    """INSERT INTO terms
                       (project_id, name, seq, invoice_date, discount_percent, locked)
                       VALUES (?, ?, ?, ?, ?, 0)""",
                    (project_id, term_name, seq, invoice_date, discount),
                )
                term_id = int(cur.lastrowid)
                for item_id, item in inserted:
                    qty = (
                        item.term_qty[seq - 1]
                        if seq - 1 < len(item.term_qty)
                        else 0
                    )
                    conn.execute(
                        """INSERT INTO term_qty (term_id, item_id, qty)
                           VALUES (?, ?, ?)""",
                        (term_id, item_id, int(qty)),
                    )
            conn.execute(
                "INSERT INTO audit_log (project_id, ts, action, detail) VALUES (?, ?, ?, ?)",
                (
                    project_id,
                    self._now(),
                    "import_rab",
                    f"{len(inserted)} item, {len(groups)} jenis kendaraan, "
                    f"{len(term_names)} termin",
                ),
            )

    # --------------------------------------------------------------- term qty
    def get_term_qty(self, term_id: int) -> dict[int, int]:
        rows = self.conn.execute(
            "SELECT item_id, qty FROM term_qty WHERE term_id = ?", (term_id,)
        ).fetchall()
        return {int(r["item_id"]): int(r["qty"] or 0) for r in rows}

    def get_project_term_qty(self, project_id: int) -> dict[tuple[int, int], int]:
        rows = self.conn.execute(
            """SELECT tq.term_id, tq.item_id, tq.qty
               FROM term_qty tq
               JOIN terms t ON t.id = tq.term_id
               WHERE t.project_id = ?""",
            (project_id,),
        ).fetchall()
        return {
            (int(r["term_id"]), int(r["item_id"])): int(r["qty"] or 0)
            for r in rows
        }

    def set_term_qty(self, term_id: int, item_id: int, qty: int) -> None:
        with self.transaction() as conn:
            conn.execute(
                """INSERT INTO term_qty (term_id, item_id, qty) VALUES (?, ?, ?)
                   ON CONFLICT(term_id, item_id) DO UPDATE SET qty = excluded.qty""",
                (term_id, item_id, int(qty)),
            )

    def replace_term_qty(self, term_id: int, qty_by_item: dict[int, int]) -> None:
        with self.transaction() as conn:
            for item_id, qty in qty_by_item.items():
                conn.execute(
                    """INSERT INTO term_qty (term_id, item_id, qty) VALUES (?, ?, ?)
                       ON CONFLICT(term_id, item_id) DO UPDATE SET qty = excluded.qty""",
                    (term_id, item_id, int(qty)),
                )

    # ------------------------------------------------------------- allocations
    def get_term_allocations(self, term_id: int) -> dict[tuple[int, int], int]:
        rows = self.conn.execute(
            """SELECT item_id, vehicle_id, qty FROM allocations
               WHERE term_id = ? AND qty <> 0""",
            (term_id,),
        ).fetchall()
        return {
            (int(r["item_id"]), int(r["vehicle_id"])): int(r["qty"] or 0)
            for r in rows
        }

    def set_allocation(
        self, term_id: int, item_id: int, vehicle_id: int, qty: int
    ) -> None:
        with self.transaction() as conn:
            if int(qty) == 0:
                conn.execute(
                    """DELETE FROM allocations
                       WHERE term_id = ? AND item_id = ? AND vehicle_id = ?""",
                    (term_id, item_id, vehicle_id),
                )
            else:
                conn.execute(
                    """INSERT INTO allocations (term_id, item_id, vehicle_id, qty)
                       VALUES (?, ?, ?, ?)
                       ON CONFLICT(term_id, item_id, vehicle_id)
                       DO UPDATE SET qty = excluded.qty""",
                    (term_id, item_id, vehicle_id, int(qty)),
                )

    def replace_item_allocations(
        self, term_id: int, item_id: int, qty_by_vehicle: dict[int, int]
    ) -> None:
        with self.transaction() as conn:
            conn.execute(
                "DELETE FROM allocations WHERE term_id = ? AND item_id = ?",
                (term_id, item_id),
            )
            for vehicle_id, qty in qty_by_vehicle.items():
                if int(qty) > 0:
                    conn.execute(
                        """INSERT INTO allocations
                           (term_id, item_id, vehicle_id, qty) VALUES (?, ?, ?, ?)""",
                        (term_id, item_id, vehicle_id, int(qty)),
                    )

    def clear_term_allocations(self, term_id: int) -> None:
        with self.transaction() as conn:
            conn.execute("DELETE FROM allocations WHERE term_id = ?", (term_id,))

    def get_project_allocation_totals(
        self, project_id: int
    ) -> dict[tuple[int, int], int]:
        """Total alokasi per (term_id, item_id) di seluruh kendaraan."""
        rows = self.conn.execute(
            """SELECT a.term_id, a.item_id, SUM(a.qty) AS total
               FROM allocations a
               JOIN terms t ON t.id = a.term_id
               WHERE t.project_id = ?
               GROUP BY a.term_id, a.item_id""",
            (project_id,),
        ).fetchall()
        return {
            (int(r["term_id"]), int(r["item_id"])): int(r["total"] or 0)
            for r in rows
        }

    def get_item_history(
        self, project_id: int, item_id: int, before_seq: int
    ) -> dict[int, int]:
        rows = self.conn.execute(
            """SELECT a.vehicle_id AS vehicle_id, SUM(a.qty) AS total
               FROM allocations a
               JOIN terms t ON t.id = a.term_id
               WHERE t.project_id = ? AND a.item_id = ? AND t.seq < ?
               GROUP BY a.vehicle_id""",
            (project_id, item_id, before_seq),
        ).fetchall()
        return {int(r["vehicle_id"]): int(r["total"] or 0) for r in rows}

    # --------------------------------------------------------------- audit log
    def log(self, project_id: int | None, action: str, detail: str = "") -> None:
        with self.transaction() as conn:
            conn.execute(
                "INSERT INTO audit_log (project_id, ts, action, detail) VALUES (?, ?, ?, ?)",
                (project_id, self._now(), action, detail),
            )

    def list_log(self, project_id: int, limit: int = 300) -> list[sqlite3.Row]:
        return self.conn.execute(
            """SELECT * FROM audit_log WHERE project_id = ?
               ORDER BY id DESC LIMIT ?""",
            (project_id, limit),
        ).fetchall()

    # ---------------------------------------------------------------- settings
    def get_setting(self, key: str, default: str = "") -> str:
        row = self.conn.execute(
            "SELECT value FROM settings WHERE key = ?", (key,)
        ).fetchone()
        return row["value"] if row else default

    def set_setting(self, key: str, value: str) -> None:
        with self.transaction() as conn:
            conn.execute(
                """INSERT INTO settings (key, value) VALUES (?, ?)
                   ON CONFLICT(key) DO UPDATE SET value = excluded.value""",
                (key, value),
            )
