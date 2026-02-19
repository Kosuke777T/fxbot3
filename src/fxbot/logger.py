"""ロガー設定."""

from __future__ import annotations

import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

from fxbot.config import Settings

_configured = False


def setup_logger(settings: Settings) -> logging.Logger:
    """アプリケーションロガーを構成して返す."""
    global _configured
    logger = logging.getLogger("fxbot")

    if _configured:
        return logger

    log_cfg = settings.logging
    logger.setLevel(getattr(logging, log_cfg.level.upper(), logging.INFO))

    fmt = logging.Formatter(
        "%(asctime)s [%(levelname)-8s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # コンソール出力
    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(fmt)
    logger.addHandler(console)

    # ファイル出力
    log_path = settings.resolve_path(log_cfg.file)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    file_handler = RotatingFileHandler(
        log_path,
        maxBytes=log_cfg.max_bytes,
        backupCount=log_cfg.backup_count,
        encoding="utf-8",
    )
    file_handler.setFormatter(fmt)
    logger.addHandler(file_handler)

    _configured = True
    return logger


def get_logger(name: str = "fxbot") -> logging.Logger:
    """子ロガーを取得."""
    return logging.getLogger(name)
