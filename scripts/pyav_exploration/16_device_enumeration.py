#!/usr/bin/env python3
"""
Exploration Script 16: Device Enumeration

PURPOSE:
List V4L2 video devices, filtering out metadata nodes.

BACKGROUND:
- USB cameras often expose multiple /dev/video* entries
- Some are for video capture, others are for metadata (UVC)
- We need to identify only the video capture devices

APPROACH:
Use v4l2-ctl to query device capabilities and filter by type.

OUTPUT:
List of device paths with their names and capabilities.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path


@dataclass
class V4L2Device:
    """Information about a V4L2 device."""

    path: str
    name: str
    driver: str
    bus_info: str
    capabilities: list[str]

    @property
    def is_video_capture(self) -> bool:
        """True if device supports video capture."""
        return "Video Capture" in self.capabilities

    @property
    def is_metadata(self) -> bool:
        """True if device is a metadata node."""
        return "Metadata Capture" in self.capabilities and not self.is_video_capture


def get_device_info(device_path: str) -> V4L2Device | None:
    """
    Query device information using v4l2-ctl.

    Returns V4L2Device or None if query fails.
    """
    try:
        result = subprocess.run(
            ["v4l2-ctl", "-d", device_path, "--info"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode != 0:
            return None

        # Parse output
        info = result.stdout
        name = ""
        driver = ""
        bus_info = ""
        capabilities = []

        for line in info.splitlines():
            line = line.strip()
            if line.startswith("Card type"):
                name = line.split(":", 1)[1].strip()
            elif line.startswith("Driver name"):
                driver = line.split(":", 1)[1].strip()
            elif line.startswith("Bus info"):
                bus_info = line.split(":", 1)[1].strip()
            elif ":" in line and line.split(":")[0].strip() == "":
                # Capability line (indented)
                cap = line.strip()
                if cap:
                    capabilities.append(cap)

        # Parse capabilities from the "Device Caps" section
        in_caps = False
        for line in info.splitlines():
            if "Device Caps" in line:
                in_caps = True
                continue
            if in_caps:
                if line.strip().startswith("Device Caps") or not line.strip():
                    break
                cap = line.strip()
                if cap and ":" not in cap:
                    capabilities.append(cap)

        return V4L2Device(
            path=device_path,
            name=name,
            driver=driver,
            bus_info=bus_info,
            capabilities=capabilities,
        )

    except (subprocess.TimeoutExpired, FileNotFoundError):
        return None


def enumerate_devices() -> list[V4L2Device]:
    """
    Enumerate all V4L2 video devices.

    Returns list of V4L2Device objects for video capture devices.
    """
    devices = []
    for path in sorted(Path("/dev").glob("video*")):
        device_path = str(path)
        info = get_device_info(device_path)
        if info and info.is_video_capture:
            devices.append(info)
    return devices


def enumerate_all_devices() -> list[V4L2Device]:
    """
    Enumerate ALL V4L2 devices including metadata nodes.

    Returns list of all V4L2Device objects.
    """
    devices = []
    for path in sorted(Path("/dev").glob("video*")):
        device_path = str(path)
        info = get_device_info(device_path)
        if info:
            devices.append(info)
    return devices


def main():
    print("=" * 70)
    print("V4L2 Device Enumeration")
    print("=" * 70)
    print()

    # Get all devices
    all_devices = enumerate_all_devices()

    print(f"Found {len(all_devices)} total V4L2 device(s):\n")

    # Group by bus_info to show which camera they belong to
    by_bus: dict[str, list[V4L2Device]] = {}
    for dev in all_devices:
        bus = dev.bus_info or "unknown"
        if bus not in by_bus:
            by_bus[bus] = []
        by_bus[bus].append(dev)

    for bus, devices in by_bus.items():
        print(f"Bus: {bus}")
        for dev in devices:
            node_type = "CAPTURE" if dev.is_video_capture else "metadata"
            print(f"  {dev.path:15} [{node_type:8}] {dev.name}")
        print()

    # Summary of capture-only devices
    capture_devices = [d for d in all_devices if d.is_video_capture]
    print("-" * 70)
    print(f"\nVideo capture devices only ({len(capture_devices)}):")
    for dev in capture_devices:
        print(f"  {dev.path}: {dev.name}")

    # Show how to use in code
    print()
    print("-" * 70)
    print("\nTo use in your code:")
    print("```python")
    print("from scripts.pyav_exploration.device_enumeration import enumerate_devices")
    print("for device in enumerate_devices():")
    print("    print(device.path, device.name)")
    print("```")


if __name__ == "__main__":
    main()
