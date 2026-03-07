"""戦略分析タブ向けのルールベース助言."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class StrategyAdvice:
    severity: str  # info | warn | good
    title: str
    message: str
    evidence: str
    action_tab: str | None = None  # "market_filter" | "settings" | None


def generate_strategy_advice(
    *,
    symbols: list[str],
    summary: dict,
    action_rows: list[dict],
    hold_rows: list[dict],
    filter_rows: list[dict],
    exit_rows: list[dict],
    direction_rows: list[dict],
    hour_rows: list[dict],
    bucket_rows: list[dict],
    model_rows: list[dict],
    symbol_rows: list[dict],
    prev_summary: dict | None = None,
) -> tuple[str, list[StrategyAdvice]]:
    """既存集計結果から戦略アドバイスを生成."""
    advices: list[StrategyAdvice] = []

    eval_count = int(summary.get("eval_count", 0) or 0)
    entered_count = int(summary.get("entered_count", 0) or 0)
    hold_count = int(summary.get("hold_count", 0) or 0)
    entry_rate = float(summary.get("entry_rate", 0.0) or 0.0)
    closed_count = sum(int(row.get("count", 0) or 0) for row in exit_rows)

    if eval_count == 0:
        return (
            "まだ分析イベントがありません。ライブ取引を実行して戦略判断ログを蓄積すると、ここに改善候補が表示されます。",
            [],
        )

    if eval_count < 30 or closed_count < 10:
        advices.append(StrategyAdvice(
            severity="info",
            title="サンプル数が少なめです",
            message="判定数または決済数が少ないため、今の傾向は参考値として扱うのが安全です。",
            evidence=f"総判定数 {eval_count}件 / 決済件数 {closed_count}件",
        ))

    if eval_count >= 20 and entry_rate < 0.10:
        top_hold = _top_row(hold_rows, "count")
        if top_hold:
            delta_str = ""
            if prev_summary is not None:
                prev_rate = float(prev_summary.get("entry_rate", 0.0) or 0.0)
                delta = entry_rate - prev_rate
                if abs(delta) > 0.001:
                    arrow = "↑" if delta > 0 else "↓"
                    delta_str = f"（前回比 {arrow} {delta:+.1%}）"
            advices.append(StrategyAdvice(
                severity="warn",
                title="HOLDが多くエントリー率が低いです",
                message="フィルターや閾値が厳しすぎて、チャンスを取り逃している可能性があります。",
                evidence=(
                    f"約定率 {entry_rate:.1%}{delta_str} / HOLD {hold_count}件 / "
                    f"最多HOLD理由 {top_hold.get('hold_reason', 'unknown')} ({int(top_hold.get('count', 0) or 0)}件)"
                ),
                action_tab="market_filter",
            ))

    filter_row = _top_block_filter(filter_rows)
    if filter_row and int(filter_row.get("enabled_count", 0) or 0) >= 10:
        pass_rate = filter_row.get("pass_rate")
        if pass_rate is not None and pass_rate < 0.40:
            advices.append(StrategyAdvice(
                severity="warn",
                title=f"{filter_row.get('display_name', 'フィルター')} のブロック率が高いです",
                message="このフィルターが主な見送り原因になっている可能性があります。設定値や適用条件の見直し候補です。",
                evidence=(
                    f"有効 {int(filter_row.get('enabled_count', 0) or 0)}回 / "
                    f"通過率 {pass_rate:.1%} / ブロック {int(filter_row.get('block_count', 0) or 0)}回"
                ),
                action_tab="settings",
            ))

    if len(direction_rows) >= 2:
        stronger, weaker = _compare_metric_rows(direction_rows, "avg_pnl")
        if stronger and weaker:
            stronger_avg = float(stronger.get("avg_pnl", 0.0) or 0.0)
            weaker_avg = float(weaker.get("avg_pnl", 0.0) or 0.0)
            weaker_count = int(weaker.get("count", 0) or 0)
            if weaker_count >= 3 and stronger_avg > 0 and weaker_avg < 0:
                advices.append(StrategyAdvice(
                    severity="warn",
                    title=f"{weaker.get('direction', '片方向')} の成績が弱いです",
                    message="片方向で平均損益が悪化しているため、その方向だけ閾値や条件を厳しくする余地があります。",
                    evidence=(
                        f"{stronger.get('direction')} 平均 {stronger_avg:+.0f} / "
                        f"{weaker.get('direction')} 平均 {weaker_avg:+.0f}"
                    ),
                ))

    sl_row = _find_row(exit_rows, "exit_reason", "sl")
    trailing_row = _find_row(exit_rows, "exit_reason", "trailing")
    tp_row = _find_row(exit_rows, "exit_reason", "tp")
    if sl_row and tp_row:
        sl_avg = float(sl_row.get("avg_pnl", 0.0) or 0.0)
        tp_avg = float(tp_row.get("avg_pnl", 0.0) or 0.0)
        sl_count = int(sl_row.get("count", 0) or 0)
        if sl_count >= 3 and tp_avg > 0 and sl_avg < 0:
            advices.append(StrategyAdvice(
                severity="warn",
                title="SL決済の重さが目立ちます",
                message="利確できる時の利益に対して、SL時の損失が大きい場合は損切り設計やロット管理の再確認候補です。",
                evidence=f"TP平均 {tp_avg:+.0f} / SL平均 {sl_avg:+.0f}",
            ))
    if trailing_row:
        trailing_avg = float(trailing_row.get("avg_pnl", 0.0) or 0.0)
        trailing_count = int(trailing_row.get("count", 0) or 0)
        if trailing_count >= 3 and trailing_avg < 0:
            advices.append(StrategyAdvice(
                severity="warn",
                title="トレーリング決済が逆効果の可能性があります",
                message="トレーリング決済の平均損益がマイナスなら、発動条件や追従幅が合っていない可能性があります。",
                evidence=f"trailing件数 {trailing_count}件 / 平均損益 {trailing_avg:+.0f}",
            ))

    hour_best, hour_worst = _compare_metric_rows(hour_rows, "avg_pnl")
    if hour_best and hour_worst:
        worst_count = int(hour_worst.get("count", 0) or 0)
        best_avg = float(hour_best.get("avg_pnl", 0.0) or 0.0)
        worst_avg = float(hour_worst.get("avg_pnl", 0.0) or 0.0)
        if worst_count >= 3 and best_avg > 0 and worst_avg < 0:
            advices.append(StrategyAdvice(
                severity="info",
                title="時間帯による差が見えます",
                message="弱い時間帯を避けるか、時間帯ごとに条件を変えると改善余地があります。",
                evidence=f"良い時間帯 {hour_best.get('hour_bucket')}時 平均 {best_avg:+.0f} / 悪い時間帯 {hour_worst.get('hour_bucket')}時 平均 {worst_avg:+.0f}",
            ))

    bucket_best, bucket_worst = _compare_metric_rows(bucket_rows, "avg_pnl")
    if bucket_best and bucket_worst:
        worst_count = int(bucket_worst.get("count", 0) or 0)
        best_avg = float(bucket_best.get("avg_pnl", 0.0) or 0.0)
        worst_avg = float(bucket_worst.get("avg_pnl", 0.0) or 0.0)
        if worst_count >= 3 and best_avg > 0 and worst_avg < 0:
            advices.append(StrategyAdvice(
                severity="info",
                title="予測値の弱い帯が成績を下げている可能性があります",
                message="低予測帯の成績が悪い場合、最小予測値閾値を少し引き上げる候補があります。",
                evidence=(
                    f"良い帯 {bucket_best.get('bucket')} 平均 {best_avg:+.0f} / "
                    f"弱い帯 {bucket_worst.get('bucket')} 平均 {worst_avg:+.0f}"
                ),
            ))

    if len(model_rows) >= 2:
        model_best, model_worst = _compare_metric_rows(model_rows, "avg_pnl")
        if model_best and model_worst:
            best_avg = float(model_best.get("avg_pnl", 0.0) or 0.0)
            worst_avg = float(model_worst.get("avg_pnl", 0.0) or 0.0)
            if int(model_worst.get("count", 0) or 0) >= 3 and best_avg > worst_avg:
                advices.append(StrategyAdvice(
                    severity="info",
                    title="モデルごとの差が見えます",
                    message="モデル別成績に差があるため、最近のモデル更新後に成績が改善しているかを重点確認すると有効です。",
                    evidence=(
                        f"良いモデル 平均 {best_avg:+.0f} / "
                        f"弱いモデル 平均 {worst_avg:+.0f}"
                    ),
                ))

    weak_symbol = _worst_symbol(symbol_rows)
    strong_symbol = _best_symbol(symbol_rows)
    if weak_symbol and strong_symbol:
        weak_avg = float(weak_symbol.get("avg_pnl", 0.0) or 0.0)
        strong_avg = float(strong_symbol.get("avg_pnl", 0.0) or 0.0)
        if int(weak_symbol.get("closed_trades", 0) or 0) >= 3 and strong_avg > weak_avg:
            advices.append(StrategyAdvice(
                severity="info",
                title="通貨ペアごとの差があります",
                message="弱い通貨ペアの条件を厳しくするか、強い通貨ペアを優先する運用が候補です。",
                evidence=(
                    f"良いペア {strong_symbol.get('symbol')} 平均 {strong_avg:+.0f} / "
                    f"弱いペア {weak_symbol.get('symbol')} 平均 {weak_avg:+.0f}"
                ),
            ))

    if not advices:
        advices.append(StrategyAdvice(
            severity="good",
            title="大きな偏りはまだ見えていません",
            message="現時点では特定の改善ポイントより、サンプルを増やしながら継続観察する段階です。",
            evidence=f"対象ペア: {' / '.join(symbols) if symbols else '全体'} / 総判定数 {eval_count}件",
        ))

    overall = _build_overall_comment(advices, eval_count, entered_count)
    return overall, advices


def _build_overall_comment(advices: list[StrategyAdvice], eval_count: int, entered_count: int) -> str:
    warn_count = sum(1 for item in advices if item.severity == "warn")
    good_count = sum(1 for item in advices if item.severity == "good")
    if warn_count >= 2:
        prefix = "改善候補が複数見えています。"
    elif warn_count == 1:
        prefix = "明確な見直し候補が1点あります。"
    elif good_count > 0:
        prefix = "大きな異常は見えていません。"
    else:
        prefix = "いくつか観察ポイントがあります。"
    return f"{prefix} 総判定数 {eval_count}件、約定数 {entered_count}件をもとに助言しています。"


def _find_row(rows: list[dict], key: str, value: str) -> dict | None:
    for row in rows:
        if str(row.get(key, "")).lower() == value.lower():
            return row
    return None


def _top_row(rows: list[dict], metric: str) -> dict | None:
    if not rows:
        return None
    return max(rows, key=lambda row: float(row.get(metric, 0) or 0))


def _top_block_filter(rows: list[dict]) -> dict | None:
    filtered = [row for row in rows if int(row.get("enabled_count", 0) or 0) > 0]
    if not filtered:
        return None
    return max(filtered, key=lambda row: float(row.get("block_count", 0) or 0))


def _compare_metric_rows(rows: list[dict], metric: str) -> tuple[dict | None, dict | None]:
    filtered = [row for row in rows if row.get(metric) is not None]
    if len(filtered) < 2:
        return None, None
    ordered = sorted(filtered, key=lambda row: float(row.get(metric, 0) or 0), reverse=True)
    return ordered[0], ordered[-1]


def _best_symbol(rows: list[dict]) -> dict | None:
    filtered = [row for row in rows if int(row.get("closed_trades", 0) or 0) > 0]
    if not filtered:
        return None
    return max(filtered, key=lambda row: float(row.get("avg_pnl", 0) or 0))


def _worst_symbol(rows: list[dict]) -> dict | None:
    filtered = [row for row in rows if int(row.get("closed_trades", 0) or 0) > 0]
    if not filtered:
        return None
    return min(filtered, key=lambda row: float(row.get("avg_pnl", 0) or 0))
