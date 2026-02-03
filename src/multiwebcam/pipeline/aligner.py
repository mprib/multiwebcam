"""Temporal alignment of frames from multiple sources."""

from __future__ import annotations

import logging
from queue import Empty, Queue
from threading import Event, Thread
from typing import Iterator

from .cluster import FrameCluster
from ..sources.frame_packet import FramePacket

logger = logging.getLogger(__name__)


class FrameAligner:
    """
    Consumes frames from multiple per-camera queues and groups them into
    temporally aligned clusters.

    The aligner pulls frames from each camera's queue and groups frames that
    were captured within a time tolerance window. This creates FrameClusters
    representing "concurrent" multi-camera frames (within ~10-50ms).

    Usage:
        queues = {
            "/dev/video0": Queue(),
            "/dev/video2": Queue(),
        }
        output_queue = Queue()

        aligner = FrameAligner(queues, output_queue, tolerance_ms=50)
        aligner.start()

        for cluster in iter(output_queue.get, None):
            process(cluster)

        aligner.stop()
    """

    def __init__(
        self,
        input_queues: dict[str, Queue[FramePacket]],
        output_queue: Queue[FrameCluster],
        tolerance_ms: float = 50.0,
        timeout_seconds: float = 1.0,
    ) -> None:
        """
        Initialize a FrameAligner.

        Args:
            input_queues: Map from device_path to input queue
            output_queue: Queue to push FrameClusters to
            tolerance_ms: Maximum time difference for frames in a cluster (milliseconds)
            timeout_seconds: How long to wait for frames before considering a camera stalled
        """
        self.input_queues = input_queues
        self.output_queue = output_queue
        self.tolerance_seconds = tolerance_ms / 1000.0
        self.timeout_seconds = timeout_seconds

        self._thread: Thread | None = None
        self._shutdown_event = Event()
        self._running = False
        self._cluster_index = 0

    @property
    def is_running(self) -> bool:
        """True if the aligner thread is running."""
        return self._running

    def start(self) -> None:
        """Start the aligner thread."""
        if self._running:
            logger.warning("Aligner already running")
            return

        self._shutdown_event.clear()
        self._thread = Thread(target=self._run, daemon=True)
        self._running = True
        self._thread.start()
        logger.info(f"Started aligner for {len(self.input_queues)} cameras")

    def stop(self, timeout: float = 5.0) -> None:
        """
        Stop the aligner thread.

        Args:
            timeout: Maximum time to wait for thread to join (seconds)
        """
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
        """Aligner thread main loop."""
        try:
            # Buffer to hold most recent frame from each camera
            frame_buffer: dict[str, FramePacket] = {}

            # Fill initial buffer - need at least one frame from each camera
            for device_path in self.input_queues.keys():
                frame = self._get_frame(device_path)
                if frame is None:
                    logger.error(f"Failed to get initial frame from {device_path}")
                    return
                frame_buffer[device_path] = frame

            # Main alignment loop
            while not self._shutdown_event.is_set():
                # Find oldest frame
                oldest_device = min(
                    frame_buffer.keys(),
                    key=lambda dev: frame_buffer[dev].frame_time,
                )
                oldest_time = frame_buffer[oldest_device].frame_time

                # Group all frames within tolerance
                cluster_frames: dict[str, FramePacket] = {}
                for device_path, frame in frame_buffer.items():
                    time_diff = abs(frame.frame_time - oldest_time)
                    if time_diff <= self.tolerance_seconds:
                        cluster_frames[device_path] = frame

                # If we got frames from all cameras, emit cluster
                if len(cluster_frames) == len(self.input_queues):
                    cluster = FrameCluster(
                        cluster_index=self._cluster_index,
                        cluster_time=oldest_time,
                        frames=cluster_frames,
                    )
                    self.output_queue.put(cluster)
                    self._cluster_index += 1

                    # Advance all cameras that were in this cluster
                    for device_path in cluster_frames.keys():
                        new_frame = self._get_frame(device_path)
                        if new_frame is None:
                            logger.info(f"Camera {device_path} stopped producing frames")
                            return
                        frame_buffer[device_path] = new_frame
                else:
                    # Advance only the oldest camera
                    new_frame = self._get_frame(oldest_device)
                    if new_frame is None:
                        logger.info(f"Camera {oldest_device} stopped producing frames")
                        return
                    frame_buffer[oldest_device] = new_frame

        except Exception as e:
            logger.error(f"Aligner error: {e}", exc_info=True)
        finally:
            logger.debug("Aligner thread exiting")

    def _get_frame(self, device_path: str) -> FramePacket | None:
        """
        Get next frame from a device's queue with timeout.

        Returns:
            FramePacket if available, None if queue is stalled/empty
        """
        queue = self.input_queues[device_path]
        try:
            return queue.get(timeout=self.timeout_seconds)
        except Empty:
            # Camera may have disconnected or stopped producing
            return None
