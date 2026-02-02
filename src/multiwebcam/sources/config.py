"""FrameSource configuration and status types."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal


@dataclass(frozen=True, slots=True)
class FrameSourceConfig:
    """
    Configuration for a FrameSource.

    All fields have sensible defaults. Construct with overrides as needed:
        config = FrameSourceConfig(resolution=(1920, 1080), fps=30)

    The v4l2_options dict passes through to FFmpeg's v4l2 input.
    Common use: {"exposure_dynamic_framerate": "0"} to disable auto-fps.
    """

    resolution: tuple[int, int] = (1280, 720)
    fps: int = 30
    pixel_format: str = "mjpeg"
    warmup_frames: int = 5
    v4l2_options: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class FrameSourceStatus:
    """
    Status information returned when a FrameSource starts successfully.

    This captures what the device actually negotiated, which may differ
    from what was requested (some cameras silently fall back to nearest
    supported mode).
    """

    device_path: str
    resolution: tuple[int, int]
    actual_fps: float
    first_pts_seconds: float | None
    timestamp_source: Literal["pts", "wall_clock"]
    warmup_frames_discarded: int
