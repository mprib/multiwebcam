"""Visual test for AspectRatioLabel widget.

Tests aspect ratio preservation with synthetic images of various ratios,
resize behavior, and integration with SourceTile and FocusView.

Usage:
    python scripts/widget_visualization/wv_aspect_ratio.py
"""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))
sys.path.insert(0, str(Path(__file__).parent))

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPainter, QPixmap
from PySide6.QtWidgets import QApplication

from multiwebcam.ui.views.aspect_ratio_label import AspectRatioLabel
from multiwebcam.ui.views.focus_view import FocusView
from multiwebcam.ui.views.source_tile import SourceTile
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
    print("ASPECT RATIO LABEL TEST")
    print("=" * 60)
    print()

    # Test images with different aspect ratios
    test_images = [
        (1280, 720, QColor(0, 100, 200), "16:9"),     # Landscape
        (1024, 768, QColor(0, 150, 0), "4:3"),        # Traditional
        (480, 480, QColor(200, 0, 0), "1:1"),         # Square
        (720, 1280, QColor(200, 200, 0), "9:16"),     # Portrait
    ]

    # Test 1: AspectRatioLabel with fixed container size
    print("[1] Testing aspect ratio preservation in 640x480 container")
    print()

    for width, height, color, label_text in test_images:
        print(f"  Testing {label_text} ({width}x{height})...")
        pixmap = create_test_pixmap(width, height, color, label_text)

        label = AspectRatioLabel()
        label.setFixedSize(640, 480)
        label.display_pixmap(pixmap)
        label.show()

        process_events_for(100)
        filename = f"aspect_{label_text.replace(':', 'x')}.png"
        capture_widget(label, filename)

        label.close()

    # Test 2: Resize behavior
    print()
    print("[2] Testing resize behavior (landscape container → portrait container)")
    print()

    pixmap_16x9 = create_test_pixmap(1280, 720, QColor(0, 100, 200), "16:9")

    print("  Creating label with 16:9 image, 640x480 landscape container...")
    label = AspectRatioLabel()
    label.setFixedSize(640, 480)
    label.display_pixmap(pixmap_16x9)
    label.show()

    process_events_for(100)
    capture_widget(label, "aspect_resize_landscape.png")

    print("  Resizing to 480x640 portrait container...")
    label.setFixedSize(480, 640)
    process_events_for(100)
    capture_widget(label, "aspect_resize_portrait.png")

    label.close()

    # Test 3: SourceTile integration
    print()
    print("[3] Testing AspectRatioLabel inside SourceTile")
    print()

    pixmap_16x9 = create_test_pixmap(1280, 720, QColor(0, 100, 200), "16:9")

    print("  Creating SourceTile with 16:9 frame...")
    tile = SourceTile(source_id=0, label="Test Camera")
    tile.display_frame(pixmap_16x9)
    tile.update_stats(fps=30.0, jitter_ms=2.5)
    tile.show()

    process_events_for(100)
    capture_widget(tile, "aspect_source_tile.png")

    tile.close()

    # Test 4: FocusView integration
    print()
    print("[4] Testing AspectRatioLabel inside FocusView")
    print()

    pixmap_16x9 = create_test_pixmap(1280, 720, QColor(0, 100, 200), "16:9")

    print("  Creating FocusView with 16:9 frame...")
    focus_view = FocusView(source_id=0, label="Test Camera")
    focus_view.display_frame(pixmap_16x9)
    focus_view.resize(800, 600)
    focus_view.show()

    process_events_for(100)
    capture_widget(focus_view, "aspect_focus_view.png")

    focus_view.close()

    print()
    print("=" * 60)
    print("TEST COMPLETE")
    print("=" * 60)
    print()
    print(f"Screenshots saved to: {Path(__file__).parent / 'output'}")
    print()
    print("Verification checklist:")
    print("  [ ] aspect_16x9.png: Landscape image, letterboxed top/bottom")
    print("  [ ] aspect_4x3.png: Traditional ratio, smaller letterbox")
    print("  [ ] aspect_1x1.png: Square image, pillarboxed left/right")
    print("  [ ] aspect_9x16.png: Portrait image, large pillarbox")
    print("  [ ] aspect_resize_landscape.png: 16:9 in landscape, letterboxed")
    print("  [ ] aspect_resize_portrait.png: Same 16:9 in portrait, pillarboxed")
    print("  [ ] aspect_source_tile.png: Tile with frame, fps/jitter stats")
    print("  [ ] aspect_focus_view.png: Large view with frame")
    print()
    print("Expected behavior:")
    print("  - No distortion: all images preserve aspect ratio")
    print("  - Black bars fill unused space (letterbox/pillarbox)")
    print("  - Resize changes bar orientation but preserves image ratio")
    print("  - SourceTile and FocusView use AspectRatioLabel correctly")
    print()


if __name__ == "__main__":
    main()
