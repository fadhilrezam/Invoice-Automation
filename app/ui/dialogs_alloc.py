"""Dialog pembagian sisa dan pengelolaan termin."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..db import Database
from ..models import Project
from ..services.allocation import (
    RemainderPlan,
    allocations_for_choice,
    validate_choice,
)
from ..utils import parse_date_text
from .style import GREEN, MUTED, RED
from .widgets import Banner, button, muted, setup_table


@dataclass
class RemainderJob:
    item_id: int
    item_name: str
    unit: str
    plan: RemainderPlan
    history: dict[int, int]


class RemainderDialog(QDialog):
    """Antrean konfirmasi untuk item yang qty-nya tidak habis dibagi."""

    def __init__(
        self,
        jobs: list[RemainderJob],
        vehicle_labels: dict[int, tuple[str, str]],
        parent: QWidget | None = None,
        term_name: str = "",
    ):
        super().__init__(parent)
        self.setWindowTitle(
            f"Konfirmasi Pembagian Sisa - {term_name}" if term_name else "Konfirmasi Pembagian Sisa"
        )
        self.resize(980, 620)
        self.jobs = jobs
        self.vehicle_labels = vehicle_labels
        self.choices: dict[int, list[int]] = {}
        self.skipped: set[int] = set()
        self.drafts: dict[int, set[int]] = {}
        self.current_index = 0
        self._updating = False

        for job in jobs:
            self.drafts[job.item_id] = set(job.plan.suggested)

        self._build_ui()
        if self.jobs:
            self._select_job(0)

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 14)
        root.setSpacing(10)

        title = QLabel("Pilih kendaraan penerima sisa")
        title.setStyleSheet("font-size: 14pt; font-weight: 600; color: #1F2937;")
        root.addWidget(title)
        root.addWidget(
            muted(
                "Qty tidak habis dibagi. Pilih tepat sejumlah kendaraan untuk "
                "menerima tambahan 1 unit. Saran awal memprioritaskan kendaraan "
                "yang paling sedikit menerima item ini di termin sebelumnya."
            )
        )

        splitter = QSplitter(Qt.Horizontal)
        self.list = QListWidget()
        self.list.setMinimumWidth(260)
        for index, job in enumerate(self.jobs):
            item = QListWidgetItem(self._job_text(index))
            item.setData(Qt.UserRole, index)
            self.list.addItem(item)
        self.list.currentRowChanged.connect(self._select_job)
        splitter.addWidget(self.list)

        panel = QWidget()
        panel_layout = QVBoxLayout(panel)
        panel_layout.setContentsMargins(12, 0, 0, 0)
        panel_layout.setSpacing(10)

        self.item_title = QLabel("")
        self.item_title.setStyleSheet(
            "font-size: 12pt; font-weight: 600; color: #1F2937;"
        )
        self.item_title.setWordWrap(True)
        panel_layout.addWidget(self.item_title)

        self.info_banner = Banner("", self)
        panel_layout.addWidget(self.info_banner)

        self.vehicle_table = QTableWidget()
        self.vehicle_table.setColumnCount(5)
        self.vehicle_table.setHorizontalHeaderLabels(
            ["Pilih", "No Kendaraan", "Tipe Kendaraan", "Riwayat item ini", "Jatah"]
        )
        setup_table(self.vehicle_table, row_height=32)
        self.vehicle_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        header = self.vehicle_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.Fixed)
        header.setSectionResizeMode(1, QHeaderView.Stretch)
        header.setSectionResizeMode(2, QHeaderView.Stretch)
        header.setSectionResizeMode(3, QHeaderView.Fixed)
        header.setSectionResizeMode(4, QHeaderView.Fixed)
        self.vehicle_table.setColumnWidth(0, 60)
        self.vehicle_table.setColumnWidth(3, 130)
        self.vehicle_table.setColumnWidth(4, 90)
        self.vehicle_table.itemChanged.connect(self._on_check_changed)
        panel_layout.addWidget(self.vehicle_table, 1)

        row = QHBoxLayout()
        suggest = QPushButton("Gunakan Saran")
        suggest.clicked.connect(self._use_suggestion)
        row.addWidget(suggest)
        row.addStretch(1)
        skip = QPushButton("Lewati Item Ini")
        skip.clicked.connect(self._skip_current)
        row.addWidget(skip)
        save = button("Simpan && Lanjut", primary=True)
        save.clicked.connect(self._save_current)
        row.addWidget(save)
        panel_layout.addLayout(row)
        splitter.addWidget(panel)
        splitter.setSizes([280, 680])
        root.addWidget(splitter, 1)

        bottom = QHBoxLayout()
        self.progress_label = muted("")
        bottom.addWidget(self.progress_label)
        bottom.addStretch(1)
        cancel = QPushButton("Batal")
        cancel.clicked.connect(self.reject)
        bottom.addWidget(cancel)
        apply_btn = button("Terapkan Pilihan", primary=True)
        apply_btn.clicked.connect(self._apply_all)
        bottom.addWidget(apply_btn)
        root.addLayout(bottom)
        self._refresh_progress()

    # ----------------------------------------------------------------- helpers
    def _job_text(self, index: int) -> str:
        job = self.jobs[index]
        state = ""
        if job.item_id in self.choices:
            state = "  [Selesai]"
        elif job.item_id in self.skipped:
            state = "  [Dilewati]"
        return f"{job.item_name}{state}"

    def _refresh_list(self) -> None:
        for index in range(self.list.count()):
            self.list.item(index).setText(self._job_text(index))

    def _refresh_progress(self) -> None:
        total = len(self.jobs)
        done = len(self.choices)
        skipped = len(self.skipped)
        self.progress_label.setText(
            f"{done} selesai • {skipped} dilewati • {total - done - skipped} belum"
        )

    def _select_job(self, index: int) -> None:
        if index < 0 or index >= len(self.jobs):
            return
        self.current_index = index
        job = self.jobs[index]
        plan = job.plan
        self.item_title.setText(job.item_name)
        total_qty = plan.qty
        unit = f" {job.unit}" if job.unit else ""
        self.info_banner.set_state(
            "info",
            f"Qty termin: {total_qty}{unit} • {len(plan.vehicle_ids)} kendaraan • "
            f"dasar {plan.base} per kendaraan • sisa {plan.remainder} unit harus dipilih.",
        )

        self._updating = True
        self.vehicle_table.setRowCount(len(plan.vehicle_ids))
        chosen = self.drafts.get(job.item_id, set(plan.suggested))
        for row, vehicle_id in enumerate(plan.vehicle_ids):
            plate, vehicle_type = self.vehicle_labels.get(
                vehicle_id, (f"ID {vehicle_id}", "")
            )
            check = QTableWidgetItem("")
            check.setFlags(
                Qt.ItemIsEnabled | Qt.ItemIsSelectable | Qt.ItemIsUserCheckable
            )
            check.setCheckState(
                Qt.Checked if vehicle_id in chosen else Qt.Unchecked
            )
            check.setData(Qt.UserRole, vehicle_id)
            self.vehicle_table.setItem(row, 0, check)

            plate_item = QTableWidgetItem(plate)
            plate_item.setFlags(plate_item.flags() & ~Qt.ItemIsEditable)
            self.vehicle_table.setItem(row, 1, plate_item)

            type_item = QTableWidgetItem(vehicle_type)
            type_item.setFlags(type_item.flags() & ~Qt.ItemIsEditable)
            self.vehicle_table.setItem(row, 2, type_item)

            history = job.history.get(vehicle_id, 0)
            history_item = QTableWidgetItem(str(history))
            history_item.setTextAlignment(Qt.AlignCenter)
            history_item.setFlags(history_item.flags() & ~Qt.ItemIsEditable)
            self.vehicle_table.setItem(row, 3, history_item)

            qty = plan.base + (1 if vehicle_id in chosen else 0)
            qty_item = QTableWidgetItem(str(qty))
            qty_item.setTextAlignment(Qt.AlignCenter)
            qty_item.setFlags(qty_item.flags() & ~Qt.ItemIsEditable)
            self.vehicle_table.setItem(row, 4, qty_item)
        self._updating = False
        self._update_selection_state()

    def _chosen_vehicle_ids(self) -> list[int]:
        chosen: list[int] = []
        for row in range(self.vehicle_table.rowCount()):
            item = self.vehicle_table.item(row, 0)
            if item and item.checkState() == Qt.Checked:
                chosen.append(int(item.data(Qt.UserRole)))
        return chosen

    def _on_check_changed(self, item: QTableWidgetItem) -> None:
        if self._updating or item.column() != 0:
            return
        job = self.jobs[self.current_index]
        self.drafts[job.item_id] = set(self._chosen_vehicle_ids())
        self._update_selection_state()

    def _update_selection_state(self) -> None:
        if not self.jobs:
            return
        job = self.jobs[self.current_index]
        chosen = self._chosen_vehicle_ids()
        plan = job.plan
        self._updating = True
        selected = set(chosen)
        for row in range(self.vehicle_table.rowCount()):
            vehicle_id = int(self.vehicle_table.item(row, 0).data(Qt.UserRole))
            qty = plan.base + (1 if vehicle_id in selected else 0)
            self.vehicle_table.item(row, 4).setText(str(qty))
        self._updating = False
        error = validate_choice(plan, chosen)
        if error:
            self.info_banner.set_state(
                "error", f"Perlu dipilih tepat {plan.remainder} kendaraan. {error}"
            )
        else:
            self.info_banner.set_state(
                "success",
                f"Pilihan valid: {len(chosen)} kendaraan mendapat tambahan 1 unit. "
                f"Total = {plan.qty}.",
            )

    def _use_suggestion(self) -> None:
        if not self.jobs:
            return
        job = self.jobs[self.current_index]
        self.drafts[job.item_id] = set(job.plan.suggested)
        self._select_job(self.current_index)

    def _save_current(self) -> None:
        if not self.jobs:
            return
        job = self.jobs[self.current_index]
        chosen = self._chosen_vehicle_ids()
        error = validate_choice(job.plan, chosen)
        if error:
            QMessageBox.warning(self, "Pilihan belum valid", error)
            return
        self.choices[job.item_id] = chosen
        self.skipped.discard(job.item_id)
        self.drafts[job.item_id] = set(chosen)
        self._refresh_list()
        self._refresh_progress()
        if self.current_index + 1 < len(self.jobs):
            self.list.setCurrentRow(self.current_index + 1)

    def _skip_current(self) -> None:
        if not self.jobs:
            return
        job = self.jobs[self.current_index]
        self.choices.pop(job.item_id, None)
        self.skipped.add(job.item_id)
        self._refresh_list()
        self._refresh_progress()
        if self.current_index + 1 < len(self.jobs):
            self.list.setCurrentRow(self.current_index + 1)

    def _apply_all(self) -> None:
        pending = len(self.jobs) - len(self.choices) - len(self.skipped)
        if pending:
            answer = QMessageBox.question(
                self,
                "Masih ada item belum diputuskan",
                f"{pending} item belum disimpan/dilewati. Item tersebut akan "
                "dibiarkan belum teralokasi. Lanjutkan?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if answer != QMessageBox.Yes:
                return
        super().accept()


class TermManagerDialog(QDialog):
    """Tambah/ubah/hapus termin beserta tanggal invoice dan diskon."""

    def __init__(
        self,
        db: Database,
        project: Project,
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self.setWindowTitle("Kelola Termin")
        self.resize(760, 460)
        self.db = db
        self.project = project
        self.terms = db.list_terms(project.id)
        self._deleted_ids: list[int] = []
        self.saved = False

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 14)
        root.setSpacing(10)
        title = QLabel("Kelola Termin")
        title.setStyleSheet("font-size: 14pt; font-weight: 600; color: #1F2937;")
        root.addWidget(title)
        root.addWidget(
            muted(
                "Nama termin sebaiknya sama dengan kolom termin di RAB. "
                "Tanggal invoice dan diskon (%) dipakai saat export."
            )
        )

        self.table = QTableWidget()
        self.table.setColumnCount(5)
        self.table.setHorizontalHeaderLabels(
            [
                "Nama Termin",
                "Tanggal Invoice (YYYY-MM-DD)",
                "Format Tanggal",
                "Diskon (%)",
                "Status",
            ]
        )
        setup_table(self.table, row_height=32)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.Stretch)
        header.setSectionResizeMode(1, QHeaderView.Fixed)
        header.setSectionResizeMode(2, QHeaderView.Fixed)
        header.setSectionResizeMode(3, QHeaderView.Fixed)
        header.setSectionResizeMode(4, QHeaderView.Fixed)
        self.table.setColumnWidth(1, 180)
        self.table.setColumnWidth(2, 190)
        self.table.setColumnWidth(3, 100)
        self.table.setColumnWidth(4, 100)
        self._fill_table()
        root.addWidget(self.table, 1)

        row = QHBoxLayout()
        add = QPushButton("Tambah Termin")
        add.clicked.connect(self._add_row)
        row.addWidget(add)
        delete = QPushButton("Hapus Termin")
        delete.clicked.connect(self._delete_row)
        row.addWidget(delete)
        row.addStretch(1)
        cancel = QPushButton("Batal")
        cancel.clicked.connect(self.reject)
        row.addWidget(cancel)
        save = button("Simpan", primary=True)
        save.clicked.connect(self._save)
        row.addWidget(save)
        root.addLayout(row)

    def _fill_table(self) -> None:
        self.table.setRowCount(len(self.terms))
        for row, term in enumerate(self.terms):
            name = QTableWidgetItem(term.name)
            name.setData(Qt.UserRole, term.id)
            self.table.setItem(row, 0, name)
            date_text = (
                term.date_obj.isoformat()
                if term.date_obj
                else self.project.date_obj.isoformat()
            )
            self.table.setItem(row, 1, QTableWidgetItem(date_text))
            self.table.setCellWidget(
                row, 2, self._make_format_combo(term.date_format)
            )
            discount = QTableWidgetItem(f"{term.discount_percent:g}")
            discount.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self.table.setItem(row, 3, discount)
            status = QTableWidgetItem("Terkunci" if term.locked else "Terbuka")
            status.setFlags(status.flags() & ~Qt.ItemIsEditable)
            if term.locked:
                status.setForeground(QColor(GREEN))
            self.table.setItem(row, 4, status)

    def _make_format_combo(self, date_format: str | None = None) -> QComboBox:
        combo = QComboBox()
        combo.addItem("Ikuti proyek", "")
        combo.addItem("Tanggal lengkap", "full")
        combo.addItem("Bulan dan tahun", "bulan_tahun")
        idx = combo.findData(date_format or "")
        combo.setCurrentIndex(idx if idx >= 0 else 0)
        return combo

    def _add_row(self) -> None:
        row = self.table.rowCount()
        self.table.insertRow(row)
        name = QTableWidgetItem(f"Termin {row + 1}")
        name.setData(Qt.UserRole, None)
        self.table.setItem(row, 0, name)
        self.table.setItem(row, 1, QTableWidgetItem(self.project.date_obj.isoformat()))
        self.table.setCellWidget(row, 2, self._make_format_combo(None))
        discount = QTableWidgetItem("0")
        discount.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.table.setItem(row, 3, discount)
        status = QTableWidgetItem("Baru")
        status.setFlags(status.flags() & ~Qt.ItemIsEditable)
        self.table.setItem(row, 4, status)
        self.table.setCurrentCell(row, 0)

    def _delete_row(self) -> None:
        row = self.table.currentRow()
        if row < 0:
            QMessageBox.information(self, "Pilih termin", "Pilih baris termin yang akan dihapus.")
            return
        if self.table.rowCount() <= 1:
            QMessageBox.warning(self, "Tidak bisa", "Minimal harus ada satu termin.")
            return
        name_item = self.table.item(row, 0)
        name = name_item.text() if name_item else "termin ini"
        answer = QMessageBox.question(
            self,
            "Hapus termin",
            f"Hapus '{name}'? Semua alokasi di termin ini juga akan terhapus.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return
        term_id = name_item.data(Qt.UserRole) if name_item else None
        if term_id is not None:
            self._deleted_ids.append(int(term_id))
        self.table.removeRow(row)

    def _save(self) -> None:
        rows: list[tuple[int | None, str, date, float, str | None]] = []
        names: set[str] = set()
        for row in range(self.table.rowCount()):
            name_item = self.table.item(row, 0)
            name = (name_item.text() if name_item else "").strip()
            if not name:
                QMessageBox.warning(self, "Nama kosong", f"Nama termin baris {row + 1} kosong.")
                return
            if name in names:
                QMessageBox.warning(self, "Nama ganda", f"Nama termin '{name}' dipakai lebih dari sekali.")
                return
            names.add(name)
            date_item = self.table.item(row, 1)
            date_text = (date_item.text() if date_item else "").strip()
            parsed = parse_date_text(date_text)
            if parsed is None:
                QMessageBox.warning(
                    self,
                    "Tanggal tidak valid",
                    f"Tanggal '{date_text}' tidak dikenali. Gunakan format YYYY-MM-DD.",
                )
                return
            format_combo = self.table.cellWidget(row, 2)
            date_format = (
                (format_combo.currentData() or None)
                if isinstance(format_combo, QComboBox)
                else None
            )
            discount_item = self.table.item(row, 3)
            try:
                discount = float((discount_item.text() if discount_item else "0").replace(",", "."))
            except ValueError:
                QMessageBox.warning(self, "Diskon tidak valid", "Diskon harus angka 0-100.")
                return
            if not (0 <= discount <= 100):
                QMessageBox.warning(self, "Diskon tidak valid", "Diskon harus antara 0 dan 100.")
                return
            term_id = name_item.data(Qt.UserRole)
            rows.append(
                (
                    int(term_id) if term_id is not None else None,
                    name,
                    parsed,
                    discount,
                    date_format,
                )
            )

        with self.db.transaction() as conn:
            for term_id in self._deleted_ids:
                conn.execute("DELETE FROM terms WHERE id = ?", (term_id,))
            for term_id, name, parsed, discount, date_format in rows:
                if term_id is None:
                    seq = conn.execute(
                        "SELECT COALESCE(MAX(seq), 0) + 1 FROM terms WHERE project_id = ?",
                        (self.project.id,),
                    ).fetchone()[0]
                    conn.execute(
                        """INSERT INTO terms
                           (project_id, name, seq, invoice_date, date_format,
                            discount_percent, locked)
                           VALUES (?, ?, ?, ?, ?, ?, 0)""",
                        (
                            self.project.id,
                            name,
                            seq,
                            parsed.isoformat(),
                            date_format,
                            discount,
                        ),
                    )
                else:
                    conn.execute(
                        """UPDATE terms SET name = ?, invoice_date = ?, date_format = ?,
                           discount_percent = ? WHERE id = ?""",
                        (name, parsed.isoformat(), date_format, discount, term_id),
                    )
        self.db.log(
            self.project.id,
            "kelola_termin",
            f"{len(rows)} termin disimpan, {len(self._deleted_ids)} dihapus",
        )
        self.saved = True
        super().accept()
