"""注文送信・変更・決済."""

from __future__ import annotations

import MetaTrader5 as mt5

from fxbot.logger import get_logger

log = get_logger(__name__)


def _get_filling_type(symbol_info) -> int:
    """シンボルがサポートする約定方式を自動判定."""
    filling = symbol_info.filling_mode
    if filling & 1:  # FOK
        return mt5.ORDER_FILLING_FOK
    if filling & 2:  # IOC
        return mt5.ORDER_FILLING_IOC
    return mt5.ORDER_FILLING_RETURN


def send_order(
    symbol: str,
    side: str,
    lot: float,
    sl: float,
    tp: float,
    comment: str = "fxbot3",
) -> dict | None:
    """成行注文を送信.

    Returns:
        約定結果の辞書、失敗時はNone
    """
    symbol_info = mt5.symbol_info(symbol)
    if symbol_info is None:
        log.error(f"シンボル情報取得失敗: {symbol}")
        return None

    if not symbol_info.visible:
        if not mt5.symbol_select(symbol, True):
            log.error(f"シンボル表示切替失敗: {symbol}")
            return None

    if side == "buy":
        order_type = mt5.ORDER_TYPE_BUY
        price = mt5.symbol_info_tick(symbol).ask
    else:
        order_type = mt5.ORDER_TYPE_SELL
        price = mt5.symbol_info_tick(symbol).bid

    filling_type = _get_filling_type(symbol_info)
    request = {
        "action": mt5.TRADE_ACTION_DEAL,
        "symbol": symbol,
        "volume": lot,
        "type": order_type,
        "price": price,
        "deviation": 20,
        "magic": 300003,
        "comment": comment,
        "type_time": mt5.ORDER_TIME_GTC,
        "type_filling": filling_type,
    }
    if sl:
        request["sl"] = sl
    if tp:
        request["tp"] = tp

    result = mt5.order_send(request)
    if result is None:
        log.error(f"注文送信失敗: {mt5.last_error()}")
        return None

    if result.retcode != mt5.TRADE_RETCODE_DONE:
        msg = f"注文拒否: {result.retcode} — {result.comment}"
        log.error(msg)
        return {"error": msg}

    log.info(f"注文約定: {side.upper()} {symbol} {lot}lot @ {result.price} "
             f"(ticket: {result.order})")
    return {
        "ticket": result.order,
        "price": result.price,
        "volume": result.volume,
    }


def modify_position(
    ticket: int,
    sl: float | None = None,
    tp: float | None = None,
) -> bool:
    """ポジションのSL/TPを変更."""
    position = mt5.positions_get(ticket=ticket)
    if not position:
        log.error(f"ポジション取得失敗: ticket={ticket}")
        return False

    pos = position[0]
    request = {
        "action": mt5.TRADE_ACTION_SLTP,
        "position": ticket,
        "symbol": pos.symbol,
        "sl": sl if sl is not None else pos.sl,
        "tp": tp if tp is not None else pos.tp,
    }

    result = mt5.order_send(request)
    if result is None or result.retcode != mt5.TRADE_RETCODE_DONE:
        log.error(f"ポジション変更失敗: {result}")
        return False

    log.info(f"ポジション変更: ticket={ticket}, SL={sl}, TP={tp}")
    return True


def close_position(ticket: int) -> bool:
    """ポジションを決済."""
    position = mt5.positions_get(ticket=ticket)
    if not position:
        log.error(f"ポジション取得失敗: ticket={ticket}")
        return False

    pos = position[0]
    symbol_info = mt5.symbol_info(pos.symbol)
    if pos.type == mt5.ORDER_TYPE_BUY:
        order_type = mt5.ORDER_TYPE_SELL
        price = mt5.symbol_info_tick(pos.symbol).bid
    else:
        order_type = mt5.ORDER_TYPE_BUY
        price = mt5.symbol_info_tick(pos.symbol).ask

    filling_type = _get_filling_type(symbol_info) if symbol_info else mt5.ORDER_FILLING_IOC
    request = {
        "action": mt5.TRADE_ACTION_DEAL,
        "position": ticket,
        "symbol": pos.symbol,
        "volume": pos.volume,
        "type": order_type,
        "price": price,
        "deviation": 20,
        "magic": 300003,
        "comment": "fxbot3_close",
        "type_time": mt5.ORDER_TIME_GTC,
        "type_filling": filling_type,
    }

    result = mt5.order_send(request)
    if result is None or result.retcode != mt5.TRADE_RETCODE_DONE:
        log.error(f"決済失敗: {result}")
        return False

    log.info(f"決済完了: ticket={ticket}, {pos.symbol}")
    return True


def close_all_positions() -> int:
    """全ポジションを決済.

    Returns:
        決済したポジション数
    """
    positions = mt5.positions_get()
    if not positions:
        return 0

    closed = 0
    for pos in positions:
        if close_position(pos.ticket):
            closed += 1

    log.info(f"全決済: {closed}/{len(positions)}")
    return closed
