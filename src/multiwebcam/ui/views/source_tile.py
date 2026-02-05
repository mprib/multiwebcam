"""Single source tile widget for grid display."""

from PySide6.QtCore import Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QFrame, QLabel, QPushButton, QVBoxLayout

from multiwebcam.ui.views.aspect_ratio_label import AspectRatioLabel


class SourceTile(QFrame):
    """Displays a single video source with label and focus button.

    Signals:
        focus_requested: Emitted when user clicks focus button
    """

    focus_requested = Signal()  # User wants to focus this source

    def __init__(self, source_id: int, label: str, parent=None):
        super().__init__(parent)
        self._source_id = source_id

        # Frame display
        self._frame_label = AspectRatioLabel()
        self._frame_label.setMinimumSize(320, 240)

        # Source label
        self._name_label = QLabel(label)

        # Stats label
        self._stats_label = QLabel("-- fps")

        # Focus button
        self._focus_btn = QPushButton("Focus")
        self._focus_btn.clicked.connect(self.focus_requested.emit)

        # Layout
        layout = QVBoxLayout(self)
        layout.addWidget(self._frame_label)
        layout.addWidget(self._name_label)
        layout.addWidget(self._stats_label)
        layout.addWidget(self._focus_btn)

    @property
    def source_id(self) -> int:
        return self._source_id

    def display_frame(self, pixmap: QPixmap) -> None:
        """Update the displayed frame."""
        self._frame_label.display_pixmap(pixmap)

    def update_stats(self, fps: float, jitter_ms: float = 0.0) -> None:
        """Update stats display."""
        self._stats_label.setText(f"{fps:.1f} fps | {jitter_ms:.1f}ms jitter")

    def set_error(self, message: str) -> None:
        """Show error state (e.g., disconnected)."""
        self._frame_label.setText(message)
        self._stats_label.setText("--")
