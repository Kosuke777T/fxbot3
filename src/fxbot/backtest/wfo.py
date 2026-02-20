"""ウォークフォワード最適化（WFO）."""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from fxbot.backtest.engine import BacktestEngine, BacktestResult
from fxbot.backtest.metrics import calc_all_metrics
from fxbot.config import Settings
from fxbot.features.builder import build_feature_matrix
from fxbot.model.predictor import Predictor
from fxbot.model.shap_analysis import select_features
from fxbot.model.trainer import prepare_dataset, train_model
from fxbot.logger import get_logger

log = get_logger(__name__)


@dataclass
class WFOFold:
    fold_num: int
    train_start: pd.Timestamp
    train_end: pd.Timestamp
    test_start: pd.Timestamp
    test_end: pd.Timestamp
    train_metrics: dict
    test_metrics: dict
    num_trades: int


@dataclass
class WFOResult:
    folds: list[WFOFold]
    combined_equity: pd.Series
    combined_trades: pd.DataFrame
    overall_metrics: dict


def run_wfo(
    multi_tf_data: dict[str, pd.DataFrame],
    settings: Settings,
    base_timeframe: str = "M5",
) -> WFOResult:
    """ウォークフォワード最適化を実行.

    ローリングウィンドウで train → SHAP特徴量選択 → 再学習 → バックテスト
    """
    cfg = settings.backtest
    train_days = cfg.train_window_days
    test_days = cfg.test_window_days

    # 特徴量マトリクス構築
    feature_matrix = build_feature_matrix(multi_tf_data, base_timeframe)
    log.info(f"WFO用特徴量マトリクス: {feature_matrix.shape}")

    start = feature_matrix.index[0]
    end = feature_matrix.index[-1]

    # データ期間がWFOウィンドウより短い場合、自動調整
    data_span_days = (end - start).days
    if data_span_days < train_days + test_days:
        log.warning(
            f"データ期間({data_span_days}日)がWFOウィンドウ"
            f"({train_days}+{test_days}日)より短いため自動調整"
        )
        train_days = int(data_span_days * 0.7)
        test_days = data_span_days - train_days
        log.info(f"調整後: train={train_days}日, test={test_days}日")

    folds: list[WFOFold] = []
    all_equities = []
    all_trades = []

    fold_num = 0
    cursor = start + pd.Timedelta(days=train_days)

    while cursor + pd.Timedelta(days=test_days) <= end:
        fold_num += 1
        train_start = cursor - pd.Timedelta(days=train_days)
        train_end = cursor
        test_start = cursor
        test_end = cursor + pd.Timedelta(days=test_days)

        log.info(f"=== WFO Fold {fold_num}: train {train_start.date()}~{train_end.date()}, "
                 f"test {test_start.date()}~{test_end.date()} ===")

        # train/testデータ分割
        # 学習データ末尾からhorizonバー分を除去（purge）
        # ターゲット(close.shift(-horizon))がテスト期間の価格を参照する問題を防止
        horizon = settings.trading.prediction_horizon
        train_data = feature_matrix[train_start:train_end].iloc[:-horizon]
        test_data = feature_matrix[test_start:test_end]

        if len(train_data) < 100 or len(test_data) < 10:
            log.warning(f"Fold {fold_num}: データ不足、スキップ")
            cursor += pd.Timedelta(days=test_days)
            continue

        # モデルモード（設定から取得）
        model_mode = getattr(settings.model, "mode", "regression")

        # 1. 全特徴量で学習
        horizon = settings.trading.prediction_horizon
        X_train, y_train, feat_names = prepare_dataset(train_data, horizon, mode=model_mode)
        if len(X_train) < 100:
            cursor += pd.Timedelta(days=test_days)
            continue

        model_full, _ = train_model(X_train, y_train, settings, mode=model_mode)

        # 2. SHAP特徴量選択
        selected, _ = select_features(
            model_full, X_train,
            top_pct=settings.model.shap_top_pct,
        )

        # 3. 選択された特徴量で再学習
        X_train_sel, y_train_sel, _ = prepare_dataset(train_data, horizon, selected, mode=model_mode)
        model, train_metrics = train_model(X_train_sel, y_train_sel, settings, mode=model_mode)

        # 4. テスト期間で予測
        predictor = Predictor(model, selected, mode=model_mode)
        if model_mode == "classification":
            pred_df = predictor.predict_with_confidence(test_data)
            # direction: 1(up)→正, -1(down)→負、confidenceで重み付け
            predictions = pred_df["direction"].astype(float) * pred_df["confidence"]
        else:
            predictions = predictor.predict(test_data)

        # 5. バックテスト
        engine = BacktestEngine(settings)
        bt_result = engine.run(test_data, predictions)

        # メトリクス
        trades_df = pd.DataFrame([{
            "entry_time": t.entry_time, "exit_time": t.exit_time,
            "side": t.side, "entry_price": t.entry_price,
            "exit_price": t.exit_price, "lot": t.lot,
            "pnl": t.pnl, "exit_reason": t.exit_reason,
        } for t in bt_result.trades]) if bt_result.trades else pd.DataFrame(columns=["pnl"])

        test_metrics = {}
        if not bt_result.equity.empty:
            test_metrics = calc_all_metrics(bt_result.equity, trades_df)

        folds.append(WFOFold(
            fold_num=fold_num,
            train_start=train_start,
            train_end=train_end,
            test_start=test_start,
            test_end=test_end,
            train_metrics=train_metrics,
            test_metrics=test_metrics,
            num_trades=len(bt_result.trades),
        ))

        all_equities.append(bt_result.equity)
        if not trades_df.empty:
            all_trades.append(trades_df)

        cursor += pd.Timedelta(days=test_days)

    # 結果統合
    combined_equity = pd.concat(all_equities) if all_equities else pd.Series(dtype=float)
    combined_trades = pd.concat(all_trades, ignore_index=True) if all_trades else pd.DataFrame(columns=["pnl"])
    overall_metrics = calc_all_metrics(combined_equity, combined_trades) if not combined_equity.empty else {}

    log.info(f"WFO完了: {len(folds)}フォールド, {len(combined_trades)}トレード")

    return WFOResult(
        folds=folds,
        combined_equity=combined_equity,
        combined_trades=combined_trades,
        overall_metrics=overall_metrics,
    )
