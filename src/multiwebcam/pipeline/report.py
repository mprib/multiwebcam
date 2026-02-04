"""Monitoring reports for per-camera capture statistics."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class CameraStats:
    """Per-camera statistics for one monitoring window."""

    device_path: str
    frames_in_window: int  # Frames in measurement window
    measured_fps: float  # Actual frame rate from timestamps
    jitter_ms: float  # Stddev of inter-frame intervals
    queue_depth: int  # Current alignment queue depth
