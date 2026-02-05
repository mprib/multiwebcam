"""Debug script to investigate frame display issues.

Runs for 8 seconds with periodic screenshots and diagnostic output.

Usage:
    python scripts/widget_visualization/wv_debug_frames.py
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

    project_path = Path(__file__).parent / "output" / "test_project"
    project_path.mkdir(parents=True, exist_ok=True)

    print("=" * 60)
    print("FRAME DEBUG SESSION")
    print("=" * 60)
    print()

    print("Creating MainWindow...")
    window = MainWindow(project_path)
    window.setWindowTitle("Frame Debug - 8 second run")
    window.resize(1200, 800)
    window.show()

    # Get references for diagnostics
    coordinator = window._coordinator
    session = coordinator.session

    print(f"Project path: {project_path}")
    print(f"Session: {session}")
    print(f"Sources: {list(coordinator.sources.keys())}")
    print()

    # Initial state
    print("[0s] Initial state")
    capture_widget(window, "00_initial.png")

    if session:
        print(f"  Active device paths: {session.active_device_paths}")
        frames = session.get_latest_frames()
        print(f"  get_latest_frames() returned: {list(frames.keys())}")
        for path, packet in frames.items():
            if packet:
                print(f"    {path}: frame shape {packet.frame.shape}, index {packet.frame_index}")
            else:
                print(f"    {path}: None")

    # Run for 8 seconds with periodic checks
    for i in range(1, 9):
        print(f"\n[{i}s] Waiting...")
        process_events_for(1000)
        capture_widget(window, f"{i:02d}_at_{i}s.png")

        if session:
            frames = session.get_latest_frames()
            stats = session.get_camera_stats()
            print(f"  Frames: {sum(1 for p in frames.values() if p is not None)}/{len(frames)} have data")
            if stats:
                for path, stat in stats.items():
                    print(f"    {path}: {stat.measured_fps:.1f} fps, {stat.jitter_ms:.1f}ms jitter")

        # Check presenter state
        presenter = window._current_presenter
        if presenter:
            print(f"  Presenter active: {presenter.is_active}")

        # Check grid view tiles
        grid_view = window._stack.currentWidget()
        if hasattr(grid_view, "_tiles"):
            print(f"  Grid tiles: {list(grid_view._tiles.keys())}")
            for sid, tile in grid_view._tiles.items():
                pixmap = tile._frame_label.pixmap()
                if pixmap and not pixmap.isNull():
                    print(f"    Tile {sid}: has pixmap {pixmap.width()}x{pixmap.height()}")
                else:
                    print(f"    Tile {sid}: NO pixmap")

    # Clean shutdown
    print("\n[done] Closing...")
    window.close()
    process_events_for(500)

    print()
    print("=" * 60)
    print("DEBUG SESSION COMPLETE")
    print("=" * 60)
    print()
    print(f"Screenshots saved to: {Path(__file__).parent / 'output'}")
    print()
    print("Check:")
    print("  - Are frames being captured? (get_latest_frames)")
    print("  - Is presenter active?")
    print("  - Do tiles have pixmaps?")
    print()


if __name__ == "__main__":
    main()
