"""テスト共通フィクスチャ."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from fxbot.config import Settings, load_settings


@pytest.fixture
def settings() -> Settings:
    """テスト用設定."""
    return load_settings()


@pytest.fixture
def sample_ohlcv() -> pd.DataFrame:
    """テスト用OHLCVデータ（500行）."""
    np.random.seed(42)
    n = 500
    dates = pd.date_range("2024-01-01", periods=n, freq="5min", tz="UTC")

    close = 1.1000 + np.cumsum(np.random.randn(n) * 0.0002)
    high = close + np.abs(np.random.randn(n) * 0.0003)
    low = close - np.abs(np.random.randn(n) * 0.0003)
    open_ = close + np.random.randn(n) * 0.0001
    volume = np.random.randint(100, 10000, n).astype(float)

    df = pd.DataFrame({
        "open": open_,
        "high": high,
        "low": low,
        "close": close,
        "volume": volume,
        "spread": np.ones(n) * 10,
        "real_volume": np.zeros(n),
    }, index=dates)
    df.index.name = "datetime"
    return df


@pytest.fixture
def sample_multi_tf(sample_ohlcv) -> dict[str, pd.DataFrame]:
    """マルチTFテストデータ."""
    m5 = sample_ohlcv.copy()

    # M15を模擬（3行ごとにリサンプル）
    m15 = m5.resample("15min").agg({
        "open": "first",
        "high": "max",
        "low": "min",
        "close": "last",
        "volume": "sum",
        "spread": "mean",
        "real_volume": "sum",
    }).dropna()

    # H1を模擬
    h1 = m5.resample("1h").agg({
        "open": "first",
        "high": "max",
        "low": "min",
        "close": "last",
        "volume": "sum",
        "spread": "mean",
        "real_volume": "sum",
    }).dropna()

    return {"M5": m5, "M15": m15, "H1": h1}
