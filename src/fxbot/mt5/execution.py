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
        return None

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


def get_deal_history(position_ticket: int) -> dict | None:
    """ポジションの決済情報をMT5履歴から取得.

    MT5 APIの profit は個別取引の損益（口座通貨）で取得可能。
    日付範囲 + position= を組み合わせて検索し、position_id で明示フィルタリングする
    （一部ブローカーでは position= 単独指定が空を返すケースがあるため）。
    デポジット等の混入は type チェックで除外する。
    複数ポジション同時決済時にMT5履歴反映が遅延する場合に備え、最大3回リトライする。

    Returns:
        決済情報の辞書 {price, profit, time, reason}、取得失敗時はNone
    """
    import time
    from datetime import datetime, timedelta, timezone
    from zoneinfo import ZoneInfo

    # MT5の deal.time はUTCのUnixタイムスタンプ。日本時間(JST)で記録するため明示的に変換
    JST = ZoneInfo("Asia/Tokyo")

    DEAL_ENTRY_OUT = getattr(mt5, "DEAL_ENTRY_OUT", 1)
    DEAL_TYPE_BUY = getattr(mt5, "DEAL_TYPE_BUY", 0)
    DEAL_TYPE_SELL = getattr(mt5, "DEAL_TYPE_SELL", 1)

    reason_map = {
        getattr(mt5, "DEAL_REASON_CLIENT", 0): "manual",
        getattr(mt5, "DEAL_REASON_MOBILE", 1): "manual",
        getattr(mt5, "DEAL_REASON_WEB", 2): "manual",
        getattr(mt5, "DEAL_REASON_EXPERT", 3): "expert",
        getattr(mt5, "DEAL_REASON_SL", 4): "sl",
        getattr(mt5, "DEAL_REASON_TP", 5): "tp",
        getattr(mt5, "DEAL_REASON_SO", 6): "stop_out",
    }

    date_from = datetime(2020, 1, 1)

    for attempt in range(3):
        date_to = datetime.now() + timedelta(days=1)
        deals = mt5.history_deals_get(date_from, date_to, position=position_ticket)

        # position_id で明示フィルタリング（一部環境で position= が効かず全履歴が返る対策）
        if deals:
            deals = [d for d in deals if getattr(d, "position_id", None) == position_ticket]

        if deals:
            # 取引ディール（BUY/SELL）に限定して決済ディールを検出
            # コミッション・ボーナス等の非取引ディールを除外するため type チェックを追加
            exit_deal = None
            for deal in deals:
                if (deal.entry == DEAL_ENTRY_OUT
                        and deal.type in (DEAL_TYPE_BUY, DEAL_TYPE_SELL)):
                    exit_deal = deal
                    break

            if exit_deal is not None:
                utc_dt = datetime.fromtimestamp(exit_deal.time, tz=timezone.utc)
                deal_time = utc_dt.astimezone(JST).replace(tzinfo=None).isoformat()
                reason = reason_map.get(exit_deal.reason, f"unknown({exit_deal.reason})")

                # 取引ディール（BUY/SELL）のみ合算。入金・ボーナス等（type=2等）を除外して
                # 残高値が混入しないようにする。
                trade_deals = [
                    d for d in deals
                    if d.type in (DEAL_TYPE_BUY, DEAL_TYPE_SELL)
                ]
                total_profit = sum(
                    getattr(d, "profit", 0.0)
                    + getattr(d, "commission", 0.0)
                    + getattr(d, "swap", 0.0)
                    for d in trade_deals
                )

                return {
                    "price": exit_deal.price,
                    "profit": total_profit,
                    "time": deal_time,
                    "reason": reason,
                }

        if attempt < 2:
            log.debug(f"決済履歴リトライ {attempt + 1}/3: position={position_ticket}")
            time.sleep(2.0)

    log.warning(f"決済履歴取得失敗（3回リトライ後）: position={position_ticket}")
    return None


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
