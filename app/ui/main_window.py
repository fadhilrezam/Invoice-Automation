"""Jendela utama aplikasi."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import (
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QStackedWidget,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from ..config import APP_TITLE, db_path
from ..db import Database
from ..models import Project
from .allocation_tab import AllocationTab
from .dialogs_misc import HelpDialog, LogDialog, SettingsDialog
from .export_tab import ExportTab
from .project_tab import ProjectTab
from .style import app_icon
from .widgets import button, heading, muted


class NewProjectDialog(QDialog):
    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle("Proyek Baru")
        self.setMinimumWidth(480)
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 14)
        root.setSpacing(12)
        title = QLabel("Buat proyek baru")
        title.setStyleSheet("font-size: 14pt; font-weight: 600; color: #1F2937;")
        root.addWidget(title)
        root.addWidget(
            muted("Isi nama proyek dulu. Data klien dan RAB bisa dilengkapi setelahnya.")
        )
        form = QFormLayout()
        form.setSpacing(10)
        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("mis. Pemeliharaan Kendaraan Dinas 2026")
        self.client_edit = QLineEdit()
        self.client_edit.setPlaceholderText("mis. POLRESTA BANDUNG")
        form.addRow("Nama proyek", self.name_edit)
        form.addRow("Kepada Yth", self.client_edit)
        root.addLayout(form)
        row = QHBoxLayout()
        row.addStretch(1)
        cancel = QPushButton("Batal")
        cancel.clicked.connect(self.reject)
        row.addWidget(cancel)
        create = button("Buat Proyek", primary=True)
        create.clicked.connect(self._accept)
        row.addWidget(create)
        root.addLayout(row)
        self.name_edit.setFocus()

    def _accept(self) -> None:
        if not self.name_edit.text().strip():
            QMessageBox.warning(self, "Belum lengkap", "Nama proyek wajib diisi.")
            return
        super().accept()

    @property
    def project_name(self) -> str:
        return self.name_edit.text().strip()

    @property
    def client_name(self) -> str:
        return self.client_edit.text().strip()


class MainWindow(QMainWindow):
    def __init__(self, db: Database):
        super().__init__()
        self.db = db
        self.project: Project | None = None
        self.setWindowTitle(APP_TITLE)
        self.setWindowIcon(app_icon())
        self.resize(1360, 860)
        self.setMinimumSize(1080, 680)
        self._build_ui()
        self._build_menu()
        self.statusBar().showMessage(f"Data: {db_path()}")
        self.refresh_projects()

    # ------------------------------------------------------------------ UI
    def _build_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        layout = QHBoxLayout(central)
        layout.setContentsMargins(14, 14, 14, 10)
        layout.setSpacing(14)

        sidebar = QWidget()
        sidebar.setFixedWidth(250)
        side = QVBoxLayout(sidebar)
        side.setContentsMargins(0, 0, 0, 0)
        side.setSpacing(10)

        brand = QLabel("INVOICE")
        brand.setStyleSheet(
            "font-size: 18pt; font-weight: 800; color: #B03A2E; letter-spacing: 2px;"
        )
        side.addWidget(brand)
        tagline = muted("Pembagian RAB ke kendaraan")
        tagline.setStyleSheet("color: #64748B; margin-bottom: 4px;")
        side.addWidget(tagline)

        self.project_list = QListWidget()
        self.project_list.setSpacing(2)
        self.project_list.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.project_list.setTextElideMode(Qt.ElideRight)
        self.project_list.currentItemChanged.connect(self._project_selected)
        side.addWidget(self.project_list, 1)

        new_btn = button("+  Proyek Baru", primary=True)
        new_btn.clicked.connect(self.new_project)
        side.addWidget(new_btn)
        delete_btn = button("Hapus Proyek", danger=True)
        delete_btn.clicked.connect(self.delete_project)
        side.addWidget(delete_btn)
        layout.addWidget(sidebar)

        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(10)

        header = QHBoxLayout()
        self.project_title = heading("Belum ada proyek", 16)
        header.addWidget(self.project_title)
        self.project_badge = muted("")
        header.addWidget(self.project_badge)
        header.addStretch(1)
        content_layout.addLayout(header)

        self.stack = QStackedWidget()
        content_layout.addWidget(self.stack, 1)

        empty = QWidget()
        empty_layout = QVBoxLayout(empty)
        empty_layout.setContentsMargins(30, 30, 30, 30)
        empty_layout.addStretch(1)
        empty_title = heading("Mulai dengan membuat proyek", 18)
        empty_title.setAlignment(Qt.AlignCenter)
        empty_layout.addWidget(empty_title)
        empty_text = muted(
            "Satu proyek berisi satu RAB, satu daftar kendaraan, dan beberapa termin.\n"
            "Setelah proyek dibuat, import RAB dan daftar kendaraan dari Excel."
        )
        empty_text.setAlignment(Qt.AlignCenter)
        empty_text.setWordWrap(True)
        empty_layout.addWidget(empty_text)
        empty_btn_row = QHBoxLayout()
        empty_btn_row.addStretch(1)
        empty_btn = button("Buat Proyek Pertama", primary=True)
        empty_btn.clicked.connect(self.new_project)
        empty_btn_row.addWidget(empty_btn)
        empty_btn_row.addStretch(1)
        empty_layout.addLayout(empty_btn_row)
        empty_layout.addStretch(2)
        self.stack.addWidget(empty)

        self.tabs = QTabWidget()
        self.project_tab = ProjectTab(self.db)
        self.allocation_tab = AllocationTab(self.db)
        self.export_tab = ExportTab(self.db)
        self.tabs.addTab(self.project_tab, "1. Data Proyek")
        self.tabs.addTab(self.allocation_tab, "2. Alokasi Termin")
        self.tabs.addTab(self.export_tab, "3. Export Invoice")
        self.stack.addWidget(self.tabs)

        self.project_tab.data_changed.connect(self._data_changed)
        self.allocation_tab.data_changed.connect(self._allocation_changed)
        self.tabs.currentChanged.connect(self._tab_changed)
        layout.addWidget(content, 1)

    def _build_menu(self) -> None:
        menu = self.menuBar()

        berkas = menu.addMenu("Berkas")
        settings_action = QAction("Pengaturan...", self)
        settings_action.triggered.connect(self.open_settings)
        berkas.addAction(settings_action)
        berkas.addSeparator()
        quit_action = QAction("Keluar", self)
        quit_action.setShortcut(QKeySequence.Quit)
        quit_action.triggered.connect(self.close)
        berkas.addAction(quit_action)

        proyek = menu.addMenu("Proyek")
        new_action = QAction("Proyek Baru", self)
        new_action.setShortcut(QKeySequence.New)
        new_action.triggered.connect(self.new_project)
        proyek.addAction(new_action)
        delete_action = QAction("Hapus Proyek", self)
        delete_action.triggered.connect(self.delete_project)
        proyek.addAction(delete_action)
        proyek.addSeparator()
        log_action = QAction("Riwayat Aktivitas", self)
        log_action.triggered.connect(self.open_log)
        proyek.addAction(log_action)

        bantuan = menu.addMenu("Bantuan")
        help_action = QAction("Panduan", self)
        help_action.setShortcut(QKeySequence.HelpContents)
        help_action.triggered.connect(self.open_help)
        bantuan.addAction(help_action)
        about_action = QAction("Tentang", self)
        about_action.triggered.connect(self.open_about)
        bantuan.addAction(about_action)

    # -------------------------------------------------------------- projects
    def refresh_projects(self, select_id: int | None = None) -> None:
        if select_id is None and self.project:
            select_id = self.project.id
        projects = self.db.list_projects()
        self.project_list.blockSignals(True)
        self.project_list.clear()
        selected_row = -1
        for index, project in enumerate(projects):
            item = QListWidgetItem(project.name)
            item.setData(Qt.UserRole, project.id)
            item.setToolTip(
                f"Klien: {project.client_name or '-'}\n"
                f"Tanggal invoice: {project.invoice_date}"
            )
            self.project_list.addItem(item)
            if project.id == select_id:
                selected_row = index
        self.project_list.blockSignals(False)

        if not projects:
            self.project = None
            self.project_title.setText("Belum ada proyek")
            self.project_badge.setText("")
            self.stack.setCurrentIndex(0)
            return
        if selected_row < 0:
            selected_row = 0
        self.project_list.setCurrentRow(selected_row)

    def _project_selected(self, current: QListWidgetItem | None, previous=None) -> None:
        if current is None:
            return
        project_id = current.data(Qt.UserRole)
        if project_id is None:
            return
        project = self.db.get_project(int(project_id))
        if not project:
            return
        self.project = project
        self.project_title.setText(project.name)
        bits = []
        if project.client_name:
            bits.append(project.client_name)
        if project.vehicle_type:
            bits.append(project.vehicle_type)
        self.project_badge.setText("  •  ".join(bits))
        self.project_badge.setStyleSheet("color: #64748B;")
        self.project_tab.set_project(project)
        self.allocation_tab.set_project(project)
        self.export_tab.set_project(project)
        self.stack.setCurrentWidget(self.tabs)

    def _data_changed(self) -> None:
        if not self.project:
            return
        project = self.db.get_project(self.project.id)
        if not project:
            return
        self.project = project
        for index in range(self.project_list.count()):
            item = self.project_list.item(index)
            if item.data(Qt.UserRole) == project.id:
                item.setText(project.name)
                break
        self.project_title.setText(project.name)
        self.project_tab.set_project(project)
        self.allocation_tab.set_project(project)
        self.export_tab.set_project(project)

    def _allocation_changed(self) -> None:
        if not self.project:
            return
        self.project_tab.refresh()
        self.export_tab.refresh()

    def _tab_changed(self, index: int) -> None:
        if not self.project:
            return
        if index == 1:
            self.allocation_tab.refresh()
        elif index == 2:
            self.export_tab.refresh()

    # --------------------------------------------------------------- actions
    def new_project(self) -> None:
        dialog = NewProjectDialog(self)
        if dialog.exec() != QDialog.Accepted:
            return
        project_id = self.db.create_project(
            dialog.project_name, client_name=dialog.client_name
        )
        self.refresh_projects(select_id=project_id)
        self.tabs.setCurrentIndex(0)

    def delete_project(self) -> None:
        if not self.project:
            QMessageBox.information(self, "Tidak ada proyek", "Belum ada proyek yang dipilih.")
            return
        answer = QMessageBox.question(
            self,
            "Hapus proyek",
            f"Hapus proyek '{self.project.name}' beserta seluruh RAB, termin, "
            "alokasi, dan riwayatnya? Tindakan ini tidak bisa dibatalkan.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return
        self.db.delete_project(self.project.id)
        self.project = None
        self.project_tab.set_project(None)
        self.allocation_tab.set_project(None)
        self.export_tab.set_project(None)
        self.refresh_projects(select_id=-1)

    def open_settings(self) -> None:
        dialog = SettingsDialog(self.db, self)
        if dialog.exec() == QDialog.Accepted and dialog.saved:
            self.export_tab.refresh()

    def open_log(self) -> None:
        if not self.project:
            QMessageBox.information(self, "Tidak ada proyek", "Pilih proyek terlebih dahulu.")
            return
        LogDialog(self.db, self.project, self).exec()

    def open_help(self) -> None:
        HelpDialog(self).exec()

    def open_about(self) -> None:
        QMessageBox.about(
            self,
            "Tentang Invoice Automation",
            "<h3>Invoice Automation 1.0</h3>"
            "<p>Aplikasi lokal untuk membagi qty RAB ke kendaraan per termin "
            "dan mengekspor invoice Excel sesuai template.</p>"
            "<p>Python + PySide6 + openpyxl + SQLite.</p>"
            "<p>Data tersimpan di:<br><code>%APPDATA%\\InvoiceAutomation\\data.db</code></p>",
        )
