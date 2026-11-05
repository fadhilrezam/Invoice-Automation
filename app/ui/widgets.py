"""Widget & helper UI kecil yang dipakai berulang."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QTableWidget,
    QVBoxLayout,
    QWidget,
)

from .style import ACCENT, AMBER, GREEN, MUTED, RED


def button(text: str, *, primary: bool = False, danger: bool = False) -> QPushButton:
    btn = QPushButton(text)
    if primary:
        btn.setObjectName("Primary")
    elif danger:
        btn.setObjectName("Danger")
    btn.setCursor(Qt.PointingHandCursor)
    return btn


class Card(QFrame):
    """Kotak putih dengan judul."""

    def __init__(self, title: str = "", parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("Card")
        self.setStyleSheet(
            "#Card { background: #FFFFFF; border: 1px solid #E2E6EA; "
            "border-radius: 8px; }"
        )
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(16, 14, 16, 16)
        self._layout.setSpacing(10)
        if title:
            label = QLabel(title)
            label.setStyleSheet(
                "font-size: 11pt; font-weight: 600; color: #B03A2E;"
            )
            self._layout.addWidget(label)
        self.body = QWidget()
        self.body_layout = QVBoxLayout(self.body)
        self.body_layout.setContentsMargins(0, 0, 0, 0)
        self.body_layout.setSpacing(10)
        self._layout.addWidget(self.body)

    def add(self, widget: QWidget) -> None:
        self.body_layout.addWidget(widget)

    def add_layout(self, layout) -> None:
        self.body_layout.addLayout(layout)


class Banner(QLabel):
    """Label status berwarna."""

    def __init__(self, text: str = "", parent: QWidget | None = None):
        super().__init__(text, parent)
        self.setWordWrap(True)
        self.setVisible(bool(text))
        self.set_state("info", text)

    def set_state(self, kind: str, text: str) -> None:
        colors = {
            "info": ("#F1F5F9", "#475569", "#E2E8F0"),
            "success": ("#EAF7EF", GREEN, "#C9E9D5"),
            "warning": ("#FFF8E1", AMBER, "#F2DFA0"),
            "error": ("#FDECEA", RED, "#F3C2BC"),
        }
        bg, fg, border = colors.get(kind, colors["info"])
        self.setText(text)
        self.setVisible(bool(text))
        self.setStyleSheet(
            f"background: {bg}; color: {fg}; border: 1px solid {border}; "
            "border-radius: 6px; padding: 8px 10px;"
        )


def heading(text: str, size: int = 14) -> QLabel:
    label = QLabel(text)
    font = QFont("Segoe UI", size)
    font.setBold(True)
    label.setFont(font)
    label.setStyleSheet("color: #1F2937;")
    return label


def muted(text: str = "") -> QLabel:
    label = QLabel(text)
    label.setStyleSheet(f"color: {MUTED};")
    return label


def hline() -> QFrame:
    line = QFrame()
    line.setFrameShape(QFrame.HLine)
    line.setStyleSheet("color: #E2E6EA;")
    return line


def setup_table(
    table: QTableWidget,
    *,
    stretch_last: bool = False,
    read_only: bool = False,
    row_height: int = 30,
) -> None:
    table.setAlternatingRowColors(True)
    table.setSelectionBehavior(QAbstractItemView.SelectRows)
    table.setSelectionMode(QAbstractItemView.SingleSelection)
    table.setEditTriggers(
        QAbstractItemView.NoEditTriggers if read_only else QAbstractItemView.DoubleClicked
        | QAbstractItemView.EditKeyPressed
    )
    table.verticalHeader().setVisible(False)
    table.verticalHeader().setDefaultSectionSize(row_height)
    table.horizontalHeader().setHighlightSections(False)
    table.setShowGrid(False)
    table.setWordWrap(False)
    if stretch_last:
        table.horizontalHeader().setStretchLastSection(True)


def money_text(value: float | int) -> str:
    return f"{int(round(value)):,}".replace(",", ".")


def set_item(
    table: QTableWidget,
    row: int,
    col: int,
    text: str,
    *,
    align: Qt.AlignmentFlag = Qt.AlignLeft | Qt.AlignVCenter,
    bold: bool = False,
    color: str | None = None,
    bg: str | None = None,
    tooltip: str | None = None,
) -> None:
    from PySide6.QtWidgets import QTableWidgetItem

    item = QTableWidgetItem(text)
    item.setTextAlignment(align)
    if bold:
        font = item.font()
        font.setBold(True)
        item.setFont(font)
    if color:
        item.setForeground(QColor(color))
    if bg:
        item.setBackground(QColor(bg))
    if tooltip:
        item.setToolTip(tooltip)
    item.setFlags(item.flags() & ~Qt.ItemIsEditable)
    table.setItem(row, col, item)


def row_layout(*widgets, spacing: int = 8) -> QHBoxLayout:
    layout = QHBoxLayout()
    layout.setSpacing(spacing)
    for widget in widgets:
        if widget is None:
            layout.addStretch(1)
        else:
            layout.addWidget(widget)
    return layout
