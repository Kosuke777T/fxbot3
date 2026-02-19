"""バックテストタブ — BT実行, エクイティカーブ, 指標."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGroupBox,
    QPushButton, QLabel, QComboBox, QTableWidget,
    QTableWidgetItem, QHeaderView, QSplitter,
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor

from fxbot.config import Settings
from fxbot.gui.widgets.chart_widget import ChartWidget
from fxbot.gui.workers import BacktestWorker
from fxbot.logger import get_logger

log = get_logger(__name__)


class BacktestTab(QWidget):
    """バックテストタブ."""

    def __init__(self, settings: Settings, parent=None):
        super().__init__(parent)
        self.settings = settings
        self.worker = None
        self.multi_tf_data = None
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)

        # コントロール
        ctrl_layout = QHBoxLayout()
        self.symbol_combo = QComboBox()
        ctrl_layout.addWidget(QLabel("シンボル:"))
        ctrl_layout.addWidget(self.symbol_combo)

        self.run_btn = QPushButton("WFO実行")
        self.run_btn.clicked.connect(self._run_backtest)
        ctrl_layout.addWidget(self.run_btn)

        self.status_label = QLabel("待機中")
        ctrl_layout.addWidget(self.status_label)
        ctrl_layout.addStretch()

        layout.addLayout(ctrl_layout)

        # チャート + メトリクス
        splitter = QSplitter(Qt.Orientation.Vertical)

        # エクイティカーブ
        self.equity_chart = ChartWidget(figsize=(10, 4))
        splitter.addWidget(self.equity_chart)

        # ドローダウン
        self.dd_chart = ChartWidget(figsize=(10, 3))
        splitter.addWidget(self.dd_chart)

        layout.addWidget(splitter)

        # メトリクス表
        metrics_group = QGroupBox("パフォーマンス指標")
        metrics_layout = QVBoxLayout()
        self.metrics_table = QTableWidget()
        self.metrics_table.setColumnCount(2)
        self.metrics_table.setHorizontalHeaderLabels(["指標", "値"])
        self.metrics_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch
        )
        metrics_layout.addWidget(self.metrics_table)
        metrics_group.setLayout(metrics_layout)
        layout.addWidget(metrics_group)

        # トレード一覧
        trades_group = QGroupBox("トレード一覧")
        trades_layout = QVBoxLayout()
        self.trades_table = QTableWidget()
        self.trades_table.setColumnCount(7)
        self.trades_table.setHorizontalHeaderLabels(
            ["時刻", "売買", "エントリー", "決済", "ロット", "損益", "決済理由"]
        )
        self.trades_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch
        )
        trades_layout.addWidget(self.trades_table)
        trades_group.setLayout(trades_layout)
        layout.addWidget(trades_group)

    def set_symbols(self, symbols: list[str]):
        self.symbol_combo.clear()
        self.symbol_combo.addItems(symbols)

    def set_multi_tf_data(self, data: dict):
        self.multi_tf_data = data

    def _run_backtest(self):
        if self.multi_tf_data is None:
            self.status_label.setText("先にデータを取得してください")
            return

        self.run_btn.setEnabled(False)
        self.status_label.setText("WFO実行中...")

        self.worker = BacktestWorker(self.multi_tf_data, self.settings)
        self.worker.signals.progress.connect(self._on_progress)
        self.worker.signals.finished.connect(self._on_finished)
        self.worker.signals.error.connect(self._on_error)
        self.worker.start()

    def _on_progress(self, msg: str):
        self.status_label.setText(msg)

    def _on_finished(self, result):
        self.run_btn.setEnabled(True)

        if result is None:
            self.status_label.setText("結果なし")
            return

        # 0フォールド時のフィードバック
        if len(result.folds) == 0:
            self.status_label.setText(
                "0フォールド — データ不足の可能性があります。"
                "より多くのデータを取得してください。"
            )
        else:
            self.status_label.setText(
                f"完了: {len(result.folds)}フォールド, "
                f"{len(result.combined_trades)}トレード"
            )

        # エクイティカーブ
        initial_balance = self.settings.backtest.initial_balance
        if not result.combined_equity.empty:
            self.equity_chart.plot_equity(result.combined_equity, initial_balance)
            self.dd_chart.plot_drawdown(result.combined_equity)

        # メトリクス表示
        metrics = result.overall_metrics
        metric_labels = {
            "total_return": ("トータルリターン", lambda v: f"{v*100:.2f}%"),
            "total_pnl": ("トータル損益", lambda v: f"¥{v:,.0f}"),
            "sharpe_ratio": ("シャープレシオ", lambda v: f"{v:.3f}"),
            "sortino_ratio": ("ソルティノレシオ", lambda v: f"{v:.3f}"),
            "max_drawdown_pct": ("最大DD", lambda v: f"{v*100:.2f}%"),
            "num_trades": ("トレード数", lambda v: f"{v}"),
            "win_rate": ("勝率", lambda v: f"{v*100:.1f}%"),
            "profit_factor": ("プロフィットファクター", lambda v: f"{v:.2f}"),
            "avg_pnl": ("平均損益", lambda v: f"¥{v:,.0f}"),
        }

        self.metrics_table.setRowCount(len(metrics))
        for i, (key, value) in enumerate(metrics.items()):
            label, fmt = metric_labels.get(key, (key, lambda v: f"{v}"))
            self.metrics_table.setItem(i, 0, QTableWidgetItem(label))
            self.metrics_table.setItem(i, 1, QTableWidgetItem(fmt(value)))

        # トレード一覧
        self._populate_trades_table(result.combined_trades)

    def _populate_trades_table(self, trades_df):
        """トレード一覧テーブルを表示."""
        if trades_df.empty or "entry_time" not in trades_df.columns:
            self.trades_table.setRowCount(0)
            return

        self.trades_table.setRowCount(len(trades_df))
        for i, (_, row) in enumerate(trades_df.iterrows()):
            self.trades_table.setItem(i, 0, QTableWidgetItem(
                str(row.get("entry_time", ""))
            ))
            self.trades_table.setItem(i, 1, QTableWidgetItem(
                str(row.get("side", ""))
            ))
            self.trades_table.setItem(i, 2, QTableWidgetItem(
                f"{row.get('entry_price', 0):.5f}"
            ))
            self.trades_table.setItem(i, 3, QTableWidgetItem(
                f"{row.get('exit_price', 0):.5f}"
            ))
            self.trades_table.setItem(i, 4, QTableWidgetItem(
                f"{row.get('lot', 0):.2f}"
            ))

            # 損益（色分け）
            pnl = row.get("pnl", 0)
            pnl_item = QTableWidgetItem(f"¥{pnl:,.0f}")
            if pnl >= 0:
                pnl_item.setForeground(QColor("#4CAF50"))
            else:
                pnl_item.setForeground(QColor("#F44336"))
            self.trades_table.setItem(i, 5, pnl_item)

            self.trades_table.setItem(i, 6, QTableWidgetItem(
                str(row.get("exit_reason", ""))
            ))

    def _on_error(self, msg: str):
        self.run_btn.setEnabled(True)
        self.status_label.setText("エラー")
        log.error(msg)
