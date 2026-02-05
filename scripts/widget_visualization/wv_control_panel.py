"""Visual test for ControlPanel widget.

Tests the dynamically-generated control panel with various V4L2 control types:
int, bool, and menu controls. Verifies widget creation, layout, and signal emission.

Usage:
    python scripts/widget_visualization/wv_control_panel.py
"""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))
sys.path.insert(0, str(Path(__file__).parent))

from PySide6.QtWidgets import QApplication, QWidget, QVBoxLayout

from multiwebcam.sources.controls import V4L2Control
from multiwebcam.ui.views.control_panel import ControlPanel
from utils import capture_widget, clear_output_dir, process_events_for


def create_sample_controls() -> list[V4L2Control]:
    """Create realistic V4L2 controls covering all three types."""
    return [
        # Int controls with realistic ranges
        V4L2Control(
            name="brightness",
            type="int",
            min=0,
            max=255,
            step=1,
            default=128,
            current=128,
            menu_items=None,
        ),
        V4L2Control(
            name="contrast",
            type="int",
            min=0,
            max=255,
            step=1,
            default=128,
            current=150,
            menu_items=None,
        ),
        V4L2Control(
            name="saturation",
            type="int",
            min=0,
            max=255,
            step=1,
            default=128,
            current=100,
            menu_items=None,
        ),
        V4L2Control(
            name="exposure_absolute",
            type="int",
            min=3,
            max=2047,
            step=1,
            default=250,
            current=166,
            menu_items=None,
        ),
        # Bool control
        V4L2Control(
            name="focus_auto",
            type="bool",
            min=None,
            max=None,
            step=None,
            default=1,
            current=1,
            menu_items=None,
        ),
        # Menu control
        V4L2Control(
            name="exposure_auto",
            type="menu",
            min=0,
            max=3,
            step=None,
            default=3,
            current=3,
            menu_items={1: "Manual Mode", 3: "Aperture Priority Mode"},
        ),
    ]


def main() -> None:
    clear_output_dir()
    app = QApplication(sys.argv)

    print("=" * 60)
    print("CONTROL PANEL WIDGET TEST")
    print("=" * 60)
    print()

    # Test 1: Populated panel with all control types
    print("[1] Testing control panel with mixed control types")
    print()

    controls = create_sample_controls()

    print(f"  Creating ControlPanel with {len(controls)} controls:")
    for control in controls:
        print(f"    - {control.name} ({control.type})")
    print()

    panel = ControlPanel(controls)

    # Connect signal to print changes
    def on_control_changed(name: str, value: int) -> None:
        print(f"    Control changed: {name} = {value}")

    panel.control_changed.connect(on_control_changed)

    # Wrap in a container for better visualization
    container = QWidget()
    layout = QVBoxLayout(container)
    layout.addWidget(panel)

    container.resize(400, 600)
    container.setWindowTitle("Control Panel Test")
    container.show()

    process_events_for(100)
    capture_widget(container, "control_panel_populated.png")

    print()
    print("  Try adjusting controls in the window to test signal emission...")
    print("  (Close window to continue)")
    print()

    # Keep window open for manual interaction
    app.exec()

    container.close()

    # Test 2: Empty panel
    print()
    print("[2] Testing empty control panel")
    print()

    print("  Creating ControlPanel with no controls...")
    empty_panel = ControlPanel([])

    container = QWidget()
    layout = QVBoxLayout(container)
    layout.addWidget(empty_panel)

    container.resize(400, 300)
    container.setWindowTitle("Empty Control Panel Test")
    container.show()

    process_events_for(100)
    capture_widget(container, "control_panel_empty.png")

    container.close()

    print()
    print("=" * 60)
    print("TEST COMPLETE")
    print("=" * 60)
    print()
    print(f"Screenshots saved to: {Path(__file__).parent / 'output'}")
    print()
    print("Verification checklist:")
    print("  [ ] control_panel_populated.png:")
    print("      - Header: 'Camera Controls' (bold)")
    print("      - Int controls: slider + spinbox pairs")
    print("      - Bool control: checkbox")
    print("      - Menu control: combobox with two items")
    print("      - Labels formatted nicely (e.g., 'Exposure Absolute')")
    print("      - Scrollable if needed")
    print()
    print("  [ ] control_panel_empty.png:")
    print("      - Header: 'Camera Controls' (bold)")
    print("      - Message: 'No controls available' (disabled/grayed)")
    print()
    print("Expected behavior:")
    print("  - Int controls: slider and spinbox stay in sync")
    print("  - Bool control: checkbox toggles between 0/1")
    print("  - Menu control: combobox shows descriptive labels")
    print("  - control_changed signal emitted on every change")
    print()


if __name__ == "__main__":
    main()
