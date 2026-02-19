"""バックテストエンジンのテスト."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from fxbot.backtest.engine import BacktestEngine
from fxbot.backtest.metrics import (
    calc_sharpe, calc_max_drawdown, calc_win_rate,
    calc_profit_factor, calc_all_metrics,
)
from fxbot.features.builder import build_feature_matrix
from fxbot.model.trainer import prepare_dataset, train_model


class TestBacktestEngine:
    def test_basic_run(self, sample_multi_tf, settings):
        fm = build_feature_matrix(sample_multi_tf, "M5")
        X, y, feat_names = prepare_dataset(fm, horizon=6)
        model, _ = train_model(X, y, settings)

        predictions = pd.Series(
            model.predict(X), index=X.index, name="prediction"
        )

        # fmにpredictionsをアライメント
        aligned_fm = fm.loc[predictions.index]

        engine = BacktestEngine(settings)
        result = engine.run(aligned_fm, predictions, point=0.0001)

        assert not result.equity.empty
        assert len(result.trades) >= 0  # トレードは0以上
        assert result.equity.iloc[0] > 0

    def test_no_trades_below_threshold(self, sample_multi_tf, settings):
        """閾値以下の予測ではトレードしない."""
        fm = build_feature_matrix(sample_multi_tf, "M5")
        # 全て0の予測
        predictions = pd.Series(0.0, index=fm.index, name="prediction")

        engine = BacktestEngine(settings)
        result = engine.run(fm, predictions, point=0.0001)

        assert len(result.trades) == 0


class TestMetrics:
    def test_calc_sharpe(self):
        returns = pd.Series(np.random.randn(1000) * 0.01 + 0.0001)
        sharpe = calc_sharpe(returns)
        assert isinstance(sharpe, float)

    def test_calc_max_drawdown(self):
        equity = pd.Series([100, 110, 105, 95, 100, 115])
        dd_abs, dd_pct = calc_max_drawdown(equity)
        assert dd_abs < 0
        assert dd_pct < 0

    def test_calc_win_rate(self):
        trades = pd.DataFrame({"pnl": [100, -50, 200, -30, 50]})
        wr = calc_win_rate(trades)
        assert wr == 0.6

    def test_calc_profit_factor(self):
        trades = pd.DataFrame({"pnl": [100, -50, 200, -30, 50]})
        pf = calc_profit_factor(trades)
        assert pf == 350 / 80

    def test_calc_all_metrics(self):
        equity = pd.Series(
            [1000, 1010, 1005, 1020, 1015, 1030],
            index=pd.date_range("2024-01-01", periods=6, freq="h"),
        )
        trades = pd.DataFrame({"pnl": [10, -5, 15, -5, 15]})
        metrics = calc_all_metrics(equity, trades)

        assert "total_return" in metrics
        assert "sharpe_ratio" in metrics
        assert "max_drawdown_pct" in metrics
        assert "win_rate" in metrics
        assert metrics["win_rate"] == 0.6
