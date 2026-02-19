"""モメンタム指標: RSI, Stochastic, CCI, Williams %R, ROC."""

from __future__ import annotations

import pandas as pd
import ta


def add_momentum_features(df: pd.DataFrame, prefix: str = "") -> pd.DataFrame:
    """モメンタム系特徴量を追加."""
    p = f"{prefix}_" if prefix else ""
    close = df["close"]
    high = df["high"]
    low = df["low"]

    # RSI
    for period in [7, 14, 21]:
        df[f"{p}rsi_{period}"] = ta.momentum.rsi(close, window=period)

    # Stochastic
    stoch = ta.momentum.StochasticOscillator(high, low, close, window=14, smooth_window=3)
    df[f"{p}stoch_k"] = stoch.stoch()
    df[f"{p}stoch_d"] = stoch.stoch_signal()

    # CCI
    df[f"{p}cci"] = ta.trend.cci(high, low, close, window=20)

    # Williams %R
    df[f"{p}williams_r"] = ta.momentum.williams_r(high, low, close, lbp=14)

    # ROC
    for period in [5, 10, 20]:
        df[f"{p}roc_{period}"] = ta.momentum.roc(close, window=period)

    # Ultimate Oscillator
    df[f"{p}uo"] = ta.momentum.ultimate_oscillator(high, low, close)

    # Awesome Oscillator
    df[f"{p}ao"] = ta.momentum.awesome_oscillator(high, low)

    # RSIの変化率
    df[f"{p}rsi_14_change"] = df[f"{p}rsi_14"].diff()

    return df
