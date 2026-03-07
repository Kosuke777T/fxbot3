"""全体監視タブ."""

from __future__ import annotations

import json
import re
from pathlib import Path

from PySide6.QtCore import QTimer
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
    QHeaderView,
)

from fxbot.config import Settings
from fxbot.logger import get_logger

log = get_logger(__name__)

_LOG_RE = re.compile(r"^(?P<ts>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}) \[(?P<level>[A-Z]+)\s*\] (?P<body>.*)$")


class SystemAnalysisTab(QWidget):
    """ソフト全体の状態・直近イベントを監視するタブ."""

    def __init__(self, settings: Settings, parent=None):
        super().__init__(parent)
        self.settings = settings
        self._runtime = {
            "connection": "未接続",
            "autotrade": "---",
            "trading": "停止中",
            "trading_running": False,
            "retrain_running": False,
            "last_progress": "---",
            "last_error": "---",
        }
        self._init_ui()

        self._timer = QTimer(self)
        self._timer.timeout.connect(self.refresh)
        self._timer.start(10000)
        self.refresh()

    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)

        status_group = QGroupBox("稼働状態")
        status_layout = QHBoxLayout(status_group)
        self.connection_label = QLabel("MT5接続: ---")
        self.autotrade_label = QLabel("自動売買: ---")
        self.trading_label = QLabel("取引ワーカー: ---")
        self.retrain_label = QLabel("再学習: ---")
        for label in (
            self.connection_label,
            self.autotrade_label,
            self.trading_label,
            self.retrain_label,
        ):
            label.setStyleSheet("font-size: 14px; font-weight: bold;")
            status_layout.addWidget(label)
        status_layout.addStretch()
        layout.addWidget(status_group)

        message_group = QGroupBox("最新メッセージ")
        message_layout = QVBoxLayout(message_group)
        self.progress_label = QLabel("最新進捗: ---")
        self.error_label = QLabel("最新エラー: ---")
        self.progress_label.setWordWrap(True)
        self.error_label.setWordWrap(True)
        message_layout.addWidget(self.progress_label)
        message_layout.addWidget(self.error_label)
        layout.addWidget(message_group)

        summary_group = QGroupBox("運用サマリー")
        summary_layout = QHBoxLayout(summary_group)
        self.log_health_label = QLabel("ログ健全性: ---")
        self.event_summary_label = QLabel("直近イベント: ---")
        self.trade_summary_label = QLabel("取引サマリー: ---")
        self.retrain_summary_label = QLabel("再学習結果: ---")
        for label in (
            self.log_health_label,
            self.event_summary_label,
            self.trade_summary_label,
            self.retrain_summary_label,
        ):
            label.setStyleSheet("font-size: 14px;")
            summary_layout.addWidget(label)
        summary_layout.addStretch()
        layout.addWidget(summary_group)

        self.events_table = QTableWidget()
        self.events_table.setColumnCount(4)
        self.events_table.setHorizontalHeaderLabels(["時刻", "レベル", "ロガー", "内容"])
        self.events_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.events_table.horizontalHeader().setStretchLastSection(True)
        self.events_table.setAlternatingRowColors(True)
        self.events_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.events_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.events_table.setMaximumHeight(260)
        layout.addWidget(self._wrap_group("直近イベント", self.events_table))

        self.trades_table = QTableWidget()
        self.trades_table.setColumnCount(5)
        self.trades_table.setHorizontalHeaderLabels(["時刻", "シンボル", "方向", "損益", "決済理由"])
        self.trades_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.trades_table.horizontalHeader().setStretchLastSection(True)
        self.trades_table.setAlternatingRowColors(True)
        self.trades_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.trades_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        layout.addWidget(self._wrap_group("直近取引", self.trades_table))

    @staticmethod
    def _wrap_group(title: str, widget: QWidget) -> QGroupBox:
        group = QGroupBox(title)
        group_layout = QVBoxLayout(group)
        group_layout.addWidget(widget)
        return group

    def update_runtime_snapshot(
        self,
        *,
        connection: str | None = None,
        autotrade: str | None = None,
        trading: str | None = None,
        trading_running: bool | None = None,
        retrain_running: bool | None = None,
        progress: str | None = None,
        error: str | None = None,
    ) -> None:
        """MainWindow から現在の稼働状態を反映."""
        if connection is not None:
            self._runtime["connection"] = connection
        if autotrade is not None:
            self._runtime["autotrade"] = autotrade
        if trading is not None:
            self._runtime["trading"] = trading
        if trading_running is not None:
            self._runtime["trading_running"] = trading_running
        if retrain_running is not None:
            self._runtime["retrain_running"] = retrain_running
        if progress is not None:
            self._runtime["last_progress"] = progress
        if error is not None:
            self._runtime["last_error"] = error
        self._update_runtime_labels()

    def refresh(self) -> None:
        """ログ・再学習結果・取引DBを再取得して表示."""
        self._update_runtime_labels()
        self._refresh_log_summary()
        self._refresh_trade_summary()
        self._refresh_retrain_summary()

    def _update_runtime_labels(self) -> None:
        self.connection_label.setText(f"MT5接続: {self._runtime['connection']}")
        self.autotrade_label.setText(f"自動売買: {self._runtime['autotrade']}")
        trading_state = "稼働中" if self._runtime["trading_running"] else "停止"
        self.trading_label.setText(f"取引ワーカー: {trading_state} ({self._runtime['trading']})")
        retrain_state = "実行中" if self._runtime["retrain_running"] else "待機"
        self.retrain_label.setText(f"再学習: {retrain_state}")
        self.progress_label.setText(f"最新進捗: {self._runtime['last_progress']}")
        self.error_label.setText(f"最新エラー: {self._runtime['last_error']}")
        self.error_label.setStyleSheet(
            "font-size: 14px; color: #F44336;" if self._runtime["last_error"] != "---" else "font-size: 14px;"
        )

    def _refresh_log_summary(self) -> None:
        log_path = self.settings.resolve_path(self.settings.logging.file)
        lines = self._tail_lines(log_path, 200)
        parsed = [self._parse_log_line(line) for line in lines]
        parsed = [row for row in parsed if row is not None]

        error_count = sum(1 for row in parsed if row["level"] == "ERROR")
        warning_count = sum(1 for row in parsed if row["level"] == "WARNING")
        order_count = sum(1 for row in parsed if "注文約定" in row["message"] or "約定:" in row["message"])
        exit_count = sum(1 for row in parsed if "取引記録[exit]" in row["message"])
        trailing_count = sum(1 for row in parsed if "トレーリング" in row["message"])

        self.log_health_label.setText(f"ログ健全性: ERROR {error_count}件 / WARNING {warning_count}件")
        self.event_summary_label.setText(
            f"直近イベント: 約定 {order_count} / 決済 {exit_count} / トレーリング {trailing_count}"
        )

        rows = list(reversed(parsed[-20:]))
        self.events_table.setRowCount(len(rows))
        for i, row in enumerate(rows):
            self.events_table.setItem(i, 0, QTableWidgetItem(row["ts"]))
            level_item = QTableWidgetItem(row["level"])
            if row["level"] == "ERROR":
                level_item.setForeground(QColor("#F44336"))
            elif row["level"] == "WARNING":
                level_item.setForeground(QColor("#FF9800"))
            self.events_table.setItem(i, 1, level_item)
            self.events_table.setItem(i, 2, QTableWidgetItem(row["logger"]))
            self.events_table.setItem(i, 3, QTableWidgetItem(row["message"]))

    def _refresh_trade_summary(self) -> None:
        if not self.settings.trade_logging.enabled:
            self.trade_summary_label.setText("取引サマリー: 取引ログ無効")
            self.trades_table.setRowCount(0)
            return

        from fxbot.trade_logger import TradeLogger

        db_path = self.settings.resolve_path(self.settings.trade_logging.db_path)
        if not db_path.exists():
            self.trade_summary_label.setText("取引サマリー: DB未作成")
            self.trades_table.setRowCount(0)
            return

        try:
            tl = TradeLogger(db_path)
            total = tl._conn.execute("SELECT COUNT(*) FROM trades").fetchone()[0]
            closed = tl._conn.execute("SELECT COUNT(*) FROM trades WHERE pnl IS NOT NULL").fetchone()[0]
            open_count = total - closed
            rolling = tl.get_rolling_metrics(20)
            recent = tl.get_recent_trades(10)
            tl.close()

            self.trade_summary_label.setText(
                f"取引サマリー: 総数 {total} / 未決済 {open_count} / 直近20件勝率 {rolling.get('win_rate', 0):.1%}"
            )

            self.trades_table.setRowCount(len(recent))
            for i, trade in enumerate(recent):
                ts = (trade.get("exit_time") or trade.get("timestamp") or "")[:19]
                self.trades_table.setItem(i, 0, QTableWidgetItem(ts))
                self.trades_table.setItem(i, 1, QTableWidgetItem(trade.get("symbol", "")))
                self.trades_table.setItem(i, 2, QTableWidgetItem(trade.get("direction", "").upper()))
                pnl = trade.get("pnl")
                pnl_text = f"{pnl:+,.0f}" if pnl is not None else "---"
                pnl_item = QTableWidgetItem(pnl_text)
                if pnl is not None:
                    pnl_item.setForeground(QColor("#4CAF50") if pnl >= 0 else QColor("#F44336"))
                self.trades_table.setItem(i, 3, pnl_item)
                self.trades_table.setItem(i, 4, QTableWidgetItem(trade.get("exit_reason") or "---"))
        except Exception as e:
            log.warning(f"全体監視タブの取引サマリー更新エラー: {e}")
            self.trade_summary_label.setText(f"取引サマリー: エラー ({e})")
            self.trades_table.setRowCount(0)

    def _refresh_retrain_summary(self) -> None:
        log_dir = self.settings.resolve_path("logs")
        files = sorted(log_dir.glob("auto_retrain_*.json")) if log_dir.exists() else []
        if not files:
            self.retrain_summary_label.setText("再学習結果: 履歴なし")
            return

        try:
            latest = files[-1]
            data = json.loads(latest.read_text(encoding="utf-8"))
            ts = str(data.get("timestamp", ""))[:19]
            trained = "学習済" if data.get("trained", False) else "スキップ"
            wr = data.get("wfo_win_rate", 0.0)
            sh = data.get("wfo_sharpe", 0.0)
            self.retrain_summary_label.setText(
                f"再学習結果: {trained} / {ts} / WFO勝率 {wr:.1%} / Sharpe {sh:.2f}"
            )
        except Exception as e:
            self.retrain_summary_label.setText(f"再学習結果: 読込エラー ({e})")

    @staticmethod
    def _tail_lines(path: Path, max_lines: int) -> list[str]:
        if not path.exists():
            return []
        try:
            return path.read_text(encoding="utf-8", errors="ignore").splitlines()[-max_lines:]
        except Exception:
            return []

    @staticmethod
    def _parse_log_line(line: str) -> dict | None:
        match = _LOG_RE.match(line.strip())
        if not match:
            return None
        body = match.group("body")
        logger_name, message = body.split(": ", 1) if ": " in body else ("fxbot", body)
        return {
            "ts": match.group("ts"),
            "level": match.group("level"),
            "logger": logger_name,
            "message": message,
        }
