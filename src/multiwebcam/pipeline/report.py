"""Monitoring reports for frame alignment system health."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class CameraStats:
    """Per-camera statistics for one reporting window."""

    device_path: str
    frames_received: int  # Frames pulled from queue this window
    clusters_participated: int  # Clusters where this camera had a frame
    cluster_skip_rate: float  # Fraction of clusters with no frame (0.0 = perfect)
    queue_depth: int  # Current input queue depth
    measured_fps: float  # Actual frame rate this window


@dataclass(frozen=True, slots=True)
class AlignmentReport:
    """
    Periodic snapshot of alignment system health.

    Provides a view into how well the multi-camera alignment is performing:
    - Are all cameras keeping up?
    - How often do we get complete clusters (all cameras present)?
    - Is memory pressure building (queue depths, frame storage)?

    Reports are emitted at fixed intervals (typically 2s) during capture.
    """

    window_start: float  # Start time (perf_counter epoch)
    window_end: float  # End time (perf_counter epoch)
    window_duration: float  # window_end - window_start
    clusters_emitted: int  # Total clusters this window
    cluster_rate: float  # Clusters per second
    complete_cluster_count: int  # Clusters where ALL cameras participated
    complete_cluster_rate: float  # Fraction of complete clusters (0.0-1.0)
    frame_storage_count: int  # Frames buffered in aligner (memory proxy)
    camera_stats: dict[str, CameraStats]  # Per-camera breakdown

    @property
    def camera_count(self) -> int:
        """Number of cameras being aligned."""
        return len(self.camera_stats)

    @property
    def is_healthy(self) -> bool:
        """
        True if all cameras have skip rate < 0.2 (>80% participation).

        A healthy system means cameras are temporally aligned and producing
        frames at similar rates. High skip rates indicate one camera is
        lagging or experiencing drops.
        """
        if not self.camera_stats:
            return False
        return all(cs.cluster_skip_rate < 0.2 for cs in self.camera_stats.values())
