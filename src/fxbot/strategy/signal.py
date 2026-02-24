"""予測→TradeSignal変換."""

from __future__ import annotations

from dataclasses import dataclass, field
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
    hold_reason: str = ""


@dataclass
class FilterStatus:
    """1フィルターの状態を保持するデータクラス."""
    filter_name: str        # 内部識別子 e.g. "adx"
    display_name: str       # 表示名 e.g. "ADXフィルター"
    enabled: bool           # このフィルターが有効かどうか
    passed: bool            # 通過したか（enabled=Falseの場合はTrueとみなす）
    current_value: str      # 現在値の文字列表現
    threshold_str: str      # 閾値の文字列表現
    reason: str = ""        # ブロック理由（通過時は空）


def get_filter_statuses(
    symbol: str,
    prediction: float,
    current_price: float,
    atr: float,
    settings: Settings,
    confidence: float = 1.0,
    spread_pips: float = 0.0,
    current_hour_utc: int | None = None,
    regime: str = "trend_up",
) -> list[FilterStatus]:
    """各フィルターの状態を計算して返す（副作用なし）."""
    mf = settings.market_filter
    statuses: list[FilterStatus] = []

    # --- ADXフィルター ---
    adx_enabled = mf.enabled and mf.use_adx_filter
    if adx_enabled:
        adx_passed = regime != "ranging"
        current_val = f"レジーム: {regime}"
        threshold = "レンジ除外"
        reason = "ranging相場でブロック" if not adx_passed else ""
    else:
        adx_passed = True
        current_val = f"レジーム: {regime}"
        threshold = "---"
        reason = ""
    statuses.append(FilterStatus(
        filter_name="adx",
        display_name="ADXフィルター",
        enabled=adx_enabled,
        passed=adx_passed,
        current_value=current_val,
        threshold_str=threshold,
        reason=reason,
    ))

    # --- スプレッドフィルター ---
    spread_enabled = mf.enabled and mf.use_spread_filter
    if spread_enabled:
        spread_passed = spread_pips <= mf.max_spread_pips
        current_val = f"{spread_pips:.1f} pips"
        threshold = f"閾値:{mf.max_spread_pips:.1f}"
        reason = f"{spread_pips:.1f}pips > {mf.max_spread_pips:.1f}pips" if not spread_passed else ""
    else:
        spread_passed = True
        current_val = f"{spread_pips:.1f} pips"
        threshold = "---"
        reason = ""
    statuses.append(FilterStatus(
        filter_name="spread",
        display_name="スプレッドフィルター",
        enabled=spread_enabled,
        passed=spread_passed,
        current_value=current_val,
        threshold_str=threshold,
        reason=reason,
    ))

    # --- ボラティリティフィルター ---
    vol_enabled = mf.enabled and mf.use_volatility_filter
    if vol_enabled and current_price > 0 and atr > 0:
        atr_pct = atr / current_price * 100
        vol_passed = mf.min_atr_pct <= atr_pct <= mf.max_atr_pct
        current_val = f"ATR%: {atr_pct:.4f}%"
        threshold = f"{mf.min_atr_pct}%〜{mf.max_atr_pct}%"
        if atr_pct < mf.min_atr_pct:
            reason = f"低ボラ({atr_pct:.4f}% < {mf.min_atr_pct}%)"
        elif atr_pct > mf.max_atr_pct:
            reason = f"過大ボラ({atr_pct:.4f}% > {mf.max_atr_pct}%)"
        else:
            reason = ""
    else:
        vol_passed = True
        current_val = "無効" if not vol_enabled else "データ不足"
        threshold = "---"
        reason = ""
    statuses.append(FilterStatus(
        filter_name="volatility",
        display_name="ボラティリティ",
        enabled=vol_enabled,
        passed=vol_passed,
        current_value=current_val,
        threshold_str=threshold,
        reason=reason,
    ))

    # --- セッションフィルター ---
    session_enabled = mf.enabled and mf.session_only
    if session_enabled and current_hour_utc is not None:
        in_london = 7 <= current_hour_utc < 16
        in_ny = 13 <= current_hour_utc < 22
        session_passed = in_london or in_ny
        session_name = "ロンドン" if in_london else ("NY" if in_ny else "セッション外")
        current_val = f"UTC {current_hour_utc}時({session_name})"
        threshold = "7-16/13-22 UTC"
        reason = f"UTC {current_hour_utc}時はセッション外" if not session_passed else ""
    else:
        session_passed = True
        current_val = f"UTC {current_hour_utc}時" if current_hour_utc is not None else "---"
        threshold = "---"
        reason = ""
    statuses.append(FilterStatus(
        filter_name="session",
        display_name="セッションフィルター",
        enabled=session_enabled,
        passed=session_passed,
        current_value=current_val,
        threshold_str=threshold,
        reason=reason,
    ))

    # --- 信頼度チェック ---
    min_conf = settings.trading.min_confidence
    conf_enabled = min_conf > 0.0
    conf_passed = confidence >= min_conf
    statuses.append(FilterStatus(
        filter_name="confidence",
        display_name="信頼度チェック",
        enabled=conf_enabled,
        passed=conf_passed,
        current_value=f"信頼度: {confidence:.4f}",
        threshold_str=f"最低:{min_conf:.2f}" if conf_enabled else "---",
        reason=f"{confidence:.4f} < {min_conf:.2f}" if not conf_passed else "",
    ))

    return statuses


def _make_hold(symbol: str, prediction: float, reason: str = "") -> TradeSignal:
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
        hold_reason=reason,
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
        # ADXフィルター（レンジ相場）
        if mf.use_adx_filter and regime == "ranging":
            log.debug(f"レンジ相場でHOLD: {symbol} regime={regime}")
            return _make_hold(symbol, prediction, "adx_ranging")

        # スプレッドフィルター
        if mf.use_spread_filter and spread_pips is not None and spread_pips > mf.max_spread_pips:
            log.debug(f"スプレッド過大でHOLD: {symbol} spread={spread_pips:.1f}pips > {mf.max_spread_pips}")
            return _make_hold(symbol, prediction, "spread_over")

        # ボラティリティフィルター（個別スイッチで制御）
        if mf.use_volatility_filter and current_price > 0 and atr > 0:
            atr_pct = atr / current_price * 100
            if atr_pct < mf.min_atr_pct:
                log.debug(f"低ボラでHOLD: {symbol} ATR%={atr_pct:.4f}% < {mf.min_atr_pct}%")
                return _make_hold(symbol, prediction, "volatility_low")
            if atr_pct > mf.max_atr_pct:
                log.debug(f"過大ボラでHOLD: {symbol} ATR%={atr_pct:.4f}% > {mf.max_atr_pct}%")
                return _make_hold(symbol, prediction, "volatility_high")

        # セッションフィルター（ロンドン7-16 UTC, NY13-22 UTC）
        if mf.session_only and current_hour_utc is not None:
            in_london = 7 <= current_hour_utc < 16
            in_ny = 13 <= current_hour_utc < 22
            if not (in_london or in_ny):
                log.debug(f"セッション外でHOLD: {symbol} UTC={current_hour_utc}時")
                return _make_hold(symbol, prediction, "session_outside")

    # --- 信頼度チェック（分類モデル使用時）---
    if confidence < min_confidence:
        log.debug(f"信頼度不足でHOLD: {symbol} confidence={confidence:.4f} < {min_confidence}")
        return _make_hold(symbol, prediction, "confidence_low")

    # --- 予測値閾値チェック ---
    if abs(prediction) < threshold:
        return _make_hold(symbol, prediction, "prediction_threshold")

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
