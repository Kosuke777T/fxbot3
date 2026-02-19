"""QThreadワーカー — データ取得/学習/ライブ取引."""

from __future__ import annotations

import time
import traceback
from pathlib import Path

from PySide6.QtCore import QThread, Signal, QObject

from fxbot.config import Settings
from fxbot.logger import get_logger

log = get_logger(__name__)


class WorkerSignals(QObject):
    """ワーカー共通シグナル."""
    started = Signal()
    finished = Signal(object)  # result
    error = Signal(str)
    progress = Signal(str)


class DataFetchWorker(QThread):
    """OHLCV取得ワーカー."""
    signals = WorkerSignals()

    def __init__(self, symbol: str, settings: Settings, parent=None):
        super().__init__(parent)
        self.symbol = symbol
        self.settings = settings
        self._running = True

    def run(self):
        try:
            self.signals.started.emit()
            self.signals.progress.emit(f"{self.symbol} データ取得中...")

            from fxbot.mt5.data_feed import fetch_multi_timeframe
            data = fetch_multi_timeframe(self.symbol, self.settings)

            self.signals.finished.emit(data)
        except Exception as e:
            self.signals.error.emit(f"データ取得エラー: {e}\n{traceback.format_exc()}")

    def stop(self):
        self._running = False


class TrainWorker(QThread):
    """モデル学習ワーカー."""
    signals = WorkerSignals()

    def __init__(self, multi_tf_data: dict, symbol: str, settings: Settings, parent=None):
        super().__init__(parent)
        self.multi_tf_data = multi_tf_data
        self.symbol = symbol
        self.settings = settings

    def run(self):
        try:
            self.signals.started.emit()
            self.signals.progress.emit("特徴量構築中...")

            from fxbot.features.builder import build_feature_matrix
            from fxbot.model.trainer import prepare_dataset, train_model
            from fxbot.model.shap_analysis import select_features
            from fxbot.model.registry import save_model

            # 特徴量構築
            fm = build_feature_matrix(self.multi_tf_data, self.settings.data.base_timeframe)
            self.signals.progress.emit(f"特徴量: {fm.shape[1]}列")

            # 全特徴量で学習
            horizon = self.settings.trading.prediction_horizon
            X, y, feat_names = prepare_dataset(fm, horizon)
            self.signals.progress.emit("学習中（全特徴量）...")
            model_full, _ = train_model(X, y, self.settings)

            # SHAP特徴量選択
            self.signals.progress.emit("SHAP計算中...")
            selected, importance_df = select_features(
                model_full, X,
                top_pct=self.settings.model.shap_top_pct,
            )

            # 選択特徴量で再学習
            self.signals.progress.emit(f"再学習中（{len(selected)}特徴量）...")
            X_sel, y_sel, _ = prepare_dataset(fm, horizon, selected)
            model, metrics = train_model(X_sel, y_sel, self.settings)

            # 保存
            tf = self.settings.data.base_timeframe
            model_dir = save_model(model, selected, metrics, self.symbol, tf, self.settings)

            result = {
                "model": model,
                "feature_names": selected,
                "metrics": metrics,
                "importance": importance_df,
                "model_dir": str(model_dir),
            }
            self.signals.finished.emit(result)

        except Exception as e:
            self.signals.error.emit(f"学習エラー: {e}\n{traceback.format_exc()}")


class BacktestWorker(QThread):
    """バックテストワーカー."""
    signals = WorkerSignals()

    def __init__(self, multi_tf_data: dict, settings: Settings, parent=None):
        super().__init__(parent)
        self.multi_tf_data = multi_tf_data
        self.settings = settings

    def run(self):
        try:
            self.signals.started.emit()
            self.signals.progress.emit("WFO実行中...")

            from fxbot.backtest.wfo import run_wfo
            result = run_wfo(self.multi_tf_data, self.settings)

            self.signals.finished.emit(result)

        except Exception as e:
            self.signals.error.emit(f"バックテストエラー: {e}\n{traceback.format_exc()}")


class TradingWorker(QThread):
    """ライブ取引ワーカー — Phase 7で本実装."""
    signals = WorkerSignals()

    def __init__(self, settings: Settings, parent=None):
        super().__init__(parent)
        self.settings = settings
        self._running = True

    def run(self):
        try:
            self.signals.started.emit()
            self.signals.progress.emit("ライブ取引開始...")

            from fxbot.mt5.connection import connect, is_connected, reconnect
            from fxbot.mt5.data_feed import fetch_and_cache
            from fxbot.features.builder import build_feature_matrix
            from fxbot.model.predictor import Predictor
            from fxbot.model.registry import load_model
            from fxbot.strategy.signal import generate_signal, SignalAction
            from fxbot.risk.portfolio import can_open_position, get_open_positions
            from fxbot.mt5.execution import send_order
            from fxbot.risk.stop_manager import update_trailing_stop, StopLevels

            import MetaTrader5 as mt5

            # 学習済みモデルが存在するシンボルを自動検出
            from fxbot.model.registry import list_models
            tf = self.settings.data.base_timeframe

            all_trained = list_models(self.settings)
            # シンボルごとに最新モデルだけ残す
            seen_symbols = set()
            models: dict[str, tuple] = {}
            for meta_info in all_trained:
                sym = meta_info.get("symbol", "")
                if sym in seen_symbols or meta_info.get("timeframe") != tf:
                    continue
                seen_symbols.add(sym)
                model_dir = Path(meta_info["path"])
                model, meta = load_model(model_dir)
                models[sym] = (Predictor(model, meta["feature_names"]), meta)
                log.info(f"取引モデル読込: {sym} ({model_dir.name})")

            if not models:
                self.signals.error.emit("取引可能なモデルがありません。先に学習を実行してください。")
                return

            self.signals.progress.emit(f"取引対象: {list(models.keys())}")

            while self._running:
                if not is_connected():
                    self.signals.progress.emit("再接続中...")
                    if not reconnect(self.settings):
                        time.sleep(30)
                        continue

                for sym, (predictor, meta) in models.items():
                    try:
                        # データ取得
                        from fxbot.mt5.data_feed import fetch_multi_timeframe
                        data = fetch_multi_timeframe(sym, self.settings)
                        if not data:
                            continue

                        # 特徴量構築
                        fm = build_feature_matrix(data, self.settings.data.base_timeframe)
                        if fm.empty:
                            continue

                        # 予測
                        pred_val = predictor.predict_latest(fm)

                        # シグナル生成
                        current_price = fm["close"].iloc[-1]
                        atr = fm["atr_14"].iloc[-1] if "atr_14" in fm.columns else current_price * 0.001

                        account_info = mt5.account_info()
                        balance = account_info.balance if account_info else 10000

                        sym_info = mt5.symbol_info(sym)
                        point = sym_info.point if sym_info else 0.0001

                        signal = generate_signal(
                            sym, pred_val, current_price, atr, balance, point, self.settings
                        )

                        if signal.action != SignalAction.HOLD and can_open_position(sym, self.settings):
                            result = send_order(
                                sym, signal.action.value, signal.lot, signal.sl, signal.tp
                            )
                            if result:
                                self.signals.progress.emit(
                                    f"約定: {signal.action.value.upper()} {sym} "
                                    f"{signal.lot}lot @ {result['price']}"
                                )

                        # トレーリングストップ更新
                        positions = get_open_positions()
                        for pos in positions:
                            if pos["symbol"] == sym:
                                from fxbot.mt5.execution import modify_position
                                stops = StopLevels(
                                    sl=pos["sl"], tp=pos["tp"],
                                    trailing_activation=atr * self.settings.risk.trailing_activation_atr,
                                    trailing_distance=atr * self.settings.risk.trailing_atr_multiplier,
                                )
                                new_sl = update_trailing_stop(
                                    pos["type"], pos["price_current"],
                                    pos["price_open"], pos["sl"], stops,
                                )
                                if new_sl is not None:
                                    modify_position(pos["ticket"], sl=new_sl)

                    except Exception as e:
                        log.error(f"取引ループエラー ({sym}): {e}")

                # 次のバー確定まで待機（M5 = 300秒）
                wait_seconds = 300
                for _ in range(wait_seconds):
                    if not self._running:
                        break
                    time.sleep(1)

            self.signals.progress.emit("取引停止")
            self.signals.finished.emit(None)

        except Exception as e:
            self.signals.error.emit(f"取引ワーカーエラー: {e}\n{traceback.format_exc()}")

    def stop(self):
        self._running = False
