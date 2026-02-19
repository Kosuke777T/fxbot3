"""モデル保存・読込・バージョン管理."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import lightgbm as lgb

from fxbot.config import Settings
from fxbot.logger import get_logger

log = get_logger(__name__)


def _model_dir(symbol: str, timeframe: str, settings: Settings, timestamp: str | None = None) -> Path:
    """モデル保存ディレクトリを生成."""
    if timestamp is None:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    base = settings.resolve_path(settings.model.model_dir)
    return base / f"{symbol}_{timeframe}_{timestamp}"


def save_model(
    model: lgb.Booster,
    feature_names: list[str],
    metrics: dict,
    symbol: str,
    timeframe: str,
    settings: Settings,
) -> Path:
    """モデル + メタデータを保存."""
    model_dir = _model_dir(symbol, timeframe, settings)
    model_dir.mkdir(parents=True, exist_ok=True)

    # モデル本体
    model_path = model_dir / "model.txt"
    model.save_model(str(model_path))

    # メタデータ
    meta = {
        "symbol": symbol,
        "timeframe": timeframe,
        "created_at": datetime.now().isoformat(),
        "feature_names": feature_names,
        "metrics": metrics,
        "num_features": len(feature_names),
        "best_iteration": model.best_iteration,
    }
    meta_path = model_dir / "metadata.json"
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2, ensure_ascii=False)

    log.info(f"モデル保存: {model_dir}")
    return model_dir


def load_model(model_dir: Path | str) -> tuple[lgb.Booster, dict]:
    """モデルとメタデータを読み込む.

    Returns:
        (model, metadata) のタプル
    """
    model_dir = Path(model_dir)
    model_path = model_dir / "model.txt"
    meta_path = model_dir / "metadata.json"

    model = lgb.Booster(model_file=str(model_path))

    with open(meta_path, "r", encoding="utf-8") as f:
        metadata = json.load(f)

    log.info(f"モデル読込: {model_dir} (特徴量: {metadata['num_features']})")
    return model, metadata


def find_latest_model(symbol: str, timeframe: str, settings: Settings) -> Path | None:
    """最新のモデルディレクトリを検索."""
    base = settings.resolve_path(settings.model.model_dir)
    pattern = f"{symbol}_{timeframe}_*"
    dirs = sorted(base.glob(pattern), reverse=True)
    if dirs:
        return dirs[0]
    return None


def list_models(settings: Settings) -> list[dict]:
    """保存済みモデルの一覧を返す."""
    base = settings.resolve_path(settings.model.model_dir)
    if not base.exists():
        return []

    models = []
    for meta_path in sorted(base.glob("*/metadata.json"), reverse=True):
        with open(meta_path, "r", encoding="utf-8") as f:
            meta = json.load(f)
        meta["path"] = str(meta_path.parent)
        models.append(meta)
    return models
