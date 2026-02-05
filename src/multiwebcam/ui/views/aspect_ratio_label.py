"""QLabel subclass that preserves aspect ratio when displaying pixmaps."""

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap, QResizeEvent
from PySide6.QtWidgets import QLabel


class AspectRatioLabel(QLabel):
    """Displays a pixmap scaled to fit while preserving aspect ratio.

    Unused space is filled with the background color (black by default),
    producing letterbox or pillarbox bars as needed.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._original_pixmap: QPixmap | None = None
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setStyleSheet("background-color: black;")

    def display_pixmap(self, pixmap: QPixmap) -> None:
        """Set the pixmap to display, scaling to fit current size."""
        self._original_pixmap = pixmap
        self._update_scaled()

    def resizeEvent(self, event: QResizeEvent) -> None:
        """Re-scale pixmap when the label is resized."""
        super().resizeEvent(event)
        self._update_scaled()

    def _update_scaled(self) -> None:
        if self._original_pixmap is None:
            return
        scaled = self._original_pixmap.scaled(
            self.size(),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        super().setPixmap(scaled)
