"""Tab alokasi qty termin ke kendaraan."""
from __future__ import annotations

from datetime import date

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..db import Database
from ..models import AllocIssue, Item, Project, Term, Vehicle, VehicleType
from ..services.allocation import (
    RemainderPlan,
    allocations_for_choice,
    build_remainder_plan,
    split_qty,
)
from ..services.validation import term_totals, validate_project, validate_term
from ..utils import format_rupiah
from .dialogs_alloc import RemainderDialog, RemainderJob, TermManagerDialog
from .style import AMBER, GREEN, MUTED, RED
from .widgets import Banner, Card, button, muted, setup_table

STATUS_COLORS = {
    "done": ("#EAF7EF", GREEN),
    "partial": ("#FFF8E1", AMBER),
    "over": ("#FDECEA", RED),
    "empty": ("#F1F5F9", MUTED),
}


class AllocationTab(QWidget):
    data_changed = Signal()

    def __init__(self, db: Database, parent: QWidget | None = None):
        super().__init__(parent)
        self.db = db
        self.project: Project | None = None
        self.term: Term | None = None
        self.vehicle_types: list[VehicleType] = []
        self.items: list[Item] = []
        self.vehicles: list[Vehicle] = []
        self.term_qty: dict[int, int] = {}
        self.alloc: dict[tuple[int, int], int] = {}
        self._updating = False
        self._build_ui()
        self._set_enabled(False)

    # ------------------------------------------------------------------ UI
    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(12)

        toolbar = Card()
        row1 = QHBoxLayout()
        row1.setSpacing(8)
        row1.addWidget(QLabel("Termin"))
        self.term_combo = QComboBox()
        self.term_combo.setMinimumWidth(220)
        self.term_combo.currentIndexChanged.connect(self._term_changed)
        row1.addWidget(self.term_combo)
        self.lock_badge = QLabel("")
        row1.addWidget(self.lock_badge)
        row1.addSpacing(12)
        row1.addWidget(QLabel("Jenis kendaraan"))
        self.type_combo = QComboBox()
        self.type_combo.setMinimumWidth(200)
        self.type_combo.currentIndexChanged.connect(self._type_changed)
        row1.addWidget(self.type_combo)
        row1.addSpacing(12)
        self.date_label = muted("")
        row1.addWidget(self.date_label)
        self.discount_label = muted("")
        row1.addWidget(self.discount_label)
        row1.addStretch(1)
        self.auto_btn = button("Bagi Otomatis", primary=True)
        self.auto_btn.clicked.connect(self._auto_allocate)
        row1.addWidget(self.auto_btn)
        self.clear_btn = button("Kosongkan")
        self.clear_btn.clicked.connect(self._clear_term)
        row1.addWidget(self.clear_btn)
        self.terms_btn = button("Kelola Termin")
        self.terms_btn.clicked.connect(self._manage_terms)
        row1.addWidget(self.terms_btn)
        toolbar.add_layout(row1)

        row2 = QHBoxLayout()
        row2.setSpacing(8)
        row2.addWidget(muted("Perubahan sel qty langsung tersimpan."))
        row2.addStretch(1)
        self.unlock_btn = button("Buka Kunci")
        self.unlock_btn.clicked.connect(self._unlock_term)
        row2.addWidget(self.unlock_btn)
        self.lock_btn = button("Kunci Termin", primary=True)
        self.lock_btn.clicked.connect(self._lock_term)
        row2.addWidget(self.lock_btn)
        toolbar.add_layout(row2)
        root.addWidget(toolbar)

        self.banner = Banner("", self)
        root.addWidget(self.banner)

        self.table = QTableWidget()
        setup_table(self.table, row_height=30)
        self.table.itemChanged.connect(self._on_cell_changed)
        self.table.setWordWrap(False)
        root.addWidget(self.table, 1)

        footer = QHBoxLayout()
        self.stats_label = muted("")
        footer.addWidget(self.stats_label)
        footer.addStretch(1)
        self.remaining_label = QLabel("")
        footer.addWidget(self.remaining_label)
        root.addLayout(footer)

    def _set_enabled(self, enabled: bool) -> None:
        for widget in (
            self.term_combo,
            self.type_combo,
            self.auto_btn,
            self.clear_btn,
            self.terms_btn,
            self.lock_btn,
            self.unlock_btn,
            self.table,
        ):
            widget.setEnabled(enabled)

    # --------------------------------------------------------------- project
    def set_project(self, project: Project | None) -> None:
        self.project = project
        self._set_enabled(project is not None)
        if not project:
            self.term_combo.clear()
            self.type_combo.clear()
            self.term = None
            self._clear_table()
            return
        self.refresh()

    def refresh(self) -> None:
        if not self.project:
            return
        self.project = self.db.get_project(self.project.id)
        terms = self.db.list_terms(self.project.id)
        current_id = self.term.id if self.term else None
        current_type_id = self.type_combo.currentData()
        self.vehicle_types = self.db.list_vehicle_types(self.project.id)
        self._updating = True
        self.term_combo.clear()
        for term in terms:
            self.term_combo.addItem(term.name, term.id)
        if current_id is not None:
            index = self.term_combo.findData(current_id)
            if index >= 0:
                self.term_combo.setCurrentIndex(index)

        self.type_combo.clear()
        if self.vehicle_types:
            for vehicle_type in self.vehicle_types:
                label = (
                    f"{vehicle_type.name} ({vehicle_type.unit_count} unit)"
                    if vehicle_type.unit_count
                    else vehicle_type.name
                )
                self.type_combo.addItem(label, vehicle_type.id)
            if current_type_id is not None:
                index = self.type_combo.findData(current_type_id)
                if index >= 0:
                    self.type_combo.setCurrentIndex(index)
        else:
            self.type_combo.addItem("Semua kendaraan", None)
        self._updating = False

        if not terms:
            self.term = None
            self._clear_table()
            self.banner.set_state(
                "warning",
                "Belum ada termin. Import RAB terlebih dahulu di tab Data Proyek.",
            )
            self.lock_badge.setText("")
            self.stats_label.setText("")
            self.remaining_label.setText("")
            for widget in (self.auto_btn, self.clear_btn, self.lock_btn, self.unlock_btn):
                widget.setEnabled(False)
            return

        if self.term_combo.currentIndex() < 0:
            self.term_combo.setCurrentIndex(0)
        self._load_term()

    def _term_changed(self) -> None:
        if self._updating or not self.project:
            return
        self._load_term()

    def _type_changed(self) -> None:
        if self._updating or not self.project:
            return
        self._load_term()

    def _load_term(self) -> None:
        if not self.project:
            return
        term_id = self.term_combo.currentData()
        if term_id is None:
            return
        self.term = self.db.get_term(int(term_id))
        if not self.term:
            return
        type_id = self.type_combo.currentData()
        selected_type = int(type_id) if type_id is not None else None
        self.items = self.db.list_items(self.project.id, selected_type)
        self.vehicles = self.db.list_vehicles(self.project.id, selected_type)
        self.term_qty = self.db.get_term_qty(self.term.id)
        self.alloc = self.db.get_term_allocations(self.term.id)

        invoice_date = self.term.date_obj or self.project.date_obj
        self.date_label.setText(f"Tanggal: {invoice_date.strftime('%d-%m-%Y')}")
        self.discount_label.setText(
            f"• Diskon: {self.term.discount_percent:g}%"
            if self.term.discount_percent
            else "• Diskon: 0%"
        )
        self._set_lock_badge()
        self._build_table()
        self._update_stats()
        self._update_validation()

    def _set_lock_badge(self) -> None:
        if not self.term:
            self.lock_badge.setText("")
            return
        if self.term.locked:
            self.lock_badge.setText("TERKUNCI")
            self.lock_badge.setStyleSheet(
                f"background:#EAF7EF;color:{GREEN};border:1px solid #C9E9D5;"
                "border-radius:5px;padding:3px 8px;font-weight:600;"
            )
        else:
            self.lock_badge.setText("TERBUKA")
            self.lock_badge.setStyleSheet(
                "background:#F1F5F9;color:#475569;border:1px solid #E2E8F0;"
                "border-radius:5px;padding:3px 8px;font-weight:600;"
            )

    # ----------------------------------------------------------------- table
    def _clear_table(self) -> None:
        self._updating = True
        self.table.clear()
        self.table.setRowCount(0)
        self.table.setColumnCount(0)
        self._updating = False

    def _build_table(self) -> None:
        self._updating = True
        vehicle_count = len(self.vehicles)
        fixed_before = 4
        fixed_after = 2
        self.table.clear()
        self.table.setColumnCount(fixed_before + vehicle_count + fixed_after)
        headers = ["No", "Nama Barang", "Satuan", "Qty"]
        headers += [v.display_name for v in self.vehicles]
        headers += ["Terbagi", "Status"]
        self.table.setHorizontalHeaderLabels(headers)
        self.table.setRowCount(len(self.items))
        for offset, vehicle in enumerate(self.vehicles):
            header_item = self.table.horizontalHeaderItem(fixed_before + offset)
            if header_item is not None:
                header_item.setToolTip(
                    f"{vehicle.display_name} — {vehicle.type_name or vehicle.vehicle_type}"
                )

        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.Fixed)
        header.setSectionResizeMode(1, QHeaderView.Stretch)
        header.setSectionResizeMode(2, QHeaderView.Fixed)
        header.setSectionResizeMode(3, QHeaderView.Fixed)
        for c in range(fixed_before, fixed_before + vehicle_count):
            header.setSectionResizeMode(c, QHeaderView.Fixed)
        header.setSectionResizeMode(fixed_before + vehicle_count, QHeaderView.Fixed)
        header.setSectionResizeMode(fixed_before + vehicle_count + 1, QHeaderView.Fixed)
        self.table.setColumnWidth(0, 45)
        self.table.setColumnWidth(2, 70)
        self.table.setColumnWidth(3, 65)
        for c in range(fixed_before, fixed_before + vehicle_count):
            self.table.setColumnWidth(c, 86)
        self.table.setColumnWidth(fixed_before + vehicle_count, 70)
        self.table.setColumnWidth(fixed_before + vehicle_count + 1, 110)
        self.table.horizontalHeader().setMinimumHeight(34)

        locked = bool(self.term and self.term.locked)
        editable_flags = Qt.ItemIsEnabled | Qt.ItemIsSelectable | Qt.ItemIsEditable
        readonly_flags = Qt.ItemIsEnabled | Qt.ItemIsSelectable

        for row, item in enumerate(self.items):
            no = QTableWidgetItem(str(row + 1))
            no.setTextAlignment(Qt.AlignCenter)
            no.setFlags(readonly_flags)
            self.table.setItem(row, 0, no)

            name = QTableWidgetItem(item.name)
            name.setFlags(readonly_flags)
            name.setToolTip(item.name)
            self.table.setItem(row, 1, name)

            unit = QTableWidgetItem(item.unit)
            unit.setFlags(readonly_flags)
            unit.setTextAlignment(Qt.AlignCenter)
            self.table.setItem(row, 2, unit)

            target = self.term_qty.get(item.id, 0)
            qty = QTableWidgetItem(str(target))
            qty.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            qty.setFlags(readonly_flags)
            qty.setBackground(QColor("#F7F8FA"))
            self.table.setItem(row, 3, qty)

            allocated = 0
            for offset, vehicle in enumerate(self.vehicles):
                value = self.alloc.get((item.id, vehicle.id), 0)
                allocated += value
                cell = QTableWidgetItem(str(value))
                cell.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                cell.setData(Qt.UserRole, value)
                cell.setFlags(editable_flags if not locked else readonly_flags)
                if value == 0:
                    cell.setForeground(QColor("#9AA5B1"))
                self.table.setItem(row, fixed_before + offset, cell)

            total_item = QTableWidgetItem(str(allocated))
            total_item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            total_item.setFlags(readonly_flags)
            total_item.setBackground(QColor("#F7F8FA"))
            self.table.setItem(row, fixed_before + vehicle_count, total_item)

            status = QTableWidgetItem("")
            status.setFlags(readonly_flags)
            status.setTextAlignment(Qt.AlignCenter)
            self.table.setItem(row, fixed_before + vehicle_count + 1, status)
            self._update_row(row)
        self._updating = False

    def _vehicle_column_start(self) -> int:
        return 4

    def _on_cell_changed(self, item: QTableWidgetItem) -> None:
        if self._updating or not self.term or self.term.locked:
            return
        start = self._vehicle_column_start()
        end = start + len(self.vehicles)
        if not (start <= item.column() < end):
            return
        row = item.row()
        if row < 0 or row >= len(self.items):
            return
        text = item.text().strip()
        if text == "":
            qty = 0
        else:
            try:
                qty = int(text)
            except ValueError:
                qty = -1
        if qty < 0:
            old = item.data(Qt.UserRole)
            self._updating = True
            item.setText(str(old if old is not None else 0))
            self._updating = False
            QMessageBox.warning(
                self, "Qty tidak valid", "Qty alokasi harus bilangan bulat ≥ 0."
            )
            return

        vehicle = self.vehicles[item.column() - start]
        item_obj = self.items[row]
        self.db.set_allocation(self.term.id, item_obj.id, vehicle.id, qty)
        key = (item_obj.id, vehicle.id)
        if qty:
            self.alloc[key] = qty
        else:
            self.alloc.pop(key, None)

        self._updating = True
        item.setData(Qt.UserRole, qty)
        item.setText(str(qty))
        item.setForeground(QColor("#263238") if qty else QColor("#9AA5B1"))
        self._updating = False
        self._update_row(row)
        self._update_stats()
        self._update_validation()

    # ------------------------------------------------------------- row status
    def _row_total(self, row: int) -> int:
        start = self._vehicle_column_start()
        total = 0
        for col in range(start, start + len(self.vehicles)):
            cell = self.table.item(row, col)
            if cell:
                try:
                    total += int(cell.text())
                except ValueError:
                    pass
        return total

    def _update_row(self, row: int) -> None:
        if row < 0 or row >= len(self.items):
            return
        item = self.items[row]
        target = self.term_qty.get(item.id, 0)
        actual = self._row_total(row)
        total_col = 4 + len(self.vehicles)
        status_col = total_col + 1
        self._updating = True
        total_item = self.table.item(row, total_col)
        if total_item:
            total_item.setText(str(actual))
        status = self.table.item(row, status_col)
        if status:
            if actual == target:
                key = "done"
                text = "Selesai" if target > 0 else "Tidak ada qty"
            elif actual == 0:
                key = "empty"
                text = "Belum"
            elif actual < target:
                key = "partial"
                text = f"Kurang {target - actual}"
            else:
                key = "over"
                text = f"Lebih {actual - target}"
            bg, fg = STATUS_COLORS[key]
            status.setText(text)
            status.setForeground(QColor(fg))
            status.setBackground(QColor(bg))
        if total_item:
            if actual == target:
                total_item.setForeground(QColor(GREEN))
            elif actual < target:
                total_item.setForeground(QColor(AMBER))
            else:
                total_item.setForeground(QColor(RED))
        self._updating = False

    def _update_stats(self) -> None:
        if not self.term:
            return
        stats = term_totals(self.db, self.term, self.items)
        self.stats_label.setText(
            f"Total qty termin: {stats['total_qty']} • terbagi: {stats['allocated']} • "
            f"nilai invoice: {format_rupiah(stats['value'])}"
        )
        remaining = stats["remaining"]
        if remaining == 0:
            self.remaining_label.setText("Sisa: 0")
            self.remaining_label.setStyleSheet(f"color:{GREEN};font-weight:600;")
        elif remaining > 0:
            self.remaining_label.setText(f"Sisa belum dibagi: {remaining}")
            self.remaining_label.setStyleSheet(f"color:{AMBER};font-weight:600;")
        else:
            self.remaining_label.setText(f"Kelebihan: {-remaining}")
            self.remaining_label.setStyleSheet(f"color:{RED};font-weight:600;")

    def _update_validation(self) -> None:
        if not self.project or not self.term:
            return
        project_issues = validate_project(self.db, self.project.id)
        scope_issues = validate_term(self.db, self.term, self.items, self.vehicles)
        all_issues = (
            scope_issues
            if len(self.items) == len(self.db.list_items(self.project.id))
            else validate_term(self.db, self.term)
        )
        self._project_issues = project_issues
        self._term_issues = all_issues
        self._scope_issues = scope_issues
        type_name = self.type_combo.currentText() or "jenis ini"
        if project_issues:
            self.banner.set_state(
                "error",
                f"{len(project_issues)} masalah qty RAB/termin. Perbaiki di tab "
                "'Data Proyek' (Edit Qty Termin) sebelum alokasi/export.",
            )
        elif scope_issues:
            self.banner.set_state(
                "warning",
                f"{len(scope_issues)} item belum seimbang di {self.term.name} "
                f"({type_name}). Klik Bagi Otomatis atau edit sel qty.",
            )
        elif all_issues:
            self.banner.set_state(
                "warning",
                f"Jenis kendaraan ini sudah seimbang, tetapi masih ada "
                f"{len(all_issues)} masalah di jenis kendaraan lain pada "
                f"{self.term.name}.",
            )
        elif self.term.locked:
            self.banner.set_state(
                "success",
                f"Termin {self.term.name} terkunci dan valid. Siap export invoice.",
            )
        else:
            self.banner.set_state(
                "success",
                f"Semua item di {self.term.name} sudah seimbang. "
                "Kunci termin sebelum export.",
            )

        locked = self.term.locked
        self.lock_btn.setEnabled(
            not locked and not project_issues and not all_issues
        )
        self.unlock_btn.setEnabled(locked)
        self.auto_btn.setEnabled(not locked and not project_issues)
        self.clear_btn.setEnabled(not locked and bool(self.alloc))
        self.table.setEditTriggers(
            QAbstractItemView.NoEditTriggers
            if locked
            else QAbstractItemView.DoubleClicked | QAbstractItemView.EditKeyPressed
        )

    # ---------------------------------------------------------------- actions
    def _manage_terms(self) -> None:
        if not self.project:
            return
        dialog = TermManagerDialog(self.db, self.project, self)
        if dialog.exec() == QDialog.Accepted and dialog.saved:
            self.refresh()
            self.data_changed.emit()

    def _clear_term(self) -> None:
        if not self.term:
            return
        answer = QMessageBox.question(
            self,
            "Kosongkan termin",
            f"Hapus semua alokasi di {self.term.name}?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return
        self.db.clear_term_allocations(self.term.id)
        self.db.log(self.project.id, "kosongkan_termin", self.term.name)
        self._load_term()
        self.data_changed.emit()

    def _lock_term(self) -> None:
        if not self.term:
            return
        issues = list(getattr(self, "_project_issues", [])) + list(
            getattr(self, "_term_issues", [])
        )
        if issues:
            self._show_issues("Termin belum bisa dikunci", issues)
            return
        self.db.set_term_locked(self.term.id, True)
        self.db.log(self.project.id, "kunci_termin", self.term.name)
        self._load_term()
        self.data_changed.emit()

    def _unlock_term(self) -> None:
        if not self.term:
            return
        answer = QMessageBox.question(
            self,
            "Buka kunci termin",
            f"Buka kunci {self.term.name}? Setelah dibuka, alokasi bisa diubah lagi. "
            "Invoice yang sudah diexport tidak otomatis berubah.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return
        self.db.set_term_locked(self.term.id, False)
        self.db.log(self.project.id, "buka_kunci_termin", self.term.name)
        self._load_term()
        self.data_changed.emit()

    def _show_issues(self, title: str, issues: list[AllocIssue]) -> None:
        box = QMessageBox(self)
        box.setWindowTitle(title)
        box.setIcon(QMessageBox.Warning)
        box.setText(
            f"{len(issues)} masalah ditemukan. Perbaiki dulu sebelum melanjutkan."
        )
        detail = "\n".join(
            f"- {issue.item_name or '(umum)'}: {issue.message}" for issue in issues[:50]
        )
        if len(issues) > 50:
            detail += f"\n... dan {len(issues) - 50} lainnya"
        box.setDetailedText(detail)
        box.exec()

    def _auto_allocate(self) -> None:
        if not self.project or not self.term:
            return
        if self.term.locked:
            QMessageBox.information(self, "Terkunci", "Buka kunci termin terlebih dahulu.")
            return
        vehicle_types = self.db.list_vehicle_types(self.project.id)
        if vehicle_types:
            scopes = [
                (
                    vehicle_type.name,
                    self.db.list_items(self.project.id, vehicle_type.id),
                    self.db.list_vehicles(self.project.id, vehicle_type.id),
                )
                for vehicle_type in vehicle_types
            ]
        else:
            scopes = [
                (
                    "",
                    self.db.list_items(self.project.id),
                    self.db.list_vehicles(self.project.id),
                )
            ]
        if not any(vehicles for _name, _items, vehicles in scopes):
            QMessageBox.warning(
                self,
                "Belum ada kendaraan",
                "RAB belum punya unit kendaraan. Import RAB multi-jenis atau "
                "tambahkan kendaraan di tab Data Proyek.",
            )
            return
        project_issues = validate_project(self.db, self.project.id)
        if project_issues:
            self._show_issues("Qty RAB/termin belum valid", project_issues)
            return

        self.term_qty = self.db.get_term_qty(self.term.id)
        self.alloc = self.db.get_term_allocations(self.term.id)
        vehicle_labels = {
            vehicle.id: (
                vehicle.display_name,
                vehicle.type_name or vehicle.vehicle_type or "",
            )
            for _name, _items, vehicles in scopes
            for vehicle in vehicles
        }

        filled = 0
        partial = 0
        no_vehicle_items = 0
        jobs: list[RemainderJob] = []
        plans: dict[int, RemainderPlan] = {}

        for scope_name, items, vehicles in scopes:
            vehicle_ids = [v.id for v in vehicles]
            if not vehicle_ids:
                no_vehicle_items += sum(
                    1 for item in items if self.term_qty.get(item.id, 0) > 0
                )
                continue
            order = {vid: index for index, vid in enumerate(vehicle_ids)}
            for item in items:
                target = self.term_qty.get(item.id, 0)
                if target <= 0:
                    continue
                existing = sum(
                    self.alloc.get((item.id, vid), 0) for vid in vehicle_ids
                )
                if existing == target:
                    continue
                if existing > 0:
                    partial += 1
                    continue

                base, remainder = split_qty(target, len(vehicle_ids))
                if remainder == 0:
                    self.db.replace_item_allocations(
                        self.term.id,
                        item.id,
                        {vid: base for vid in vehicle_ids},
                    )
                    filled += 1
                else:
                    history = self.db.get_item_history(
                        self.project.id, item.id, self.term.seq
                    )
                    plan = build_remainder_plan(
                        item.id, target, vehicle_ids, history, order
                    )
                    plans[item.id] = plan
                    display_name = (
                        f"{scope_name} — {item.name}"
                        if scope_name and len(scopes) > 1
                        else item.name
                    )
                    jobs.append(
                        RemainderJob(
                            item_id=item.id,
                            item_name=display_name,
                            unit=item.unit,
                            plan=plan,
                            history=history,
                        )
                    )

        applied_remainders = 0
        skipped_remainders = 0
        if jobs:
            dialog = RemainderDialog(
                jobs, vehicle_labels, self, term_name=self.term.name
            )
            if dialog.exec() == QDialog.Accepted:
                for item_id, chosen in dialog.choices.items():
                    plan = plans[item_id]
                    self.db.replace_item_allocations(
                        self.term.id,
                        item_id,
                        allocations_for_choice(plan, chosen),
                    )
                    applied_remainders += 1
                skipped_remainders = len(jobs) - applied_remainders
            else:
                skipped_remainders = len(jobs)

        all_items = self.db.list_items(self.project.id)
        total_items = sum(
            1 for item in all_items if self.term_qty.get(item.id, 0) > 0
        )
        self.db.log(
            self.project.id,
            "bagi_otomatis",
            f"{self.term.name}: {filled} item otomatis, "
            f"{applied_remainders} sisa dikonfirmasi, "
            f"{partial} item sebagian dilewati, {skipped_remainders} sisa belum, "
            f"{no_vehicle_items} item tanpa kendaraan",
        )
        self._load_term()
        self.data_changed.emit()

        remaining_issues = validate_term(self.db, self.term)
        lines = [
            f"{filled} item habis dibagi langsung terisi.",
            f"{applied_remainders} item sisa dikonfirmasi.",
            f"Total item diproses: {total_items}.",
        ]
        if no_vehicle_items:
            lines.append(
                f"{no_vehicle_items} item dilewati karena jenis kendaraannya "
                "belum punya unit."
            )
        if partial:
            lines.append(
                f"{partial} item sudah terisi sebagian dan dilewati. "
                "Selesaikan manual atau kosongkan termin lalu ulangi."
            )
        if skipped_remainders:
            lines.append(
                f"{skipped_remainders} item sisa belum diputuskan. "
                "Klik Bagi Otomatis lagi atau isi manual."
            )
        if remaining_issues:
            lines.append(f"Masih ada {len(remaining_issues)} item belum seimbang.")
        else:
            lines.append("Semua item sudah seimbang dan siap dikunci.")
        QMessageBox.information(self, "Bagi Otomatis", "\n".join(lines))
