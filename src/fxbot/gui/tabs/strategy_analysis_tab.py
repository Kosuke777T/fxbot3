"""戦略分析タブ."""

from __future__ import annotations

from PySide6.QtCore import QTimer
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
    QHeaderView,
)

from fxbot.config import Settings
from fxbot.logger import get_logger

log = get_logger(__name__)


class StrategyAnalysisTab(QWidget):
    """売買戦略の判断と成績を分析するタブ."""

    def __init__(self, settings: Settings, parent=None):
        super().__init__(parent)
        self.settings = settings
        self._active_symbols: list[str] = list(settings.trading.active_symbols)
        self._init_ui()

        self._timer = QTimer(self)
        self._timer.timeout.connect(self.refresh)
        self._timer.start(15000)
        self.refresh()

    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)

        header_layout = QHBoxLayout()
        self.symbols_label = QLabel("対象ペア: ---")
        self.symbols_label.setStyleSheet("font-size: 14px; font-weight: bold;")
        header_layout.addWidget(self.symbols_label)
        header_layout.addStretch()
        self.refresh_btn = QPushButton("更新")
        self.refresh_btn.clicked.connect(self.refresh)
        header_layout.addWidget(self.refresh_btn)
        layout.addLayout(header_layout)

        self.message_label = QLabel("")
        self.message_label.setStyleSheet("font-size: 14px; color: gray;")
        layout.addWidget(self.message_label)

        summary_group = QGroupBox("戦略サマリー")
        summary_layout = QHBoxLayout(summary_group)
        self.eval_label = QLabel("総判定数: ---")
        self.entry_label = QLabel("約定数: ---")
        self.hold_label = QLabel("HOLD数: ---")
        self.block_label = QLabel("見送り: ---")
        self.fail_label = QLabel("注文失敗: ---")
        for label in (
            self.eval_label,
            self.entry_label,
            self.hold_label,
            self.block_label,
            self.fail_label,
        ):
            label.setStyleSheet("font-size: 14px;")
            summary_layout.addWidget(label)
        summary_layout.addStretch()
        layout.addWidget(summary_group)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        content = QWidget()
        content_layout = QVBoxLayout(content)

        self.action_table = self._create_table(["判定", "件数", "約定数", "注文失敗"])
        self.hold_reason_table = self._create_table(["HOLD理由", "件数"])
        self.filter_table = self._create_table(["フィルター", "有効回数", "通過回数", "ブロック回数", "通過率"])
        self.exit_reason_table = self._create_table(["決済理由", "件数", "合計損益", "平均損益", "勝率"])
        self.direction_table = self._create_table(["方向", "件数", "合計損益", "平均損益", "勝率"])
        self.hour_table = self._create_table(["時間帯", "件数", "合計損益", "平均損益", "勝率"])
        self.prediction_bucket_table = self._create_table(["予測帯", "件数", "合計損益", "平均損益", "勝率"])
        self.model_version_table = self._create_table(["モデル", "件数", "合計損益", "平均損益", "勝率"])
        self.recent_events_table = self._create_table(
            ["時刻", "シンボル", "判定", "HOLD理由", "見送り理由", "予測値", "信頼度", "ブロックフィルター"]
        )

        content_layout.addWidget(self._wrap_group("判定内訳", self.action_table))
        content_layout.addWidget(self._wrap_group("HOLD理由", self.hold_reason_table))
        content_layout.addWidget(self._wrap_group("フィルター通過率", self.filter_table))
        content_layout.addWidget(self._wrap_group("決済理由別成績", self.exit_reason_table))
        content_layout.addWidget(self._wrap_group("BUY/SELL別成績", self.direction_table))
        content_layout.addWidget(self._wrap_group("時間帯別成績", self.hour_table))
        content_layout.addWidget(self._wrap_group("予測値帯別成績", self.prediction_bucket_table))
        content_layout.addWidget(self._wrap_group("モデル別成績", self.model_version_table))
        content_layout.addWidget(self._wrap_group("直近戦略イベント", self.recent_events_table))
        content_layout.addStretch()

        scroll.setWidget(content)
        layout.addWidget(scroll)

    @staticmethod
    def _create_table(headers: list[str]) -> QTableWidget:
        table = QTableWidget()
        table.setColumnCount(len(headers))
        table.setHorizontalHeaderLabels(headers)
        table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        table.horizontalHeader().setStretchLastSection(True)
        table.setAlternatingRowColors(True)
        table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        table.setMaximumHeight(220)
        return table

    @staticmethod
    def _wrap_group(title: str, widget: QWidget) -> QGroupBox:
        group = QGroupBox(title)
        group_layout = QVBoxLayout(group)
        group_layout.addWidget(widget)
        return group

    def refresh_symbols(self, symbols: list[str]) -> None:
        self._active_symbols = list(symbols)
        self.refresh()

    def refresh(self) -> None:
        if not self.settings.trade_logging.enabled:
            self.symbols_label.setText("対象ペア: ---")
            self.message_label.setText("取引ログが無効です。設定タブで有効にしてください。")
            self._clear_all_tables()
            return

        symbols = self._active_symbols or list(self.settings.trading.active_symbols)
        self.symbols_label.setText(f"対象ペア: {' / '.join(symbols) if symbols else '---'}")

        db_path = self.settings.resolve_path(self.settings.trade_logging.db_path)
        if not db_path.exists():
            self.message_label.setText("取引DBがまだ作成されていません。")
            self._clear_all_tables()
            return

        try:
            from fxbot.trade_logger import TradeLogger

            tl = TradeLogger(db_path)
            summary = tl.get_strategy_summary(symbols)
            action_rows = tl.get_action_breakdown(symbols)
            hold_rows = tl.get_hold_reason_breakdown(symbols)
            filter_rows = tl.get_filter_pass_rates(symbols)
            exit_rows = tl.get_exit_reason_performance(symbols)
            direction_rows = tl.get_direction_performance(symbols)
            hour_rows = tl.get_hourly_performance(symbols)
            bucket_rows = tl.get_prediction_bucket_performance(symbols)
            model_rows = tl.get_model_version_performance(symbols)
            recent_rows = tl.get_recent_analysis_events(symbols, 20)
            tl.close()

            if summary["eval_count"] == 0:
                self.message_label.setText(
                    "分析イベントがまだありません。ライブ取引を実行すると戦略判断ログが蓄積されます。"
                )
            else:
                self.message_label.setText("")

            self.eval_label.setText(f"総判定数: {summary['eval_count']}")
            self.entry_label.setText(
                f"約定数: {summary['entered_count']} ({summary['entry_rate']:.1%})"
            )
            self.hold_label.setText(f"HOLD数: {summary['hold_count']}")
            self.block_label.setText(
                f"見送り: 上限 {summary['position_blocked']} / 劣化 {summary['model_blocked']}"
            )
            self.fail_label.setText(f"注文失敗: {summary['order_failed']}")

            self._fill_action_table(action_rows)
            self._fill_count_table(self.hold_reason_table, hold_rows, ("hold_reason", "count"))
            self._fill_filter_table(filter_rows)
            self._fill_performance_table(self.exit_reason_table, exit_rows, "exit_reason")
            self._fill_performance_table(self.direction_table, direction_rows, "direction")
            self._fill_performance_table(self.hour_table, hour_rows, "hour_bucket")
            self._fill_performance_table(self.prediction_bucket_table, bucket_rows, "bucket")
            self._fill_performance_table(self.model_version_table, model_rows, "model_version")
            self._fill_recent_events_table(recent_rows)

        except Exception as e:
            log.warning(f"戦略分析タブ更新エラー: {e}")
            self.message_label.setText(f"分析データ取得エラー: {e}")
            self._clear_all_tables()

    def _clear_all_tables(self) -> None:
        for table in (
            self.action_table,
            self.hold_reason_table,
            self.filter_table,
            self.exit_reason_table,
            self.direction_table,
            self.hour_table,
            self.prediction_bucket_table,
            self.model_version_table,
            self.recent_events_table,
        ):
            table.setRowCount(0)

    def _fill_action_table(self, rows: list[dict]) -> None:
        self.action_table.setRowCount(len(rows))
        for i, row in enumerate(rows):
            self.action_table.setItem(i, 0, QTableWidgetItem(str(row.get("action", "")).upper()))
            self.action_table.setItem(i, 1, QTableWidgetItem(str(int(row.get("count", 0) or 0))))
            self.action_table.setItem(i, 2, QTableWidgetItem(str(int(row.get("entered_count", 0) or 0))))
            self.action_table.setItem(i, 3, QTableWidgetItem(str(int(row.get("order_failed", 0) or 0))))

    @staticmethod
    def _fill_count_table(table: QTableWidget, rows: list[dict], keys: tuple[str, str]) -> None:
        table.setRowCount(len(rows))
        left_key, right_key = keys
        for i, row in enumerate(rows):
            table.setItem(i, 0, QTableWidgetItem(str(row.get(left_key, ""))))
            table.setItem(i, 1, QTableWidgetItem(str(int(row.get(right_key, 0) or 0))))

    def _fill_filter_table(self, rows: list[dict]) -> None:
        self.filter_table.setRowCount(len(rows))
        for i, row in enumerate(rows):
            self.filter_table.setItem(i, 0, QTableWidgetItem(str(row.get("display_name", ""))))
            self.filter_table.setItem(i, 1, QTableWidgetItem(str(int(row.get("enabled_count", 0) or 0))))
            self.filter_table.setItem(i, 2, QTableWidgetItem(str(int(row.get("pass_count", 0) or 0))))
            self.filter_table.setItem(i, 3, QTableWidgetItem(str(int(row.get("block_count", 0) or 0))))
            rate = row.get("pass_rate")
            rate_text = f"{rate:.1%}" if rate is not None else "---"
            rate_item = QTableWidgetItem(rate_text)
            if rate is not None:
                rate_item.setForeground(QColor("#4CAF50") if rate >= 0.5 else QColor("#F44336"))
            self.filter_table.setItem(i, 4, rate_item)

    def _fill_performance_table(self, table: QTableWidget, rows: list[dict], label_key: str) -> None:
        table.setRowCount(len(rows))
        for i, row in enumerate(rows):
            table.setItem(i, 0, QTableWidgetItem(str(row.get(label_key, ""))))
            table.setItem(i, 1, QTableWidgetItem(str(int(row.get("count", 0) or 0))))

            total_pnl = row.get("total_pnl")
            total_item = QTableWidgetItem(f"{(total_pnl or 0):+,.0f}")
            total_item.setForeground(QColor("#4CAF50") if (total_pnl or 0) >= 0 else QColor("#F44336"))
            table.setItem(i, 2, total_item)

            avg_pnl = row.get("avg_pnl")
            avg_item = QTableWidgetItem(f"{(avg_pnl or 0):+,.0f}")
            avg_item.setForeground(QColor("#4CAF50") if (avg_pnl or 0) >= 0 else QColor("#F44336"))
            table.setItem(i, 3, avg_item)

            win_rate = row.get("win_rate")
            wr_text = f"{win_rate:.1%}" if win_rate is not None else "---"
            wr_item = QTableWidgetItem(wr_text)
            if win_rate is not None:
                wr_item.setForeground(QColor("#4CAF50") if win_rate >= 0.5 else QColor("#F44336"))
            table.setItem(i, 4, wr_item)

    def _fill_recent_events_table(self, rows: list[dict]) -> None:
        self.recent_events_table.setRowCount(len(rows))
        for i, row in enumerate(rows):
            self.recent_events_table.setItem(i, 0, QTableWidgetItem(str(row.get("timestamp", ""))[:19]))
            self.recent_events_table.setItem(i, 1, QTableWidgetItem(str(row.get("symbol", ""))))
            action = str(row.get("action", "")).upper()
            action_item = QTableWidgetItem(action)
            if action == "BUY":
                action_item.setForeground(QColor("#4CAF50"))
            elif action == "SELL":
                action_item.setForeground(QColor("#F44336"))
            self.recent_events_table.setItem(i, 2, action_item)
            self.recent_events_table.setItem(i, 3, QTableWidgetItem(str(row.get("hold_reason") or "---")))
            self.recent_events_table.setItem(i, 4, QTableWidgetItem(str(row.get("skip_reason") or "---")))
            self.recent_events_table.setItem(i, 5, QTableWidgetItem(f"{float(row.get('prediction') or 0.0):.6f}"))
            self.recent_events_table.setItem(i, 6, QTableWidgetItem(f"{float(row.get('confidence') or 0.0):.3f}"))
            blocked = row.get("blocked_filters") or []
            self.recent_events_table.setItem(i, 7, QTableWidgetItem(", ".join(blocked) if blocked else "---"))
