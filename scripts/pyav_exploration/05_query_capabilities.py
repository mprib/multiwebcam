#!/usr/bin/env python3
"""
Script 05: Query Capabilities

Discover supported resolutions, framerates, and pixel formats per camera.
Uses v4l2-ctl --list-formats-ext for reliable capability enumeration.

Usage:
    uv run python scripts/pyav_exploration/05_query_capabilities.py [device]
"""

import re
import subprocess
import sys
from dataclasses import dataclass


@dataclass
class FrameSize:
    """A supported frame size with its available framerates."""

    width: int
    height: int
    framerates: list[float]

    def __str__(self) -> str:
        fps_str = ", ".join(f"{fps:.0f}" for fps in self.framerates)
        return f"{self.width}x{self.height} @ {fps_str} fps"


@dataclass
class PixelFormat:
    """A supported pixel format with its available frame sizes."""

    name: str
    fourcc: str
    sizes: list[FrameSize]


def parse_formats_ext(output: str) -> list[PixelFormat]:
    """
    Parse output from v4l2-ctl --list-formats-ext.

    Example output:
        ioctl: VIDIOC_ENUM_FMT
            Type: Video Capture

            [0]: 'YUYV' (YUYV 4:2:2)
                Size: Discrete 640x480
                    Interval: Discrete 0.033s (30.000 fps)
                    Interval: Discrete 0.042s (24.000 fps)
                Size: Discrete 1280x720
                    Interval: Discrete 0.100s (10.000 fps)
            [1]: 'MJPG' (Motion-JPEG, compressed)
                Size: Discrete 640x480
                    Interval: Discrete 0.033s (30.000 fps)
    """
    formats = []
    current_format = None
    current_size = None

    # Patterns
    format_pattern = re.compile(r"\[\d+\]: '(\w+)' \(([^)]+)\)")
    size_pattern = re.compile(r"Size: Discrete (\d+)x(\d+)")
    fps_pattern = re.compile(r"\((\d+\.?\d*) fps\)")
    # Some cameras report stepwise sizes
    stepwise_pattern = re.compile(r"Size: Stepwise (\d+)x(\d+) - (\d+)x(\d+)")

    for line in output.splitlines():
        line = line.strip()

        # New format block
        format_match = format_pattern.search(line)
        if format_match:
            if current_format and current_size:
                current_format.sizes.append(current_size)
            if current_format:
                formats.append(current_format)

            fourcc = format_match.group(1)
            description = format_match.group(2)
            current_format = PixelFormat(name=description, fourcc=fourcc, sizes=[])
            current_size = None
            continue

        # New size block
        size_match = size_pattern.search(line)
        if size_match and current_format:
            if current_size:
                current_format.sizes.append(current_size)
            width = int(size_match.group(1))
            height = int(size_match.group(2))
            current_size = FrameSize(width=width, height=height, framerates=[])
            continue

        # Stepwise size (some cameras report this instead of discrete)
        stepwise_match = stepwise_pattern.search(line)
        if stepwise_match and current_format:
            if current_size:
                current_format.sizes.append(current_size)
            # For stepwise, just note the max size
            max_width = int(stepwise_match.group(3))
            max_height = int(stepwise_match.group(4))
            current_size = FrameSize(width=max_width, height=max_height, framerates=[])
            continue

        # Framerate
        fps_match = fps_pattern.search(line)
        if fps_match and current_size:
            fps = float(fps_match.group(1))
            current_size.framerates.append(fps)

    # Don't forget last entries
    if current_format and current_size:
        current_format.sizes.append(current_size)
    if current_format:
        formats.append(current_format)

    return formats


def query_capabilities(device: str) -> list[PixelFormat]:
    """
    Query device capabilities using v4l2-ctl.

    Args:
        device: Path to V4L2 device (e.g., /dev/video0)

    Returns:
        List of supported pixel formats with their resolutions and framerates
    """
    result = subprocess.run(
        ["v4l2-ctl", "-d", device, "--list-formats-ext"],
        capture_output=True,
        text=True,
        timeout=5,
    )

    if result.returncode != 0:
        print(f"Error querying {device}:")
        print(result.stderr)
        return []

    return parse_formats_ext(result.stdout)


def get_device_name(device: str) -> str:
    """Get human-readable device name from v4l2-ctl."""
    try:
        result = subprocess.run(
            ["v4l2-ctl", "-d", device, "--info"],
            capture_output=True,
            text=True,
            timeout=2,
        )
        for line in result.stdout.splitlines():
            if "Card type" in line:
                return line.split(":", 1)[1].strip()
    except (subprocess.TimeoutExpired, subprocess.CalledProcessError):
        pass
    return "Unknown"


def print_capabilities(device: str, formats: list[PixelFormat]) -> None:
    """Print formatted capability report."""
    device_name = get_device_name(device)

    print(f"\nDevice: {device} ({device_name})")
    print("-" * 60)

    if not formats:
        print("  No formats reported (device may not support capture)")
        return

    for fmt in formats:
        print(f"\n  {fmt.fourcc} ({fmt.name}):")
        for size in fmt.sizes:
            if size.framerates:
                print(f"    {size}")
            else:
                # Stepwise or no fps info
                print(f"    {size.width}x{size.height} (fps not reported)")

    # Recommendations
    print("\n" + "-" * 60)
    print("Recommendations:")

    # Find MJPEG if available (better for high-res)
    mjpeg = next((f for f in formats if f.fourcc == "MJPG"), None)
    yuyv = next((f for f in formats if f.fourcc in ("YUYV", "YUY2")), None)

    if mjpeg and mjpeg.sizes:
        best_mjpeg = max(mjpeg.sizes, key=lambda s: s.width * s.height)
        best_fps = max(best_mjpeg.framerates) if best_mjpeg.framerates else 0
        print(f"  High resolution: MJPG {best_mjpeg.width}x{best_mjpeg.height} @ {best_fps:.0f}fps")
        print("    (MJPG uses less USB bandwidth, allows higher resolutions)")

    if yuyv and yuyv.sizes:
        # Find highest res with 30fps
        candidates = [s for s in yuyv.sizes if 30 in [int(f) for f in s.framerates]]
        if candidates:
            best_yuyv = max(candidates, key=lambda s: s.width * s.height)
            print(f"  Low latency: YUYV {best_yuyv.width}x{best_yuyv.height} @ 30fps")
            print("    (YUYV has no compression, slightly lower latency)")


def main():
    device = sys.argv[1] if len(sys.argv) > 1 else "/dev/video4"

    print("=" * 70)
    print("PyAV Exploration - Script 05: Query Capabilities")
    print("=" * 70)

    # Check v4l2-ctl is available
    try:
        subprocess.run(["v4l2-ctl", "--version"], capture_output=True, check=True, timeout=2)
    except FileNotFoundError:
        print("\nError: v4l2-ctl not found")
        print("Install with: sudo apt install v4l-utils")
        sys.exit(1)

    formats = query_capabilities(device)
    print_capabilities(device, formats)

    print("\n" + "=" * 70)
    print("Usage Notes:")
    print("=" * 70)
    print("""
To use these settings with PyAV:

    options = {
        'video_size': '1280x720',
        'framerate': '30',
        'input_format': 'mjpeg',  # or 'yuyv422' for YUYV
    }
    container = av.open('/dev/video0', format='v4l2', options=options)

MJPG vs YUYV trade-offs:
  - MJPG: Higher resolutions, lower bandwidth, minimal CPU to decode
  - YUYV: No compression artifacts, but limited to lower resolutions/fps

Next: Use script 06 to verify setting resolutions actually works.
""")


if __name__ == "__main__":
    main()
