"""予測値ベース可変ロットサイズ計算."""

from __future__ import annotations

import numpy as np

from fxbot.config import Settings
from fxbot.logger import get_logger

log = get_logger(__name__)


def calculate_lot(
    prediction: float,
    balance: float,
    atr: float,
    point: float,
    settings: Settings,
) -> float:
    """予測値・残高・ATRからロットサイズを計算.

    ロジック:
    1. リスク金額 = 残高 × max_risk_per_trade
    2. SL距離 = ATR × atr_sl_multiplier
    3. ベースロット = リスク金額 / (SL距離 × contract_size)
    4. 予測値の大きさで調整（大きいほどロット増）
    """
    risk_cfg = settings.risk
    trading_cfg = settings.trading

    risk_amount = balance * risk_cfg.max_risk_per_trade
    sl_distance = atr * risk_cfg.atr_sl_multiplier

    if sl_distance <= 0 or np.isnan(sl_distance):
        return trading_cfg.min_lot

    # 標準ロット: 100,000通貨 = 1ロット
    base_lot = risk_amount / (sl_distance * 100_000)

    # 予測値の大きさで調整（sigmoid的にスケーリング）
    pred_abs = abs(prediction)
    threshold = trading_cfg.min_prediction_threshold
    if pred_abs <= threshold:
        return 0.0  # 閾値未満は取引しない

    # 予測値が閾値の2倍 → ×1.5、3倍 → ×1.8 (対数スケール)
    scale = 1.0 + 0.5 * np.log1p(pred_abs / threshold - 1)
    scale = min(scale, 2.0)  # 最大2倍

    lot = base_lot * scale
    lot = max(trading_cfg.min_lot, min(trading_cfg.max_lot, lot))
    lot = round(lot, 2)

    return lot
