"""通貨ペア別成績タブ."""

from __future__ import annotations

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from fxbot.config import Settings
from fxbot.logger import get_logger

log = get_logger(__name__)


class PairPerformanceTab(QWidget):
    """選択中通貨ペアごとの成績を横並び表示."""

    def __init__(self, settings: Settings, parent=None):
        super().__init__(parent)
        self.settings = settings
        self._active_symbols: list[str] = list(self.settings.trading.active_symbols)
        self._init_ui()

        self.update_timer = QTimer(self)
        self.update_timer.timeout.connect(self.refresh)
        self.update_timer.start(15000)

        self.refresh()

    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)

        header_layout = QHBoxLayout()
        self.summary_label = QLabel("選択中ペア: ---")
        self.summary_label.setStyleSheet("font-size: 14px; font-weight: bold;")
        header_layout.addWidget(self.summary_label)
        header_layout.addStretch()

        self.refresh_btn = QPushButton("更新")
        self.refresh_btn.clicked.connect(self.refresh)
        header_layout.addWidget(self.refresh_btn)
        layout.addLayout(header_layout)

        self.message_label = QLabel("")
        self.message_label.setStyleSheet("font-size: 14px; color: gray;")
        layout.addWidget(self.message_label)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        self._content = QWidget()
        self._cards_layout = QHBoxLayout(self._content)
        self._cards_layout.setContentsMargins(0, 0, 0, 0)
        self._cards_layout.setSpacing(12)
        self.scroll.setWidget(self._content)
        layout.addWidget(self.scroll)

    def refresh_symbols(self, symbols: list[str]) -> None:
        """表示対象シンボルを更新."""
        self._active_symbols = list(symbols)
        self.refresh()

    def refresh(self) -> None:
        """DBから通貨ペア別成績を再取得して表示."""
        self._clear_cards()

        if not self.settings.trade_logging.enabled:
            self.summary_label.setText("選択中ペア: ---")
            self.message_label.setText("取引ログが無効です。設定タブで有効にしてください。")
            return

        symbols = self._active_symbols or list(self.settings.trading.active_symbols)
        if not symbols:
            self.summary_label.setText("選択中ペア: 0")
            self.message_label.setText("通貨ペアタブで表示したいペアを選択してください。")
            return

        db_path = self.settings.resolve_path(self.settings.trade_logging.db_path)
        if not db_path.exists():
            self.summary_label.setText(f"選択中ペア: {len(symbols)}")
            self.message_label.setText("取引DBがまだ作成されていません。")
            return

        self.summary_label.setText(f"選択中ペア: {len(symbols)}  ({' / '.join(symbols)})")
        self.message_label.setText("")

        try:
            from fxbot.trade_logger import TradeLogger

            tl = TradeLogger(db_path)
            performance = tl.get_symbol_performance(symbols)
            tl.close()

            for perf in performance:
                self._cards_layout.addWidget(self._create_symbol_card(perf))
            self._cards_layout.addStretch()
        except Exception as e:
            log.warning(f"通貨ペア別成績の更新エラー: {e}")
            self.message_label.setText(f"成績取得エラー: {e}")

    def _clear_cards(self) -> None:
        while self._cards_layout.count():
            item = self._cards_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

    def _create_symbol_card(self, perf: dict) -> QWidget:
        card = QGroupBox(perf["symbol"])
        card.setMinimumWidth(280)

        layout = QVBoxLayout(card)

        closed = perf["closed_trades"]
        total = perf["total_trades"]
        open_trades = perf["open_trades"]
        win_rate = perf["win_rate"]
        total_pnl = perf["total_pnl"]
        avg_pnl = perf["avg_pnl"]
        best_pnl = perf["best_pnl"]
        worst_pnl = perf["worst_pnl"]
        avg_win = perf["avg_win"]
        avg_loss = perf["avg_loss"]
        last_pnl = perf["last_pnl"]
        last_reason = perf["last_exit_reason"] or ("open" if total > 0 else "---")
        last_direction = (perf["last_direction"] or "---").upper()
        last_time = (perf["last_time"] or "---")[:19]

        layout.addWidget(self._make_label(f"総取引数: {total}件"))
        layout.addWidget(self._make_label(f"決済済: {closed}件 / 未決済: {open_trades}件"))

        win_rate_label = self._make_label(f"勝率: {win_rate:.1%}" if closed > 0 else "勝率: ---")
        if closed > 0:
            win_rate_label.setStyleSheet(
                f"font-size: 14px; color: {'#4CAF50' if win_rate >= 0.5 else '#F44336'};"
            )
        layout.addWidget(win_rate_label)

        total_pnl_label = self._make_label(f"合計損益: {total_pnl:+,.0f}")
        total_pnl_label.setStyleSheet(
            f"font-size: 14px; font-weight: bold; color: {'#4CAF50' if total_pnl >= 0 else '#F44336'};"
        )
        layout.addWidget(total_pnl_label)

        layout.addWidget(self._make_label(
            f"平均損益: {avg_pnl:+,.0f}" if avg_pnl is not None else "平均損益: ---"
        ))
        layout.addWidget(self._make_label(
            f"最大利益: {best_pnl:+,.0f}" if best_pnl is not None else "最大利益: ---"
        ))
        layout.addWidget(self._make_label(
            f"最大損失: {worst_pnl:+,.0f}" if worst_pnl is not None else "最大損失: ---"
        ))
        layout.addWidget(self._make_label(
            f"平均利益: {avg_win:+,.0f}" if avg_win is not None else "平均利益: ---"
        ))
        layout.addWidget(self._make_label(
            f"平均損失: {avg_loss:+,.0f}" if avg_loss is not None else "平均損失: ---"
        ))

        last_result = self._make_label(
            f"直近結果: {last_direction} / {last_reason} / {last_pnl:+,.0f}"
            if last_pnl is not None else f"直近結果: {last_direction} / {last_reason}"
        )
        if last_pnl is not None:
            last_result.setStyleSheet(
                f"font-size: 14px; color: {'#4CAF50' if last_pnl >= 0 else '#F44336'};"
            )
        layout.addWidget(last_result)
        layout.addWidget(self._make_label(f"最終更新: {last_time}"))
        layout.addStretch()
        return card

    @staticmethod
    def _make_label(text: str) -> QLabel:
        label = QLabel(text)
        label.setStyleSheet("font-size: 14px;")
        return label
