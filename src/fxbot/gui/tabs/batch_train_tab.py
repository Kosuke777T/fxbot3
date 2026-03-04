"""一括学習タブ — active_symbols を順番に自動学習."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from fxbot.config import Settings
from fxbot.logger import get_logger

log = get_logger(__name__)

_COLOR_WAITING = "#9E9E9E"
_COLOR_ACTIVE = "#FF9800"
_COLOR_DONE = "#4CAF50"
_COLOR_ERROR = "#F44336"


class BatchTrainTab(QWidget):
    """一括学習タブ."""

    def __init__(self, settings: Settings, parent=None):
        super().__init__(parent)
        self.settings = settings
        self._workers: dict[str, object] = {}
        self._queue: list[str] = []
        self._total: int = 0
        self._completed: int = 0
        self._batch_id: int = 0
        # (status_label, progress_label) per symbol
        self._status_labels: dict[str, tuple[QLabel, QLabel]] = {}
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)

        # --- ペア一覧グループ ---
        self._pairs_group = QGroupBox("選択中ペア")
        self._pairs_layout = QVBoxLayout(self._pairs_group)
        self._pairs_layout.addWidget(QLabel("（通貨ペア未選択）"))
        layout.addWidget(self._pairs_group)

        # --- 全体進捗バー ---
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        layout.addWidget(self.progress_bar)

        # --- 開始ボタン ---
        self._start_btn = QPushButton("一括学習開始")
        self._start_btn.setEnabled(False)
        self._start_btn.setStyleSheet(
            "QPushButton { background-color: #1976D2; color: white; "
            "padding: 8px 20px; font-size: 14px; font-weight: bold; }"
            "QPushButton:disabled { background-color: #9E9E9E; }"
        )
        self._start_btn.clicked.connect(self._start_batch)
        layout.addWidget(self._start_btn)
        layout.addStretch()

    def refresh_symbols(self, symbols: list[str]) -> None:
        """active_symbols 変更時に表示を更新."""
        # 既存ウィジェットとレイアウトを削除
        while self._pairs_layout.count():
            item = self._pairs_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
            elif item.layout():
                self._clear_layout(item.layout())

        self._status_labels.clear()

        if not symbols:
            self._pairs_layout.addWidget(QLabel("（通貨ペア未選択）"))
            self._start_btn.setEnabled(False)
            return

        # ヘッダー行
        hdr = QHBoxLayout()
        for text, width in [("ペア", 120), ("ステータス", 200), ("進捗", 300)]:
            lbl = QLabel(text)
            lbl.setFixedWidth(width)
            lbl.setStyleSheet("font-weight: bold; color: gray; font-size: 11px;")
            hdr.addWidget(lbl)
        hdr.addStretch()
        self._pairs_layout.addLayout(hdr)

        for sym in symbols:
            row = QHBoxLayout()

            sym_lbl = QLabel(sym)
            sym_lbl.setFixedWidth(120)
            sym_lbl.setStyleSheet("font-weight: bold;")
            row.addWidget(sym_lbl)

            status_lbl = QLabel("● 待機中")
            status_lbl.setFixedWidth(200)
            status_lbl.setStyleSheet(f"color: {_COLOR_WAITING};")
            row.addWidget(status_lbl)

            progress_lbl = QLabel("")
            progress_lbl.setFixedWidth(300)
            row.addWidget(progress_lbl)

            row.addStretch()
            self._pairs_layout.addLayout(row)
            self._status_labels[sym] = (status_lbl, progress_lbl)

        self._start_btn.setEnabled(True)

    def _clear_layout(self, layout) -> None:
        while layout.count():
            item = layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

    def _set_status(
        self,
        sym: str,
        status_text: str,
        color: str = _COLOR_ACTIVE,
        progress_text: str = "",
    ) -> None:
        labels = self._status_labels.get(sym)
        if labels:
            status_lbl, progress_lbl = labels
            status_lbl.setText(f"● {status_text}")
            status_lbl.setStyleSheet(f"color: {color};")
            if progress_text:
                progress_lbl.setText(progress_text)

    def _start_batch(self):
        symbols = list(self.settings.trading.active_symbols)
        if not symbols:
            return

        self._batch_id += 1
        self._queue = symbols[:]
        self._total = len(self._queue)
        self._completed = 0
        self.progress_bar.setValue(0)
        self._start_btn.setEnabled(False)

        # 全ペアを待機状態にリセット
        for sym in self._status_labels:
            status_lbl, progress_lbl = self._status_labels[sym]
            status_lbl.setText("● 待機中")
            status_lbl.setStyleSheet(f"color: {_COLOR_WAITING};")
            progress_lbl.setText("")

        self._train_next()

    def _train_next(self):
        if not self._queue:
            self._start_btn.setEnabled(True)
            log.info("一括学習完了")
            return

        sym = self._queue.pop(0)
        batch_id = self._batch_id
        self._set_status(sym, "データ取得中...", _COLOR_ACTIVE)

        from fxbot.gui.workers import DataFetchWorker

        worker = DataFetchWorker(sym, self.settings)

        # processed フラグでシグナル多重発火を防ぐ
        fetched = [False]

        def on_fetched(data, s=sym, bid=batch_id):
            if fetched[0] or bid != self._batch_id:
                return
            fetched[0] = True
            self._on_fetched(s, data, bid)

        def on_fetch_error(e, s=sym, bid=batch_id):
            if fetched[0] or bid != self._batch_id:
                return
            fetched[0] = True
            self._on_error(s, e, bid)

        worker.signals.finished.connect(on_fetched)
        worker.signals.error.connect(on_fetch_error)
        worker.start()
        self._workers[sym] = worker

    def _on_fetched(self, sym: str, data: dict, batch_id: int) -> None:
        self._set_status(sym, "学習中...", _COLOR_ACTIVE)

        from fxbot.gui.workers import TrainWorker

        worker = TrainWorker(data, sym, self.settings)

        done = [False]

        def on_progress(msg, s=sym, bid=batch_id):
            if bid != self._batch_id:
                return
            self._set_status(s, "学習中", _COLOR_ACTIVE, msg)

        def on_done(result, s=sym, bid=batch_id):
            if done[0] or bid != self._batch_id:
                return
            done[0] = True
            self._on_done(s, bid)

        def on_train_error(e, s=sym, bid=batch_id):
            if done[0] or bid != self._batch_id:
                return
            done[0] = True
            self._on_error(s, e, bid)

        worker.signals.progress.connect(on_progress)
        worker.signals.finished.connect(on_done)
        worker.signals.error.connect(on_train_error)
        worker.start()
        self._workers[sym] = worker

    def _on_done(self, sym: str, batch_id: int) -> None:
        self._set_status(sym, "✓ 完了", _COLOR_DONE)
        self._completed += 1
        self.progress_bar.setValue(int(self._completed / self._total * 100))
        log.info(f"一括学習完了: {sym}")
        self._train_next()

    def _on_error(self, sym: str, error_msg: str, batch_id: int) -> None:
        short_msg = error_msg.split("\n")[0][:80]
        self._set_status(sym, "エラー", _COLOR_ERROR, short_msg)
        log.error(f"一括学習エラー ({sym}): {error_msg}")
        self._completed += 1
        self.progress_bar.setValue(int(self._completed / self._total * 100))
        self._train_next()  # エラーでも次のペアへ
