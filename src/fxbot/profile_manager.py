"""設定プロファイル管理 — SQLiteベースの設定バージョン管理."""

from __future__ import annotations

import dataclasses
import hashlib
import json
import sqlite3
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from fxbot.logger import get_logger

log = get_logger(__name__)

_SENSITIVE_KEYS = {"login", "password", "webhook_url"}

_CREATE_SETTINGS_PROFILES = """
CREATE TABLE IF NOT EXISTS settings_profiles (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    profile_id  TEXT NOT NULL UNIQUE,
    name        TEXT NOT NULL,
    description TEXT DEFAULT '',
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL,
    is_archived INTEGER NOT NULL DEFAULT 0,
    base_profile_id TEXT
)
"""

_CREATE_SETTINGS_SNAPSHOTS = """
CREATE TABLE IF NOT EXISTS settings_snapshots (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    profile_id    TEXT NOT NULL,
    version_no    INTEGER NOT NULL,
    snapshot_hash TEXT NOT NULL UNIQUE,
    settings_json TEXT NOT NULL,
    note          TEXT DEFAULT '',
    created_at    TEXT NOT NULL,
    is_active     INTEGER NOT NULL DEFAULT 0,
    FOREIGN KEY(profile_id) REFERENCES settings_profiles(profile_id),
    UNIQUE(profile_id, version_no)
)
"""

_CREATE_RUN_SESSIONS = """
CREATE TABLE IF NOT EXISTS run_sessions (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id       TEXT NOT NULL UNIQUE,
    profile_id   TEXT,
    snapshot_id  INTEGER,
    run_type     TEXT NOT NULL,
    started_at   TEXT NOT NULL,
    ended_at     TEXT,
    symbol_scope TEXT DEFAULT '',
    model_version TEXT DEFAULT '',
    environment  TEXT DEFAULT 'live',
    note         TEXT DEFAULT '',
    FOREIGN KEY(profile_id) REFERENCES settings_profiles(profile_id),
    FOREIGN KEY(snapshot_id) REFERENCES settings_snapshots(id)
)
"""

_CREATE_PROFILE_PERFORMANCE_SUMMARY = """
CREATE TABLE IF NOT EXISTS profile_performance_summary (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id       TEXT NOT NULL,
    profile_id   TEXT NOT NULL,
    snapshot_id  INTEGER,
    metric_scope TEXT NOT NULL,
    symbol       TEXT DEFAULT '',
    trades_count INTEGER NOT NULL DEFAULT 0,
    win_rate     REAL,
    profit_factor REAL,
    sharpe       REAL,
    max_drawdown REAL,
    net_profit   REAL,
    avg_profit   REAL,
    avg_loss     REAL,
    period_from  TEXT,
    period_to    TEXT,
    created_at   TEXT NOT NULL,
    FOREIGN KEY(run_id) REFERENCES run_sessions(run_id)
)
"""


def _sanitize_settings_dict(d: dict[str, Any]) -> dict[str, Any]:
    """認証情報を除いた設定辞書を再帰的に構築."""
    result: dict[str, Any] = {}
    for k, v in d.items():
        if k in _SENSITIVE_KEYS:
            continue
        if isinstance(v, dict):
            result[k] = _sanitize_settings_dict(v)
        else:
            result[k] = v
    return result


def _now_str() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _profile_id_now() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


class ProfileManager:
    """設定プロファイルのCRUDとセッション管理."""

    def __init__(self, db_path: Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self.db_path))
        self._conn.row_factory = sqlite3.Row
        self._ensure_tables()

    def _ensure_tables(self) -> None:
        for sql in [
            _CREATE_SETTINGS_PROFILES,
            _CREATE_SETTINGS_SNAPSHOTS,
            _CREATE_RUN_SESSIONS,
            _CREATE_PROFILE_PERFORMANCE_SUMMARY,
        ]:
            self._conn.execute(sql)
        self._conn.commit()

    def _settings_to_json(self, settings: Any) -> str:
        d = dataclasses.asdict(settings)
        sanitized = _sanitize_settings_dict(d)
        return json.dumps(sanitized, ensure_ascii=False, sort_keys=True)

    def _compute_hash(self, settings_json: str) -> str:
        return hashlib.md5(settings_json.encode()).hexdigest()

    def save_profile(
        self,
        name: str,
        description: str,
        settings: Any,
        base_profile_id: str | None = None,
    ) -> tuple[str, int]:
        """新規プロファイル + スナップショット保存。(profile_id, snapshot_id) を返す。"""
        profile_id = _profile_id_now()
        now = _now_str()
        settings_json = self._settings_to_json(settings)
        snap_hash = self._compute_hash(settings_json)

        # 既存の同一内容スナップショット確認
        existing = self._conn.execute(
            "SELECT id, profile_id FROM settings_snapshots WHERE snapshot_hash=?",
            (snap_hash,),
        ).fetchone()
        if existing:
            log.info(f"同一内容のスナップショット既存 profile_id={existing['profile_id']}")

        self._conn.execute(
            """
            INSERT INTO settings_profiles
                (profile_id, name, description, created_at, updated_at, is_archived, base_profile_id)
            VALUES (?, ?, ?, ?, ?, 0, ?)
            """,
            (profile_id, name, description, now, now, base_profile_id),
        )

        cursor = self._conn.execute(
            """
            INSERT INTO settings_snapshots
                (profile_id, version_no, snapshot_hash, settings_json, note, created_at, is_active)
            VALUES (?, 1, ?, ?, '', ?, 1)
            """,
            (profile_id, snap_hash, settings_json, now),
        )
        snapshot_id = cursor.lastrowid
        self._conn.commit()
        log.info(f"プロファイル保存: {name} ({profile_id}) snapshot_id={snapshot_id}")
        return profile_id, snapshot_id

    def update_snapshot(self, profile_id: str, settings: Any, note: str = "") -> int:
        """既存プロファイルに新バージョンを追記。新 snapshot_id を返す。"""
        settings_json = self._settings_to_json(settings)
        snap_hash = self._compute_hash(settings_json)

        # 重複チェック
        existing = self._conn.execute(
            "SELECT id FROM settings_snapshots WHERE snapshot_hash=? AND profile_id=?",
            (snap_hash, profile_id),
        ).fetchone()
        if existing:
            log.info(f"同一内容のスナップショット既存 id={existing['id']}")
            return existing["id"]

        # 現在の最大バージョン番号を取得
        row = self._conn.execute(
            "SELECT MAX(version_no) AS max_v FROM settings_snapshots WHERE profile_id=?",
            (profile_id,),
        ).fetchone()
        next_version = (row["max_v"] or 0) + 1
        now = _now_str()

        # 既存スナップショットを非アクティブに
        self._conn.execute(
            "UPDATE settings_snapshots SET is_active=0 WHERE profile_id=?",
            (profile_id,),
        )

        cursor = self._conn.execute(
            """
            INSERT INTO settings_snapshots
                (profile_id, version_no, snapshot_hash, settings_json, note, created_at, is_active)
            VALUES (?, ?, ?, ?, ?, ?, 1)
            """,
            (profile_id, next_version, snap_hash, settings_json, note, now),
        )
        snapshot_id = cursor.lastrowid

        self._conn.execute(
            "UPDATE settings_profiles SET updated_at=? WHERE profile_id=?",
            (now, profile_id),
        )
        self._conn.commit()
        log.info(f"スナップショット追加: profile_id={profile_id} v{next_version} id={snapshot_id}")
        return snapshot_id

    def load_profiles(self, include_archived: bool = False) -> list[dict]:
        """settings_profiles + 最新 snapshot の settings_json を JOIN して返す。"""
        where = "" if include_archived else "WHERE p.is_archived=0"
        cursor = self._conn.execute(
            f"""
            SELECT
                p.profile_id, p.name, p.description, p.created_at, p.updated_at,
                p.is_archived, p.base_profile_id,
                s.id AS snapshot_id, s.version_no, s.settings_json, s.created_at AS snap_created_at
            FROM settings_profiles p
            LEFT JOIN settings_snapshots s
                ON s.profile_id = p.profile_id AND s.is_active = 1
            {where}
            ORDER BY p.created_at DESC
            """
        )
        return [dict(row) for row in cursor.fetchall()]

    def get_snapshot(self, snapshot_id: int) -> dict | None:
        """snapshot の settings_json を dict で返す。"""
        row = self._conn.execute(
            "SELECT settings_json FROM settings_snapshots WHERE id=?",
            (snapshot_id,),
        ).fetchone()
        if row is None:
            return None
        return json.loads(row["settings_json"])

    def apply_profile(self, snapshot_id: int, settings: Any) -> None:
        """snapshot の settings_json を現在の settings に上書き反映。"""
        snap_dict = self.get_snapshot(snapshot_id)
        if snap_dict is None:
            log.error(f"スナップショット未発見: id={snapshot_id}")
            return

        import dataclasses as _dc
        from fxbot.config import (
            DataConfig, TradingConfig, RiskConfig, ModelConfig,
            BacktestConfig, RetrainingConfig, LoggingConfig,
            TradeLoggingConfig, MarketFilterConfig, SlackNotifierConfig,
        )

        def _apply(cls, attr: str, key: str) -> None:
            if key in snap_dict:
                field_names = {f.name for f in _dc.fields(cls)}
                filtered = {k: v for k, v in snap_dict[key].items() if k in field_names}
                setattr(settings, attr, cls(**filtered))

        _apply(DataConfig, "data", "data")
        _apply(TradingConfig, "trading", "trading")
        _apply(RiskConfig, "risk", "risk")
        _apply(ModelConfig, "model", "model")
        _apply(BacktestConfig, "backtest", "backtest")
        _apply(RetrainingConfig, "retraining", "retraining")
        _apply(LoggingConfig, "logging", "logging")
        _apply(TradeLoggingConfig, "trade_logging", "trade_logging")
        _apply(MarketFilterConfig, "market_filter", "market_filter")
        _apply(SlackNotifierConfig, "slack", "slack")
        log.info(f"プロファイル適用: snapshot_id={snapshot_id}")

    def archive_profile(self, profile_id: str) -> None:
        self._conn.execute(
            "UPDATE settings_profiles SET is_archived=1, updated_at=? WHERE profile_id=?",
            (_now_str(), profile_id),
        )
        self._conn.commit()
        log.info(f"プロファイルアーカイブ: {profile_id}")

    def start_session(
        self,
        profile_id: str,
        snapshot_id: int,
        run_type: str,
        symbols: list[str],
        model_version: str,
        environment: str,
    ) -> str:
        """run_sessions に INSERT し run_id (UUID) を返す。"""
        run_id = str(uuid.uuid4())
        now = _now_str()
        self._conn.execute(
            """
            INSERT INTO run_sessions
                (run_id, profile_id, snapshot_id, run_type, started_at,
                 symbol_scope, model_version, environment)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                run_id, profile_id, snapshot_id, run_type, now,
                json.dumps(symbols, ensure_ascii=False),
                model_version, environment,
            ),
        )
        self._conn.commit()
        log.info(f"セッション開始: run_id={run_id} type={run_type} profile={profile_id}")
        return run_id

    def end_session(self, run_id: str) -> None:
        """ended_at を更新。"""
        self._conn.execute(
            "UPDATE run_sessions SET ended_at=? WHERE run_id=?",
            (_now_str(), run_id),
        )
        self._conn.commit()
        log.info(f"セッション終了: run_id={run_id}")

    def get_profile_performance(self, run_type: str = "live") -> list[dict]:
        """profile_id 別成績集計（run_sessions JOIN trades GROUP BY profile_id）."""
        cursor = self._conn.execute(
            """
            SELECT
                p.profile_id,
                p.name AS profile_name,
                p.created_at AS profile_created_at,
                rs.run_id,
                rs.started_at,
                rs.ended_at,
                rs.snapshot_id,
                COUNT(t.id) AS trades_count,
                SUM(CASE WHEN t.pnl > 0 THEN 1 ELSE 0 END) AS win_count,
                SUM(t.pnl) AS net_profit,
                AVG(CASE WHEN t.pnl > 0 THEN t.pnl END) AS avg_profit,
                AVG(CASE WHEN t.pnl < 0 THEN t.pnl END) AS avg_loss,
                MIN(t.timestamp) AS period_from,
                MAX(t.exit_time) AS period_to
            FROM run_sessions rs
            LEFT JOIN settings_profiles p ON p.profile_id = rs.profile_id
            LEFT JOIN trades t ON t.run_id = rs.run_id AND t.pnl IS NOT NULL
            WHERE rs.run_type = ?
            GROUP BY rs.run_id, rs.profile_id
            ORDER BY rs.started_at DESC
            """,
            (run_type,),
        )
        results = []
        for row in cursor.fetchall():
            d = dict(row)
            tc = d.get("trades_count") or 0
            wc = d.get("win_count") or 0
            d["win_rate"] = (wc / tc) if tc > 0 else None
            avg_p = d.get("avg_profit") or 0.0
            avg_l = abs(d.get("avg_loss") or 0.0)
            d["profit_factor"] = (avg_p / avg_l) if avg_l > 0 else None
            results.append(d)
        return results

    def save_performance_summary(
        self,
        run_id: str,
        profile_id: str,
        snapshot_id: int,
        rows: list[dict],
    ) -> None:
        """profile_performance_summary に一括 INSERT。"""
        now = _now_str()
        for row in rows:
            self._conn.execute(
                """
                INSERT INTO profile_performance_summary
                    (run_id, profile_id, snapshot_id, metric_scope, symbol,
                     trades_count, win_rate, profit_factor, sharpe, max_drawdown,
                     net_profit, avg_profit, avg_loss, period_from, period_to, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id, profile_id, snapshot_id,
                    row.get("metric_scope", "overall"),
                    row.get("symbol", ""),
                    row.get("trades_count", 0),
                    row.get("win_rate"),
                    row.get("profit_factor"),
                    row.get("sharpe"),
                    row.get("max_drawdown"),
                    row.get("net_profit"),
                    row.get("avg_profit"),
                    row.get("avg_loss"),
                    row.get("period_from"),
                    row.get("period_to"),
                    now,
                ),
            )
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()
