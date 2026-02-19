"""モデルタブ — 学習状況, 再学習ボタン."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGroupBox,
    QPushButton, QLabel, QComboBox, QTableWidget,
    QTableWidgetItem, QHeaderView, QProgressBar,
)

from fxbot.config import Settings
from fxbot.gui.workers import DataFetchWorker, TrainWorker
from fxbot.logger import get_logger

log = get_logger(__name__)


class ModelTab(QWidget):
    """モデルタブ."""

    # 学習完了時にSHAPタブに重要度を渡すためのコールバック
    on_train_complete = None  # callable(result)

    def __init__(self, settings: Settings, parent=None):
        super().__init__(parent)
        self.settings = settings
        self.multi_tf_data = None
        self.worker = None
        self.data_worker = None
        self._init_ui()
        self._refresh_models()

    def _init_ui(self):
        layout = QVBoxLayout(self)

        # === 学習コントロール ===
        train_group = QGroupBox("モデル学習")
        train_layout = QVBoxLayout()

        ctrl_layout = QHBoxLayout()
        ctrl_layout.addWidget(QLabel("シンボル:"))
        self.symbol_combo = QComboBox()
        ctrl_layout.addWidget(self.symbol_combo)

        self.fetch_btn = QPushButton("データ取得")
        self.fetch_btn.clicked.connect(self._fetch_data)
        ctrl_layout.addWidget(self.fetch_btn)

        self.train_btn = QPushButton("学習開始")
        self.train_btn.clicked.connect(self._start_training)
        self.train_btn.setStyleSheet("background-color: #4CAF50; color: white;")
        ctrl_layout.addWidget(self.train_btn)

        train_layout.addLayout(ctrl_layout)

        self.status_label = QLabel("待機中")
        train_layout.addWidget(self.status_label)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 0)  # indeterminate
        self.progress_bar.hide()
        train_layout.addWidget(self.progress_bar)

        train_group.setLayout(train_layout)
        layout.addWidget(train_group)

        # === 学習結果 ===
        result_group = QGroupBox("最新学習結果")
        result_layout = QVBoxLayout()
        self.metrics_label = QLabel("---")
        self.metrics_label.setWordWrap(True)
        result_layout.addWidget(self.metrics_label)
        result_group.setLayout(result_layout)
        layout.addWidget(result_group)

        # === 保存済みモデル一覧 ===
        models_group = QGroupBox("保存済みモデル")
        models_layout = QVBoxLayout()

        self.models_table = QTableWidget()
        self.models_table.setColumnCount(5)
        self.models_table.setHorizontalHeaderLabels([
            "シンボル", "時間足", "作成日時", "特徴量数", "方向精度",
        ])
        self.models_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch
        )
        models_layout.addWidget(self.models_table)

        refresh_btn = QPushButton("一覧更新")
        refresh_btn.clicked.connect(self._refresh_models)
        models_layout.addWidget(refresh_btn)

        models_group.setLayout(models_layout)
        layout.addWidget(models_group)

    def set_symbols(self, symbols: list[str]):
        self.symbol_combo.clear()
        self.symbol_combo.addItems(symbols)

    def _fetch_data(self):
        symbol = self.symbol_combo.currentText()
        if not symbol:
            return

        self.fetch_btn.setEnabled(False)
        self.status_label.setText(f"{symbol} データ取得中...")
        self.progress_bar.show()

        self.data_worker = DataFetchWorker(symbol, self.settings)
        self.data_worker.signals.finished.connect(self._on_data_fetched)
        self.data_worker.signals.error.connect(self._on_error)
        self.data_worker.start()

    def _on_data_fetched(self, data):
        self.multi_tf_data = data
        self.fetch_btn.setEnabled(True)
        self.progress_bar.hide()
        self.status_label.setText("データ取得完了。学習を開始できます。")

    def _start_training(self):
        symbol = self.symbol_combo.currentText()
        if not symbol:
            return
        if self.multi_tf_data is None:
            self.status_label.setText("先にデータを取得してください")
            return

        self.train_btn.setEnabled(False)
        self.progress_bar.show()

        self.worker = TrainWorker(self.multi_tf_data, symbol, self.settings)
        self.worker.signals.progress.connect(self._on_progress)
        self.worker.signals.finished.connect(self._on_train_finished)
        self.worker.signals.error.connect(self._on_error)
        self.worker.start()

    def _on_progress(self, msg: str):
        self.status_label.setText(msg)

    def _on_train_finished(self, result):
        self.train_btn.setEnabled(True)
        self.progress_bar.hide()

        if result is None:
            return

        metrics = result["metrics"]
        self.status_label.setText("学習完了")
        self.metrics_label.setText(
            f"MAE: {metrics['mae']:.6f}\n"
            f"方向精度: {metrics['direction_accuracy']:.4f}\n"
            f"IC: {metrics['information_coefficient']:.4f}\n"
            f"特徴量数: {metrics['num_features']}\n"
            f"保存先: {result['model_dir']}"
        )

        self._refresh_models()

        if self.on_train_complete:
            self.on_train_complete(result)

    def _on_error(self, msg: str):
        self.train_btn.setEnabled(True)
        self.fetch_btn.setEnabled(True)
        self.progress_bar.hide()
        self.status_label.setText("エラー")
        log.error(msg)

    def _refresh_models(self):
        try:
            from fxbot.model.registry import list_models
            models = list_models(self.settings)
            self.models_table.setRowCount(len(models))
            for i, meta in enumerate(models):
                self.models_table.setItem(i, 0, QTableWidgetItem(meta.get("symbol", "")))
                self.models_table.setItem(i, 1, QTableWidgetItem(meta.get("timeframe", "")))
                self.models_table.setItem(i, 2, QTableWidgetItem(meta.get("created_at", "")))
                self.models_table.setItem(i, 3, QTableWidgetItem(str(meta.get("num_features", 0))))
                metrics = meta.get("metrics", {})
                acc = metrics.get("direction_accuracy", 0)
                self.models_table.setItem(i, 4, QTableWidgetItem(f"{acc:.4f}"))
        except Exception:
            pass
