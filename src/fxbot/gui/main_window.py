"""メインウィンドウ — QMainWindow + タブ + ライブ取引制御."""

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
from fxbot.gui.tabs.market_filter_tab import MarketFilterTab
from fxbot.gui.tabs.trade_log_tab import TradeLogTab
from fxbot.gui.tabs.pair_performance_tab import PairPerformanceTab
from fxbot.gui.tabs.system_analysis_tab import SystemAnalysisTab
from fxbot.gui.tabs.strategy_analysis_tab import StrategyAnalysisTab
from fxbot.gui.tabs.pair_selection_tab import PairSelectionTab
from fxbot.gui.tabs.batch_train_tab import BatchTrainTab
from fxbot.gui.tabs.settings_analysis_tab import SettingsAnalysisTab
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

        from fxbot import notifier as slack
        slack.configure(settings.slack)

        self._init_ui()
        self._connect_signals()
        self._update_status_bar()
        self._load_symbols()
        self._setup_retraining_scheduler()
        self._push_analysis_runtime_state()

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

        # 0. ダッシュボード
        self.dashboard_tab = DashboardTab(self.settings)
        self.tabs.addTab(self.dashboard_tab, "ダッシュボード")

        # 1. 通貨ペア選択
        self.pair_selection_tab = PairSelectionTab(self.settings)
        self.tabs.addTab(self.pair_selection_tab, "通貨ペア")

        # 2. 一括学習
        self.batch_train_tab = BatchTrainTab(self.settings)
        self.tabs.addTab(self.batch_train_tab, "一括学習")

        # 3. モデル
        self.model_tab = ModelTab(self.settings)
        self.tabs.addTab(self.model_tab, "モデル")

        # 4. バックテスト
        self.backtest_tab = BacktestTab(self.settings)
        self.tabs.addTab(self.backtest_tab, "バックテスト")

        # 5. SHAP
        self.shap_tab = ShapTab(self.settings)
        self.tabs.addTab(self.shap_tab, "SHAP")

        # 6. 設定
        self.settings_tab = SettingsTab(self.settings)
        self.tabs.addTab(self.settings_tab, "設定")

        # 7. 市場フィルター
        self.market_filter_tab = MarketFilterTab(self.settings)
        self.tabs.addTab(self.market_filter_tab, "市場フィルター")

        # 8. 取引ログ
        self.trade_log_tab = TradeLogTab(self.settings)
        self.tabs.addTab(self.trade_log_tab, "取引ログ")

        # 9. 通貨別成績
        self.pair_performance_tab = PairPerformanceTab(self.settings)
        self.tabs.addTab(self.pair_performance_tab, "通貨別成績")

        # 10. 全体監視
        self.system_analysis_tab = SystemAnalysisTab(self.settings)
        self.tabs.addTab(self.system_analysis_tab, "全体監視")

        # 11. 戦略分析
        self.strategy_analysis_tab = StrategyAnalysisTab(self.settings)
        self.tabs.addTab(self.strategy_analysis_tab, "戦略分析")

        # 12. 設定分析
        self.settings_analysis_tab = SettingsAnalysisTab(self.settings)
        self.tabs.addTab(self.settings_analysis_tab, "設定分析")

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
        self.settings_tab.settings_changed.connect(self._on_settings_changed)
        self.settings_tab.settings_changed.connect(self._on_symbols_changed)
        self.pair_selection_tab.settings_changed.connect(self._on_symbols_changed)
        self.model_tab.on_train_complete = self._on_train_complete
        self.strategy_analysis_tab.jump_requested.connect(self._on_advice_jump)
        self.strategy_analysis_tab.warn_count_changed.connect(self._on_warn_count_changed)
        self.settings_analysis_tab.apply_profile_requested.connect(self._on_apply_profile)
        self.settings_analysis_tab.clone_and_edit_requested.connect(self._on_clone_profile)

    def _on_advice_jump(self, tab_name: str) -> None:
        """戦略アドバイザーのボタンで対象タブへジャンプ."""
        tab_map = {"market_filter": 7, "settings": 6}
        idx = tab_map.get(tab_name)
        if idx is not None:
            self.tabs.setCurrentIndex(idx)

    def _on_apply_profile(self, profile_id: str, snapshot_id: int) -> None:
        """設定分析タブからのプロファイル適用."""
        if not self.settings.trade_logging.enabled:
            return
        from fxbot.config import _PROJECT_ROOT, save_settings
        from fxbot.profile_manager import ProfileManager
        db_path = _PROJECT_ROOT / self.settings.trade_logging.db_path
        pm = ProfileManager(db_path)
        pm.apply_profile(snapshot_id, self.settings)
        pm.close()
        self.settings.active_profile_id = profile_id
        self.settings.active_snapshot_id = snapshot_id
        save_settings(self.settings)
        self._on_settings_changed()
        self._on_symbols_changed()
        self.tabs.setCurrentIndex(self.tabs.indexOf(self.settings_tab))

    def _on_clone_profile(self, profile_id: str, snapshot_id: int) -> None:
        """設定分析タブからのプロファイル複製→設定タブへジャンプ."""
        if not self.settings.trade_logging.enabled:
            return
        from fxbot.config import _PROJECT_ROOT, save_settings
        from fxbot.profile_manager import ProfileManager
        import dataclasses
        db_path = _PROJECT_ROOT / self.settings.trade_logging.db_path
        pm = ProfileManager(db_path)
        tmp = dataclasses.replace(self.settings)
        pm.apply_profile(snapshot_id, tmp)
        new_name = f"clone_{profile_id[:8]}"
        new_pid, new_sid = pm.save_profile(new_name, "(複製)", tmp, base_profile_id=profile_id)
        pm.close()
        self.settings.active_profile_id = new_pid
        self.settings.active_snapshot_id = new_sid
        save_settings(self.settings)
        self._on_settings_changed()
        self._on_symbols_changed()
        self.tabs.setCurrentIndex(self.tabs.indexOf(self.settings_tab))

    def _on_warn_count_changed(self, count: int) -> None:
        """戦略アドバイザー由来のwarn件数をタブラベルに反映."""
        idx = self.tabs.indexOf(self.strategy_analysis_tab)
        if idx >= 0:
            label = f"戦略分析 ⚠{count}" if count > 0 else "戦略分析"
            self.tabs.setTabText(idx, label)

    def _load_symbols(self):
        """保存済みシンボルをタブに設定。未保存の場合はMT5から自動検出."""
        try:
            from fxbot.mt5.symbols import get_symbol_names, detect_symbols, save_symbols

            symbols = get_symbol_names(self.settings)
            if symbols:
                self.pair_selection_tab.set_symbols(symbols)
                self.model_tab.set_symbols(symbols)
                self.backtest_tab.set_symbols(symbols)
                self._on_symbols_changed()
                return

            # symbols.json が存在しないor空 → MT5接続して自動検出
            log.info("シンボル未保存 — MT5から自動検出を開始")
            from fxbot.mt5.connection import connect

            if not connect(self.settings):
                log.warning("MT5接続失敗 — シンボル自動検出をスキップ")
                self._on_symbols_changed()
                return

            self.connection_status.setText("接続中")
            self.connection_status.setStyleSheet("color: green;")
            self._check_autotrade()

            detected = detect_symbols(self.settings)
            if not detected:
                log.warning("シンボル検出結果が空です")
                self._on_symbols_changed()
                return

            save_symbols(detected, self.settings)
            symbols = [s["name"] for s in detected]
            self.pair_selection_tab.set_symbols(symbols)
            self.model_tab.set_symbols(symbols)
            self.backtest_tab.set_symbols(symbols)
            self._on_symbols_changed()
            log.info(f"シンボル自動検出完了: {len(symbols)}ペア")
        except Exception:
            log.exception("シンボル読み込みエラー")

    def _on_symbols_changed(self) -> None:
        """active_symbols 変更時に各タブを更新."""
        syms = self.settings.trading.active_symbols
        self.batch_train_tab.refresh_symbols(syms)
        self.market_filter_tab.refresh_symbols(syms)
        self.pair_performance_tab.refresh_symbols(syms)
        self.strategy_analysis_tab.refresh_symbols(syms)

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
        self.trading_worker.signals.filter_update.connect(self.market_filter_tab.update_filter_status)
        self.trading_worker.start()

        self.start_trading_btn.setEnabled(False)
        self.stop_trading_btn.setEnabled(True)
        self.trading_status_label.setText("取引中...")
        self.trading_status_label.setStyleSheet(
            "font-size: 14px; padding: 0 10px; color: #4CAF50; font-weight: bold;"
        )
        self._push_analysis_runtime_state(progress="ライブ取引開始")
        log.info("ライブ取引開始")

    def _stop_trading(self):
        """ライブ取引を停止."""
        if self.trading_worker:
            self.trading_worker.stop()
            self.trading_status_label.setText("停止処理中...")
            self._push_analysis_runtime_state(progress="停止処理中...")

    def _on_trading_progress(self, msg: str):
        self.trading_status_label.setText(msg)
        self._push_analysis_runtime_state(progress=msg)

    def _on_trading_error(self, msg: str):
        log.error(msg)
        self.trading_status_label.setText("エラー")
        self.trading_status_label.setStyleSheet(
            "font-size: 14px; padding: 0 10px; color: #F44336;"
        )
        self.start_trading_btn.setEnabled(True)
        self.stop_trading_btn.setEnabled(False)
        self._push_analysis_runtime_state(error=msg)

    def _on_trading_stopped(self, _result):
        self.start_trading_btn.setEnabled(True)
        self.stop_trading_btn.setEnabled(False)
        self.trading_status_label.setText("停止中")
        self.trading_status_label.setStyleSheet("font-size: 14px; padding: 0 10px;")
        self._push_analysis_runtime_state(progress="停止中")
        log.info("ライブ取引停止")

    # --- 自動再学習スケジューラ ---

    def _setup_retraining_scheduler(self):
        """自動再学習タイマーを設定（1時間ごとにチェック）."""
        if not self.settings.retraining.enabled:
            return

        if self.settings.retraining.weekend_only:
            interval_ms = 3600 * 1000
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

        if rt_cfg.weekend_only:
            if now.weekday() < 5:
                return
            if self._last_weekend_retrain_date == now.date():
                return

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

        if not trained:
            consecutive = self._count_consecutive_wfo_failures()
            max_fail = self.settings.retraining.wfo_max_consecutive_failures
            log.warning(f"WFO連続未達: {consecutive}回 (閾値: {max_fail}回)")
            if consecutive >= max_fail and self.trading_worker is not None:
                log.warning(f"WFO連続未達{consecutive}回に達したためライブ取引を自動停止")
                self._stop_trading()

        self.dashboard_tab.refresh_auto_retrain_result()
        self.strategy_analysis_tab.refresh()
        self._push_analysis_runtime_state(progress=f"週末再学習完了: {reason}")

    def _count_consecutive_wfo_failures(self) -> int:
        """直近の auto_retrain ログから連続WFO未達回数を数える（最新ログ含む）."""
        import json
        log_dir = self.settings.resolve_path("logs")
        files = sorted(log_dir.glob("auto_retrain_*.json"), reverse=True)
        count = 0
        for f in files:
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                if data.get("trained", True):
                    break
                count += 1
            except Exception:
                break
        return count

    def _on_weekend_retrain_error(self, msg: str):
        """週末再学習エラー."""
        log.error(msg)
        self._push_analysis_runtime_state(error=msg)

    # --- 口座切替・その他 ---

    def _on_settings_changed(self):
        """設定保存後に SlackNotifier を再初期化."""
        from fxbot import notifier as slack
        slack.configure(self.settings.slack)

    def _on_account_changed(self, account_name: str):
        """口座切替時の処理."""
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
        self._push_analysis_runtime_state()

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
            self._push_analysis_runtime_state()
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

    def _push_analysis_runtime_state(
        self,
        *,
        progress: str | None = None,
        error: str | None = None,
    ) -> None:
        """分析タブへ現在の稼働状態を反映."""
        if not hasattr(self, "system_analysis_tab"):
            return
        trading_running = self.trading_worker is not None and self.trading_worker.isRunning()
        retrain_running = (
            self.weekend_retrain_worker is not None and self.weekend_retrain_worker.isRunning()
        )
        self.system_analysis_tab.update_runtime_snapshot(
            connection=self.connection_status.text() or "未接続",
            autotrade=self.autotrade_status.text().strip() or "---",
            trading=self.trading_status_label.text() or "---",
            trading_running=trading_running,
            retrain_running=retrain_running,
            progress=progress,
            error=error,
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
