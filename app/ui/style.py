"""Tema visual aplikasi."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont, QIcon, QPainter, QPixmap

ACCENT = "#B03A2E"
ACCENT_DARK = "#8E2C23"
GREEN = "#1E7B45"
AMBER = "#9A6700"
RED = "#B71C1C"
TEXT = "#263238"
MUTED = "#64748B"
BORDER = "#DDE3E9"

APP_STYLESHEET = """
QWidget {
    font-family: "Segoe UI";
    font-size: 10pt;
    color: #263238;
}
QMainWindow, QDialog {
    background: #F3F5F7;
}
QMenuBar {
    background: #FFFFFF;
    border-bottom: 1px solid #E2E6EA;
    padding: 2px 6px;
}
QMenuBar::item { padding: 5px 10px; border-radius: 4px; }
QMenuBar::item:selected { background: #F2E7E5; }
QMenu {
    background: #FFFFFF;
    border: 1px solid #DDE3E9;
    border-radius: 6px;
    padding: 4px;
}
QMenu::item { padding: 6px 22px 6px 12px; border-radius: 4px; }
QMenu::item:selected { background: #F7EDEB; }
QStatusBar {
    background: #FFFFFF;
    border-top: 1px solid #E2E6EA;
    color: #64748B;
}
QTabWidget::pane {
    border: 1px solid #E2E6EA;
    background: #FFFFFF;
    border-radius: 8px;
    top: -1px;
}
QTabBar::tab {
    background: transparent;
    padding: 9px 18px;
    margin-right: 2px;
    border-bottom: 2px solid transparent;
    color: #64748B;
}
QTabBar::tab:hover { color: #263238; }
QTabBar::tab:selected {
    color: #B03A2E;
    border-bottom: 2px solid #B03A2E;
    font-weight: 600;
}
QGroupBox {
    background: #FFFFFF;
    border: 1px solid #E2E6EA;
    border-radius: 8px;
    margin-top: 16px;
    padding: 14px 12px 12px 12px;
    font-weight: 600;
}
QGroupBox::title {
    subcontrol-origin: margin;
    left: 12px;
    padding: 0 6px;
    color: #B03A2E;
    background-color: #FFFFFF;
}
QPushButton {
    background: #FFFFFF;
    border: 1px solid #CFD6DD;
    border-radius: 6px;
    padding: 6px 14px;
    min-height: 20px;
}
QPushButton:hover { background: #F7F9FA; border-color: #B8C2CC; }
QPushButton:pressed { background: #EEF2F5; }
QPushButton:disabled { color: #9AA5B1; background: #F4F6F8; }
QPushButton#Primary {
    background: #B03A2E;
    border: 1px solid #B03A2E;
    color: #FFFFFF;
    font-weight: 600;
}
QPushButton#Primary:hover { background: #8E2C23; border-color: #8E2C23; }
QPushButton#Primary:disabled { background: #D8A9A3; border-color: #D8A9A3; }
QPushButton#Danger { color: #B71C1C; border-color: #E6B0AA; }
QPushButton#Danger:hover { background: #FDECEA; }
QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox, QDateEdit {
    background: #FFFFFF;
    border: 1px solid #CFD6DD;
    border-radius: 6px;
    padding: 5px 8px;
    min-height: 20px;
    selection-background-color: #B03A2E;
    selection-color: #FFFFFF;
}
QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus, QDateEdit:focus {
    border: 1px solid #B03A2E;
}
QComboBox::drop-down { border: none; width: 22px; }
QComboBox QAbstractItemView {
    background: #FFFFFF;
    border: 1px solid #DDE3E9;
    selection-background-color: #F7EDEB;
    selection-color: #263238;
    outline: 0;
}
QCheckBox { spacing: 7px; }
QTableWidget, QTableView {
    background: #FFFFFF;
    border: 1px solid #E2E6EA;
    border-radius: 6px;
    gridline-color: #EDF0F3;
    selection-background-color: #FDECEA;
    selection-color: #263238;
    alternate-background-color: #FAFBFC;
}
QTableWidget::item, QTableView::item { padding: 4px 6px; }
QHeaderView::section {
    background: #F7F8FA;
    color: #475569;
    border: none;
    border-bottom: 1px solid #E2E6EA;
    border-right: 1px solid #EDF0F3;
    padding: 6px;
    font-weight: 600;
}
QListWidget {
    background: #FFFFFF;
    border: 1px solid #E2E6EA;
    border-radius: 8px;
    outline: 0;
    padding: 4px;
}
QListWidget::item {
    padding: 9px 10px;
    border-radius: 6px;
    margin: 2px 1px;
}
QListWidget::item:hover { background: #F7F9FA; }
QListWidget::item:selected {
    background: #F7EDEB;
    color: #8E2C23;
    font-weight: 600;
}
QScrollArea { border: none; background: transparent; }
QScrollArea > QWidget > QWidget { background: transparent; }
QSplitter::handle { background: transparent; width: 8px; }
QToolTip {
    background: #263238;
    color: #FFFFFF;
    border: none;
    padding: 5px 8px;
    border-radius: 4px;
}
QProgressBar {
    border: 1px solid #DDE3E9;
    border-radius: 5px;
    background: #FFFFFF;
    text-align: center;
    height: 18px;
}
QProgressBar::chunk { background: #B03A2E; border-radius: 4px; }
QTextEdit, QPlainTextEdit {
    background: #FFFFFF;
    border: 1px solid #E2E6EA;
    border-radius: 6px;
}
"""


def app_icon() -> QIcon:
    """Ikon sederhana: huruf I di atas kotak merah."""
    pixmap = QPixmap(64, 64)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)
    painter.setBrush(QColor(ACCENT))
    painter.setPen(Qt.NoPen)
    painter.drawRoundedRect(4, 4, 56, 56, 14, 14)
    painter.setPen(QColor("#FFFFFF"))
    font = QFont("Segoe UI", 30, QFont.Bold)
    painter.setFont(font)
    painter.drawText(pixmap.rect(), Qt.AlignCenter, "I")
    painter.end()
    return QIcon(pixmap)
