"""ボリューム特徴量."""

from __future__ import annotations

import numpy as np
import pandas as pd
import ta


def add_volume_features(df: pd.DataFrame, prefix: str = "") -> pd.DataFrame:
    """ボリューム系特徴量を追加."""
    p = f"{prefix}_" if prefix else ""
    close = df["close"]
    high = df["high"]
    low = df["low"]
    volume = df["volume"]

    # ボリューム移動平均
    for period in [5, 10, 20]:
        df[f"{p}vol_sma_{period}"] = volume.rolling(period).mean()

    # ボリューム比率
    df[f"{p}vol_ratio_5_20"] = (
        volume.rolling(5).mean() / volume.rolling(20).mean().replace(0, np.nan)
    )

    # OBV
    df[f"{p}obv"] = ta.volume.on_balance_volume(close, volume)
    df[f"{p}obv_sma_10"] = df[f"{p}obv"].rolling(10).mean()

    # MFI (Money Flow Index)
    df[f"{p}mfi"] = ta.volume.money_flow_index(high, low, close, volume, window=14)

    # VWAP近似（ローリング）
    typical_price = (high + low + close) / 3
    for period in [20]:
        cum_tp_vol = (typical_price * volume).rolling(period).sum()
        cum_vol = volume.rolling(period).sum()
        df[f"{p}vwap_{period}"] = cum_tp_vol / cum_vol.replace(0, np.nan)
        df[f"{p}vwap_{period}_dev"] = (close - df[f"{p}vwap_{period}"]) / df[f"{p}vwap_{period}"]

    # Force Index
    df[f"{p}force_index"] = ta.volume.force_index(close, volume, window=13)

    # Volume変化率
    df[f"{p}vol_change"] = volume.pct_change()

    return df
