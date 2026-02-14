"""Single source tile widget for grid display."""

from PySide6.QtCore import Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout

from multiwebcam.ui.views.aspect_ratio_label import AspectRatioLabel

_QUEUE_DEPTH_WARNING = 30  # frames (~1s at 30fps)
_COLOR_WARNING = "#FFA000"
_STYLE_MUTED = "font-size: 10px; color: #888888;"


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

        # Source label + resolution on one line
        self._name_label = QLabel(label)
        self._resolution_label = QLabel("")
        self._resolution_label.setStyleSheet("color: #AAAAAA;")

        info_row = QHBoxLayout()
        info_row.addWidget(self._name_label)
        info_row.addStretch()
        info_row.addWidget(self._resolution_label)

        # Stats label
        self._stats_label = QLabel("-- fps")

        # Queue depth label (hidden when not recording)
        self._queue_label = QLabel("Unsaved frames: 0")
        self._queue_label.setVisible(False)
        self._queue_label.setStyleSheet(_STYLE_MUTED)
        self._queue_warning = False

        # Focus button
        self._focus_btn = QPushButton("Focus")
        self._focus_btn.clicked.connect(self.focus_requested.emit)

        # Layout
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(2)
        layout.addWidget(self._frame_label)
        layout.addLayout(info_row)
        layout.addWidget(self._stats_label)
        layout.addWidget(self._queue_label)
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

    def set_queue_visible(self, visible: bool) -> None:
        """Show/hide queue label based on recording state."""
        self._queue_label.setVisible(visible)
        if not visible:
            self._queue_label.setText("Unsaved frames: 0")
            if self._queue_warning:
                self._queue_label.setStyleSheet(_STYLE_MUTED)
                self._queue_warning = False

    def set_queue_depth(self, depth: int) -> None:
        """Update unsaved frame count. Does not change visibility."""
        self._queue_label.setText(f"Unsaved frames: {depth}")
        warning = depth >= _QUEUE_DEPTH_WARNING
        if warning != self._queue_warning:
            color = _COLOR_WARNING if warning else "#888888"
            self._queue_label.setStyleSheet(f"font-size: 10px; color: {color};")
            self._queue_warning = warning

    def set_resolution(self, resolution: str) -> None:
        """Show camera resolution (e.g., '1920x1080')."""
        self._resolution_label.setText(resolution)

    def set_error(self, message: str) -> None:
        """Show error state (e.g., disconnected)."""
        self._frame_label.setText(message)
        self._stats_label.setText("--")

    def set_focus_enabled(self, enabled: bool, reason: str = "") -> None:
        """Enable/disable focus button. Shows reason text when disabled."""
        self._focus_btn.setEnabled(enabled)
        if enabled:
            self._focus_btn.setText("Focus")
        elif reason:
            self._focus_btn.setText(reason)
