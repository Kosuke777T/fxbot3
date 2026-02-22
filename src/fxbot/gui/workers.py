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
    prediction = Signal(dict)  # {symbol: pred_val}


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

            # モデルモード取得
            model_mode = self.settings.model.mode

            self.signals.progress.emit(f"学習モード: {model_mode}")

            # 特徴量構築
            fm = build_feature_matrix(self.multi_tf_data, self.settings.data.base_timeframe)
            self.signals.progress.emit(f"特徴量: {fm.shape[1]}列")

            # 全特徴量で学習
            horizon = self.settings.trading.prediction_horizon
            X, y, feat_names = prepare_dataset(fm, horizon, mode=model_mode)
            self.signals.progress.emit(f"学習中（全特徴量, {model_mode}）...")
            model_full, _ = train_model(X, y, self.settings, mode=model_mode)

            # SHAP特徴量選択
            self.signals.progress.emit("SHAP計算中...")
            selected, importance_df = select_features(
                model_full, X,
                top_pct=self.settings.model.shap_top_pct,
            )

            # 選択特徴量で再学習
            self.signals.progress.emit(f"再学習中（{len(selected)}特徴量）...")
            X_sel, y_sel, _ = prepare_dataset(fm, horizon, selected, mode=model_mode)
            model, metrics = train_model(X_sel, y_sel, self.settings, mode=model_mode)
            metrics["mode"] = model_mode

            # 保存
            tf = self.settings.data.base_timeframe
            model_dir = save_model(model, selected, metrics, self.symbol, tf, self.settings)

            result = {
                "model": model,
                "feature_names": selected,
                "metrics": metrics,
                "importance": importance_df,
                "model_dir": str(model_dir),
                "mode": model_mode,
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


class WeekendRetrainWorker(QThread):
    """週末自動WFO→学習ワーカー."""
    signals = WorkerSignals()

    def __init__(self, multi_tf_data: dict, symbol: str, settings: Settings, parent=None):
        super().__init__(parent)
        self.multi_tf_data = multi_tf_data
        self.symbol = symbol
        self.settings = settings

    def run(self):
        try:
            self.signals.started.emit()
            rt_cfg = self.settings.retraining

            # Step 1: WFO実行
            self.signals.progress.emit("週末自動再学習: WFO実行中...")
            from fxbot.backtest.wfo import run_wfo
            wfo_result = run_wfo(self.multi_tf_data, self.settings)
            metrics = wfo_result.overall_metrics if hasattr(wfo_result, "overall_metrics") else {}

            wfo_win_rate = metrics.get("win_rate", 0.0)
            wfo_sharpe = metrics.get("sharpe", 0.0)
            self.signals.progress.emit(
                f"WFO完了: 勝率={wfo_win_rate:.1%} Sharpe={wfo_sharpe:.2f}"
            )

            # Step 2: 合格判定
            ok = (wfo_win_rate >= rt_cfg.wfo_min_win_rate
                  and wfo_sharpe >= rt_cfg.wfo_min_sharpe)

            if not ok:
                reason = (
                    f"WFO基準未達 "
                    f"(勝率{wfo_win_rate:.1%}<{rt_cfg.wfo_min_win_rate:.1%} "
                    f"or Sharpe{wfo_sharpe:.2f}<{rt_cfg.wfo_min_sharpe:.2f})"
                )
                self.signals.progress.emit(f"週末自動再学習: {reason} → スキップ")
                self.signals.finished.emit({
                    "wfo_result": wfo_result,
                    "wfo_win_rate": wfo_win_rate,
                    "wfo_sharpe": wfo_sharpe,
                    "trained": False,
                    "reason": reason,
                })
                return

            # Step 3: 学習実行（TrainWorkerと同じロジック）
            self.signals.progress.emit("週末自動再学習: WFO合格 → 学習開始...")
            from fxbot.features.builder import build_feature_matrix
            from fxbot.model.trainer import prepare_dataset, train_model
            from fxbot.model.shap_analysis import select_features
            from fxbot.model.registry import save_model

            model_mode = self.settings.model.mode
            horizon = self.settings.trading.prediction_horizon

            fm = build_feature_matrix(self.multi_tf_data, self.settings.data.base_timeframe)
            self.signals.progress.emit(f"特徴量: {fm.shape[1]}列")

            X, y, _ = prepare_dataset(fm, horizon, mode=model_mode)
            self.signals.progress.emit("全特徴量で学習中...")
            model_full, _ = train_model(X, y, self.settings, mode=model_mode)

            self.signals.progress.emit("SHAP計算中...")
            selected, importance_df = select_features(
                model_full, X, top_pct=self.settings.model.shap_top_pct,
            )

            self.signals.progress.emit(f"選択特徴量で再学習中（{len(selected)}列）...")
            X_sel, y_sel, _ = prepare_dataset(fm, horizon, selected, mode=model_mode)
            model, train_metrics = train_model(X_sel, y_sel, self.settings, mode=model_mode)
            train_metrics["mode"] = model_mode

            tf = self.settings.data.base_timeframe
            model_dir = save_model(model, selected, train_metrics, self.symbol, tf, self.settings)
            self.signals.progress.emit(f"週末自動再学習完了: {model_dir}")

            self.signals.finished.emit({
                "wfo_result": wfo_result,
                "wfo_win_rate": wfo_win_rate,
                "wfo_sharpe": wfo_sharpe,
                "trained": True,
                "reason": "WFO合格",
                "train_metrics": train_metrics,
                "model_dir": str(model_dir),
            })

        except Exception as e:
            self.signals.error.emit(f"週末自動再学習エラー: {e}\n{traceback.format_exc()}")


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
            from datetime import datetime

            # TradeLogger & ModelMonitor 初期化
            trade_logger = None
            model_monitor = None
            if self.settings.trade_logging.enabled:
                from fxbot.trade_logger import TradeLogger, TradeRecord
                from fxbot.model.monitor import ModelMonitor
                db_path = self.settings.resolve_path(self.settings.trade_logging.db_path)
                trade_logger = TradeLogger(db_path)
                rt_cfg = self.settings.retraining
                model_monitor = ModelMonitor(
                    trade_logger,
                    window=rt_cfg.monitor_window,
                    min_win_rate=rt_cfg.min_win_rate,
                    min_sharpe=rt_cfg.min_sharpe,
                )
                log.info("取引ログ・モデル監視有効化")

            # モデルモード判定
            model_mode = getattr(self.settings.model, "mode", "regression")

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
                # メタデータからモードを取得（なければ設定から）
                pred_mode = meta.get("mode", model_mode)
                models[sym] = (Predictor(model, meta["feature_names"], mode=pred_mode), meta)
                log.info(f"取引モデル読込: {sym} ({model_dir.name}) mode={pred_mode}")

            if not models:
                self.signals.error.emit("取引可能なモデルがありません。先に学習を実行してください。")
                return

            self.signals.progress.emit(f"取引対象: {list(models.keys())}")

            # クローズ検出用: 前回ループのチケット集合
            prev_tickets: dict[str, set[int]] = {sym: set() for sym in models}

            while self._running:
                predictions_this_bar: dict[str, float] = {}
                if not is_connected():
                    self.signals.progress.emit("再接続中...")
                    if not reconnect(self.settings):
                        time.sleep(30)
                        continue

                for sym, (predictor, meta) in models.items():
                    try:
                        # クローズ検出: 前回あったチケットが消えた → exit記録
                        if trade_logger and prev_tickets[sym]:
                            current_positions = get_open_positions()
                            current_tickets = {
                                p["ticket"] for p in current_positions if p["symbol"] == sym
                            }
                            closed_tickets = prev_tickets[sym] - current_tickets
                            for ticket in closed_tickets:
                                # MT5の履歴から約定情報を取得
                                try:
                                    from fxbot.mt5.execution import get_deal_history
                                    deal = get_deal_history(ticket)
                                    if deal:
                                        trade_logger.log_exit(
                                            ticket=ticket,
                                            exit_price=deal.get("price", 0.0),
                                            exit_time=deal.get("time", datetime.now().isoformat()),
                                            exit_reason=deal.get("reason", "unknown"),
                                            pnl=deal.get("profit", 0.0),
                                        )
                                except Exception as ex:
                                    log.warning(f"クローズ記録失敗 ticket={ticket}: {ex}")

                        # データ取得
                        from fxbot.mt5.data_feed import fetch_multi_timeframe
                        data = fetch_multi_timeframe(sym, self.settings)
                        if not data:
                            continue

                        # 特徴量構築
                        fm = build_feature_matrix(data, self.settings.data.base_timeframe)
                        if fm.empty:
                            continue

                        # 予測・信頼度
                        confidence = 1.0
                        if predictor.mode == "classification":
                            direction, confidence = predictor.predict_latest_with_confidence(fm)
                            pred_val = float(direction) * confidence  # 方向 × 信頼度を予測値として使用
                        else:
                            pred_val = predictor.predict_latest(fm)

                        predictions_this_bar[sym] = pred_val

                        # シグナル生成
                        current_price = fm["close"].iloc[-1]
                        atr = fm["atr_14"].iloc[-1] if "atr_14" in fm.columns else current_price * 0.001

                        account_info = mt5.account_info()
                        balance = account_info.balance if account_info else 10000

                        sym_info = mt5.symbol_info(sym)
                        point = sym_info.point if sym_info else 0.0001

                        # スプレッド取得（pips換算）
                        spread_pips = 0.0
                        if sym_info:
                            spread_pips = sym_info.spread * sym_info.point / 0.0001

                        # 市場レジーム判定
                        regime = "trend_up"
                        if "regime_ranging" in fm.columns:
                            from fxbot.features.regime import detect_regime
                            adx_val = fm["regime_adx"].iloc[-1] if "regime_adx" in fm.columns else 25.0
                            di_p = fm["adx_pos"].iloc[-1] if "adx_pos" in fm.columns else 20.0
                            di_n = fm["adx_neg"].iloc[-1] if "adx_neg" in fm.columns else 15.0
                            regime = detect_regime(adx_val, di_p, di_n)

                        # 現在時刻（UTC）
                        current_hour_utc = datetime.utcnow().hour

                        signal = generate_signal(
                            sym, pred_val, current_price, atr, balance, point,
                            self.settings, confidence=confidence,
                            spread_pips=spread_pips,
                            current_hour_utc=current_hour_utc,
                            regime=regime,
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

                                # 取引ログ記録
                                if trade_logger:
                                    from fxbot.trade_logger import TradeRecord
                                    record = TradeRecord(
                                        timestamp=datetime.now().isoformat(),
                                        symbol=sym,
                                        direction=signal.action.value,
                                        entry_price=result["price"],
                                        sl=signal.sl,
                                        tp=signal.tp,
                                        lot=signal.lot,
                                        prediction=pred_val,
                                        confidence=confidence,
                                        atr=atr,
                                        balance=balance,
                                        ticket=result.get("ticket"),
                                        model_version=meta.get("created_at", "unknown"),
                                    )
                                    trade_logger.log_entry(record)

                        # トレーリングストップ更新 & チケット集合更新
                        positions = get_open_positions()
                        prev_tickets[sym] = set()
                        for pos in positions:
                            if pos["symbol"] == sym:
                                prev_tickets[sym].add(pos["ticket"])
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

                # 予測値をダッシュボードに送信
                if predictions_this_bar:
                    self.signals.prediction.emit(predictions_this_bar)

                # ModelMonitorチェック（取引ログが有効な場合）
                if model_monitor and self.settings.retraining.enabled:
                    result = model_monitor.check()
                    if not result["healthy"]:
                        m = result["metrics"]
                        self.signals.progress.emit(
                            f"モデル劣化検知: 勝率={m.get('win_rate', 0):.1%} "
                            f"Sharpe={m.get('sharpe', 0):.2f} → 再学習推奨"
                        )
                        log.warning(f"モデル劣化: {result['warnings']}")

                # 次のM5バー確定まで待機（バー境界同期）
                self._wait_for_next_bar()

            if trade_logger:
                trade_logger.close()

            self.signals.progress.emit("取引停止")
            self.signals.finished.emit(None)

        except Exception as e:
            self.signals.error.emit(f"取引ワーカーエラー: {e}\n{traceback.format_exc()}")

    def _wait_for_next_bar(self) -> None:
        """次のM5バー確定タイミング（分の末尾が0/5）+ 5秒まで待機."""
        import datetime as dt
        now = dt.datetime.now()
        # 次の5分境界を計算
        minute = now.minute
        next_bar_minute = ((minute // 5) + 1) * 5
        if next_bar_minute >= 60:
            next_bar = now.replace(minute=0, second=5, microsecond=0) + dt.timedelta(hours=1)
        else:
            next_bar = now.replace(minute=next_bar_minute, second=5, microsecond=0)

        wait_seconds = (next_bar - now).total_seconds()
        # 安全対策: 最低10秒、最大310秒
        wait_seconds = max(10, min(310, wait_seconds))

        log.debug(f"次バー待機: {wait_seconds:.0f}秒 (次バー: {next_bar.strftime('%H:%M:%S')})")
        for _ in range(int(wait_seconds)):
            if not self._running:
                break
            time.sleep(1)

    def stop(self):
        self._running = False
