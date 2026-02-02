#!/usr/bin/env python3
"""
Exploration Script 20: Device Capabilities Summary

PURPOSE:
Combine device enumeration and capability queries into a single utility.
This will inform the design of a DeviceCapabilities class for the main package.

USAGE:
    python 20_device_capabilities.py           # Show all devices
    python 20_device_capabilities.py /dev/video0   # Detailed info for one device
"""

from __future__ import annotations

import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class FrameRate:
    """A supported framerate."""

    fps: float

    def __str__(self) -> str:
        if self.fps == int(self.fps):
            return f"{int(self.fps)}"
        return f"{self.fps:.1f}"


@dataclass
class Resolution:
    """A supported resolution with framerates."""

    width: int
    height: int
    framerates: list[FrameRate] = field(default_factory=list)

    def __str__(self) -> str:
        fps_str = "/".join(str(f) for f in self.framerates)
        return f"{self.width}x{self.height} @ {fps_str} fps"


@dataclass
class PixelFormat:
    """A supported pixel format with resolutions."""

    name: str
    resolutions: list[Resolution] = field(default_factory=list)


@dataclass
class DeviceCapabilities:
    """Complete capability information for a V4L2 device."""

    path: str
    name: str
    driver: str
    bus_info: str
    is_capture: bool
    formats: list[PixelFormat] = field(default_factory=list)

    @property
    def supported_resolutions(self) -> set[tuple[int, int]]:
        """All unique resolutions across all formats."""
        resolutions = set()
        for fmt in self.formats:
            for res in fmt.resolutions:
                resolutions.add((res.width, res.height))
        return resolutions

    @property
    def max_resolution(self) -> tuple[int, int]:
        """Highest resolution (by pixel count)."""
        resolutions = self.supported_resolutions
        if not resolutions:
            return (0, 0)
        return max(resolutions, key=lambda r: r[0] * r[1])

    def get_format(self, name: str) -> PixelFormat | None:
        """Get a specific pixel format by name."""
        for fmt in self.formats:
            if fmt.name == name:
                return fmt
        return None

    def supports_format(self, name: str) -> bool:
        """Check if device supports a pixel format."""
        return self.get_format(name) is not None

    def supports_resolution(
        self, format_name: str, width: int, height: int
    ) -> bool:
        """Check if device supports a specific format + resolution."""
        fmt = self.get_format(format_name)
        if not fmt:
            return False
        for res in fmt.resolutions:
            if res.width == width and res.height == height:
                return True
        return False

    def get_framerates(
        self, format_name: str, width: int, height: int
    ) -> list[float]:
        """Get supported framerates for format + resolution."""
        fmt = self.get_format(format_name)
        if not fmt:
            return []
        for res in fmt.resolutions:
            if res.width == width and res.height == height:
                return [fr.fps for fr in res.framerates]
        return []


def query_device_info(device_path: str) -> tuple[str, str, str, bool]:
    """Query basic device info via v4l2-ctl --info."""
    try:
        result = subprocess.run(
            ["v4l2-ctl", "-d", device_path, "--info"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode != 0:
            return ("", "", "", False)

        name = ""
        driver = ""
        bus_info = ""
        is_capture = False

        for line in result.stdout.splitlines():
            line = line.strip()
            if line.startswith("Card type"):
                name = line.split(":", 1)[1].strip()
            elif line.startswith("Driver name"):
                driver = line.split(":", 1)[1].strip()
            elif line.startswith("Bus info"):
                bus_info = line.split(":", 1)[1].strip()
            elif "Video Capture" in line:
                is_capture = True

        return (name, driver, bus_info, is_capture)

    except (subprocess.TimeoutExpired, FileNotFoundError):
        return ("", "", "", False)


def query_formats(device_path: str) -> list[PixelFormat]:
    """Query supported formats via v4l2-ctl --list-formats-ext."""
    try:
        result = subprocess.run(
            ["v4l2-ctl", "-d", device_path, "--list-formats-ext"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode != 0:
            return []

        return _parse_formats(result.stdout)

    except (subprocess.TimeoutExpired, FileNotFoundError):
        return []


def _parse_formats(output: str) -> list[PixelFormat]:
    """Parse v4l2-ctl --list-formats-ext output."""
    import re

    formats: list[PixelFormat] = []
    current_format: PixelFormat | None = None
    current_resolution: Resolution | None = None

    format_pattern = re.compile(r"\[\d+\]:\s+'(\w+)'")
    size_pattern = re.compile(r"Size:\s+\w+\s+(\d+)x(\d+)")
    interval_pattern = re.compile(r"Interval:.*\((\d+\.?\d*)\s*fps\)")
    fraction_pattern = re.compile(r"Interval:\s+\w+\s+(\d+)/(\d+)")

    for line in output.splitlines():
        line = line.strip()

        # New format
        match = format_pattern.search(line)
        if match:
            if current_format and current_resolution:
                current_format.resolutions.append(current_resolution)
            if current_format:
                formats.append(current_format)
            current_format = PixelFormat(name=match.group(1))
            current_resolution = None
            continue

        # New resolution
        match = size_pattern.search(line)
        if match and current_format:
            if current_resolution:
                current_format.resolutions.append(current_resolution)
            current_resolution = Resolution(
                width=int(match.group(1)),
                height=int(match.group(2)),
            )
            continue

        # Framerate (fps form)
        match = interval_pattern.search(line)
        if match and current_resolution:
            fps = float(match.group(1))
            current_resolution.framerates.append(FrameRate(fps=fps))
            continue

        # Framerate (fraction form)
        match = fraction_pattern.search(line)
        if match and current_resolution:
            num = int(match.group(1))
            denom = int(match.group(2))
            fps = denom / num if num else 0
            current_resolution.framerates.append(FrameRate(fps=fps))
            continue

    # Don't forget last items
    if current_format and current_resolution:
        current_format.resolutions.append(current_resolution)
    if current_format:
        formats.append(current_format)

    return formats


def get_device_capabilities(device_path: str) -> DeviceCapabilities | None:
    """Get complete capabilities for a device."""
    name, driver, bus_info, is_capture = query_device_info(device_path)
    if not name:
        return None

    formats = query_formats(device_path) if is_capture else []

    return DeviceCapabilities(
        path=device_path,
        name=name,
        driver=driver,
        bus_info=bus_info,
        is_capture=is_capture,
        formats=formats,
    )


def enumerate_capture_devices() -> list[DeviceCapabilities]:
    """Enumerate all video capture devices with capabilities."""
    devices = []
    for path in sorted(Path("/dev").glob("video*")):
        caps = get_device_capabilities(str(path))
        # Only include if it's a capture device AND has formats
        # (metadata nodes don't have formats)
        if caps and caps.is_capture and caps.formats:
            devices.append(caps)
    return devices


def print_device_summary(caps: DeviceCapabilities) -> None:
    """Print a short summary of device capabilities."""
    print(f"{caps.path}: {caps.name}")
    print(f"  Driver: {caps.driver}")
    print(f"  Bus: {caps.bus_info}")
    if caps.formats:
        format_names = [f.name for f in caps.formats]
        print(f"  Formats: {', '.join(format_names)}")
        print(f"  Max resolution: {caps.max_resolution[0]}x{caps.max_resolution[1]}")


def print_device_details(caps: DeviceCapabilities) -> None:
    """Print detailed device capabilities."""
    print(f"Device: {caps.path}")
    print(f"Name: {caps.name}")
    print(f"Driver: {caps.driver}")
    print(f"Bus: {caps.bus_info}")
    print()

    for fmt in caps.formats:
        print(f"{fmt.name}:")
        for res in fmt.resolutions:
            fps_str = ", ".join(str(f) for f in res.framerates)
            print(f"  {res.width:4d}x{res.height:<4d} @ {fps_str} fps")
        print()

    # Check recommended config
    print("Recommended config (720p MJPEG @ 30fps):")
    if caps.supports_resolution("MJPG", 1280, 720):
        fps_list = caps.get_framerates("MJPG", 1280, 720)
        if 30 in fps_list or 30.0 in fps_list:
            print("  SUPPORTED")
        else:
            print(f"  Partial: 1280x720 available but not at 30fps")
            print(f"  Available fps: {fps_list}")
    else:
        print("  NOT SUPPORTED")
        print(f"  Available MJPG resolutions:")
        mjpg = caps.get_format("MJPG")
        if mjpg:
            for res in mjpg.resolutions:
                print(f"    {res}")
        else:
            print("    No MJPG format available")


def main():
    print("=" * 70)
    print("V4L2 Device Capabilities")
    print("=" * 70)
    print()

    if len(sys.argv) > 1:
        # Detailed info for specific device
        device_path = sys.argv[1]
        caps = get_device_capabilities(device_path)
        if caps:
            print_device_details(caps)
        else:
            print(f"Could not get capabilities for {device_path}")
            sys.exit(1)
    else:
        # Summary of all devices
        devices = enumerate_capture_devices()
        print(f"Found {len(devices)} capture device(s):\n")
        for caps in devices:
            print_device_summary(caps)
            print()


if __name__ == "__main__":
    main()
