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


def _make_hold(symbol: str, prediction: float) -> TradeSignal:
    """HOLDシグナルを生成するヘルパー."""
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


def generate_signal(
    symbol: str,
    prediction: float,
    current_price: float,
    atr: float,
    balance: float,
    point: float,
    settings: Settings,
    confidence: float = 1.0,
    spread_pips: float = 0.0,
    current_hour_utc: int | None = None,
    regime: str = "trend_up",
) -> TradeSignal:
    """予測値からトレードシグナルを生成.

    Args:
        confidence: 分類モデルの信頼度 (0.0〜1.0)。
                    min_confidence未満の場合はHOLDを返す。
                    デフォルト1.0で後方互換性を維持。
        spread_pips: 現在のスプレッド（pips）。
        current_hour_utc: 現在時刻（UTC時）。Noneで時刻フィルタ無効。
        regime: 現在の市場レジーム ("trend_up"|"trend_down"|"ranging")。
    """
    from fxbot.risk.position_sizer import calculate_lot
    from fxbot.risk.stop_manager import calculate_stops

    threshold = settings.trading.min_prediction_threshold
    min_confidence = settings.trading.min_confidence

    # --- 市場環境フィルター ---
    mf = settings.market_filter
    if mf.enabled:
        # レンジ相場フィルター
        if regime == "ranging":
            log.info(f"レンジ相場でHOLD: {symbol} regime={regime}")
            return _make_hold(symbol, prediction)

        # スプレッドフィルター
        if spread_pips > mf.max_spread_pips:
            log.info(f"スプレッド過大でHOLD: {symbol} spread={spread_pips:.1f}pips > {mf.max_spread_pips}")
            return _make_hold(symbol, prediction)

        # ATR%ボラティリティフィルター（過小・過大ボラをHOLD）
        # ATR%が0に近い（動かない）、または異常に高い（指標発表など）はHOLD
        if current_price > 0 and atr > 0:
            atr_pct = atr / current_price * 100
            # 過小ボラ: スプレッドコストに対して動きが小さすぎる（ATR% < 0.02%）
            if atr_pct < 0.02:
                log.info(f"低ボラでHOLD: {symbol} ATR%={atr_pct:.4f}% < 0.02%")
                return _make_hold(symbol, prediction)
            # 過大ボラ: 経済指標発表などの異常相場（ATR% > 0.5%）
            if atr_pct > 0.5:
                log.info(f"過大ボラでHOLD: {symbol} ATR%={atr_pct:.4f}% > 0.5%")
                return _make_hold(symbol, prediction)

        # セッションフィルター（ロンドン7-16 UTC, NY13-22 UTC）
        if mf.session_only and current_hour_utc is not None:
            in_london = 7 <= current_hour_utc < 16
            in_ny = 13 <= current_hour_utc < 22
            if not (in_london or in_ny):
                log.info(f"セッション外でHOLD: {symbol} UTC={current_hour_utc}時")
                return _make_hold(symbol, prediction)

    # --- 信頼度チェック（分類モデル使用時）---
    if confidence < min_confidence:
        log.info(f"信頼度不足でHOLD: {symbol} confidence={confidence:.4f} < {min_confidence}")
        return _make_hold(symbol, prediction)

    # --- 予測値閾値チェック ---
    if abs(prediction) < threshold:
        return _make_hold(symbol, prediction)

    side = "buy" if prediction > 0 else "sell"

    lot = calculate_lot(prediction, balance, atr, point, settings, confidence=confidence)
    if lot <= 0:
        return _make_hold(symbol, prediction)

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
             f"pred={prediction:.6f} conf={confidence:.4f} lot={lot} "
             f"SL={stops.sl:.5f} TP={stops.tp:.5f} regime={regime}")
    return signal
