"""バー単位バックテストシミュレーション."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

import numpy as np
import pandas as pd

from fxbot.config import Settings
from fxbot.logger import get_logger
from fxbot.strategy.signal import SignalAction, generate_signal
from fxbot.risk.stop_manager import calculate_stops

log = get_logger(__name__)


class Side(str, Enum):
    BUY = "buy"
    SELL = "sell"


@dataclass
class Position:
    entry_time: pd.Timestamp
    side: Side
    entry_price: float
    lot: float
    sl: float
    tp: float
    trailing_sl: float | None = None
    tp_triggered: bool = False  # TP到達後トレーリング継続フラグ


@dataclass
class PendingEntry:
    signal_time: pd.Timestamp
    action: SignalAction
    prediction: float
    lot: float
    atr: float


@dataclass
class Trade:
    entry_time: pd.Timestamp
    exit_time: pd.Timestamp
    side: str
    entry_price: float
    exit_price: float
    lot: float
    pnl: float
    exit_reason: str


@dataclass
class BacktestResult:
    equity: pd.Series
    closed_equity: pd.Series
    trades: list[Trade]
    settings: dict


class BacktestEngine:
    """バー単位のバックテストエンジン."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self.initial_balance = settings.backtest.initial_balance
        self.spread_pips = settings.backtest.spread_pips
        self.slippage_pips = settings.backtest.slippage_pips
        self.max_positions = settings.trading.max_positions

    def _resolve_pip_size(
        self,
        feature_matrix: pd.DataFrame,
        symbol: str | None = None,
        point: float | None = None,
    ) -> float:
        """シンボル桁に応じた 1pip の値幅を返す."""
        if symbol:
            try:
                from fxbot.mt5.symbols import load_symbols

                for item in load_symbols(self.settings):
                    if item.get("name") != symbol:
                        continue
                    symbol_point = float(item.get("point") or 0.0)
                    digits = int(item.get("digits") or 0)
                    if symbol_point > 0:
                        return symbol_point * 10 if digits in (3, 5) else symbol_point
            except Exception as e:
                log.debug(f"pip size 解決に失敗: {symbol} {e}")

        resolved_point = float(point or 0.0)
        if resolved_point > 0:
            if resolved_point in (0.001, 0.00001):
                return resolved_point * 10
            return resolved_point

        if "close" in feature_matrix.columns and not feature_matrix.empty:
            price = float(feature_matrix["close"].median())
            # JPY系など価格水準が高い通貨は 1pip=0.01 とみなす
            if price >= 20:
                return 0.01

        return 0.0001

    @staticmethod
    def _resolve_regime(row: pd.Series) -> str:
        """特徴量行から市場レジームを解決."""
        if "regime_ranging" in row.index and bool(row["regime_ranging"]):
            return "ranging"
        if "regime_trend_down" in row.index and bool(row["regime_trend_down"]):
            return "trend_down"
        return "trend_up"

    @staticmethod
    def _resolve_h4_regime(row: pd.Series) -> str:
        """特徴量行からH4レジームを解決."""
        if "h4_regime_trend_up" in row.index and bool(row["h4_regime_trend_up"]):
            return "trend_up"
        if "h4_regime_trend_down" in row.index and bool(row["h4_regime_trend_down"]):
            return "trend_down"
        return "ranging"

    def _apply_exit_slippage(self, side: Side, exit_price: float, slippage: float) -> float:
        """決済価格に不利な方向のスリッページを反映."""
        if side == Side.BUY:
            return exit_price - slippage
        return exit_price + slippage

    def _resolve_point_size(
        self,
        feature_matrix: pd.DataFrame,
        symbol: str | None = None,
        point: float | None = None,
        pip_size: float | None = None,
    ) -> float:
        """シンボル桁に応じた point 値を返す."""
        if symbol:
            try:
                from fxbot.mt5.symbols import load_symbols

                for item in load_symbols(self.settings):
                    if item.get("name") == symbol:
                        symbol_point = float(item.get("point") or 0.0)
                        if symbol_point > 0:
                            return symbol_point
                        break
            except Exception as e:
                log.debug(f"point size 解決に失敗: {symbol} {e}")

        if point is not None and point > 0:
            return float(point)

        if pip_size in (0.01, 0.0001):
            return pip_size / 10
        return float(pip_size or 0.0001)

    def _resolve_spread_pips(
        self,
        row: pd.Series,
        point_size: float,
        pip_size: float,
    ) -> float:
        """バーの spread 列から pips 換算し、最低スプレッドを下限に返す."""
        raw_spread = row.get("spread")
        if raw_spread is None or pd.isna(raw_spread):
            return float(self.spread_pips)
        actual_spread_pips = float(raw_spread) * point_size / pip_size
        return max(actual_spread_pips, float(self.spread_pips))

    def _resolve_slippage_pips(self, effective_spread_pips: float) -> float:
        """実効スプレッドに連動したスリッページを返す.

        settings.backtest.slippage_pips を基準スリッページとし、
        スプレッドが最低スプレッドを超えて広がったバーでは比例して増やす。
        """
        base_slippage = float(self.slippage_pips)
        min_spread = float(self.spread_pips)
        if min_spread <= 0:
            return base_slippage
        scale = max(effective_spread_pips / min_spread, 1.0)
        return base_slippage * scale

    def _build_closed_equity_series(self, trades: list[Trade]) -> pd.Series:
        """決済済み損益のみで構成した equity を返す."""
        if not trades:
            return pd.Series(dtype=float, name="closed_equity")

        trade_df = pd.DataFrame(
            {"exit_time": [t.exit_time for t in trades], "pnl": [t.pnl for t in trades]}
        )
        trade_df["exit_time"] = pd.to_datetime(trade_df["exit_time"], utc=True)
        daily_pnl = trade_df.set_index("exit_time")["pnl"].resample("D").sum().fillna(0.0)
        closed_equity = (daily_pnl.cumsum() + self.initial_balance).astype(float)
        closed_equity.name = "closed_equity"
        closed_equity.index.name = "datetime"
        return closed_equity

    @staticmethod
    def _resolve_exit_hit(
        side: Side,
        low: float,
        high: float,
        effective_sl: float,
        tp: float,
        trailing_sl_active: bool,
        tp_triggered: bool,
        trailing_tp_enabled: bool,
    ) -> tuple[float | None, str]:
        """同一バー内のSL/TP競合時は不利側を優先して決済価格を返す."""
        sl_hit = (low <= effective_sl) if side == Side.BUY else (high >= effective_sl)
        tp_hit = (not tp_triggered and not trailing_tp_enabled and (
            (high >= tp) if side == Side.BUY else (low <= tp)
        ))

        if sl_hit:
            return effective_sl, "trailing" if trailing_sl_active else "sl"
        if tp_hit:
            return tp, "tp"
        return None, ""

    def run(
        self,
        feature_matrix: pd.DataFrame,
        predictions: pd.Series,
        point: float | None = None,
        symbol: str | None = None,
    ) -> BacktestResult:
        """バックテストを実行.

        Args:
            feature_matrix: close, high, low, atr_14 列を含むDataFrame
            predictions: 予測対数リターン
            point: MT5のpoint値
            symbol: シンボル名（pip換算用）

        Returns:
            BacktestResult
        """
        balance = self.initial_balance
        positions: list[Position] = []
        pending_entry: PendingEntry | None = None
        trades: list[Trade] = []
        equity_series = {}

        risk_cfg = self.settings.risk
        pip_size = self._resolve_pip_size(feature_matrix, symbol=symbol, point=point)
        point_size = self._resolve_point_size(feature_matrix, symbol=symbol, point=point, pip_size=pip_size)
        point_for_signal = point if point is not None else pip_size

        for i in range(len(feature_matrix)):
            row = feature_matrix.iloc[i]
            time = feature_matrix.index[i]
            open_price = row["open"]
            close = row["close"]
            high = row["high"]
            low = row["low"]
            spread_pips = self._resolve_spread_pips(row, point_size, pip_size)
            spread = spread_pips * pip_size
            slippage_pips = self._resolve_slippage_pips(spread_pips)
            slippage = slippage_pips * pip_size

            atr_col = "atr_14" if "atr_14" in row.index else None
            atr = row[atr_col] if atr_col and not np.isnan(row[atr_col]) else close * 0.001

            # --- 前バーで確定したシグナルを次バー始値で約定 ---
            if pending_entry is not None:
                if len(positions) < self.max_positions:
                    if pending_entry.action == SignalAction.BUY:
                        entry_price = open_price + spread / 2 + slippage
                        stops = calculate_stops("buy", entry_price, pending_entry.prediction, pending_entry.atr, self.settings)
                        positions.append(Position(
                            entry_time=time,
                            side=Side.BUY,
                            entry_price=entry_price,
                            lot=pending_entry.lot,
                            sl=stops.sl,
                            tp=stops.tp,
                        ))
                    elif pending_entry.action == SignalAction.SELL:
                        entry_price = open_price - spread / 2 - slippage
                        stops = calculate_stops("sell", entry_price, pending_entry.prediction, pending_entry.atr, self.settings)
                        positions.append(Position(
                            entry_time=time,
                            side=Side.SELL,
                            entry_price=entry_price,
                            lot=pending_entry.lot,
                            sl=stops.sl,
                            tp=stops.tp,
                        ))
                pending_entry = None

            # --- ポジション管理（SL/TP/トレーリング） ---
            closed_indices = []
            for j, pos in enumerate(positions):
                exit_price = None
                exit_reason = ""

                if pos.side == Side.BUY:
                    # SLチェック（trailing_slがあれば優先）
                    effective_sl = pos.trailing_sl if pos.trailing_sl is not None else pos.sl
                    exit_price, exit_reason = self._resolve_exit_hit(
                        pos.side, low, high, effective_sl, pos.tp,
                        pos.trailing_sl is not None,
                        pos.tp_triggered, risk_cfg.trailing_tp_enabled
                    )
                    if exit_price is not None:
                        pass
                    elif not pos.tp_triggered and high >= pos.tp:
                        # TP到達
                        if not risk_cfg.trailing_tp_enabled:
                            exit_price = pos.tp
                            exit_reason = "tp"
                        else:
                            pos.tp_triggered = True  # TP到達マーク、決済しない
                            # TP水準からtrailing_distanceだけ戻った位置にSLをロック
                            lock_sl = pos.tp - atr * risk_cfg.trailing_atr_multiplier
                            if pos.trailing_sl is None or lock_sl > pos.trailing_sl:
                                pos.trailing_sl = lock_sl
                    else:
                        # trailing_sl_enabledがONのときのみSLを追従更新
                        if risk_cfg.trailing_sl_enabled:
                            activation = pos.entry_price + atr * risk_cfg.trailing_activation_atr
                            if high >= activation:
                                new_trailing = high - atr * risk_cfg.trailing_atr_multiplier
                                if pos.trailing_sl is None or new_trailing > pos.trailing_sl:
                                    pos.trailing_sl = new_trailing

                else:  # SELL
                    effective_sl = pos.trailing_sl if pos.trailing_sl is not None else pos.sl
                    exit_price, exit_reason = self._resolve_exit_hit(
                        pos.side, low, high, effective_sl, pos.tp,
                        pos.trailing_sl is not None,
                        pos.tp_triggered, risk_cfg.trailing_tp_enabled
                    )
                    if exit_price is not None:
                        pass
                    elif not pos.tp_triggered and low <= pos.tp:
                        if not risk_cfg.trailing_tp_enabled:
                            exit_price = pos.tp
                            exit_reason = "tp"
                        else:
                            pos.tp_triggered = True
                            lock_sl = pos.tp + atr * risk_cfg.trailing_atr_multiplier
                            if pos.trailing_sl is None or lock_sl < pos.trailing_sl:
                                pos.trailing_sl = lock_sl
                    else:
                        if risk_cfg.trailing_sl_enabled:
                            activation = pos.entry_price - atr * risk_cfg.trailing_activation_atr
                            if low <= activation:
                                new_trailing = low + atr * risk_cfg.trailing_atr_multiplier
                                if pos.trailing_sl is None or new_trailing < pos.trailing_sl:
                                    pos.trailing_sl = new_trailing

                if exit_price is not None:
                    exit_price = self._apply_exit_slippage(pos.side, exit_price, slippage)
                    if pos.side == Side.BUY:
                        pnl = (exit_price - pos.entry_price - spread) * pos.lot * 100000
                    else:
                        pnl = (pos.entry_price - exit_price - spread) * pos.lot * 100000

                    balance += pnl
                    trades.append(Trade(
                        entry_time=pos.entry_time,
                        exit_time=time,
                        side=pos.side.value,
                        entry_price=pos.entry_price,
                        exit_price=exit_price,
                        lot=pos.lot,
                        pnl=pnl,
                        exit_reason=exit_reason,
                    ))
                    closed_indices.append(j)

            # 決済済みポジションを除去
            for idx in reversed(closed_indices):
                positions.pop(idx)

            # --- エントリーシグナル ---
            if i < len(predictions) and len(positions) < self.max_positions:
                pred = predictions.iloc[i] if i < len(predictions) else 0.0
                regime = self._resolve_regime(row)
                h4_regime = self._resolve_h4_regime(row)
                current_hour_utc = getattr(time, "hour", None)

                signal = generate_signal(
                    symbol or "",
                    pred,
                    close,
                    atr,
                    balance,
                    point_for_signal,
                    self.settings,
                    confidence=1.0,
                    spread_pips=spread_pips,
                    current_hour_utc=current_hour_utc,
                    regime=regime,
                    h4_regime=h4_regime,
                )

                if signal.action in (SignalAction.BUY, SignalAction.SELL) and i + 1 < len(feature_matrix):
                    pending_entry = PendingEntry(
                        signal_time=time,
                        action=signal.action,
                        prediction=pred,
                        lot=signal.lot,
                        atr=atr,
                    )

            # エクイティ記録（残高 + 含み損益）
            unrealized = 0.0
            for pos in positions:
                if pos.side == Side.BUY:
                    unrealized += (close - pos.entry_price) * pos.lot * 100000
                else:
                    unrealized += (pos.entry_price - close) * pos.lot * 100000
            equity_series[time] = balance + unrealized

        # 残ポジションを最終バーで強制決済
        final_close = feature_matrix["close"].iloc[-1]
        final_time = feature_matrix.index[-1]
        for pos in positions:
            if pos.side == Side.BUY:
                exit_price = self._apply_exit_slippage(pos.side, final_close, slippage)
                pnl = (exit_price - pos.entry_price - spread) * pos.lot * 100000
            else:
                exit_price = self._apply_exit_slippage(pos.side, final_close, slippage)
                pnl = (pos.entry_price - exit_price - spread) * pos.lot * 100000
            balance += pnl
            trades.append(Trade(
                entry_time=pos.entry_time,
                exit_time=final_time,
                side=pos.side.value,
                entry_price=pos.entry_price,
                exit_price=exit_price,
                lot=pos.lot,
                pnl=pnl,
                exit_reason="end",
            ))

        equity = pd.Series(equity_series, name="equity")
        equity.index.name = "datetime"
        closed_equity = self._build_closed_equity_series(trades)

        trades_df = pd.DataFrame([
            {
                "entry_time": t.entry_time,
                "exit_time": t.exit_time,
                "side": t.side,
                "entry_price": t.entry_price,
                "exit_price": t.exit_price,
                "lot": t.lot,
                "pnl": t.pnl,
                "exit_reason": t.exit_reason,
            }
            for t in trades
        ])

        log.info(
            f"バックテスト完了: {len(trades)}トレード, "
            f"最終残高: {balance:.2f}, "
            f"リターン: {(balance / self.initial_balance - 1) * 100:.2f}%"
        )

        return BacktestResult(
            equity=equity,
            closed_equity=closed_equity,
            trades=trades,
            settings={
                "initial_balance": self.initial_balance,
                "spread_pips": self.spread_pips,
                "slippage_pips": self.slippage_pips,
                "pip_size": pip_size,
                "point_size": point_size,
                "symbol": symbol or "",
            },
        )
