"""
PyAV-based video capture sources.

This module provides V4L2 device capture using PyAV/FFmpeg,
replacing OpenCV's buggy VideoCapture.

Example:
    from multiwebcam.sources import (
        discover_frame_sources,
        FrameSource,
    )

    # Discover available cameras
    for options in discover_frame_sources():
        print(f"{options.path}: {options.model}")

    # Get suggested config and start capture
    options = discover_frame_sources()[0]
    config = options.suggested_config()

    with FrameSource(options.path, config) as source:
        for packet in source:
            cv2.imshow("frame", packet.frame)
            if cv2.waitKey(1) == ord('q'):
                break
"""

from multiwebcam.sources.config import FrameSourceConfig, FrameSourceStatus
from multiwebcam.sources.controls import V4L2Control, get_control_value, parse_controls, query_controls, set_control
from multiwebcam.sources.conversion import frame_to_bgr
from multiwebcam.sources.device import FrameSource, FrameSourceError
from multiwebcam.sources.discovery import (
    FrameSourceOptions,
    VideoMode,
    discover_frame_sources,
    get_frame_source_options,
)
from multiwebcam.sources.frame_packet import FramePacket

__all__ = [
    "FramePacket",
    "FrameSource",
    "FrameSourceConfig",
    "FrameSourceError",
    "FrameSourceOptions",
    "FrameSourceStatus",
    "V4L2Control",
    "VideoMode",
    "discover_frame_sources",
    "frame_to_bgr",
    "get_control_value",
    "get_frame_source_options",
    "parse_controls",
    "query_controls",
    "set_control",
]
