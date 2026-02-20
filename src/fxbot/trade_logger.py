"""取引ログ — SQLiteベースの取引記録・分析."""

from __future__ import annotations

import csv
import sqlite3
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional

from fxbot.logger import get_logger

log = get_logger(__name__)

_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS trades (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    symbol TEXT NOT NULL,
    direction TEXT NOT NULL,
    entry_price REAL NOT NULL,
    sl REAL,
    tp REAL,
    lot REAL NOT NULL,
    prediction REAL,
    confidence REAL,
    atr REAL,
    balance REAL,
    exit_price REAL,
    exit_time TEXT,
    exit_reason TEXT,
    pnl REAL,
    ticket INTEGER,
    model_version TEXT
)
"""


@dataclass
class TradeRecord:
    timestamp: str
    symbol: str
    direction: str
    entry_price: float
    sl: float
    tp: float
    lot: float
    prediction: float
    confidence: float
    atr: float
    balance: float
    exit_price: Optional[float] = None
    exit_time: Optional[str] = None
    exit_reason: Optional[str] = None
    pnl: Optional[float] = None
    ticket: Optional[int] = None
    model_version: Optional[str] = None


class TradeLogger:
    """SQLiteベースの取引ログ管理."""

    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self.db_path))
        self._conn.row_factory = sqlite3.Row
        self._conn.execute(_CREATE_TABLE)
        self._conn.commit()
        log.info(f"TradeLogger初期化: {self.db_path}")

    def log_entry(self, record: TradeRecord) -> int:
        """エントリーを記録し、レコードIDを返す."""
        data = asdict(record)
        cols = ", ".join(data.keys())
        placeholders = ", ".join(["?"] * len(data))
        cursor = self._conn.execute(
            f"INSERT INTO trades ({cols}) VALUES ({placeholders})",
            list(data.values()),
        )
        self._conn.commit()
        row_id = cursor.lastrowid
        log.info(f"取引記録[entry]: id={row_id} {record.direction} {record.symbol} "
                 f"@ {record.entry_price} lot={record.lot}")
        return row_id

    def log_exit(
        self,
        ticket: int,
        exit_price: float,
        exit_time: str,
        exit_reason: str,
        pnl: float,
    ) -> None:
        """クローズ済みポジションのexit情報を更新."""
        self._conn.execute(
            "UPDATE trades SET exit_price=?, exit_time=?, exit_reason=?, pnl=? "
            "WHERE ticket=? AND exit_price IS NULL",
            (exit_price, exit_time, exit_reason, pnl, ticket),
        )
        self._conn.commit()
        log.info(f"取引記録[exit]: ticket={ticket} reason={exit_reason} pnl={pnl:.2f}")

    def get_recent_trades(self, n: int = 50) -> list[dict]:
        """直近N件の取引を取得."""
        cursor = self._conn.execute(
            "SELECT * FROM trades ORDER BY id DESC LIMIT ?", (n,)
        )
        return [dict(row) for row in cursor.fetchall()]

    def get_rolling_metrics(self, window: int = 20) -> dict:
        """直近window件のクローズ済み取引からローリングメトリクスを計算."""
        cursor = self._conn.execute(
            "SELECT pnl FROM trades WHERE pnl IS NOT NULL ORDER BY id DESC LIMIT ?",
            (window,),
        )
        rows = cursor.fetchall()
        if not rows:
            return {"count": 0, "win_rate": 0.0, "avg_pnl": 0.0, "sharpe": 0.0}

        pnls = [row["pnl"] for row in rows]
        count = len(pnls)
        wins = sum(1 for p in pnls if p > 0)
        win_rate = wins / count if count > 0 else 0.0
        avg_pnl = sum(pnls) / count

        import numpy as np
        pnl_arr = np.array(pnls)
        std = pnl_arr.std()
        sharpe = (pnl_arr.mean() / std) if std > 0 else 0.0

        return {
            "count": count,
            "win_rate": win_rate,
            "avg_pnl": avg_pnl,
            "total_pnl": sum(pnls),
            "sharpe": sharpe,
        }

    def export_csv(self, path: str | Path) -> None:
        """全取引をCSVにエクスポート."""
        cursor = self._conn.execute("SELECT * FROM trades ORDER BY id")
        rows = cursor.fetchall()
        if not rows:
            log.warning("エクスポート対象の取引がありません")
            return

        out_path = Path(path)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with open(out_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(rows[0].keys())
            for row in rows:
                writer.writerow(tuple(row))
        log.info(f"取引ログCSVエクスポート: {out_path} ({len(rows)}件)")

    def close(self) -> None:
        self._conn.close()
