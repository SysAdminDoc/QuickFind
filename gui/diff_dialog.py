"""Inline diff dialog for two selected result files."""

import os

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QLabel,
    QPlainTextEdit,
    QVBoxLayout,
)

from core.diff_compare import DiffResult, build_unified_diff
from gui.theme import MOCHA


class DiffCompareDialog(QDialog):
    """Read-only unified diff viewer."""

    def __init__(self, left_path: str, right_path: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Compare Files")
        self.setMinimumSize(820, 560)

        result = build_unified_diff(left_path, right_path)
        self._setup_ui(result)

    def _setup_ui(self, result: DiffResult):
        layout = QVBoxLayout(self)

        header = QLabel(
            f"{os.path.basename(result.left_path)}  ->  {os.path.basename(result.right_path)}"
        )
        header.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        header.setStyleSheet(f"color: {MOCHA['text']}; font-weight: 600; padding: 4px;")
        layout.addWidget(header)

        diff_view = QPlainTextEdit()
        diff_view.setReadOnly(True)
        diff_view.setFont(QFont("Cascadia Code", 10))
        diff_view.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        diff_view.setPlainText(result.error or result.text)
        diff_view.setStyleSheet(f"""
            QPlainTextEdit {{
                background-color: {MOCHA['base']};
                color: {MOCHA['text']};
                border: 1px solid {MOCHA['surface0']};
            }}
        """)
        layout.addWidget(diff_view, 1)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
