"""取引ログタブ — SQLite 全取引レコードの表示・検索・CSV出力."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGroupBox,
    QLabel, QTableWidget, QTableWidgetItem, QPushButton,
    QComboBox, QHeaderView, QFileDialog, QMessageBox,
)
from PySide6.QtGui import QColor

from fxbot.config import Settings
from fxbot.logger import get_logger

log = get_logger(__name__)

_LIMIT_OPTIONS = [("50件", 50), ("200件", 200), ("全件", 999999)]
_DIR_OPTIONS = ["全て", "BUY", "SELL"]

_HEADERS = ["時刻", "決済時刻", "シンボル", "方向", "ロット", "建値", "決済価格", "損益", "決済理由", "信頼度"]


class TradeLogTab(QWidget):
    """取引ログタブ — 全取引を閲覧・フィルター・エクスポート."""

    def __init__(self, settings: Settings, parent=None):
        super().__init__(parent)
        self.settings = settings
        self._init_ui()
        self.refresh()

    def _init_ui(self):
        layout = QVBoxLayout(self)

        # === サマリーバー ===
        summary_group = QGroupBox("サマリー")
        summary_layout = QHBoxLayout()

        self.total_label = QLabel("総取引数: ---")
        self.total_label.setStyleSheet("font-size: 14px; font-weight: bold;")
        summary_layout.addWidget(self.total_label)

        self.win_rate_label = QLabel("勝率: ---")
        self.win_rate_label.setStyleSheet("font-size: 14px;")
        summary_layout.addWidget(self.win_rate_label)

        self.total_pnl_label = QLabel("合計損益: ---")
        self.total_pnl_label.setStyleSheet("font-size: 14px;")
        summary_layout.addWidget(self.total_pnl_label)

        summary_layout.addStretch()
        summary_group.setLayout(summary_layout)
        layout.addWidget(summary_group)

        # === フィルターバー ===
        filter_layout = QHBoxLayout()

        filter_layout.addWidget(QLabel("表示件数:"))
        self.limit_combo = QComboBox()
        for label, _ in _LIMIT_OPTIONS:
            self.limit_combo.addItem(label)
        filter_layout.addWidget(self.limit_combo)

        filter_layout.addWidget(QLabel("方向:"))
        self.dir_combo = QComboBox()
        for d in _DIR_OPTIONS:
            self.dir_combo.addItem(d)
        filter_layout.addWidget(self.dir_combo)

        filter_layout.addStretch()

        self.refresh_btn = QPushButton("リフレッシュ")
        self.refresh_btn.clicked.connect(self.refresh)
        filter_layout.addWidget(self.refresh_btn)

        self.export_btn = QPushButton("CSVエクスポート")
        self.export_btn.setStyleSheet(
            "QPushButton { background-color: #2196F3; color: white; padding: 4px 12px; }"
        )
        self.export_btn.clicked.connect(self._export_csv)
        filter_layout.addWidget(self.export_btn)

        layout.addLayout(filter_layout)

        # === テーブル ===
        self.table = QTableWidget()
        self.table.setColumnCount(len(_HEADERS))
        self.table.setHorizontalHeaderLabels(_HEADERS)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setAlternatingRowColors(True)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        layout.addWidget(self.table)

        # 無効メッセージ用ラベル（初期は非表示）
        self.disabled_label = QLabel("取引ログが無効です（設定タブで有効にしてください）")
        self.disabled_label.setStyleSheet("font-size: 14px; color: gray;")
        self.disabled_label.setVisible(False)
        layout.addWidget(self.disabled_label)

    def refresh(self):
        """データを再取得してテーブルを更新."""
        if not self.settings.trade_logging.enabled:
            self.table.setVisible(False)
            self.disabled_label.setVisible(True)
            self._reset_summary("ログ無効")
            return

        self.table.setVisible(True)
        self.disabled_label.setVisible(False)

        try:
            from fxbot.trade_logger import TradeLogger

            db_path = self.settings.resolve_path(self.settings.trade_logging.db_path)
            if not db_path.exists():
                self._reset_summary("DB未作成")
                self.table.setRowCount(0)
                return

            tl = TradeLogger(db_path)

            # 件数セレクト
            limit = _LIMIT_OPTIONS[self.limit_combo.currentIndex()][1]
            trades = tl.get_recent_trades(limit)
            tl.close()

            # 方向フィルター
            direction_filter = self.dir_combo.currentText()
            if direction_filter != "全て":
                trades = [t for t in trades if t.get("direction", "").upper() == direction_filter]

            self._populate_table(trades)
            self._update_summary(trades)

        except Exception as e:
            log.warning(f"取引ログ更新エラー: {e}")
            self._reset_summary("エラー")

    def _populate_table(self, trades: list[dict]):
        """テーブルにデータをセット."""
        self.table.setRowCount(len(trades))
        for i, t in enumerate(trades):
            ts = (t.get("timestamp") or "")[:19]
            exit_time = (t.get("exit_time") or "")[:19]
            symbol = t.get("symbol", "")
            direction = t.get("direction", "").upper()
            lot = t.get("lot", 0)
            entry_price = t.get("entry_price", 0)
            exit_price = t.get("exit_price")
            pnl = t.get("pnl")
            exit_reason = t.get("exit_reason") or "---"
            confidence = t.get("confidence")

            self.table.setItem(i, 0, QTableWidgetItem(ts))
            self.table.setItem(i, 1, QTableWidgetItem(exit_time if exit_time else "---"))
            self.table.setItem(i, 2, QTableWidgetItem(symbol))

            dir_item = QTableWidgetItem(direction)
            dir_item.setForeground(
                QColor("#4CAF50") if direction == "BUY" else QColor("#F44336")
            )
            self.table.setItem(i, 3, dir_item)

            self.table.setItem(i, 4, QTableWidgetItem(f"{lot:.2f}"))
            self.table.setItem(i, 5, QTableWidgetItem(f"{entry_price:.5f}"))
            self.table.setItem(i, 6, QTableWidgetItem(f"{exit_price:.5f}" if exit_price is not None else "---"))

            pnl_str = f"{pnl:+.0f}" if pnl is not None else "---"
            pnl_item = QTableWidgetItem(pnl_str)
            if pnl is not None:
                pnl_item.setForeground(
                    QColor("#4CAF50") if pnl >= 0 else QColor("#F44336")
                )
            self.table.setItem(i, 7, pnl_item)

            self.table.setItem(i, 8, QTableWidgetItem(exit_reason))
            self.table.setItem(
                i, 9,
                QTableWidgetItem(f"{confidence:.3f}" if confidence is not None else "---")
            )

    def _update_summary(self, trades: list[dict]):
        """サマリーバーを更新."""
        closed = [t for t in trades if t.get("pnl") is not None]
        total = len(trades)
        n_closed = len(closed)

        self.total_label.setText(f"総取引数: {total}件 (決済済: {n_closed}件)")

        if n_closed > 0:
            wins = sum(1 for t in closed if t["pnl"] > 0)
            win_rate = wins / n_closed
            wr_color = "#4CAF50" if win_rate >= 0.5 else "#F44336"
            self.win_rate_label.setText(f"勝率: {win_rate:.1%}")
            self.win_rate_label.setStyleSheet(f"font-size: 14px; color: {wr_color};")

            total_pnl = sum(t["pnl"] for t in closed)
            pnl_color = "#4CAF50" if total_pnl >= 0 else "#F44336"
            self.total_pnl_label.setText(f"合計損益: {total_pnl:+,.0f}")
            self.total_pnl_label.setStyleSheet(f"font-size: 14px; color: {pnl_color};")
        else:
            self.win_rate_label.setText("勝率: ---")
            self.win_rate_label.setStyleSheet("font-size: 14px;")
            self.total_pnl_label.setText("合計損益: ---")
            self.total_pnl_label.setStyleSheet("font-size: 14px;")

    def _reset_summary(self, reason: str):
        """サマリーをリセット."""
        self.total_label.setText(f"総取引数: --- ({reason})")
        self.win_rate_label.setText("勝率: ---")
        self.win_rate_label.setStyleSheet("font-size: 14px;")
        self.total_pnl_label.setText("合計損益: ---")
        self.total_pnl_label.setStyleSheet("font-size: 14px;")

    def _export_csv(self):
        """CSVエクスポートダイアログ."""
        if not self.settings.trade_logging.enabled:
            QMessageBox.warning(self, "エクスポート失敗", "取引ログが無効です。")
            return

        path, _ = QFileDialog.getSaveFileName(
            self, "CSVエクスポート先を選択", "trades.csv", "CSV files (*.csv)"
        )
        if not path:
            return

        try:
            from fxbot.trade_logger import TradeLogger

            db_path = self.settings.resolve_path(self.settings.trade_logging.db_path)
            if not db_path.exists():
                QMessageBox.warning(self, "エクスポート失敗", "取引DBが存在しません。")
                return

            tl = TradeLogger(db_path)
            tl.export_csv(path)
            tl.close()
            QMessageBox.information(self, "エクスポート完了", f"CSVを保存しました:\n{path}")
        except Exception as e:
            log.error(f"CSVエクスポートエラー: {e}")
            QMessageBox.critical(self, "エクスポートエラー", str(e))
