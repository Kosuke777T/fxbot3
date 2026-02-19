"""LightGBM学習パイプライン."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import lightgbm as lgb
import numpy as np
import pandas as pd
from sklearn.model_selection import train_test_split

from fxbot.config import Settings
from fxbot.logger import get_logger

log = get_logger(__name__)

# 特徴量から除外する列
_EXCLUDE_COLS = {"open", "high", "low", "close", "volume", "spread", "real_volume"}


def build_target(df: pd.DataFrame, horizon: int = 6) -> pd.Series:
    """対数リターンのターゲットを構築.

    y = log(close[t+horizon] / close[t])
    """
    close = df["close"]
    target = np.log(close.shift(-horizon) / close)
    target.name = "target"
    return target


def prepare_dataset(
    feature_matrix: pd.DataFrame,
    horizon: int = 6,
    selected_features: list[str] | None = None,
) -> tuple[pd.DataFrame, pd.Series, list[str]]:
    """特徴量マトリクスからX, yを準備.

    Returns:
        (X, y, feature_names) のタプル
    """
    target = build_target(feature_matrix, horizon)

    # 特徴量列の選定
    if selected_features:
        feat_cols = selected_features
    else:
        feat_cols = [c for c in feature_matrix.columns if c not in _EXCLUDE_COLS]

    X = feature_matrix[feat_cols].copy()
    y = target.copy()

    # NaN除去（ターゲットのshift分）
    valid_mask = y.notna() & X.notna().all(axis=1)
    X = X[valid_mask]
    y = y[valid_mask]

    log.info(f"データセット準備: {X.shape[0]}サンプル × {X.shape[1]}特徴量")
    return X, y, feat_cols


def train_model(
    X: pd.DataFrame,
    y: pd.Series,
    settings: Settings,
    val_ratio: float = 0.2,
) -> tuple[lgb.Booster, dict]:
    """LightGBMモデルを学習.

    時系列データのため、末尾をvalidationに使用（シャッフルしない）。

    Returns:
        (model, metrics) のタプル
    """
    cfg = settings.model

    # 時系列分割（末尾をval）
    split_idx = int(len(X) * (1 - val_ratio))
    X_train, X_val = X.iloc[:split_idx], X.iloc[split_idx:]
    y_train, y_val = y.iloc[:split_idx], y.iloc[split_idx:]

    log.info(f"学習: {len(X_train)}サンプル, 検証: {len(X_val)}サンプル")

    train_data = lgb.Dataset(X_train, label=y_train)
    val_data = lgb.Dataset(X_val, label=y_val, reference=train_data)

    callbacks = [
        lgb.early_stopping(cfg.early_stopping_rounds),
        lgb.log_evaluation(100),
    ]

    model = lgb.train(
        params=cfg.lgbm_params,
        train_set=train_data,
        num_boost_round=cfg.num_boost_round,
        valid_sets=[train_data, val_data],
        valid_names=["train", "val"],
        callbacks=callbacks,
    )

    # メトリクス計算
    y_pred_val = model.predict(X_val)
    mae = np.mean(np.abs(y_val - y_pred_val))
    direction_acc = np.mean(np.sign(y_val) == np.sign(y_pred_val))
    ic = np.corrcoef(y_val, y_pred_val)[0, 1]

    metrics = {
        "mae": float(mae),
        "direction_accuracy": float(direction_acc),
        "information_coefficient": float(ic),
        "best_iteration": model.best_iteration,
        "num_features": X.shape[1],
        "train_samples": len(X_train),
        "val_samples": len(X_val),
    }

    log.info(f"学習完了: MAE={mae:.6f}, 方向精度={direction_acc:.4f}, IC={ic:.4f}")
    return model, metrics
