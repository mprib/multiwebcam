"""V4L2 camera control discovery and manipulation.

Uses v4l2-ctl for reliable control enumeration and modification.
Ported from scripts/pyav_exploration/08_camera_controls.py.
"""

from __future__ import annotations

import logging
import re
import subprocess
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class V4L2Control:
    """A V4L2 camera control with its properties.

    The name field serves as the control identifier (e.g., "exposure_auto").
    """

    name: str
    type: str  # int, bool, menu
    min: int | None
    max: int | None
    step: int | None
    default: int | None
    current: int | None
    menu_items: dict[int, str] | None = None

    def __str__(self) -> str:
        if self.type == "menu" and self.menu_items:
            if self.current is not None:
                current_name = self.menu_items.get(self.current, str(self.current))
            else:
                current_name = "None"
            return f"{self.name}: {current_name} (menu)"
        elif self.type == "bool":
            return f"{self.name}: {'ON' if self.current else 'OFF'}"
        else:
            range_str = f"[{self.min}-{self.max}]" if self.min is not None else ""
            return f"{self.name}: {self.current} {range_str}"


def parse_controls(output: str) -> list[V4L2Control]:
    """Parse output from v4l2-ctl --list-ctrls-menus.

    Example output:
                     brightness 0x00980900 (int)    : min=0 max=255 step=1 default=128 value=128
                       contrast 0x00980901 (int)    : min=0 max=255 step=1 default=128 value=128
                  exposure_auto 0x009a0901 (menu)   : min=0 max=3 default=3 value=3
                                    1: Manual Mode
                                    3: Aperture Priority Mode
             exposure_absolute 0x009a0902 (int)    : min=3 max=2047 step=1 default=250 value=166

    Args:
        output: Raw output from v4l2-ctl

    Returns:
        List of V4L2Control objects
    """
    controls = []
    current_control = None

    # Pattern for control line
    control_pattern = re.compile(r"^\s*(\w+)\s+0x[\da-f]+\s+\((\w+)\)\s*:\s*(.+)$", re.IGNORECASE)
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
    """Query all available controls for a device.

    Args:
        device: V4L2 device path (e.g., "/dev/video0")

    Returns:
        List of V4L2Control objects (empty list if query fails)
    """
    result = subprocess.run(
        ["v4l2-ctl", "-d", device, "--list-ctrls-menus"],
        capture_output=True,
        text=True,
        timeout=5,
    )

    if result.returncode != 0:
        logger.debug(f"v4l2-ctl failed for {device}: {result.stderr.strip()}")
        return []

    return parse_controls(result.stdout)


def set_control(device: str, control_name: str, value: int) -> bool:
    """Set a control value.

    Args:
        device: V4L2 device path (e.g., "/dev/video0")
        control_name: Name of control (e.g., "exposure_auto")
        value: Integer value to set

    Returns:
        True if successful, False otherwise
    """
    result = subprocess.run(
        ["v4l2-ctl", "-d", device, "--set-ctrl", f"{control_name}={value}"],
        capture_output=True,
        text=True,
        timeout=5,
    )

    return result.returncode == 0


def get_control_value(device: str, control_name: str) -> int | None:
    """Get current value of a control.

    Args:
        device: V4L2 device path (e.g., "/dev/video0")
        control_name: Name of control (e.g., "brightness")

    Returns:
        Current value, or None if query fails
    """
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
