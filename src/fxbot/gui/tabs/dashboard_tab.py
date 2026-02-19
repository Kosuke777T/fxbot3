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

    def refresh_positions(self):
        """ポジション情報を更新."""
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
