"""推論."""

from __future__ import annotations

import lightgbm as lgb
import numpy as np
import pandas as pd

from fxbot.logger import get_logger

log = get_logger(__name__)


class Predictor:
    """LightGBMモデルで対数リターンを予測."""

    def __init__(self, model: lgb.Booster, feature_names: list[str]):
        self.model = model
        self.feature_names = feature_names

    def predict(self, feature_matrix: pd.DataFrame) -> pd.Series:
        """特徴量マトリクスから予測値を計算.

        Returns:
            予測対数リターンのSeries
        """
        X = feature_matrix[self.feature_names]
        preds = self.model.predict(X)
        return pd.Series(preds, index=feature_matrix.index, name="prediction")

    def predict_latest(self, feature_matrix: pd.DataFrame) -> float:
        """最新バーの予測値を返す."""
        preds = self.predict(feature_matrix)
        return float(preds.iloc[-1])

    def predict_with_confidence(
        self, feature_matrix: pd.DataFrame
    ) -> pd.DataFrame:
        """予測値と信頼度指標を返す."""
        preds = self.predict(feature_matrix)
        # 予測値の絶対値を信頼度の代理指標として使用
        result = pd.DataFrame({
            "prediction": preds,
            "abs_prediction": preds.abs(),
            "direction": np.sign(preds),
        }, index=feature_matrix.index)
        return result
