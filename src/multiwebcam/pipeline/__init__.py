"""
Multi-camera capture pipeline with temporal alignment.

This module implements the CSP (Communicating Sequential Processes) pattern
for concurrent frame capture:

    FrameSource₀ ──► FrameProducer₀ ──► Queue ──┐
                                                ├──► FrameAligner ──► Clusters
    FrameSource₁ ──► FrameProducer₁ ──► Queue ──┘

Example:
    from multiwebcam.sources import FrameSource
    from multiwebcam.pipeline import CaptureSession

    sources = [
        FrameSource("/dev/video0"),
        FrameSource("/dev/video2"),
    ]

    with CaptureSession(sources) as session:
        for cluster in session.clusters():
            for device_path, packet in cluster.frames.items():
                print(f"{device_path}: frame {packet.frame_index}")
"""

from .aligner import FrameAligner
from .cluster import FrameCluster
from .producer import FrameProducer
from .session import CaptureSession, CaptureSessionError
from .signals import ShutdownSignal, StartSignal, StopSignal

__all__ = [
    "CaptureSession",
    "CaptureSessionError",
    "FrameAligner",
    "FrameCluster",
    "FrameProducer",
    "ShutdownSignal",
    "StartSignal",
    "StopSignal",
]
