"""Multi-camera capture session orchestration."""

from __future__ import annotations

import logging
from queue import Queue
from typing import Iterator

from multiwebcam.pipeline.aligner import FrameAligner
from multiwebcam.pipeline.cluster import FrameCluster
from multiwebcam.pipeline.producer import FrameProducer
from multiwebcam.pipeline.report import AlignmentReport
from multiwebcam.pipeline.signals import StopSignal
from multiwebcam.sources.device import FrameSource
from multiwebcam.sources.frame_packet import FramePacket

logger = logging.getLogger(__name__)


class CaptureSessionError(Exception):
    """Raised when capture session operations fail."""

    pass


class CaptureSession:
    """
    Orchestrates multi-camera capture with temporal alignment.

    Creates producer threads for each camera, an aligner thread to group
    frames, and provides an iterator over aligned FrameClusters.

    Usage:
        sources = [
            FrameSource("/dev/video0"),
            FrameSource("/dev/video2"),
        ]

        with CaptureSession(sources) as session:
            for cluster in session.clusters():
                # Process aligned frames
                for device_path, packet in cluster.frames.items():
                    cv2.imshow(device_path, packet.frame)
    """

    def __init__(
        self,
        sources: list[FrameSource],
        queue_size: int = 30,
        enable_reports: bool = False,
        report_interval_seconds: float = 2.0,
    ) -> None:
        """
        Initialize a CaptureSession.

        Args:
            sources: List of FrameSource instances to capture from
            queue_size: Maximum frames to buffer per camera
            enable_reports: If True, emit AlignmentReports for monitoring
            report_interval_seconds: How often to emit reports (if enabled)
        """
        if not sources:
            raise CaptureSessionError("At least one FrameSource required")

        self.sources = sources
        self.queue_size = queue_size
        self.report_interval_seconds = report_interval_seconds

        # Per-camera queues
        self._producer_queues: dict[str, Queue[FramePacket | StopSignal]] = {}
        self._producers: list[FrameProducer] = []

        # Aligner output queue
        self._cluster_queue: Queue[FrameCluster | None] = Queue(maxsize=queue_size)
        self._aligner: FrameAligner | None = None

        # Report queue (optional)
        self._report_queue: Queue[AlignmentReport] | None = Queue() if enable_reports else None

        self._running = False

    def start(self) -> None:
        """Start all producers and aligner."""
        if self._running:
            logger.warning("CaptureSession already running")
            return

        logger.info(f"Starting capture session with {len(self.sources)} cameras")

        # Start all cameras in parallel and validate PTS compatibility
        # Cameras stay open - producers take over the already-running sources
        self._start_all_sources_parallel()

        # Create per-camera queues and producers
        for source in self.sources:
            queue: Queue[FramePacket | StopSignal] = Queue(maxsize=self.queue_size)
            self._producer_queues[source.device_path] = queue

            producer = FrameProducer(source, queue)
            self._producers.append(producer)

        # Start all producers first (they push frames to queues)
        for producer in self._producers:
            producer.start()

        # Create and start aligner (consumes from queues)
        # Uses nearest-neighbor algorithm, not fixed tolerance
        self._aligner = FrameAligner(
            input_queues=self._producer_queues,
            output_queue=self._cluster_queue,
            queue_timeout_seconds=5.0,  # Allow time for cameras to warm up
            report_queue=self._report_queue,
            report_interval_seconds=self.report_interval_seconds,
        )
        self._aligner.start()

        self._running = True
        logger.info("Capture session started")

    def stop(self) -> None:
        """Stop all producers and aligner in correct order."""
        if not self._running:
            return

        logger.info("Stopping capture session")

        # Stop producers first (stops frame flow)
        for producer in self._producers:
            producer.stop()

        # Then stop aligner (waits for queues to drain)
        if self._aligner is not None:
            self._aligner.stop()

        self._running = False
        logger.info("Capture session stopped")

    def clusters(self) -> Iterator[FrameCluster]:
        """
        Iterate over aligned frame clusters.

        Automatically starts the session if not already running.
        Yields clusters until session is stopped.
        """
        if not self._running:
            self.start()

        while self._running:
            try:
                cluster = self._cluster_queue.get(timeout=1.0)
                if cluster is None:
                    # End sentinel from aligner
                    break
                yield cluster
            except Exception:
                # Queue timeout - check if we should continue
                if not self._running:
                    break

    def get_latest_report(self) -> AlignmentReport | None:
        """
        Get the latest alignment report (non-blocking).

        Returns the most recent report, discarding any older ones in the queue.
        Returns None if no reports are available or reporting is disabled.
        """
        if self._report_queue is None:
            return None

        latest: AlignmentReport | None = None
        while True:
            try:
                latest = self._report_queue.get_nowait()
            except Exception:
                break
        return latest

    def _start_all_sources_parallel(self) -> None:
        """
        Start all cameras in parallel and validate PTS compatibility.

        Opens all cameras simultaneously using threads, then checks that
        their PTS timestamps are from the same epoch. Cameras stay open
        after validation - they're handed to producers.

        Raises:
            CaptureSessionError: If cameras have incompatible timestamp epochs.
        """
        from concurrent.futures import ThreadPoolExecutor, as_completed

        def start_source(source: FrameSource) -> tuple[str, float | None, Exception | None]:
            """Start a single source and return its PTS info."""
            try:
                status = source.start()
                return (source.device_path, status.first_pts_seconds, None)
            except Exception as e:
                return (source.device_path, None, e)

        # Start all cameras in parallel
        pts_values: list[tuple[str, float | None]] = []
        errors: list[tuple[str, Exception]] = []

        with ThreadPoolExecutor(max_workers=len(self.sources)) as executor:
            futures = {executor.submit(start_source, s): s for s in self.sources}
            for future in as_completed(futures):
                path, pts, error = future.result()
                if error is not None:
                    errors.append((path, error))
                else:
                    pts_values.append((path, pts))

        # If any camera failed to start, stop the ones that did and raise
        if errors:
            for source in self.sources:
                if source.is_running:
                    source.stop()
            error_msgs = [f"{path}: {e}" for path, e in errors]
            raise CaptureSessionError(f"Failed to start cameras:\n" + "\n".join(error_msgs))

        # Validate PTS compatibility
        pts_cameras = [(path, pts) for path, pts in pts_values if pts is not None]

        if not pts_cameras:
            logger.warning(
                "All cameras using wall-clock timestamps (PTS unavailable). Temporal alignment may be less accurate."
            )
            return

        if len(pts_cameras) < len(self.sources):
            logger.warning(
                f"{len(self.sources) - len(pts_cameras)} camera(s) using wall-clock "
                f"while others use PTS. Mixing timestamp sources may reduce alignment accuracy."
            )

        # Check PTS epoch consistency
        pts_times = [pts for _, pts in pts_cameras]
        spread = max(pts_times) - min(pts_times)

        if spread >= 60:
            # Stop all cameras before raising
            for source in self.sources:
                source.stop()
            raise CaptureSessionError(
                f"PTS timestamps have incompatible epochs (spread: {spread:.1f}s). "
                "Cameras may be using different timestamp bases."
            )

        logger.info(
            f"PTS validation passed: {len(pts_cameras)} camera(s) using compatible timestamps (spread: {spread:.3f}s)"
        )

    def __enter__(self) -> CaptureSession:
        """Context manager entry - starts session."""
        self.start()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        """Context manager exit - stops session."""
        self.stop()
