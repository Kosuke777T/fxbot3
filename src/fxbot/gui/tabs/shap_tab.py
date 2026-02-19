"""SHAPタブ — 特徴量重要度可視化."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QSpinBox, QPushButton, QTableWidget,
    QTableWidgetItem, QHeaderView, QSplitter,
)
from PySide6.QtCore import Qt

from fxbot.config import Settings
from fxbot.gui.widgets.chart_widget import ChartWidget
from fxbot.logger import get_logger

log = get_logger(__name__)


class ShapTab(QWidget):
    """SHAP特徴量重要度タブ."""

    def __init__(self, settings: Settings, parent=None):
        super().__init__(parent)
        self.settings = settings
        self.importance_df = None
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)

        # コントロール
        ctrl_layout = QHBoxLayout()
        ctrl_layout.addWidget(QLabel("表示数:"))

        self.top_n_spin = QSpinBox()
        self.top_n_spin.setRange(5, 100)
        self.top_n_spin.setValue(20)
        self.top_n_spin.valueChanged.connect(self._update_chart)
        ctrl_layout.addWidget(self.top_n_spin)

        ctrl_layout.addStretch()
        layout.addLayout(ctrl_layout)

        # チャート + テーブル
        splitter = QSplitter(Qt.Orientation.Horizontal)

        self.chart = ChartWidget(figsize=(8, 6))
        splitter.addWidget(self.chart)

        self.table = QTableWidget()
        self.table.setColumnCount(3)
        self.table.setHorizontalHeaderLabels(["特徴量", "重要度", "累積%"])
        self.table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch
        )
        splitter.addWidget(self.table)

        layout.addWidget(splitter)

    def set_importance(self, importance_df):
        """SHAP重要度データを設定."""
        self.importance_df = importance_df
        self._update_chart()
        self._update_table()

    def _update_chart(self):
        if self.importance_df is not None:
            self.chart.plot_shap_importance(self.importance_df, self.top_n_spin.value())

    def _update_table(self):
        if self.importance_df is None:
            return

        df = self.importance_df
        self.table.setRowCount(len(df))
        for i, (_, row) in enumerate(df.iterrows()):
            self.table.setItem(i, 0, QTableWidgetItem(row["feature"]))
            self.table.setItem(i, 1, QTableWidgetItem(f"{row['importance']:.6f}"))
            self.table.setItem(i, 2, QTableWidgetItem(f"{row['cumulative_pct']*100:.1f}%"))
