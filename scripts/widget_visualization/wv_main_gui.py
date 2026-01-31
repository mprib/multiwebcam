"""
Widget visualization script for the main multiwebcam GUI.

Run with: uv run python scripts/widget_visualization/wv_main_gui.py

This script:
1. Launches the main window
2. Creates a temp project folder
3. Takes screenshots at key states
4. Allows interactive exploration

NOT headless - you'll see the window and can interact with it.
"""

import sys
import tempfile
from pathlib import Path

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(Path(__file__).parent))

from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QTimer

from utils import capture_widget, clear_output_dir, process_events_for, wait_for_signal

from multiwebcam.logger import setup_logging

setup_logging()

from multiwebcam.gui.main_widget import MainWindow


def run_visualization():
    clear_output_dir()

    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()

    # Let the window fully render
    process_events_for(500)
    capture_widget(window, "01_initial_launch.png")
    print("  [1] Initial window state - no project loaded")

    # Create a temp project folder
    temp_dir = tempfile.mkdtemp(prefix="multiwebcam_viz_")
    print(f"\n  Creating temp project at: {temp_dir}")

    # Launch session with the temp folder
    # This will attempt to find cameras
    print("  Launching session (will look for cameras)...")
    window.launch_session(temp_dir)

    # Give time for camera detection
    process_events_for(2000)
    capture_widget(window, "02_after_session_launch.png")
    print("  [2] After session launch - camera detection attempted")

    # Check if cameras were found
    if hasattr(window, 'session') and window.session.streams:
        print(f"\n  Found {len(window.session.streams)} camera(s)!")

        # Try SingleCamera mode
        if window.intrinsic_mode_select.isEnabled():
            print("  Switching to SingleCamera mode...")
            window.intrinsic_mode_select.trigger()
            process_events_for(1000)
            capture_widget(window, "03_single_camera_mode.png")
            print("  [3] SingleCamera mode")

        # Try MultiCamera mode
        if window.recording_mode_select.isEnabled():
            print("  Switching to MultiCamera mode...")
            window.recording_mode_select.trigger()
            process_events_for(1000)
            capture_widget(window, "04_multi_camera_mode.png")
            print("  [4] MultiCamera mode")
    else:
        print("\n  No cameras detected. Limited visualization possible.")
        print("  Connect USB webcams and re-run for full visualization.")

    # Print verification checklist
    print()
    print("=" * 60)
    print("VISUALIZATION COMPLETE")
    print("=" * 60)
    print()
    print("Screenshots saved to: scripts/widget_visualization/output/")
    print()
    print("Interactive checks (window is still open):")
    print("  [ ] Menu bar accessible (File, Mode)")
    print("  [ ] Log dock widget visible at bottom")
    print("  [ ] Window resizes correctly")
    print()
    print("Press Ctrl+C in terminal or close window to exit.")
    print()

    # Keep the app running for interactive exploration
    sys.exit(app.exec())


if __name__ == "__main__":
    run_visualization()
