"""推論（回帰 + 分類対応）."""

from __future__ import annotations

import lightgbm as lgb
import numpy as np
import pandas as pd

from fxbot.logger import get_logger

log = get_logger(__name__)


class Predictor:
    """LightGBMモデルで予測（回帰・分類両対応）."""

    def __init__(
        self, model: lgb.Booster, feature_names: list[str], mode: str = "regression"
    ):
        self.model = model
        self.feature_names = feature_names
        self.mode = mode

    def predict(self, feature_matrix: pd.DataFrame) -> pd.Series:
        """特徴量マトリクスから予測値を計算.

        Returns:
            回帰: 予測対数リターンのSeries
            分類: 予測クラス(0=down, 1=neutral, 2=up)のSeries
        """
        X = feature_matrix[self.feature_names]
        preds = self.model.predict(X)
        if self.mode == "classification":
            # (n_samples, 3) → argmax でクラス予測
            preds = np.argmax(preds, axis=1)
        return pd.Series(preds, index=feature_matrix.index, name="prediction")

    def predict_proba(self, feature_matrix: pd.DataFrame) -> pd.DataFrame:
        """分類モデルの3クラス確率を返す.

        Returns:
            DataFrame with columns: prob_down, prob_neutral, prob_up
        """
        X = feature_matrix[self.feature_names]
        preds = self.model.predict(X)
        if self.mode != "classification":
            raise ValueError("predict_proba() は分類モデルでのみ使用可能")
        return pd.DataFrame(
            preds,
            index=feature_matrix.index,
            columns=["prob_down", "prob_neutral", "prob_up"],
        )

    def predict_latest(self, feature_matrix: pd.DataFrame) -> float:
        """最新バーの予測値を返す（回帰モデル用）."""
        preds = self.predict(feature_matrix)
        return float(preds.iloc[-1])

    def predict_latest_with_confidence(
        self, feature_matrix: pd.DataFrame
    ) -> tuple[int, float]:
        """最新バーの方向と信頼度を返す（分類モデル用）.

        Returns:
            (direction, confidence): direction は 1(up) or -1(down),
            confidence は max(prob_up, prob_down)
        """
        proba = self.predict_proba(feature_matrix)
        latest = proba.iloc[-1]
        prob_up = latest["prob_up"]
        prob_down = latest["prob_down"]
        direction = 1 if prob_up > prob_down else -1
        confidence = max(prob_up, prob_down)
        return direction, float(confidence)

    def predict_with_confidence(
        self, feature_matrix: pd.DataFrame
    ) -> pd.DataFrame:
        """予測値と信頼度指標を返す（後方互換）."""
        if self.mode == "classification":
            proba = self.predict_proba(feature_matrix)
            direction = np.where(
                proba["prob_up"] > proba["prob_down"], 1, -1
            )
            confidence = np.maximum(proba["prob_up"], proba["prob_down"])
            return pd.DataFrame({
                "prediction": self.predict(feature_matrix),
                "confidence": confidence,
                "direction": direction,
            }, index=feature_matrix.index)
        else:
            preds = self.predict(feature_matrix)
            return pd.DataFrame({
                "prediction": preds,
                "abs_prediction": preds.abs(),
                "direction": np.sign(preds),
            }, index=feature_matrix.index)
