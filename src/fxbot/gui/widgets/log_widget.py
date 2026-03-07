"""ログ表示ウィジェット."""

from __future__ import annotations

import logging

from PySide6.QtWidgets import QComboBox, QHBoxLayout, QLabel, QTextEdit, QVBoxLayout, QWidget
from PySide6.QtCore import Signal, QObject
from PySide6.QtGui import QTextCursor


class LogSignal(QObject):
    new_log = Signal(str)


class QTextEditHandler(logging.Handler):
    """ログをQTextEditに転送するハンドラ."""

    def __init__(self):
        super().__init__()
        self.signal = LogSignal()

    def emit(self, record):
        msg = self.format(record)
        self.signal.new_log.emit(msg)


class LogWidget(QWidget):
    """ログ表示ウィジェット."""

    _LEVELS = [
        ("WARNING", logging.WARNING),
        ("INFO", logging.INFO),
        ("ERROR", logging.ERROR),
    ]

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        # レベルセレクター
        header = QHBoxLayout()
        header.addWidget(QLabel("表示レベル:"))
        self.level_combo = QComboBox()
        for name, _ in self._LEVELS:
            self.level_combo.addItem(name)
        self.level_combo.setCurrentIndex(0)  # デフォルト: WARNING
        self.level_combo.currentIndexChanged.connect(self._on_level_changed)
        header.addWidget(self.level_combo)
        header.addStretch()
        layout.addLayout(header)

        self.text_edit = QTextEdit()
        self.text_edit.setReadOnly(True)
        self.text_edit.setStyleSheet(
            "QTextEdit { font-family: 'Consolas', monospace; font-size: 11px; "
            "background-color: #1e1e1e; color: #d4d4d4; }"
        )
        layout.addWidget(self.text_edit)

        # ログハンドラ設定
        self.handler = QTextEditHandler()
        self.handler.setLevel(logging.WARNING)
        self.handler.setFormatter(logging.Formatter(
            "%(asctime)s [%(levelname)-8s] %(message)s",
            datefmt="%H:%M:%S",
        ))
        self.handler.signal.new_log.connect(self._append_log)

        logger = logging.getLogger("fxbot")
        logger.addHandler(self.handler)

    def _on_level_changed(self, index: int) -> None:
        _, level = self._LEVELS[index]
        self.handler.setLevel(level)

    def _append_log(self, msg: str):
        self.text_edit.append(msg)
        self.text_edit.moveCursor(QTextCursor.MoveOperation.End)
