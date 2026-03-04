"""市場フィルタータブ — 3ペア横並びパネルでフィルターステータスを表示."""

from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from fxbot.config import Settings
from fxbot.logger import get_logger

log = get_logger(__name__)

_COLOR_PASS = "#4CAF50"
_COLOR_BLOCK = "#F44336"
_COLOR_DISABLED = "#9E9E9E"


class FilterIndicator(QWidget):
    """1フィルター分のインジケーター行."""

    def __init__(self, display_name: str, parent=None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 2, 4, 2)

        self._dot = QLabel("●")
        self._dot.setFixedWidth(16)
        self._dot.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._dot)

        self._name_label = QLabel(display_name)
        self._name_label.setStyleSheet("font-weight: bold;")
        layout.addWidget(self._name_label)

        layout.addStretch()

        self._result_label = QLabel("---")
        self._result_label.setFixedWidth(60)
        self._result_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._result_label)

        self._set_color(_COLOR_DISABLED)

    def _set_color(self, color: str):
        self._dot.setStyleSheet(f"color: {color}; font-size: 14px;")
        self._result_label.setStyleSheet(
            f"color: white; background-color: {color}; "
            "border-radius: 4px; padding: 2px 4px; font-weight: bold;"
        )

    def update_status(
        self,
        enabled: bool,
        passed: bool,
        current_value: str,
        threshold_str: str,
        reason: str,
    ):
        tooltip = f"現在値: {current_value}  閾値: {threshold_str}"
        if reason:
            tooltip += f"\n{reason}"
        self.setToolTip(tooltip)

        if not enabled:
            self._set_color(_COLOR_DISABLED)
            self._result_label.setText("無効")
        elif passed:
            self._set_color(_COLOR_PASS)
            self._result_label.setText("通過")
        else:
            self._set_color(_COLOR_BLOCK)
            self._result_label.setText("NG")


class MarketFilterTab(QWidget):
    """市場フィルタータブ — 3列横並びパネル."""

    _FILTER_DEFS = [
        ("adx", "ADXフィルター"),
        ("spread", "スプレッドフィルター"),
        ("volatility", "ボラティリティ"),
        ("session", "セッションフィルター"),
        ("confidence", "信頼度チェック"),
    ]

    def __init__(self, settings: Settings, parent=None):
        super().__init__(parent)
        self.settings = settings
        self._panels: dict[str, dict] = {}
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)

        # ヘッダー行
        header_layout = QHBoxLayout()
        title = QLabel("市場フィルター")
        title.setStyleSheet("font-size: 14px; font-weight: bold;")
        header_layout.addWidget(title)
        header_layout.addStretch()
        self._update_time = QLabel("最終更新: ---")
        header_layout.addWidget(self._update_time)
        layout.addLayout(header_layout)

        # 3列パネルコンテナ
        self._panels_container = QHBoxLayout()
        layout.addLayout(self._panels_container)
        layout.addStretch()

        # 初期メッセージ
        self._empty_label = QLabel("通貨ペアが選択されていません。「通貨ペア」タブで選択してください。")
        self._empty_label.setStyleSheet("color: gray; padding: 20px;")
        layout.addWidget(self._empty_label)
        layout.addStretch()

        self._outer_layout = layout

    def _build_symbol_panel(self, sym: str) -> QGroupBox:
        group = QGroupBox(sym)
        group.setMinimumWidth(220)
        panel_layout = QVBoxLayout(group)

        status_label = QLabel("● 未確認")
        status_label.setStyleSheet("font-weight: bold; color: gray;")
        panel_layout.addWidget(status_label)

        indicators: dict[str, FilterIndicator] = {}
        for key, name in self._FILTER_DEFS:
            ind = FilterIndicator(name)
            panel_layout.addWidget(ind)
            indicators[key] = ind

        panel_layout.addStretch()
        self._panels[sym] = {
            "group": group,
            "status": status_label,
            "indicators": indicators,
        }
        return group

    def refresh_symbols(self, symbols: list[str]) -> None:
        """active_symbols 変更時にパネルを再構築."""
        # 既存パネルを削除
        for sym, panel in self._panels.items():
            panel["group"].setParent(None)
            panel["group"].deleteLater()
        self._panels.clear()

        if not symbols:
            self._empty_label.show()
            return

        self._empty_label.hide()

        for sym in symbols:
            panel = self._build_symbol_panel(sym)
            self._panels_container.addWidget(panel)

        # 残余スペースを埋める
        self._panels_container.addStretch()

    def update_filter_status(self, data: dict) -> None:
        """ワーカーからのシグナルを受信してパネルを更新."""
        try:
            sym = data.get("symbol", "")
            if not sym or sym not in self._panels:
                return

            panel = self._panels[sym]
            statuses = data.get("filter_statuses", [])

            all_passed = all(
                fs.get("passed", True)
                for fs in statuses
                if fs.get("enabled", False)
            )

            if not self.settings.market_filter.enabled:
                panel["status"].setText("● 無効")
                panel["status"].setStyleSheet("font-weight: bold; color: gray;")
            elif all_passed:
                panel["status"].setText("● 通過")
                panel["status"].setStyleSheet(f"font-weight: bold; color: {_COLOR_PASS};")
            else:
                panel["status"].setText("● ブロック")
                panel["status"].setStyleSheet(f"font-weight: bold; color: {_COLOR_BLOCK};")

            for fs in statuses:
                ind = panel["indicators"].get(fs.get("filter_name", ""))
                if ind:
                    ind.update_status(
                        enabled=fs.get("enabled", False),
                        passed=fs.get("passed", True),
                        current_value=fs.get("current_value", "---"),
                        threshold_str=fs.get("threshold_str", "---"),
                        reason=fs.get("reason", ""),
                    )

            self._update_time.setText(f"最終更新: {datetime.now().strftime('%H:%M:%S')}")

        except Exception as e:
            log.warning(f"フィルター状態更新エラー: {e}")
