"""Dialog-dialog untuk import RAB dan pengelolaan item."""
from __future__ import annotations

from pathlib import Path

import openpyxl
from openpyxl.utils import get_column_letter
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..db import Database
from ..models import Item, Project, Term
from ..services.rab_parser import (
    ROLE_IGNORE,
    ROLE_LABELS,
    ROLE_NAME,
    ROLE_PRICE,
    ROLE_TERM,
    ROLE_TOTAL_QTY,
    ROLE_UNIT,
    MappedColumn,
    ParseResult,
    RabMapping,
    RabParseError,
    cell_text,
    detect_best_header,
    detect_columns,
    header_text,
)
from .style import ACCENT, AMBER, GREEN, MUTED, RED
from .widgets import Banner, button, money_text, muted, setup_table


class RabMappingDialog(QDialog):
    """Pemetaan kolom Excel RAB ke peran aplikasi."""

    def __init__(self, path: str | Path, parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle("Import RAB - Petakan Kolom")
        self.resize(1080, 760)
        self.path = Path(path)
        self.mapping: RabMapping | None = None
        self._loading = False
        try:
            self._wb = openpyxl.load_workbook(str(self.path), data_only=True)
        except Exception as exc:  # noqa: BLE001
            raise RabParseError(f"File tidak bisa dibuka: {exc}") from exc

        self._build_ui()
        self._load_sheets()

    # ------------------------------------------------------------------ UI
    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 14)
        root.setSpacing(10)

        title = QLabel("Petakan kolom Excel RAB")
        title.setStyleSheet("font-size: 14pt; font-weight: 600; color: #1F2937;")
        root.addWidget(title)
        subtitle = muted(
            "Pilih sheet dan baris header, lalu tentukan peran setiap kolom. "
            "Nama kolom termin akan menjadi nama termin di aplikasi. "
            "RAB dengan penanda jenis kendaraan (mis. 'YAMAHA VIXION (3 Unit)') "
            "dikenali otomatis; setiap blok menjadi jenis + daftar item sendiri."
        )
        root.addWidget(subtitle)

        top = QHBoxLayout()
        top.setSpacing(10)
        top.addWidget(QLabel("Sheet"))
        self.sheet_combo = QComboBox()
        self.sheet_combo.setMinimumWidth(180)
        top.addWidget(self.sheet_combo)
        top.addSpacing(12)
        top.addWidget(QLabel("Baris header"))
        self.header_spin = QSpinBox()
        self.header_spin.setRange(1, 500)
        self.header_spin.setValue(1)
        self.header_spin.setFixedWidth(80)
        top.addWidget(self.header_spin)
        detect_btn = button("Deteksi Otomatis")
        detect_btn.clicked.connect(self._detect_auto)
        top.addWidget(detect_btn)
        top.addStretch(1)
        root.addLayout(top)

        splitter = QSplitter(Qt.Vertical)
        self.map_table = QTableWidget()
        self.map_table.setColumnCount(4)
        self.map_table.setHorizontalHeaderLabels(
            ["Kolom", "Header Excel", "Peran", "Nama Termin"]
        )
        self.map_table.verticalHeader().setVisible(False)
        self.map_table.setSelectionMode(QAbstractItemView.NoSelection)
        self.map_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.map_table.setShowGrid(False)
        self.map_table.setAlternatingRowColors(True)
        header = self.map_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.Fixed)
        header.setSectionResizeMode(1, QHeaderView.Stretch)
        header.setSectionResizeMode(2, QHeaderView.Fixed)
        header.setSectionResizeMode(3, QHeaderView.Fixed)
        self.map_table.setColumnWidth(0, 70)
        self.map_table.setColumnWidth(2, 190)
        self.map_table.setColumnWidth(3, 190)
        splitter.addWidget(self.map_table)

        preview_wrap = QWidget()
        preview_layout = QVBoxLayout(preview_wrap)
        preview_layout.setContentsMargins(0, 0, 0, 0)
        preview_layout.setSpacing(4)
        preview_layout.addWidget(muted("Pratinjau data (baris header ke bawah):"))
        self.preview_table = QTableWidget()
        self.preview_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.preview_table.setSelectionMode(QAbstractItemView.NoSelection)
        self.preview_table.setShowGrid(False)
        self.preview_table.setAlternatingRowColors(True)
        self.preview_table.verticalHeader().setDefaultSectionSize(24)
        preview_layout.addWidget(self.preview_table)
        splitter.addWidget(preview_wrap)
        splitter.setSizes([360, 260])
        root.addWidget(splitter, 1)

        bottom = QHBoxLayout()
        bottom.addWidget(QLabel("Jika tidak ada kolom termin, jadikan satu term bernama:"))
        self.single_term_edit = QLineEdit("Termin 1")
        self.single_term_edit.setFixedWidth(180)
        bottom.addWidget(self.single_term_edit)
        bottom.addStretch(1)
        cancel = QPushButton("Batal")
        cancel.clicked.connect(self.reject)
        bottom.addWidget(cancel)
        self.import_btn = button("Lanjut", primary=True)
        self.import_btn.clicked.connect(self._accept)
        bottom.addWidget(self.import_btn)
        root.addLayout(bottom)

        self.sheet_combo.currentIndexChanged.connect(self._sheet_changed)
        self.header_spin.valueChanged.connect(self._header_changed)

    # --------------------------------------------------------------- loading
    def _load_sheets(self) -> None:
        self._loading = True
        self.sheet_combo.clear()
        self.sheet_combo.addItems(self._wb.sheetnames)
        self._loading = False
        self._sheet_changed()

    def _current_ws(self):
        name = self.sheet_combo.currentText()
        return self._wb[name] if name in self._wb.sheetnames else None

    def _sheet_changed(self) -> None:
        if self._loading:
            return
        ws = self._current_ws()
        if ws is None:
            return
        self._loading = True
        self.header_spin.setMaximum(max(1, min(ws.max_row or 1, 500)))
        self._loading = False
        self._detect_auto()

    def _header_changed(self) -> None:
        if self._loading:
            return
        ws = self._current_ws()
        if ws is None:
            return
        self._populate_columns(detect_columns(ws, self.header_spin.value()))

    def _detect_auto(self) -> None:
        ws = self._current_ws()
        if ws is None:
            return
        row, columns = detect_best_header(ws)
        self._loading = True
        self.header_spin.setValue(row)
        self._loading = False
        self._populate_columns(columns)

    def _populate_columns(self, columns: list[MappedColumn]) -> None:
        ws = self._current_ws()
        if ws is None:
            return
        self.map_table.setRowCount(0)
        self.map_table.setRowCount(len(columns))
        term_index = 0
        for index, mapped in enumerate(columns):
            col = mapped.col
            letter = get_column_letter(col)
            header_value = (
                header_text(ws, self.header_spin.value(), col) or "(kosong)"
            )
            item_col = QTableWidgetItem(letter)
            item_col.setTextAlignment(Qt.AlignCenter)
            self.map_table.setItem(index, 0, item_col)
            header_item = QTableWidgetItem(header_value)
            header_item.setToolTip(header_value)
            self.map_table.setItem(index, 1, header_item)

            combo = QComboBox()
            for role in (
                ROLE_NAME,
                ROLE_UNIT,
                ROLE_PRICE,
                ROLE_TOTAL_QTY,
                ROLE_TERM,
                ROLE_IGNORE,
            ):
                combo.addItem(ROLE_LABELS[role], role)
            combo.setCurrentIndex(max(0, combo.findData(mapped.role)))
            self.map_table.setCellWidget(index, 2, combo)

            term_edit = QLineEdit(mapped.term_name)
            term_edit.setPlaceholderText("mis. Termin 1")
            term_edit.setEnabled(mapped.role == ROLE_TERM)
            self.map_table.setCellWidget(index, 3, term_edit)

            def on_role_changed(_idx: int, r=index, cmb=combo, edit=term_edit):
                role = cmb.currentData()
                edit.setEnabled(role == ROLE_TERM)
                if role == ROLE_TERM and not edit.text().strip():
                    count = sum(
                        1
                        for i in range(self.map_table.rowCount())
                        if (w := self.map_table.cellWidget(i, 2))
                        and w.currentData() == ROLE_TERM
                    )
                    edit.setText(f"Termin {max(1, count)}")

            combo.currentIndexChanged.connect(on_role_changed)
            term_index += 1

        self.map_table.resizeRowsToContents()
        self._populate_preview()

    def _populate_preview(self) -> None:
        ws = self._current_ws()
        if ws is None:
            return
        header_row = self.header_spin.value()
        max_col = min(ws.max_column or 1, 40)
        row_count = max(1, min((ws.max_row or header_row) - header_row, 10))
        self.preview_table.clear()
        self.preview_table.setRowCount(row_count)
        self.preview_table.setColumnCount(max_col)
        labels = [get_column_letter(c) for c in range(1, max_col + 1)]
        self.preview_table.setHorizontalHeaderLabels(labels)
        vlabels = [str(header_row + i) for i in range(row_count)]
        self.preview_table.setVerticalHeaderLabels(vlabels)
        for r in range(row_count):
            for c in range(1, max_col + 1):
                value = ws.cell(row=header_row + r, column=c).value
                text = "" if value is None else str(value)
                item = QTableWidgetItem(text)
                item.setToolTip(text)
                self.preview_table.setItem(r, c - 1, item)
        self.preview_table.resizeColumnsToContents()
        for c in range(max_col):
            if self.preview_table.columnWidth(c) > 220:
                self.preview_table.setColumnWidth(c, 220)

    # -------------------------------------------------------------- accepting
    def _build_mapping(self) -> RabMapping:
        columns: list[MappedColumn] = []
        term_counter = 0
        for row in range(self.map_table.rowCount()):
            combo = self.map_table.cellWidget(row, 2)
            edit = self.map_table.cellWidget(row, 3)
            role = combo.currentData() if combo else ROLE_IGNORE
            term_name = edit.text().strip() if edit else ""
            if role == ROLE_TERM:
                term_counter += 1
                if not term_name:
                    term_name = f"Termin {term_counter}"
            else:
                term_name = ""
            columns.append(MappedColumn(row + 1, role, term_name))
        return RabMapping(
            sheet=self.sheet_combo.currentText(),
            header_row=self.header_spin.value(),
            columns=columns,
            single_term_name=self.single_term_edit.text().strip() or "Termin 1",
        )

    def _accept(self) -> None:
        mapping = self._build_mapping()
        error = mapping.validate()
        if error:
            QMessageBox.warning(self, "Pemetaan belum lengkap", error)
            return
        self.mapping = mapping
        super().accept()


class RabImportConfirmDialog(QDialog):
    """Ringkasan hasil parsing + konfirmasi pembulatan qty desimal."""

    def __init__(
        self,
        result: ParseResult,
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self.setWindowTitle("Konfirmasi Import RAB")
        self.setMinimumWidth(720)
        self.result = result

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 14)
        root.setSpacing(10)

        title = QLabel("RAB berhasil dibaca")
        title.setStyleSheet("font-size: 14pt; font-weight: 600; color: #1F2937;")
        root.addWidget(title)

        total_qty = sum(item.total_qty for item in result.items)
        total_value = sum(item.total_qty * item.unit_price for item in result.items)
        group_text = ""
        if result.groups:
            units = sum(group.unit_count for group in result.groups)
            group_text = (
                f" • {len(result.groups)} jenis kendaraan"
                + (f" ({units} unit)" if units else "")
            )
        summary = (
            f"{len(result.items)} item{group_text} • {len(result.term_names)} termin "
            f"({', '.join(result.term_names)}) • total qty {total_qty:,} • "
            f"nilai RAB Rp {money_text(total_value)}"
        ).replace(",", ".")
        root.addWidget(Banner(summary, self))

        if result.issues:
            root.addWidget(
                QLabel(
                    "Ada hal yang perlu diperiksa. Kamu tetap bisa import, "
                    "lalu perbaiki lewat menu Edit Qty Termin."
                )
            )
            issues_box = QPlainTextEdit()
            issues_box.setReadOnly(True)
            issues_box.setMinimumHeight(160)
            issues_box.setPlainText("\n".join(f"• {issue}" for issue in result.issues))
            root.addWidget(issues_box, 1)
        else:
            ok = QLabel("Tidak ada masalah qty. Total termin sudah sama dengan qty RAB.")
            ok.setStyleSheet(f"color: {GREEN};")
            root.addWidget(ok)
            root.addStretch(1)

        self.decimal_check = None
        if result.decimal_rows:
            rows = ", ".join(str(r) for r in sorted(set(result.decimal_rows))[:12])
            self.decimal_check = QCheckBox(
                f"Saya setuju qty desimal (baris {rows}) dibulatkan ke bilangan bulat."
            )
            root.addWidget(self.decimal_check)

        self.ack_check = None
        if result.issues:
            self.ack_check = QCheckBox(
                "Saya sudah membaca masalah di atas dan tetap ingin import."
            )
            root.addWidget(self.ack_check)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        cancel = QPushButton("Batal")
        cancel.clicked.connect(self.reject)
        buttons.addWidget(cancel)
        self.import_btn = button("Import RAB", primary=True)
        self.import_btn.clicked.connect(self._accept)
        buttons.addWidget(self.import_btn)
        root.addLayout(buttons)

        self._update_button()
        if self.decimal_check:
            self.decimal_check.stateChanged.connect(self._update_button)
        if self.ack_check:
            self.ack_check.stateChanged.connect(self._update_button)
        self.adjustSize()

    def _update_button(self) -> None:
        ok = True
        if self.decimal_check and not self.decimal_check.isChecked():
            ok = False
        if self.ack_check and not self.ack_check.isChecked():
            ok = False
        self.import_btn.setEnabled(ok)

    def _accept(self) -> None:
        if self.decimal_check and not self.decimal_check.isChecked():
            return
        if self.ack_check and not self.ack_check.isChecked():
            return
        super().accept()


class TermQtyDialog(QDialog):
    """Editor matriks qty item × termin untuk memperbaiki selisih."""

    def __init__(
        self,
        db: Database,
        project: Project,
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self.setWindowTitle("Edit Qty per Termin")
        self.resize(980, 640)
        self.db = db
        self.project = project
        self.terms = db.list_terms(project.id)
        self.items = db.list_items(project.id)
        self._updating = False
        self.saved = False

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 14)
        root.setSpacing(10)

        title = QLabel("Edit Qty per Termin")
        title.setStyleSheet("font-size: 14pt; font-weight: 600; color: #1F2937;")
        root.addWidget(title)
        root.addWidget(
            muted(
                "Jumlah qty semua termin per item harus sama dengan qty RAB. "
                "Gunakan tabel ini untuk memperbaiki selisih tanpa membuka Excel."
            )
        )

        self.banner = Banner("", self)
        root.addWidget(self.banner)

        self.table = QTableWidget()
        self.table.setColumnCount(4 + len(self.terms) + 2)
        headers = ["No", "Jenis Kendaraan", "Nama Barang", "Qty RAB"] + [
            f"Qty {term.name}" for term in self.terms
        ] + ["Total Termin", "Status"]
        self.table.setHorizontalHeaderLabels(headers)
        setup_table(self.table, row_height=32)
        self.table.setWordWrap(False)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.Fixed)
        header.setSectionResizeMode(1, QHeaderView.Fixed)
        header.setSectionResizeMode(2, QHeaderView.Stretch)
        header.setSectionResizeMode(3, QHeaderView.Fixed)
        for c in range(4, 4 + len(self.terms)):
            header.setSectionResizeMode(c, QHeaderView.Fixed)
        header.setSectionResizeMode(4 + len(self.terms), QHeaderView.Fixed)
        header.setSectionResizeMode(5 + len(self.terms), QHeaderView.Fixed)
        self.table.setColumnWidth(0, 45)
        self.table.setColumnWidth(1, 160)
        self.table.setColumnWidth(3, 80)
        for c in range(4, 4 + len(self.terms)):
            self.table.setColumnWidth(c, 105)
        self.table.setColumnWidth(4 + len(self.terms), 100)
        self.table.setColumnWidth(5 + len(self.terms), 140)

        self.term_qty = db.get_project_term_qty(project.id)
        self.table.setRowCount(len(self.items))
        for row, item in enumerate(self.items):
            self._make_item_row(row, item)
        self.table.itemChanged.connect(self._on_item_changed)
        root.addWidget(self.table, 1)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        cancel = QPushButton("Batal")
        cancel.clicked.connect(self.reject)
        buttons.addWidget(cancel)
        save = button("Simpan Qty Termin", primary=True)
        save.clicked.connect(self._save)
        buttons.addWidget(save)
        root.addLayout(buttons)
        self._refresh_summary()

    def _make_item_row(self, row: int, item: Item) -> None:
        self._updating = True
        no = QTableWidgetItem(str(row + 1))
        no.setTextAlignment(Qt.AlignCenter)
        no.setFlags(no.flags() & ~Qt.ItemIsEditable)
        self.table.setItem(row, 0, no)

        item_type = QTableWidgetItem(item.type_name or "")
        item_type.setFlags(item_type.flags() & ~Qt.ItemIsEditable)
        item_type.setToolTip(item.type_name or "")
        self.table.setItem(row, 1, item_type)

        name = QTableWidgetItem(item.name)
        name.setFlags(name.flags() & ~Qt.ItemIsEditable)
        self.table.setItem(row, 2, name)

        total = QTableWidgetItem(str(item.total_qty))
        total.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
        total.setFlags(total.flags() & ~Qt.ItemIsEditable)
        self.table.setItem(row, 3, total)

        for index, term in enumerate(self.terms):
            qty = self.term_qty.get((term.id, item.id), 0)
            cell = QTableWidgetItem(str(qty))
            cell.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            cell.setData(Qt.UserRole, term.id)
            self.table.setItem(row, 4 + index, cell)

        sum_item = QTableWidgetItem("")
        sum_item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
        sum_item.setFlags(sum_item.flags() & ~Qt.ItemIsEditable)
        self.table.setItem(row, 4 + len(self.terms), sum_item)

        status = QTableWidgetItem("")
        status.setFlags(status.flags() & ~Qt.ItemIsEditable)
        self.table.setItem(row, 5 + len(self.terms), status)
        self._updating = False
        self._update_row(row)

    def _on_item_changed(self, item: QTableWidgetItem) -> None:
        if self._updating:
            return
        term_cols = range(4, 4 + len(self.terms))
        if item.column() not in term_cols:
            return
        text = item.text().strip()
        try:
            qty = int(text)
            if qty < 0:
                raise ValueError
        except ValueError:
            qty = 0
            self._updating = True
            item.setText("0")
            self._updating = False
            QMessageBox.warning(self, "Qty tidak valid", "Qty harus bilangan bulat ≥ 0.")
        else:
            self._updating = True
            item.setText(str(qty))
            self._updating = False
        self._update_row(item.row())
        self._refresh_summary()

    def _row_values(self, row: int) -> tuple[list[int], int]:
        values: list[int] = []
        for index in range(len(self.terms)):
            item = self.table.item(row, 4 + index)
            try:
                values.append(int(item.text()) if item else 0)
            except ValueError:
                values.append(0)
        return values, sum(values)

    def _update_row(self, row: int) -> None:
        item = self.items[row]
        values, total = self._row_values(row)
        self._updating = True
        total_item = self.table.item(row, 4 + len(self.terms))
        total_item.setText(str(total))
        status = self.table.item(row, 5 + len(self.terms))
        if total == item.total_qty:
            status.setText("Cocok")
            status.setForeground(QColor(GREEN))
            total_item.setForeground(QColor(GREEN))
        else:
            diff = total - item.total_qty
            status.setText(f"Selisih {diff:+d}")
            status.setForeground(QColor(RED))
            total_item.setForeground(QColor(RED))
        self._updating = False

    def _mismatch_count(self) -> int:
        count = 0
        for row, item in enumerate(self.items):
            _values, total = self._row_values(row)
            if total != item.total_qty:
                count += 1
        return count

    def _refresh_summary(self) -> None:
        mismatch = self._mismatch_count()
        if mismatch:
            self.banner.set_state(
                "warning",
                f"{mismatch} item masih punya selisih. Alokasi & export akan diblokir "
                "sampai semua qty termin cocok dengan qty RAB.",
            )
        else:
            self.banner.set_state(
                "success", "Semua item cocok. Qty termin siap dipakai."
            )

    def _save(self) -> None:
        mismatch = self._mismatch_count()
        if mismatch:
            answer = QMessageBox.question(
                self,
                "Masih ada selisih",
                f"{mismatch} item masih belum cocok. Simpan tetap? "
                "Alokasi dan export akan diblokir sampai diperbaiki.",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if answer != QMessageBox.Yes:
                return
        with self.db.transaction() as conn:
            for row, item in enumerate(self.items):
                values, _total = self._row_values(row)
                for index, term in enumerate(self.terms):
                    qty = values[index]
                    conn.execute(
                        """INSERT INTO term_qty (term_id, item_id, qty)
                           VALUES (?, ?, ?)
                           ON CONFLICT(term_id, item_id)
                           DO UPDATE SET qty = excluded.qty""",
                        (term.id, item.id, qty),
                    )
        self.db.log(
            self.project.id,
            "edit_qty_termin",
            f"Qty termin diperbarui; {mismatch} item masih selisih",
        )
        self.saved = True
        super().accept()


class ItemsDialog(QDialog):
    """Daftar item RAB + sisa volume yang belum tertagih (F7)."""

    def __init__(
        self,
        db: Database,
        project: Project,
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self.setWindowTitle("Item RAB & Sisa Volume")
        self.resize(1080, 620)
        items = db.list_items(project.id)
        terms = db.list_terms(project.id)
        alloc = db.get_project_allocation_totals(project.id)

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 14)
        root.setSpacing(10)
        title = QLabel("Item RAB & Sisa Volume")
        title.setStyleSheet("font-size: 14pt; font-weight: 600; color: #1F2937;")
        root.addWidget(title)
        root.addWidget(
            muted(
                "Sisa = qty RAB dikurangi seluruh qty yang sudah dialokasikan "
                "di semua termin (terkunci maupun belum)."
            )
        )

        table = QTableWidget()
        headers = [
            "No",
            "Jenis Kendaraan",
            "Nama Barang",
            "Satuan",
            "Harga Satuan",
            "Qty RAB",
        ] + [f"Teralokasi\n{term.name}" for term in terms] + ["Sisa"]
        table.setColumnCount(len(headers))
        table.setHorizontalHeaderLabels(headers)
        setup_table(table, read_only=True, row_height=30)
        header = table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.Fixed)
        header.setSectionResizeMode(1, QHeaderView.Fixed)
        header.setSectionResizeMode(2, QHeaderView.Stretch)
        header.setSectionResizeMode(3, QHeaderView.Fixed)
        header.setSectionResizeMode(4, QHeaderView.Fixed)
        header.setSectionResizeMode(5, QHeaderView.Fixed)
        for c in range(6, 6 + len(terms)):
            header.setSectionResizeMode(c, QHeaderView.Fixed)
        header.setSectionResizeMode(6 + len(terms), QHeaderView.Fixed)
        table.setColumnWidth(0, 45)
        table.setColumnWidth(1, 160)
        table.setColumnWidth(3, 80)
        table.setColumnWidth(4, 120)
        table.setColumnWidth(5, 80)
        for c in range(6, 6 + len(terms)):
            table.setColumnWidth(c, 105)
        table.setColumnWidth(6 + len(terms), 80)

        for row, item in enumerate(items):
            table.insertRow(row)
            values = [
                str(row + 1),
                item.type_name or "",
                item.name,
                item.unit,
                money_text(item.unit_price),
                str(item.total_qty),
            ]
            for term in terms:
                values.append(str(alloc.get((term.id, item.id), 0)))
            allocated = sum(alloc.get((term.id, item.id), 0) for term in terms)
            remaining = item.total_qty - allocated
            values.append(str(remaining))
            for col, value in enumerate(values):
                cell = QTableWidgetItem(value)
                if col >= 4:
                    cell.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                if col == len(values) - 1 and remaining != 0:
                    cell.setForeground(QColor(RED))
                    cell.setToolTip("Masih ada volume yang belum dialokasikan.")
                table.setItem(row, col, cell)
        root.addWidget(table, 1)

        close = button("Tutup", primary=True)
        close.clicked.connect(self.accept)
        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(close)
        root.addLayout(row)
