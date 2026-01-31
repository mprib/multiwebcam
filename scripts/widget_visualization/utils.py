"""
Shared utilities for widget visualization scripts.
"""

import shutil
from pathlib import Path

from PySide6.QtCore import QCoreApplication, QEventLoop, QTimer
from PySide6.QtWidgets import QWidget

OUTPUT_DIR = Path(__file__).parent / "output"


def clear_output_dir():
    """Remove and recreate the output directory."""
    if OUTPUT_DIR.exists():
        shutil.rmtree(OUTPUT_DIR)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


def process_events_for(ms: int):
    """Process Qt events for the specified duration."""
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


def capture_widget(widget: QWidget, filename: str):
    """Capture a screenshot of the widget."""
    pixmap = widget.grab()
    output_path = OUTPUT_DIR / filename
    pixmap.save(str(output_path))
    print(f"  Saved: {output_path}")


def capture_screen(app, filename: str):
    """Capture the entire primary screen."""
    screen = app.primaryScreen()
    pixmap = screen.grabWindow(0)
    output_path = OUTPUT_DIR / filename
    pixmap.save(str(output_path))
    print(f"  Saved: {output_path}")


def wait_for_signal(signal, timeout_ms: int = 30000) -> bool:
    """Block until signal fires or timeout. Returns True if signal fired."""
    loop = QEventLoop()
    timed_out = [False]

    def on_timeout():
        timed_out[0] = True
        loop.quit()

    signal.connect(loop.quit)
    QTimer.singleShot(timeout_ms, on_timeout)
    loop.exec()
    return not timed_out[0]
