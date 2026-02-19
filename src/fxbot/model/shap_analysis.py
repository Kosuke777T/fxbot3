"""SHAP計算・特徴量選択."""

from __future__ import annotations

import lightgbm as lgb
import numpy as np
import pandas as pd
import shap

from fxbot.logger import get_logger

log = get_logger(__name__)


def compute_shap_values(
    model: lgb.Booster,
    X: pd.DataFrame,
    max_samples: int = 5000,
) -> tuple[np.ndarray, np.ndarray]:
    """SHAP値を計算.

    Returns:
        (shap_values, expected_value) のタプル
    """
    # サンプル数が多い場合はサブサンプリング
    if len(X) > max_samples:
        X_sample = X.sample(max_samples, random_state=42)
    else:
        X_sample = X

    explainer = shap.TreeExplainer(model)
    shap_values = explainer.shap_values(X_sample)

    log.info(f"SHAP計算完了: {X_sample.shape[0]}サンプル × {X_sample.shape[1]}特徴量")
    return shap_values, explainer.expected_value


def compute_feature_importance(
    shap_values: np.ndarray,
    feature_names: list[str],
) -> pd.DataFrame:
    """SHAP値から特徴量重要度を計算.

    Returns:
        feature, importance列を持つDataFrame（重要度降順）
    """
    importance = np.abs(shap_values).mean(axis=0)
    df = pd.DataFrame({
        "feature": feature_names,
        "importance": importance,
    })
    df = df.sort_values("importance", ascending=False).reset_index(drop=True)
    df["cumulative_pct"] = df["importance"].cumsum() / df["importance"].sum()
    return df


def select_features(
    model: lgb.Booster,
    X: pd.DataFrame,
    top_pct: float = 0.5,
    max_samples: int = 5000,
) -> tuple[list[str], pd.DataFrame]:
    """SHAP値に基づいて上位N%の特徴量を選択.

    Args:
        model: 学習済みモデル
        X: 特徴量マトリクス
        top_pct: 上位何%を残すか（0-1）
        max_samples: SHAP計算に使うサンプル数上限

    Returns:
        (selected_feature_names, importance_df) のタプル
    """
    shap_values, _ = compute_shap_values(model, X, max_samples)
    importance_df = compute_feature_importance(shap_values, list(X.columns))

    n_select = max(1, int(len(importance_df) * top_pct))
    selected = importance_df.head(n_select)["feature"].tolist()

    log.info(f"特徴量選択: {len(X.columns)} → {len(selected)} (上位{top_pct*100:.0f}%)")
    return selected, importance_df
