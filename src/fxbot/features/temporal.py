"""時間帯特徴量（cyclical encoding）."""

from __future__ import annotations

import numpy as np
import pandas as pd


def add_temporal_features(df: pd.DataFrame, prefix: str = "") -> pd.DataFrame:
    """時間関連特徴量を追加（cyclical encoding）."""
    p = f"{prefix}_" if prefix else ""
    dt = df.index

    # 時刻（0-23）→ cyclical
    hour = dt.hour
    df[f"{p}hour_sin"] = np.sin(2 * np.pi * hour / 24)
    df[f"{p}hour_cos"] = np.cos(2 * np.pi * hour / 24)

    # 曜日（0=月 ~ 4=金）→ cyclical
    dow = dt.dayofweek
    df[f"{p}dow_sin"] = np.sin(2 * np.pi * dow / 5)
    df[f"{p}dow_cos"] = np.cos(2 * np.pi * dow / 5)

    # 月内日（1-31）→ cyclical
    dom = dt.day
    df[f"{p}dom_sin"] = np.sin(2 * np.pi * dom / 31)
    df[f"{p}dom_cos"] = np.cos(2 * np.pi * dom / 31)

    # セッション判定（UTC基準）
    # 東京: 0-8 UTC, ロンドン: 7-16 UTC, NY: 13-22 UTC
    df[f"{p}session_tokyo"] = ((hour >= 0) & (hour < 8)).astype(int)
    df[f"{p}session_london"] = ((hour >= 7) & (hour < 16)).astype(int)
    df[f"{p}session_ny"] = ((hour >= 13) & (hour < 22)).astype(int)
    df[f"{p}session_overlap_lon_ny"] = ((hour >= 13) & (hour < 16)).astype(int)

    # 週初め/週末フラグ
    df[f"{p}is_monday"] = (dow == 0).astype(int)
    df[f"{p}is_friday"] = (dow == 4).astype(int)

    return df
