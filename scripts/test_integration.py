"""Integration test for multiwebcam UI with real cameras.

Run this script to manually validate the full UI stack:
- Camera discovery and live preview
- View switching (grid <-> focus)
- Recording functionality

Usage:
    uv run python scripts/test_integration.py
"""

import sys
from pathlib import Path

from PySide6.QtWidgets import QApplication

from multiwebcam.ui import MainWindow


def main() -> None:
    print("Starting multiwebcam integration test...")
    print("This will connect to real cameras.")
    print()

    app = QApplication(sys.argv)

    # Use temp directory for test recordings
    project_path = Path(__file__).parent / "test_project"
    project_path.mkdir(exist_ok=True)

    print(f"Project path: {project_path}")
    print()

    window = MainWindow(project_path)
    window.setWindowTitle("multiwebcam - Integration Test")
    window.resize(1200, 800)
    window.show()

    print("Window opened. Test the following:")
    print("1. Grid view shows all connected cameras")
    print("2. Frames update at ~30fps")
    print("3. Stats show fps and jitter")
    print("4. Click 'Focus' to enter focus mode")
    print("5. Click 'Back to Grid' to return")
    print("6. Click 'Record' to start recording")
    print("7. Click 'Stop' to stop recording")
    print(f"8. Check {project_path}/recordings for output files")
    print()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
