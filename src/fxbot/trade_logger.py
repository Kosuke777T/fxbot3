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
        log.debug(f"TradeLogger初期化: {self.db_path}")

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
        db_row_id: int | None = None,
    ) -> None:
        """クローズ済みポジションのexit情報を更新.

        ticket で更新できない場合（ticket=NULL等）は db_row_id でフォールバックする。
        """
        cursor = self._conn.execute(
            "UPDATE trades SET exit_price=?, exit_time=?, exit_reason=?, pnl=? "
            "WHERE ticket=? AND exit_price IS NULL",
            (exit_price, exit_time, exit_reason, pnl, ticket),
        )
        self._conn.commit()

        if cursor.rowcount == 0 and db_row_id is not None:
            # ticket マッチなし → db_row_id でフォールバック更新
            cursor = self._conn.execute(
                "UPDATE trades SET exit_price=?, exit_time=?, exit_reason=?, pnl=? "
                "WHERE id=? AND exit_price IS NULL",
                (exit_price, exit_time, exit_reason, pnl, db_row_id),
            )
            self._conn.commit()
            if cursor.rowcount == 0:
                log.warning(
                    f"クローズ記録0行更新: ticket={ticket} db_row_id={db_row_id} "
                    "— DBにticket未登録またはすでにexit済みの可能性"
                )
            else:
                log.info(
                    f"取引記録[exit/id]: db_row_id={db_row_id} ticket={ticket} "
                    f"reason={exit_reason} pnl={pnl:.2f}"
                )
        elif cursor.rowcount == 0:
            log.warning(
                f"クローズ記録0行更新: ticket={ticket} "
                "— DBにticket未登録またはすでにexit済みの可能性"
            )
        else:
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

    def get_symbol_performance(self, symbols: list[str]) -> list[dict]:
        """指定シンボルごとの成績を集計."""
        results: list[dict] = []

        for symbol in symbols:
            summary = self._conn.execute(
                """
                SELECT
                    COUNT(*) AS total_trades,
                    SUM(CASE WHEN pnl IS NOT NULL THEN 1 ELSE 0 END) AS closed_trades,
                    SUM(CASE WHEN pnl IS NULL THEN 1 ELSE 0 END) AS open_trades,
                    SUM(CASE WHEN pnl > 0 THEN 1 ELSE 0 END) AS wins,
                    COALESCE(SUM(pnl), 0.0) AS total_pnl,
                    AVG(pnl) AS avg_pnl,
                    MAX(pnl) AS best_pnl,
                    MIN(pnl) AS worst_pnl,
                    AVG(CASE WHEN pnl > 0 THEN pnl END) AS avg_win,
                    AVG(CASE WHEN pnl < 0 THEN pnl END) AS avg_loss
                FROM trades
                WHERE symbol=?
                """,
                (symbol,),
            ).fetchone()

            latest = self._conn.execute(
                """
                SELECT direction, exit_reason, pnl, COALESCE(exit_time, timestamp) AS last_time
                FROM trades
                WHERE symbol=?
                ORDER BY id DESC
                LIMIT 1
                """,
                (symbol,),
            ).fetchone()

            total_trades = int(summary["total_trades"] or 0)
            closed_trades = int(summary["closed_trades"] or 0)
            wins = int(summary["wins"] or 0)
            win_rate = (wins / closed_trades) if closed_trades > 0 else 0.0

            results.append({
                "symbol": symbol,
                "total_trades": total_trades,
                "closed_trades": closed_trades,
                "open_trades": int(summary["open_trades"] or 0),
                "win_rate": win_rate,
                "total_pnl": float(summary["total_pnl"] or 0.0),
                "avg_pnl": float(summary["avg_pnl"] or 0.0) if summary["avg_pnl"] is not None else None,
                "best_pnl": float(summary["best_pnl"] or 0.0) if summary["best_pnl"] is not None else None,
                "worst_pnl": float(summary["worst_pnl"] or 0.0) if summary["worst_pnl"] is not None else None,
                "avg_win": float(summary["avg_win"] or 0.0) if summary["avg_win"] is not None else None,
                "avg_loss": float(summary["avg_loss"] or 0.0) if summary["avg_loss"] is not None else None,
                "last_direction": latest["direction"] if latest else None,
                "last_exit_reason": latest["exit_reason"] if latest else None,
                "last_pnl": float(latest["pnl"] or 0.0) if latest and latest["pnl"] is not None else None,
                "last_time": latest["last_time"] if latest else None,
            })

        return results

    def get_unclosed_trades(self) -> list[dict]:
        """exit_price が NULL の未決済取引を返す（ticket が NULL のものは除く）."""
        cursor = self._conn.execute(
            "SELECT id, ticket, symbol FROM trades WHERE exit_price IS NULL AND ticket IS NOT NULL"
        )
        return [dict(row) for row in cursor.fetchall()]

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
