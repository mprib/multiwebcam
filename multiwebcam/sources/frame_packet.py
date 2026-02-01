"""Immutable frame packet for pipeline transport."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    import numpy as np


@dataclass(frozen=True, slots=True)
class FramePacket:
    """
    A single captured frame with metadata.

    This is the unit of data flowing through the capture pipeline.
    The frame array is a copy (PyAV reuses buffers internally).

    Attributes:
        device_path: Full V4L2 device path (e.g., "/dev/video0")
        device_id: Numeric ID extracted from path (e.g., 0)
        frame_index: Sequential frame number from this source (0-based)
        frame_time: Timestamp in seconds (PTS or wall-clock, see timestamp_source)
        timestamp_source: Which clock provided frame_time
        frame: BGR image as numpy array, shape (H, W, 3), dtype uint8
        fps: Rolling average fps (measured, not requested)
    """

    device_path: str
    device_id: int
    frame_index: int
    frame_time: float
    timestamp_source: Literal["pts", "wall_clock"]
    frame: "np.ndarray"
    fps: float
