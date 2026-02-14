"""Threaded frame producer wrapping FrameSource."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from queue import Empty, Queue
from threading import Event, Thread
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from multiwebcam.sources.device import FrameSource
    from multiwebcam.sources.frame_packet import FramePacket

logger = logging.getLogger(__name__)


@dataclass
class QueueBundle:
    """Bundle of output queues for a single camera."""

    display: Queue[FramePacket]  # maxsize=1, drop-oldest
    recording: Queue[FramePacket | None]  # large, blocking (only when recording); None = sentinel
    alignment: Queue[FramePacket]  # large, for monitoring


class FrameProducer:
    """
    Threaded wrapper around FrameSource that pushes frames to multiple queues.

    The producer runs in its own thread, pulling frames from the FrameSource
    and pushing them to queues with different behaviors:
    - Display queue: maxsize=1, drop-oldest for latest frame access
    - Alignment queue: blocking puts for monitoring
    - Recording queue: conditional (only when is_recording flag is set)

    Usage:
        source = FrameSource("/dev/video0")
        is_recording = Event()
        queues = QueueBundle(
            display=Queue(maxsize=1),
            recording=Queue(maxsize=150),
            alignment=Queue(maxsize=150),
        )
        producer = FrameProducer(source, queues, is_recording)

        producer.start()
        # ... consume from queues ...
        producer.stop()
    """

    def __init__(
        self,
        source: FrameSource,
        queues: QueueBundle,
        is_recording: Event,
    ) -> None:
        """
        Initialize a FrameProducer.

        Args:
            source: FrameSource to capture from
            queues: QueueBundle bundle for this camera
            is_recording: Shared Event flag - only push to recording queue when set
        """
        self.source = source
        self.queues = queues
        self.is_recording = is_recording
        self._thread: Thread | None = None
        self._shutdown_event = Event()
        self._resume_event = Event()
        self._resume_event.set()  # Start in running state
        self._running = False  # Tracks thread lifecycle
        self._frames_captured = 0

    @property
    def is_running(self) -> bool:
        """True if the producer thread is running."""
        return self._running

    @property
    def device_path(self) -> str:
        """Device path of the underlying source."""
        return self.source.device_path

    @property
    def frames_captured(self) -> int:
        """Total frames captured by this producer."""
        return self._frames_captured

    def pause(self) -> None:
        """Pause frame production. Producer thread blocks until resume()."""
        self._resume_event.clear()

    def resume(self) -> None:
        """Resume frame production after pause."""
        self._resume_event.set()

    @property
    def is_paused(self) -> bool:
        """True if producer is paused."""
        return not self._resume_event.is_set()

    def start(self) -> None:
        """Start the producer thread."""
        if self._running:
            logger.warning(f"Producer for {self.device_path} already running")
            return

        self._shutdown_event.clear()
        self._thread = Thread(target=self._run, daemon=True)
        self._running = True
        self._thread.start()
        logger.info(f"Started producer for {self.device_path}")

    def stop(self, timeout: float = 5.0) -> None:
        """
        Stop the producer thread.

        Closes the source from main thread to unblock decode(), then waits
        for producer thread to exit.

        Args:
            timeout: Maximum time to wait for thread to join (seconds)
        """
        if not self._running:
            return

        logger.info(f"Stopping producer for {self.device_path}")
        self._shutdown_event.set()
        self._resume_event.set()  # Unblock if paused

        # Close the source to unblock decode() - do this from main thread
        # This will cause the producer thread's decode() to raise an exception
        self.source.stop()

        if self._thread is not None:
            self._thread.join(timeout=timeout)
            if self._thread.is_alive():
                logger.warning(
                    f"Producer thread for {self.device_path} "
                    f"did not terminate within {timeout}s"
                )

        self._running = False
        logger.info(f"Stopped producer for {self.device_path}")

    def _run(self) -> None:
        """Producer thread main loop."""
        max_restarts = 3
        restarts = 0

        try:
            self.source.start()
        except Exception as e:
            logger.error(f"Failed to start source {self.device_path}: {e}")
            return

        while not self._shutdown_event.is_set():
            try:
                for packet in self.source:
                    # Block if paused
                    self._resume_event.wait()

                    # Check shutdown after resume to avoid processing one more frame
                    if self._shutdown_event.is_set():
                        return

                    # Make frame array read-only to enforce immutability
                    packet.frame.flags.writeable = False

                    self._frames_captured += 1

                    # Display queue: drop-oldest (always get latest)
                    try:
                        self.queues.display.get_nowait()
                    except Empty:
                        pass
                    self.queues.display.put_nowait(packet)

                    # Alignment queue: always push (for monitoring)
                    self.queues.alignment.put(packet)

                    # Recording queue: conditional on is_recording flag
                    if self.is_recording.is_set():
                        self.queues.recording.put(packet)

                # Iterator exhausted normally
                break

            except Exception as e:
                if self._shutdown_event.is_set():
                    break

                restarts += 1
                if restarts > max_restarts:
                    logger.error(
                        f"Producer {self.device_path} exceeded {max_restarts} "
                        f"restarts, giving up: {e}"
                    )
                    break

                # Transient decode errors happen when V4L2 controls change
                # mid-stream (e.g. switching exposure mode). Restart the
                # source and resume capturing.
                logger.warning(
                    f"Decode error on {self.device_path} ({restarts}/{max_restarts}), "
                    f"restarting source: {e}"
                )
                try:
                    self.source.stop()
                    self.source.start()
                except Exception as restart_err:
                    logger.error(
                        f"Failed to restart source {self.device_path}: {restart_err}"
                    )
                    break

        logger.debug(f"Producer thread exiting for {self.device_path}")
