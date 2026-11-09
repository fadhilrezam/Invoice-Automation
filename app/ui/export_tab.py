"""Tab export invoice."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..config import default_template_path
from ..db import Database
from ..models import Project, Term
from ..services.invoice_builder import build_invoice_data
from ..services.invoice_export import InvoiceExportError, export_invoices
from ..services.validation import term_totals, validate_project, validate_term
from ..utils import format_date_id, format_rupiah
from .style import GREEN, MUTED, RED
from .widgets import Banner, Card, button, muted, setup_table


class ExportTab(QWidget):
    def __init__(self, db: Database, parent: QWidget | None = None):
        super().__init__(parent)
        self.db = db
        self.project: Project | None = None
        self.term: Term | None = None
        self.vehicles = []
        self._updating = False
        self._last_output: Path | None = None
        self._build_ui()
        self._set_enabled(False)

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(12)

        card = Card("Export Invoice")
        top = QHBoxLayout()
        top.setSpacing(8)
        top.addWidget(QLabel("Termin"))
        self.term_combo = QComboBox()
        self.term_combo.setMinimumWidth(220)
        self.term_combo.currentIndexChanged.connect(self._term_changed)
        top.addWidget(self.term_combo)
        self.lock_label = QLabel("")
        top.addWidget(self.lock_label)
        top.addSpacing(12)
        self.term_info = muted("")
        top.addWidget(self.term_info)
        top.addStretch(1)
        card.add_layout(top)

        self.banner = Banner("", self)
        card.add(self.banner)

        vehicles_header = QHBoxLayout()
        vehicles_header.addWidget(QLabel("Pilih kendaraan yang akan diexport"))
        vehicles_header.addStretch(1)
        self.select_all_btn = button("Pilih Semua")
        self.select_all_btn.clicked.connect(self._select_all)
        vehicles_header.addWidget(self.select_all_btn)
        self.select_none_btn = button("Kosongkan Pilihan")
        self.select_none_btn.clicked.connect(self._select_none)
        vehicles_header.addWidget(self.select_none_btn)
        card.add_layout(vehicles_header)

        self.vehicle_table = QTableWidget()
        self.vehicle_table.setColumnCount(5)
        self.vehicle_table.setHorizontalHeaderLabels(
            ["Pilih", "No Kendaraan", "Tipe Kendaraan", "Jumlah Item", "Total Invoice"]
        )
        setup_table(self.vehicle_table, row_height=30)
        self.vehicle_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        header = self.vehicle_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.Fixed)
        header.setSectionResizeMode(1, QHeaderView.Stretch)
        header.setSectionResizeMode(2, QHeaderView.Stretch)
        header.setSectionResizeMode(3, QHeaderView.Fixed)
        header.setSectionResizeMode(4, QHeaderView.Fixed)
        self.vehicle_table.setColumnWidth(0, 60)
        self.vehicle_table.setColumnWidth(3, 110)
        self.vehicle_table.setColumnWidth(4, 150)
        self.vehicle_table.itemChanged.connect(self._vehicle_check_changed)
        self.vehicle_table.setMinimumHeight(220)
        card.add(self.vehicle_table)

        options = QHBoxLayout()
        options.setSpacing(8)
        options.addWidget(QLabel("Folder output"))
        self.output_edit = QLineEdit()
        options.addWidget(self.output_edit, 1)
        browse = button("Pilih Folder")
        browse.clicked.connect(self._browse_output)
        options.addWidget(browse)
        card.add_layout(options)

        options2 = QHBoxLayout()
        options2.setSpacing(8)
        options2.addWidget(QLabel("Format"))
        self.mode_combo = QComboBox()
        self.mode_combo.addItem("Satu file per kendaraan", "files")
        self.mode_combo.addItem("Satu workbook, sheet per kendaraan", "workbook")
        self.mode_combo.setCurrentIndex(1)
        options2.addWidget(self.mode_combo)
        self.overwrite_check = QCheckBox("Timpa file yang sudah ada")
        options2.addWidget(self.overwrite_check)
        options2.addStretch(1)
        self.selected_label = muted("")
        options2.addWidget(self.selected_label)
        self.export_btn = button("Export Invoice", primary=True)
        self.export_btn.clicked.connect(self._export)
        options2.addWidget(self.export_btn)
        card.add_layout(options2)
        root.addWidget(card, 1)

        result_card = Card("Hasil Export")
        self.result_box = QPlainTextEdit()
        self.result_box.setReadOnly(True)
        self.result_box.setPlaceholderText("Belum ada export.")
        result_card.add(self.result_box)
        bottom = QHBoxLayout()
        bottom.addStretch(1)
        self.open_folder_btn = button("Buka Folder")
        self.open_folder_btn.clicked.connect(self._open_folder)
        self.open_folder_btn.setEnabled(False)
        bottom.addWidget(self.open_folder_btn)
        result_card.add_layout(bottom)
        root.addWidget(result_card, 1)

        self._refresh_selected_label()

    def _set_enabled(self, enabled: bool) -> None:
        for widget in (
            self.term_combo,
            self.vehicle_table,
            self.output_edit,
            self.mode_combo,
            self.overwrite_check,
            self.export_btn,
            self.select_all_btn,
            self.select_none_btn,
        ):
            widget.setEnabled(enabled)

    # --------------------------------------------------------------- project
    def set_project(self, project: Project | None) -> None:
        self.project = project
        self._set_enabled(project is not None)
        if not project:
            self.term_combo.clear()
            self.term = None
            self.vehicle_table.setRowCount(0)
            return
        if not self.output_edit.text().strip():
            default_dir = self.db.get_setting(
                "last_output_dir", str(Path.home() / "Documents" / "Invoice")
            )
            self.output_edit.setText(default_dir)
        self.refresh()

    def refresh(self) -> None:
        if not self.project:
            return
        self.project = self.db.get_project(self.project.id)
        terms = self.db.list_terms(self.project.id)
        current_id = self.term.id if self.term else None
        self._updating = True
        self.term_combo.clear()
        for term in terms:
            self.term_combo.addItem(term.name, term.id)
        if current_id is not None:
            idx = self.term_combo.findData(current_id)
            if idx >= 0:
                self.term_combo.setCurrentIndex(idx)
        self._updating = False

        if not terms:
            self.term = None
            self.vehicle_table.setRowCount(0)
            self.banner.set_state("warning", "Belum ada termin. Import RAB terlebih dahulu.")
            self.lock_label.setText("")
            self.term_info.setText("")
            self.export_btn.setEnabled(False)
            return
        if self.term_combo.currentIndex() < 0:
            self.term_combo.setCurrentIndex(0)
        self._load_term()

    def _term_changed(self) -> None:
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
        items = self.db.list_items(self.project.id)
        self.vehicles = self.db.list_vehicles(self.project.id)
        allocations = self.db.get_term_allocations(self.term.id)

        fmt = self.term.date_format or self.project.date_format or "full"
        date_text = format_date_id(self.term.date_obj or self.project.date_obj, fmt)
        self.term_info.setText(
            f"Tanggal {date_text} • diskon {self.term.discount_percent:g}%"
        )
        if self.term.locked:
            self.lock_label.setText("TERKUNCI")
            self.lock_label.setStyleSheet(
                f"background:#EAF7EF;color:{GREEN};border:1px solid #C9E9D5;"
                "border-radius:5px;padding:3px 8px;font-weight:600;"
            )
        else:
            self.lock_label.setText("BELUM DIKUNCI")
            self.lock_label.setStyleSheet(
                "background:#FFF8E1;color:#9A6700;border:1px solid #F2DFA0;"
                "border-radius:5px;padding:3px 8px;font-weight:600;"
            )

        self._fill_vehicles(items, allocations)
        stats = term_totals(self.db, self.term, items)
        self.term_info.setText(
            f"Tanggal {date_text} • diskon {self.term.discount_percent:g}% • "
            f"qty {stats['total_qty']} • nilai {format_rupiah(stats['value'])}"
        )
        self._update_banner()
        self._refresh_selected_label()

    def _fill_vehicles(self, items, allocations) -> None:
        self._updating = True
        self.vehicle_table.setRowCount(len(self.vehicles))
        by_vehicle: dict[int, tuple[int, int]] = {}
        for vehicle in self.vehicles:
            count = 0
            total = 0
            for item in items:
                qty = allocations.get((item.id, vehicle.id), 0)
                if qty:
                    count += 1
                    total += qty * item.unit_price
            by_vehicle[vehicle.id] = (count, total)

        for row, vehicle in enumerate(self.vehicles):
            check = QTableWidgetItem("")
            check.setFlags(
                Qt.ItemIsEnabled | Qt.ItemIsSelectable | Qt.ItemIsUserCheckable
            )
            count, total = by_vehicle[vehicle.id]
            check.setCheckState(Qt.Checked if count else Qt.Unchecked)
            check.setData(Qt.UserRole, vehicle.id)
            self.vehicle_table.setItem(row, 0, check)

            plate = QTableWidgetItem(vehicle.display_name)
            plate.setFlags(plate.flags() & ~Qt.ItemIsEditable)
            plate.setToolTip(f"Plat: {vehicle.plate or '(kosong)'}")
            self.vehicle_table.setItem(row, 1, plate)

            vtype = QTableWidgetItem(
                vehicle.type_name
                or vehicle.vehicle_type
                or (self.project.vehicle_type if self.project else "")
            )
            vtype.setFlags(vtype.flags() & ~Qt.ItemIsEditable)
            self.vehicle_table.setItem(row, 2, vtype)

            count_item = QTableWidgetItem(str(count))
            count_item.setTextAlignment(Qt.AlignCenter)
            count_item.setFlags(count_item.flags() & ~Qt.ItemIsEditable)
            self.vehicle_table.setItem(row, 3, count_item)

            total_item = QTableWidgetItem(format_rupiah(total))
            total_item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            total_item.setFlags(total_item.flags() & ~Qt.ItemIsEditable)
            self.vehicle_table.setItem(row, 4, total_item)
        self._updating = False

    def _update_banner(self) -> None:
        if not self.project or not self.term:
            return
        project_issues = validate_project(self.db, self.project.id)
        term_issues = validate_term(self.db, self.term)
        template = Path(
            self.db.get_setting("template_path", str(default_template_path()))
        )
        if not template.exists():
            self.banner.set_state(
                "error",
                f"Template invoice tidak ditemukan: {template}. Atur di menu Pengaturan.",
            )
            self.export_btn.setEnabled(False)
            return
        if project_issues:
            self.banner.set_state(
                "error",
                f"{len(project_issues)} masalah qty RAB/termin. Perbaiki di tab Data Proyek.",
            )
            self.export_btn.setEnabled(False)
            return
        if term_issues:
            self.banner.set_state(
                "error",
                f"{len(term_issues)} item belum seimbang. Selesaikan alokasi di tab "
                "Alokasi Termin.",
            )
            self.export_btn.setEnabled(False)
            return
        if not self.term.locked:
            self.banner.set_state(
                "warning",
                "Termin belum dikunci. Kunci termin di tab Alokasi Termin sebelum export.",
            )
            self.export_btn.setEnabled(False)
            return
        selected = len(self._selected_vehicle_ids())
        self.banner.set_state(
            "success",
            f"Siap export. {selected} kendaraan dipilih. "
            "File mengikuti layout invoice_template.xlsx.",
        )
        self.export_btn.setEnabled(selected > 0)

    # -------------------------------------------------------------- selection
    def _selected_vehicle_ids(self) -> list[int]:
        selected: list[int] = []
        for row in range(self.vehicle_table.rowCount()):
            item = self.vehicle_table.item(row, 0)
            if item and item.checkState() == Qt.Checked:
                selected.append(int(item.data(Qt.UserRole)))
        return selected

    def _vehicle_check_changed(self, item: QTableWidgetItem) -> None:
        if self._updating or item.column() != 0:
            return
        self._refresh_selected_label()
        if self.project and self.term:
            self._update_export_enabled()

    def _refresh_selected_label(self) -> None:
        selected = self._selected_vehicle_ids()
        self.selected_label.setText(f"{len(selected)} kendaraan dipilih")

    def _update_export_enabled(self) -> None:
        if not self.project or not self.term:
            return
        project_issues = validate_project(self.db, self.project.id)
        term_issues = validate_term(self.db, self.term)
        ok = (
            self.term.locked
            and not project_issues
            and not term_issues
            and bool(self._selected_vehicle_ids())
        )
        self.export_btn.setEnabled(ok)

    def _select_all(self) -> None:
        self._updating = True
        for row in range(self.vehicle_table.rowCount()):
            item = self.vehicle_table.item(row, 0)
            if item:
                item.setCheckState(Qt.Checked)
        self._updating = False
        self._refresh_selected_label()
        self._update_export_enabled()

    def _select_none(self) -> None:
        self._updating = True
        for row in range(self.vehicle_table.rowCount()):
            item = self.vehicle_table.item(row, 0)
            if item:
                item.setCheckState(Qt.Unchecked)
        self._updating = False
        self._refresh_selected_label()
        self._update_export_enabled()

    # ----------------------------------------------------------------- export
    def _browse_output(self) -> None:
        start = self.output_edit.text().strip() or str(Path.home() / "Documents")
        folder = QFileDialog.getExistingDirectory(self, "Pilih folder output", start)
        if folder:
            self.output_edit.setText(folder)

    def _export(self) -> None:
        if not self.project or not self.term:
            return
        if not self.term.locked:
            QMessageBox.warning(
                self, "Termin belum dikunci", "Kunci termin dulu di tab Alokasi Termin."
            )
            return
        project_issues = validate_project(self.db, self.project.id)
        term_issues = validate_term(self.db, self.term)
        if project_issues or term_issues:
            QMessageBox.warning(
                self,
                "Belum valid",
                f"Masih ada {len(project_issues) + len(term_issues)} masalah qty. "
                "Perbaiki dulu sebelum export.",
            )
            return
        output_text = self.output_edit.text().strip()
        if not output_text:
            QMessageBox.warning(self, "Folder kosong", "Pilih folder output terlebih dahulu.")
            return
        output_dir = Path(output_text)
        selected_ids = set(self._selected_vehicle_ids())
        if not selected_ids:
            QMessageBox.warning(self, "Belum dipilih", "Pilih minimal satu kendaraan.")
            return

        items = self.db.list_items(self.project.id)
        vehicles = [v for v in self.vehicles if v.id in selected_ids]
        company_name = self.db.get_setting("company_name", "CV. PANJI PERKASA")
        company_address = self.db.get_setting(
            "company_address", "Kab. Bandung, Jawa Barat, Indonesia"
        )
        template = self.db.get_setting("template_path", str(default_template_path()))

        invoices = []
        skipped = []
        for vehicle in vehicles:
            invoice = build_invoice_data(
                self.db,
                self.project,
                self.term,
                vehicle,
                company_name=company_name,
                company_address=company_address,
                template_path=template,
            )
            if invoice is None:
                skipped.append(vehicle.display_name)
            else:
                invoices.append(invoice)
        if not invoices:
            QMessageBox.warning(
                self,
                "Tidak ada invoice",
                "Kendaraan yang dipilih tidak punya alokasi qty di termin ini.",
            )
            return

        overwrite = self.overwrite_check.isChecked()
        if overwrite:
            answer = QMessageBox.question(
                self,
                "Timpa file?",
                "File invoice dengan nama sama di folder output akan ditimpa. Lanjutkan?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if answer != QMessageBox.Yes:
                return

        mode = self.mode_combo.currentData()
        self.export_btn.setEnabled(False)
        try:
            paths = export_invoices(
                template,
                invoices,
                output_dir,
                mode=mode,
                overwrite=overwrite,
            )
        except InvoiceExportError as exc:
            QMessageBox.critical(self, "Export gagal", str(exc))
            self.export_btn.setEnabled(True)
            return
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "Export gagal", f"Terjadi kesalahan: {exc}")
            self.export_btn.setEnabled(True)
            return
        finally:
            self._update_export_enabled()

        self.db.set_setting("last_output_dir", str(output_dir))
        self.db.log(
            self.project.id,
            "export_invoice",
            f"{self.term.name}: {len(paths)} file, {len(invoices)} kendaraan, "
            f"mode {mode}",
        )
        self._last_output = output_dir
        self.open_folder_btn.setEnabled(True)
        lines = [f"Export {self.term.name} selesai."]
        lines.append(f"{len(invoices)} invoice dibuat.")
        for path in paths:
            lines.append(f"• {path}")
        if skipped:
            lines.append(
                "Dilewati karena tidak punya alokasi: " + ", ".join(skipped)
            )
        self.result_box.setPlainText("\n".join(lines))
        QMessageBox.information(
            self,
            "Export selesai",
            f"{len(paths)} file berhasil dibuat di:\n{output_dir}",
        )

    def _open_folder(self) -> None:
        if not self._last_output:
            return
        try:
            import os

            os.startfile(str(self._last_output))  # type: ignore[attr-defined]
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(self, "Gagal membuka folder", str(exc))
