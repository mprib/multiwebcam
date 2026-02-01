#!/usr/bin/env python3
"""
Script 08: Camera Controls

Query and set V4L2 camera controls (exposure, gain, white balance, focus).
Uses v4l2-ctl for reliable control enumeration and modification.

Usage:
    uv run python scripts/pyav_exploration/08_camera_controls.py [device]

Optional flags:
    --demo    Run a visual demo showing exposure changes (requires cv2.imshow)
"""

import re
import subprocess
import sys
from dataclasses import dataclass


@dataclass
class V4L2Control:
    """A V4L2 camera control with its properties."""

    name: str
    id: str  # v4l2 control ID (e.g., "exposure_auto")
    type: str  # int, bool, menu
    min: int | None
    max: int | None
    step: int | None
    default: int | None
    current: int | None
    menu_items: dict[int, str] | None = None

    def __str__(self) -> str:
        if self.type == "menu" and self.menu_items:
            current_name = self.menu_items.get(self.current, str(self.current))
            return f"{self.name}: {current_name} (menu)"
        elif self.type == "bool":
            return f"{self.name}: {'ON' if self.current else 'OFF'}"
        else:
            range_str = f"[{self.min}-{self.max}]" if self.min is not None else ""
            return f"{self.name}: {self.current} {range_str}"


def parse_controls(output: str) -> list[V4L2Control]:
    """
    Parse output from v4l2-ctl --list-ctrls-menus.

    Example output:
                     brightness 0x00980900 (int)    : min=0 max=255 step=1 default=128 value=128
                       contrast 0x00980901 (int)    : min=0 max=255 step=1 default=128 value=128
                  exposure_auto 0x009a0901 (menu)   : min=0 max=3 default=3 value=3
                                    1: Manual Mode
                                    3: Aperture Priority Mode
             exposure_absolute 0x009a0902 (int)    : min=3 max=2047 step=1 default=250 value=166
    """
    controls = []
    current_control = None

    # Pattern for control line
    control_pattern = re.compile(
        r"^\s*(\w+)\s+0x[\da-f]+\s+\((\w+)\)\s*:\s*(.+)$", re.IGNORECASE
    )
    # Pattern for menu item
    menu_pattern = re.compile(r"^\s*(\d+):\s*(.+)$")

    for line in output.splitlines():
        # Try to match a control definition
        match = control_pattern.match(line)
        if match:
            # Save previous control
            if current_control:
                controls.append(current_control)

            name = match.group(1)
            ctrl_type = match.group(2)
            properties = match.group(3)

            # Parse properties
            props = {}
            for prop in ["min", "max", "step", "default", "value"]:
                prop_match = re.search(rf"{prop}=(-?\d+)", properties)
                if prop_match:
                    props[prop] = int(prop_match.group(1))

            current_control = V4L2Control(
                name=name,
                id=name,
                type=ctrl_type,
                min=props.get("min"),
                max=props.get("max"),
                step=props.get("step"),
                default=props.get("default"),
                current=props.get("value"),
                menu_items={} if ctrl_type == "menu" else None,
            )
            continue

        # Try to match a menu item (belongs to current control)
        menu_match = menu_pattern.match(line)
        if menu_match and current_control and current_control.menu_items is not None:
            idx = int(menu_match.group(1))
            label = menu_match.group(2).strip()
            current_control.menu_items[idx] = label

    # Don't forget last control
    if current_control:
        controls.append(current_control)

    return controls


def query_controls(device: str) -> list[V4L2Control]:
    """
    Query all available controls for a device.

    Args:
        device: V4L2 device path

    Returns:
        List of V4L2Control objects
    """
    result = subprocess.run(
        ["v4l2-ctl", "-d", device, "--list-ctrls-menus"],
        capture_output=True,
        text=True,
        timeout=5,
    )

    if result.returncode != 0:
        print(f"Error querying controls: {result.stderr}")
        return []

    return parse_controls(result.stdout)


def set_control(device: str, control_name: str, value: int) -> bool:
    """
    Set a control value.

    Args:
        device: V4L2 device path
        control_name: Name of control (e.g., 'exposure_auto')
        value: Integer value to set

    Returns:
        True if successful
    """
    result = subprocess.run(
        ["v4l2-ctl", "-d", device, "--set-ctrl", f"{control_name}={value}"],
        capture_output=True,
        text=True,
        timeout=5,
    )

    return result.returncode == 0


def get_control_value(device: str, control_name: str) -> int | None:
    """Get current value of a control."""
    result = subprocess.run(
        ["v4l2-ctl", "-d", device, "--get-ctrl", control_name],
        capture_output=True,
        text=True,
        timeout=5,
    )

    if result.returncode == 0:
        match = re.search(r":\s*(-?\d+)", result.stdout)
        if match:
            return int(match.group(1))
    return None


def categorize_controls(controls: list[V4L2Control]) -> dict[str, list[V4L2Control]]:
    """Group controls by category for display."""
    categories = {
        "Exposure": [],
        "White Balance": [],
        "Focus": [],
        "Image": [],
        "Other": [],
    }

    for ctrl in controls:
        name_lower = ctrl.name.lower()
        if "exposure" in name_lower or "gain" in name_lower:
            categories["Exposure"].append(ctrl)
        elif "white" in name_lower or "balance" in name_lower or "temperature" in name_lower:
            categories["White Balance"].append(ctrl)
        elif "focus" in name_lower:
            categories["Focus"].append(ctrl)
        elif any(x in name_lower for x in ["brightness", "contrast", "saturation", "sharpness", "hue"]):
            categories["Image"].append(ctrl)
        else:
            categories["Other"].append(ctrl)

    return {k: v for k, v in categories.items() if v}


def print_controls(device: str, controls: list[V4L2Control]) -> None:
    """Print formatted control report."""
    print(f"\nAvailable controls for {device}:")
    print("-" * 60)

    categorized = categorize_controls(controls)

    for category, ctrls in categorized.items():
        print(f"\n{category}:")
        for ctrl in ctrls:
            print(f"  {ctrl}")


def demo_exposure_control(device: str) -> None:
    """
    Visual demo of exposure control (requires display).

    Opens a window showing the camera feed while adjusting exposure.
    """
    try:
        import cv2
    except ImportError:
        print("\nSkipping visual demo (opencv-python not available)")
        return

    import av

    print("\n" + "=" * 60)
    print("Visual Demo: Exposure Control")
    print("=" * 60)
    print("Watch the camera feed as exposure changes...")
    print("Press 'q' to quit")

    # First, try to set manual exposure mode
    # Most cameras use exposure_auto: 1=Manual, 3=Aperture Priority
    set_control(device, "exposure_auto", 1)  # Manual mode

    container = av.open(device, format="v4l2", options={"video_size": "640x480"})

    exposure_values = [50, 100, 250, 500, 1000]
    current_idx = 0
    frame_count = 0

    print(f"\nCycling through exposure values: {exposure_values}")

    for frame in container.decode(video=0):
        img = frame.to_ndarray(format="bgr24")

        # Change exposure every 30 frames
        if frame_count % 30 == 0:
            exposure = exposure_values[current_idx % len(exposure_values)]
            set_control(device, "exposure_absolute", exposure)
            print(f"  Exposure set to: {exposure}")
            current_idx += 1

        # Show current exposure on frame
        current_exposure = get_control_value(device, "exposure_absolute")
        cv2.putText(
            img,
            f"Exposure: {current_exposure}",
            (10, 30),
            cv2.FONT_HERSHEY_SIMPLEX,
            1,
            (0, 255, 0),
            2,
        )

        cv2.imshow("Exposure Demo", img)

        frame_count += 1
        if cv2.waitKey(1) & 0xFF == ord("q") or frame_count > 200:
            break

    container.close()
    cv2.destroyAllWindows()

    # Reset to auto exposure
    set_control(device, "exposure_auto", 3)
    print("\nReset to auto exposure mode")


def test_control_modification(device: str, controls: list[V4L2Control]) -> None:
    """Test modifying a safe control and verify it changed."""
    print("\n" + "=" * 60)
    print("Testing Control Modification")
    print("=" * 60)

    # Find brightness control (safe to modify)
    brightness = next((c for c in controls if c.name == "brightness"), None)

    if not brightness:
        print("  No brightness control found, skipping test")
        return

    original = brightness.current
    test_value = brightness.min + 10 if brightness.min is not None else 50

    print(f"\n  Original brightness: {original}")
    print(f"  Setting brightness to: {test_value}")

    success = set_control(device, "brightness", test_value)
    if not success:
        print("  FAIL: Could not set brightness")
        return

    # Verify change
    new_value = get_control_value(device, "brightness")
    print(f"  Read back: {new_value}")

    if new_value == test_value:
        print("  OK: Control modification verified")
    else:
        print(f"  WARNING: Value mismatch (expected {test_value}, got {new_value})")

    # Reset to original
    set_control(device, "brightness", original)
    print(f"  Reset to original: {original}")


def main():
    # Parse arguments
    device = "/dev/video0"
    run_demo = False

    for arg in sys.argv[1:]:
        if arg == "--demo":
            run_demo = True
        elif arg.startswith("/dev/"):
            device = arg

    print("=" * 70)
    print("PyAV Exploration - Script 08: Camera Controls")
    print("=" * 70)

    # Check v4l2-ctl is available
    try:
        subprocess.run(
            ["v4l2-ctl", "--version"], capture_output=True, check=True, timeout=2
        )
    except FileNotFoundError:
        print("\nError: v4l2-ctl not found")
        print("Install with: sudo apt install v4l-utils")
        sys.exit(1)

    # Query and display controls
    controls = query_controls(device)

    if not controls:
        print(f"\nNo controls found for {device}")
        print("This may be a metadata node - try a different /dev/video* device")
        sys.exit(1)

    print_controls(device, controls)

    # Test control modification
    test_control_modification(device, controls)

    # Run visual demo if requested
    if run_demo:
        demo_exposure_control(device)

    print("\n" + "=" * 70)
    print("Key Findings:")
    print("=" * 70)
    print("""
V4L2 Camera Control Patterns:

1. Auto vs Manual modes:
   - exposure_auto: 1=Manual, 3=Aperture Priority (auto)
   - white_balance_temperature_auto: 0=Manual, 1=Auto
   - focus_auto: 0=Manual, 1=Auto

   Must set to Manual before adjusting related controls!

2. Control dependencies:
   - exposure_absolute only works when exposure_auto=1
   - white_balance_temperature only works when wb_auto=0
   - Some controls require stream restart to take effect

3. Setting controls via v4l2-ctl:
   v4l2-ctl -d /dev/video0 --set-ctrl exposure_auto=1
   v4l2-ctl -d /dev/video0 --set-ctrl exposure_absolute=500

4. Setting controls BEFORE PyAV open:
   Recommended workflow:
   1. Configure controls with v4l2-ctl
   2. Then open stream with PyAV
   3. Controls persist while device is open

5. Per-camera variation:
   - Available controls vary significantly by camera
   - Cheap cameras may have fewer controls
   - Some controls may be read-only despite appearing in list

Run with --demo flag to see visual exposure changes.
""")


if __name__ == "__main__":
    main()
