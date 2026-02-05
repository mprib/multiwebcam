"""Widget visualization test for MainWindow with real cameras.

Captures screenshots at key moments to verify the UI is rendering correctly.

Usage:
    # Headless (CI/remote)
    xvfb-run --auto-servernum python scripts/widget_visualization/wv_main_window.py

    # With display (interactive)
    python scripts/widget_visualization/wv_main_window.py
"""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))
sys.path.insert(0, str(Path(__file__).parent))

from PySide6.QtWidgets import QApplication

from multiwebcam.ui import MainWindow
from utils import capture_widget, clear_output_dir, process_events_for


def main() -> None:
    clear_output_dir()
    app = QApplication(sys.argv)

    # Use temp project path
    project_path = Path(__file__).parent / "output" / "test_project"
    project_path.mkdir(parents=True, exist_ok=True)

    print("Creating MainWindow...")
    window = MainWindow(project_path)
    window.setWindowTitle("Widget Visualization Test")
    window.resize(1200, 800)
    window.show()

    # Wait for cameras to initialize and frames to arrive
    print("Waiting for camera initialization (2s)...")
    process_events_for(2000)
    capture_widget(window, "01_initial_grid.png")

    # Wait longer for frames to appear
    print("Waiting for frames (3s)...")
    process_events_for(3000)
    capture_widget(window, "02_with_frames.png")

    # Find a Focus button and click it
    grid_view = window._stack.currentWidget()
    if hasattr(grid_view, "_tiles") and grid_view._tiles:
        source_id = next(iter(grid_view._tiles.keys()))
        tile = grid_view._tiles[source_id]
        print(f"Clicking Focus on source {source_id}...")
        tile._focus_btn.click()
        process_events_for(1000)
        capture_widget(window, "03_focus_view.png")

        # Click back
        focus_view = window._stack.currentWidget()
        if hasattr(focus_view, "_back_btn"):
            print("Clicking Back to Grid...")
            focus_view._back_btn.click()
            process_events_for(500)
            capture_widget(window, "04_back_to_grid.png")

    # Clean shutdown
    window.close()
    process_events_for(500)

    print()
    print("=" * 60)
    print("VERIFICATION COMPLETE")
    print("=" * 60)
    print()
    print("Check screenshots in scripts/widget_visualization/output/")
    print()
    print("Static checks (review screenshots):")
    print("  [ ] 01: Grid view renders with camera tiles")
    print("  [ ] 02: Frames appear in tiles after waiting")
    print("  [ ] 03: Focus view shows single large frame")
    print("  [ ] 04: Returns to grid view correctly")
    print()


if __name__ == "__main__":
    main()
