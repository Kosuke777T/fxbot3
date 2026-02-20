"""Triple Barrier ラベリング.

Marcos Lopez de Prado の Triple Barrier Method に基づく。
各バーから前方horizonバーを走査し、TP/SLバリアのどちらに先にヒットするかでラベル付け。
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from fxbot.logger import get_logger

log = get_logger(__name__)


def compute_triple_barrier_labels(
    df: pd.DataFrame,
    horizon: int = 6,
    sl_mult: float = 2.0,
    tp_mult: float = 2.0,
    vol_lookback: int = 20,
) -> pd.Series:
    """Triple Barrier Method でラベルを生成.

    Args:
        df: close列を含むDataFrame
        horizon: 前方走査バー数（vertical barrier）
        sl_mult: ボラティリティに対するSLバリア倍率
        tp_mult: ボラティリティに対するTPバリア倍率
        vol_lookback: ローリング標準偏差のルックバック期間

    Returns:
        ラベルSeries: 1 (TP hit / up), -1 (SL hit / down), 0 (vertical barrier / no hit)
    """
    close = df["close"].values
    n = len(close)

    # ローリング標準偏差（対数リターン）をバリア幅として使用
    log_returns = np.log(close[1:] / close[:-1])
    vol = pd.Series(log_returns).rolling(vol_lookback).std().values
    # 先頭にNaNが入るので、1つずらしてcloseと同じ長さにする
    vol = np.concatenate([[np.nan], vol])

    labels = np.full(n, np.nan)

    for i in range(n - 1):
        if np.isnan(vol[i]) or vol[i] <= 0:
            continue

        tp_barrier = close[i] * np.exp(vol[i] * tp_mult)
        sl_barrier = close[i] * np.exp(-vol[i] * sl_mult)

        end_idx = min(i + horizon + 1, n)
        label = 0  # デフォルト: vertical barrier（どちらにもヒットせず）

        for j in range(i + 1, end_idx):
            if close[j] >= tp_barrier:
                label = 1
                break
            elif close[j] <= sl_barrier:
                label = -1
                break

        labels[i] = label

    result = pd.Series(labels, index=df.index, name="label")
    valid = result.notna()
    counts = result[valid].value_counts()
    log.info(f"Triple Barrier ラベル分布: {counts.to_dict()} "
             f"(total={valid.sum()}, NaN={(~valid).sum()})")
    return result
