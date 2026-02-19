"""エントリーポイント — GUI起動 or CLIモード."""

from __future__ import annotations

import sys

from fxbot.config import load_settings
from fxbot.logger import setup_logger


def main() -> None:
    settings = load_settings()
    log = setup_logger(settings)

    # --cli フラグでCLIモード（Phase 1デモ用）
    if "--cli" in sys.argv:
        _run_cli(settings, log)
        return

    _run_gui(settings, log)


def _run_gui(settings, log) -> None:
    """GUI起動."""
    from PySide6.QtWidgets import QApplication
    from fxbot.gui.main_window import MainWindow

    log.info("=== FXBot3 GUI 起動 ===")

    app = QApplication(sys.argv)
    app.setStyle("Fusion")

    window = MainWindow(settings)
    window.show()

    sys.exit(app.exec())


def _run_cli(settings, log) -> None:
    """CLIモード — MT5接続→ペア検出→OHLCV取得."""
    from fxbot.mt5.connection import connect, disconnect, get_account_info
    from fxbot.mt5.symbols import detect_symbols, save_symbols
    from fxbot.mt5.data_feed import fetch_multi_timeframe

    log.info("=== FXBot3 CLI モード ===")

    if not connect(settings):
        log.error("MT5接続失敗。終了します。")
        sys.exit(1)

    try:
        info = get_account_info()
        if info:
            log.info(f"口座: {info['login']} | 残高: {info['balance']} {info['currency']}")

        symbols = detect_symbols(settings)
        if symbols:
            save_symbols(symbols, settings)
            symbol_names = [s["name"] for s in symbols]
            log.info(f"検出ペア: {symbol_names[:10]}{'...' if len(symbol_names) > 10 else ''}")
        else:
            log.warning("FXペアが検出されませんでした")
            return

        demo_symbols = symbol_names[:3]
        for sym in demo_symbols:
            log.info(f"--- {sym} データ取得 ---")
            data = fetch_multi_timeframe(sym, settings)
            for tf, df in data.items():
                log.info(f"  {tf}: {len(df)}行, 期間: {df.index[0]} ~ {df.index[-1]}")

        log.info("=== データ取得完了 ===")

    finally:
        disconnect()


if __name__ == "__main__":
    main()
