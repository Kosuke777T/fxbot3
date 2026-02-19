"""予測→TradeSignal変換."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from fxbot.config import Settings
from fxbot.logger import get_logger

log = get_logger(__name__)


class SignalAction(str, Enum):
    BUY = "buy"
    SELL = "sell"
    HOLD = "hold"


@dataclass
class TradeSignal:
    symbol: str
    action: SignalAction
    prediction: float
    lot: float
    sl: float
    tp: float
    trailing_activation: float
    trailing_distance: float


def generate_signal(
    symbol: str,
    prediction: float,
    current_price: float,
    atr: float,
    balance: float,
    point: float,
    settings: Settings,
) -> TradeSignal:
    """予測値からトレードシグナルを生成."""
    from fxbot.risk.position_sizer import calculate_lot
    from fxbot.risk.stop_manager import calculate_stops

    threshold = settings.trading.min_prediction_threshold

    if abs(prediction) < threshold:
        return TradeSignal(
            symbol=symbol,
            action=SignalAction.HOLD,
            prediction=prediction,
            lot=0.0,
            sl=0.0,
            tp=0.0,
            trailing_activation=0.0,
            trailing_distance=0.0,
        )

    side = "buy" if prediction > 0 else "sell"

    lot = calculate_lot(prediction, balance, atr, point, settings)
    if lot <= 0:
        return TradeSignal(
            symbol=symbol,
            action=SignalAction.HOLD,
            prediction=prediction,
            lot=0.0,
            sl=0.0,
            tp=0.0,
            trailing_activation=0.0,
            trailing_distance=0.0,
        )

    stops = calculate_stops(side, current_price, prediction, atr, settings)

    signal = TradeSignal(
        symbol=symbol,
        action=SignalAction.BUY if side == "buy" else SignalAction.SELL,
        prediction=prediction,
        lot=lot,
        sl=stops.sl,
        tp=stops.tp,
        trailing_activation=stops.trailing_activation,
        trailing_distance=stops.trailing_distance,
    )

    log.info(f"シグナル生成: {signal.action.value.upper()} {symbol} "
             f"pred={prediction:.6f} lot={lot} SL={stops.sl:.5f} TP={stops.tp:.5f}")
    return signal
