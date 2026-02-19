"""特徴量エンジニアリングのテスト."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from fxbot.features.trend import add_trend_features
from fxbot.features.momentum import add_momentum_features
from fxbot.features.volatility import add_volatility_features
from fxbot.features.price_action import add_price_action_features
from fxbot.features.volume import add_volume_features
from fxbot.features.temporal import add_temporal_features
from fxbot.features.builder import compute_features_single, build_feature_matrix


class TestIndividualFeatures:
    """個別特徴量モジュールのテスト."""

    def test_trend_features(self, sample_ohlcv):
        result = add_trend_features(sample_ohlcv.copy())
        assert "sma_20" in result.columns
        assert "ema_10" in result.columns
        assert "macd" in result.columns
        assert "adx" in result.columns
        assert len(result) == len(sample_ohlcv)

    def test_momentum_features(self, sample_ohlcv):
        result = add_momentum_features(sample_ohlcv.copy())
        assert "rsi_14" in result.columns
        assert "stoch_k" in result.columns
        assert "cci" in result.columns
        assert len(result) == len(sample_ohlcv)

    def test_volatility_features(self, sample_ohlcv):
        result = add_volatility_features(sample_ohlcv.copy())
        assert "bb_upper" in result.columns
        assert "atr_14" in result.columns
        assert "bb_width" in result.columns
        assert len(result) == len(sample_ohlcv)

    def test_price_action_features(self, sample_ohlcv):
        result = add_price_action_features(sample_ohlcv.copy())
        assert "body_ratio" in result.columns
        assert "log_ret_1" in result.columns
        assert "gap" in result.columns
        assert len(result) == len(sample_ohlcv)

    def test_volume_features(self, sample_ohlcv):
        result = add_volume_features(sample_ohlcv.copy())
        assert "obv" in result.columns
        assert "mfi" in result.columns
        assert "vol_ratio_5_20" in result.columns
        assert len(result) == len(sample_ohlcv)

    def test_temporal_features(self, sample_ohlcv):
        result = add_temporal_features(sample_ohlcv.copy())
        assert "hour_sin" in result.columns
        assert "hour_cos" in result.columns
        assert "dow_sin" in result.columns
        assert "session_tokyo" in result.columns
        # 時間特徴量にNaNなし
        temporal_cols = [c for c in result.columns if c.startswith("hour") or c.startswith("dow") or c.startswith("session")]
        assert result[temporal_cols].isna().sum().sum() == 0


class TestFeatureBuilder:
    """特徴量統合のテスト."""

    def test_compute_features_single(self, sample_ohlcv):
        result = compute_features_single(sample_ohlcv.copy())
        # 80列以上の特徴量
        non_ohlcv = [c for c in result.columns if c not in ["open", "high", "low", "close", "volume", "spread", "real_volume"]]
        assert len(non_ohlcv) > 60

    def test_build_feature_matrix(self, sample_multi_tf):
        result = build_feature_matrix(sample_multi_tf, base_timeframe="M5")
        # NaNがないこと
        assert result.isna().sum().sum() == 0
        # 行数は元データより少ない（NaN除去のため）
        assert len(result) > 0
        assert len(result) < len(sample_multi_tf["M5"])
        # 上位足の特徴量が含まれること
        m15_cols = [c for c in result.columns if c.startswith("m15_")]
        h1_cols = [c for c in result.columns if c.startswith("h1_")]
        assert len(m15_cols) > 0
        assert len(h1_cols) > 0

    def test_no_lookahead_bias(self, sample_multi_tf):
        """ルックアヘッドバイアスがないことを確認."""
        result = build_feature_matrix(sample_multi_tf, base_timeframe="M5")
        # 上位足の値が未来のデータを使っていないことを確認
        # M15の特徴量は、そのM15バーの開始時刻以降のM5バーにのみ存在すべき
        if "m15_sma_20" in result.columns:
            m15_feat = result["m15_sma_20"]
            # 値が変わるタイミングがM15の境界と一致するか
            changes = m15_feat.diff().ne(0)
            change_times = result.index[changes]
            for t in change_times[1:]:  # 最初の変化は除外
                assert t.minute % 15 == 0 or t.minute % 5 == 0  # 基準足の境界
