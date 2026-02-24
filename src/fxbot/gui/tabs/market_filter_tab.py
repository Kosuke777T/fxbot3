"""市場フィルタータブ — フィルターステータスとローソク足チャートを表示."""

from __future__ import annotations

from collections import deque
from datetime import datetime

import pandas as pd
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from fxbot.config import Settings
from fxbot.gui.widgets.chart_widget import ChartWidget
from fxbot.logger import get_logger

log = get_logger(__name__)

# 判定ラベルの色
_COLOR_PASS = "#4CAF50"    # 緑
_COLOR_BLOCK = "#F44336"   # 赤
_COLOR_DISABLED = "#9E9E9E"  # グレー


class FilterIndicator(QWidget):
    """1フィルター分のインジケーター行."""

    def __init__(self, display_name: str, parent=None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 2, 4, 2)

        # ● カラードット
        self._dot = QLabel("●")
        self._dot.setFixedWidth(20)
        self._dot.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._dot)

        # フィルター名
        self._name_label = QLabel(display_name)
        self._name_label.setFixedWidth(140)
        self._name_label.setStyleSheet("font-weight: bold;")
        layout.addWidget(self._name_label)

        # 現在値
        self._value_label = QLabel("---")
        self._value_label.setFixedWidth(180)
        layout.addWidget(self._value_label)

        # 閾値
        self._threshold_label = QLabel("---")
        self._threshold_label.setFixedWidth(130)
        layout.addWidget(self._threshold_label)

        # 判定テキスト
        self._result_label = QLabel("---")
        self._result_label.setFixedWidth(80)
        self._result_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._result_label)

        layout.addStretch()

        self._set_color(_COLOR_DISABLED)

    def _set_color(self, color: str):
        self._dot.setStyleSheet(f"color: {color}; font-size: 16px;")
        self._result_label.setStyleSheet(
            f"color: white; background-color: {color}; "
            "border-radius: 4px; padding: 2px 6px; font-weight: bold;"
        )

    def update_status(
        self,
        enabled: bool,
        passed: bool,
        current_value: str,
        threshold_str: str,
        reason: str,
    ):
        """フィルター状態に応じて表示を更新."""
        self._value_label.setText(current_value)
        self._threshold_label.setText(threshold_str)
        self._value_label.setToolTip("")  # 前回のツールチップをクリア

        if not enabled:
            self._set_color(_COLOR_DISABLED)
            self._result_label.setText("無効")
        elif passed:
            self._set_color(_COLOR_PASS)
            self._result_label.setText("通過")
        else:
            self._set_color(_COLOR_BLOCK)
            self._result_label.setText("ブロック")
            if reason:
                self._value_label.setToolTip(reason)


class MarketFilterTab(QWidget):
    """市場フィルタータブ."""

    # フィルター定義: (filter_name, display_name)
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
        # シンボルごとのデータバッファ
        self._symbol_data: dict[str, dict] = {}
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)

        # --- 上部ヘッダー ---
        header_layout = QHBoxLayout()

        header_layout.addWidget(QLabel("シンボル:"))
        self._symbol_combo = QComboBox()
        self._symbol_combo.setFixedWidth(120)
        self._symbol_combo.currentTextChanged.connect(self._on_symbol_changed)
        header_layout.addWidget(self._symbol_combo)

        header_layout.addSpacing(20)

        self._filter_status_label = QLabel("フィルター: 未確認")
        self._filter_status_label.setStyleSheet("font-weight: bold;")
        header_layout.addWidget(self._filter_status_label)

        header_layout.addSpacing(20)

        self._last_update_label = QLabel("最終更新: ---")
        header_layout.addWidget(self._last_update_label)

        header_layout.addStretch()
        layout.addLayout(header_layout)

        # --- フィルターステータスパネル ---
        status_group = QGroupBox("フィルターステータス")
        status_layout = QVBoxLayout(status_group)

        # ヘッダー行
        hdr = QHBoxLayout()
        hdr.setContentsMargins(4, 0, 4, 0)
        for text, width in [
            ("", 20), ("フィルター名", 140), ("現在値", 180),
            ("閾値", 130), ("判定", 80),
        ]:
            lbl = QLabel(text)
            lbl.setFixedWidth(width)
            lbl.setStyleSheet("color: gray; font-size: 11px;")
            hdr.addWidget(lbl)
        hdr.addStretch()
        status_layout.addLayout(hdr)

        # 各フィルターのインジケーター行
        self._indicators: dict[str, FilterIndicator] = {}
        for fname, dname in self._FILTER_DEFS:
            indicator = FilterIndicator(dname)
            self._indicators[fname] = indicator
            status_layout.addWidget(indicator)

        layout.addWidget(status_group)

        # --- ローソク足チャート ---
        chart_group = QGroupBox("ローソク足チャート（HOLDポイント付き）")
        chart_layout = QVBoxLayout(chart_group)
        self._chart = ChartWidget(figsize=(10, 4))
        chart_layout.addWidget(self._chart)
        chart_group.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        layout.addWidget(chart_group, stretch=1)

    # --- 公開 API ---

    def set_symbols(self, symbols: list[str]):
        """シンボルリストを設定."""
        current = self._symbol_combo.currentText()
        self._symbol_combo.blockSignals(True)
        self._symbol_combo.clear()
        self._symbol_combo.addItems(symbols)
        if current in symbols:
            self._symbol_combo.setCurrentText(current)
        self._symbol_combo.blockSignals(False)

        # バッファ初期化
        for sym in symbols:
            if sym not in self._symbol_data:
                self._symbol_data[sym] = {
                    "ohlcv_df": pd.DataFrame(),
                    "hold_timestamps": deque(maxlen=200),
                    "filter_statuses": [],
                }

    def update_filter_status(self, data: dict):
        """ワーカーからのシグナルを受信してバッファを更新."""
        try:
            sym = data.get("symbol", "")
            if not sym:
                return

            if sym not in self._symbol_data:
                self._symbol_data[sym] = {
                    "ohlcv_df": pd.DataFrame(),
                    "hold_timestamps": deque(maxlen=200),
                    "filter_statuses": [],
                }

            buf = self._symbol_data[sym]
            buf["filter_statuses"] = data.get("filter_statuses", [])

            ohlcv_df = data.get("ohlcv_df")
            if isinstance(ohlcv_df, pd.DataFrame) and not ohlcv_df.empty:
                buf["ohlcv_df"] = ohlcv_df

            hold_ts = data.get("hold_timestamp")
            if hold_ts:
                buf["hold_timestamps"].append(hold_ts)

            # 現在選択中のシンボルなら表示更新
            if self._symbol_combo.currentText() == sym:
                self._refresh_display(sym)

            # 最終更新時刻
            self._last_update_label.setText(
                f"最終更新: {datetime.now().strftime('%H:%M:%S')}"
            )
        except Exception as e:
            log.warning(f"フィルター状態更新エラー: {e}")

    # --- 内部メソッド ---

    def _on_symbol_changed(self, symbol: str):
        if not symbol:
            return
        if symbol in self._symbol_data:
            self._refresh_display(symbol)
        else:
            # まだデータが届いていないシンボル → チャートをリセット
            self._chart.plot_candlestick(pd.DataFrame(), [], symbol)

    def _refresh_display(self, symbol: str):
        """選択シンボルの表示を更新."""
        buf = self._symbol_data.get(symbol)
        if not buf:
            return

        filter_statuses = buf["filter_statuses"]
        ohlcv_df = buf["ohlcv_df"]
        hold_timestamps = list(buf["hold_timestamps"])

        # フィルターインジケーター更新
        any_blocked = False
        for fs_dict in filter_statuses:
            fname = fs_dict.get("filter_name", "")
            if fname in self._indicators:
                enabled = fs_dict.get("enabled", False)
                passed = fs_dict.get("passed", True)
                if enabled and not passed:
                    any_blocked = True
                self._indicators[fname].update_status(
                    enabled=enabled,
                    passed=passed,
                    current_value=fs_dict.get("current_value", "---"),
                    threshold_str=fs_dict.get("threshold_str", "---"),
                    reason=fs_dict.get("reason", ""),
                )

        # マスターステータスラベル
        if not self.settings.market_filter.enabled:
            self._filter_status_label.setText("フィルター: 無効")
            self._filter_status_label.setStyleSheet("font-weight: bold; color: gray;")
        elif any_blocked:
            self._filter_status_label.setText("フィルター: ブロックあり")
            self._filter_status_label.setStyleSheet(
                "font-weight: bold; color: #F44336;"
            )
        else:
            self._filter_status_label.setText("フィルター: 有効（全通過）")
            self._filter_status_label.setStyleSheet(
                "font-weight: bold; color: #4CAF50;"
            )

        # ローソク足チャート更新
        self._chart.plot_candlestick(ohlcv_df, hold_timestamps, symbol)
