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

from multiwebcam.pipeline.aligner import FrameAligner
from multiwebcam.pipeline.cluster import FrameCluster
from multiwebcam.pipeline.producer import FrameProducer
from multiwebcam.pipeline.report import AlignmentReport, CameraStats
from multiwebcam.pipeline.session import CaptureSession, CaptureSessionError
from multiwebcam.pipeline.signals import ShutdownSignal, StartSignal, StopSignal

__all__ = [
    "AlignmentReport",
    "CameraStats",
    "CaptureSession",
    "CaptureSessionError",
    "FrameAligner",
    "FrameCluster",
    "FrameProducer",
    "ShutdownSignal",
    "StartSignal",
    "StopSignal",
]
