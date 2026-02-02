"""
PyAV-based video capture sources.

This module provides V4L2 device capture using PyAV/FFmpeg,
replacing OpenCV's buggy VideoCapture.

Example:
    from multiwebcam.sources import FrameSource, FrameSourceConfig

    config = FrameSourceConfig(resolution=(1920, 1080), fps=30)

    with FrameSource("/dev/video0", config) as source:
        for packet in source:
            cv2.imshow("frame", packet.frame)
            if cv2.waitKey(1) == ord('q'):
                break
"""

from .config import FrameSourceConfig, FrameSourceStatus
from .conversion import frame_to_bgr
from .device import FrameSource, FrameSourceError
from .frame_packet import FramePacket

__all__ = [
    "FramePacket",
    "FrameSource",
    "FrameSourceConfig",
    "FrameSourceError",
    "FrameSourceStatus",
    "frame_to_bgr",
]
