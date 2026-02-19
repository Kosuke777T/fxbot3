"""最大ポジション数・相関管理."""

from __future__ import annotations

import MetaTrader5 as mt5

from fxbot.config import Settings
from fxbot.logger import get_logger

log = get_logger(__name__)


def get_open_positions() -> list[dict]:
    """MT5からオープンポジションを取得."""
    positions = mt5.positions_get()
    if positions is None:
        return []
    return [
        {
            "ticket": p.ticket,
            "symbol": p.symbol,
            "type": "buy" if p.type == mt5.ORDER_TYPE_BUY else "sell",
            "volume": p.volume,
            "price_open": p.price_open,
            "price_current": p.price_current,
            "sl": p.sl,
            "tp": p.tp,
            "profit": p.profit,
            "time": p.time,
        }
        for p in positions
    ]


def can_open_position(symbol: str, settings: Settings) -> bool:
    """新しいポジションを建てられるか判定."""
    positions = get_open_positions()
    if len(positions) >= settings.trading.max_positions:
        log.debug(f"最大ポジション数到達: {len(positions)}/{settings.trading.max_positions}")
        return False

    # 同一シンボルの既存ポジションチェック（オプション: 制限可能）
    same_symbol = [p for p in positions if p["symbol"] == symbol]
    if len(same_symbol) >= 2:
        log.debug(f"{symbol}: 同一シンボルポジション上限到達")
        return False

    return True


def get_total_exposure(positions: list[dict]) -> float:
    """合計エクスポージャー（ロット）."""
    return sum(p["volume"] for p in positions)
