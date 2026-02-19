"""トレンド指標: SMA, EMA, MACD."""

from __future__ import annotations

import pandas as pd
import ta


def add_trend_features(df: pd.DataFrame, prefix: str = "") -> pd.DataFrame:
    """トレンド系特徴量を追加."""
    p = f"{prefix}_" if prefix else ""
    close = df["close"]
    high = df["high"]
    low = df["low"]

    # SMA
    for period in [5, 10, 20, 50, 100, 200]:
        df[f"{p}sma_{period}"] = ta.trend.sma_indicator(close, window=period)

    # EMA
    for period in [5, 10, 20, 50, 100]:
        df[f"{p}ema_{period}"] = ta.trend.ema_indicator(close, window=period)

    # MACD
    macd = ta.trend.MACD(close, window_slow=26, window_fast=12, window_sign=9)
    df[f"{p}macd"] = macd.macd()
    df[f"{p}macd_signal"] = macd.macd_signal()
    df[f"{p}macd_hist"] = macd.macd_diff()

    # ADX
    adx = ta.trend.ADXIndicator(high, low, close, window=14)
    df[f"{p}adx"] = adx.adx()
    df[f"{p}adx_pos"] = adx.adx_pos()
    df[f"{p}adx_neg"] = adx.adx_neg()

    # Ichimoku
    ichi = ta.trend.IchimokuIndicator(high, low, window1=9, window2=26, window3=52)
    df[f"{p}ichimoku_a"] = ichi.ichimoku_a()
    df[f"{p}ichimoku_b"] = ichi.ichimoku_b()
    df[f"{p}ichimoku_base"] = ichi.ichimoku_base_line()
    df[f"{p}ichimoku_conv"] = ichi.ichimoku_conversion_line()

    # SMA乖離率
    for period in [20, 50, 200]:
        sma = df[f"{p}sma_{period}"]
        df[f"{p}sma_{period}_dev"] = (close - sma) / sma

    # EMAクロス
    df[f"{p}ema_cross_5_20"] = df[f"{p}ema_5"] - df[f"{p}ema_20"]
    df[f"{p}ema_cross_20_50"] = df[f"{p}ema_20"] - df[f"{p}ema_50"]

    return df
