"""matplotlib in Qt チャートウィジェット."""

from __future__ import annotations

import matplotlib
matplotlib.use("QtAgg")

import matplotlib.font_manager as _fm

_JP_FONTS = ["Meiryo", "Yu Gothic", "MS Gothic", "IPAexGothic", "Noto Sans CJK JP"]
_available = {f.name for f in _fm.fontManager.ttflist}
for _font in _JP_FONTS:
    if _font in _available:
        matplotlib.rcParams["font.family"] = _font
        break

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

    def plot_multi_equity(
        self,
        equity_curves: dict[str, pd.Series],
        initial_balance: float = 1_000_000,
        title: str = "比較エクイティカーブ",
    ) -> None:
        """複数エクイティカーブを1グラフに重ねて描画."""
        import pandas as pd
        self.figure.clear()
        ax = self.figure.add_subplot(111)
        colors = ["#9E9E9E", "#03A9F4", "#4CAF50", "#FF9800"]
        linestyles = ["--", "-", "-", "-"]
        for idx, (label, equity) in enumerate(equity_curves.items()):
            if equity is None or equity.empty:
                continue
            ax.plot(equity.index, equity.values,
                    color=colors[idx % 4], linewidth=1.5,
                    linestyle=linestyles[idx % 4], label=label)
        ax.axhline(y=initial_balance, color="gray", linestyle=":", alpha=0.4)
        ax.set_title(title, fontsize=12)
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

    def plot_candlestick(self, df, hold_timestamps: list[str] | None = None, symbol: str = ""):
        """ローソク足チャートを描画（HOLDマーカー付き）.

        mplfinance が利用可能な場合は ax= パターンで既存 Figure に描画。
        未インストール時は matplotlib 折れ線でフォールバック。

        Args:
            df: OHLCV DataFrame（index=DatetimeIndex, columns=open/high/low/close）
            hold_timestamps: HOLDが発生したバーの ISO 文字列タイムスタンプリスト
            symbol: シンボル名（タイトル表示用）
        """
        self.figure.clear()

        if df is None or df.empty:
            ax = self.figure.add_subplot(111)
            ax.text(0.5, 0.5, "データなし", ha="center", va="center", transform=ax.transAxes)
            self.canvas.draw()
            return

        import pandas as pd

        # カラム名を小文字に統一
        df = df.copy()
        df.columns = [c.lower() for c in df.columns]

        required = {"open", "high", "low", "close"}
        if not required.issubset(set(df.columns)):
            ax = self.figure.add_subplot(111)
            ax.text(0.5, 0.5, "OHLCカラムが見つかりません",
                    ha="center", va="center", transform=ax.transAxes)
            self.canvas.draw()
            return

        # DatetimeIndex に変換
        if not isinstance(df.index, pd.DatetimeIndex):
            try:
                df.index = pd.to_datetime(df.index)
            except Exception:
                pass

        title = f"{symbol} ローソク足（直近{len(df)}本）" if symbol else f"ローソク足（直近{len(df)}本）"

        try:
            import mplfinance as mpf

            ax = self.figure.add_subplot(111)
            # ax= パターン: volume=False で単一 Axes に描画
            mpf.plot(df, type="candle", ax=ax, volume=False, style="charles")

            # HOLD マーカーを Axes に直接追加
            # mplfinance は数値 x 軸（0, 1, 2...）を使うので iloc を x 座標として使用
            if hold_timestamps:
                n = len(df)
                index_tz = getattr(df.index, "tz", None)
                plotted = set()
                first_marker = True
                for ts_str in hold_timestamps:
                    try:
                        ts = pd.to_datetime(ts_str)
                        # df.index の timezone と型を合わせる
                        if index_tz is not None and ts.tzinfo is None:
                            ts = ts.tz_localize("UTC")
                        elif index_tz is None and ts.tzinfo is not None:
                            ts = ts.tz_localize(None)
                        iloc = df.index.get_indexer([ts], method="nearest")[0]
                        if 0 <= iloc < n and iloc not in plotted:
                            plotted.add(iloc)
                            y_pos = df["high"].iloc[iloc] * 1.001
                            ax.scatter(iloc, y_pos, color="red", marker="v",
                                       s=80, zorder=5,
                                       label="HOLD" if first_marker else "")
                            first_marker = False
                    except Exception:
                        continue

            ax.set_title(title, fontsize=10)
            self.figure.tight_layout()
            self.canvas.draw()

        except ImportError:
            # mplfinance 未インストール時は折れ線でフォールバック
            self._plot_candlestick_fallback(df, hold_timestamps, title)
        except Exception:
            self._plot_candlestick_fallback(df, hold_timestamps, title)

    def _plot_candlestick_fallback(self, df, hold_timestamps: list[str] | None, title: str):
        """mplfinance なしの折れ線フォールバック描画."""
        import pandas as pd

        self.figure.clear()
        ax = self.figure.add_subplot(111)
        ax.plot(df.index, df["close"], color="#2196F3", linewidth=1, label="終値")

        if hold_timestamps:
            index_tz = getattr(df.index, "tz", None)
            first = True
            for ts_str in hold_timestamps:
                try:
                    ts = pd.to_datetime(ts_str)
                    if index_tz is not None and ts.tzinfo is None:
                        ts = ts.tz_localize("UTC")
                    elif index_tz is None and ts.tzinfo is not None:
                        ts = ts.tz_localize(None)
                    idx = df.index.get_indexer([ts], method="nearest")[0]
                    if 0 <= idx < len(df):
                        ax.scatter(df.index[idx], df["close"].iloc[idx],
                                   color="red", marker="v", s=80, zorder=5,
                                   label="HOLD" if first else "")
                        first = False
                except Exception:
                    continue

        ax.set_title(title, fontsize=10)
        ax.grid(True, alpha=0.3)
        ax.legend(fontsize=8)
        self.figure.tight_layout()
        self.canvas.draw()
