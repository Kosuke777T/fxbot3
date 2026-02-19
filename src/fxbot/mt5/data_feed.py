"""OHLCV取得・parquetキャッシュ."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import MetaTrader5 as mt5
import numpy as np
import pandas as pd

from fxbot.config import Settings
from fxbot.logger import get_logger
from fxbot.mt5.connection import TIMEFRAME_MAP

log = get_logger(__name__)


def fetch_ohlcv(
    symbol: str,
    timeframe: str,
    bars: int = 10000,
) -> pd.DataFrame:
    """MT5からOHLCVデータを取得しDataFrameで返す."""
    tf = TIMEFRAME_MAP.get(timeframe)
    if tf is None:
        raise ValueError(f"未対応のタイムフレーム: {timeframe}")

    rates = mt5.copy_rates_from_pos(symbol, tf, 0, bars)
    if rates is None or len(rates) == 0:
        log.warning(f"データ取得失敗: {symbol} {timeframe} — {mt5.last_error()}")
        return pd.DataFrame()

    df = pd.DataFrame(rates)
    df["time"] = pd.to_datetime(df["time"], unit="s", utc=True)
    df = df.rename(columns={
        "time": "datetime",
        "open": "open",
        "high": "high",
        "low": "low",
        "close": "close",
        "tick_volume": "volume",
        "spread": "spread",
        "real_volume": "real_volume",
    })
    df = df.set_index("datetime")
    return df


def _cache_path(symbol: str, timeframe: str, settings: Settings) -> Path:
    """キャッシュファイルのパスを生成."""
    cache_dir = settings.resolve_path(settings.data.cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)
    return cache_dir / f"{symbol}_{timeframe}.parquet"


def save_ohlcv(df: pd.DataFrame, symbol: str, timeframe: str, settings: Settings) -> Path:
    """OHLCVをparquetに保存."""
    path = _cache_path(symbol, timeframe, settings)
    df.to_parquet(path, engine="pyarrow")
    log.info(f"OHLCV保存: {path} ({len(df)}行)")
    return path


def load_ohlcv(symbol: str, timeframe: str, settings: Settings) -> pd.DataFrame:
    """キャッシュからOHLCVを読み込む."""
    path = _cache_path(symbol, timeframe, settings)
    if not path.exists():
        return pd.DataFrame()
    df = pd.read_parquet(path, engine="pyarrow")
    log.debug(f"OHLCVキャッシュ読込: {path} ({len(df)}行)")
    return df


def fetch_and_cache(
    symbol: str,
    timeframe: str,
    settings: Settings,
    bars: int | None = None,
) -> pd.DataFrame:
    """MT5からOHLCVを取得し、キャッシュに保存して返す.

    既存キャッシュがある場合は差分のみ取得してマージする。
    """
    if bars is None:
        bars = settings.data.bars_count

    cached = load_ohlcv(symbol, timeframe, settings)
    fresh = fetch_ohlcv(symbol, timeframe, bars)

    if fresh.empty:
        return cached

    if not cached.empty:
        # 既存データとマージ（重複排除）
        df = pd.concat([cached, fresh])
        df = df[~df.index.duplicated(keep="last")]
        df = df.sort_index()
    else:
        df = fresh

    save_ohlcv(df, symbol, timeframe, settings)
    return df


def fetch_multi_timeframe(
    symbol: str,
    settings: Settings,
) -> dict[str, pd.DataFrame]:
    """基準足 + 上位足のOHLCVをまとめて取得."""
    timeframes = [settings.data.base_timeframe] + settings.data.higher_timeframes
    result = {}
    for tf in timeframes:
        log.info(f"取得中: {symbol} {tf}")
        df = fetch_and_cache(symbol, tf, settings)
        if not df.empty:
            result[tf] = df
            log.info(f"  → {len(df)}行")
        else:
            log.warning(f"  → データなし")
    return result
