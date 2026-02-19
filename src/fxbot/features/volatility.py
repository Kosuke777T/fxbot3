"""ボラティリティ指標: BB, ATR, Keltner Channel."""

from __future__ import annotations

import numpy as np
import pandas as pd
import ta


def add_volatility_features(df: pd.DataFrame, prefix: str = "") -> pd.DataFrame:
    """ボラティリティ系特徴量を追加."""
    p = f"{prefix}_" if prefix else ""
    close = df["close"]
    high = df["high"]
    low = df["low"]

    # Bollinger Bands
    bb = ta.volatility.BollingerBands(close, window=20, window_dev=2)
    df[f"{p}bb_upper"] = bb.bollinger_hband()
    df[f"{p}bb_lower"] = bb.bollinger_lband()
    df[f"{p}bb_mid"] = bb.bollinger_mavg()
    df[f"{p}bb_width"] = bb.bollinger_wband()
    df[f"{p}bb_pband"] = bb.bollinger_pband()  # %B

    # ATR
    for period in [7, 14, 21]:
        df[f"{p}atr_{period}"] = ta.volatility.average_true_range(high, low, close, window=period)

    # ATR正規化（close対比）
    df[f"{p}atr_14_norm"] = df[f"{p}atr_14"] / close

    # Keltner Channel
    kc = ta.volatility.KeltnerChannel(high, low, close, window=20)
    df[f"{p}kc_upper"] = kc.keltner_channel_hband()
    df[f"{p}kc_lower"] = kc.keltner_channel_lband()
    df[f"{p}kc_mid"] = kc.keltner_channel_mband()
    df[f"{p}kc_width"] = (kc.keltner_channel_hband() - kc.keltner_channel_lband()) / close

    # Donchian Channel
    dc = ta.volatility.DonchianChannel(high, low, close, window=20)
    df[f"{p}dc_upper"] = dc.donchian_channel_hband()
    df[f"{p}dc_lower"] = dc.donchian_channel_lband()
    df[f"{p}dc_width"] = dc.donchian_channel_wband()

    # 対数リターンのローリング標準偏差
    log_ret = np.log(close / close.shift(1))
    for period in [5, 10, 20]:
        df[f"{p}ret_std_{period}"] = log_ret.rolling(period).std()

    # High-Low Range
    df[f"{p}hl_range"] = (high - low) / close

    return df
