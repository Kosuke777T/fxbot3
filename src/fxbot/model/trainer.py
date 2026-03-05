"""LightGBM学習パイプライン（回帰 + 分類対応）."""

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
    """対数リターンのターゲットを構築（回帰用）.

    y = log(close[t+horizon] / close[t])
    """
    close = df["close"]
    target = np.log(close.shift(-horizon) / close)
    target.name = "target"
    return target


def build_target_classification(
    df: pd.DataFrame,
    horizon: int = 6,
    sl_mult: float = 2.0,
    tp_mult: float = 2.0,
    vol_lookback: int = 20,
) -> pd.Series:
    """Triple Barrier ラベルのターゲットを構築（分類用）.

    Returns:
        ラベルSeries: {-1, 0, 1} → LightGBM用に {0, 1, 2} にマッピング
        -1 (SL hit) → 0, 0 (no hit) → 1, 1 (TP hit) → 2
    """
    from fxbot.model.labeling import compute_triple_barrier_labels

    labels = compute_triple_barrier_labels(
        df, horizon=horizon, sl_mult=sl_mult, tp_mult=tp_mult,
        vol_lookback=vol_lookback,
    )
    # {-1, 0, 1} → {0, 1, 2} にマッピング（LightGBMのmulticlass用）
    mapped = labels + 1  # -1→0, 0→1, 1→2
    mapped.name = "target"
    return mapped


def prepare_dataset(
    feature_matrix: pd.DataFrame,
    horizon: int = 6,
    selected_features: list[str] | None = None,
    mode: str = "regression",
) -> tuple[pd.DataFrame, pd.Series, list[str]]:
    """特徴量マトリクスからX, yを準備.

    Args:
        feature_matrix: 特徴量マトリクス
        horizon: 予測ホライゾン
        selected_features: 使用する特徴量リスト
        mode: "regression" | "classification"

    Returns:
        (X, y, feature_names) のタプル
    """
    if mode == "classification":
        target = build_target_classification(feature_matrix, horizon)
    else:
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

    log.info(f"データセット準備 ({mode}): {X.shape[0]}サンプル × {X.shape[1]}特徴量")
    return X, y, feat_cols


def _make_time_weights(n: int, decay: float = 0.9995) -> np.ndarray:
    """時系列サンプルウェイトを生成（最新データを重視）.

    最古サンプルを基準1.0として、最新は (1/decay)^n 倍重くなる。
    decayが大きいほど均一に近い（0.9995で約50%前のデータは約22%の重み）。
    """
    indices = np.arange(n)
    weights = decay ** (n - 1 - indices)  # 最新 → weight=1.0, 古い → 小さい
    weights = weights / weights.mean()     # 平均1に正規化
    return weights.astype(np.float32)


def train_model(
    X: pd.DataFrame,
    y: pd.Series,
    settings: Settings,
    val_ratio: float = 0.2,
    mode: str = "regression",
    use_time_weights: bool = True,
) -> tuple[lgb.Booster, dict]:
    """LightGBMモデルを学習.

    時系列データのため、末尾をvalidationに使用（シャッフルしない）。
    最近のデータを重視するサンプルウェイトを適用（概念ドリフト対策）。

    Args:
        X: 特徴量
        y: ターゲット
        settings: 設定
        val_ratio: 検証データ割合
        mode: "regression" | "classification"
        use_time_weights: 時系列サンプルウェイトを使用するか

    Returns:
        (model, metrics) のタプル
    """
    cfg = settings.model

    # 時系列分割（末尾をval）
    split_idx = int(len(X) * (1 - val_ratio))
    X_train, X_val = X.iloc[:split_idx], X.iloc[split_idx:]
    y_train, y_val = y.iloc[:split_idx], y.iloc[split_idx:]

    log.info(f"学習 ({mode}): {len(X_train)}サンプル, 検証: {len(X_val)}サンプル")

    # 時系列サンプルウェイト（最近のデータほど重く）
    train_weights = _make_time_weights(len(X_train)) if use_time_weights else None
    if use_time_weights:
        log.info(f"サンプルウェイト適用 (decay=0.9995): "
                 f"最古={train_weights[0]:.3f}, 最新={train_weights[-1]:.3f}")

    # パラメータ構築
    params = dict(cfg.lgbm_params)
    if mode == "classification":
        params["objective"] = "multiclass"
        params["num_class"] = 3
        params["metric"] = "multi_logloss"

    train_data = lgb.Dataset(X_train, label=y_train, weight=train_weights)
    val_data = lgb.Dataset(X_val, label=y_val, reference=train_data)

    callbacks = [
        lgb.early_stopping(cfg.early_stopping_rounds),
        lgb.log_evaluation(100),
    ]

    model = lgb.train(
        params=params,
        train_set=train_data,
        num_boost_round=cfg.num_boost_round,
        valid_sets=[train_data, val_data],
        valid_names=["train", "val"],
        callbacks=callbacks,
    )

    # メトリクス計算
    if mode == "classification":
        metrics = _calc_classification_metrics(model, X_val, y_val, X)
    else:
        metrics = _calc_regression_metrics(model, X_val, y_val, X)

    metrics["best_iteration"] = model.best_iteration
    metrics["num_features"] = X.shape[1]
    metrics["train_samples"] = len(X_train)
    metrics["val_samples"] = len(X_val)
    metrics["mode"] = mode

    return model, metrics


def _calc_regression_metrics(
    model: lgb.Booster, X_val: pd.DataFrame, y_val: pd.Series, X: pd.DataFrame
) -> dict:
    y_pred_val = model.predict(X_val)
    mae = np.mean(np.abs(y_val - y_pred_val))
    direction_acc = np.mean(np.sign(y_val) == np.sign(y_pred_val))
    ic = np.corrcoef(y_val, y_pred_val)[0, 1]

    log.info(f"学習完了: MAE={mae:.6f}, 方向精度={direction_acc:.4f}, IC={ic:.4f}")
    return {
        "mae": float(mae),
        "direction_accuracy": float(direction_acc),
        "information_coefficient": float(ic),
    }


def _calc_classification_metrics(
    model: lgb.Booster, X_val: pd.DataFrame, y_val: pd.Series, X: pd.DataFrame
) -> dict:
    # predict returns (n_samples, 3) probabilities for multiclass
    y_pred_proba = model.predict(X_val)
    y_pred_class = np.argmax(y_pred_proba, axis=1)
    y_true = y_val.values.astype(int)

    accuracy = np.mean(y_pred_class == y_true)

    # Per-class precision/recall
    per_class = {}
    class_names = {0: "down", 1: "neutral", 2: "up"}
    for cls in range(3):
        pred_mask = y_pred_class == cls
        true_mask = y_true == cls
        tp = np.sum(pred_mask & true_mask)
        precision = tp / pred_mask.sum() if pred_mask.sum() > 0 else 0.0
        recall = tp / true_mask.sum() if true_mask.sum() > 0 else 0.0
        per_class[class_names[cls]] = {
            "precision": float(precision),
            "recall": float(recall),
            "support": int(true_mask.sum()),
        }

    # 方向精度（up vs down のみ。neutralは除外）
    dir_mask = (y_true != 1)  # neutral以外
    if dir_mask.sum() > 0:
        pred_dir = y_pred_proba[:, 2] > y_pred_proba[:, 0]  # up probability > down
        true_dir = y_true[dir_mask] == 2  # true class is up
        direction_acc = np.mean(pred_dir[dir_mask] == true_dir)
    else:
        direction_acc = 0.0

    log.info(f"学習完了 (分類): 精度={accuracy:.4f}, 方向精度={direction_acc:.4f}, "
             f"クラス分布={per_class}")
    return {
        "accuracy": float(accuracy),
        "direction_accuracy": float(direction_acc),
        "per_class": per_class,
    }
