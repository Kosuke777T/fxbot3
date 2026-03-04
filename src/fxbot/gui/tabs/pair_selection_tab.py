"""通貨ペア選択タブ — 最大3ペアをチェックボックスで選択・保存."""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from fxbot.config import Settings, save_settings
from fxbot.logger import get_logger

log = get_logger(__name__)

MAX_PAIRS = 3


class PairSelectionTab(QWidget):
    """通貨ペア選択タブ."""

    settings_changed = Signal()

    def __init__(self, settings: Settings, parent=None):
        super().__init__(parent)
        self.settings = settings
        self._checkboxes: dict[str, QCheckBox] = {}
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)

        # --- ペア選択グループ ---
        group = QGroupBox(f"取引通貨ペア（最大{MAX_PAIRS}つ）")
        group_layout = QVBoxLayout(group)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        self._scroll_content = QWidget()
        self._scroll_layout = QVBoxLayout(self._scroll_content)
        self._scroll_layout.addStretch()
        scroll.setWidget(self._scroll_content)
        group_layout.addWidget(scroll)

        layout.addWidget(group, stretch=1)

        # --- 選択中ペア表示 ---
        sel_layout = QHBoxLayout()
        sel_layout.addWidget(QLabel("選択中:"))
        self._selected_label = QLabel("（未選択）")
        self._selected_label.setStyleSheet("font-weight: bold; color: #1976D2;")
        sel_layout.addWidget(self._selected_label)
        sel_layout.addStretch()
        layout.addLayout(sel_layout)

        # --- 保存ボタン ---
        self._save_btn = QPushButton("保存")
        self._save_btn.setStyleSheet(
            "QPushButton { background-color: #4CAF50; color: white; "
            "padding: 6px 20px; font-weight: bold; }"
        )
        self._save_btn.clicked.connect(self._save)
        layout.addWidget(self._save_btn)

    def set_symbols(self, symbols: list[str]) -> None:
        """利用可能シンボル一覧をセット（main_windowから呼び出し）."""
        active = self.settings.trading.active_symbols

        # 既存チェックボックスをクリア（最後のstretchを残す）
        while self._scroll_layout.count() > 1:
            item = self._scroll_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        self._checkboxes.clear()

        for sym in symbols:
            cb = QCheckBox(sym)
            cb.setChecked(sym in active)
            cb.toggled.connect(lambda checked, s=sym: self._on_checkbox_toggled(s, checked))
            self._scroll_layout.insertWidget(self._scroll_layout.count() - 1, cb)
            self._checkboxes[sym] = cb

        self._update_selected_label()

    def _on_checkbox_toggled(self, symbol: str, checked: bool) -> None:
        """3つ超えたら4つ目のチェックを拒否."""
        if checked:
            selected = [s for s, cb in self._checkboxes.items() if cb.isChecked()]
            if len(selected) > MAX_PAIRS:
                cb = self._checkboxes[symbol]
                cb.blockSignals(True)
                cb.setChecked(False)
                cb.blockSignals(False)
                QMessageBox.warning(
                    self,
                    "選択上限",
                    f"取引ペアは最大{MAX_PAIRS}つまで選択できます。\n"
                    "現在選択中のペアを解除してから追加してください。",
                )
                return
        self._update_selected_label()

    def _update_selected_label(self) -> None:
        selected = [s for s, cb in self._checkboxes.items() if cb.isChecked()]
        if selected:
            self._selected_label.setText(" / ".join(selected))
        else:
            self._selected_label.setText("（未選択）")

    def _save(self) -> None:
        selected = [s for s, cb in self._checkboxes.items() if cb.isChecked()]
        self.settings.trading.active_symbols = selected
        save_settings(self.settings)
        self.settings_changed.emit()
        log.info(f"取引ペア保存: {selected}")
        QMessageBox.information(
            self,
            "保存完了",
            f"取引ペアを保存しました:\n{', '.join(selected) or '（なし）'}",
        )
