"""matplotlib in Qt チャートウィジェット."""

from __future__ import annotations

import matplotlib
matplotlib.use("QtAgg")

from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure
from matplotlib.ticker import FuncFormatter

from PySide6.QtWidgets import QVBoxLayout, QWidget


class ChartWidget(QWidget):
    """matplotlibチャートを埋め込むウィジェット."""

    def __init__(self, parent=None, figsize=(10, 6)):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self.figure = Figure(figsize=figsize, dpi=100)
        self.canvas = FigureCanvas(self.figure)
        layout.addWidget(self.canvas)

    def clear(self):
        self.figure.clear()
        self.canvas.draw()

    def plot_equity(self, equity_series, initial_balance: float = 1_000_000):
        """エクイティカーブを描画."""
        self.figure.clear()
        ax = self.figure.add_subplot(111)
        ax.plot(equity_series.index, equity_series.values, color="#2196F3", linewidth=1)

        # 初期残高の水平点線
        ax.axhline(y=initial_balance, color="gray", linestyle="--", alpha=0.5, label=f"初期残高 ¥{initial_balance:,.0f}")

        # 最終損益をタイトルに表示
        final_value = equity_series.iloc[-1] if len(equity_series) > 0 else initial_balance
        pnl = final_value - initial_balance
        sign = "+" if pnl >= 0 else ""
        ax.set_title(f"資金曲線 (損益: {sign}¥{pnl:,.0f})", fontsize=12)

        ax.set_xlabel("Date")
        ax.set_ylabel("Equity (¥)")
        ax.yaxis.set_major_formatter(FuncFormatter(lambda v, _: f"¥{v:,.0f}"))
        ax.grid(True, alpha=0.3)
        ax.legend(loc="upper left", fontsize=8)
        self.figure.tight_layout()
        self.canvas.draw()

    def plot_shap_importance(self, importance_df, top_n=20):
        """SHAP特徴量重要度を描画."""
        self.figure.clear()
        ax = self.figure.add_subplot(111)

        top = importance_df.head(top_n).sort_values("importance")
        ax.barh(top["feature"], top["importance"], color="#4CAF50")
        ax.set_title(f"Top {top_n} Feature Importance (SHAP)", fontsize=12)
        ax.set_xlabel("Mean |SHAP value|")
        self.figure.tight_layout()
        self.canvas.draw()

    def plot_drawdown(self, equity_series):
        """ドローダウンを描画."""
        self.figure.clear()
        ax = self.figure.add_subplot(111)

        peak = equity_series.cummax()
        dd_pct = (equity_series - peak) / peak * 100

        ax.fill_between(dd_pct.index, dd_pct.values, 0, color="#F44336", alpha=0.3)
        ax.plot(dd_pct.index, dd_pct.values, color="#F44336", linewidth=0.5)
        ax.set_title("Drawdown (%)", fontsize=12)
        ax.set_xlabel("Date")
        ax.set_ylabel("Drawdown %")
        ax.grid(True, alpha=0.3)
        self.figure.tight_layout()
        self.canvas.draw()
