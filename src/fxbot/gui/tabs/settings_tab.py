"""設定タブ — デモ/リアル切替, ペア選択, リスク設定."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFormLayout, QGroupBox,
    QLabel, QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox,
    QPushButton, QMessageBox, QListWidget, QAbstractItemView, QCheckBox,
    QTabWidget,
)
from PySide6.QtCore import Signal, QTimer

from fxbot.config import Settings, AccountConfig
from fxbot.logger import get_logger

log = get_logger(__name__)


class SettingsTab(QWidget):
    """設定タブ."""
    account_changed = Signal(str)  # 口座切替シグナル
    settings_changed = Signal()

    def __init__(self, settings: Settings, parent=None):
        super().__init__(parent)
        self.settings = settings
        self._init_ui()
        self._load_settings()

    def _init_ui(self):
        main_layout = QVBoxLayout(self)

        sub_tabs = QTabWidget()
        sub_tabs.addTab(self._build_account_tab(), "口座")
        sub_tabs.addTab(self._build_trading_tab(), "取引・リスク")
        sub_tabs.addTab(self._build_model_tab(), "モデル")
        sub_tabs.addTab(self._build_log_tab(), "ログ")
        main_layout.addWidget(sub_tabs)

        save_btn = QPushButton("設定保存")
        save_btn.clicked.connect(self._save_settings)
        main_layout.addWidget(save_btn)

    # ---- サブタブ構築 ----

    def _build_account_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)

        # 口座設定
        account_group = QGroupBox("口座設定")
        account_layout = QFormLayout()

        self.account_combo = QComboBox()
        self.account_combo.addItems(list(self.settings.accounts.keys()))
        self.account_combo.currentTextChanged.connect(self._on_account_selected)
        account_layout.addRow("アクティブ口座:", self.account_combo)

        self.server_edit = QLineEdit()
        account_layout.addRow("サーバー:", self.server_edit)

        self.login_edit = QSpinBox()
        self.login_edit.setRange(0, 999999999)
        account_layout.addRow("ログインID:", self.login_edit)

        self.password_edit = QLineEdit()
        self.password_edit.setEchoMode(QLineEdit.EchoMode.Password)
        account_layout.addRow("パスワード:", self.password_edit)

        self.account_type_label = QLabel()
        account_layout.addRow("口座タイプ:", self.account_type_label)

        self.switch_btn = QPushButton("口座切替")
        self.switch_btn.clicked.connect(self._on_switch_account)
        account_layout.addRow(self.switch_btn)

        account_group.setLayout(account_layout)
        layout.addWidget(account_group)

        # 発注テスト
        test_group = QGroupBox("発注テスト")
        test_layout = QVBoxLayout()

        self.test_order_btn = QPushButton("発注テスト（USDJPY 最小ロット）")
        self.test_order_btn.clicked.connect(self._on_test_order)
        test_layout.addWidget(self.test_order_btn)

        test_group.setLayout(test_layout)
        layout.addWidget(test_group)

        layout.addStretch()
        return page

    def _build_trading_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)

        # 取引設定
        trading_group = QGroupBox("取引設定")
        trading_layout = QFormLayout()

        self.max_positions_spin = QSpinBox()
        self.max_positions_spin.setRange(1, 20)
        trading_layout.addRow("最大ポジション数:", self.max_positions_spin)

        self.prediction_horizon_spin = QSpinBox()
        self.prediction_horizon_spin.setRange(1, 50)
        trading_layout.addRow("予測ホライゾン:", self.prediction_horizon_spin)

        self.min_threshold_spin = QDoubleSpinBox()
        self.min_threshold_spin.setDecimals(5)
        self.min_threshold_spin.setRange(0.0, 0.01)
        self.min_threshold_spin.setSingleStep(0.0001)
        trading_layout.addRow("最小予測閾値:", self.min_threshold_spin)

        self.max_lot_spin = QDoubleSpinBox()
        self.max_lot_spin.setDecimals(2)
        self.max_lot_spin.setRange(0.01, 10.0)
        self.max_lot_spin.setSingleStep(0.01)
        trading_layout.addRow("最大ロット:", self.max_lot_spin)

        trading_group.setLayout(trading_layout)
        layout.addWidget(trading_group)

        # リスク管理
        risk_group = QGroupBox("リスク管理")
        risk_layout = QFormLayout()

        self.risk_per_trade_spin = QDoubleSpinBox()
        self.risk_per_trade_spin.setDecimals(3)
        self.risk_per_trade_spin.setRange(0.001, 0.1)
        self.risk_per_trade_spin.setSingleStep(0.005)
        risk_layout.addRow("1トレードリスク:", self.risk_per_trade_spin)

        self.atr_sl_spin = QDoubleSpinBox()
        self.atr_sl_spin.setDecimals(1)
        self.atr_sl_spin.setRange(0.5, 5.0)
        self.atr_sl_spin.setSingleStep(0.5)
        risk_layout.addRow("ATR SL倍率:", self.atr_sl_spin)

        self.atr_tp_spin = QDoubleSpinBox()
        self.atr_tp_spin.setDecimals(1)
        self.atr_tp_spin.setRange(0.5, 10.0)
        self.atr_tp_spin.setSingleStep(0.5)
        risk_layout.addRow("ATR TP倍率:", self.atr_tp_spin)

        risk_group.setLayout(risk_layout)
        layout.addWidget(risk_group)

        layout.addStretch()
        return page

    def _build_model_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)

        # モデル設定
        model_group = QGroupBox("モデル設定")
        model_layout = QFormLayout()

        self.model_mode_combo = QComboBox()
        self.model_mode_combo.addItems(["regression", "classification"])
        self.model_mode_combo.setToolTip(
            "regression: 対数リターン予測（デフォルト）\n"
            "classification: Triple Barrier勝率重視"
        )
        model_layout.addRow("学習モード:", self.model_mode_combo)

        self.min_confidence_spin = QDoubleSpinBox()
        self.min_confidence_spin.setDecimals(2)
        self.min_confidence_spin.setRange(0.0, 1.0)
        self.min_confidence_spin.setSingleStep(0.05)
        self.min_confidence_spin.setToolTip("0.0=無効 / 分類モード推奨値: 0.55")
        model_layout.addRow("最低信頼度 (分類):", self.min_confidence_spin)

        model_group.setLayout(model_layout)
        layout.addWidget(model_group)

        # 市場環境フィルター
        mf_group = QGroupBox("市場環境フィルター（勝率向上）")
        mf_layout = QFormLayout()

        self.mf_enabled_check = QCheckBox("フィルターを有効にする")
        mf_layout.addRow(self.mf_enabled_check)

        self.mf_min_adx_spin = QDoubleSpinBox()
        self.mf_min_adx_spin.setDecimals(1)
        self.mf_min_adx_spin.setRange(5.0, 50.0)
        self.mf_min_adx_spin.setSingleStep(5.0)
        self.mf_min_adx_spin.setToolTip("ADXがこの値未満はレンジ相場としてHOLD")
        mf_layout.addRow("最小ADX (トレンド判定):", self.mf_min_adx_spin)

        self.mf_max_spread_spin = QDoubleSpinBox()
        self.mf_max_spread_spin.setDecimals(1)
        self.mf_max_spread_spin.setRange(0.5, 10.0)
        self.mf_max_spread_spin.setSingleStep(0.5)
        self.mf_max_spread_spin.setToolTip("スプレッドがこれを超えたらHOLD (pips)")
        mf_layout.addRow("最大スプレッド (pips):", self.mf_max_spread_spin)

        self.mf_session_check = QCheckBox("ロンドン・NYセッションのみ取引")
        self.mf_session_check.setToolTip("ロンドン7-16 UTC、NY 13-22 UTC")
        mf_layout.addRow(self.mf_session_check)

        mf_group.setLayout(mf_layout)
        layout.addWidget(mf_group)

        layout.addStretch()
        return page

    def _build_log_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)

        tl_group = QGroupBox("取引ログ（勝率分析）")
        tl_layout = QFormLayout()

        self.tl_enabled_check = QCheckBox("取引ログを有効にする")
        tl_layout.addRow(self.tl_enabled_check)

        self.tl_db_path_edit = QLineEdit()
        self.tl_db_path_edit.setToolTip("プロジェクトルートからの相対パス")
        tl_layout.addRow("DB保存パス:", self.tl_db_path_edit)

        tl_group.setLayout(tl_layout)
        layout.addWidget(tl_group)

        layout.addStretch()
        return page

    def _load_settings(self):
        s = self.settings
        self.account_combo.setCurrentText(s.active_account)
        self._update_account_fields(s.active_account)

        self.max_positions_spin.setValue(s.trading.max_positions)
        self.prediction_horizon_spin.setValue(s.trading.prediction_horizon)
        self.min_threshold_spin.setValue(s.trading.min_prediction_threshold)
        self.max_lot_spin.setValue(s.trading.max_lot)

        self.risk_per_trade_spin.setValue(s.risk.max_risk_per_trade)
        self.atr_sl_spin.setValue(s.risk.atr_sl_multiplier)
        self.atr_tp_spin.setValue(s.risk.atr_tp_multiplier)

        # モデル設定
        mode_idx = self.model_mode_combo.findText(s.model.mode)
        if mode_idx >= 0:
            self.model_mode_combo.setCurrentIndex(mode_idx)
        self.min_confidence_spin.setValue(s.trading.min_confidence)

        # 市場フィルター
        self.mf_enabled_check.setChecked(s.market_filter.enabled)
        self.mf_min_adx_spin.setValue(s.market_filter.min_adx)
        self.mf_max_spread_spin.setValue(s.market_filter.max_spread_pips)
        self.mf_session_check.setChecked(s.market_filter.session_only)

        # 取引ログ
        self.tl_enabled_check.setChecked(s.trade_logging.enabled)
        self.tl_db_path_edit.setText(s.trade_logging.db_path)

    def _update_account_fields(self, name: str):
        acc = self.settings.accounts.get(name)
        if acc:
            self.server_edit.setText(acc.server)
            self.login_edit.setValue(acc.login)
            self.password_edit.setText(acc.password)
            self.account_type_label.setText(acc.type.upper())
            if acc.type == "real":
                self.account_type_label.setStyleSheet("color: red; font-weight: bold;")
            else:
                self.account_type_label.setStyleSheet("color: green; font-weight: bold;")

    def _on_account_selected(self, name: str):
        self._update_account_fields(name)

    def _on_switch_account(self):
        name = self.account_combo.currentText()
        acc = self.settings.accounts.get(name)

        if acc and acc.type == "real":
            reply = QMessageBox.warning(
                self,
                "リアル口座への切替",
                "リアル口座に切り替えます。\n実際の資金で取引が行われます。\n\n本当に切り替えますか？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if reply != QMessageBox.StandardButton.Yes:
                return

        # 設定を更新
        self.settings.active_account = name
        acc = self.settings.accounts[name]
        acc.server = self.server_edit.text()
        acc.login = self.login_edit.value()
        acc.password = self.password_edit.text()

        log.info(f"口座切替: {name} ({acc.type})")
        self.account_changed.emit(name)

    def _save_settings(self):
        s = self.settings

        # 現在の口座設定を保存
        name = self.account_combo.currentText()
        acc = s.accounts[name]
        acc.server = self.server_edit.text()
        acc.login = self.login_edit.value()
        acc.password = self.password_edit.text()

        s.trading.max_positions = self.max_positions_spin.value()
        s.trading.prediction_horizon = self.prediction_horizon_spin.value()
        s.trading.min_prediction_threshold = self.min_threshold_spin.value()
        s.trading.max_lot = self.max_lot_spin.value()
        s.trading.min_confidence = self.min_confidence_spin.value()

        s.risk.max_risk_per_trade = self.risk_per_trade_spin.value()
        s.risk.atr_sl_multiplier = self.atr_sl_spin.value()
        s.risk.atr_tp_multiplier = self.atr_tp_spin.value()

        s.model.mode = self.model_mode_combo.currentText()

        s.market_filter.enabled = self.mf_enabled_check.isChecked()
        s.market_filter.min_adx = self.mf_min_adx_spin.value()
        s.market_filter.max_spread_pips = self.mf_max_spread_spin.value()
        s.market_filter.session_only = self.mf_session_check.isChecked()

        s.trade_logging.enabled = self.tl_enabled_check.isChecked()
        s.trade_logging.db_path = self.tl_db_path_edit.text()

        self.settings_changed.emit()
        log.info("設定保存完了")
        QMessageBox.information(self, "保存", "設定を保存しました。")

    # --- 発注テスト ---

    def _on_test_order(self):
        """USDJPYを最小ロットで発注し、10秒後に決済するテスト."""
        from fxbot.mt5.symbols import load_symbols
        from fxbot.mt5.execution import send_order, close_position

        # symbols.json からUSDJPYの実際のシンボル名とvolume_minを取得
        symbols = load_symbols(self.settings)
        test_symbol = None
        volume_min = 0.01
        for s in symbols:
            if "USDJPY" in s["name"]:
                test_symbol = s["name"]
                volume_min = s["volume_min"]
                break

        if test_symbol is None:
            log.error("発注テスト: USDJPYシンボルが見つかりません")
            QMessageBox.warning(self, "エラー", "USDJPYシンボルが見つかりません。\nシンボル検出を先に実行してください。")
            return

        reply = QMessageBox.question(
            self,
            "発注テスト確認",
            f"{test_symbol}を最小ロット({volume_min})で成行BUYし、\n"
            "10秒後に自動決済します。\n\n実行しますか？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        self.test_order_btn.setEnabled(False)

        # MT5の自動売買が有効か事前チェック
        import MetaTrader5 as mt5
        ti = mt5.terminal_info()
        if ti is None or not ti.trade_allowed:
            msg = "MT5ターミナルで自動売買が無効です。\nツールバーの「アルゴリズム取引」ボタンを有効にしてください。"
            log.error(f"発注テスト: {msg}")
            QMessageBox.warning(self, "発注テスト失敗", msg)
            self.test_order_btn.setEnabled(True)
            return

        result = send_order(test_symbol, "buy", volume_min, sl=0, tp=0,
                            comment="fxbot3_test")
        if result is None or "error" in result:
            err = result["error"] if result and "error" in result else "注文送信失敗"
            log.error(f"発注テスト: {err}")
            QMessageBox.warning(self, "発注テスト失敗", err)
            self.test_order_btn.setEnabled(True)
            return

        ticket = result["ticket"]
        log.info(f"発注テスト: 約定 ticket={ticket}, price={result['price']}, "
                 f"volume={result['volume']}")

        def _close():
            if close_position(ticket):
                log.info(f"発注テスト: 決済完了 ticket={ticket}")
            else:
                log.error(f"発注テスト: 決済失敗 ticket={ticket}")
            self.test_order_btn.setEnabled(True)

        QTimer.singleShot(10000, _close)
