"""MT5接続・切断・状態確認."""

from __future__ import annotations

import MetaTrader5 as mt5

from fxbot.config import AccountConfig, Settings
from fxbot.logger import get_logger

log = get_logger(__name__)

# MT5タイムフレームのマッピング
TIMEFRAME_MAP: dict[str, int] = {
    "M1": mt5.TIMEFRAME_M1,
    "M5": mt5.TIMEFRAME_M5,
    "M15": mt5.TIMEFRAME_M15,
    "M30": mt5.TIMEFRAME_M30,
    "H1": mt5.TIMEFRAME_H1,
    "H4": mt5.TIMEFRAME_H4,
    "D1": mt5.TIMEFRAME_D1,
    "W1": mt5.TIMEFRAME_W1,
    "MN1": mt5.TIMEFRAME_MN1,
}


def connect(settings: Settings) -> bool:
    """MT5に接続しログインする."""
    account = settings.current_account
    log.info("MT5初期化中...")

    if not mt5.initialize():
        log.error(f"MT5初期化失敗: {mt5.last_error()}")
        return False

    log.info("MT5初期化成功")

    if account.login and account.password:
        authorized = mt5.login(
            login=account.login,
            password=account.password,
            server=account.server,
        )
        if not authorized:
            log.error(f"MT5ログイン失敗: {mt5.last_error()}")
            mt5.shutdown()
            return False
        log.info(f"MT5ログイン成功: {account.server} (口座: {account.login})")
    else:
        log.info("ログイン情報未設定 — デフォルト口座で接続")

    info = mt5.account_info()
    if info:
        log.info(f"口座残高: {info.balance} {info.currency}, レバレッジ: 1:{info.leverage}")

    return True


def disconnect() -> None:
    """MT5接続を切断."""
    mt5.shutdown()
    log.info("MT5切断完了")


def reconnect(settings: Settings) -> bool:
    """再接続."""
    disconnect()
    return connect(settings)


def is_connected() -> bool:
    """MT5が接続状態か確認."""
    info = mt5.terminal_info()
    return info is not None and info.connected


def get_account_info() -> dict | None:
    """口座情報を取得."""
    info = mt5.account_info()
    if info is None:
        return None
    return {
        "login": info.login,
        "balance": info.balance,
        "equity": info.equity,
        "margin": info.margin,
        "free_margin": info.margin_free,
        "currency": info.currency,
        "leverage": info.leverage,
        "server": info.server,
        "trade_mode": info.trade_mode,
    }
