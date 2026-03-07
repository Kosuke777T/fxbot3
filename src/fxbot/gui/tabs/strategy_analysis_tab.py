"""戦略分析タブ."""

from __future__ import annotations

from PySide6.QtCore import QTimer, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTabWidget,
    QScrollArea,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
    QHeaderView,
)

from fxbot.config import Settings
from fxbot.logger import get_logger

log = get_logger(__name__)


class StrategyAnalysisTab(QWidget):
    """売買戦略の判断と成績を分析するタブ."""

    jump_requested = Signal(str)    # "market_filter" | "settings"
    warn_count_changed = Signal(int)

    def __init__(self, settings: Settings, parent=None):
        super().__init__(parent)
        self.settings = settings
        self._active_symbols: list[str] = list(settings.trading.active_symbols)
        self._prev_summary: dict | None = None
        self._init_ui()

        self._timer = QTimer(self)
        self._timer.timeout.connect(self.refresh)
        self._timer.start(15000)
        self.refresh()

    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)

        header_layout = QHBoxLayout()
        self.symbols_label = QLabel("対象ペア: ---")
        self.symbols_label.setStyleSheet("font-size: 14px; font-weight: bold;")
        header_layout.addWidget(self.symbols_label)
        header_layout.addStretch()
        self.refresh_btn = QPushButton("更新")
        self.refresh_btn.clicked.connect(self.refresh)
        header_layout.addWidget(self.refresh_btn)
        layout.addLayout(header_layout)

        self.message_label = QLabel("")
        self.message_label.setStyleSheet("font-size: 14px; color: gray;")
        layout.addWidget(self.message_label)

        summary_group = QGroupBox("戦略サマリー")
        summary_layout = QHBoxLayout(summary_group)
        self.eval_label = QLabel("総判定数: ---")
        self.entry_label = QLabel("約定数: ---")
        self.hold_label = QLabel("HOLD数: ---")
        self.block_label = QLabel("見送り: ---")
        self.fail_label = QLabel("注文失敗: ---")
        for label in (
            self.eval_label,
            self.entry_label,
            self.hold_label,
            self.block_label,
            self.fail_label,
        ):
            label.setStyleSheet("font-size: 14px;")
            summary_layout.addWidget(label)
        summary_layout.addStretch()
        layout.addWidget(summary_group)

        self.detail_tabs = QTabWidget()

        self.action_table = self._create_table(["判定", "件数", "約定数", "注文失敗"])
        self.hold_reason_table = self._create_table(["HOLD理由", "件数"])
        self.filter_table = self._create_table(["フィルター", "有効回数", "通過回数", "ブロック回数", "通過率"])
        self.exit_reason_table = self._create_table(["決済理由", "件数", "合計損益", "平均損益", "勝率"])
        self.direction_table = self._create_table(["方向", "件数", "合計損益", "平均損益", "勝率"])
        self.hour_table = self._create_table(["時間帯", "件数", "合計損益", "平均損益", "勝率"])
        self.prediction_bucket_table = self._create_table(["予測帯", "件数", "合計損益", "平均損益", "勝率"])
        self.model_version_table = self._create_table(["モデル", "件数", "合計損益", "平均損益", "勝率"])
        self.recent_events_table = self._create_table(
            ["時刻", "シンボル", "判定", "HOLD理由", "見送り理由", "予測値", "信頼度", "ブロックフィルター", "プロファイル"]
        )

        decision_tab = QWidget()
        decision_layout = QVBoxLayout(decision_tab)
        decision_layout.addWidget(self._wrap_group("判定内訳", self.action_table))
        decision_layout.addWidget(self._wrap_group("HOLD理由", self.hold_reason_table))
        decision_layout.addWidget(self._wrap_group("フィルター通過率", self.filter_table))
        decision_layout.addStretch()

        performance_tab = QWidget()
        performance_layout = QVBoxLayout(performance_tab)
        self.performance_tabs = QTabWidget()

        exit_perf_tab = QWidget()
        exit_perf_layout = QVBoxLayout(exit_perf_tab)
        exit_perf_layout.addWidget(self._wrap_group("決済理由別成績", self.exit_reason_table))
        exit_perf_layout.addWidget(self._wrap_group("BUY/SELL別成績", self.direction_table))
        exit_perf_layout.addStretch()

        timing_perf_tab = QWidget()
        timing_perf_layout = QVBoxLayout(timing_perf_tab)
        timing_perf_layout.addWidget(self._wrap_group("時間帯別成績", self.hour_table))
        timing_perf_layout.addWidget(self._wrap_group("予測値帯別成績", self.prediction_bucket_table))
        timing_perf_layout.addStretch()

        model_perf_tab = QWidget()
        model_perf_layout = QVBoxLayout(model_perf_tab)
        model_perf_layout.addWidget(self._wrap_group("モデル別成績", self.model_version_table))
        model_perf_layout.addStretch()

        self.performance_tabs.addTab(exit_perf_tab, "出口・方向")
        self.performance_tabs.addTab(timing_perf_tab, "時間帯・予測値")
        self.performance_tabs.addTab(model_perf_tab, "モデル別")
        performance_layout.addWidget(self.performance_tabs)

        recent_tab = QWidget()
        recent_layout = QVBoxLayout(recent_tab)
        recent_layout.addWidget(self._wrap_group("直近戦略イベント", self.recent_events_table))
        recent_layout.addStretch()

        advice_tab = QWidget()
        advice_layout = QVBoxLayout(advice_tab)
        self.advice_inner_tabs = QTabWidget()
        advice_layout.addWidget(self.advice_inner_tabs)

        self.detail_tabs.addTab(decision_tab, "判定・フィルター")
        self.detail_tabs.addTab(performance_tab, "成績分析")
        self.detail_tabs.addTab(recent_tab, "直近イベント")
        self.detail_tabs.addTab(advice_tab, "戦略アドバイザー")
        layout.addWidget(self.detail_tabs)

    @staticmethod
    def _create_table(headers: list[str]) -> QTableWidget:
        table = QTableWidget()
        table.setColumnCount(len(headers))
        table.setHorizontalHeaderLabels(headers)
        table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        table.setAlternatingRowColors(True)
        table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        table.verticalHeader().setVisible(False)
        table.setWordWrap(False)
        table.setMinimumHeight(220)
        return table

    @staticmethod
    def _wrap_group(title: str, widget: QWidget) -> QGroupBox:
        group = QGroupBox(title)
        group_layout = QVBoxLayout(group)
        group_layout.addWidget(widget)
        return group

    def refresh_symbols(self, symbols: list[str]) -> None:
        self._active_symbols = list(symbols)
        self.refresh()

    def refresh(self) -> None:
        if not self.settings.trade_logging.enabled:
            self.symbols_label.setText("対象ペア: ---")
            self.message_label.setText("取引ログが無効です。設定タブで有効にしてください。")
            self._clear_all_tables()
            return

        symbols = self._active_symbols or list(self.settings.trading.active_symbols)
        self.symbols_label.setText(f"対象ペア: {' / '.join(symbols) if symbols else '---'}")

        db_path = self.settings.resolve_path(self.settings.trade_logging.db_path)
        if not db_path.exists():
            self.message_label.setText("取引DBがまだ作成されていません。")
            self._clear_all_tables()
            return

        try:
            from fxbot.trade_logger import TradeLogger

            tl = TradeLogger(db_path)
            summary = tl.get_strategy_summary(symbols)
            action_rows = tl.get_action_breakdown(symbols)
            hold_rows = tl.get_hold_reason_breakdown(symbols)
            filter_rows = tl.get_filter_pass_rates(symbols)
            exit_rows = tl.get_exit_reason_performance(symbols)
            direction_rows = tl.get_direction_performance(symbols)
            hour_rows = tl.get_hourly_performance(symbols)
            bucket_rows = tl.get_prediction_bucket_performance(symbols)
            model_rows = tl.get_model_version_performance(symbols)
            symbol_rows = tl.get_symbol_performance(symbols)
            recent_rows = tl.get_recent_analysis_events(symbols, 20)
            tl.close()

            if summary["eval_count"] == 0:
                self.message_label.setText(
                    "分析イベントがまだありません。ライブ取引を実行すると戦略判断ログが蓄積されます。"
                )
            else:
                self.message_label.setText("")

            self.eval_label.setText(f"総判定数: {summary['eval_count']}")
            self.entry_label.setText(
                f"約定数: {summary['entered_count']} ({summary['entry_rate']:.1%})"
            )
            self.hold_label.setText(f"HOLD数: {summary['hold_count']}")
            self.block_label.setText(
                f"見送り: 上限 {summary['position_blocked']} / 劣化 {summary['model_blocked']}"
            )
            self.fail_label.setText(f"注文失敗: {summary['order_failed']}")

            self._fill_action_table(action_rows)
            self._fill_count_table(self.hold_reason_table, hold_rows, ("hold_reason", "count"))
            self._fill_filter_table(filter_rows)
            self._fill_performance_table(self.exit_reason_table, exit_rows, "exit_reason")
            self._fill_performance_table(self.direction_table, direction_rows, "direction")
            self._fill_performance_table(self.hour_table, hour_rows, "hour_bucket")
            self._fill_performance_table(self.prediction_bucket_table, bucket_rows, "bucket")
            self._fill_performance_table(self.model_version_table, model_rows, "model_version")
            self._fill_recent_events_table(recent_rows)
            self._fill_advice_tab(
                symbols=symbols,
                summary=summary,
                action_rows=action_rows,
                hold_rows=hold_rows,
                filter_rows=filter_rows,
                exit_rows=exit_rows,
                direction_rows=direction_rows,
                hour_rows=hour_rows,
                bucket_rows=bucket_rows,
                model_rows=model_rows,
                symbol_rows=symbol_rows,
                db_path=db_path,
            )
            self._prev_summary = dict(summary)

        except Exception as e:
            log.warning(f"戦略分析タブ更新エラー: {e}")
            self.message_label.setText(f"分析データ取得エラー: {e}")
            self._clear_all_tables()

    def _clear_all_tables(self) -> None:
        for table in (
            self.action_table,
            self.hold_reason_table,
            self.filter_table,
            self.exit_reason_table,
            self.direction_table,
            self.hour_table,
            self.prediction_bucket_table,
            self.model_version_table,
            self.recent_events_table,
        ):
            table.setRowCount(0)
        self._clear_advice_inner_tabs()

    def _fill_action_table(self, rows: list[dict]) -> None:
        self.action_table.setRowCount(len(rows))
        for i, row in enumerate(rows):
            self.action_table.setItem(i, 0, QTableWidgetItem(str(row.get("action", "")).upper()))
            self.action_table.setItem(i, 1, QTableWidgetItem(str(int(row.get("count", 0) or 0))))
            self.action_table.setItem(i, 2, QTableWidgetItem(str(int(row.get("entered_count", 0) or 0))))
            self.action_table.setItem(i, 3, QTableWidgetItem(str(int(row.get("order_failed", 0) or 0))))

    @staticmethod
    def _fill_count_table(table: QTableWidget, rows: list[dict], keys: tuple[str, str]) -> None:
        table.setRowCount(len(rows))
        left_key, right_key = keys
        for i, row in enumerate(rows):
            table.setItem(i, 0, QTableWidgetItem(str(row.get(left_key, ""))))
            table.setItem(i, 1, QTableWidgetItem(str(int(row.get(right_key, 0) or 0))))

    def _fill_filter_table(self, rows: list[dict]) -> None:
        self.filter_table.setRowCount(len(rows))
        for i, row in enumerate(rows):
            self.filter_table.setItem(i, 0, QTableWidgetItem(str(row.get("display_name", ""))))
            self.filter_table.setItem(i, 1, QTableWidgetItem(str(int(row.get("enabled_count", 0) or 0))))
            self.filter_table.setItem(i, 2, QTableWidgetItem(str(int(row.get("pass_count", 0) or 0))))
            self.filter_table.setItem(i, 3, QTableWidgetItem(str(int(row.get("block_count", 0) or 0))))
            rate = row.get("pass_rate")
            rate_text = f"{rate:.1%}" if rate is not None else "---"
            rate_item = QTableWidgetItem(rate_text)
            if rate is not None:
                rate_item.setForeground(QColor("#4CAF50") if rate >= 0.5 else QColor("#F44336"))
            self.filter_table.setItem(i, 4, rate_item)

    def _fill_performance_table(self, table: QTableWidget, rows: list[dict], label_key: str) -> None:
        table.setRowCount(len(rows))
        for i, row in enumerate(rows):
            table.setItem(i, 0, QTableWidgetItem(str(row.get(label_key, ""))))
            table.setItem(i, 1, QTableWidgetItem(str(int(row.get("count", 0) or 0))))

            total_pnl = row.get("total_pnl")
            total_item = QTableWidgetItem(f"{(total_pnl or 0):+,.0f}")
            total_item.setForeground(QColor("#4CAF50") if (total_pnl or 0) >= 0 else QColor("#F44336"))
            table.setItem(i, 2, total_item)

            avg_pnl = row.get("avg_pnl")
            avg_item = QTableWidgetItem(f"{(avg_pnl or 0):+,.0f}")
            avg_item.setForeground(QColor("#4CAF50") if (avg_pnl or 0) >= 0 else QColor("#F44336"))
            table.setItem(i, 3, avg_item)

            win_rate = row.get("win_rate")
            wr_text = f"{win_rate:.1%}" if win_rate is not None else "---"
            wr_item = QTableWidgetItem(wr_text)
            if win_rate is not None:
                wr_item.setForeground(QColor("#4CAF50") if win_rate >= 0.5 else QColor("#F44336"))
            table.setItem(i, 4, wr_item)

    def _fill_recent_events_table(self, rows: list[dict]) -> None:
        self.recent_events_table.setRowCount(len(rows))
        for i, row in enumerate(rows):
            self.recent_events_table.setItem(i, 0, QTableWidgetItem(str(row.get("timestamp", ""))[:19]))
            self.recent_events_table.setItem(i, 1, QTableWidgetItem(str(row.get("symbol", ""))))
            action = str(row.get("action", "")).upper()
            action_item = QTableWidgetItem(action)
            if action == "BUY":
                action_item.setForeground(QColor("#4CAF50"))
            elif action == "SELL":
                action_item.setForeground(QColor("#F44336"))
            self.recent_events_table.setItem(i, 2, action_item)
            self.recent_events_table.setItem(i, 3, QTableWidgetItem(str(row.get("hold_reason") or "---")))
            self.recent_events_table.setItem(i, 4, QTableWidgetItem(str(row.get("skip_reason") or "---")))
            self.recent_events_table.setItem(i, 5, QTableWidgetItem(f"{float(row.get('prediction') or 0.0):.6f}"))
            self.recent_events_table.setItem(i, 6, QTableWidgetItem(f"{float(row.get('confidence') or 0.0):.3f}"))
            blocked = row.get("blocked_filters") or []
            self.recent_events_table.setItem(i, 7, QTableWidgetItem(", ".join(blocked) if blocked else "---"))
            self.recent_events_table.setItem(i, 8, QTableWidgetItem(str(row.get("profile_id") or "---")))

    def _fill_advice_tab(
        self,
        *,
        symbols: list[str],
        summary: dict,
        action_rows: list[dict],
        hold_rows: list[dict],
        filter_rows: list[dict],
        exit_rows: list[dict],
        direction_rows: list[dict],
        hour_rows: list[dict],
        bucket_rows: list[dict],
        model_rows: list[dict],
        symbol_rows: list[dict],
        db_path,
    ) -> None:
        from fxbot.analysis.strategy_advisor import generate_strategy_advice

        self._clear_advice_inner_tabs()

        # --- 全体タブ ---
        overall, advices = generate_strategy_advice(
            symbols=symbols,
            summary=summary,
            action_rows=action_rows,
            hold_rows=hold_rows,
            filter_rows=filter_rows,
            exit_rows=exit_rows,
            direction_rows=direction_rows,
            hour_rows=hour_rows,
            bucket_rows=bucket_rows,
            model_rows=model_rows,
            symbol_rows=symbol_rows,
            prev_summary=self._prev_summary,
        )
        panel, summary_lbl, cards_layout = self._make_advice_panel()
        self._populate_advice_panel(summary_lbl, cards_layout, overall, advices)
        self.advice_inner_tabs.addTab(panel, "全体")

        warn_count = sum(1 for a in advices if a.severity == "warn")

        # --- ペア別タブ ---
        if len(symbols) > 1:
            try:
                from fxbot.trade_logger import TradeLogger
                tl = TradeLogger(db_path)
                for sym in symbols:
                    sym_summary = tl.get_strategy_summary([sym])
                    sym_overall, sym_advices = generate_strategy_advice(
                        symbols=[sym],
                        summary=sym_summary,
                        action_rows=tl.get_action_breakdown([sym]),
                        hold_rows=tl.get_hold_reason_breakdown([sym]),
                        filter_rows=tl.get_filter_pass_rates([sym]),
                        exit_rows=tl.get_exit_reason_performance([sym]),
                        direction_rows=tl.get_direction_performance([sym]),
                        hour_rows=tl.get_hourly_performance([sym]),
                        bucket_rows=tl.get_prediction_bucket_performance([sym]),
                        model_rows=tl.get_model_version_performance([sym]),
                        symbol_rows=tl.get_symbol_performance([sym]),
                    )
                    sym_panel, sym_lbl, sym_cards = self._make_advice_panel()
                    self._populate_advice_panel(sym_lbl, sym_cards, sym_overall, sym_advices)
                    self.advice_inner_tabs.addTab(sym_panel, sym)
                tl.close()
            except Exception as e:
                log.warning(f"ペア別アドバイス生成エラー: {e}")

        self.warn_count_changed.emit(warn_count)

    def _make_advice_panel(self) -> tuple[QWidget, QLabel, QVBoxLayout]:
        """総評ラベル + カードスクロールエリアを含むパネルを生成."""
        panel = QWidget()
        v = QVBoxLayout(panel)
        summary_lbl = QLabel("総評: ---")
        summary_lbl.setWordWrap(True)
        summary_lbl.setStyleSheet("font-size: 14px; font-weight: bold;")
        v.addWidget(self._wrap_group("総評", summary_lbl))
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        container = QWidget()
        cards_layout = QVBoxLayout(container)
        cards_layout.setContentsMargins(0, 0, 0, 0)
        cards_layout.setSpacing(10)
        scroll.setWidget(container)
        v.addWidget(scroll)
        return panel, summary_lbl, cards_layout

    def _populate_advice_panel(
        self,
        summary_lbl: QLabel,
        cards_layout: QVBoxLayout,
        overall: str,
        advices: list,
    ) -> None:
        summary_lbl.setText(f"総評: {overall}")
        if not advices:
            cards_layout.addWidget(self._create_advice_card(
                severity="info",
                title="アドバイスなし",
                message="現時点では表示できる助言がありません。",
                evidence="データ蓄積後に自動表示されます。",
                action_tab=None,
            ))
        else:
            for advice in advices:
                cards_layout.addWidget(self._create_advice_card(
                    severity=advice.severity,
                    title=advice.title,
                    message=advice.message,
                    evidence=advice.evidence,
                    action_tab=advice.action_tab,
                ))
        cards_layout.addStretch()

    def _clear_advice_inner_tabs(self) -> None:
        while self.advice_inner_tabs.count():
            widget = self.advice_inner_tabs.widget(0)
            self.advice_inner_tabs.removeTab(0)
            if widget is not None:
                widget.deleteLater()

    def _create_advice_card(
        self,
        *,
        severity: str,
        title: str,
        message: str,
        evidence: str,
        action_tab: str | None = None,
    ) -> QGroupBox:
        color_map = {
            "warn": "#F44336",
            "good": "#4CAF50",
            "info": "#2196F3",
        }
        color = color_map.get(severity, "#607D8B")

        group = QGroupBox(title)
        group.setStyleSheet(f"QGroupBox {{ font-weight: bold; border: 1px solid {color}; margin-top: 8px; }}")
        layout = QVBoxLayout(group)

        severity_label = QLabel(f"重要度: {severity.upper()}")
        severity_label.setStyleSheet(f"color: {color}; font-weight: bold;")
        layout.addWidget(severity_label)

        message_label = QLabel(message)
        message_label.setWordWrap(True)
        layout.addWidget(message_label)

        evidence_label = QLabel(f"根拠: {evidence}")
        evidence_label.setWordWrap(True)
        evidence_label.setStyleSheet("color: gray;")
        layout.addWidget(evidence_label)

        if action_tab is not None:
            label_map = {"market_filter": "市場フィルターを開く", "settings": "設定を開く"}
            btn_label = label_map.get(action_tab, "設定を開く")
            btn = QPushButton(btn_label)
            btn.setStyleSheet(f"QPushButton {{ color: {color}; border: 1px solid {color}; padding: 2px 8px; }}")
            btn.clicked.connect(lambda: self.jump_requested.emit(action_tab))
            layout.addWidget(btn)

        return group
