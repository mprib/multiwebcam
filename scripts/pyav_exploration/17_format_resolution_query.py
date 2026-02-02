#!/usr/bin/env python3
"""
Exploration Script 17: Format/Resolution Query

PURPOSE:
For a given V4L2 device, list all supported pixel formats and resolutions.

BACKGROUND:
- Cameras support specific pixel formats (MJPG, YUYV, etc.)
- Each format may support different resolutions
- We need to query this upfront to offer valid options to users
- This supports the "fail-fast configuration" principle from CLAUDE.md

APPROACH:
Use v4l2-ctl --list-formats-ext to get complete format information.
"""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass


@dataclass
class Resolution:
    """A supported resolution."""

    width: int
    height: int

    def __str__(self) -> str:
        return f"{self.width}x{self.height}"


@dataclass
class FrameInterval:
    """A supported frame interval (fps)."""

    numerator: int  # Usually 1
    denominator: int  # The fps value (e.g., 30)

    @property
    def fps(self) -> float:
        return self.denominator / self.numerator if self.numerator else 0

    def __str__(self) -> str:
        return f"{self.fps:.0f}fps"


@dataclass
class FormatResolution:
    """A format + resolution combination with supported framerates."""

    pixel_format: str
    resolution: Resolution
    frame_intervals: list[FrameInterval]

    def __str__(self) -> str:
        fps_list = ", ".join(str(fi) for fi in self.frame_intervals)
        return f"{self.pixel_format} {self.resolution} @ {fps_list}"


def query_formats(device_path: str) -> list[FormatResolution]:
    """
    Query all supported format/resolution combinations for a device.

    Args:
        device_path: Path to V4L2 device (e.g., /dev/video0)

    Returns:
        List of FormatResolution objects with supported fps values
    """
    try:
        result = subprocess.run(
            ["v4l2-ctl", "-d", device_path, "--list-formats-ext"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode != 0:
            return []

        return _parse_formats_output(result.stdout)

    except (subprocess.TimeoutExpired, FileNotFoundError):
        return []


def _parse_formats_output(output: str) -> list[FormatResolution]:
    """Parse v4l2-ctl --list-formats-ext output."""
    results = []
    current_format = None
    current_resolution = None

    # Pattern for format line: [0]: 'MJPG' (Motion-JPEG, ...)
    format_pattern = re.compile(r"\[\d+\]:\s+'(\w+)'")

    # Pattern for size line: Size: Discrete 1920x1080
    size_pattern = re.compile(r"Size:\s+\w+\s+(\d+)x(\d+)")

    # Pattern for interval line: Interval: Discrete 0.033s (30.000 fps)
    interval_pattern = re.compile(r"Interval:.*\((\d+\.?\d*)\s*fps\)")

    # Alternative pattern for fraction intervals: Interval: Discrete 1/30
    fraction_pattern = re.compile(r"Interval:\s+\w+\s+(\d+)/(\d+)")

    intervals: list[FrameInterval] = []

    for line in output.splitlines():
        line = line.strip()

        # Check for new format
        match = format_pattern.search(line)
        if match:
            current_format = match.group(1)
            current_resolution = None
            intervals = []
            continue

        # Check for resolution
        match = size_pattern.search(line)
        if match and current_format:
            # Save previous resolution if we have one
            if current_resolution and intervals:
                results.append(
                    FormatResolution(
                        pixel_format=current_format,
                        resolution=current_resolution,
                        frame_intervals=intervals.copy(),
                    )
                )
            width = int(match.group(1))
            height = int(match.group(2))
            current_resolution = Resolution(width, height)
            intervals = []
            continue

        # Check for fps interval
        match = interval_pattern.search(line)
        if match and current_resolution:
            fps = float(match.group(1))
            intervals.append(FrameInterval(numerator=1, denominator=int(fps)))
            continue

        # Check for fraction interval
        match = fraction_pattern.search(line)
        if match and current_resolution:
            num = int(match.group(1))
            denom = int(match.group(2))
            intervals.append(FrameInterval(numerator=num, denominator=denom))
            continue

    # Don't forget the last resolution
    if current_format and current_resolution and intervals:
        results.append(
            FormatResolution(
                pixel_format=current_format,
                resolution=current_resolution,
                frame_intervals=intervals.copy(),
            )
        )

    return results


def get_formats_by_pixel_format(formats: list[FormatResolution]) -> dict[str, list[FormatResolution]]:
    """Group formats by pixel format."""
    by_format: dict[str, list[FormatResolution]] = {}
    for fr in formats:
        if fr.pixel_format not in by_format:
            by_format[fr.pixel_format] = []
        by_format[fr.pixel_format].append(fr)
    return by_format


def get_supported_resolutions(
    formats: list[FormatResolution], pixel_format: str
) -> list[Resolution]:
    """Get resolutions supported for a specific pixel format."""
    return [
        fr.resolution
        for fr in formats
        if fr.pixel_format == pixel_format
    ]


def get_supported_fps(
    formats: list[FormatResolution], pixel_format: str, resolution: Resolution
) -> list[float]:
    """Get fps values supported for a specific format and resolution."""
    for fr in formats:
        if fr.pixel_format == pixel_format and fr.resolution == resolution:
            return [fi.fps for fi in fr.frame_intervals]
    return []


def main():
    import sys

    print("=" * 70)
    print("V4L2 Format/Resolution Query")
    print("=" * 70)
    print()

    # Use provided device or default
    if len(sys.argv) > 1:
        device_path = sys.argv[1]
    else:
        # Default to first capture device
        from scripts.pyav_exploration import _16_device_enumeration as enum_mod

        # Import the enumeration module
        sys.path.insert(0, str(__file__).rsplit("/", 1)[0])
        exec(open("scripts/pyav_exploration/16_device_enumeration.py").read())
        devices = enumerate_devices()  # type: ignore  # noqa: F821
        if not devices:
            print("No video capture devices found!")
            sys.exit(1)
        device_path = devices[0].path

    print(f"Device: {device_path}")
    print()

    formats = query_formats(device_path)
    if not formats:
        print("No formats found (device may not support format enumeration)")
        sys.exit(1)

    # Group by pixel format
    by_format = get_formats_by_pixel_format(formats)

    for pixel_format, format_list in sorted(by_format.items()):
        print(f"{pixel_format}:")
        for fr in format_list:
            fps_str = ", ".join(f"{fi.fps:.0f}" for fi in fr.frame_intervals)
            print(f"  {fr.resolution.width:4d}x{fr.resolution.height:<4d} @ {fps_str} fps")
        print()

    # Summary
    print("-" * 70)
    print("\nSummary:")
    print(f"  Pixel formats: {', '.join(sorted(by_format.keys()))}")
    print(f"  Total resolution/fps combinations: {len(formats)}")

    # Show recommended settings
    print()
    print("Recommended for multiwebcam (720p MJPEG):")
    for fr in formats:
        if fr.pixel_format == "MJPG" and fr.resolution.height == 720:
            fps_30 = any(fi.fps >= 30 for fi in fr.frame_intervals)
            if fps_30:
                print(f"  {fr.resolution} @ 30fps - SUPPORTED")
            else:
                max_fps = max(fi.fps for fi in fr.frame_intervals)
                print(f"  {fr.resolution} @ {max_fps:.0f}fps - Available (no 30fps)")


if __name__ == "__main__":
    main()
