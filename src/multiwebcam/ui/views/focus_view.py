"""Focus view for single source with detailed controls."""

from PySide6.QtCore import Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from multiwebcam.pipeline.report import CameraStats


class FocusView(QWidget):
    """Large preview of single source with stats.

    Signals:
        back_requested: User wants to return to grid view
    """

    back_requested = Signal()

    def __init__(self, source_id: int, label: str, parent=None):
        super().__init__(parent)
        self._source_id = source_id

        layout = QVBoxLayout(self)

        # Large frame display
        self._frame_label = QLabel()
        self._frame_label.setMinimumSize(640, 480)
        self._frame_label.setScaledContents(True)
        layout.addWidget(self._frame_label, stretch=1)

        # Info bar
        self._info_label = QLabel(f"{label} (source {source_id})")
        layout.addWidget(self._info_label)

        # Stats
        self._stats_label = QLabel("-- fps | -- jitter")
        layout.addWidget(self._stats_label)

        # Back button
        self._back_btn = QPushButton("Back to Grid")
        self._back_btn.clicked.connect(self.back_requested.emit)
        layout.addWidget(self._back_btn)

    @property
    def source_id(self) -> int:
        return self._source_id

    def display_frame(self, pixmap: QPixmap) -> None:
        """Update the displayed frame."""
        self._frame_label.setPixmap(pixmap)

    def update_stats(self, stats: CameraStats) -> None:
        """Update stats display."""
        self._stats_label.setText(f"{stats.measured_fps:.1f} fps | {stats.jitter_ms:.1f}ms jitter")
