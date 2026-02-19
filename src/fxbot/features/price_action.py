"""価格アクション: ローソク足パターン, ギャップ, リターン."""

from __future__ import annotations

import numpy as np
import pandas as pd


def add_price_action_features(df: pd.DataFrame, prefix: str = "") -> pd.DataFrame:
    """価格アクション系特徴量を追加."""
    p = f"{prefix}_" if prefix else ""
    o, h, l, c = df["open"], df["high"], df["low"], df["close"]
    body = c - o
    body_abs = body.abs()
    hl_range = h - l

    # 基本的なローソク足特徴
    df[f"{p}body_ratio"] = body / hl_range.replace(0, np.nan)
    df[f"{p}upper_shadow"] = (h - pd.concat([o, c], axis=1).max(axis=1)) / hl_range.replace(0, np.nan)
    df[f"{p}lower_shadow"] = (pd.concat([o, c], axis=1).min(axis=1) - l) / hl_range.replace(0, np.nan)

    # 対数リターン（複数期間）
    for period in [1, 2, 3, 5, 10, 20]:
        df[f"{p}log_ret_{period}"] = np.log(c / c.shift(period))

    # ギャップ
    df[f"{p}gap"] = (o - c.shift(1)) / c.shift(1)

    # High/Lowからの位置
    for period in [5, 10, 20, 50]:
        rolling_high = h.rolling(period).max()
        rolling_low = l.rolling(period).min()
        hl_diff = rolling_high - rolling_low
        df[f"{p}pos_in_range_{period}"] = (c - rolling_low) / hl_diff.replace(0, np.nan)

    # 連続陽線/陰線カウント
    is_bull = (c > o).astype(int)
    is_bear = (c < o).astype(int)

    # 連続カウント計算
    bull_groups = is_bull.ne(is_bull.shift()).cumsum()
    df[f"{p}consec_bull"] = is_bull.groupby(bull_groups).cumsum() * is_bull

    bear_groups = is_bear.ne(is_bear.shift()).cumsum()
    df[f"{p}consec_bear"] = is_bear.groupby(bear_groups).cumsum() * is_bear

    # Doji判定（bodyが小さい）
    avg_body = body_abs.rolling(20).mean()
    df[f"{p}is_doji"] = (body_abs < avg_body * 0.1).astype(int)

    # ハンマー/シューティングスター
    df[f"{p}is_hammer"] = (
        (df[f"{p}lower_shadow"] > 2 * df[f"{p}body_ratio"].abs())
        & (df[f"{p}upper_shadow"] < 0.3)
    ).astype(int)

    df[f"{p}is_shooting_star"] = (
        (df[f"{p}upper_shadow"] > 2 * df[f"{p}body_ratio"].abs())
        & (df[f"{p}lower_shadow"] < 0.3)
    ).astype(int)

    return df
