"""Per-camera video encoder thread."""

from __future__ import annotations

import logging
from pathlib import Path
from queue import Empty, Queue
from threading import Thread
from typing import Callable, Literal

import av
from av.video.stream import VideoStream

from multiwebcam.sources.frame_packet import FramePacket

logger = logging.getLogger(__name__)


class CameraEncoder:
    """
    Per-camera worker thread that drains recording queue and writes MP4.

    This is an internal implementation detail of FrameRecorder. Each camera
    gets its own encoder thread that:
    1. Drains frames from the recording queue
    2. Encodes to MP4 via PyAV
    3. Reports timestamps to FrametimesCollector
    4. Exits when sentinel (None) is received

    The encoder runs in its own daemon thread.
    """

    def __init__(
        self,
        cam_id: int,
        queue: Queue[FramePacket | None],
        output_path: Path,
        codec: str = "h264",
        timestamp_callback: Callable[[int, int, float], None] | None = None,
    ) -> None:
        """
        Initialize a CameraEncoder.

        Args:
            cam_id: Integer camera ID for logging and callbacks
            queue: Queue to drain frames from (None = sentinel)
            output_path: Path to write MP4 file
            codec: Video codec (default "h264")
            timestamp_callback: Called for each frame: callback(cam_id, frame_index, frame_time)
        """
        self.cam_id = cam_id
        self.queue = queue
        self.output_path = output_path
        self.codec = codec
        self.timestamp_callback = timestamp_callback

        self._thread: Thread | None = None
        self._frames_written = 0
        self._errors: list[str] = []
        self._running = False

    @property
    def frames_written(self) -> int:
        """Number of frames successfully written."""
        return self._frames_written

    @property
    def errors(self) -> list[str]:
        """List of error messages encountered during encoding."""
        return self._errors.copy()

    @property
    def is_running(self) -> bool:
        """True if encoder thread is running."""
        return self._running

    def start(self) -> None:
        """Start the encoder thread."""
        if self._running:
            logger.warning(f"Encoder for cam_{self.cam_id} already running")
            return

        self._thread = Thread(target=self._run, daemon=True)
        self._running = True
        self._thread.start()
        logger.info(f"Started encoder for cam_{self.cam_id} -> {self.output_path}")

    def join(self, timeout: float | None = None) -> bool:
        """
        Wait for encoder thread to finish.

        Args:
            timeout: Maximum time to wait in seconds (None = wait forever)

        Returns:
            True if thread finished, False if timeout
        """
        if self._thread is None:
            return True

        self._thread.join(timeout=timeout)
        return not self._thread.is_alive()

    def _run(self) -> None:
        """
        Encoder thread main loop.

        Drains queue, encodes frames, reports timestamps. Exits when sentinel (None) received.
        """
        # PyAV types: container is av.container.OutputContainer (no public import)
        container = None
        stream: VideoStream | None = None
        first_frame = True

        try:
            while True:
                # Wait for frame (blocking)
                try:
                    packet = self.queue.get(timeout=1.0)
                except Empty:
                    # Check for sentinel periodically even if queue is empty
                    continue

                # Sentinel = stop signal
                if packet is None:
                    logger.debug(f"Encoder for cam_{self.cam_id} received sentinel, stopping")
                    break

                # Initialize encoder on first frame (need resolution)
                if first_frame:
                    try:
                        container, stream = self._initialize_encoder(packet.frame.shape)
                        first_frame = False
                    except Exception as e:
                        error_msg = f"Failed to initialize encoder: {e}"
                        logger.error(f"cam_{self.cam_id}: {error_msg}", exc_info=True)
                        self._errors.append(error_msg)
                        # Can't encode without container - drain queue and exit
                        self._drain_queue_on_error()
                        break

                # Encode frame
                try:
                    if container is not None and stream is not None:
                        self._encode_frame(container, stream, packet)
                        self._frames_written += 1

                        # Report timestamp
                        if self.timestamp_callback is not None:
                            self.timestamp_callback(
                                self.cam_id,
                                packet.frame_index,
                                packet.frame_time,
                            )
                except OSError as e:
                    # I/O error (disk full, permission denied, etc.) - can't continue
                    error_msg = f"I/O error (disk full?): {e}"
                    logger.error(f"cam_{self.cam_id}: {error_msg}")
                    self._errors.append(error_msg)
                    self._drain_queue_on_error()
                    break
                except Exception as e:
                    error_msg = f"Failed to encode frame {packet.frame_index}: {e}"
                    logger.error(f"cam_{self.cam_id}: {error_msg}")
                    self._errors.append(error_msg)
                    # Continue with next frame - don't let one bad frame kill recording

        except Exception as e:
            error_msg = f"Encoder thread crashed: {e}"
            logger.error(f"cam_{self.cam_id}: {error_msg}", exc_info=True)
            self._errors.append(error_msg)

        finally:
            # Finalize MP4 container
            if container is not None and stream is not None:
                try:
                    # Flush remaining buffered frames before closing
                    for packet in stream.encode():
                        container.mux(packet)
                    container.close()
                    logger.info(
                        f"Encoder for cam_{self.cam_id} finished: {self._frames_written} frames written to {self.output_path}"
                    )
                except Exception as e:
                    error_msg = f"Failed to close container: {e}"
                    logger.error(f"cam_{self.cam_id}: {error_msg}", exc_info=True)
                    self._errors.append(error_msg)

            self._running = False

    def _initialize_encoder(self, frame_shape: tuple[int, ...]) -> tuple[av.container.OutputContainer, VideoStream]:  # type: ignore[name-defined]
        # Return types: PyAV container and stream - OutputContainer not publicly exported
        """
        Initialize PyAV encoder with frame resolution.

        Args:
            frame_shape: Shape of BGR frame (H, W, 3)

        Returns:
            (container, stream) tuple
        """
        height, width = frame_shape[0], frame_shape[1]

        container = av.open(str(self.output_path), mode="w")
        stream = container.add_stream(self.codec, rate=30)  # Assume 30fps for now
        stream.width = width
        stream.height = height
        stream.pix_fmt = "yuv420p"

        logger.debug(f"Initialized encoder for cam_{self.cam_id}: {width}x{height}, codec={self.codec}")
        return container, stream

    def _encode_frame(
        self,
        container: av.container.OutputContainer,  # type: ignore[name-defined]
        stream: VideoStream,
        packet: FramePacket,
    ) -> None:
        # PyAV's OutputContainer type not publicly exported - use type: ignore
        """
        Encode a single frame to the container.

        Args:
            container: PyAV output container
            stream: PyAV video stream
            packet: Frame to encode
        """
        # Convert BGR to VideoFrame
        # PyAV expects RGB, so we need to convert from BGR
        bgr = packet.frame
        rgb = bgr[:, :, ::-1]  # Reverse channel order BGR -> RGB

        # Create VideoFrame from numpy array
        frame = av.VideoFrame.from_ndarray(rgb, format="rgb24")

        # Encode and write
        for encoded_packet in stream.encode(frame):
            container.mux(encoded_packet)

    def _drain_queue_on_error(self) -> None:
        """Drain remaining frames from queue when encoder fails."""
        drained = 0
        while True:
            try:
                packet = self.queue.get_nowait()
                if packet is None:
                    break
                drained += 1
            except Empty:
                break

        if drained > 0:
            logger.warning(f"cam_{self.cam_id}: Drained {drained} frames after encoder failure")
