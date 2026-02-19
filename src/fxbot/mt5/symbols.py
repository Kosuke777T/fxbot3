"""通貨ペア自動検出・保存."""

from __future__ import annotations

import json
from pathlib import Path

import MetaTrader5 as mt5

from fxbot.config import Settings
from fxbot.logger import get_logger

log = get_logger(__name__)

SYMBOLS_FILE = "data/symbols.json"


def detect_symbols(settings: Settings) -> list[dict]:
    """MT5から取引可能なFXペアを検出."""
    all_symbols = mt5.symbols_get()
    if all_symbols is None:
        log.error(f"シンボル取得失敗: {mt5.last_error()}")
        return []

    fx_symbols = []
    for s in all_symbols:
        # FXペア: trade_modeがFULL、かつ通貨ペアっぽいもの
        if s.trade_mode != mt5.SYMBOL_TRADE_MODE_FULL:
            continue
        # path に "Forex" を含む or calc_mode が FOREX
        is_forex = (
            "Forex" in (s.path or "")
            or s.trade_calc_mode == 0  # SYMBOL_CALC_MODE_FOREX
        )
        if is_forex:
            fx_symbols.append({
                "name": s.name,
                "description": s.description,
                "digits": s.digits,
                "point": s.point,
                "trade_contract_size": s.trade_contract_size,
                "volume_min": s.volume_min,
                "volume_max": s.volume_max,
                "volume_step": s.volume_step,
                "spread": s.spread,
            })

    log.info(f"FXペア検出: {len(fx_symbols)}ペア")
    return fx_symbols


def save_symbols(symbols: list[dict], settings: Settings) -> Path:
    """シンボル情報をJSONに保存."""
    path = settings.resolve_path(SYMBOLS_FILE)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(symbols, f, indent=2, ensure_ascii=False)
    log.info(f"シンボル情報保存: {path} ({len(symbols)}ペア)")
    return path


def load_symbols(settings: Settings) -> list[dict]:
    """保存済みシンボル情報を読み込む."""
    path = settings.resolve_path(SYMBOLS_FILE)
    if not path.exists():
        return []
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def get_symbol_names(settings: Settings) -> list[str]:
    """シンボル名のリストを返す（保存済みから読み込み）."""
    symbols = load_symbols(settings)
    return [s["name"] for s in symbols]
