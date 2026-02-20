"""モデル劣化検知 — ローリングメトリクスで取引パフォーマンスを監視."""

from __future__ import annotations

from fxbot.logger import get_logger
from fxbot.trade_logger import TradeLogger

log = get_logger(__name__)


class ModelMonitor:
    """TradeLoggerから直近N件のローリングメトリクスを計算し、劣化を検知."""

    def __init__(
        self,
        trade_logger: TradeLogger,
        window: int = 20,
        min_win_rate: float = 0.40,
        min_sharpe: float = 0.0,
    ):
        self.trade_logger = trade_logger
        self.window = window
        self.min_win_rate = min_win_rate
        self.min_sharpe = min_sharpe

    def check(self) -> dict:
        """モデルの健全性をチェック.

        Returns:
            {
                "healthy": bool,
                "warnings": list[str],
                "metrics": dict,
            }
        """
        metrics = self.trade_logger.get_rolling_metrics(self.window)
        warnings = []

        if metrics["count"] < self.window:
            return {
                "healthy": True,
                "warnings": [f"データ不足: {metrics['count']}/{self.window}件"],
                "metrics": metrics,
            }

        if metrics["win_rate"] < self.min_win_rate:
            warnings.append(
                f"勝率低下: {metrics['win_rate']:.1%} < {self.min_win_rate:.1%}"
            )

        if metrics["sharpe"] < self.min_sharpe:
            warnings.append(
                f"シャープレシオ低下: {metrics['sharpe']:.2f} < {self.min_sharpe:.2f}"
            )

        healthy = len(warnings) == 0

        if not healthy:
            for w in warnings:
                log.warning(f"モデル劣化検知: {w}")

        return {
            "healthy": healthy,
            "warnings": warnings,
            "metrics": metrics,
        }
