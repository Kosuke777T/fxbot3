"""メインウィンドウ — QMainWindow + 5タブ + ライブ取引制御."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QMainWindow, QTabWidget, QStatusBar, QLabel, QVBoxLayout, QHBoxLayout,
    QWidget, QSplitter, QPushButton, QMessageBox,
)
from PySide6.QtCore import Qt, QTimer
from datetime import datetime, date

from fxbot.config import Settings
from fxbot.gui.tabs.settings_tab import SettingsTab
from fxbot.gui.tabs.dashboard_tab import DashboardTab
from fxbot.gui.tabs.backtest_tab import BacktestTab
from fxbot.gui.tabs.shap_tab import ShapTab
from fxbot.gui.tabs.model_tab import ModelTab
from fxbot.gui.widgets.log_widget import LogWidget
from fxbot.gui.workers import TradingWorker, WeekendRetrainWorker
from fxbot.logger import get_logger

log = get_logger(__name__)


class MainWindow(QMainWindow):
    """FXBot3 メインウィンドウ."""

    def __init__(self, settings: Settings):
        super().__init__()
        self.settings = settings
        self.trading_worker: TradingWorker | None = None
        self.weekend_retrain_worker: WeekendRetrainWorker | None = None
        self.retrain_timer: QTimer | None = None
        self._last_weekend_retrain_date: date | None = None
        self._init_ui()
        self._connect_signals()
        self._update_status_bar()
        self._load_symbols()
        self._setup_retraining_scheduler()

    def _init_ui(self):
        self.setWindowTitle("FXBot3 — FX自動売買ボット")
        self.setMinimumSize(1200, 800)

        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)

        # ライブ取引コントロールバー
        trade_bar = QHBoxLayout()

        self.start_trading_btn = QPushButton("取引開始")
        self.start_trading_btn.setStyleSheet(
            "QPushButton { background-color: #4CAF50; color: white; "
            "padding: 8px 20px; font-size: 14px; font-weight: bold; }"
        )
        self.start_trading_btn.clicked.connect(self._start_trading)
        trade_bar.addWidget(self.start_trading_btn)

        self.stop_trading_btn = QPushButton("取引停止")
        self.stop_trading_btn.setStyleSheet(
            "QPushButton { background-color: #F44336; color: white; "
            "padding: 8px 20px; font-size: 14px; font-weight: bold; }"
        )
        self.stop_trading_btn.setEnabled(False)
        self.stop_trading_btn.clicked.connect(self._stop_trading)
        trade_bar.addWidget(self.stop_trading_btn)

        self.trading_status_label = QLabel("停止中")
        self.trading_status_label.setStyleSheet("font-size: 14px; padding: 0 10px;")
        trade_bar.addWidget(self.trading_status_label)

        trade_bar.addStretch()
        layout.addLayout(trade_bar)

        # タブ + ログの分割
        splitter = QSplitter(Qt.Orientation.Vertical)

        self.tabs = QTabWidget()

        self.dashboard_tab = DashboardTab(self.settings)
        self.tabs.addTab(self.dashboard_tab, "ダッシュボード")

        self.model_tab = ModelTab(self.settings)
        self.tabs.addTab(self.model_tab, "モデル")

        self.backtest_tab = BacktestTab(self.settings)
        self.tabs.addTab(self.backtest_tab, "バックテスト")

        self.shap_tab = ShapTab(self.settings)
        self.tabs.addTab(self.shap_tab, "SHAP")

        self.settings_tab = SettingsTab(self.settings)
        self.tabs.addTab(self.settings_tab, "設定")

        splitter.addWidget(self.tabs)

        self.log_widget = LogWidget()
        splitter.addWidget(self.log_widget)

        splitter.setSizes([600, 200])
        layout.addWidget(splitter)

        # ステータスバー
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)

        self.account_status = QLabel()
        self.status_bar.addPermanentWidget(self.account_status)

        self.autotrade_status = QLabel()
        self.status_bar.addPermanentWidget(self.autotrade_status)

        self.connection_status = QLabel("未接続")
        self.status_bar.addPermanentWidget(self.connection_status)

    def _connect_signals(self):
        self.settings_tab.account_changed.connect(self._on_account_changed)
        self.model_tab.on_train_complete = self._on_train_complete

    def _load_symbols(self):
        """保存済みシンボルをタブに設定。未保存の場合はMT5から自動検出."""
        try:
            from fxbot.mt5.symbols import get_symbol_names, detect_symbols, save_symbols

            symbols = get_symbol_names(self.settings)
            if symbols:
                self.model_tab.set_symbols(symbols)
                self.backtest_tab.set_symbols(symbols)
                return

            # symbols.json が存在しないor空 → MT5接続して自動検出
            log.info("シンボル未保存 — MT5から自動検出を開始")
            from fxbot.mt5.connection import connect

            if not connect(self.settings):
                log.warning("MT5接続失敗 — シンボル自動検出をスキップ")
                return

            self.connection_status.setText("接続中")
            self.connection_status.setStyleSheet("color: green;")
            self._check_autotrade()

            detected = detect_symbols(self.settings)
            if not detected:
                log.warning("シンボル検出結果が空です")
                return

            save_symbols(detected, self.settings)
            symbols = [s["name"] for s in detected]
            self.model_tab.set_symbols(symbols)
            self.backtest_tab.set_symbols(symbols)
            log.info(f"シンボル自動検出完了: {len(symbols)}ペア")
        except Exception:
            log.exception("シンボル読み込みエラー")

    # --- ライブ取引制御 ---

    def _start_trading(self):
        """ライブ取引を開始."""
        acc = self.settings.current_account
        if acc.type == "real":
            reply = QMessageBox.warning(
                self, "リアル口座で取引開始",
                "リアル口座で自動売買を開始します。\n実際の資金で取引が行われます。\n\n開始しますか？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if reply != QMessageBox.StandardButton.Yes:
                return

        self.trading_worker = TradingWorker(self.settings)
        self.trading_worker.signals.progress.connect(self._on_trading_progress)
        self.trading_worker.signals.error.connect(self._on_trading_error)
        self.trading_worker.signals.finished.connect(self._on_trading_stopped)
        self.trading_worker.signals.prediction.connect(self.dashboard_tab.update_predictions)
        self.trading_worker.start()

        self.start_trading_btn.setEnabled(False)
        self.stop_trading_btn.setEnabled(True)
        self.trading_status_label.setText("取引中...")
        self.trading_status_label.setStyleSheet(
            "font-size: 14px; padding: 0 10px; color: #4CAF50; font-weight: bold;"
        )
        log.info("ライブ取引開始")

    def _stop_trading(self):
        """ライブ取引を停止."""
        if self.trading_worker:
            self.trading_worker.stop()
            self.trading_status_label.setText("停止処理中...")

    def _on_trading_progress(self, msg: str):
        self.trading_status_label.setText(msg)

    def _on_trading_error(self, msg: str):
        log.error(msg)
        self.trading_status_label.setText("エラー")
        self.trading_status_label.setStyleSheet(
            "font-size: 14px; padding: 0 10px; color: #F44336;"
        )
        self.start_trading_btn.setEnabled(True)
        self.stop_trading_btn.setEnabled(False)

    def _on_trading_stopped(self, _result):
        self.start_trading_btn.setEnabled(True)
        self.stop_trading_btn.setEnabled(False)
        self.trading_status_label.setText("停止中")
        self.trading_status_label.setStyleSheet("font-size: 14px; padding: 0 10px;")
        log.info("ライブ取引停止")

    # --- 自動再学習スケジューラ ---

    def _setup_retraining_scheduler(self):
        """自動再学習タイマーを設定（1時間ごとにチェック）."""
        if not self.settings.retraining.enabled:
            return

        # 週末オプション有効時は毎時チェック、無効時はinterval_hours間隔
        if self.settings.retraining.weekend_only:
            interval_ms = 3600 * 1000  # 1時間ごとにチェック
            log.info("自動再学習スケジューラ: 週末モード（毎時チェック）")
        else:
            interval_ms = self.settings.retraining.interval_hours * 3600 * 1000
            log.info(f"自動再学習スケジューラ: {self.settings.retraining.interval_hours}時間間隔")

        self.retrain_timer = QTimer(self)
        self.retrain_timer.timeout.connect(self._auto_retrain)
        self.retrain_timer.start(interval_ms)

    def _auto_retrain(self):
        """定期自動再学習チェック・実行."""
        if not self.settings.retraining.enabled:
            return

        rt_cfg = self.settings.retraining
        now = datetime.now()

        # 週末のみオプション: 平日はスキップ
        if rt_cfg.weekend_only:
            if now.weekday() < 5:  # 0=月〜4=金
                return
            # 今週末すでに実行済みならスキップ
            if self._last_weekend_retrain_date == now.date():
                return

        # ワーカー実行中ならスキップ
        if self.weekend_retrain_worker and self.weekend_retrain_worker.isRunning():
            return

        if (rt_cfg.run_wfo_before_train
                and self.model_tab.multi_tf_data
                and self.model_tab.symbol_combo.currentText()):
            self._start_weekend_retrain()
        elif self.model_tab.multi_tf_data and self.model_tab.symbol_combo.currentText():
            log.info("自動再学習開始（WFOなし）")
            self.model_tab._start_training()

    def _start_weekend_retrain(self):
        """WeekendRetrainWorker を起動."""
        symbol = self.model_tab.symbol_combo.currentText()
        log.info(f"週末自動WFO→学習開始: {symbol}")

        self.weekend_retrain_worker = WeekendRetrainWorker(
            self.model_tab.multi_tf_data, symbol, self.settings
        )
        self.weekend_retrain_worker.signals.progress.connect(
            lambda msg: log.info(msg)
        )
        self.weekend_retrain_worker.signals.error.connect(self._on_weekend_retrain_error)
        self.weekend_retrain_worker.signals.finished.connect(self._on_weekend_retrain_finished)
        self.weekend_retrain_worker.start()

    def _on_weekend_retrain_finished(self, result: dict):
        """週末再学習完了時の処理."""
        import json
        from pathlib import Path

        now = datetime.now()
        self._last_weekend_retrain_date = now.date()

        # ログ保存
        log_dir = self.settings.resolve_path("logs")
        log_dir.mkdir(parents=True, exist_ok=True)
        log_file = log_dir / f"auto_retrain_{now.strftime('%Y%m%d')}.json"

        save_data = {
            "timestamp": now.isoformat(),
            "trained": result.get("trained", False),
            "reason": result.get("reason", ""),
            "wfo_win_rate": result.get("wfo_win_rate", 0.0),
            "wfo_sharpe": result.get("wfo_sharpe", 0.0),
            "train_metrics": result.get("train_metrics", {}),
            "model_dir": result.get("model_dir", ""),
        }
        try:
            with open(log_file, "w", encoding="utf-8") as f:
                json.dump(save_data, f, ensure_ascii=False, indent=2, default=str)
        except Exception as e:
            log.warning(f"自動再学習ログ保存失敗: {e}")

        trained = result.get("trained", False)
        reason = result.get("reason", "")
        log.info(f"週末自動再学習完了: trained={trained}, reason={reason}")

        # ダッシュボードを更新
        self.dashboard_tab.refresh_auto_retrain_result()

    def _on_weekend_retrain_error(self, msg: str):
        """週末再学習エラー."""
        log.error(msg)

    # --- 口座切替・その他 ---

    def _on_account_changed(self, account_name: str):
        """口座切替時の処理."""
        # 取引中なら停止
        if self.trading_worker and self.trading_worker.isRunning():
            self._stop_trading()
            self.trading_worker.wait(5000)

        log.info(f"口座切替: {account_name}")

        from fxbot.mt5.connection import reconnect
        if reconnect(self.settings):
            self.connection_status.setText("接続中")
            self.connection_status.setStyleSheet("color: green;")
            self._check_autotrade()
        else:
            self.connection_status.setText("接続失敗")
            self.connection_status.setStyleSheet("color: red;")
            self.autotrade_status.setText("")

        self._update_status_bar()

    def _on_train_complete(self, result):
        """学習完了時."""
        if "importance" in result:
            self.shap_tab.set_importance(result["importance"])
        if self.model_tab.multi_tf_data:
            self.backtest_tab.set_multi_tf_data(self.model_tab.multi_tf_data)

    def _check_autotrade(self):
        """MT5の自動売買状態をチェックしてステータスバーに表示."""
        try:
            import MetaTrader5 as mt5
            ti = mt5.terminal_info()
            if ti is None:
                self.autotrade_status.setText("")
                return
            if ti.trade_allowed:
                self.autotrade_status.setText("  自動売買: ON  ")
                self.autotrade_status.setStyleSheet(
                    "background-color: #4CAF50; color: white; padding: 2px 8px; "
                    "border-radius: 3px; font-weight: bold;"
                )
            else:
                self.autotrade_status.setText("  自動売買: OFF  ")
                self.autotrade_status.setStyleSheet(
                    "background-color: #FF9800; color: white; padding: 2px 8px; "
                    "border-radius: 3px; font-weight: bold;"
                )
                log.warning("MT5の自動売買が無効です — ツールバーの「アルゴリズム取引」を有効にしてください")
        except Exception:
            pass

    def _update_status_bar(self):
        """ステータスバーの口座表示を更新."""
        acc = self.settings.current_account
        if acc.type == "real":
            self.account_status.setText(f"  REAL: {acc.server} ({acc.login})  ")
            self.account_status.setStyleSheet(
                "background-color: #F44336; color: white; padding: 2px 8px; "
                "border-radius: 3px; font-weight: bold;"
            )
        else:
            self.account_status.setText(f"  DEMO: {acc.server} ({acc.login})  ")
            self.account_status.setStyleSheet(
                "background-color: #4CAF50; color: white; padding: 2px 8px; "
                "border-radius: 3px; font-weight: bold;"
            )

    def closeEvent(self, event):
        """ウィンドウ閉じる時にワーカーを停止."""
        if self.trading_worker and self.trading_worker.isRunning():
            self.trading_worker.stop()
            self.trading_worker.wait(5000)
        if self.weekend_retrain_worker and self.weekend_retrain_worker.isRunning():
            self.weekend_retrain_worker.wait(5000)
        if self.retrain_timer:
            self.retrain_timer.stop()
        event.accept()
