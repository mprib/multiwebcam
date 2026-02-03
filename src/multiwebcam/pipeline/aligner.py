"""Temporal alignment of frames from multiple sources using nearest-neighbor."""

from __future__ import annotations

import logging
import time
from queue import Empty, Queue
from threading import Event, Thread
from typing import TYPE_CHECKING

from multiwebcam.pipeline.cluster import FrameCluster
from multiwebcam.pipeline.report import AlignmentReport, CameraStats
from multiwebcam.pipeline.signals import StopSignal

if TYPE_CHECKING:
    from multiwebcam.sources.frame_packet import FramePacket

logger = logging.getLogger(__name__)


class FrameAligner:
    """
    Temporal alignment using nearest-neighbor algorithm.

    Consumes frames from multiple per-camera queues and groups them into
    temporally aligned clusters. Uses relative comparison (is this frame
    closer to the current cluster or the next?) rather than fixed tolerance.

    Based on Caliscope's synchronizer algorithm.
    """

    def __init__(
        self,
        input_queues: dict[str, Queue[FramePacket | StopSignal]],
        output_queue: Queue[FrameCluster | None],
        queue_timeout_seconds: float = 1.0,
        report_queue: Queue[AlignmentReport] | None = None,
        report_interval_seconds: float = 2.0,
    ) -> None:
        """
        Initialize the aligner.

        Args:
            input_queues: Map from device_path to input queue
            output_queue: Queue to push FrameClusters to
            queue_timeout_seconds: Timeout for queue.get() operations
            report_queue: Optional queue for AlignmentReport monitoring
            report_interval_seconds: How often to emit reports (if report_queue set)
        """
        self.input_queues = input_queues
        self.output_queue = output_queue
        self.queue_timeout_seconds = queue_timeout_seconds
        self.report_queue = report_queue
        self.report_interval_seconds = report_interval_seconds

        self._thread: Thread | None = None
        self._shutdown_event = Event()
        self._running = False

        # Per-camera state
        self._active_cameras: set[str] = set()
        self._frame_count: dict[str, int] = {}
        self._current_frame_index: dict[str, int] = {}
        self._all_frames: dict[str, FramePacket] = {}
        self._cluster_index = 0

        # Window counters for reporting
        self._window_start_time = 0.0
        self._window_frames_received: dict[str, int] = {}
        self._window_clusters_participated: dict[str, int] = {}
        self._window_clusters_emitted = 0
        self._window_complete_clusters = 0

        # Track frame timestamps for accurate fps calculation.
        # We record first and last frame_time per camera during the window,
        # then compute fps from actual capture timestamps rather than wall clock.
        self._window_first_frame_time: dict[str, float | None] = {}
        self._window_last_frame_time: dict[str, float | None] = {}

    @property
    def is_running(self) -> bool:
        """True if the aligner thread is running."""
        return self._running

    def start(self) -> None:
        """Start the aligner thread."""
        if self._running:
            logger.warning("Aligner already running")
            return

        # Initialize per-camera state
        for device_path in self.input_queues.keys():
            self._active_cameras.add(device_path)
            self._frame_count[device_path] = 0
            self._current_frame_index[device_path] = 0
            self._window_frames_received[device_path] = 0
            self._window_clusters_participated[device_path] = 0
            self._window_first_frame_time[device_path] = None
            self._window_last_frame_time[device_path] = None

        self._window_start_time = time.perf_counter()
        self._shutdown_event.clear()
        self._thread = Thread(target=self._run, daemon=True)
        self._running = True
        self._thread.start()
        logger.info(f"Started aligner for {len(self.input_queues)} cameras")

    def stop(self, timeout: float = 5.0) -> None:
        """Stop the aligner thread."""
        if not self._running:
            return

        logger.info("Stopping aligner")
        self._shutdown_event.set()

        if self._thread is not None:
            self._thread.join(timeout=timeout)
            if self._thread.is_alive():
                logger.warning(f"Aligner thread did not terminate within {timeout}s")

        self._running = False
        logger.info("Stopped aligner")

    def _run(self) -> None:
        """Main aligner loop: harvest frames, then align into clusters."""
        try:
            # Initial harvest: get first frame from each camera
            for device_path in list(self._active_cameras):
                self._harvest_frame(device_path)

            # Reset window timer AFTER initial harvest to avoid overstating fps.
            # Queues may have buffered frames during startup (before aligner started).
            # Draining those in the first window would inflate the fps measurement.
            self._reset_window_counters()
            self._window_start_time = time.perf_counter()

            # Main loop
            while not self._shutdown_event.is_set() and self._active_cameras:
                # Phase 1: Ensure we have next frame for lookahead
                for device_path in list(self._active_cameras):
                    self._ensure_next_frame_available(device_path)

                # Exit if no cameras remain
                if not self._active_cameras:
                    break

                # Phase 2: Align - group frames into cluster
                self._emit_cluster()

                # Phase 3: Check if report interval elapsed
                if self.report_queue is not None:
                    now = time.perf_counter()
                    elapsed = now - self._window_start_time
                    if elapsed >= self.report_interval_seconds:
                        self._emit_report()
                        self._reset_window_counters()

            # Signal end of stream
            self.output_queue.put(None)
            logger.info("Aligner finished - all cameras stopped")

        except Exception as e:
            logger.error(f"Aligner error: {e}", exc_info=True)

    def _harvest_frame(self, device_path: str) -> bool:
        """
        Pull one frame from a camera's queue into storage.

        Returns True if frame harvested, False if camera stopped/timed out.
        """
        item = self._get_next_item(device_path)

        if isinstance(item, StopSignal):
            logger.info(f"Camera {device_path} finished (StopSignal)")
            self._active_cameras.discard(device_path)
            return False

        if item is None:
            logger.warning(f"Camera {device_path} timed out")
            self._active_cameras.discard(device_path)
            return False

        # Store frame
        frame_idx = self._frame_count[device_path]
        key = f"{device_path}_{frame_idx}"
        self._all_frames[key] = item
        self._frame_count[device_path] += 1

        # Track for reporting
        self._window_frames_received[device_path] += 1

        # Track frame timestamps for fps calculation from actual capture times
        frame_time = item.frame_time
        if self._window_first_frame_time[device_path] is None:
            self._window_first_frame_time[device_path] = frame_time
        self._window_last_frame_time[device_path] = frame_time

        return True

    def _ensure_next_frame_available(self, device_path: str) -> None:
        """Ensure we have the next frame for this camera (needed for lookahead)."""
        next_idx = self._current_frame_index[device_path] + 1
        next_key = f"{device_path}_{next_idx}"

        if next_key not in self._all_frames:
            self._harvest_frame(device_path)

    def _get_next_item(self, device_path: str) -> FramePacket | StopSignal | None:
        """Pull next item from queue with timeout."""
        queue = self.input_queues[device_path]
        try:
            return queue.get(timeout=self.queue_timeout_seconds)
        except Empty:
            return None

    def _earliest_next_frame_time(self, exclude_device: str) -> float:
        """Get earliest timestamp among other cameras' NEXT frames."""
        next_times = []

        for device_path in self._active_cameras:
            if device_path == exclude_device:
                continue

            next_idx = self._current_frame_index[device_path] + 1
            next_key = f"{device_path}_{next_idx}"

            if next_key in self._all_frames:
                next_times.append(self._all_frames[next_key].frame_time)

        return min(next_times) if next_times else float('inf')

    def _latest_current_frame_time(self, exclude_device: str) -> float:
        """Get latest timestamp among other cameras' CURRENT frames."""
        current_times = []

        for device_path in self._active_cameras:
            if device_path == exclude_device:
                continue

            current_idx = self._current_frame_index[device_path]
            current_key = f"{device_path}_{current_idx}"

            if current_key in self._all_frames:
                current_times.append(self._all_frames[current_key].frame_time)

        return max(current_times) if current_times else float('-inf')

    def _emit_cluster(self) -> None:
        """Build and emit a cluster using nearest-neighbor logic."""
        # Pre-compute decision boundaries for each camera
        earliest_next: dict[str, float] = {}
        latest_current: dict[str, float] = {}

        for device_path in self._active_cameras:
            earliest_next[device_path] = self._earliest_next_frame_time(device_path)
            latest_current[device_path] = self._latest_current_frame_time(device_path)

        # Decide which frames go in this cluster
        cluster_frames: dict[str, FramePacket | None] = {}
        cluster_times: list[float] = []

        for device_path in self._active_cameras:
            current_idx = self._current_frame_index[device_path]
            current_key = f"{device_path}_{current_idx}"

            if current_key not in self._all_frames:
                # Frame not available yet - expected for slower cameras
                logger.debug(f"No frame available: {current_key}")
                cluster_frames[device_path] = None
                continue

            frame = self._all_frames[current_key]
            frame_time = frame.frame_time

            # Nearest-neighbor decision rules (from Caliscope)

            # Rule 1: If frame_time > earliest_next, skip (belongs to later cluster)
            if frame_time > earliest_next[device_path]:
                logger.debug(f"Skip {device_path} frame {current_idx}: time > earliest_next")
                cluster_frames[device_path] = None
                continue

            # Rule 2: If frame is closer to next cluster than current, skip
            dist_to_next = earliest_next[device_path] - frame_time
            dist_to_current = frame_time - latest_current[device_path]

            if dist_to_next < dist_to_current:
                logger.debug(f"Skip {device_path} frame {current_idx}: closer to next")
                cluster_frames[device_path] = None
                continue

            # Include frame in cluster
            cluster_frames[device_path] = frame
            cluster_times.append(frame_time)

            # Track for reporting
            self._window_clusters_participated[device_path] += 1

            # Advance this camera's index and remove consumed frame
            self._current_frame_index[device_path] += 1
            self._all_frames.pop(current_key)

        # Compute cluster time
        if cluster_times:
            cluster_time = sum(cluster_times) / len(cluster_times)
        else:
            logger.warning(f"Empty cluster at index {self._cluster_index}")
            cluster_time = 0.0

        # Track for reporting
        self._window_clusters_emitted += 1
        if all(frame is not None for frame in cluster_frames.values()):
            self._window_complete_clusters += 1

        # Emit cluster
        cluster = FrameCluster(
            cluster_index=self._cluster_index,
            cluster_time=cluster_time,
            frames=cluster_frames,
        )
        self.output_queue.put(cluster)
        self._cluster_index += 1

    def _emit_report(self) -> None:
        """Build and emit an AlignmentReport from current window counters."""
        window_end = time.perf_counter()
        window_duration = window_end - self._window_start_time

        # Build per-camera stats
        camera_stats: dict[str, CameraStats] = {}

        for device_path in self.input_queues.keys():
            frames_received = self._window_frames_received.get(device_path, 0)
            clusters_participated = self._window_clusters_participated.get(device_path, 0)

            # Calculate skip rate (handle division by zero)
            if self._window_clusters_emitted > 0:
                cluster_skip_rate = 1.0 - (
                    clusters_participated / self._window_clusters_emitted
                )
            else:
                cluster_skip_rate = 0.0

            # Calculate measured fps from frame timestamps (actual camera rate).
            # Uses (frames - 1) / time_span because N frames span N-1 intervals.
            first_time = self._window_first_frame_time.get(device_path)
            last_time = self._window_last_frame_time.get(device_path)

            if first_time is not None and last_time is not None and frames_received >= 2:
                time_span = last_time - first_time
                if time_span > 0:
                    measured_fps = (frames_received - 1) / time_span
                else:
                    measured_fps = 0.0
            else:
                measured_fps = 0.0

            # Get current queue depth
            queue_depth = self.input_queues[device_path].qsize()

            camera_stats[device_path] = CameraStats(
                device_path=device_path,
                frames_received=frames_received,
                clusters_participated=clusters_participated,
                cluster_skip_rate=cluster_skip_rate,
                queue_depth=queue_depth,
                measured_fps=measured_fps,
            )

        # Calculate cluster rate
        if window_duration > 0:
            cluster_rate = self._window_clusters_emitted / window_duration
        else:
            cluster_rate = 0.0

        # Calculate complete cluster rate
        if self._window_clusters_emitted > 0:
            complete_cluster_rate = (
                self._window_complete_clusters / self._window_clusters_emitted
            )
        else:
            complete_cluster_rate = 0.0

        # Build report
        report = AlignmentReport(
            window_start=self._window_start_time,
            window_end=window_end,
            window_duration=window_duration,
            clusters_emitted=self._window_clusters_emitted,
            cluster_rate=cluster_rate,
            complete_cluster_count=self._window_complete_clusters,
            complete_cluster_rate=complete_cluster_rate,
            frame_storage_count=len(self._all_frames),
            camera_stats=camera_stats,
        )

        # Emit report
        if self.report_queue is not None:
            self.report_queue.put(report)

    def _reset_window_counters(self) -> None:
        """Zero out window counters and update window start time."""
        self._window_start_time = time.perf_counter()
        self._window_clusters_emitted = 0
        self._window_complete_clusters = 0

        for device_path in self.input_queues.keys():
            self._window_frames_received[device_path] = 0
            self._window_clusters_participated[device_path] = 0
            self._window_first_frame_time[device_path] = None
            self._window_last_frame_time[device_path] = None
