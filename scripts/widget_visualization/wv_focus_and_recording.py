"""Test Focus view switching and recording functionality.

Tests:
1. Grid view with frames
2. Switch to Focus view (click Focus button)
3. Return to Grid view (click Back)
4. Start recording
5. Stop recording

Usage:
    python scripts/widget_visualization/wv_focus_and_recording.py
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
    print("FOCUS VIEW & RECORDING TEST")
    print("=" * 60)
    print()

    # Create and show window
    print("Creating MainWindow...")
    window = MainWindow(project_path)
    window.setWindowTitle("Focus & Recording Test")
    window.resize(1200, 800)
    window.show()

    # Wait for frames to appear
    print("\n[1] Waiting for grid view with frames (3s)...")
    process_events_for(3000)
    capture_widget(window, "01_grid_with_frames.png")

    # Get grid view and find a tile to click
    grid_view = window._stack.currentWidget()
    if not hasattr(grid_view, "_tiles") or not grid_view._tiles:
        print("ERROR: No tiles found in grid view")
        return

    # Click Focus on first tile
    source_id = next(iter(grid_view._tiles.keys()))
    tile = grid_view._tiles[source_id]
    print(f"\n[2] Clicking Focus on source {source_id}...")
    tile._focus_btn.click()
    process_events_for(2000)
    capture_widget(window, "02_focus_view.png")

    # Verify we're in focus view
    focus_view = window._stack.currentWidget()
    print(f"  Current view type: {type(focus_view).__name__}")
    if hasattr(focus_view, "_source_id"):
        print(f"  Focused on source: {focus_view._source_id}")

    # Wait a bit longer to see frames updating
    print("\n[3] Focus view running (2s)...")
    process_events_for(2000)
    capture_widget(window, "03_focus_view_2s.png")

    # Click Back to Grid
    if hasattr(focus_view, "_back_btn"):
        print("\n[4] Clicking Back to Grid...")
        focus_view._back_btn.click()
        process_events_for(1000)
        capture_widget(window, "04_back_to_grid.png")
    else:
        print("ERROR: No back button found")

    # Verify we're back in grid view
    grid_view = window._stack.currentWidget()
    print(f"  Current view type: {type(grid_view).__name__}")

    # Start recording
    if hasattr(grid_view, "_record_btn"):
        print("\n[5] Starting recording...")
        grid_view._record_btn.click()
        process_events_for(500)
        capture_widget(window, "05_recording_started.png")

        # Let it record for 3 seconds
        print("  Recording for 3s...")
        process_events_for(3000)
        capture_widget(window, "06_recording_3s.png")

        # Check recording state
        presenter = window._current_presenter
        if presenter and hasattr(presenter, "is_recording"):
            print(f"  Presenter.is_recording: {presenter.is_recording}")

        # Stop recording
        print("\n[6] Stopping recording...")
        grid_view._stop_btn.click()
        process_events_for(1000)
        capture_widget(window, "07_recording_stopped.png")

        # Check for output files
        recordings_dir = project_path / "recordings"
        if recordings_dir.exists():
            files = list(recordings_dir.rglob("*"))
            print(f"  Files in recordings dir: {len(files)}")
            for f in files[:10]:  # Show first 10
                print(f"    {f.relative_to(project_path)}")
    else:
        print("ERROR: No record button found")

    # Clean shutdown
    print("\n[done] Closing...")
    window.close()
    process_events_for(500)

    print()
    print("=" * 60)
    print("TEST COMPLETE")
    print("=" * 60)
    print()
    print(f"Screenshots saved to: {Path(__file__).parent / 'output'}")
    print()
    print("Verification checklist:")
    print("  [ ] 01: Grid view shows all cameras with frames")
    print("  [ ] 02: Focus view shows single large camera")
    print("  [ ] 03: Focus view frames update")
    print("  [ ] 04: Back returns to grid view")
    print("  [ ] 05: Record button starts recording (button states change)")
    print("  [ ] 06: Recording continues (check for any visual indicator)")
    print("  [ ] 07: Stop button stops recording")
    print("  [ ] Output files created in recordings/")
    print()


if __name__ == "__main__":
    main()
