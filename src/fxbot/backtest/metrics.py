"""パフォーマンス指標: Sharpe, Sortino, 最大DD, 勝率, PF, 月次リターン."""

from __future__ import annotations

import numpy as np
import pandas as pd


def calc_sharpe(returns: pd.Series, periods_per_year: float = 252 * 24 * 12) -> float:
    """年率シャープレシオ（M5基準 = 252日 * 24h * 12本/h）."""
    if returns.std() == 0:
        return 0.0
    return float(returns.mean() / returns.std() * np.sqrt(periods_per_year))


def calc_sortino(returns: pd.Series, periods_per_year: float = 252 * 24 * 12) -> float:
    """年率ソルティノレシオ."""
    downside = returns[returns < 0]
    if len(downside) == 0 or downside.std() == 0:
        return 0.0
    return float(returns.mean() / downside.std() * np.sqrt(periods_per_year))


def calc_max_drawdown(equity: pd.Series) -> tuple[float, float]:
    """最大ドローダウン（金額と割合）."""
    peak = equity.cummax()
    dd = equity - peak
    dd_pct = dd / peak
    return float(dd.min()), float(dd_pct.min())


def calc_win_rate(trades: pd.DataFrame) -> float:
    """勝率."""
    if len(trades) == 0:
        return 0.0
    wins = (trades["pnl"] > 0).sum()
    return float(wins / len(trades))


def calc_profit_factor(trades: pd.DataFrame) -> float:
    """プロフィットファクター."""
    gross_profit = trades.loc[trades["pnl"] > 0, "pnl"].sum()
    gross_loss = abs(trades.loc[trades["pnl"] < 0, "pnl"].sum())
    if gross_loss == 0:
        return float("inf") if gross_profit > 0 else 0.0
    return float(gross_profit / gross_loss)


def calc_monthly_returns(equity: pd.Series) -> pd.Series:
    """月次リターン."""
    monthly = equity.resample("ME").last()
    return monthly.pct_change().dropna()


def calc_all_metrics(equity: pd.Series, trades: pd.DataFrame) -> dict:
    """全メトリクスをまとめて計算."""
    returns = equity.pct_change().dropna()
    dd_abs, dd_pct = calc_max_drawdown(equity)

    return {
        "total_return": float((equity.iloc[-1] / equity.iloc[0]) - 1),
        "total_pnl": float(equity.iloc[-1] - equity.iloc[0]),
        "sharpe_ratio": calc_sharpe(returns),
        "sortino_ratio": calc_sortino(returns),
        "max_drawdown": dd_abs,
        "max_drawdown_pct": dd_pct,
        "num_trades": len(trades),
        "win_rate": calc_win_rate(trades),
        "profit_factor": calc_profit_factor(trades),
        "avg_pnl": float(trades["pnl"].mean()) if len(trades) > 0 else 0.0,
        "avg_win": float(trades.loc[trades["pnl"] > 0, "pnl"].mean()) if (trades["pnl"] > 0).any() else 0.0,
        "avg_loss": float(trades.loc[trades["pnl"] < 0, "pnl"].mean()) if (trades["pnl"] < 0).any() else 0.0,
    }
