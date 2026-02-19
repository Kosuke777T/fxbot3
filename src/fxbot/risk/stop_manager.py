"""ATR/予測値/トレーリングの3層SL/TP管理."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from fxbot.config import Settings
from fxbot.logger import get_logger

log = get_logger(__name__)


@dataclass
class StopLevels:
    sl: float
    tp: float
    trailing_activation: float
    trailing_distance: float


def calculate_stops(
    side: str,
    entry_price: float,
    prediction: float,
    atr: float,
    settings: Settings,
) -> StopLevels:
    """3層ストップレベルを計算.

    Layer 1: ATRベースSL/TP
    Layer 2: 予測値ベースで微調整
    Layer 3: トレーリングストップパラメータ
    """
    risk_cfg = settings.risk
    pred_abs = abs(prediction)

    # Layer 1: ATRベース
    atr_sl = atr * risk_cfg.atr_sl_multiplier
    atr_tp = atr * risk_cfg.atr_tp_multiplier

    # Layer 2: 予測値の大きさで微調整
    # 予測値が大きい → TPを少し広げ、SLを少し狭める
    pred_scale = min(pred_abs / 0.001, 2.0)  # 正規化
    tp_adj = 1.0 + 0.1 * pred_scale  # TP最大+20%
    sl_adj = 1.0 - 0.05 * pred_scale  # SL最大-10%

    adjusted_sl = atr_sl * sl_adj
    adjusted_tp = atr_tp * tp_adj

    # Layer 3: トレーリングストップ
    trailing_activation = atr * risk_cfg.trailing_activation_atr
    trailing_distance = atr * risk_cfg.trailing_atr_multiplier

    if side == "buy":
        sl = entry_price - adjusted_sl
        tp = entry_price + adjusted_tp
    else:
        sl = entry_price + adjusted_sl
        tp = entry_price - adjusted_tp

    return StopLevels(
        sl=sl,
        tp=tp,
        trailing_activation=trailing_activation,
        trailing_distance=trailing_distance,
    )


def update_trailing_stop(
    side: str,
    current_price: float,
    entry_price: float,
    current_sl: float,
    stop_levels: StopLevels,
) -> float | None:
    """トレーリングストップを更新.

    Returns:
        新しいSL値、更新不要ならNone
    """
    if side == "buy":
        profit = current_price - entry_price
        if profit >= stop_levels.trailing_activation:
            new_sl = current_price - stop_levels.trailing_distance
            if new_sl > current_sl:
                return new_sl
    else:
        profit = entry_price - current_price
        if profit >= stop_levels.trailing_activation:
            new_sl = current_price + stop_levels.trailing_distance
            if new_sl < current_sl:
                return new_sl

    return None
