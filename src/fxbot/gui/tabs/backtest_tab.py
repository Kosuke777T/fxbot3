"""バックテストタブ — WFO単体 / 比較BT + プロファイル選択."""

from __future__ import annotations

import copy

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
        self._profiles_cache: list[dict] = []
        self._init_ui()
        self.refresh_profiles()

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

        self.profile_combo = QComboBox()
        self.profile_combo.setToolTip("WFO/比較バックテストで使用する設定プロファイル")
        ctrl.addWidget(QLabel("プロファイル:"))
        ctrl.addWidget(self.profile_combo)

        self.refresh_profiles_btn = QPushButton("更新")
        self.refresh_profiles_btn.clicked.connect(self.refresh_profiles)
        ctrl.addWidget(self.refresh_profiles_btn)

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

        self.wfo_detail_tabs = QTabWidget()
        self.wfo_detail_tabs.addTab(self._build_wfo_chart_page(), "グラフ")
        self.wfo_detail_tabs.addTab(self._build_wfo_metrics_page(), "パフォーマンス指標")
        self.wfo_detail_tabs.addTab(self._build_wfo_trades_page(), "トレード一覧")
        layout.addWidget(self.wfo_detail_tabs)

        return w

    def _build_wfo_chart_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)

        hint = QLabel("グラフをダブルクリックすると別窓で拡大表示します。")
        hint.setStyleSheet("color: gray;")
        layout.addWidget(hint)

        splitter = QSplitter(Qt.Orientation.Vertical)
        self.equity_chart = ChartWidget(figsize=(10, 4))
        self.dd_chart = ChartWidget(figsize=(10, 3))
        splitter.addWidget(self.equity_chart)
        splitter.addWidget(self.dd_chart)
        splitter.setSizes([420, 280])
        layout.addWidget(splitter)
        return page

    def _build_wfo_metrics_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)

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
        return page

    def _build_wfo_trades_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)

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
        return page

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

    def refresh_profiles(self) -> None:
        """実行に使える設定プロファイル一覧を読み込む."""
        current_snapshot_id = self.settings.active_snapshot_id
        current_text = self.profile_combo.currentText() if hasattr(self, "profile_combo") else ""
        self.profile_combo.clear()
        self.profile_combo.addItem("現在の設定", None)
        self._profiles_cache = []

        try:
            from fxbot.config import _PROJECT_ROOT
            from fxbot.profile_manager import ProfileManager

            db_path = _PROJECT_ROOT / self.settings.trade_logging.db_path
            pm = ProfileManager(db_path)
            profiles = pm.load_profiles(include_archived=False)
            pm.close()
        except Exception as e:
            log.warning(f"バックテスト用プロファイル一覧取得失敗: {e}")
            return

        self._profiles_cache = profiles
        selected_index = 0

        for idx, profile in enumerate(profiles, start=1):
            version_no = profile.get("version_no")
            version_suffix = f" v{version_no}" if version_no else ""
            label = f"{profile.get('name', '(無名)')}{version_suffix}"
            self.profile_combo.addItem(label, idx - 1)

            if profile.get("snapshot_id") == current_snapshot_id:
                selected_index = idx
            elif label == current_text and selected_index == 0:
                selected_index = idx

        self.profile_combo.setCurrentIndex(selected_index)

    def _build_run_settings(self) -> tuple[Settings, str]:
        """選択されたプロファイルを一時適用した実行用 settings を返す."""
        run_settings = copy.deepcopy(self.settings)
        profile_idx = self.profile_combo.currentData()
        profile_label = self.profile_combo.currentText() or "現在の設定"

        if profile_idx is None:
            return run_settings, profile_label

        try:
            profile = self._profiles_cache[int(profile_idx)]
            snapshot_id = profile.get("snapshot_id")
            if snapshot_id is None:
                return run_settings, profile_label

            from fxbot.config import _PROJECT_ROOT
            from fxbot.profile_manager import ProfileManager

            db_path = _PROJECT_ROOT / self.settings.trade_logging.db_path
            pm = ProfileManager(db_path)
            pm.apply_profile(snapshot_id, run_settings)
            pm.close()

            run_settings.active_profile_id = profile.get("profile_id", "")
            run_settings.active_snapshot_id = snapshot_id
            return run_settings, profile_label
        except Exception as e:
            log.warning(f"バックテスト実行用プロファイル適用失敗: {e}")
            return run_settings, "現在の設定"

    # ------------------------------------------------------------------ #
    #  WFO                                                                 #
    # ------------------------------------------------------------------ #
    def _run_backtest(self):
        symbol = self.symbol_combo.currentText()
        if not symbol:
            self.status_label.setText("シンボルを選択してください")
            return

        self.run_btn.setEnabled(False)
        run_settings, profile_label = self._build_run_settings()
        self.status_label.setText(f"データ取得+WFO実行中... ({symbol} / {profile_label})")

        self.worker = BacktestWorker(symbol, run_settings)
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
            "worst_fold_drawdown_pct": ("最悪フォールドDD",  lambda v: f"{v*100:.2f}%"),
            "avg_fold_drawdown_pct": ("平均フォールドDD",   lambda v: f"{v*100:.2f}%"),
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
        run_settings, profile_label = self._build_run_settings()
        self.status_label.setText(f"[比較BT] {symbol} データ取得中... ({profile_label})")

        self.comparison_worker = ComparisonWorker(symbol, run_settings)
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
