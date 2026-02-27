"""Multi-camera recording orchestration."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from pathlib import Path
from queue import Queue

from multiwebcam.recording.encoder import CameraEncoder
from multiwebcam.recording.timestamps import TimestampCollector
from multiwebcam.sources.frame_packet import FramePacket

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RecordingResult:
    """
    Result of a recording session.

    Returned by FrameRecorder.stop() after finalizing all files.
    """

    output_dir: Path
    frames_per_camera: dict[int, int]  # cam_id -> frame count
    duration_seconds: float
    errors: list[str]  # Any non-fatal errors encountered
    timestamps_path: Path  # Path to timestamps.csv


class FrameRecorder:
    """
    Orchestrates per-camera encoder threads for a recording session.

    CaptureSession creates one FrameRecorder per recording session.
    The recorder:
    - Spawns a CameraEncoder thread per camera
    - Collects timestamps from all encoders
    - Drains queues and finalizes files on stop

    Usage:
        recording_queues = {
            "/dev/video0": Queue(),
            "/dev/video2": Queue(),
        }
        cam_ids = {
            "/dev/video0": 0,
            "/dev/video2": 1,
        }

        recorder = FrameRecorder(recording_queues, output_dir, cam_ids)

        # After setting is_recording flag:
        recorder.start()

        # When ready to stop (after clearing is_recording and pushing sentinels):
        result = recorder.stop()
    """

    def __init__(
        self,
        recording_queues: dict[str, Queue[FramePacket | None]],
        output_dir: Path,
        cam_ids: dict[str, int],
        codec: str = "h264",
    ) -> None:
        """
        Initialize a FrameRecorder.

        Args:
            recording_queues: Per-camera recording queues (device_path -> queue)
            output_dir: Directory to write MP4 files and timestamps.csv
            cam_ids: Device path to integer cam_id mapping
            codec: Video codec (default "h264")
        """
        self.recording_queues = recording_queues
        self.output_dir = output_dir
        self.cam_ids = cam_ids
        self.codec = codec

        self._encoders: list[CameraEncoder] = []
        self._timestamp_collector = TimestampCollector()
        self._start_time: float | None = None
        self._running = False

    @property
    def is_running(self) -> bool:
        """True if encoder threads are running."""
        return self._running

    @property
    def frames_written(self) -> dict[int, int]:
        """Per-camera frame counts (cam_id -> count)."""
        return {enc.cam_id: enc.frames_written for enc in self._encoders}

    @property
    def recording_duration(self) -> float:
        """Seconds since start() was called (0 if not started)."""
        if self._start_time is None:
            return 0.0
        return time.perf_counter() - self._start_time

    def start(self) -> None:
        """
        Start encoder threads.

        Call this AFTER setting the is_recording flag so producers start pushing.
        """
        if self._running:
            logger.warning("FrameRecorder already running")
            return

        logger.info(f"Starting recording to {self.output_dir} with {len(self.recording_queues)} cameras")

        # Ensure output directory exists
        self.output_dir.mkdir(parents=True, exist_ok=True)

        # Create encoder for each camera
        for device_path, queue in self.recording_queues.items():
            # Get cam_id for this device
            cam_id = self.cam_ids[device_path]
            output_path = self.output_dir / f"cam_{cam_id}.mp4"

            # Create encoder with timestamp callback
            encoder = CameraEncoder(
                cam_id=cam_id,
                queue=queue,
                output_path=output_path,
                codec=self.codec,
                timestamp_callback=self._timestamp_collector.add_timestamp,
            )
            self._encoders.append(encoder)

        # Start all encoders
        for encoder in self._encoders:
            encoder.start()

        self._start_time = time.perf_counter()
        self._running = True
        logger.info("All encoders started")

    def stop(self, drain_timeout: float = 10.0) -> RecordingResult:
        """
        Stop recording, drain remaining frames, finalize files.

        This should be called AFTER:
        1. Clearing the is_recording flag (producers stop pushing)
        2. Pushing None sentinel to each recording queue

        Args:
            drain_timeout: Maximum time to wait for each encoder thread (seconds)

        Returns:
            RecordingResult with frame counts and any errors
        """
        if not self._running:
            logger.warning("FrameRecorder not running, nothing to stop")
            # Return empty result
            return RecordingResult(
                output_dir=self.output_dir,
                frames_per_camera={},
                duration_seconds=0.0,
                errors=["Recording was not active"],
                timestamps_path=self.output_dir / "timestamps.csv",
            )

        logger.info("Stopping recording, draining encoder queues...")

        # Wait for all encoder threads to finish (they exit on sentinel)
        for encoder in self._encoders:
            finished = encoder.join(timeout=drain_timeout)
            if not finished:
                logger.warning(
                    f"Encoder for cam_{encoder.cam_id} did not finish within {drain_timeout}s timeout"
                )

        # Calculate duration
        duration = self.recording_duration

        # Collect frame counts and errors
        frames_per_camera = {}
        all_errors = []

        for encoder in self._encoders:
            frames_per_camera[encoder.cam_id] = encoder.frames_written
            all_errors.extend(encoder.errors)

        # Write timestamps.csv
        timestamps_path = self.output_dir / "timestamps.csv"
        try:
            self._timestamp_collector.write_csv(timestamps_path)
        except Exception as e:
            error_msg = f"Failed to write timestamps.csv: {e}"
            logger.error(error_msg, exc_info=True)
            all_errors.append(error_msg)

        self._running = False

        result = RecordingResult(
            output_dir=self.output_dir,
            frames_per_camera=frames_per_camera,
            duration_seconds=duration,
            errors=all_errors,
            timestamps_path=timestamps_path,
        )

        logger.info(
            f"Recording stopped: {duration:.1f}s, "
            f"{sum(frames_per_camera.values())} total frames, "
            f"{len(all_errors)} errors"
        )

        return result
