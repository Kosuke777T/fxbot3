"""ダッシュボードタブ — ポジション, P&L, 予測表示."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGroupBox,
    QLabel, QTableWidget, QTableWidgetItem, QPushButton,
    QHeaderView,
)
from PySide6.QtCore import QTimer
from PySide6.QtGui import QColor

from fxbot.config import Settings
from fxbot.logger import get_logger

log = get_logger(__name__)


class DashboardTab(QWidget):
    """ダッシュボードタブ."""

    def __init__(self, settings: Settings, parent=None):
        super().__init__(parent)
        self.settings = settings
        self._init_ui()

        # 自動更新タイマー（5秒間隔）
        self.update_timer = QTimer(self)
        self.update_timer.timeout.connect(self.refresh_positions)
        self.update_timer.start(5000)

    def _init_ui(self):
        layout = QVBoxLayout(self)

        # === 口座情報 ===
        info_group = QGroupBox("口座情報")
        info_layout = QHBoxLayout()

        self.balance_label = QLabel("残高: ---")
        self.balance_label.setStyleSheet("font-size: 16px; font-weight: bold;")
        info_layout.addWidget(self.balance_label)

        self.equity_label = QLabel("有効証拠金: ---")
        self.equity_label.setStyleSheet("font-size: 16px; font-weight: bold;")
        info_layout.addWidget(self.equity_label)

        self.margin_label = QLabel("証拠金維持率: ---")
        info_layout.addWidget(self.margin_label)

        self.pnl_label = QLabel("損益: ---")
        self.pnl_label.setStyleSheet("font-size: 16px;")
        info_layout.addWidget(self.pnl_label)

        info_group.setLayout(info_layout)
        layout.addWidget(info_group)

        # === ポジション一覧 ===
        pos_group = QGroupBox("オープンポジション")
        pos_layout = QVBoxLayout()

        self.position_table = QTableWidget()
        self.position_table.setColumnCount(8)
        self.position_table.setHorizontalHeaderLabels([
            "チケット", "シンボル", "方向", "ロット",
            "建値", "現在値", "SL", "損益",
        ])
        self.position_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch
        )
        pos_layout.addWidget(self.position_table)

        # 操作ボタン
        btn_layout = QHBoxLayout()
        self.refresh_btn = QPushButton("更新")
        self.refresh_btn.clicked.connect(self.refresh_positions)
        btn_layout.addWidget(self.refresh_btn)

        self.close_all_btn = QPushButton("全決済")
        self.close_all_btn.setStyleSheet("background-color: #F44336; color: white;")
        self.close_all_btn.clicked.connect(self._on_close_all)
        btn_layout.addWidget(self.close_all_btn)

        pos_layout.addLayout(btn_layout)
        pos_group.setLayout(pos_layout)
        layout.addWidget(pos_group)

        # === 最新予測 ===
        pred_group = QGroupBox("最新予測")
        pred_layout = QVBoxLayout()

        self.prediction_table = QTableWidget()
        self.prediction_table.setColumnCount(3)
        self.prediction_table.setHorizontalHeaderLabels(["シンボル", "予測値", "方向"])
        self.prediction_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch
        )
        pred_layout.addWidget(self.prediction_table)

        pred_group.setLayout(pred_layout)
        layout.addWidget(pred_group)

        # === 取引パフォーマンス（TradeLogger連携）===
        perf_group = QGroupBox("取引パフォーマンス（直近20件）")
        perf_layout = QHBoxLayout()

        self.win_rate_label = QLabel("勝率: ---")
        self.win_rate_label.setStyleSheet("font-size: 14px; font-weight: bold;")
        perf_layout.addWidget(self.win_rate_label)

        self.avg_pnl_label = QLabel("平均損益: ---")
        perf_layout.addWidget(self.avg_pnl_label)

        self.sharpe_label = QLabel("Sharpe: ---")
        perf_layout.addWidget(self.sharpe_label)

        self.model_health_label = QLabel("モデル: ---")
        self.model_health_label.setStyleSheet("font-size: 14px;")
        perf_layout.addWidget(self.model_health_label)

        perf_group.setLayout(perf_layout)
        layout.addWidget(perf_group)

        # === 週末自動再学習結果 ===
        retrain_group = QGroupBox("週末自動再学習（最終実行結果）")
        retrain_layout = QHBoxLayout()

        self.retrain_date_label = QLabel("最終実行: ---")
        retrain_layout.addWidget(self.retrain_date_label)

        self.retrain_wfo_label = QLabel("WFO: ---")
        retrain_layout.addWidget(self.retrain_wfo_label)

        self.retrain_status_label = QLabel("結果: ---")
        retrain_layout.addWidget(self.retrain_status_label)

        retrain_group.setLayout(retrain_layout)
        layout.addWidget(retrain_group)

        # === 取引履歴 ===
        history_group = QGroupBox("取引履歴（直近10件）")
        history_layout = QVBoxLayout()

        self.trade_history_table = QTableWidget()
        self.trade_history_table.setColumnCount(7)
        self.trade_history_table.setHorizontalHeaderLabels([
            "時刻", "シンボル", "方向", "ロット", "建値", "損益", "決済理由",
        ])
        self.trade_history_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch
        )
        self.trade_history_table.setMaximumHeight(200)
        history_layout.addWidget(self.trade_history_table)

        history_group.setLayout(history_layout)
        layout.addWidget(history_group)

    def refresh_positions(self):
        """ポジション情報と取引ログを更新."""
        self._refresh_trade_log()
        self.refresh_auto_retrain_result()
        try:
            from fxbot.risk.portfolio import get_open_positions
            from fxbot.mt5.connection import get_account_info

            # 口座情報
            info = get_account_info()
            if info:
                self.balance_label.setText(f"残高: {info['balance']:,.0f} {info['currency']}")
                self.equity_label.setText(f"有効証拠金: {info['equity']:,.0f}")
                margin_ratio = (info['equity'] / info['margin'] * 100) if info['margin'] > 0 else 0
                self.margin_label.setText(f"証拠金維持率: {margin_ratio:.1f}%")
                pnl = info['equity'] - info['balance']
                color = "#4CAF50" if pnl >= 0 else "#F44336"
                self.pnl_label.setText(f"損益: {pnl:+,.0f}")
                self.pnl_label.setStyleSheet(f"font-size: 16px; color: {color};")

            # ポジション
            positions = get_open_positions()
            self.position_table.setRowCount(len(positions))
            for i, pos in enumerate(positions):
                self.position_table.setItem(i, 0, QTableWidgetItem(str(pos["ticket"])))
                self.position_table.setItem(i, 1, QTableWidgetItem(pos["symbol"]))
                self.position_table.setItem(i, 2, QTableWidgetItem(pos["type"].upper()))
                self.position_table.setItem(i, 3, QTableWidgetItem(f"{pos['volume']:.2f}"))
                self.position_table.setItem(i, 4, QTableWidgetItem(f"{pos['price_open']:.5f}"))
                self.position_table.setItem(i, 5, QTableWidgetItem(f"{pos['price_current']:.5f}"))
                self.position_table.setItem(i, 6, QTableWidgetItem(f"{pos['sl']:.5f}"))

                pnl_item = QTableWidgetItem(f"{pos['profit']:+,.0f}")
                pnl_item.setForeground(
                    QColor("#4CAF50") if pos["profit"] >= 0 else QColor("#F44336")
                )
                self.position_table.setItem(i, 7, pnl_item)

        except Exception as e:
            log.debug(f"ポジション更新スキップ: {e}")

    def _refresh_trade_log(self):
        """取引ログからパフォーマンスを更新."""
        if not self.settings.trade_logging.enabled:
            return
        try:
            from fxbot.trade_logger import TradeLogger
            from fxbot.model.monitor import ModelMonitor
            db_path = self.settings.resolve_path(self.settings.trade_logging.db_path)
            if not db_path.exists():
                return
            tl = TradeLogger(db_path)
            rt_cfg = self.settings.retraining
            monitor = ModelMonitor(
                tl,
                window=rt_cfg.monitor_window,
                min_win_rate=rt_cfg.min_win_rate,
                min_sharpe=rt_cfg.min_sharpe,
            )
            result = monitor.check()
            m = result["metrics"]
            tl.close()

            # パフォーマンスラベル更新
            count = m.get("count", 0)
            if count > 0:
                wr = m.get("win_rate", 0)
                wr_color = "#4CAF50" if wr >= 0.5 else "#F44336"
                self.win_rate_label.setText(f"勝率: {wr:.1%}")
                self.win_rate_label.setStyleSheet(
                    f"font-size: 14px; font-weight: bold; color: {wr_color};"
                )
                avg = m.get("avg_pnl", 0)
                self.avg_pnl_label.setText(f"平均損益: {avg:+.0f}")
                sh = m.get("sharpe", 0)
                self.sharpe_label.setText(f"Sharpe: {sh:.2f}")

                # モデル健全性
                if result["healthy"]:
                    self.model_health_label.setText("モデル: 正常")
                    self.model_health_label.setStyleSheet(
                        "font-size: 14px; color: #4CAF50;"
                    )
                else:
                    warns = ", ".join(result["warnings"])
                    self.model_health_label.setText(f"モデル: 要再学習 ({warns})")
                    self.model_health_label.setStyleSheet(
                        "font-size: 14px; color: #F44336;"
                    )

            # 取引履歴テーブル更新
            tl2 = TradeLogger(db_path)
            trades = tl2.get_recent_trades(10)
            tl2.close()
            self.trade_history_table.setRowCount(len(trades))
            for i, t in enumerate(trades):
                ts = (t.get("exit_time") or t.get("timestamp", ""))[:19]
                self.trade_history_table.setItem(i, 0, QTableWidgetItem(ts))
                self.trade_history_table.setItem(i, 1, QTableWidgetItem(t.get("symbol", "")))
                self.trade_history_table.setItem(i, 2, QTableWidgetItem(t.get("direction", "").upper()))
                self.trade_history_table.setItem(i, 3, QTableWidgetItem(f"{t.get('lot', 0):.2f}"))
                self.trade_history_table.setItem(i, 4, QTableWidgetItem(f"{t.get('entry_price', 0):.5f}"))

                pnl = t.get("pnl")
                pnl_str = f"{pnl:+.0f}" if pnl is not None else "---"
                pnl_item = QTableWidgetItem(pnl_str)
                if pnl is not None:
                    pnl_item.setForeground(
                        QColor("#4CAF50") if pnl >= 0 else QColor("#F44336")
                    )
                self.trade_history_table.setItem(i, 5, pnl_item)
                self.trade_history_table.setItem(
                    i, 6, QTableWidgetItem(t.get("exit_reason") or "---")
                )

        except Exception as e:
            log.debug(f"取引ログ更新スキップ: {e}")

    def update_predictions(self, predictions: dict[str, float]):
        """予測値を更新."""
        self.prediction_table.setRowCount(len(predictions))
        for i, (symbol, pred) in enumerate(predictions.items()):
            self.prediction_table.setItem(i, 0, QTableWidgetItem(symbol))
            self.prediction_table.setItem(i, 1, QTableWidgetItem(f"{pred:.6f}"))

            direction = "BUY" if pred > 0 else "SELL" if pred < 0 else "---"
            dir_item = QTableWidgetItem(direction)
            dir_item.setForeground(
                QColor("#4CAF50") if pred > 0 else QColor("#F44336") if pred < 0 else QColor("gray")
            )
            self.prediction_table.setItem(i, 2, dir_item)

    def refresh_auto_retrain_result(self):
        """logsディレクトリの最新 auto_retrain_*.json を読み込んで表示."""
        import json
        try:
            log_dir = self.settings.resolve_path("logs")
            if not log_dir.exists():
                return
            files = sorted(log_dir.glob("auto_retrain_*.json"))
            if not files:
                return
            latest = files[-1]
            with open(latest, "r", encoding="utf-8") as f:
                data = json.load(f)

            ts = data.get("timestamp", "")[:19]
            self.retrain_date_label.setText(f"最終実行: {ts}")

            wr = data.get("wfo_win_rate", 0.0)
            sh = data.get("wfo_sharpe", 0.0)
            self.retrain_wfo_label.setText(f"WFO: 勝率{wr:.1%} / Sharpe{sh:.2f}")

            trained = data.get("trained", False)
            reason = data.get("reason", "")
            if trained:
                self.retrain_status_label.setText(f"結果: 学習済 ({reason})")
                self.retrain_status_label.setStyleSheet("color: #4CAF50; font-weight: bold;")
            else:
                self.retrain_status_label.setText(f"結果: スキップ ({reason})")
                self.retrain_status_label.setStyleSheet("color: #FF9800;")
        except Exception as e:
            log.debug(f"自動再学習結果更新スキップ: {e}")

    def _on_close_all(self):
        from PySide6.QtWidgets import QMessageBox
        reply = QMessageBox.warning(
            self, "全決済確認",
            "全てのポジションを決済します。よろしいですか？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            from fxbot.mt5.execution import close_all_positions
            closed = close_all_positions()
            log.info(f"全決済: {closed}ポジション")
            self.refresh_positions()
