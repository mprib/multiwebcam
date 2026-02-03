"""Threaded frame producer wrapping FrameSource."""

from __future__ import annotations

import logging
from queue import Queue
from threading import Event, Thread
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..sources.device import FrameSource
    from ..sources.frame_packet import FramePacket

logger = logging.getLogger(__name__)


class FrameProducer:
    """
    Threaded wrapper around FrameSource that pushes frames to a queue.

    The producer runs in its own thread, pulling frames from the FrameSource
    and pushing them to an output queue. It respects stop/shutdown signals
    for clean termination.

    Usage:
        source = FrameSource("/dev/video0")
        queue: Queue[FramePacket] = Queue(maxsize=30)
        producer = FrameProducer(source, queue)

        producer.start()
        # ... consume from queue ...
        producer.stop()
    """

    def __init__(self, source: FrameSource, output_queue: Queue[FramePacket]) -> None:
        """
        Initialize a FrameProducer.

        Args:
            source: FrameSource to capture from
            output_queue: Queue to push FramePackets to
        """
        self.source = source
        self.output_queue = output_queue
        self._thread: Thread | None = None
        self._shutdown_event = Event()
        self._running = False

    @property
    def is_running(self) -> bool:
        """True if the producer thread is running."""
        return self._running

    @property
    def device_path(self) -> str:
        """Device path of the underlying source."""
        return self.source.device_path

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

        Args:
            timeout: Maximum time to wait for thread to join (seconds)
        """
        if not self._running:
            return

        logger.info(f"Stopping producer for {self.device_path}")
        self._shutdown_event.set()

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
        try:
            self.source.start()

            for packet in self.source:
                # Make frame array read-only to enforce immutability
                packet.frame.flags.writeable = False

                # Check for shutdown signal
                if self._shutdown_event.is_set():
                    break

                # Push to queue (blocks if full)
                self.output_queue.put(packet)

        except Exception as e:
            logger.error(f"Producer error on {self.device_path}: {e}", exc_info=True)
        finally:
            self.source.stop()
            logger.debug(f"Producer thread exiting for {self.device_path}")
