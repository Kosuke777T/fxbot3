"""設定管理 — YAML読込 + Settings dataclass."""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

_PROJECT_ROOT = Path(__file__).resolve().parents[2]  # D:/fxbot3
DEFAULT_CONFIG_PATH = _PROJECT_ROOT / "config" / "default_settings.yaml"


@dataclass
class AccountConfig:
    server: str = ""
    login: int = 0
    password: str = ""
    type: str = "demo"  # "demo" | "real"


@dataclass
class DataConfig:
    base_timeframe: str = "M5"
    higher_timeframes: list[str] = field(default_factory=lambda: ["M15", "H1", "H4", "D1"])
    bars_count: int = 10000
    cache_dir: str = "data/ohlcv"


@dataclass
class TradingConfig:
    max_positions: int = 5
    prediction_horizon: int = 6
    min_prediction_threshold: float = 0.0005
    max_lot: float = 0.1
    min_lot: float = 0.01
    min_confidence: float = 0.0  # 分類モデルの最低信頼度（0.0=無効）


@dataclass
class RiskConfig:
    max_risk_per_trade: float = 0.02
    atr_sl_multiplier: float = 2.0
    atr_tp_multiplier: float = 3.0
    trailing_atr_multiplier: float = 1.5
    trailing_activation_atr: float = 1.0
    trailing_update_interval: int = 60  # バー待機中のトレーリング更新間隔（秒）、0で無効


@dataclass
class ModelConfig:
    lgbm_params: dict[str, Any] = field(default_factory=lambda: {
        "objective": "regression",
        "metric": "mae",
        "boosting_type": "gbdt",
        "num_leaves": 63,
        "learning_rate": 0.05,
        "feature_fraction": 0.8,
        "bagging_fraction": 0.8,
        "bagging_freq": 5,
        "verbose": -1,
    })
    num_boost_round: int = 1000
    early_stopping_rounds: int = 50
    shap_top_pct: float = 0.5
    model_dir: str = "data/models"
    mode: str = "regression"  # "regression" | "classification"


@dataclass
class BacktestConfig:
    train_window_days: int = 180
    test_window_days: int = 30
    initial_balance: float = 1_000_000
    spread_pips: float = 1.5


@dataclass
class TradeLoggingConfig:
    enabled: bool = False
    db_path: str = "data/trades.db"


@dataclass
class MarketFilterConfig:
    """市場環境フィルター設定."""
    enabled: bool = False
    # ADXフィルター
    use_adx_filter: bool = True
    min_adx: float = 20.0          # この値未満のADX（弱トレンド）ではHOLD
    # スプレッドフィルター
    use_spread_filter: bool = True
    max_spread_pips: float = 3.0   # スプレッドがこれを超えたらHOLD
    # ボラティリティフィルター
    use_volatility_filter: bool = False
    min_atr_pct: float = 0.02      # ATR%がこれ未満は低ボラでHOLD
    max_atr_pct: float = 0.5       # ATR%がこれを超えたら過大ボラでHOLD
    # セッションフィルター
    session_only: bool = False     # Trueでロンドン・NYセッションのみ取引


@dataclass
class RetrainingConfig:
    enabled: bool = False
    interval_hours: int = 168
    # ModelMonitorトリガー
    monitor_window: int = 20       # 直近N件で監視
    min_win_rate: float = 0.40     # 勝率がこれを下回ったら再学習
    min_sharpe: float = 0.0        # シャープレシオがこれを下回ったら再学習
    # 週末スケジューラー
    weekend_only: bool = True          # 土日のみ実行
    run_wfo_before_train: bool = True  # 学習前にWFOを実行
    wfo_min_win_rate: float = 0.45     # WFO合格基準（勝率）
    wfo_min_sharpe: float = 0.3        # WFO合格基準（シャープ）


@dataclass
class LoggingConfig:
    level: str = "INFO"
    file: str = "data/fxbot.log"
    max_bytes: int = 10_485_760
    backup_count: int = 3


@dataclass
class SlackNotifierConfig:
    enabled: bool = False
    webhook_url: str = ""          # .env の SLACK_WEBHOOK_URL で上書き
    notify_entry: bool = True
    notify_exit: bool = True
    notify_error: bool = True
    notify_model_degraded: bool = True
    notify_retraining_done: bool = True
    notify_backtest_done: bool = False


@dataclass
class Settings:
    active_account: str = "demo"
    accounts: dict[str, AccountConfig] = field(default_factory=lambda: {
        "demo": AccountConfig(),
        "real": AccountConfig(type="real"),
    })
    data: DataConfig = field(default_factory=DataConfig)
    trading: TradingConfig = field(default_factory=TradingConfig)
    risk: RiskConfig = field(default_factory=RiskConfig)
    model: ModelConfig = field(default_factory=ModelConfig)
    backtest: BacktestConfig = field(default_factory=BacktestConfig)
    retraining: RetrainingConfig = field(default_factory=RetrainingConfig)
    logging: LoggingConfig = field(default_factory=LoggingConfig)
    trade_logging: TradeLoggingConfig = field(default_factory=TradeLoggingConfig)
    market_filter: MarketFilterConfig = field(default_factory=MarketFilterConfig)
    slack: SlackNotifierConfig = field(default_factory=SlackNotifierConfig)

    @property
    def current_account(self) -> AccountConfig:
        return self.accounts[self.active_account]

    def resolve_path(self, relative: str) -> Path:
        """プロジェクトルートからの相対パスを絶対パスに変換."""
        return _PROJECT_ROOT / relative


def _merge_dict(base: dict, override: dict) -> dict:
    """再帰的にdictをマージ."""
    result = copy.deepcopy(base)
    for k, v in override.items():
        if k in result and isinstance(result[k], dict) and isinstance(v, dict):
            result[k] = _merge_dict(result[k], v)
        else:
            result[k] = copy.deepcopy(v)
    return result


def _dict_to_dataclass(cls, data: dict):
    """dictからdataclassインスタンスを構築（未知のキーは無視）."""
    import dataclasses
    field_names = {f.name for f in dataclasses.fields(cls)}
    return cls(**{k: v for k, v in data.items() if k in field_names})


def _save_env(settings: Settings) -> None:
    """アカウント認証情報と Slack Webhook URL を .env ファイルに書き込む."""
    env_path = _PROJECT_ROOT / ".env"

    # 既存 .env を読み込み、MT5_ 行と SLACK_ 行を除去
    lines: list[str] = []
    if env_path.exists():
        with open(env_path, "r", encoding="utf-8") as f:
            lines = [line for line in f.readlines()
                     if not line.startswith("MT5_") and not line.startswith("SLACK_")]

    # MT5 アカウント情報
    for name, acc in settings.accounts.items():
        prefix = f"MT5_{name.upper()}_"
        lines += [
            f"{prefix}SERVER={acc.server}\n",
            f"{prefix}LOGIN={acc.login}\n",
            f"{prefix}PASSWORD={acc.password}\n",
        ]

    # Slack Webhook URL
    lines.append(f"SLACK_WEBHOOK_URL={settings.slack.webhook_url}\n")

    with open(env_path, "w", encoding="utf-8") as f:
        f.writelines(lines)


def save_settings(settings: Settings, path: Path | str | None = None) -> None:
    """SettingsをYAMLファイルに書き込む（認証情報は .env に保存）."""
    import dataclasses
    cfg_path = Path(path) if path else DEFAULT_CONFIG_PATH
    cfg_path.parent.mkdir(parents=True, exist_ok=True)
    data = dataclasses.asdict(settings)

    # YAML には認証情報を書かない
    for acc_data in data.get("accounts", {}).values():
        acc_data["server"] = ""
        acc_data["login"] = 0
        acc_data["password"] = ""

    # YAML には Webhook URL を書かない
    if "slack" in data:
        data["slack"]["webhook_url"] = ""

    with open(cfg_path, "w", encoding="utf-8") as f:
        yaml.dump(data, f, allow_unicode=True, default_flow_style=False, sort_keys=False)

    # 認証情報と Webhook URL は .env に保存
    _save_env(settings)


def load_settings(path: Path | str | None = None) -> Settings:
    """YAML設定ファイルを読み込みSettingsを返す（認証情報は .env でオーバーライド）."""
    import os
    from dotenv import load_dotenv

    cfg_path = Path(path) if path else DEFAULT_CONFIG_PATH
    if not cfg_path.exists():
        return Settings()

    with open(cfg_path, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}

    settings = Settings()
    settings.active_account = raw.get("active_account", settings.active_account)

    # accounts
    if "accounts" in raw:
        accounts = {}
        for name, acc_data in raw["accounts"].items():
            accounts[name] = _dict_to_dataclass(AccountConfig, acc_data)
        settings.accounts = accounts

    # sub-configs
    section_map = {
        "data": (DataConfig, "data"),
        "trading": (TradingConfig, "trading"),
        "risk": (RiskConfig, "risk"),
        "model": (ModelConfig, "model"),
        "backtest": (BacktestConfig, "backtest"),
        "retraining": (RetrainingConfig, "retraining"),
        "logging": (LoggingConfig, "logging"),
        "trade_logging": (TradeLoggingConfig, "trade_logging"),
        "market_filter": (MarketFilterConfig, "market_filter"),
        "slack": (SlackNotifierConfig, "slack"),
    }
    for yaml_key, (cls, attr_name) in section_map.items():
        if yaml_key in raw:
            setattr(settings, attr_name, _dict_to_dataclass(cls, raw[yaml_key]))

    # .env の認証情報でアカウント設定をオーバーライド
    load_dotenv(_PROJECT_ROOT / ".env", override=True)
    for name, acc in settings.accounts.items():
        prefix = f"MT5_{name.upper()}_"
        acc.server = os.environ.get(f"{prefix}SERVER", acc.server)
        login_str = os.environ.get(f"{prefix}LOGIN", "")
        if login_str.strip().isdigit():
            acc.login = int(login_str)
        acc.password = os.environ.get(f"{prefix}PASSWORD", acc.password)

    # Slack Webhook URL を .env からオーバーライド
    webhook = os.environ.get("SLACK_WEBHOOK_URL", "")
    if webhook:
        settings.slack.webhook_url = webhook

    return settings
