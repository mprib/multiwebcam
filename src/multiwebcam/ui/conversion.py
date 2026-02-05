"""Frame conversion utilities for Qt display."""

import numpy as np
from PySide6.QtGui import QImage, QPixmap


def frame_to_pixmap(frame: np.ndarray) -> QPixmap:
    """Convert BGR numpy array to QPixmap for display.

    Args:
        frame: BGR image array, shape (H, W, 3), dtype uint8

    Returns:
        QPixmap ready for display in Qt widgets
    """
    height, width, channels = frame.shape
    bytes_per_line = channels * width
    # Convert BGR to RGB for Qt
    rgb_frame = frame[..., ::-1].copy()
    image = QImage(rgb_frame.data, width, height, bytes_per_line, QImage.Format.Format_RGB888)
    # Copy into QImage's internal buffer before rgb_frame goes out of scope
    return QPixmap.fromImage(image.copy())
