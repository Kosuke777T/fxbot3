"""設定タブ — デモ/リアル切替, ペア選択, リスク設定."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFormLayout, QGroupBox,
    QLabel, QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox,
    QPushButton, QMessageBox, QListWidget, QAbstractItemView, QCheckBox,
    QTabWidget, QScrollArea, QTableWidget, QTableWidgetItem, QHeaderView,
    QTextEdit,
)
from PySide6.QtCore import Qt, Signal, QTimer
from PySide6.QtGui import QColor, QFont

from fxbot.config import Settings, AccountConfig, save_settings
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
        sub_tabs.addTab(self._build_notification_tab(), "通知")
        sub_tabs.addTab(self._build_profile_tab(), "プロファイル")
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
        trading_layout.addRow("最大ポジション数（全体）:", self.max_positions_spin)

        self.max_active_symbols_spin = QSpinBox()
        self.max_active_symbols_spin.setRange(1, 10)
        self.max_active_symbols_spin.setToolTip("同時に保有できる通貨ペアの種類数")
        trading_layout.addRow("最大通貨ペア数:", self.max_active_symbols_spin)

        self.max_positions_per_symbol_spin = QSpinBox()
        self.max_positions_per_symbol_spin.setRange(1, 10)
        self.max_positions_per_symbol_spin.setToolTip("1通貨ペアあたりの最大保有ポジション数")
        trading_layout.addRow("ペア別最大ポジション数:", self.max_positions_per_symbol_spin)

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
        trading_layout.addRow("最大ロット（絶対上限）:", self.max_lot_spin)

        self.max_lot_balance_pct_spin = QDoubleSpinBox()
        self.max_lot_balance_pct_spin.setDecimals(3)
        self.max_lot_balance_pct_spin.setRange(0.0, 0.05)
        self.max_lot_balance_pct_spin.setSingleStep(0.001)
        self.max_lot_balance_pct_spin.setToolTip(
            "0.0=無効（最大ロット固定）\n"
            "例: 0.005 → 残高の0.5%をロット上限に\n"
            "balance=1,000,000 → 上限0.05lot"
        )
        trading_layout.addRow("残高連動ロット上限(%):", self.max_lot_balance_pct_spin)

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

        self.trailing_sl_check = QCheckBox("SLトレーリング（SLを利益方向へ追従）")
        risk_layout.addRow(self.trailing_sl_check)

        self.trailing_tp_check = QCheckBox("TPトレーリング（TP到達後も継続保有）")
        risk_layout.addRow(self.trailing_tp_check)

        risk_group.setLayout(risk_layout)
        layout.addWidget(risk_group)

        layout.addStretch()
        return page

    def _build_model_tab(self) -> QWidget:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)

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

        self.mf_enabled_check = QCheckBox("フィルターを有効にする（マスタースイッチ）")
        self.mf_enabled_check.stateChanged.connect(self._on_mf_enabled_changed)
        mf_layout.addRow(self.mf_enabled_check)

        # ADXフィルター
        self.mf_adx_check = QCheckBox("ADXフィルター（レンジ相場を除外）")
        self.mf_adx_check.setToolTip("ADXが閾値未満のレンジ相場ではHOLD")
        mf_layout.addRow(self.mf_adx_check)

        self.mf_min_adx_spin = QDoubleSpinBox()
        self.mf_min_adx_spin.setDecimals(1)
        self.mf_min_adx_spin.setRange(5.0, 50.0)
        self.mf_min_adx_spin.setSingleStep(5.0)
        self.mf_min_adx_spin.setToolTip("ADXがこの値未満はレンジ相場としてHOLD")
        mf_layout.addRow("    最小ADX:", self.mf_min_adx_spin)

        # スプレッドフィルター
        self.mf_spread_check = QCheckBox("スプレッドフィルター")
        self.mf_spread_check.setToolTip("スプレッドが閾値を超えた場合はHOLD")
        mf_layout.addRow(self.mf_spread_check)

        self.mf_max_spread_spin = QDoubleSpinBox()
        self.mf_max_spread_spin.setDecimals(1)
        self.mf_max_spread_spin.setRange(0.5, 10.0)
        self.mf_max_spread_spin.setSingleStep(0.5)
        self.mf_max_spread_spin.setToolTip("スプレッドがこれを超えたらHOLD (pips)")
        mf_layout.addRow("    最大スプレッド (pips):", self.mf_max_spread_spin)

        # ボラティリティフィルター
        self.mf_volatility_check = QCheckBox("ボラティリティフィルター（低/過大ボラを除外）")
        self.mf_volatility_check.setToolTip("ATR%が閾値外の低ボラ・過大ボラ相場ではHOLD")
        mf_layout.addRow(self.mf_volatility_check)

        self.mf_min_atr_spin = QDoubleSpinBox()
        self.mf_min_atr_spin.setDecimals(3)
        self.mf_min_atr_spin.setRange(0.001, 0.5)
        self.mf_min_atr_spin.setSingleStep(0.005)
        self.mf_min_atr_spin.setToolTip("ATR%がこの値未満は低ボラでHOLD")
        mf_layout.addRow("    最小ATR% (低ボラ閾値):", self.mf_min_atr_spin)

        self.mf_max_atr_spin = QDoubleSpinBox()
        self.mf_max_atr_spin.setDecimals(2)
        self.mf_max_atr_spin.setRange(0.1, 5.0)
        self.mf_max_atr_spin.setSingleStep(0.1)
        self.mf_max_atr_spin.setToolTip("ATR%がこの値を超えたら過大ボラでHOLD")
        mf_layout.addRow("    最大ATR% (過大ボラ閾値):", self.mf_max_atr_spin)

        # セッションフィルター
        self.mf_session_check = QCheckBox("ロンドン・NYセッションのみ取引")
        self.mf_session_check.setToolTip("ロンドン7-16 UTC、NY 13-22 UTC")
        mf_layout.addRow(self.mf_session_check)

        mf_group.setLayout(mf_layout)
        layout.addWidget(mf_group)

        # 自動再学習スケジューラー
        rt_group = QGroupBox("自動再学習スケジューラー")
        rt_layout = QFormLayout()

        self.rt_enabled_check = QCheckBox("自動再学習を有効にする")
        rt_layout.addRow(self.rt_enabled_check)

        self.rt_weekend_only_check = QCheckBox("土日のみ実行（週末スケジューラー）")
        self.rt_weekend_only_check.setToolTip(
            "有効: 土日のみ実行（毎時チェック）\n"
            "無効: interval_hours間隔で実行"
        )
        rt_layout.addRow(self.rt_weekend_only_check)

        self.rt_interval_spin = QSpinBox()
        self.rt_interval_spin.setRange(1, 720)
        self.rt_interval_spin.setSuffix(" 時間")
        self.rt_interval_spin.setToolTip("週末モード無効時のみ有効")
        rt_layout.addRow("実行間隔（週末オフ時）:", self.rt_interval_spin)

        self.rt_wfo_check = QCheckBox("学習前にWFOを実行して合格判定")
        rt_layout.addRow(self.rt_wfo_check)

        self.rt_wfo_win_rate_spin = QDoubleSpinBox()
        self.rt_wfo_win_rate_spin.setDecimals(2)
        self.rt_wfo_win_rate_spin.setRange(0.0, 1.0)
        self.rt_wfo_win_rate_spin.setSingleStep(0.05)
        self.rt_wfo_win_rate_spin.setToolTip("WFOがこの勝率を下回ったら学習をスキップ")
        rt_layout.addRow("WFO合格基準 勝率:", self.rt_wfo_win_rate_spin)

        self.rt_wfo_sharpe_spin = QDoubleSpinBox()
        self.rt_wfo_sharpe_spin.setDecimals(2)
        self.rt_wfo_sharpe_spin.setRange(-5.0, 10.0)
        self.rt_wfo_sharpe_spin.setSingleStep(0.1)
        self.rt_wfo_sharpe_spin.setToolTip("WFOがこのシャープを下回ったら学習をスキップ")
        rt_layout.addRow("WFO合格基準 Sharpe:", self.rt_wfo_sharpe_spin)

        self.rt_monitor_window_spin = QSpinBox()
        self.rt_monitor_window_spin.setRange(5, 200)
        self.rt_monitor_window_spin.setSuffix(" 件")
        rt_layout.addRow("監視ウィンドウ:", self.rt_monitor_window_spin)

        self.rt_min_win_rate_spin = QDoubleSpinBox()
        self.rt_min_win_rate_spin.setDecimals(2)
        self.rt_min_win_rate_spin.setRange(0.0, 1.0)
        self.rt_min_win_rate_spin.setSingleStep(0.05)
        self.rt_min_win_rate_spin.setToolTip("劣化検知トリガー: 勝率がこれを下回ったら警告")
        rt_layout.addRow("劣化検知 最低勝率:", self.rt_min_win_rate_spin)

        self.rt_min_sharpe_spin = QDoubleSpinBox()
        self.rt_min_sharpe_spin.setDecimals(2)
        self.rt_min_sharpe_spin.setRange(-5.0, 10.0)
        self.rt_min_sharpe_spin.setSingleStep(0.1)
        self.rt_min_sharpe_spin.setToolTip("劣化検知トリガー: シャープがこれを下回ったら警告")
        rt_layout.addRow("劣化検知 最低Sharpe:", self.rt_min_sharpe_spin)

        rt_group.setLayout(rt_layout)
        layout.addWidget(rt_group)

        layout.addStretch()
        scroll.setWidget(page)
        return scroll

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

    def _build_notification_tab(self) -> QWidget:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)

        page = QWidget()
        layout = QVBoxLayout(page)

        # Slack 設定
        slack_group = QGroupBox("Slack 通知（Incoming Webhook）")
        slack_layout = QFormLayout()

        self.slack_enabled_check = QCheckBox("Slack 通知を有効にする")
        slack_layout.addRow(self.slack_enabled_check)

        # Webhook URL（パスワードモード + 表示切替ボタン）
        webhook_row = QHBoxLayout()
        self.slack_webhook_edit = QLineEdit()
        self.slack_webhook_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.slack_webhook_edit.setPlaceholderText("https://hooks.slack.com/services/...")
        webhook_row.addWidget(self.slack_webhook_edit)
        self.slack_webhook_toggle_btn = QPushButton("表示")
        self.slack_webhook_toggle_btn.setFixedWidth(50)
        self.slack_webhook_toggle_btn.setCheckable(True)
        self.slack_webhook_toggle_btn.toggled.connect(self._on_webhook_toggle)
        webhook_row.addWidget(self.slack_webhook_toggle_btn)
        slack_layout.addRow("Webhook URL:", webhook_row)

        # テスト送信ボタン
        self.slack_test_btn = QPushButton("テスト送信")
        self.slack_test_btn.setToolTip("現在の Webhook URL にテストメッセージを送信します")
        self.slack_test_btn.clicked.connect(self._on_slack_test)
        slack_layout.addRow(self.slack_test_btn)

        slack_group.setLayout(slack_layout)
        layout.addWidget(slack_group)

        # 通知イベント選択
        event_group = QGroupBox("通知イベント")
        event_layout = QFormLayout()

        self.slack_notify_entry_check = QCheckBox("エントリー通知（BUY/SELL 約定）")
        event_layout.addRow(self.slack_notify_entry_check)

        self.slack_notify_exit_check = QCheckBox("決済通知（SL/TP/トレーリング/手動）")
        event_layout.addRow(self.slack_notify_exit_check)

        self.slack_notify_error_check = QCheckBox("エラー通知（注文拒否・取引ループエラー）")
        event_layout.addRow(self.slack_notify_error_check)

        self.slack_notify_degraded_check = QCheckBox("モデル劣化検知通知")
        event_layout.addRow(self.slack_notify_degraded_check)

        self.slack_notify_retraining_check = QCheckBox("再学習完了通知（WFO 結果含む）")
        event_layout.addRow(self.slack_notify_retraining_check)

        self.slack_notify_backtest_check = QCheckBox("バックテスト完了通知")
        event_layout.addRow(self.slack_notify_backtest_check)

        event_group.setLayout(event_layout)
        layout.addWidget(event_group)

        layout.addStretch()
        scroll.setWidget(page)
        return scroll

    def _build_profile_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)

        # アクティブプロファイル表示
        self.active_profile_label = QLabel("アクティブ: (未設定)")
        self.active_profile_label.setStyleSheet("font-size: 13px; font-weight: bold; color: #4CAF50;")
        layout.addWidget(self.active_profile_label)

        # 上部: テーブル + 詳細パネル
        split = QHBoxLayout()

        # 左: プロファイル一覧
        left = QVBoxLayout()
        left.addWidget(QLabel("保存済みプロファイル:"))
        self.profile_table = QTableWidget()
        self.profile_table.setColumnCount(4)
        self.profile_table.setHorizontalHeaderLabels(["名前", "作成日", "説明", "状態"])
        self.profile_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.profile_table.setAlternatingRowColors(True)
        self.profile_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.profile_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.profile_table.verticalHeader().setVisible(False)
        self.profile_table.setMinimumHeight(180)
        self.profile_table.itemSelectionChanged.connect(self._on_profile_selected)
        left.addWidget(self.profile_table)
        split.addLayout(left, 3)

        # 右: 詳細パネル
        right = QVBoxLayout()
        right.addWidget(QLabel("詳細:"))
        self.profile_detail_text = QTextEdit()
        self.profile_detail_text.setReadOnly(True)
        self.profile_detail_text.setMaximumHeight(180)
        right.addWidget(self.profile_detail_text)

        detail_btn_row = QHBoxLayout()
        self.profile_apply_btn = QPushButton("適用")
        self.profile_apply_btn.clicked.connect(self._on_profile_apply)
        self.profile_apply_btn.setEnabled(False)
        detail_btn_row.addWidget(self.profile_apply_btn)

        self.profile_clone_btn = QPushButton("複製")
        self.profile_clone_btn.clicked.connect(self._on_profile_clone)
        self.profile_clone_btn.setEnabled(False)
        detail_btn_row.addWidget(self.profile_clone_btn)

        self.profile_archive_btn = QPushButton("アーカイブ")
        self.profile_archive_btn.clicked.connect(self._on_profile_archive)
        self.profile_archive_btn.setEnabled(False)
        detail_btn_row.addWidget(self.profile_archive_btn)
        right.addLayout(detail_btn_row)

        split.addLayout(right, 2)
        layout.addLayout(split)

        # 下部: 新規保存
        save_group = QGroupBox("現在の設定を新規プロファイルとして保存")
        save_layout = QFormLayout()

        self.new_profile_name_edit = QLineEdit()
        self.new_profile_name_edit.setPlaceholderText("例: baseline_v1")
        save_layout.addRow("プロファイル名:", self.new_profile_name_edit)

        self.new_profile_desc_edit = QLineEdit()
        self.new_profile_desc_edit.setPlaceholderText("例: 初期安定設定")
        save_layout.addRow("説明:", self.new_profile_desc_edit)

        self.profile_save_new_btn = QPushButton("現在の設定を保存")
        self.profile_save_new_btn.clicked.connect(self._on_profile_save_new)
        save_layout.addRow(self.profile_save_new_btn)

        save_group.setLayout(save_layout)
        layout.addWidget(save_group)

        layout.addStretch()
        self._refresh_profile_table()
        return page

    def _get_db_path(self):
        from pathlib import Path
        from fxbot.config import _PROJECT_ROOT
        return _PROJECT_ROOT / self.settings.trade_logging.db_path

    def _refresh_profile_table(self) -> None:
        try:
            from fxbot.profile_manager import ProfileManager
            pm = ProfileManager(self._get_db_path())
            profiles = pm.load_profiles(include_archived=True)
            pm.close()
        except Exception as e:
            log.warning(f"プロファイル一覧取得失敗: {e}")
            return

        self._profiles_cache = profiles
        self.profile_table.setRowCount(len(profiles))
        active_pid = self.settings.active_profile_id

        for i, p in enumerate(profiles):
            name_item = QTableWidgetItem(p.get("name", ""))
            is_active = p.get("profile_id") == active_pid
            is_archived = bool(p.get("is_archived"))

            if is_active:
                name_item.setForeground(QColor("#4CAF50"))
                bold = QFont()
                bold.setBold(True)
                name_item.setFont(bold)
            if is_archived:
                italic = QFont()
                italic.setItalic(True)
                name_item.setFont(italic)
                name_item.setForeground(QColor("#888888"))

            created = (p.get("created_at") or "")[:10]
            desc = p.get("description") or ""
            status = "アクティブ" if is_active else ("アーカイブ" if is_archived else "")

            self.profile_table.setItem(i, 0, name_item)
            self.profile_table.setItem(i, 1, QTableWidgetItem(created))
            self.profile_table.setItem(i, 2, QTableWidgetItem(desc))
            self.profile_table.setItem(i, 3, QTableWidgetItem(status))

        if active_pid:
            active_name = next(
                (p["name"] for p in profiles if p["profile_id"] == active_pid), active_pid
            )
            self.active_profile_label.setText(f"アクティブ: {active_name}")
        else:
            self.active_profile_label.setText("アクティブ: (未設定)")

    def _on_profile_selected(self) -> None:
        rows = self.profile_table.selectedItems()
        has_sel = bool(rows)
        self.profile_apply_btn.setEnabled(has_sel)
        self.profile_clone_btn.setEnabled(has_sel)
        self.profile_archive_btn.setEnabled(has_sel)

        if not has_sel:
            self.profile_detail_text.clear()
            return

        idx = self.profile_table.currentRow()
        profiles = getattr(self, "_profiles_cache", [])
        if idx >= len(profiles):
            return
        p = profiles[idx]

        import json
        settings_dict = {}
        try:
            if p.get("settings_json"):
                settings_dict = json.loads(p["settings_json"])
        except Exception:
            pass

        # キー抜粋表示
        lines = [
            f"名前: {p.get('name', '')}",
            f"説明: {p.get('description', '')}",
            f"作成日: {(p.get('created_at') or '')[:19]}",
            f"更新日: {(p.get('updated_at') or '')[:19]}",
            "---",
        ]
        for section in ("trading", "risk", "market_filter"):
            sub = settings_dict.get(section, {})
            if sub:
                lines.append(f"[{section}]")
                for k, v in sub.items():
                    lines.append(f"  {k}: {v}")
        self.profile_detail_text.setPlainText("\n".join(lines))

    def _on_profile_save_new(self) -> None:
        name = self.new_profile_name_edit.text().strip()
        if not name:
            QMessageBox.warning(self, "プロファイル保存", "プロファイル名を入力してください。")
            return
        desc = self.new_profile_desc_edit.text().strip()

        try:
            from fxbot.profile_manager import ProfileManager
            pm = ProfileManager(self._get_db_path())
            profile_id, snapshot_id = pm.save_profile(name, desc, self.settings)
            pm.close()
        except Exception as e:
            QMessageBox.warning(self, "プロファイル保存", f"保存に失敗しました:\n{e}")
            return

        self.settings.active_profile_id = profile_id
        self.settings.active_snapshot_id = snapshot_id
        save_settings(self.settings)
        self.settings_changed.emit()
        self._refresh_profile_table()
        self.new_profile_name_edit.clear()
        self.new_profile_desc_edit.clear()
        QMessageBox.information(self, "プロファイル保存", f"プロファイル「{name}」を保存しました。")
        log.info(f"プロファイル新規保存: {name} ({profile_id})")

    def _on_profile_apply(self) -> None:
        idx = self.profile_table.currentRow()
        profiles = getattr(self, "_profiles_cache", [])
        if idx >= len(profiles):
            return
        p = profiles[idx]
        snapshot_id = p.get("snapshot_id")
        if snapshot_id is None:
            QMessageBox.warning(self, "適用", "スナップショットが見つかりません。")
            return

        try:
            from fxbot.profile_manager import ProfileManager
            pm = ProfileManager(self._get_db_path())
            pm.apply_profile(snapshot_id, self.settings)
            pm.close()
        except Exception as e:
            QMessageBox.warning(self, "適用", f"適用に失敗しました:\n{e}")
            return

        self.settings.active_profile_id = p["profile_id"]
        self.settings.active_snapshot_id = snapshot_id
        save_settings(self.settings)
        self._load_settings()
        self.settings_changed.emit()
        self._refresh_profile_table()
        QMessageBox.information(self, "適用", f"プロファイル「{p['name']}」を適用しました。")
        log.info(f"プロファイル適用: {p['name']} snapshot_id={snapshot_id}")

    def _on_profile_clone(self) -> None:
        idx = self.profile_table.currentRow()
        profiles = getattr(self, "_profiles_cache", [])
        if idx >= len(profiles):
            return
        p = profiles[idx]
        snapshot_id = p.get("snapshot_id")
        if snapshot_id is None:
            QMessageBox.warning(self, "複製", "スナップショットが見つかりません。")
            return

        new_name = f"{p['name']}_copy"
        try:
            from fxbot.profile_manager import ProfileManager
            import json
            pm = ProfileManager(self._get_db_path())
            snap_dict = pm.get_snapshot(snapshot_id)

            # スナップショットの設定を一時的に適用して保存
            from fxbot.config import Settings
            import dataclasses
            tmp = dataclasses.replace(self.settings)
            pm.apply_profile(snapshot_id, tmp)

            new_pid, new_sid = pm.save_profile(
                new_name, f"{p.get('description', '')} (複製)",
                tmp, base_profile_id=p["profile_id"],
            )
            pm.close()
        except Exception as e:
            QMessageBox.warning(self, "複製", f"複製に失敗しました:\n{e}")
            return

        self._refresh_profile_table()
        QMessageBox.information(self, "複製", f"「{new_name}」として複製しました。")
        log.info(f"プロファイル複製: {p['name']} → {new_name} ({new_pid})")

    def _on_profile_archive(self) -> None:
        idx = self.profile_table.currentRow()
        profiles = getattr(self, "_profiles_cache", [])
        if idx >= len(profiles):
            return
        p = profiles[idx]

        reply = QMessageBox.question(
            self, "アーカイブ確認",
            f"プロファイル「{p['name']}」をアーカイブしますか？\n（一覧から非表示になりますが削除はされません）",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        try:
            from fxbot.profile_manager import ProfileManager
            pm = ProfileManager(self._get_db_path())
            pm.archive_profile(p["profile_id"])
            pm.close()
        except Exception as e:
            QMessageBox.warning(self, "アーカイブ", f"失敗しました:\n{e}")
            return

        self._refresh_profile_table()
        log.info(f"プロファイルアーカイブ: {p['name']}")

    def _on_webhook_toggle(self, checked: bool) -> None:
        if checked:
            self.slack_webhook_edit.setEchoMode(QLineEdit.EchoMode.Normal)
            self.slack_webhook_toggle_btn.setText("隠す")
        else:
            self.slack_webhook_edit.setEchoMode(QLineEdit.EchoMode.Password)
            self.slack_webhook_toggle_btn.setText("表示")

    def _on_slack_test(self) -> None:
        """Webhook URL にテストメッセージを送信."""
        from fxbot.config import SlackNotifierConfig
        from fxbot.notifier import SlackNotifier

        url = self.slack_webhook_edit.text().strip()
        if not url:
            QMessageBox.warning(self, "Slack テスト", "Webhook URL を入力してください。")
            return

        cfg = SlackNotifierConfig(enabled=True, webhook_url=url)
        n = SlackNotifier(cfg)
        ok = n._send("🔔 fxbot3 テスト送信 — Slack 通知の設定が正常に完了しました。")
        if ok:
            QMessageBox.information(self, "Slack テスト", "テスト送信に成功しました。")
        else:
            QMessageBox.warning(self, "Slack テスト", "送信に失敗しました。\nWebhook URL を確認してください。")

    def _load_settings(self):
        s = self.settings
        self.account_combo.setCurrentText(s.active_account)
        self._update_account_fields(s.active_account)

        self.max_positions_spin.setValue(s.trading.max_positions)
        self.max_active_symbols_spin.setValue(s.trading.max_active_symbols)
        self.max_positions_per_symbol_spin.setValue(s.trading.max_positions_per_symbol)
        self.prediction_horizon_spin.setValue(s.trading.prediction_horizon)
        self.min_threshold_spin.setValue(s.trading.min_prediction_threshold)
        self.max_lot_spin.setValue(s.trading.max_lot)
        self.max_lot_balance_pct_spin.setValue(s.trading.max_lot_balance_pct)

        self.risk_per_trade_spin.setValue(s.risk.max_risk_per_trade)
        self.atr_sl_spin.setValue(s.risk.atr_sl_multiplier)
        self.atr_tp_spin.setValue(s.risk.atr_tp_multiplier)
        self.trailing_sl_check.setChecked(s.risk.trailing_sl_enabled)
        self.trailing_tp_check.setChecked(s.risk.trailing_tp_enabled)

        # モデル設定
        mode_idx = self.model_mode_combo.findText(s.model.mode)
        if mode_idx >= 0:
            self.model_mode_combo.setCurrentIndex(mode_idx)
        self.min_confidence_spin.setValue(s.trading.min_confidence)

        # 市場フィルター
        self.mf_enabled_check.setChecked(s.market_filter.enabled)
        self.mf_adx_check.setChecked(s.market_filter.use_adx_filter)
        self.mf_min_adx_spin.setValue(s.market_filter.min_adx)
        self.mf_spread_check.setChecked(s.market_filter.use_spread_filter)
        self.mf_max_spread_spin.setValue(s.market_filter.max_spread_pips)
        self.mf_volatility_check.setChecked(s.market_filter.use_volatility_filter)
        self.mf_min_atr_spin.setValue(s.market_filter.min_atr_pct)
        self.mf_max_atr_spin.setValue(s.market_filter.max_atr_pct)
        self.mf_session_check.setChecked(s.market_filter.session_only)

        # 取引ログ
        self.tl_enabled_check.setChecked(s.trade_logging.enabled)
        self.tl_db_path_edit.setText(s.trade_logging.db_path)

        # Slack 通知
        self.slack_enabled_check.setChecked(s.slack.enabled)
        self.slack_webhook_edit.setText(s.slack.webhook_url)
        self.slack_notify_entry_check.setChecked(s.slack.notify_entry)
        self.slack_notify_exit_check.setChecked(s.slack.notify_exit)
        self.slack_notify_error_check.setChecked(s.slack.notify_error)
        self.slack_notify_degraded_check.setChecked(s.slack.notify_model_degraded)
        self.slack_notify_retraining_check.setChecked(s.slack.notify_retraining_done)
        self.slack_notify_backtest_check.setChecked(s.slack.notify_backtest_done)

        # 自動再学習
        rt = s.retraining
        self.rt_enabled_check.setChecked(rt.enabled)
        self.rt_weekend_only_check.setChecked(rt.weekend_only)
        self.rt_interval_spin.setValue(rt.interval_hours)
        self.rt_wfo_check.setChecked(rt.run_wfo_before_train)
        self.rt_wfo_win_rate_spin.setValue(rt.wfo_min_win_rate)
        self.rt_wfo_sharpe_spin.setValue(rt.wfo_min_sharpe)
        self.rt_monitor_window_spin.setValue(rt.monitor_window)
        self.rt_min_win_rate_spin.setValue(rt.min_win_rate)
        self.rt_min_sharpe_spin.setValue(rt.min_sharpe)

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

    def _on_mf_enabled_changed(self, state: int) -> None:
        """マスタースイッチ切替時に即時反映・自動保存（保存ボタン不要）."""
        self.settings.market_filter.enabled = bool(state)
        save_settings(self.settings)
        label = "有効" if state else "無効"
        log.info(f"市場フィルター {label} に切替（自動保存）")

    def _save_settings(self):
        s = self.settings

        # 現在の口座設定を保存
        name = self.account_combo.currentText()
        acc = s.accounts[name]
        acc.server = self.server_edit.text()
        acc.login = self.login_edit.value()
        acc.password = self.password_edit.text()

        s.trading.max_positions = self.max_positions_spin.value()
        s.trading.max_active_symbols = self.max_active_symbols_spin.value()
        s.trading.max_positions_per_symbol = self.max_positions_per_symbol_spin.value()
        s.trading.prediction_horizon = self.prediction_horizon_spin.value()
        s.trading.min_prediction_threshold = self.min_threshold_spin.value()
        s.trading.max_lot = self.max_lot_spin.value()
        s.trading.max_lot_balance_pct = self.max_lot_balance_pct_spin.value()
        s.trading.min_confidence = self.min_confidence_spin.value()

        s.risk.max_risk_per_trade = self.risk_per_trade_spin.value()
        s.risk.atr_sl_multiplier = self.atr_sl_spin.value()
        s.risk.atr_tp_multiplier = self.atr_tp_spin.value()
        s.risk.trailing_sl_enabled = self.trailing_sl_check.isChecked()
        s.risk.trailing_tp_enabled = self.trailing_tp_check.isChecked()

        s.model.mode = self.model_mode_combo.currentText()

        s.market_filter.enabled = self.mf_enabled_check.isChecked()
        s.market_filter.use_adx_filter = self.mf_adx_check.isChecked()
        s.market_filter.min_adx = self.mf_min_adx_spin.value()
        s.market_filter.use_spread_filter = self.mf_spread_check.isChecked()
        s.market_filter.max_spread_pips = self.mf_max_spread_spin.value()
        s.market_filter.use_volatility_filter = self.mf_volatility_check.isChecked()
        s.market_filter.min_atr_pct = self.mf_min_atr_spin.value()
        s.market_filter.max_atr_pct = self.mf_max_atr_spin.value()
        s.market_filter.session_only = self.mf_session_check.isChecked()

        s.trade_logging.enabled = self.tl_enabled_check.isChecked()
        s.trade_logging.db_path = self.tl_db_path_edit.text()

        # Slack 通知
        s.slack.enabled = self.slack_enabled_check.isChecked()
        s.slack.webhook_url = self.slack_webhook_edit.text().strip()
        s.slack.notify_entry = self.slack_notify_entry_check.isChecked()
        s.slack.notify_exit = self.slack_notify_exit_check.isChecked()
        s.slack.notify_error = self.slack_notify_error_check.isChecked()
        s.slack.notify_model_degraded = self.slack_notify_degraded_check.isChecked()
        s.slack.notify_retraining_done = self.slack_notify_retraining_check.isChecked()
        s.slack.notify_backtest_done = self.slack_notify_backtest_check.isChecked()

        # 自動再学習
        s.retraining.enabled = self.rt_enabled_check.isChecked()
        s.retraining.weekend_only = self.rt_weekend_only_check.isChecked()
        s.retraining.interval_hours = self.rt_interval_spin.value()
        s.retraining.run_wfo_before_train = self.rt_wfo_check.isChecked()
        s.retraining.wfo_min_win_rate = self.rt_wfo_win_rate_spin.value()
        s.retraining.wfo_min_sharpe = self.rt_wfo_sharpe_spin.value()
        s.retraining.monitor_window = self.rt_monitor_window_spin.value()
        s.retraining.min_win_rate = self.rt_min_win_rate_spin.value()
        s.retraining.min_sharpe = self.rt_min_sharpe_spin.value()

        save_settings(self.settings)
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
