"""Visual test for FocusView configuration panel.

Tests the FocusView layout with its side panel containing resolution/fps
combo boxes and Apply button. Format is locked to MJPEG.
Verifies layout with different configurations, disabled states, and aspect ratios.

Usage:
    python scripts/widget_visualization/wv_focus_config.py
"""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))
sys.path.insert(0, str(Path(__file__).parent))

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPainter, QPixmap
from PySide6.QtWidgets import QApplication

from multiwebcam.ui.views.focus_view import FocusView
from utils import capture_widget, clear_output_dir, process_events_for


def create_test_pixmap(width: int, height: int, color: QColor, label_text: str) -> QPixmap:
    """Create a synthetic test image with the specified dimensions and color."""
    pixmap = QPixmap(width, height)
    pixmap.fill(color)

    painter = QPainter(pixmap)
    painter.setPen(Qt.GlobalColor.white)

    # Use large, bold font for visibility
    font = painter.font()
    font.setPointSize(48)
    font.setBold(True)
    painter.setFont(font)

    # Center the text
    painter.drawText(pixmap.rect(), Qt.AlignmentFlag.AlignCenter, label_text)
    painter.end()

    return pixmap


def main() -> None:
    clear_output_dir()
    app = QApplication(sys.argv)

    print("=" * 60)
    print("FOCUS VIEW CONFIGURATION PANEL TEST")
    print("=" * 60)
    print()

    # Test 1: Basic layout with populated combos
    print("[1] Testing basic layout with populated configuration combos")
    print()

    print("  Creating FocusView with HD Pro Webcam C920...")
    view = FocusView(source_id=0, label="HD Pro Webcam C920")

    print("  Populating configuration options...")
    view.populate_resolutions(["1920x1080", "1280x720", "640x480"])
    view.populate_framerates(["30", "15", "5"])

    print("  Setting current config to 1280x720, 30fps...")
    view.set_current_config("1280x720", "30")

    print("  Displaying 16:9 test image (1280x720)...")
    pixmap_16x9 = create_test_pixmap(1280, 720, QColor(0, 100, 200), "16:9")
    view.display_frame(pixmap_16x9)

    view.resize(1000, 600)
    view.show()

    process_events_for(100)
    capture_widget(view, "focus_config_populated.png")

    view.close()

    # Test 2: Config disabled state (simulating recording)
    print()
    print("[2] Testing disabled state (simulating recording)")
    print()

    print("  Creating FocusView with same configuration...")
    view = FocusView(source_id=0, label="HD Pro Webcam C920")
    view.populate_resolutions(["1920x1080", "1280x720", "640x480"])
    view.populate_framerates(["30", "15", "5"])
    view.set_current_config("1280x720", "30")
    view.display_frame(pixmap_16x9)

    print("  Disabling config controls (recording state)...")
    view.set_config_enabled(False)

    view.resize(1000, 600)
    view.show()

    process_events_for(100)
    capture_widget(view, "focus_config_disabled.png")

    view.close()

    # Test 3: Different aspect ratio
    print()
    print("[3] Testing 4:3 aspect ratio with letterboxing")
    print()

    print("  Creating FocusView with 4:3 image...")
    view = FocusView(source_id=0, label="HD Pro Webcam C920")
    view.populate_resolutions(["1024x768", "800x600", "640x480"])
    view.populate_framerates(["30", "15", "5"])

    print("  Setting current config to 1024x768, 30fps...")
    view.set_current_config("1024x768", "30")

    print("  Displaying 4:3 test image (1024x768)...")
    pixmap_4x3 = create_test_pixmap(1024, 768, QColor(0, 150, 0), "4:3")
    view.display_frame(pixmap_4x3)

    view.resize(1000, 600)
    view.show()

    process_events_for(100)
    capture_widget(view, "focus_config_4x3.png")

    view.close()

    print()
    print("=" * 60)
    print("TEST COMPLETE")
    print("=" * 60)
    print()
    print(f"Screenshots saved to: {Path(__file__).parent / 'output'}")
    print()
    print("Verification checklist:")
    print("  [ ] focus_config_populated.png:")
    print("      - 16:9 image displayed in left panel (75% width)")
    print("      - Configuration panel on right (25% width)")
    print("      - Resolution, Framerate combos populated (no format combo)")
    print("      - Apply button enabled")
    print("      - Camera info and stats labels visible")
    print("      - Back to Grid button at bottom")
    print()
    print("  [ ] focus_config_disabled.png:")
    print("      - Same layout as populated test")
    print("      - All combo boxes grayed out/disabled")
    print("      - Apply button disabled")
    print("      - Back button still enabled")
    print()
    print("  [ ] focus_config_4x3.png:")
    print("      - 4:3 green image with letterboxing (black bars top/bottom)")
    print("      - Resolution combo shows 1024x768")
    print("      - Panel layout unchanged")
    print()
    print("Expected behavior:")
    print("  - Video takes 75% width, panel takes 25%")
    print("  - Configuration controls clearly grouped")
    print("  - Disabled state visually distinct")
    print("  - Aspect ratio preserved with black bars as needed")
    print("  - Back button always accessible at bottom")
    print()


if __name__ == "__main__":
    main()
