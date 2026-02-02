"""V4L2 device discovery and capability query."""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

from .config import FrameSourceConfig

# V4L2 fourcc codes to FFmpeg format names
_V4L2_TO_FFMPEG: dict[str, str] = {
    "MJPG": "mjpeg",
    "YUYV": "yuyv422",
    "NV12": "nv12",
    "H264": "h264",
}

_FFMPEG_TO_V4L2: dict[str, str] = {v: k for k, v in _V4L2_TO_FFMPEG.items()}


def _normalize_format(fmt: str) -> str:
    """Normalize pixel format to lowercase FFmpeg name."""
    upper = fmt.upper()
    if upper in _V4L2_TO_FFMPEG:
        return _V4L2_TO_FFMPEG[upper]
    return fmt.lower()


@dataclass(frozen=True, slots=True)
class VideoMode:
    """A specific capture mode: format + resolution + framerate."""

    pixel_format: str  # e.g., "MJPG", "YUYV"
    width: int
    height: int
    fps: float

    def __str__(self) -> str:
        return f"{self.pixel_format} {self.width}x{self.height}@{self.fps:.0f}fps"


@dataclass(frozen=True, slots=True)
class FrameSourceOptions:
    """Available options for a V4L2 capture device.

    Queried via v4l2-ctl before opening the device. Use this to:
    - Check what modes a device supports
    - Validate a config before creating a FrameSource
    - Get a suggested config for immediate preview
    """

    path: str  # e.g., "/dev/video0"
    name: str  # e.g., "HD Pro Webcam C920"
    driver: str  # e.g., "uvcvideo"
    bus_info: str  # e.g., "usb-0000:00:14.0-2"
    modes: tuple[VideoMode, ...]

    def supports(self, config: FrameSourceConfig) -> bool:
        """Check if this device supports the given configuration."""
        w, h = config.resolution
        config_fmt = _normalize_format(config.pixel_format)
        # Allow small fps tolerance (some cameras report 29.97 vs 30)
        return any(
            _normalize_format(mode.pixel_format) == config_fmt
            and mode.width == w
            and mode.height == h
            and abs(mode.fps - config.fps) < 1.0
            for mode in self.modes
        )

    def suggested_config(self) -> FrameSourceConfig:
        """Pick a sensible config for immediate use.

        Heuristics:
        - Prefer MJPEG (lower bandwidth than YUYV)
        - Prefer 720p if available
        - Prefer 30fps if available
        - Fall back to whatever is available
        """
        if not self.modes:
            # No modes available, return default and let it fail at open time
            return FrameSourceConfig()

        # Score each mode: higher is better
        def score(mode: VideoMode) -> tuple[int, int, int, int]:
            format_score = 2 if mode.pixel_format == "MJPG" else 1
            # Prefer 720p, then 1080p, then other resolutions by size
            if mode.height == 720:
                res_score = 10_000_000
            elif mode.height == 1080:
                res_score = 9_000_000
            else:
                res_score = mode.width * mode.height
            # Prefer 30fps, then higher, then lower
            if abs(mode.fps - 30) < 1:
                fps_score = 1000
            else:
                fps_score = int(mode.fps)
            return (format_score, res_score, fps_score, mode.width)

        best = max(self.modes, key=score)
        return FrameSourceConfig(
            resolution=(best.width, best.height),
            fps=int(best.fps),
            pixel_format=best.pixel_format.lower(),
        )

    def formats(self) -> set[str]:
        """All supported pixel formats."""
        return {mode.pixel_format for mode in self.modes}

    def resolutions(self, pixel_format: str) -> set[tuple[int, int]]:
        """Resolutions available for a pixel format."""
        fmt = _normalize_format(pixel_format)
        return {
            (mode.width, mode.height)
            for mode in self.modes
            if _normalize_format(mode.pixel_format) == fmt
        }

    def framerates(self, pixel_format: str, width: int, height: int) -> list[float]:
        """Framerates available for a format + resolution."""
        fmt = _normalize_format(pixel_format)
        return sorted(
            mode.fps
            for mode in self.modes
            if _normalize_format(mode.pixel_format) == fmt
            and mode.width == width
            and mode.height == height
        )

    @property
    def max_resolution(self) -> tuple[int, int]:
        """Highest resolution by pixel count."""
        if not self.modes:
            return (0, 0)
        best = max(self.modes, key=lambda m: m.width * m.height)
        return (best.width, best.height)


def discover_frame_sources() -> list[FrameSourceOptions]:
    """Discover all V4L2 video capture devices.

    Queries each /dev/video* device, filters out metadata nodes,
    and returns options with supported modes.

    Requires v4l2-ctl to be installed (from v4l-utils package).

    Returns:
        List of FrameSourceOptions for each capture device.

    Raises:
        FileNotFoundError: If v4l2-ctl is not installed.
    """
    devices = []
    for path in sorted(Path("/dev").glob("video*")):
        options = get_frame_source_options(str(path))
        if options is not None:
            devices.append(options)
    return devices


def get_frame_source_options(device_path: str) -> FrameSourceOptions | None:
    """Get options for a specific device.

    Args:
        device_path: Path to V4L2 device (e.g., "/dev/video0")

    Returns:
        FrameSourceOptions if device is a valid capture device, None otherwise.
    """
    info = _query_device_info(device_path)
    if info is None:
        return None

    name, driver, bus_info, is_capture = info
    if not is_capture:
        return None

    modes = _query_modes(device_path)
    if not modes:
        # No modes means it's likely a metadata node
        return None

    return FrameSourceOptions(
        path=device_path,
        name=name,
        driver=driver,
        bus_info=bus_info,
        modes=tuple(modes),
    )


def _query_device_info(device_path: str) -> tuple[str, str, str, bool] | None:
    """Query basic device info via v4l2-ctl --info."""
    try:
        result = subprocess.run(
            ["v4l2-ctl", "-d", device_path, "--info"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode != 0:
            return None

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

    except subprocess.TimeoutExpired:
        return None
    except FileNotFoundError as e:
        raise FileNotFoundError(
            "v4l2-ctl not found. Install v4l-utils: sudo apt install v4l-utils"
        ) from e


def _query_modes(device_path: str) -> list[VideoMode]:
    """Query supported modes via v4l2-ctl --list-formats-ext."""
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


def _parse_formats_output(output: str) -> list[VideoMode]:
    """Parse v4l2-ctl --list-formats-ext output into VideoMode list."""
    modes: list[VideoMode] = []
    current_format: str | None = None
    current_width: int | None = None
    current_height: int | None = None

    # Pattern for format line: [0]: 'MJPG' (Motion-JPEG, ...)
    format_pattern = re.compile(r"\[\d+\]:\s+'(\w+)'")

    # Pattern for size line: Size: Discrete 1920x1080
    size_pattern = re.compile(r"Size:\s+\w+\s+(\d+)x(\d+)")

    # Pattern for interval line: Interval: Discrete 0.033s (30.000 fps)
    interval_pattern = re.compile(r"Interval:.*\((\d+\.?\d*)\s*fps\)")

    # Alternative pattern for fraction intervals: Interval: Discrete 1/30
    fraction_pattern = re.compile(r"Interval:\s+\w+\s+(\d+)/(\d+)")

    for line in output.splitlines():
        line = line.strip()

        # New format
        match = format_pattern.search(line)
        if match:
            current_format = match.group(1)
            current_width = None
            current_height = None
            continue

        # New resolution
        match = size_pattern.search(line)
        if match and current_format:
            current_width = int(match.group(1))
            current_height = int(match.group(2))
            continue

        # Framerate (fps form)
        match = interval_pattern.search(line)
        if match and current_format and current_width and current_height:
            fps = float(match.group(1))
            modes.append(VideoMode(
                pixel_format=current_format,
                width=current_width,
                height=current_height,
                fps=fps,
            ))
            continue

        # Framerate (fraction form)
        match = fraction_pattern.search(line)
        if match and current_format and current_width and current_height:
            num = int(match.group(1))
            denom = int(match.group(2))
            fps = denom / num if num else 0
            modes.append(VideoMode(
                pixel_format=current_format,
                width=current_width,
                height=current_height,
                fps=fps,
            ))
            continue

    return modes
