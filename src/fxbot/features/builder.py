"""マルチTFアライメント・特徴量統合."""

from __future__ import annotations

import pandas as pd

from fxbot.features.trend import add_trend_features
from fxbot.features.momentum import add_momentum_features
from fxbot.features.volatility import add_volatility_features
from fxbot.features.price_action import add_price_action_features
from fxbot.features.volume import add_volume_features
from fxbot.features.temporal import add_temporal_features
from fxbot.logger import get_logger

log = get_logger(__name__)

# 各タイムフレームに適用する特徴量関数
_FEATURE_FUNCS = [
    add_trend_features,
    add_momentum_features,
    add_volatility_features,
    add_price_action_features,
    add_volume_features,
]


def compute_features_single(df: pd.DataFrame, prefix: str = "") -> pd.DataFrame:
    """単一タイムフレームのOHLCVに全特徴量を追加."""
    result = df.copy()
    for func in _FEATURE_FUNCS:
        result = func(result, prefix=prefix)
    return result


def align_higher_tf(
    base_df: pd.DataFrame,
    higher_df: pd.DataFrame,
    higher_tf: str,
) -> pd.DataFrame:
    """上位足の特徴量を基準足にアライメント.

    pd.merge_asof(direction='backward') でルックアヘッドバイアス防止。
    上位足の各バーの値は、そのバーの確定時刻以降の基準足バーに結合される。
    """
    prefix = higher_tf.lower()
    higher_feat = compute_features_single(higher_df, prefix=prefix)

    # OHLCV列は除外（特徴量のみ）
    ohlcv_cols = ["open", "high", "low", "close", "volume", "spread", "real_volume"]
    feat_cols = [c for c in higher_feat.columns if c not in ohlcv_cols]

    if not feat_cols:
        return base_df

    higher_subset = higher_feat[feat_cols].copy()
    higher_subset = higher_subset.reset_index()

    base_reset = base_df.reset_index()

    merged = pd.merge_asof(
        base_reset,
        higher_subset,
        on="datetime",
        direction="backward",
    )
    merged = merged.set_index("datetime")
    return merged


def build_feature_matrix(
    multi_tf_data: dict[str, pd.DataFrame],
    base_timeframe: str = "M5",
) -> pd.DataFrame:
    """マルチTFデータから統合特徴量マトリクスを構築.

    Args:
        multi_tf_data: {timeframe: ohlcv_df} の辞書
        base_timeframe: 基準タイムフレーム

    Returns:
        特徴量マトリクス（NaN行は除去済み）
    """
    if base_timeframe not in multi_tf_data:
        raise ValueError(f"基準足 {base_timeframe} のデータがありません")

    base_df = multi_tf_data[base_timeframe].copy()
    log.info(f"基準足 {base_timeframe}: {len(base_df)}行")

    # 基準足の特徴量
    result = compute_features_single(base_df, prefix="")

    # 時間特徴量（基準足のみ）
    result = add_temporal_features(result, prefix="")

    # 上位足をアライメント
    for tf, df in multi_tf_data.items():
        if tf == base_timeframe:
            continue
        log.info(f"上位足 {tf} アライメント中...")
        result = align_higher_tf(result, df, tf)
        log.info(f"  → 列数: {len(result.columns)}")

    # OHLCV元データ列を保持（後でターゲット構築に使用）
    # NaN行を除去
    initial_rows = len(result)
    result = result.dropna()
    dropped = initial_rows - len(result)
    log.info(f"特徴量マトリクス: {result.shape[0]}行 × {result.shape[1]}列 (NaN除去: {dropped}行)")

    return result
