"""取引ログ — SQLiteベースの取引記録・分析."""

from __future__ import annotations

import csv
import json
import sqlite3
from dataclasses import asdict, dataclass
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

_CREATE_ANALYSIS_EVENTS_TABLE = """
CREATE TABLE IF NOT EXISTS analysis_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    symbol TEXT NOT NULL,
    model_mode TEXT,
    action TEXT NOT NULL,
    hold_reason TEXT,
    prediction REAL,
    confidence REAL,
    lot REAL,
    spread_pips REAL,
    regime TEXT,
    h4_regime TEXT,
    current_hour_utc INTEGER,
    blocked_filters TEXT,
    position_allowed INTEGER NOT NULL DEFAULT 1,
    model_degraded INTEGER NOT NULL DEFAULT 0,
    order_attempted INTEGER NOT NULL DEFAULT 0,
    order_success INTEGER NOT NULL DEFAULT 0,
    entered INTEGER NOT NULL DEFAULT 0,
    skip_reason TEXT
)
"""

_CREATE_ANALYSIS_FILTERS_TABLE = """
CREATE TABLE IF NOT EXISTS analysis_filter_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id INTEGER NOT NULL,
    timestamp TEXT NOT NULL,
    symbol TEXT NOT NULL,
    filter_name TEXT NOT NULL,
    display_name TEXT NOT NULL,
    enabled INTEGER NOT NULL DEFAULT 0,
    passed INTEGER NOT NULL DEFAULT 1,
    reason TEXT,
    current_value TEXT,
    threshold_str TEXT
)
"""

_CREATE_INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_trades_symbol_timestamp ON trades(symbol, timestamp)",
    "CREATE INDEX IF NOT EXISTS idx_analysis_events_symbol_timestamp ON analysis_events(symbol, timestamp)",
    "CREATE INDEX IF NOT EXISTS idx_analysis_filter_events_symbol_name ON analysis_filter_events(symbol, filter_name)",
]

_ALTER_MIGRATIONS = [
    "ALTER TABLE trades ADD COLUMN profile_id TEXT",
    "ALTER TABLE trades ADD COLUMN snapshot_id INTEGER",
    "ALTER TABLE trades ADD COLUMN run_id TEXT",
    "ALTER TABLE analysis_events ADD COLUMN profile_id TEXT",
    "ALTER TABLE analysis_events ADD COLUMN snapshot_id INTEGER",
    "ALTER TABLE analysis_events ADD COLUMN run_id TEXT",
]


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
    profile_id: Optional[str] = None
    snapshot_id: Optional[int] = None
    run_id: Optional[str] = None


class TradeLogger:
    """SQLiteベースの取引ログ管理."""

    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self.db_path))
        self._conn.row_factory = sqlite3.Row
        self._conn.execute(_CREATE_TABLE)
        self._conn.execute(_CREATE_ANALYSIS_EVENTS_TABLE)
        self._conn.execute(_CREATE_ANALYSIS_FILTERS_TABLE)
        for query in _CREATE_INDEXES:
            self._conn.execute(query)
        self._conn.commit()
        self._run_migrations()
        log.debug(f"TradeLogger初期化: {self.db_path}")

    def _run_migrations(self) -> None:
        """新規テーブル作成 + 既存テーブルへの冪等カラム追加."""
        from fxbot.profile_manager import (
            _CREATE_SETTINGS_PROFILES, _CREATE_SETTINGS_SNAPSHOTS,
            _CREATE_RUN_SESSIONS, _CREATE_PROFILE_PERFORMANCE_SUMMARY,
        )
        for sql in [_CREATE_SETTINGS_PROFILES, _CREATE_SETTINGS_SNAPSHOTS,
                    _CREATE_RUN_SESSIONS, _CREATE_PROFILE_PERFORMANCE_SUMMARY]:
            self._conn.execute(sql)
        for alter in _ALTER_MIGRATIONS:
            try:
                self._conn.execute(alter)
            except sqlite3.OperationalError:
                pass
        self._conn.commit()

    @staticmethod
    def _symbol_clause(symbols: list[str], column: str = "symbol") -> tuple[str, list]:
        if not symbols:
            return "", []
        placeholders = ", ".join(["?"] * len(symbols))
        return f" WHERE {column} IN ({placeholders})", list(symbols)

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

    def log_analysis_event(self, event: dict, filter_statuses: list[dict]) -> int:
        """戦略判定イベントと各フィルター状態を記録."""
        blocked = [
            fs.get("filter_name", "")
            for fs in filter_statuses
            if fs.get("enabled", False) and not fs.get("passed", True)
        ]
        cursor = self._conn.execute(
            """
            INSERT INTO analysis_events (
                timestamp, symbol, model_mode, action, hold_reason,
                prediction, confidence, lot, spread_pips,
                regime, h4_regime, current_hour_utc, blocked_filters,
                position_allowed, model_degraded, order_attempted,
                order_success, entered, skip_reason,
                profile_id, snapshot_id, run_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event.get("timestamp"),
                event.get("symbol"),
                event.get("model_mode"),
                event.get("action"),
                event.get("hold_reason"),
                event.get("prediction"),
                event.get("confidence"),
                event.get("lot"),
                event.get("spread_pips"),
                event.get("regime"),
                event.get("h4_regime"),
                event.get("current_hour_utc"),
                json.dumps(blocked, ensure_ascii=False),
                int(bool(event.get("position_allowed", True))),
                int(bool(event.get("model_degraded", False))),
                int(bool(event.get("order_attempted", False))),
                int(bool(event.get("order_success", False))),
                int(bool(event.get("entered", False))),
                event.get("skip_reason"),
                event.get("profile_id"),
                event.get("snapshot_id"),
                event.get("run_id"),
            ),
        )
        event_id = cursor.lastrowid

        rows = []
        for fs in filter_statuses:
            rows.append((
                event_id,
                event.get("timestamp"),
                event.get("symbol"),
                fs.get("filter_name", ""),
                fs.get("display_name", fs.get("filter_name", "")),
                int(bool(fs.get("enabled", False))),
                int(bool(fs.get("passed", True))),
                fs.get("reason", ""),
                fs.get("current_value", ""),
                fs.get("threshold_str", ""),
            ))
        if rows:
            self._conn.executemany(
                """
                INSERT INTO analysis_filter_events (
                    event_id, timestamp, symbol, filter_name, display_name,
                    enabled, passed, reason, current_value, threshold_str
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                rows,
            )
        self._conn.commit()
        return event_id

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

    def get_strategy_summary(self, symbols: list[str]) -> dict:
        """戦略分析用のサマリーを返す."""
        where, params = self._symbol_clause(symbols)
        row = self._conn.execute(
            f"""
            SELECT
                COUNT(*) AS eval_count,
                SUM(CASE WHEN action='buy' THEN 1 ELSE 0 END) AS buy_count,
                SUM(CASE WHEN action='sell' THEN 1 ELSE 0 END) AS sell_count,
                SUM(CASE WHEN action='hold' THEN 1 ELSE 0 END) AS hold_count,
                SUM(entered) AS entered_count,
                SUM(CASE WHEN skip_reason='position_limit' THEN 1 ELSE 0 END) AS position_blocked,
                SUM(CASE WHEN skip_reason='model_degraded' THEN 1 ELSE 0 END) AS model_blocked,
                SUM(CASE WHEN order_attempted=1 AND order_success=0 THEN 1 ELSE 0 END) AS order_failed
            FROM analysis_events
            {where}
            """,
            params,
        ).fetchone()
        eval_count = int(row["eval_count"] or 0)
        entered_count = int(row["entered_count"] or 0)
        return {
            "eval_count": eval_count,
            "buy_count": int(row["buy_count"] or 0),
            "sell_count": int(row["sell_count"] or 0),
            "hold_count": int(row["hold_count"] or 0),
            "entered_count": entered_count,
            "entry_rate": (entered_count / eval_count) if eval_count > 0 else 0.0,
            "position_blocked": int(row["position_blocked"] or 0),
            "model_blocked": int(row["model_blocked"] or 0),
            "order_failed": int(row["order_failed"] or 0),
        }

    def get_action_breakdown(self, symbols: list[str]) -> list[dict]:
        """BUY/SELL/HOLD別の判定件数を返す."""
        where, params = self._symbol_clause(symbols)
        cursor = self._conn.execute(
            f"""
            SELECT
                action,
                COUNT(*) AS count,
                SUM(entered) AS entered_count,
                SUM(CASE WHEN order_attempted=1 AND order_success=0 THEN 1 ELSE 0 END) AS order_failed
            FROM analysis_events
            {where}
            GROUP BY action
            ORDER BY count DESC
            """,
            params,
        )
        return [dict(row) for row in cursor.fetchall()]

    def get_hold_reason_breakdown(self, symbols: list[str]) -> list[dict]:
        """HOLD理由別件数を返す."""
        where, params = self._symbol_clause(symbols)
        extra = "action='hold'"
        if where:
            where = where + f" AND {extra}"
        else:
            where = f" WHERE {extra}"
        cursor = self._conn.execute(
            f"""
            SELECT
                COALESCE(hold_reason, 'other') AS hold_reason,
                COUNT(*) AS count
            FROM analysis_events
            {where}
            GROUP BY COALESCE(hold_reason, 'other')
            ORDER BY count DESC, hold_reason
            """,
            params,
        )
        return [dict(row) for row in cursor.fetchall()]

    def get_filter_pass_rates(self, symbols: list[str]) -> list[dict]:
        """フィルター別の通過率を返す."""
        where, params = self._symbol_clause(symbols)
        cursor = self._conn.execute(
            f"""
            SELECT
                filter_name,
                display_name,
                SUM(CASE WHEN enabled=1 THEN 1 ELSE 0 END) AS enabled_count,
                SUM(CASE WHEN enabled=1 AND passed=1 THEN 1 ELSE 0 END) AS pass_count,
                SUM(CASE WHEN enabled=1 AND passed=0 THEN 1 ELSE 0 END) AS block_count
            FROM analysis_filter_events
            {where}
            GROUP BY filter_name, display_name
            ORDER BY display_name
            """,
            params,
        )
        results = []
        for row in cursor.fetchall():
            enabled_count = int(row["enabled_count"] or 0)
            pass_count = int(row["pass_count"] or 0)
            results.append({
                "filter_name": row["filter_name"],
                "display_name": row["display_name"],
                "enabled_count": enabled_count,
                "pass_count": pass_count,
                "block_count": int(row["block_count"] or 0),
                "pass_rate": (pass_count / enabled_count) if enabled_count > 0 else None,
            })
        return results

    def get_direction_performance(self, symbols: list[str]) -> list[dict]:
        """方向別成績を返す."""
        where, params = self._symbol_clause(symbols)
        if where:
            where += " AND pnl IS NOT NULL"
        else:
            where = " WHERE pnl IS NOT NULL"
        cursor = self._conn.execute(
            f"""
            SELECT
                UPPER(direction) AS direction,
                COUNT(*) AS count,
                SUM(pnl) AS total_pnl,
                AVG(pnl) AS avg_pnl,
                AVG(CASE WHEN pnl > 0 THEN 1.0 ELSE 0.0 END) AS win_rate
            FROM trades
            {where}
            GROUP BY UPPER(direction)
            ORDER BY count DESC
            """,
            params,
        )
        return [dict(row) for row in cursor.fetchall()]

    def get_exit_reason_performance(self, symbols: list[str]) -> list[dict]:
        """決済理由別成績を返す."""
        where, params = self._symbol_clause(symbols)
        if where:
            where += " AND pnl IS NOT NULL"
        else:
            where = " WHERE pnl IS NOT NULL"
        cursor = self._conn.execute(
            f"""
            SELECT
                COALESCE(exit_reason, 'open') AS exit_reason,
                COUNT(*) AS count,
                SUM(pnl) AS total_pnl,
                AVG(pnl) AS avg_pnl,
                AVG(CASE WHEN pnl > 0 THEN 1.0 ELSE 0.0 END) AS win_rate
            FROM trades
            {where}
            GROUP BY COALESCE(exit_reason, 'open')
            ORDER BY count DESC
            """,
            params,
        )
        return [dict(row) for row in cursor.fetchall()]

    def get_hourly_performance(self, symbols: list[str]) -> list[dict]:
        """エントリー時刻の時間帯別成績を返す."""
        where, params = self._symbol_clause(symbols)
        if where:
            where += " AND pnl IS NOT NULL"
        else:
            where = " WHERE pnl IS NOT NULL"
        cursor = self._conn.execute(
            f"""
            SELECT
                substr(timestamp, 12, 2) AS hour_bucket,
                COUNT(*) AS count,
                SUM(pnl) AS total_pnl,
                AVG(pnl) AS avg_pnl,
                AVG(CASE WHEN pnl > 0 THEN 1.0 ELSE 0.0 END) AS win_rate
            FROM trades
            {where}
            GROUP BY substr(timestamp, 12, 2)
            ORDER BY hour_bucket
            """,
            params,
        )
        return [dict(row) for row in cursor.fetchall()]

    def get_prediction_bucket_performance(self, symbols: list[str]) -> list[dict]:
        """予測値帯別成績を返す."""
        where, params = self._symbol_clause(symbols)
        if where:
            where += " AND pnl IS NOT NULL"
        else:
            where = " WHERE pnl IS NOT NULL"
        cursor = self._conn.execute(
            f"""
            SELECT
                CASE
                    WHEN ABS(prediction) < 0.0002 THEN '<0.0002'
                    WHEN ABS(prediction) < 0.0005 THEN '0.0002-0.0005'
                    WHEN ABS(prediction) < 0.0010 THEN '0.0005-0.0010'
                    ELSE '>=0.0010'
                END AS bucket,
                COUNT(*) AS count,
                SUM(pnl) AS total_pnl,
                AVG(pnl) AS avg_pnl,
                AVG(CASE WHEN pnl > 0 THEN 1.0 ELSE 0.0 END) AS win_rate
            FROM trades
            {where}
            GROUP BY bucket
            ORDER BY bucket
            """,
            params,
        )
        return [dict(row) for row in cursor.fetchall()]

    def get_model_version_performance(self, symbols: list[str]) -> list[dict]:
        """モデルバージョン別成績を返す."""
        where, params = self._symbol_clause(symbols)
        if where:
            where += " AND pnl IS NOT NULL"
        else:
            where = " WHERE pnl IS NOT NULL"
        cursor = self._conn.execute(
            f"""
            SELECT
                COALESCE(model_version, 'unknown') AS model_version,
                COUNT(*) AS count,
                SUM(pnl) AS total_pnl,
                AVG(pnl) AS avg_pnl,
                AVG(CASE WHEN pnl > 0 THEN 1.0 ELSE 0.0 END) AS win_rate
            FROM trades
            {where}
            GROUP BY COALESCE(model_version, 'unknown')
            ORDER BY count DESC, model_version DESC
            """,
            params,
        )
        return [dict(row) for row in cursor.fetchall()]

    def get_recent_analysis_events(self, symbols: list[str], n: int = 20) -> list[dict]:
        """直近の戦略判定イベントを返す."""
        where, params = self._symbol_clause(symbols)
        cursor = self._conn.execute(
            f"""
            SELECT
                timestamp, symbol, action, hold_reason, prediction, confidence,
                entered, skip_reason, blocked_filters, profile_id
            FROM analysis_events
            {where}
            ORDER BY id DESC
            LIMIT ?
            """,
            [*params, n],
        )
        rows = [dict(row) for row in cursor.fetchall()]
        for row in rows:
            try:
                row["blocked_filters"] = json.loads(row["blocked_filters"] or "[]")
            except json.JSONDecodeError:
                row["blocked_filters"] = []
        return rows

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
