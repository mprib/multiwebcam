"""Shared utilities for widget visualization scripts."""

import shutil
from pathlib import Path

from PySide6.QtCore import QCoreApplication
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QWidget

OUTPUT_DIR = Path(__file__).parent / "output"


def clear_output_dir() -> None:
    """Clear and recreate the output directory."""
    if OUTPUT_DIR.exists():
        shutil.rmtree(OUTPUT_DIR)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


def capture_widget(widget: QWidget, filename: str) -> Path:
    """Capture a widget to a PNG file in the output directory."""
    output_path = OUTPUT_DIR / filename
    pixmap = widget.grab()
    pixmap.save(str(output_path))
    print(f"  Captured: {output_path}")
    return output_path


def process_events_for(ms: int) -> None:
    """Process Qt events for the specified duration."""
    from PySide6.QtCore import QEventLoop, QTimer

    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()
