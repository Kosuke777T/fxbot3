"""バックテストタブ — WFO単体 / 比較バックテスト をサブタブで分離."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGroupBox,
    QPushButton, QLabel, QComboBox, QTableWidget,
    QTableWidgetItem, QHeaderView, QSplitter, QTabWidget,
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor

from fxbot.config import Settings
from fxbot.gui.widgets.chart_widget import ChartWidget
from fxbot.gui.workers import BacktestWorker, ComparisonWorker, ComparisonResult
from fxbot.logger import get_logger

log = get_logger(__name__)


class BacktestTab(QWidget):
    """バックテストタブ（WFO / 比較BT をサブタブで切替）."""

    def __init__(self, settings: Settings, parent=None):
        super().__init__(parent)
        self.settings = settings
        self.worker = None
        self.comparison_worker = None
        self.multi_tf_data = None
        self._init_ui()

    # ------------------------------------------------------------------ #
    #  UI 構築                                                             #
    # ------------------------------------------------------------------ #
    def _init_ui(self):
        layout = QVBoxLayout(self)

        # ── 共通コントロール（タブの外） ──────────────────────────────
        ctrl = QHBoxLayout()
        self.symbol_combo = QComboBox()
        ctrl.addWidget(QLabel("シンボル:"))
        ctrl.addWidget(self.symbol_combo)
        self.status_label = QLabel("待機中")
        ctrl.addWidget(self.status_label)
        ctrl.addStretch()
        layout.addLayout(ctrl)

        # ── サブタブ ──────────────────────────────────────────────────
        self.sub_tabs = QTabWidget()
        self.sub_tabs.addTab(self._build_wfo_tab(), "WFO")
        self.sub_tabs.addTab(self._build_comparison_tab(), "比較バックテスト")
        layout.addWidget(self.sub_tabs)

    # ── WFO タブ ──────────────────────────────────────────────────────
    def _build_wfo_tab(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)

        # 実行ボタン
        btn_row = QHBoxLayout()
        self.run_btn = QPushButton("WFO実行")
        self.run_btn.clicked.connect(self._run_backtest)
        btn_row.addWidget(self.run_btn)
        btn_row.addStretch()
        layout.addLayout(btn_row)

        # エクイティ / ドローダウン
        splitter = QSplitter(Qt.Orientation.Vertical)
        self.equity_chart = ChartWidget(figsize=(10, 4))
        self.dd_chart = ChartWidget(figsize=(10, 3))
        splitter.addWidget(self.equity_chart)
        splitter.addWidget(self.dd_chart)
        layout.addWidget(splitter)

        # メトリクス表
        metrics_group = QGroupBox("パフォーマンス指標")
        mg_layout = QVBoxLayout()
        self.metrics_table = QTableWidget()
        self.metrics_table.setColumnCount(2)
        self.metrics_table.setHorizontalHeaderLabels(["指標", "値"])
        self.metrics_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch
        )
        mg_layout.addWidget(self.metrics_table)
        metrics_group.setLayout(mg_layout)
        layout.addWidget(metrics_group)

        # トレード一覧
        trades_group = QGroupBox("トレード一覧")
        tg_layout = QVBoxLayout()
        self.trades_table = QTableWidget()
        self.trades_table.setColumnCount(7)
        self.trades_table.setHorizontalHeaderLabels(
            ["時刻", "売買", "エントリー", "決済", "ロット", "損益", "決済理由"]
        )
        self.trades_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch
        )
        tg_layout.addWidget(self.trades_table)
        trades_group.setLayout(tg_layout)
        layout.addWidget(trades_group)

        return w

    # ── 比較バックテスト タブ ──────────────────────────────────────────
    def _build_comparison_tab(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)

        # 実行ボタン
        btn_row = QHBoxLayout()
        self.compare_btn = QPushButton("比較バックテスト実行")
        self.compare_btn.clicked.connect(self._run_comparison)
        btn_row.addWidget(self.compare_btn)
        btn_row.addStretch()
        layout.addLayout(btn_row)

        # マルチエクイティチャート
        self.comparison_chart = ChartWidget(figsize=(10, 5))
        layout.addWidget(self.comparison_chart)

        # 比較メトリクス表
        self.comparison_table = QTableWidget()
        self.comparison_table.setColumnCount(5)
        self.comparison_table.setHorizontalHeaderLabels(
            ["指標", "回帰", "分類0.55", "分類0.60", "分類0.65"]
        )
        self.comparison_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch
        )
        layout.addWidget(self.comparison_table)

        return w

    # ------------------------------------------------------------------ #
    #  公開 API                                                            #
    # ------------------------------------------------------------------ #
    def set_symbols(self, symbols: list[str]):
        self.symbol_combo.clear()
        self.symbol_combo.addItems(symbols)

    def set_multi_tf_data(self, data: dict):
        self.multi_tf_data = data

    # ------------------------------------------------------------------ #
    #  WFO                                                                 #
    # ------------------------------------------------------------------ #
    def _run_backtest(self):
        symbol = self.symbol_combo.currentText()
        if not symbol:
            self.status_label.setText("シンボルを選択してください")
            return

        self.run_btn.setEnabled(False)
        self.status_label.setText(f"データ取得+WFO実行中... ({symbol})")

        self.worker = BacktestWorker(symbol, self.settings)
        self.worker.signals.progress.connect(self._on_progress)
        self.worker.signals.finished.connect(self._on_wfo_finished)
        self.worker.signals.error.connect(self._on_wfo_error)
        self.worker.start()

    def _on_progress(self, msg: str):
        self.status_label.setText(msg)

    def _on_wfo_finished(self, result):
        self.run_btn.setEnabled(True)

        if result is None:
            self.status_label.setText("結果なし")
            return

        if len(result.folds) == 0:
            self.status_label.setText(
                "0フォールド — データ不足の可能性があります。"
                "より多くのデータを取得してください。"
            )
        else:
            self.status_label.setText(
                f"WFO完了: {len(result.folds)}フォールド, "
                f"{len(result.combined_trades)}トレード"
            )

        initial_balance = self.settings.backtest.initial_balance
        if not result.combined_equity.empty:
            self.equity_chart.plot_equity(result.combined_equity, initial_balance)
            self.dd_chart.plot_drawdown(result.combined_equity)

        metrics = result.overall_metrics
        metric_labels = {
            "total_return":     ("トータルリターン",       lambda v: f"{v*100:.2f}%"),
            "total_pnl":        ("トータル損益",           lambda v: f"¥{v:,.0f}"),
            "sharpe_ratio":     ("シャープレシオ",         lambda v: f"{v:.3f}"),
            "sortino_ratio":    ("ソルティノレシオ",       lambda v: f"{v:.3f}"),
            "max_drawdown_pct": ("最大DD",                 lambda v: f"{v*100:.2f}%"),
            "num_trades":       ("トレード数",             lambda v: f"{v}"),
            "win_rate":         ("勝率",                   lambda v: f"{v*100:.1f}%"),
            "profit_factor":    ("プロフィットファクター", lambda v: f"{v:.2f}"),
            "avg_pnl":          ("平均損益",               lambda v: f"¥{v:,.0f}"),
        }
        self.metrics_table.setRowCount(len(metrics))
        for i, (key, value) in enumerate(metrics.items()):
            label, fmt = metric_labels.get(key, (key, lambda v: f"{v}"))
            self.metrics_table.setItem(i, 0, QTableWidgetItem(label))
            self.metrics_table.setItem(i, 1, QTableWidgetItem(fmt(value)))

        self._populate_trades_table(result.combined_trades)

    def _on_wfo_error(self, msg: str):
        self.run_btn.setEnabled(True)
        self.status_label.setText("WFO エラー")
        log.error(msg)

    def _populate_trades_table(self, trades_df):
        if trades_df.empty or "entry_time" not in trades_df.columns:
            self.trades_table.setRowCount(0)
            return

        self.trades_table.setRowCount(len(trades_df))
        for i, (_, row) in enumerate(trades_df.iterrows()):
            self.trades_table.setItem(i, 0, QTableWidgetItem(str(row.get("entry_time", ""))))
            self.trades_table.setItem(i, 1, QTableWidgetItem(str(row.get("side", ""))))
            self.trades_table.setItem(i, 2, QTableWidgetItem(f"{row.get('entry_price', 0):.5f}"))
            self.trades_table.setItem(i, 3, QTableWidgetItem(f"{row.get('exit_price', 0):.5f}"))
            self.trades_table.setItem(i, 4, QTableWidgetItem(f"{row.get('lot', 0):.2f}"))

            pnl = row.get("pnl", 0)
            pnl_item = QTableWidgetItem(f"¥{pnl:,.0f}")
            pnl_item.setForeground(QColor("#4CAF50") if pnl >= 0 else QColor("#F44336"))
            self.trades_table.setItem(i, 5, pnl_item)

            self.trades_table.setItem(i, 6, QTableWidgetItem(str(row.get("exit_reason", ""))))

    # ------------------------------------------------------------------ #
    #  比較バックテスト                                                     #
    # ------------------------------------------------------------------ #
    def _run_comparison(self):
        symbol = self.symbol_combo.currentText()
        if not symbol:
            self.status_label.setText("シンボルを選択してください")
            return

        self.compare_btn.setEnabled(False)
        self.status_label.setText(f"[比較BT] {symbol} データ取得中...")

        self.comparison_worker = ComparisonWorker(symbol, self.settings)
        self.comparison_worker.signals.progress.connect(self._on_progress)
        self.comparison_worker.signals.finished.connect(self._on_comparison_finished)
        self.comparison_worker.signals.error.connect(self._on_comparison_error)
        self.comparison_worker.start()

    def _on_comparison_finished(self, result: ComparisonResult):
        self.compare_btn.setEnabled(True)
        self.status_label.setText("[比較BT] 完了")

        initial_balance = self.settings.backtest.initial_balance
        equity_curves = {
            "回帰":      result.regression_equity,
            "分類 0.55": result.clf_equity_055,
            "分類 0.60": result.clf_equity_060,
            "分類 0.65": result.clf_equity_065,
        }
        self.comparison_chart.plot_multi_equity(equity_curves, initial_balance)
        self._populate_comparison_metrics(
            result.regression_metrics,
            result.clf_metrics_055,
            result.clf_metrics_060,
            result.clf_metrics_065,
        )

    def _populate_comparison_metrics(self, reg, m055, m060, m065):
        rows = [
            ("トータルリターン",       "total_return",     lambda v: f"{v*100:.2f}%"),
            ("シャープレシオ",         "sharpe_ratio",     lambda v: f"{v:.3f}"),
            ("最大DD",                 "max_drawdown_pct", lambda v: f"{v*100:.2f}%"),
            ("トレード数",             "num_trades",       lambda v: f"{int(v)}"),
            ("勝率",                   "win_rate",         lambda v: f"{v*100:.1f}%"),
            ("プロフィットファクター", "profit_factor",    lambda v: f"{v:.2f}"),
        ]
        self.comparison_table.setRowCount(len(rows))
        for i, (label, key, fmt) in enumerate(rows):
            self.comparison_table.setItem(i, 0, QTableWidgetItem(label))
            for col, metrics in enumerate([reg, m055, m060, m065], start=1):
                val = metrics.get(key)
                self.comparison_table.setItem(i, col, QTableWidgetItem(
                    fmt(val) if val is not None else "—"
                ))

    def _on_comparison_error(self, msg: str):
        self.compare_btn.setEnabled(True)
        self.status_label.setText("比較BT エラー")
        log.error(msg)
