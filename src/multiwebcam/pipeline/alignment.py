"""Lightweight alignment monitoring for multi-camera capture quality."""

from __future__ import annotations

import logging
import time
from collections import deque
from dataclasses import dataclass
from queue import Empty, Queue
from threading import Event, Lock, Thread

from multiwebcam.pipeline.report import CameraStats
from multiwebcam.sources.frame_packet import FramePacket

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class FrameMetadata:
    """Lightweight frame metadata (no image array)."""

    device_path: str
    frame_index: int
    frame_time: float


@dataclass(frozen=True, slots=True)
class Cluster:
    """
    Frames collected before duplicate camera appeared.

    A cluster represents a set of frames that were received in temporal
    proximity, determined by the collect-until-duplicate algorithm.
    """

    frames: list[FrameMetadata]
    window_duration: float  # Time from first frame to duplicate
    completeness: float  # Fraction of expected cameras present

    @property
    def spread_ms(self) -> float:
        """Temporal spread: max(pts) - min(pts) in milliseconds."""
        if len(self.frames) < 2:
            return 0.0
        times = [f.frame_time for f in self.frames]
        return (max(times) - min(times)) * 1000


@dataclass(frozen=True, slots=True)
class AlignmentStats:
    """Multi-camera alignment quality over measurement window."""

    complete_cluster_pct: float  # 0-100, % of clusters with all cameras
    mean_spread_ms: float  # Average temporal spread within clusters
    max_spread_ms: float  # Worst-case spread (for flagging issues)
    mean_window_duration_ms: float  # Average time to collect complete cluster
    total_clusters: int  # Clusters in measurement window


class AlignmentMonitor:
    """
    Monitors multi-camera alignment quality using collect-until-duplicate.

    Drains alignment queues, builds clusters, computes statistics.
    Does NOT produce aligned output - purely observational.

    Usage:
        alignment_queues = {path: queue for path, queue in ...}
        monitor = AlignmentMonitor(
            alignment_queues,
            expected_cameras=len(sources),
            window_seconds=3.0,
        )
        monitor.start()

        # Later...
        stats = monitor.get_alignment_stats()
        camera_stats = monitor.get_camera_stats()

        monitor.stop()
    """

    def __init__(
        self,
        alignment_queues: dict[str, Queue[FramePacket]],
        expected_cameras: int,
        window_seconds: float = 3.0,
    ):
        """
        Initialize an AlignmentMonitor.

        Args:
            alignment_queues: Dict mapping device_path to alignment queue
            expected_cameras: Number of cameras to expect in complete clusters
            window_seconds: Rolling window duration for statistics
        """
        self._queues = alignment_queues
        self._expected_cameras = expected_cameras
        self._window_seconds = window_seconds

        # Rolling window of recent clusters
        self._recent_clusters: deque[Cluster] = deque()

        # Per-camera frame tracking for jitter calculation
        self._camera_frames: dict[str, deque[FrameMetadata]] = {
            path: deque() for path in alignment_queues.keys()
        }

        # Lock for thread-safe access to shared data
        self._lock = Lock()

        self._shutdown_event = Event()
        self._thread: Thread | None = None
        self._running = False

    def start(self) -> None:
        """Start the monitoring thread."""
        if self._running:
            logger.warning("AlignmentMonitor already running")
            return

        self._shutdown_event.clear()
        self._thread = Thread(target=self._run, daemon=True)
        self._running = True
        self._thread.start()
        logger.info("AlignmentMonitor started")

    def stop(self, timeout: float = 5.0) -> None:
        """
        Stop the monitoring thread.

        Args:
            timeout: Maximum time to wait for thread to join (seconds)
        """
        if not self._running:
            return

        logger.info("Stopping AlignmentMonitor")
        self._shutdown_event.set()

        if self._thread is not None:
            self._thread.join(timeout=timeout)
            if self._thread.is_alive():
                logger.warning(f"AlignmentMonitor thread did not terminate within {timeout}s")

        self._running = False
        logger.info("AlignmentMonitor stopped")

    def _run(self) -> None:
        """Background thread: drain queues, build clusters, update stats."""
        try:
            while not self._shutdown_event.is_set():
                # Drain all alignment queues
                all_frames = self._drain_queues()

                # Build clusters using collect-until-duplicate
                new_clusters = self._build_clusters(all_frames)

                # Update rolling window (protected by lock)
                with self._lock:
                    self._recent_clusters.extend(new_clusters)
                    self._evict_old_clusters()
                    self._update_camera_frames(all_frames)

                time.sleep(0.1)  # Avoid busy loop

        except Exception as e:
            logger.error(f"AlignmentMonitor error: {e}", exc_info=True)
        finally:
            logger.debug("AlignmentMonitor thread exiting")

    def _drain_queues(self) -> list[FrameMetadata]:
        """Drain alignment queues, extract metadata only."""
        all_metadata = []
        for device_path, queue in self._queues.items():
            while True:
                try:
                    packet = queue.get_nowait()
                    metadata = FrameMetadata(
                        device_path=packet.device_path,
                        frame_index=packet.frame_index,
                        frame_time=packet.frame_time,
                    )
                    all_metadata.append(metadata)
                except Empty:
                    break

        # Sort by timestamp for cluster algorithm
        all_metadata.sort(key=lambda m: m.frame_time)
        return all_metadata

    def _build_clusters(self, frames: list[FrameMetadata]) -> list[Cluster]:
        """
        Collect frames until duplicate camera appears.

        Algorithm:
        - Start with empty window
        - Add frames until we see a camera twice
        - Emit cluster, start new window with duplicate frame

        Args:
            frames: Sorted list of frame metadata (by timestamp)

        Returns:
            List of clusters built from the frames
        """
        clusters = []
        window = []
        seen_cameras = set()
        window_start_time = None

        for frame in frames:
            if frame.device_path in seen_cameras:
                # Duplicate camera - emit cluster
                if window and window_start_time is not None:
                    window_duration = frame.frame_time - window_start_time
                    completeness = len(window) / self._expected_cameras
                    clusters.append(
                        Cluster(
                            frames=window,
                            window_duration=window_duration,
                            completeness=completeness,
                        )
                    )

                # Start new window with this frame
                window = [frame]
                seen_cameras = {frame.device_path}
                window_start_time = frame.frame_time
            else:
                # New camera in window
                if not window:
                    window_start_time = frame.frame_time
                window.append(frame)
                seen_cameras.add(frame.device_path)

        return clusters

    def _evict_old_clusters(self) -> None:
        """Remove clusters older than window_seconds from rolling window."""
        if not self._recent_clusters:
            return

        # Get most recent cluster time
        latest_time = max(f.frame_time for f in self._recent_clusters[-1].frames)
        cutoff_time = latest_time - self._window_seconds

        # Remove old clusters from front
        while self._recent_clusters:
            oldest_cluster = self._recent_clusters[0]
            oldest_time = max(f.frame_time for f in oldest_cluster.frames)
            if oldest_time < cutoff_time:
                self._recent_clusters.popleft()
            else:
                break

    def _update_camera_frames(self, frames: list[FrameMetadata]) -> None:
        """Update per-camera frame history for jitter calculation."""
        # Add new frames to per-camera deques
        for frame in frames:
            self._camera_frames[frame.device_path].append(frame)

        # Evict old frames from each camera
        if frames:
            latest_time = max(f.frame_time for f in frames)
            cutoff_time = latest_time - self._window_seconds

            for camera_frames in self._camera_frames.values():
                while camera_frames and camera_frames[0].frame_time < cutoff_time:
                    camera_frames.popleft()

    def get_alignment_stats(self) -> AlignmentStats | None:
        """Get alignment quality over recent window."""
        # Copy clusters under lock, process outside lock
        with self._lock:
            if not self._recent_clusters:
                return None
            clusters = list(self._recent_clusters)

        # Process outside lock to minimize hold time
        complete_clusters = [c for c in clusters if c.completeness == 1.0]
        complete_pct = (len(complete_clusters) / len(clusters)) * 100

        spreads = [c.spread_ms for c in clusters]
        mean_spread = sum(spreads) / len(spreads)
        max_spread = max(spreads)

        durations = [c.window_duration * 1000 for c in clusters]
        mean_duration = sum(durations) / len(durations)

        return AlignmentStats(
            complete_cluster_pct=complete_pct,
            mean_spread_ms=mean_spread,
            max_spread_ms=max_spread,
            mean_window_duration_ms=mean_duration,
            total_clusters=len(clusters),
        )

    def get_camera_stats(self) -> dict[str, CameraStats]:
        """Get per-camera stats (fps, jitter) from recent frames."""
        # Copy frame data under lock, process outside lock
        with self._lock:
            frames_snapshot = {path: list(deque_frames) for path, deque_frames in self._camera_frames.items()}

        # Process outside lock
        stats = {}
        for device_path, frames in frames_snapshot.items():
            if len(frames) < 2:
                continue

            # Calculate FPS from timestamps
            duration = frames[-1].frame_time - frames[0].frame_time
            if duration > 0:
                measured_fps = (len(frames) - 1) / duration
            else:
                measured_fps = 0.0

            # Calculate jitter (stddev of inter-frame intervals)
            intervals = [frames[i + 1].frame_time - frames[i].frame_time for i in range(len(frames) - 1)]
            if intervals:
                mean_interval = sum(intervals) / len(intervals)
                variance = sum((x - mean_interval) ** 2 for x in intervals) / len(intervals)
                jitter_ms = (variance**0.5) * 1000
            else:
                jitter_ms = 0.0

            stats[device_path] = CameraStats(
                device_path=device_path,
                frames_in_window=len(frames),
                measured_fps=measured_fps,
                jitter_ms=jitter_ms,
                queue_depth=self._queues[device_path].qsize(),
            )

        return stats
