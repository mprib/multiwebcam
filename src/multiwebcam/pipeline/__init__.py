"""
Multi-camera capture pipeline with triple-queue architecture.

This module implements the CSP (Communicating Sequential Processes) pattern
for concurrent frame capture with three output queues per camera:

    FrameSource --> FrameProducer --> Display Queue (maxsize=1, latest frame)
                                  --> Recording Queue (blocking, preserve all)
                                  --> Alignment Queue (blocking, for monitoring)

The AlignmentMonitor drains alignment queues and provides:
- Per-camera stats: fps, jitter from actual frame timestamps
- Alignment quality: cluster completeness, temporal spread

Example:
    from multiwebcam.sources import FrameSource
    from multiwebcam.pipeline import CaptureSession

    sources = [
        FrameSource("/dev/video0"),
        FrameSource("/dev/video2"),
    ]

    session = CaptureSession(sources)
    session.start()

    # Get latest frames for display
    frames = session.get_latest_frames()
    for device_path, packet in frames.items():
        if packet is not None:
            print(f"{device_path}: frame {packet.frame_index}")

    # Check per-camera stats (fps, jitter)
    stats = session.get_camera_stats()
    if stats:
        for device_path, stat in stats.items():
            print(f"{device_path}: {stat.measured_fps:.1f} fps, {stat.jitter_ms:.1f}ms jitter")

    # Check alignment quality
    alignment = session.get_alignment_stats()
    if alignment:
        print(f"Complete clusters: {alignment.complete_cluster_pct:.1f}%")
        print(f"Mean spread: {alignment.mean_spread_ms:.1f}ms")

    session.stop()
"""

from multiwebcam.pipeline.alignment import AlignmentMonitor, AlignmentStats
from multiwebcam.pipeline.producer import FrameProducer, QueueBundle
from multiwebcam.pipeline.report import CameraStats
from multiwebcam.pipeline.session import CaptureSession, CaptureSessionError
from multiwebcam.recording.recorder import RecordingResult

__all__ = [
    "AlignmentMonitor",
    "AlignmentStats",
    "CameraStats",
    "CaptureSession",
    "CaptureSessionError",
    "FrameProducer",
    "QueueBundle",
    "RecordingResult",
]
