"""市場レジーム判定特徴量.

トレンド相場とレンジ相場を判別し、モデルに市場環境の文脈を提供する。
ADX（トレンド強度）・BBwidth（スクイーズ）・Hurst指数（記憶性）を使用。
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import ta


def _hurst_exponent(series: pd.Series, lags: list[int] | None = None) -> pd.Series:
    """ローリング Hurst 指数を計算.

    H > 0.5: トレンド性（持続性）
    H ≈ 0.5: ランダムウォーク
    H < 0.5: 平均回帰性
    """
    if lags is None:
        lags = [2, 4, 8, 16]

    n = len(series)
    result = np.full(n, np.nan)

    window = max(lags) * 4  # 安定計算に必要な最小ウィンドウ

    for i in range(window, n):
        chunk = series.iloc[i - window:i].values
        try:
            tau = []
            lagvec = []
            for lag in lags:
                diffs = chunk[lag:] - chunk[:-lag]
                tau.append(np.sqrt(np.std(diffs)))
                lagvec.append(lag)
            if len(tau) >= 2 and all(t > 0 for t in tau):
                log_lags = np.log(lagvec)
                log_tau = np.log(tau)
                m = np.polyfit(log_lags, log_tau, 1)
                result[i] = m[0]
        except Exception:
            pass

    return pd.Series(result, index=series.index)


def add_regime_features(df: pd.DataFrame, prefix: str = "") -> pd.DataFrame:
    """市場レジーム判定特徴量を追加.

    追加される特徴量:
    - regime_adx: ADX値（トレンド強度）
    - regime_trend_up: +DI > -DI かつ ADX > 20 → 上昇トレンド
    - regime_trend_down: -DI > +DI かつ ADX > 20 → 下降トレンド
    - regime_ranging: ADX < 20 → レンジ相場
    - regime_bb_width_norm: BBwidthの過去20バー内での正規化（スクイーズ検出）
    - regime_squeeze: BBwidthが低い → スクイーズ（ブレイクアウト前）
    - regime_hurst: Hurst指数（トレンド持続性）
    - regime_vol_ratio: 短期/長期ボラティリティ比（ボラ拡大検出）
    """
    p = f"{prefix}_" if prefix else ""
    close = df["close"]
    high = df["high"]
    low = df["low"]

    # --- ADX ベースのトレンド判定 ---
    adx_ind = ta.trend.ADXIndicator(high, low, close, window=14)
    adx = adx_ind.adx()
    di_pos = adx_ind.adx_pos()
    di_neg = adx_ind.adx_neg()

    df[f"{p}regime_adx"] = adx
    df[f"{p}regime_trend_up"] = ((di_pos > di_neg) & (adx >= 20)).astype(int)
    df[f"{p}regime_trend_down"] = ((di_neg > di_pos) & (adx >= 20)).astype(int)
    df[f"{p}regime_ranging"] = (adx < 20).astype(int)

    # ADX 変化率（トレンド強まり/弱まり）
    df[f"{p}regime_adx_delta"] = adx.diff(3)

    # --- Bollinger Band スクイーズ ---
    bb = ta.volatility.BollingerBands(close, window=20, window_dev=2)
    bb_width = bb.bollinger_wband()  # (upper - lower) / mid

    # BBwidthの相対水準（過去50バー内での順位）
    bb_rank = bb_width.rolling(50).apply(
        lambda x: (x[-1] - x.min()) / (x.max() - x.min() + 1e-10), raw=True
    )
    df[f"{p}regime_bb_width_norm"] = bb_rank
    df[f"{p}regime_squeeze"] = (bb_rank < 0.2).astype(int)  # 下位20%=スクイーズ

    # --- Hurst 指数 ---
    df[f"{p}regime_hurst"] = _hurst_exponent(close)

    # --- ボラティリティ比（短期/長期） ---
    log_ret = np.log(close / close.shift(1))
    vol_short = log_ret.rolling(5).std()
    vol_long = log_ret.rolling(20).std()
    df[f"{p}regime_vol_ratio"] = vol_short / (vol_long + 1e-10)

    return df


def detect_regime(adx: float, di_pos: float, di_neg: float) -> str:
    """現在の市場レジームを文字列で返す（ライブ取引シグナル生成用）.

    Returns:
        "trend_up" | "trend_down" | "ranging"
    """
    if adx >= 20:
        return "trend_up" if di_pos > di_neg else "trend_down"
    return "ranging"
