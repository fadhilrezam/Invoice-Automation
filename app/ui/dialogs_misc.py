"""Dialog kendaraan, pengaturan, riwayat, dan panduan."""
from __future__ import annotations

import os
import shutil
from pathlib import Path

import openpyxl
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from ..config import bundled_template_path, db_path, default_template_path
from ..db import Database
from ..models import Project
from ..services.vehicle_parser import VehicleParseResult
from ..utils import parse_date_text
from .widgets import Banner, button, muted, setup_table


class VehicleDialog(QDialog):
    def __init__(
        self,
        parent: QWidget | None = None,
        plate: str = "",
        vehicle_type: str = "",
        title: str = "Tambah Kendaraan",
        allow_blank: bool = False,
    ):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumWidth(420)
        self.plate = ""
        self.vehicle_type = ""
        self.allow_blank = allow_blank

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 14)
        root.setSpacing(12)
        form = QFormLayout()
        form.setSpacing(10)
        self.plate_edit = QLineEdit(plate)
        self.plate_edit.setPlaceholderText("mis. D 1001 ABC (boleh dikosongkan)")
        self.type_edit = QLineEdit(vehicle_type)
        self.type_edit.setReadOnly(True)
        form.addRow("No Kendaraan", self.plate_edit)
        form.addRow("Jenis Kendaraan", self.type_edit)
        root.addLayout(form)
        if allow_blank:
            hint = muted("Plat boleh dikosongkan dulu; isi nanti lewat tabel.")
            hint.setWordWrap(True)
            root.addWidget(hint)

        row = QHBoxLayout()
        row.addStretch(1)
        cancel = QPushButton("Batal")
        cancel.clicked.connect(self.reject)
        row.addWidget(cancel)
        save = button("Simpan", primary=True)
        save.clicked.connect(self._accept)
        row.addWidget(save)
        root.addLayout(row)
        self.plate_edit.setFocus()

    def _accept(self) -> None:
        plate = self.plate_edit.text().strip()
        if not plate and not self.allow_blank:
            QMessageBox.warning(self, "Belum lengkap", "Nomor kendaraan wajib diisi.")
            return
        self.plate = plate
        self.vehicle_type = self.type_edit.text().strip()
        super().accept()


class VehicleImportDialog(QDialog):
    def __init__(
        self,
        result: VehicleParseResult,
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self.setWindowTitle("Preview Import Kendaraan")
        self.resize(680, 520)
        self.result = result

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 14)
        root.setSpacing(10)
        title = QLabel("Daftar kendaraan terbaca")
        title.setStyleSheet("font-size: 14pt; font-weight: 600; color: #1F2937;")
        root.addWidget(title)
        root.addWidget(
            Banner(
                f"{len(result.vehicles)} kendaraan dari sheet '{result.sheet}'.",
                self,
            )
        )
        if result.issues:
            root.addWidget(
                Banner("\n".join(result.issues), self)
            )

        table = QTableWidget()
        table.setColumnCount(3)
        table.setHorizontalHeaderLabels(["No", "No Kendaraan", "Tipe Kendaraan"])
        setup_table(table, read_only=True, row_height=28)
        table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Fixed)
        table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        table.setColumnWidth(0, 50)
        table.setRowCount(len(result.vehicles))
        for row, (plate, vehicle_type) in enumerate(result.vehicles):
            no = QTableWidgetItem(str(row + 1))
            no.setTextAlignment(Qt.AlignCenter)
            table.setItem(row, 0, no)
            table.setItem(row, 1, QTableWidgetItem(plate))
            table.setItem(row, 2, QTableWidgetItem(vehicle_type))
        root.addWidget(table, 1)

        note = muted(
            "Import ini akan mengisi ulang plat ke slot unit yang sudah ada. "
            "Jenis kendaraan dicocokkan berdasarkan nama; alokasi qty tidak dihapus."
        )
        note.setWordWrap(True)
        root.addWidget(note)

        row = QHBoxLayout()
        row.addStretch(1)
        cancel = QPushButton("Batal")
        cancel.clicked.connect(self.reject)
        row.addWidget(cancel)
        accept = button("Isi Plat Kendaraan", primary=True)
        accept.clicked.connect(self.accept)
        row.addWidget(accept)
        root.addLayout(row)


class SettingsDialog(QDialog):
    def __init__(self, db: Database, parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle("Pengaturan")
        self.resize(720, 360)
        self.db = db
        self.saved = False

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 14)
        root.setSpacing(12)
        title = QLabel("Pengaturan Aplikasi")
        title.setStyleSheet("font-size: 14pt; font-weight: 600; color: #1F2937;")
        root.addWidget(title)

        form = QFormLayout()
        form.setSpacing(10)
        self.company_edit = QLineEdit(
            db.get_setting("company_name", "CV. PANJI PERKASA")
        )
        self.address_edit = QLineEdit(
            db.get_setting("company_address", "Kab. Bandung, Jawa Barat, Indonesia")
        )
        self.template_edit = QLineEdit(
            db.get_setting("template_path", str(default_template_path()))
        )
        form.addRow("Nama perusahaan", self.company_edit)
        form.addRow("Alamat perusahaan", self.address_edit)

        template_row = QHBoxLayout()
        template_row.addWidget(self.template_edit, 1)
        browse = QPushButton("Pilih...")
        browse.clicked.connect(self._browse_template)
        template_row.addWidget(browse)
        open_btn = QPushButton("Buka")
        open_btn.clicked.connect(self._open_template)
        template_row.addWidget(open_btn)
        reset_btn = QPushButton("Reset")
        reset_btn.clicked.connect(self._reset_template)
        template_row.addWidget(reset_btn)
        form.addRow("Template invoice", template_row)

        db_label = QLineEdit(str(db_path()))
        db_label.setReadOnly(True)
        form.addRow("Lokasi data", db_label)
        root.addLayout(form)

        hint = muted(
            "Template invoice harus punya header 'Qty' dan 'Nama Barang' di baris 10. "
            "Kolom A-D dipakai untuk tabel item. Baris total dan footer akan digeser "
            "otomatis sesuai jumlah item."
        )
        hint.setWordWrap(True)
        root.addWidget(hint)
        root.addStretch(1)

        row = QHBoxLayout()
        row.addStretch(1)
        cancel = QPushButton("Batal")
        cancel.clicked.connect(self.reject)
        row.addWidget(cancel)
        save = button("Simpan", primary=True)
        save.clicked.connect(self._save)
        row.addWidget(save)
        root.addLayout(row)

    def _browse_template(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Pilih template invoice", "", "Excel (*.xlsx)"
        )
        if path:
            self.template_edit.setText(path)

    def _open_template(self) -> None:
        path = Path(self.template_edit.text().strip())
        if not path.exists():
            QMessageBox.warning(self, "Tidak ditemukan", "File template tidak ditemukan.")
            return
        try:
            os.startfile(str(path))  # type: ignore[attr-defined]
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(self, "Gagal membuka", str(exc))

    def _reset_template(self) -> None:
        source = bundled_template_path()
        target = default_template_path()
        if not source.exists():
            QMessageBox.warning(self, "Tidak ditemukan", "Template bawaan tidak ditemukan.")
            return
        try:
            if source.resolve() != target.resolve():
                shutil.copyfile(source, target)
            self.template_edit.setText(str(target))
            QMessageBox.information(self, "Template direset", "Template bawaan berhasil dipulihkan.")
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(self, "Gagal reset", str(exc))

    def _save(self) -> None:
        template = self.template_edit.text().strip()
        path = Path(template)
        if not path.exists():
            QMessageBox.warning(self, "Template tidak ditemukan", "File template tidak ditemukan.")
            return
        try:
            wb = openpyxl.load_workbook(str(path), read_only=True)
            ws = wb.worksheets[0]
            ok = (
                str(ws["A10"].value or "").strip().lower() == "qty"
                and str(ws["B10"].value or "").strip().lower() == "nama barang"
            )
            wb.close()
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(self, "Template tidak valid", f"Gagal membaca template: {exc}")
            return
        if not ok:
            QMessageBox.warning(
                self,
                "Template tidak valid",
                "Baris 10 template harus berisi 'Qty' di kolom A dan 'Nama Barang' di kolom B.",
            )
            return
        self.db.set_setting("company_name", self.company_edit.text().strip())
        self.db.set_setting("company_address", self.address_edit.text().strip())
        self.db.set_setting("template_path", template)
        self.saved = True
        super().accept()


class LogDialog(QDialog):
    def __init__(self, db: Database, project: Project, parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle("Riwayat Aktivitas")
        self.resize(760, 520)
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 14)
        root.setSpacing(10)
        title = QLabel(f"Riwayat Aktivitas - {project.name}")
        title.setStyleSheet("font-size: 14pt; font-weight: 600; color: #1F2937;")
        root.addWidget(title)

        table = QTableWidget()
        table.setColumnCount(3)
        table.setHorizontalHeaderLabels(["Waktu", "Aksi", "Detail"])
        setup_table(table, read_only=True, row_height=28)
        header = table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.Fixed)
        header.setSectionResizeMode(1, QHeaderView.Fixed)
        header.setSectionResizeMode(2, QHeaderView.Stretch)
        table.setColumnWidth(0, 170)
        table.setColumnWidth(1, 160)
        rows = db.list_log(project.id)
        table.setRowCount(len(rows))
        for row, record in enumerate(rows):
            stamp = str(record["ts"]).replace("T", " ")
            table.setItem(row, 0, QTableWidgetItem(stamp))
            table.setItem(row, 1, QTableWidgetItem(record["action"]))
            table.setItem(row, 2, QTableWidgetItem(record["detail"]))
        root.addWidget(table, 1)

        close = button("Tutup", primary=True)
        close.clicked.connect(self.accept)
        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(close)
        root.addLayout(row)


HELP_HTML = """
<h2>Panduan Singkat</h2>
<p><b>1. Buat proyek</b> lalu isi data klien, tipe kendaraan default, dan tanggal invoice.</p>
<p><b>2. Import RAB</b> dari Excel. Aplikasi mendeteksi header otomatis; koreksi pemetaan
kolom bila perlu. RAB boleh berisi banyak jenis kendaraan dengan penanda
<code>NAMA JENIS (N Unit)</code>. Kolom yang dikenali:</p>
<ul>
  <li><b>Nama Barang</b> — nama item/pekerjaan</li>
  <li><b>Satuan</b> — opsional (unit, pcs, liter, dll.)</li>
  <li><b>Harga Satuan</b> — harga per unit</li>
  <li><b>Qty Total</b> — qty RAB (opsional jika ada kolom termin)</li>
  <li><b>Termin</b> — mis. "Termin 1", "Termin 2", "Tahap I"</li>
</ul>
<p>Jika tidak ada kolom termin, semua qty masuk ke satu term yang namanya bisa diisi
di dialog import. Setiap jenis kendaraan otomatis mendapat slot unit sebanyak N.</p>
<p><b>3. Isi plat</b> lewat tabel kendaraan (klik dua kali) atau Import Plat Excel.
Plat boleh dikosongkan dulu; invoice memakai label <code>JENIS #unit</code>.
Import plat hanya mengisi ulang plat, tidak menghapus alokasi qty.</p>
<p><b>3b. Isi Prefix No PO per jenis kendaraan</b> di tabel <b>Prefix No PO per
Jenis Kendaraan</b>. Cukup sekali untuk setiap jenis; prefix otomatis berlaku untuk
semua unit pada jenis itu. No PO tiap invoice = prefix + nomor kendaraan (atau label
<code>JENIS #unit</code> bila plat kosong). Kolom <b>Contoh No PO</b> memperlihatkan
hasilnya.</p>
<p><b>4. Alokasi</b>: pilih termin dan jenis kendaraan, klik <b>Bagi Otomatis</b>.
Proses ini mencakup semua jenis kendaraan pada termin tersebut. Item yang habis dibagi
langsung terisi. Item dengan sisa akan memunculkan antrean konfirmasi: pilih kendaraan
yang menerima tambahan 1 unit. Kamu juga bisa mengedit sel qty secara manual.</p>
<p><b>5. Kunci termin</b> setelah jumlah alokasi tiap item sama dengan qty termin
di semua jenis kendaraan. Export diblokir jika masih ada selisih.</p>
<p><b>6. Export invoice</b>: pilih termin dan plat/unit, lalu export. Satu invoice =
satu plat per termin. Nama sheet invoice = No PO (prefix + plat). Hasil mengikuti
layout <code>invoice_template.xlsx</code> (header, tabel item, sub total, disc, total,
footer tanda tangan). Jumlah baris item menyesuaikan otomatis.</p>
<p>Pilih format <b>Satu workbook, sheet per kendaraan</b> untuk mendapatkan satu file
Excel berisi banyak sheet: sheet <b>Rekap</b> (di posisi pertama), satu sheet
<b>Pivot Qty - {Jenis}</b> per jenis kendaraan (pembagian qty barang per termin
terhadap No PO, dengan filter otomatis berdasarkan Termin), lalu satu sheet per
kendaraan yang bernama No PO.</p>
<h3>Aturan pembagian</h3>
<p>Untuk qty Q dan N kendaraan: dasar = Q // N, sisa R = Q % N. Sebanyak R kendaraan
mendapat tambahan 1, dipilih user. Saran awal memprioritaskan kendaraan yang paling
sedikit menerima item tersebut di termin sebelumnya.</p>
<h3>Lokasi data</h3>
<p>Data tersimpan lokal di <code>%APPDATA%\\InvoiceAutomation\\data.db</code>.
Template bisa diganti lewat menu Pengaturan.</p>
"""


class HelpDialog(QDialog):
    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle("Panduan")
        self.resize(780, 640)
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 14)
        browser = QTextBrowser()
        browser.setHtml(HELP_HTML)
        browser.setOpenExternalLinks(True)
        root.addWidget(browser, 1)
        close = button("Tutup", primary=True)
        close.clicked.connect(self.accept)
        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(close)
        root.addLayout(row)
