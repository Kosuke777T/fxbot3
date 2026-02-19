"""モデルのテスト."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from fxbot.features.builder import build_feature_matrix
from fxbot.model.trainer import build_target, prepare_dataset, train_model
from fxbot.model.predictor import Predictor


class TestTarget:
    def test_build_target(self, sample_ohlcv):
        target = build_target(sample_ohlcv, horizon=6)
        assert len(target) == len(sample_ohlcv)
        # 最後のhorizon行はNaN
        assert target.iloc[-1] != target.iloc[-1]  # NaN
        assert target.iloc[-6] != target.iloc[-6]  # NaN
        # 有効値は対数リターン
        valid = target.dropna()
        assert len(valid) > 0
        assert abs(valid.mean()) < 0.01  # ランダムデータなので平均はほぼ0


class TestTraining:
    def test_prepare_dataset(self, sample_multi_tf, settings):
        fm = build_feature_matrix(sample_multi_tf, "M5")
        X, y, feat_names = prepare_dataset(fm, horizon=6)
        assert len(X) == len(y)
        assert len(X) > 0
        assert X.isna().sum().sum() == 0
        assert y.isna().sum() == 0

    def test_train_model(self, sample_multi_tf, settings):
        fm = build_feature_matrix(sample_multi_tf, "M5")
        X, y, feat_names = prepare_dataset(fm, horizon=6)
        model, metrics = train_model(X, y, settings)

        assert model is not None
        assert "mae" in metrics
        assert "direction_accuracy" in metrics
        assert "information_coefficient" in metrics
        assert metrics["mae"] > 0

    def test_predictor(self, sample_multi_tf, settings):
        fm = build_feature_matrix(sample_multi_tf, "M5")
        X, y, feat_names = prepare_dataset(fm, horizon=6)
        model, _ = train_model(X, y, settings)

        predictor = Predictor(model, feat_names)
        preds = predictor.predict(X)
        assert len(preds) == len(X)
        assert preds.isna().sum() == 0

        latest = predictor.predict_latest(X)
        assert isinstance(latest, float)
