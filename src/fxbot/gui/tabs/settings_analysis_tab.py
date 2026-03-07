"""設定分析タブ — プロファイル成績ランキング / 差分 / グラフ / 通貨別比較."""

from __future__ import annotations

import json
from typing import Any

from PySide6.QtCore import Signal, QTimer
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (
    QComboBox,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QSplitter,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from fxbot.config import Settings
from fxbot.logger import get_logger

log = get_logger(__name__)

_SCORE_WEIGHTS = {"win_rate": 0.3, "profit_factor": 0.3, "sharpe": 0.2, "max_drawdown": 0.2}


def _calc_score(row: dict) -> float | None:
    wr = row.get("win_rate")
    pf = row.get("profit_factor")
    sharpe = row.get("sharpe")
    dd = row.get("max_drawdown")
    if wr is None and pf is None:
        return None
    score = 0.0
    if wr is not None:
        score += wr * _SCORE_WEIGHTS["win_rate"]
    if pf is not None:
        score += min(pf / 3.0, 1.0) * _SCORE_WEIGHTS["profit_factor"]
    if sharpe is not None:
        score += min(max(sharpe / 3.0, 0.0), 1.0) * _SCORE_WEIGHTS["sharpe"]
    if dd is not None:
        score -= abs(dd) * _SCORE_WEIGHTS["max_drawdown"]
    return score


def _stars(score: float | None) -> str:
    if score is None:
        return "---"
    if score >= 0.6:
        return "★★★"
    if score >= 0.35:
        return "★★☆"
    return "★☆☆"


class SettingsAnalysisTab(QWidget):
    """設定分析タブ."""

    apply_profile_requested = Signal(str, int)   # (profile_id, snapshot_id)
    clone_and_edit_requested = Signal(str, int)  # (profile_id, snapshot_id)

    def __init__(self, settings: Settings, parent=None):
        super().__init__(parent)
        self.settings = settings
        self._perf_data: list[dict] = []
        self._profiles_cache: list[dict] = []
        self._init_ui()

        self._timer = QTimer(self)
        self._timer.timeout.connect(self.refresh)
        self._timer.start(30000)
        self.refresh()

    # ------------------------------------------------------------------ UI --

    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)

        header = QHBoxLayout()
        title = QLabel("設定分析")
        title.setStyleSheet("font-size: 15px; font-weight: bold;")
        header.addWidget(title)
        header.addStretch()
        self.refresh_btn = QPushButton("更新")
        self.refresh_btn.clicked.connect(self.refresh)
        header.addWidget(self.refresh_btn)
        layout.addLayout(header)

        self.detail_tabs = QTabWidget()
        self.detail_tabs.addTab(self._build_ranking_tab(), "設定ランキング")
        self.detail_tabs.addTab(self._build_diff_tab(), "設定差分")
        self.detail_tabs.addTab(self._build_chart_tab(), "日次損益グラフ")
        self.detail_tabs.addTab(self._build_symbol_tab(), "通貨別比較")
        layout.addWidget(self.detail_tabs)

    def _build_ranking_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)

        ctrl = QHBoxLayout()
        ctrl.addWidget(QLabel("実行種別:"))
        self.rank_type_combo = QComboBox()
        self.rank_type_combo.addItems(["live", "backtest", "wfo", "retrain"])
        ctrl.addWidget(self.rank_type_combo)
        ctrl.addWidget(QLabel("最小取引数:"))
        self.rank_min_trades_spin = QSpinBox()
        self.rank_min_trades_spin.setRange(1, 1000)
        self.rank_min_trades_spin.setValue(5)
        ctrl.addWidget(self.rank_min_trades_spin)
        rank_refresh_btn = QPushButton("更新")
        rank_refresh_btn.clicked.connect(self._refresh_ranking)
        ctrl.addWidget(rank_refresh_btn)
        ctrl.addStretch()
        layout.addLayout(ctrl)

        self.ranking_table = QTableWidget()
        self.ranking_table.setColumnCount(9)
        self.ranking_table.setHorizontalHeaderLabels(
            ["スコア", "プロファイル", "取引数", "勝率", "PF", "Sharpe", "最大DD", "総損益", "期間"]
        )
        self.ranking_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.ranking_table.setAlternatingRowColors(True)
        self.ranking_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.ranking_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.ranking_table.verticalHeader().setVisible(False)
        layout.addWidget(self.ranking_table)

        btn_row = QHBoxLayout()
        self.rank_apply_btn = QPushButton("選択中を適用")
        self.rank_apply_btn.clicked.connect(self._on_rank_apply)
        btn_row.addWidget(self.rank_apply_btn)
        self.rank_clone_btn = QPushButton("選択中を複製して編集")
        self.rank_clone_btn.clicked.connect(self._on_rank_clone)
        btn_row.addWidget(self.rank_clone_btn)
        btn_row.addStretch()
        layout.addLayout(btn_row)
        return page

    def _build_diff_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)

        ctrl = QHBoxLayout()
        ctrl.addWidget(QLabel("比較:"))
        self.diff_left_combo = QComboBox()
        ctrl.addWidget(self.diff_left_combo)
        ctrl.addWidget(QLabel("vs"))
        self.diff_right_combo = QComboBox()
        ctrl.addWidget(self.diff_right_combo)
        diff_btn = QPushButton("差分を表示")
        diff_btn.clicked.connect(self._refresh_diff)
        ctrl.addWidget(diff_btn)
        ctrl.addStretch()
        layout.addLayout(ctrl)

        self.diff_table = QTableWidget()
        self.diff_table.setColumnCount(3)
        self.diff_table.setHorizontalHeaderLabels(["パラメータ", "左(ベース)", "右(比較)"])
        self.diff_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.diff_table.setAlternatingRowColors(True)
        self.diff_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.diff_table.verticalHeader().setVisible(False)
        layout.addWidget(self.diff_table)
        return page

    def _build_chart_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)

        ctrl = QHBoxLayout()
        ctrl.addWidget(QLabel("プロファイル:"))
        self.chart_profile_combo = QComboBox()
        ctrl.addWidget(self.chart_profile_combo)
        chart_btn = QPushButton("グラフ更新")
        chart_btn.clicked.connect(self._refresh_chart)
        ctrl.addWidget(chart_btn)
        ctrl.addStretch()
        layout.addLayout(ctrl)

        self.chart_label = QLabel("(プロファイルを選択して「グラフ更新」を押してください)")
        self.chart_label.setStyleSheet("color: gray; font-size: 13px;")
        layout.addWidget(self.chart_label)

        # matplotlib埋め込みウィジェット
        try:
            from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
            import matplotlib.pyplot as plt
            self._fig, self._ax = plt.subplots(figsize=(8, 4))
            self._canvas = FigureCanvasQTAgg(self._fig)
            layout.addWidget(self._canvas)
            self._has_mpl = True
        except Exception:
            self._has_mpl = False
            layout.addWidget(QLabel("matplotlib未インストール — グラフ非表示"))

        return page

    def _build_symbol_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)

        ctrl = QHBoxLayout()
        ctrl.addWidget(QLabel("プロファイルA:"))
        self.sym_left_combo = QComboBox()
        ctrl.addWidget(self.sym_left_combo)
        ctrl.addWidget(QLabel("プロファイルB:"))
        self.sym_right_combo = QComboBox()
        ctrl.addWidget(self.sym_right_combo)
        sym_btn = QPushButton("比較")
        sym_btn.clicked.connect(self._refresh_symbol_compare)
        ctrl.addWidget(sym_btn)
        ctrl.addStretch()
        layout.addLayout(ctrl)

        self.sym_table = QTableWidget()
        self.sym_table.setColumnCount(7)
        self.sym_table.setHorizontalHeaderLabels(
            ["通貨ペア", "A 取引数", "A 勝率", "A 損益", "B 取引数", "B 勝率", "B 損益"]
        )
        self.sym_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.sym_table.setAlternatingRowColors(True)
        self.sym_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.sym_table.verticalHeader().setVisible(False)
        layout.addWidget(self.sym_table)
        return page

    # --------------------------------------------------------------- data --

    def _get_db_path(self):
        from fxbot.config import _PROJECT_ROOT
        return _PROJECT_ROOT / self.settings.trade_logging.db_path

    def refresh(self) -> None:
        if not self.settings.trade_logging.enabled:
            return
        try:
            from fxbot.profile_manager import ProfileManager
            pm = ProfileManager(self._get_db_path())
            self._profiles_cache = pm.load_profiles(include_archived=False)
            run_type = self.rank_type_combo.currentText() if hasattr(self, "rank_type_combo") else "live"
            self._perf_data = pm.get_profile_performance(run_type)
            pm.close()
        except Exception as e:
            log.warning(f"設定分析データ取得失敗: {e}")
            return

        self._refresh_ranking()
        self._update_profile_combos()

    def _update_profile_combos(self) -> None:
        names = [p.get("name", "") for p in self._profiles_cache]
        for combo in (
            self.diff_left_combo, self.diff_right_combo,
            self.chart_profile_combo,
            self.sym_left_combo, self.sym_right_combo,
        ):
            current = combo.currentText()
            combo.clear()
            combo.addItems(names)
            idx = combo.findText(current)
            if idx >= 0:
                combo.setCurrentIndex(idx)

    def _refresh_ranking(self) -> None:
        if not self.settings.trade_logging.enabled:
            return
        try:
            run_type = self.rank_type_combo.currentText()
            from fxbot.profile_manager import ProfileManager
            pm = ProfileManager(self._get_db_path())
            self._perf_data = pm.get_profile_performance(run_type)
            pm.close()
        except Exception as e:
            log.warning(f"ランキング更新失敗: {e}")
            return

        min_trades = self.rank_min_trades_spin.value()
        rows = self._perf_data
        self.ranking_table.setRowCount(len(rows))

        for i, row in enumerate(rows):
            tc = row.get("trades_count") or 0
            is_ref = tc < min_trades
            score = _calc_score(row) if not is_ref else None

            items = [
                _stars(score) if not is_ref else "(参考)",
                row.get("profile_name") or row.get("profile_id") or "---",
                str(tc),
                f"{(row.get('win_rate') or 0):.1%}" if row.get("win_rate") is not None else "---",
                f"{(row.get('profit_factor') or 0):.2f}" if row.get("profit_factor") is not None else "---",
                f"{(row.get('sharpe') or 0):.2f}" if row.get("sharpe") is not None else "---",
                f"{(row.get('max_drawdown') or 0):.1%}" if row.get("max_drawdown") is not None else "---",
                f"{(row.get('net_profit') or 0):+,.0f}" if row.get("net_profit") is not None else "---",
                f"{str(row.get('period_from') or '')[:10]} ~ {str(row.get('period_to') or '')[:10]}",
            ]
            for j, text in enumerate(items):
                item = QTableWidgetItem(text)
                if is_ref:
                    item.setForeground(QColor("#888888"))
                elif j == 0 and score is not None and score >= 0.6:
                    item.setForeground(QColor("#4CAF50"))
                self.ranking_table.setItem(i, j, item)

    def _on_rank_apply(self) -> None:
        idx = self.ranking_table.currentRow()
        if idx < 0 or idx >= len(self._perf_data):
            return
        row = self._perf_data[idx]
        pid = row.get("profile_id")
        sid = row.get("snapshot_id")
        if pid and sid:
            self.apply_profile_requested.emit(pid, sid)

    def _on_rank_clone(self) -> None:
        idx = self.ranking_table.currentRow()
        if idx < 0 or idx >= len(self._perf_data):
            return
        row = self._perf_data[idx]
        pid = row.get("profile_id")
        sid = row.get("snapshot_id")
        if pid and sid:
            self.clone_and_edit_requested.emit(pid, sid)

    def _refresh_diff(self) -> None:
        left_name = self.diff_left_combo.currentText()
        right_name = self.diff_right_combo.currentText()
        if not left_name or not right_name or left_name == right_name:
            return

        def _find(name: str) -> dict | None:
            return next((p for p in self._profiles_cache if p.get("name") == name), None)

        pl = _find(left_name)
        pr = _find(right_name)
        if pl is None or pr is None:
            return

        try:
            left_dict = json.loads(pl.get("settings_json") or "{}")
            right_dict = json.loads(pr.get("settings_json") or "{}")
        except Exception:
            return

        diffs: list[tuple[str, str, str]] = []
        for section in ("trading", "risk", "market_filter", "model", "backtest"):
            ls = left_dict.get(section, {})
            rs = right_dict.get(section, {})
            all_keys = sorted(set(ls) | set(rs))
            for k in all_keys:
                lv = ls.get(k)
                rv = rs.get(k)
                if lv != rv:
                    diffs.append((f"{section}.{k}", str(lv), str(rv)))

        self.diff_table.setRowCount(len(diffs))
        for i, (param, lv, rv) in enumerate(diffs):
            self.diff_table.setItem(i, 0, QTableWidgetItem(param))
            li = QTableWidgetItem(lv)
            ri = QTableWidgetItem(rv)

            # 数値比較で色付け
            try:
                lf, rf = float(lv), float(rv)
                if rf > lf:
                    ri.setForeground(QColor("#2196F3"))   # 増加=青
                else:
                    ri.setForeground(QColor("#FF9800"))   # 減少=橙
            except (ValueError, TypeError):
                bold = QFont()
                bold.setBold(True)
                ri.setFont(bold)

            self.diff_table.setItem(i, 1, li)
            self.diff_table.setItem(i, 2, ri)

    def _refresh_chart(self) -> None:
        if not self._has_mpl:
            return
        profile_name = self.chart_profile_combo.currentText()
        p = next((x for x in self._profiles_cache if x.get("name") == profile_name), None)
        if p is None:
            return

        pid = p.get("profile_id")
        try:
            from fxbot.config import _PROJECT_ROOT
            import sqlite3
            db_path = self._get_db_path()
            conn = sqlite3.connect(str(db_path))
            rows = conn.execute(
                """
                SELECT date(t.exit_time) AS day, SUM(t.pnl) AS daily_pnl
                FROM trades t
                JOIN run_sessions rs ON rs.run_id = t.run_id
                WHERE rs.profile_id = ? AND t.pnl IS NOT NULL AND t.exit_time IS NOT NULL
                GROUP BY day
                ORDER BY day
                """,
                (pid,),
            ).fetchall()
            conn.close()
        except Exception as e:
            log.warning(f"グラフデータ取得失敗: {e}")
            return

        if not rows:
            self.chart_label.setText("取引データなし")
            return

        self.chart_label.setText("")
        days = [r[0] for r in rows]
        pnls = [r[1] for r in rows]
        cumulative = []
        total = 0.0
        for p in pnls:
            total += p
            cumulative.append(total)

        self._ax.clear()
        self._ax.plot(days, cumulative, marker="o", markersize=3)
        self._ax.axhline(0, color="gray", linewidth=0.5)
        self._ax.set_title(f"{profile_name} — 累積損益")
        self._ax.set_xlabel("日付")
        self._ax.set_ylabel("累積損益")
        self._fig.autofmt_xdate()
        self._canvas.draw()

    def _refresh_symbol_compare(self) -> None:
        left_name = self.sym_left_combo.currentText()
        right_name = self.sym_right_combo.currentText()

        def _find(name: str) -> str | None:
            p = next((x for x in self._profiles_cache if x.get("name") == name), None)
            return p.get("profile_id") if p else None

        pid_a = _find(left_name)
        pid_b = _find(right_name)
        if not pid_a or not pid_b:
            return

        try:
            import sqlite3
            db_path = self._get_db_path()
            conn = sqlite3.connect(str(db_path))

            def _fetch(pid: str) -> dict[str, dict]:
                rows = conn.execute(
                    """
                    SELECT t.symbol,
                           COUNT(*) AS cnt,
                           AVG(CASE WHEN t.pnl > 0 THEN 1.0 ELSE 0.0 END) AS wr,
                           SUM(t.pnl) AS np
                    FROM trades t
                    JOIN run_sessions rs ON rs.run_id = t.run_id
                    WHERE rs.profile_id = ? AND t.pnl IS NOT NULL
                    GROUP BY t.symbol
                    """,
                    (pid,),
                ).fetchall()
                return {r[0]: {"cnt": r[1], "wr": r[2], "np": r[3]} for r in rows}

            data_a = _fetch(pid_a)
            data_b = _fetch(pid_b)
            conn.close()
        except Exception as e:
            log.warning(f"通貨別比較失敗: {e}")
            return

        symbols = sorted(set(data_a) | set(data_b))
        self.sym_table.setRowCount(len(symbols))
        for i, sym in enumerate(symbols):
            a = data_a.get(sym, {})
            b = data_b.get(sym, {})
            self.sym_table.setItem(i, 0, QTableWidgetItem(sym))
            self.sym_table.setItem(i, 1, QTableWidgetItem(str(a.get("cnt", 0))))
            wr_a = a.get("wr")
            self.sym_table.setItem(i, 2, QTableWidgetItem(f"{wr_a:.1%}" if wr_a is not None else "---"))
            np_a = a.get("np")
            self.sym_table.setItem(i, 3, QTableWidgetItem(f"{np_a:+,.0f}" if np_a is not None else "---"))
            self.sym_table.setItem(i, 4, QTableWidgetItem(str(b.get("cnt", 0))))
            wr_b = b.get("wr")
            self.sym_table.setItem(i, 5, QTableWidgetItem(f"{wr_b:.1%}" if wr_b is not None else "---"))
            np_b = b.get("np")
            self.sym_table.setItem(i, 6, QTableWidgetItem(f"{np_b:+,.0f}" if np_b is not None else "---"))
