"""バー単位バックテストシミュレーション."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

import numpy as np
import pandas as pd

from fxbot.config import Settings
from fxbot.logger import get_logger

log = get_logger(__name__)


class Side(str, Enum):
    BUY = "buy"
    SELL = "sell"


@dataclass
class Position:
    entry_time: pd.Timestamp
    side: Side
    entry_price: float
    lot: float
    sl: float
    tp: float
    trailing_sl: float | None = None


@dataclass
class Trade:
    entry_time: pd.Timestamp
    exit_time: pd.Timestamp
    side: str
    entry_price: float
    exit_price: float
    lot: float
    pnl: float
    exit_reason: str


@dataclass
class BacktestResult:
    equity: pd.Series
    trades: list[Trade]
    settings: dict


class BacktestEngine:
    """バー単位のバックテストエンジン."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self.initial_balance = settings.backtest.initial_balance
        self.spread_pips = settings.backtest.spread_pips
        self.max_positions = settings.trading.max_positions

    def run(
        self,
        feature_matrix: pd.DataFrame,
        predictions: pd.Series,
        point: float = 0.0001,
    ) -> BacktestResult:
        """バックテストを実行.

        Args:
            feature_matrix: close, high, low, atr_14 列を含むDataFrame
            predictions: 予測対数リターン
            point: 1pipの値幅

        Returns:
            BacktestResult
        """
        balance = self.initial_balance
        positions: list[Position] = []
        trades: list[Trade] = []
        equity_series = {}

        risk_cfg = self.settings.risk
        trading_cfg = self.settings.trading
        spread = self.spread_pips * point * 10  # pips → price

        for i in range(len(feature_matrix)):
            row = feature_matrix.iloc[i]
            time = feature_matrix.index[i]
            close = row["close"]
            high = row["high"]
            low = row["low"]

            atr_col = "atr_14" if "atr_14" in row.index else None
            atr = row[atr_col] if atr_col and not np.isnan(row[atr_col]) else close * 0.001

            # --- ポジション管理（SL/TP/トレーリング） ---
            closed_indices = []
            for j, pos in enumerate(positions):
                exit_price = None
                exit_reason = ""

                if pos.side == Side.BUY:
                    # SLチェック
                    if low <= pos.sl:
                        exit_price = pos.sl
                        exit_reason = "sl"
                    # TPチェック
                    elif high >= pos.tp:
                        exit_price = pos.tp
                        exit_reason = "tp"
                    else:
                        # トレーリングストップ更新
                        activation = pos.entry_price + atr * risk_cfg.trailing_activation_atr
                        if high >= activation:
                            new_trailing = high - atr * risk_cfg.trailing_atr_multiplier
                            if pos.trailing_sl is None or new_trailing > pos.trailing_sl:
                                pos.trailing_sl = new_trailing
                        if pos.trailing_sl and low <= pos.trailing_sl:
                            exit_price = pos.trailing_sl
                            exit_reason = "trailing"

                else:  # SELL
                    if high >= pos.sl:
                        exit_price = pos.sl
                        exit_reason = "sl"
                    elif low <= pos.tp:
                        exit_price = pos.tp
                        exit_reason = "tp"
                    else:
                        activation = pos.entry_price - atr * risk_cfg.trailing_activation_atr
                        if low <= activation:
                            new_trailing = low + atr * risk_cfg.trailing_atr_multiplier
                            if pos.trailing_sl is None or new_trailing < pos.trailing_sl:
                                pos.trailing_sl = new_trailing
                        if pos.trailing_sl and high >= pos.trailing_sl:
                            exit_price = pos.trailing_sl
                            exit_reason = "trailing"

                if exit_price is not None:
                    if pos.side == Side.BUY:
                        pnl = (exit_price - pos.entry_price - spread) * pos.lot * 100000
                    else:
                        pnl = (pos.entry_price - exit_price - spread) * pos.lot * 100000

                    balance += pnl
                    trades.append(Trade(
                        entry_time=pos.entry_time,
                        exit_time=time,
                        side=pos.side.value,
                        entry_price=pos.entry_price,
                        exit_price=exit_price,
                        lot=pos.lot,
                        pnl=pnl,
                        exit_reason=exit_reason,
                    ))
                    closed_indices.append(j)

            # 決済済みポジションを除去
            for idx in reversed(closed_indices):
                positions.pop(idx)

            # --- エントリーシグナル ---
            if i < len(predictions) and len(positions) < self.max_positions:
                pred = predictions.iloc[i] if i < len(predictions) else 0.0

                if abs(pred) > trading_cfg.min_prediction_threshold:
                    # ロットサイズ計算
                    risk_amount = balance * risk_cfg.max_risk_per_trade
                    sl_distance = atr * risk_cfg.atr_sl_multiplier
                    if sl_distance > 0:
                        lot = risk_amount / (sl_distance * 100000)
                        lot = max(trading_cfg.min_lot, min(trading_cfg.max_lot, lot))
                        lot = round(lot, 2)
                    else:
                        lot = trading_cfg.min_lot

                    if pred > 0:  # BUY
                        sl = close - atr * risk_cfg.atr_sl_multiplier
                        tp = close + atr * risk_cfg.atr_tp_multiplier
                        positions.append(Position(
                            entry_time=time,
                            side=Side.BUY,
                            entry_price=close + spread / 2,
                            lot=lot,
                            sl=sl,
                            tp=tp,
                        ))
                    else:  # SELL
                        sl = close + atr * risk_cfg.atr_sl_multiplier
                        tp = close - atr * risk_cfg.atr_tp_multiplier
                        positions.append(Position(
                            entry_time=time,
                            side=Side.SELL,
                            entry_price=close - spread / 2,
                            lot=lot,
                            sl=sl,
                            tp=tp,
                        ))

            # エクイティ記録（残高 + 含み損益）
            unrealized = 0.0
            for pos in positions:
                if pos.side == Side.BUY:
                    unrealized += (close - pos.entry_price) * pos.lot * 100000
                else:
                    unrealized += (pos.entry_price - close) * pos.lot * 100000
            equity_series[time] = balance + unrealized

        # 残ポジションを最終バーで強制決済
        final_close = feature_matrix["close"].iloc[-1]
        final_time = feature_matrix.index[-1]
        for pos in positions:
            if pos.side == Side.BUY:
                pnl = (final_close - pos.entry_price - spread) * pos.lot * 100000
            else:
                pnl = (pos.entry_price - final_close - spread) * pos.lot * 100000
            balance += pnl
            trades.append(Trade(
                entry_time=pos.entry_time,
                exit_time=final_time,
                side=pos.side.value,
                entry_price=pos.entry_price,
                exit_price=final_close,
                lot=pos.lot,
                pnl=pnl,
                exit_reason="end",
            ))

        equity = pd.Series(equity_series, name="equity")
        equity.index.name = "datetime"

        trades_df = pd.DataFrame([
            {
                "entry_time": t.entry_time,
                "exit_time": t.exit_time,
                "side": t.side,
                "entry_price": t.entry_price,
                "exit_price": t.exit_price,
                "lot": t.lot,
                "pnl": t.pnl,
                "exit_reason": t.exit_reason,
            }
            for t in trades
        ])

        log.info(
            f"バックテスト完了: {len(trades)}トレード, "
            f"最終残高: {balance:.2f}, "
            f"リターン: {(balance / self.initial_balance - 1) * 100:.2f}%"
        )

        return BacktestResult(
            equity=equity,
            trades=trades,
            settings={
                "initial_balance": self.initial_balance,
                "spread_pips": self.spread_pips,
            },
        )
