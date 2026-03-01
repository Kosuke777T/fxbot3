"""Slack 通知モジュール（Incoming Webhook 経由）."""

from __future__ import annotations

import json
import logging
import ssl
import urllib.request

import certifi

log = logging.getLogger(__name__)

# モジュールレベルのシングルトン
_notifier: "SlackNotifier | None" = None


def configure(config) -> None:
    """SlackNotifierConfig でシングルトンを初期化."""
    global _notifier
    _notifier = SlackNotifier(config)


def get() -> "SlackNotifier | None":
    return _notifier


class SlackNotifier:
    def __init__(self, config):
        self._cfg = config

    def _send(self, text: str) -> bool:
        if not self._cfg.enabled or not self._cfg.webhook_url:
            return False
        payload = json.dumps({"text": text}).encode()
        req = urllib.request.Request(
            self._cfg.webhook_url,
            data=payload,
            headers={"Content-Type": "application/json"},
        )
        try:
            ssl_ctx = ssl.create_default_context(cafile=certifi.where())
            with urllib.request.urlopen(req, timeout=5, context=ssl_ctx) as resp:
                return resp.status == 200
        except Exception as e:
            log.warning(f"Slack通知失敗: {e}")
            return False

    def notify_entry(self, symbol, direction, lot, price, sl, tp, confidence=None, model_version=None):
        if not self._cfg.notify_entry:
            return
        arrow = "📈" if direction.upper() == "BUY" else "📉"
        conf_str = f" | 信頼度: {confidence:.1%}" if confidence is not None else ""
        text = (
            f"{arrow} *エントリー [{symbol} {direction.upper()}]*\n"
            f"価格: {price} | ロット: {lot:.2f}\n"
            f"SL: {sl} | TP: {tp}{conf_str}"
        )
        self._send(text)

    def notify_exit(self, symbol, direction, lot, entry_price, exit_price, pnl, reason):
        if not self._cfg.notify_exit:
            return
        pnl_str = f"+{pnl:,.0f}" if pnl >= 0 else f"{pnl:,.0f}"
        icon = "✅" if pnl >= 0 else "❌"
        reason_label = {"sl": "SL", "tp": "TP", "trailing": "TRL", "manual": "手動"}.get(reason, reason)
        text = (
            f"{icon} *決済 [{reason_label}] [{symbol} {direction.upper()}]*\n"
            f"エントリー: {entry_price} → 決済: {exit_price}\n"
            f"損益: {pnl_str}円 | ロット: {lot:.2f}"
        )
        self._send(text)

    def notify_error(self, message: str):
        if not self._cfg.notify_error:
            return
        self._send(f"⚠️ *エラー発生*\n{message[:500]}")

    def notify_model_degraded(self, warnings: list[str]):
        if not self._cfg.notify_model_degraded:
            return
        detail = "\n".join(f"• {w}" for w in warnings)
        self._send(f"⚠️ *モデル劣化検知*\n{detail}")

    def notify_retraining_done(self, win_rate: float | None = None, sharpe: float | None = None):
        if not self._cfg.notify_retraining_done:
            return
        detail = ""
        if win_rate is not None:
            detail += f"\n勝率: {win_rate:.1%}"
        if sharpe is not None:
            detail += f" | Sharpe: {sharpe:.2f}"
        self._send(f"🔄 *自動再学習完了*{detail}")

    def notify_backtest_done(self, summary: str = ""):
        if not self._cfg.notify_backtest_done:
            return
        self._send(f"📊 *バックテスト完了*\n{summary}" if summary else "📊 *バックテスト完了*")
