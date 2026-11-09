"""Tab data proyek: info, RAB, dan kendaraan."""
from __future__ import annotations

from datetime import date

from PySide6.QtCore import QDate, Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDateEdit,
    QDialog,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..db import Database
from ..models import Project
from ..services.rab_parser import RabParseError, parse_rab
from ..services.validation import validate_project
from ..services.vehicle_parser import VehicleParseError, parse_vehicle_file
from ..utils import format_rupiah, parse_iso_date
from .dialogs_alloc import TermManagerDialog
from .dialogs_misc import VehicleDialog, VehicleImportDialog
from .dialogs_rab import (
    ItemsDialog,
    RabImportConfirmDialog,
    RabMappingDialog,
    TermQtyDialog,
)
from .style import GREEN, MUTED, RED
from .widgets import Banner, Card, button, money_text, muted, row_layout, setup_table


class ProjectTab(QWidget):
    data_changed = Signal()

    def __init__(self, db: Database, parent: QWidget | None = None):
        super().__init__(parent)
        self.db = db
        self.project: Project | None = None
        self.vehicle_types = []
        self._vehicle_rows = []
        self._updating_vehicle_table = False
        self._updating_prefix_table = False
        self._build_ui()
        self._set_enabled(False)

    # ------------------------------------------------------------------ UI
    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        outer.addWidget(scroll)

        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(14)
        scroll.setWidget(content)

        # --- informasi proyek
        info = Card("Informasi Proyek")
        form = QFormLayout()
        form.setSpacing(10)
        form.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.name_edit = QLineEdit()
        self.client_edit = QLineEdit()
        self.client_edit.setPlaceholderText("mis. POLRESTA BANDUNG")
        self.address_edit = QLineEdit()
        self.address_edit.setPlaceholderText("Alamat klien yang tampil di invoice")
        self.po_edit = QLineEdit()
        self.po_edit.setPlaceholderText("mis. VXN-")
        self.po_edit.setToolTip(
            "Dipakai hanya untuk jenis kendaraan yang prefix-nya belum diisi. "
            "Untuk pengaturan per jenis, gunakan tabel di bawah."
        )
        self.type_edit = QLineEdit()
        self.type_edit.setPlaceholderText("mis. Yamaha Vixion")
        self.date_edit = QDateEdit()
        self.date_edit.setCalendarPopup(True)
        self.date_edit.setDisplayFormat("dd MMM yyyy")
        self.date_format_combo = QComboBox()
        self.date_format_combo.addItem("Tanggal lengkap (1 Juli 2026)", "full")
        self.date_format_combo.addItem("Bulan dan tahun (Juli 2026)", "bulan_tahun")
        form.addRow("Nama proyek", self.name_edit)
        form.addRow("Kepada Yth (klien)", self.client_edit)
        form.addRow("Alamat klien", self.address_edit)
        form.addRow("Prefix No PO (default)", self.po_edit)
        form.addRow("Tipe kendaraan default", self.type_edit)
        form.addRow("Tanggal invoice", self.date_edit)
        form.addRow("Format tanggal invoice", self.date_format_combo)
        info.add_layout(form)
        save_row = QHBoxLayout()
        save_row.addStretch(1)
        self.save_info_btn = button("Simpan Informasi", primary=True)
        self.save_info_btn.clicked.connect(self._save_info)
        save_row.addWidget(self.save_info_btn)
        info.add_layout(save_row)
        layout.addWidget(info)

        # --- RAB
        rab = Card("RAB & Termin")
        self.rab_summary = QLabel("RAB belum diimpor.")
        self.rab_summary.setWordWrap(True)
        rab.add(self.rab_summary)
        self.rab_banner = Banner("", self)
        rab.add(self.rab_banner)
        rab_buttons = QHBoxLayout()
        rab_buttons.setSpacing(8)
        self.import_rab_btn = button("Import RAB", primary=True)
        self.import_rab_btn.clicked.connect(self._import_rab)
        rab_buttons.addWidget(self.import_rab_btn)
        self.items_btn = button("Lihat Item && Sisa")
        self.items_btn.clicked.connect(self._show_items)
        rab_buttons.addWidget(self.items_btn)
        self.term_qty_btn = button("Edit Qty Termin")
        self.term_qty_btn.clicked.connect(self._edit_term_qty)
        rab_buttons.addWidget(self.term_qty_btn)
        self.terms_btn = button("Kelola Termin")
        self.terms_btn.clicked.connect(self._manage_terms)
        rab_buttons.addWidget(self.terms_btn)
        rab_buttons.addStretch(1)
        rab.add_layout(rab_buttons)

        self.issues_table = QTableWidget()
        self.issues_table.setColumnCount(3)
        self.issues_table.setHorizontalHeaderLabels(["Baris", "Item", "Masalah"])
        setup_table(self.issues_table, read_only=True, row_height=27)
        self.issues_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Fixed)
        self.issues_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Fixed)
        self.issues_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.issues_table.setColumnWidth(0, 60)
        self.issues_table.setColumnWidth(1, 220)
        self.issues_table.setMinimumHeight(130)
        self.issues_table.setMaximumHeight(220)
        rab.add(self.issues_table)
        layout.addWidget(rab)

        # --- prefix No PO per jenis (satu input per jenis, berlaku untuk semua unit)
        prefix_card = Card("Prefix No PO per Jenis Kendaraan")
        prefix_note = muted(
            "Cukup isi sekali untuk setiap jenis kendaraan. Prefix otomatis "
            "dipakai untuk semua unit pada jenis tersebut; No PO tiap unit = "
            "prefix + nomor kendaraan (atau label unit bila plat kosong). "
            "Contoh: HYT-, VXN-, SCRP-, NMAX-."
        )
        prefix_note.setWordWrap(True)
        prefix_card.add(prefix_note)
        self.prefix_table = QTableWidget()
        self.prefix_table.setColumnCount(4)
        self.prefix_table.setHorizontalHeaderLabels(
            ["Jenis Kendaraan", "Jumlah Unit", "Prefix No PO", "Contoh No PO"]
        )
        setup_table(self.prefix_table, row_height=30)
        self.prefix_table.setEditTriggers(
            QAbstractItemView.DoubleClicked | QAbstractItemView.EditKeyPressed
        )
        self.prefix_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.prefix_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Fixed)
        self.prefix_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Fixed)
        self.prefix_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        self.prefix_table.setColumnWidth(1, 100)
        self.prefix_table.setColumnWidth(2, 160)
        self.prefix_table.setMinimumHeight(150)
        self.prefix_table.itemChanged.connect(self._prefix_changed)
        prefix_card.add(self.prefix_table)
        layout.addWidget(prefix_card)

        # --- kendaraan
        vehicles = Card("Kendaraan per Jenis")
        vehicles_header = QHBoxLayout()
        vehicles_header.setSpacing(8)
        self.vehicle_count = QLabel("0 kendaraan")
        self.vehicle_count.setStyleSheet(f"color: {MUTED};")
        vehicles_header.addWidget(self.vehicle_count)
        vehicles_header.addStretch(1)
        vehicles_header.addWidget(QLabel("Filter jenis"))
        self.vehicle_filter = QComboBox()
        self.vehicle_filter.setMinimumWidth(220)
        self.vehicle_filter.currentIndexChanged.connect(self._vehicle_filter_changed)
        vehicles_header.addWidget(self.vehicle_filter)
        vehicles.add_layout(vehicles_header)
        self.vehicle_table = QTableWidget()
        self.vehicle_table.setColumnCount(3)
        self.vehicle_table.setHorizontalHeaderLabels(
            ["Jenis Kendaraan", "Unit", "No Kendaraan (Plat)"]
        )
        setup_table(self.vehicle_table, row_height=30)
        self.vehicle_table.setEditTriggers(
            QAbstractItemView.DoubleClicked | QAbstractItemView.EditKeyPressed
        )
        self.vehicle_table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.Stretch
        )
        self.vehicle_table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.Fixed
        )
        self.vehicle_table.horizontalHeader().setSectionResizeMode(
            2, QHeaderView.Stretch
        )
        self.vehicle_table.setColumnWidth(1, 65)
        self.vehicle_table.itemChanged.connect(self._plate_changed)
        self.vehicle_table.setMinimumHeight(240)
        vehicles.add(self.vehicle_table)
        note = muted(
            "Plat bisa dikosongkan. Klik dua kali pada kolom No Kendaraan untuk "
            "mengisi plat; perubahan langsung tersimpan."
        )
        note.setWordWrap(True)
        vehicles.add(note)
        vbuttons = QHBoxLayout()
        vbuttons.setSpacing(8)
        self.add_vehicle_btn = button("Tambah Unit")
        self.add_vehicle_btn.clicked.connect(self._add_vehicle)
        vbuttons.addWidget(self.add_vehicle_btn)
        self.edit_vehicle_btn = button("Edit Plat")
        self.edit_vehicle_btn.clicked.connect(self._edit_vehicle)
        vbuttons.addWidget(self.edit_vehicle_btn)
        self.del_vehicle_btn = button("Hapus", danger=True)
        self.del_vehicle_btn.clicked.connect(self._delete_vehicle)
        vbuttons.addWidget(self.del_vehicle_btn)
        self.import_vehicle_btn = button("Import Plat Excel")
        self.import_vehicle_btn.clicked.connect(self._import_vehicles)
        vbuttons.addWidget(self.import_vehicle_btn)
        vbuttons.addStretch(1)
        vehicles.add_layout(vbuttons)
        layout.addWidget(vehicles, 1)

    def _set_enabled(self, enabled: bool) -> None:
        for cls in (QLineEdit, QDateEdit, QPushButton, QTableWidget, QComboBox):
            for widget in self.findChildren(cls):
                widget.setEnabled(enabled)

    # --------------------------------------------------------------- project
    def set_project(self, project: Project | None) -> None:
        self.project = project
        enabled = project is not None
        self._set_enabled(enabled)
        if not project:
            self.name_edit.clear()
            self.vehicle_filter.clear()
            self.vehicle_table.setRowCount(0)
            self._vehicle_rows = []
            return
        self.name_edit.setText(project.name)
        self.client_edit.setText(project.client_name)
        self.address_edit.setText(project.client_address)
        self.po_edit.setText(project.po_prefix)
        self.type_edit.setText(project.vehicle_type)
        d = project.date_obj
        self.date_edit.setDate(QDate(d.year, d.month, d.day))
        fmt_index = self.date_format_combo.findData(project.date_format or "full")
        self.date_format_combo.setCurrentIndex(fmt_index if fmt_index >= 0 else 0)
        self.refresh()

    def refresh(self) -> None:
        if not self.project:
            return
        self.project = self.db.get_project(self.project.id)
        if not self.project:
            return
        items = self.db.list_items(self.project.id)
        terms = self.db.list_terms(self.project.id)
        self.vehicle_types = self.db.list_vehicle_types(self.project.id)
        all_vehicles = self.db.list_vehicles(self.project.id)
        total_qty = sum(item.total_qty for item in items)
        total_value = sum(item.total_qty * item.unit_price for item in items)

        if items:
            type_text = (
                f"<b>{len(self.vehicle_types)} jenis kendaraan</b> • "
                if self.vehicle_types
                else ""
            )
            self.rab_summary.setText(
                f"{type_text}<b>{len(items)} item</b> • "
                f"<b>{len(terms)} termin</b> "
                f"({', '.join(term.name for term in terms) if terms else 'belum ada'}) "
                f"• total qty <b>{f'{total_qty:,}'.replace(',', '.')}</b> • nilai RAB "
                f"<b>{format_rupiah(total_value)}</b>"
            )
        else:
            self.rab_summary.setText(
                "RAB belum diimpor. Klik <b>Import RAB</b> dan pilih file Excel."
            )

        issues = validate_project(self.db, self.project.id)
        self.issues_table.setRowCount(len(issues))
        for row, issue in enumerate(issues):
            values = [str(issue.row_no or ""), issue.item_name, issue.message]
            for col, value in enumerate(values):
                cell = QTableWidgetItem(value)
                if col == 0:
                    cell.setTextAlignment(Qt.AlignCenter)
                cell.setFlags(cell.flags() & ~Qt.ItemIsEditable)
                if col == 2:
                    cell.setForeground(QColor(RED))
                self.issues_table.setItem(row, col, cell)
        self.issues_table.setVisible(bool(issues))
        if not items:
            self.rab_banner.set_state(
                "info", "Belum ada RAB. Import file Excel untuk mulai."
            )
        elif issues:
            self.rab_banner.set_state(
                "error",
                f"{len(issues)} masalah qty. Perbaiki lewat Edit Qty Termin sebelum "
                "mengalokasikan atau export.",
            )
        else:
            self.rab_banner.set_state(
                "success", "Validasi lolos: total qty termin = qty RAB untuk semua item."
            )

        self._updating_vehicle_table = True
        self.vehicle_filter.blockSignals(True)
        current_filter = self.vehicle_filter.currentData()
        self.vehicle_filter.clear()
        self.vehicle_filter.addItem("Semua jenis", None)
        for vehicle_type in self.vehicle_types:
            label = (
                f"{vehicle_type.name} ({vehicle_type.unit_count} unit)"
                if vehicle_type.unit_count
                else vehicle_type.name
            )
            self.vehicle_filter.addItem(label, vehicle_type.id)
        if current_filter is not None:
            index = self.vehicle_filter.findData(current_filter)
            if index >= 0:
                self.vehicle_filter.setCurrentIndex(index)
        self.vehicle_filter.blockSignals(False)
        filter_id = self.vehicle_filter.currentData()
        vehicles = [
            vehicle
            for vehicle in all_vehicles
            if filter_id is None or vehicle.vehicle_type_id == int(filter_id)
        ]
        self._vehicle_rows = vehicles

        self.vehicle_table.setRowCount(len(vehicles))
        for row, vehicle in enumerate(vehicles):
            vtype = QTableWidgetItem(vehicle.type_name or vehicle.vehicle_type)
            vtype.setData(Qt.UserRole, vehicle.id)
            vtype.setFlags(vtype.flags() & ~Qt.ItemIsEditable)
            self.vehicle_table.setItem(row, 0, vtype)

            unit = QTableWidgetItem(str(vehicle.unit_no or ""))
            unit.setTextAlignment(Qt.AlignCenter)
            unit.setFlags(unit.flags() & ~Qt.ItemIsEditable)
            self.vehicle_table.setItem(row, 1, unit)

            plate = QTableWidgetItem(vehicle.plate)
            plate.setData(Qt.UserRole, vehicle.id)
            plate.setToolTip(
                "Kosongkan bila plat belum tersedia. "
                f"Label sementara: {vehicle.display_name}"
            )
            self.vehicle_table.setItem(row, 2, plate)
        self._updating_vehicle_table = False

        filled = sum(1 for vehicle in all_vehicles if vehicle.plate)
        self.vehicle_count.setText(
            f"{len(all_vehicles)} unit • {len(self.vehicle_types)} jenis • "
            f"{filled} plat terisi"
        )

        # Populate prefix table (satu baris per jenis kendaraan)
        self._updating_prefix_table = True
        self.prefix_table.setRowCount(len(self.vehicle_types))
        for row, vehicle_type in enumerate(self.vehicle_types):
            type_vehicles = [
                vehicle
                for vehicle in all_vehicles
                if vehicle.vehicle_type_id == vehicle_type.id
            ]
            unit_count = len(type_vehicles) or vehicle_type.unit_count

            name_item = QTableWidgetItem(vehicle_type.name)
            name_item.setFlags(name_item.flags() & ~Qt.ItemIsEditable)
            self.prefix_table.setItem(row, 0, name_item)

            unit_item = QTableWidgetItem(str(unit_count))
            unit_item.setTextAlignment(Qt.AlignCenter)
            unit_item.setFlags(unit_item.flags() & ~Qt.ItemIsEditable)
            self.prefix_table.setItem(row, 1, unit_item)

            prefix_item = QTableWidgetItem(vehicle_type.po_prefix or "")
            prefix_item.setData(Qt.UserRole, vehicle_type.id)
            prefix_item.setToolTip(
                "Isi sekali di sini. Prefix berlaku untuk semua unit jenis ini."
            )
            self.prefix_table.setItem(row, 2, prefix_item)

            example_label = (
                type_vehicles[0].plate or type_vehicles[0].display_name
                if type_vehicles
                else "<nomor kendaraan>"
            )
            example_item = QTableWidgetItem(f"{vehicle_type.po_prefix or ''}{example_label}")
            example_item.setFlags(example_item.flags() & ~Qt.ItemIsEditable)
            example_item.setToolTip(
                "Contoh No PO untuk unit pertama. Unit lain memakai prefix yang sama "
                "dengan nomor kendaraannya masing-masing."
            )
            self.prefix_table.setItem(row, 3, example_item)
        self._updating_prefix_table = False

        has_rab = bool(items)
        self.items_btn.setEnabled(has_rab)
        self.term_qty_btn.setEnabled(has_rab and bool(terms))
        self.terms_btn.setEnabled(bool(terms) or has_rab)

    def _save_info(self) -> None:
        if not self.project:
            return
        name = self.name_edit.text().strip()
        if not name:
            QMessageBox.warning(self, "Belum lengkap", "Nama proyek wajib diisi.")
            return
        qdate = self.date_edit.date()
        self.db.update_project(
            self.project.id,
            name=name,
            client_name=self.client_edit.text().strip(),
            client_address=self.address_edit.text().strip(),
            po_prefix=self.po_edit.text().strip(),
            vehicle_type=self.type_edit.text().strip(),
            invoice_date=date(qdate.year(), qdate.month(), qdate.day()),
            date_format=self.date_format_combo.currentData() or "full",
        )
        self.db.log(self.project.id, "edit_proyek", f"Informasi proyek diperbarui")
        self.project = self.db.get_project(self.project.id)
        self.refresh()
        self.data_changed.emit()

    # ------------------------------------------------------------------- RAB
    def _import_rab(self) -> None:
        if not self.project:
            return
        path, _ = QFileDialog.getOpenFileName(
            self, "Pilih file Excel RAB", "", "Excel (*.xlsx *.xlsm)"
        )
        if not path:
            return
        try:
            dialog = RabMappingDialog(path, self)
        except RabParseError as exc:
            QMessageBox.critical(self, "Gagal membaca file", str(exc))
            return
        if dialog.exec() != QDialog.Accepted or not dialog.mapping:
            return
        try:
            result = parse_rab(path, dialog.mapping, single_term_name=dialog.mapping.single_term_name)
        except RabParseError as exc:
            QMessageBox.critical(self, "Gagal memproses RAB", str(exc))
            return
        confirm = RabImportConfirmDialog(result, self)
        if confirm.exec() != QDialog.Accepted:
            return

        existing_items = self.db.list_items(self.project.id)
        existing_terms = self.db.list_terms(self.project.id)
        if existing_items or existing_terms:
            answer = QMessageBox.question(
                self,
                "Ganti RAB?",
                "Proyek ini sudah punya RAB/termin. Import ulang akan MENGHAPUS "
                "seluruh item, termin, dan alokasi yang ada. Lanjutkan?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if answer != QMessageBox.Yes:
                return
        self.db.replace_rab(
            self.project.id, result.term_names, groups=result.groups
        )
        self.refresh()
        self.data_changed.emit()
        QMessageBox.information(
            self,
            "Import selesai",
            f"{len(result.items)} item, {len(result.groups)} jenis kendaraan, dan "
            f"{len(result.term_names)} termin berhasil diimpor.",
        )

    def _show_items(self) -> None:
        if not self.project:
            return
        ItemsDialog(self.db, self.project, self).exec()

    def _edit_term_qty(self) -> None:
        if not self.project:
            return
        dialog = TermQtyDialog(self.db, self.project, self)
        if dialog.exec() == QDialog.Accepted and dialog.saved:
            self.refresh()
            self.data_changed.emit()

    def _manage_terms(self) -> None:
        if not self.project:
            return
        dialog = TermManagerDialog(self.db, self.project, self)
        if dialog.exec() == QDialog.Accepted and dialog.saved:
            self.refresh()
            self.data_changed.emit()

    # -------------------------------------------------------------- kendaraan
    def _vehicle_filter_changed(self) -> None:
        if getattr(self, "_updating_vehicle_table", False):
            return
        self.refresh()

    def _selected_vehicle(self):
        if not self.project:
            return None
        row = self.vehicle_table.currentRow()
        if row < 0 or row >= len(self._vehicle_rows):
            return None
        return self._vehicle_rows[row]

    def _add_vehicle(self) -> None:
        if not self.project:
            return
        filter_id = self.vehicle_filter.currentData()
        if filter_id is None and self.vehicle_types:
            filter_id = self.vehicle_types[0].id
        group = (
            next((item for item in self.vehicle_types if item.id == filter_id), None)
            if filter_id is not None
            else None
        )
        dialog = VehicleDialog(
            self,
            vehicle_type=group.name if group else self.project.vehicle_type,
            title="Tambah Unit Kendaraan",
            allow_blank=True,
        )
        if dialog.exec() != QDialog.Accepted:
            return
        self._insert_vehicle(dialog.plate, filter_id)

    def _insert_vehicle(self, plate: str, vehicle_type_id: int | None) -> None:
        if not self.project:
            return
        plate = (plate or "").strip()
        existing = {
            v.plate.strip().casefold()
            for v in self.db.list_vehicles(self.project.id)
            if v.plate.strip()
        }
        if plate and plate.casefold() in existing:
            QMessageBox.warning(self, "Duplikat", f"Kendaraan '{plate}' sudah ada.")
            return
        self.db.add_vehicle(
            self.project.id, plate, vehicle_type_id=vehicle_type_id
        )
        self.db.log(self.project.id, "tambah_kendaraan", plate or "(tanpa plat)")
        self.refresh()
        self.data_changed.emit()

    def _edit_vehicle(self) -> None:
        vehicle = self._selected_vehicle()
        if not vehicle or not self.project:
            if self.vehicle_table.currentRow() < 0:
                QMessageBox.information(self, "Pilih kendaraan", "Pilih baris kendaraan dulu.")
                return
            return
        dialog = VehicleDialog(
            self,
            plate=vehicle.plate,
            vehicle_type=vehicle.type_name or vehicle.vehicle_type,
            title="Edit No Kendaraan (Plat)",
            allow_blank=True,
        )
        if dialog.exec() != QDialog.Accepted:
            return
        existing = {
            v.plate.strip().casefold()
            for v in self.db.list_vehicles(self.project.id)
            if v.id != vehicle.id and v.plate.strip()
        }
        if dialog.plate and dialog.plate.casefold() in existing:
            QMessageBox.warning(self, "Duplikat", f"Kendaraan '{dialog.plate}' sudah ada.")
            return
        self.db.update_vehicle(
            vehicle.id,
            dialog.plate,
            vehicle.type_name or vehicle.vehicle_type,
        )
        self.db.log(
            self.project.id,
            "edit_kendaraan",
            f"{vehicle.plate or '(tanpa plat)'} -> {dialog.plate or '(tanpa plat)'}",
        )
        self.refresh()
        self.data_changed.emit()

    def _plate_changed(self, item: QTableWidgetItem) -> None:
        if getattr(self, "_updating_vehicle_table", False):
            return
        if item.column() != 2 or not self.project:
            return
        row = item.row()
        if row < 0 or row >= len(self._vehicle_rows):
            return
        vehicle = self._vehicle_rows[row]
        new_plate = item.text().strip()
        if new_plate == vehicle.plate:
            return
        if new_plate:
            existing = {
                v.plate.strip().casefold()
                for v in self.db.list_vehicles(self.project.id)
                if v.id != vehicle.id and v.plate.strip()
            }
            if new_plate.casefold() in existing:
                self._updating_vehicle_table = True
                item.setText(vehicle.plate)
                self._updating_vehicle_table = False
                QMessageBox.warning(
                    self, "Duplikat", f"Kendaraan '{new_plate}' sudah ada."
                )
                return
        self.db.update_vehicle(
            vehicle.id,
            new_plate,
            vehicle.type_name or vehicle.vehicle_type,
        )
        self.db.log(
            self.project.id,
            "edit_kendaraan",
            f"{vehicle.plate or '(tanpa plat)'} -> {new_plate or '(tanpa plat)'}",
        )
        vehicle.plate = new_plate
        self.vehicle_count.setText(
            f"{len(self.db.list_vehicles(self.project.id))} unit • "
            f"{len(self.vehicle_types)} jenis • "
            f"{sum(1 for v in self.db.list_vehicles(self.project.id) if v.plate)} plat terisi"
        )

    def _prefix_changed(self, item: QTableWidgetItem) -> None:
        if getattr(self, "_updating_prefix_table", False):
            return
        if item.column() != 2 or not self.project:
            return
        vehicle_type_id = item.data(Qt.UserRole)
        if vehicle_type_id is None:
            return
        new_prefix = item.text().strip()
        self.db.update_vehicle_type_po_prefix(int(vehicle_type_id), new_prefix)
        self.db.log(
            self.project.id,
            "edit_prefix",
            f"Prefix jenis {vehicle_type_id} diubah menjadi '{new_prefix}'",
        )

        # Perbarui contoh No PO tanpa memicu sinyal lain.
        vehicles = self.db.list_vehicles(self.project.id, int(vehicle_type_id))
        label = (
            vehicles[0].plate or vehicles[0].display_name
            if vehicles
            else "<nomor kendaraan>"
        )
        self._updating_prefix_table = True
        example = self.prefix_table.item(item.row(), 3)
        if example is not None:
            example.setText(f"{new_prefix}{label}")
        self._updating_prefix_table = False

        self.data_changed.emit()

    def _delete_vehicle(self) -> None:
        vehicle = self._selected_vehicle()
        if not vehicle or not self.project:
            QMessageBox.information(self, "Pilih kendaraan", "Pilih baris kendaraan dulu.")
            return
        answer = QMessageBox.question(
            self,
            "Hapus unit",
            f"Hapus '{vehicle.display_name}'? Semua alokasi unit ini di seluruh "
            "termin juga akan terhapus.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return
        self.db.delete_vehicle(vehicle.id)
        self.db.log(self.project.id, "hapus_kendaraan", vehicle.display_name)
        self.refresh()
        self.data_changed.emit()

    def _import_vehicles(self) -> None:
        if not self.project:
            return
        path, _ = QFileDialog.getOpenFileName(
            self, "Pilih file daftar plat kendaraan", "", "Excel (*.xlsx *.xlsm)"
        )
        if not path:
            return
        try:
            result = parse_vehicle_file(path)
        except VehicleParseError as exc:
            QMessageBox.critical(self, "Gagal membaca kendaraan", str(exc))
            return
        preview = VehicleImportDialog(result, self)
        if preview.exec() != QDialog.Accepted:
            return
        existing = self.db.list_vehicles(self.project.id)
        if existing:
            answer = QMessageBox.question(
                self,
                "Ganti plat kendaraan?",
                "Plat yang ada akan dikosongkan lalu diisi dari file sesuai jenis "
                "kendaraan. Alokasi qty tidak dihapus. Lanjutkan?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if answer != QMessageBox.Yes:
                return
        filter_id = self.vehicle_filter.currentData()
        assigned, unknown, overflow = self.db.assign_vehicle_plates(
            self.project.id,
            result.vehicles,
            default_type_id=int(filter_id) if filter_id is not None else None,
        )
        self.db.log(
            self.project.id,
            "import_kendaraan",
            f"{assigned} plat terpasang, {unknown} tipe tidak dikenal, "
            f"{overflow} melebihi jumlah unit",
        )
        self.refresh()
        self.data_changed.emit()
        lines = [f"{assigned} plat berhasil dipasang."]
        if unknown:
            lines.append(
                f"{unknown} baris tipenya tidak cocok dan dimasukkan ke jenis "
                "kendaraan default."
            )
        if overflow:
            lines.append(
                f"{overflow} baris dilewati karena jumlah unit pada jenisnya "
                "tidak mencukupi."
            )
        QMessageBox.information(self, "Import plat selesai", "\n".join(lines))

