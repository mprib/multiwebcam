"""V4L2 device capture using PyAV."""

from __future__ import annotations

import re
from collections import deque
from time import perf_counter
from typing import TYPE_CHECKING, Iterator, Literal

import av
from av.error import FFmpegError

from .config import CaptureConfig, SourceStatus
from .conversion import frame_to_bgr
from .frame_packet import FramePacket

if TYPE_CHECKING:
    pass


class DeviceSourceError(Exception):
    """Raised when device capture fails."""

    pass


class DeviceSource:
    """
    Video capture from a V4L2 device using PyAV/FFmpeg.

    This is a passive iterator - it yields FramePackets on demand.
    For threaded capture, wrap with FrameProducer from the pipeline layer.

    Usage patterns:

        # Context manager (recommended)
        with DeviceSource("/dev/video0") as source:
            for packet in source:
                process(packet.frame)

        # Explicit lifecycle
        source = DeviceSource("/dev/video0")
        status = source.start()
        for packet in source:
            process(packet.frame)
        source.stop()

        # Auto-start on iteration
        source = DeviceSource("/dev/video0")
        for packet in source:  # Calls start() implicitly
            process(packet.frame)
    """

    # Rolling window size for fps calculation
    _FPS_WINDOW_SIZE: int = 10

    def __init__(
        self,
        device: str,
        config: CaptureConfig | None = None,
    ) -> None:
        """
        Initialize a DeviceSource.

        Args:
            device: V4L2 device path (e.g., "/dev/video0")
            config: Capture configuration. Defaults to 720p30 MJPEG.

        The device is not opened until start() is called.
        """
        self._device_path = device
        self._device_id = self._extract_device_id(device)
        self._config = config or CaptureConfig()

        # Runtime state (set by start())
        self._container: av.InputContainer | None = None
        self._stream: av.video.VideoStream | None = None
        self._is_running = False
        self._timestamp_source: Literal["pts", "wall_clock"] = "pts"
        self._first_pts: float | None = None

        # Frame tracking
        self._frame_index = 0
        self._warmup_discarded = 0
        self._timestamps: deque[float] = deque(maxlen=self._FPS_WINDOW_SIZE)

    @staticmethod
    def _extract_device_id(device_path: str) -> int:
        """Extract numeric ID from device path (e.g., '/dev/video0' -> 0)."""
        match = re.search(r"video(\d+)$", device_path)
        if match:
            return int(match.group(1))
        raise ValueError(f"Cannot extract device ID from path: {device_path}")

    @property
    def device_path(self) -> str:
        """Full V4L2 device path."""
        return self._device_path

    @property
    def device_id(self) -> int:
        """Numeric device ID extracted from path."""
        return self._device_id

    @property
    def is_running(self) -> bool:
        """True if the device is open and capturing."""
        return self._is_running

    def start(self) -> SourceStatus:
        """
        Open the device and begin capture.

        Returns:
            SourceStatus with actual device parameters.

        Raises:
            DeviceSourceError: If device cannot be opened or configuration fails.
        """
        if self._is_running:
            return self._build_status()

        try:
            self._open_device()
            self._validate_and_configure()
            self._consume_warmup_frames()
        except FFmpegError as e:
            self._cleanup()
            raise DeviceSourceError(f"Failed to open {self._device_path}: {e}") from e
        except Exception as e:
            self._cleanup()
            raise DeviceSourceError(f"Capture setup failed: {e}") from e

        self._is_running = True
        return self._build_status()

    def stop(self) -> None:
        """Stop capture and release the device."""
        self._cleanup()
        self._is_running = False

    def _open_device(self) -> None:
        """Open the V4L2 device with configured options."""
        width, height = self._config.resolution

        options = {
            "input_format": self._config.pixel_format,
            "video_size": f"{width}x{height}",
            "framerate": str(self._config.fps),
        }
        options.update(self._config.v4l2_options)

        self._container = av.open(
            self._device_path,
            format="v4l2",
            options=options,
        )
        self._stream = self._container.streams.video[0]

    def _validate_and_configure(self) -> None:
        """
        Validate device configuration and determine timestamp source.

        Some cameras silently fall back to a different resolution.
        We verify we got what we asked for.
        """
        if self._stream is None:
            raise DeviceSourceError("No video stream available")

        # Verify resolution (can't check until we decode a frame, defer to warmup)

    def _consume_warmup_frames(self) -> None:
        """
        Discard initial frames during USB enumeration.

        Early frames often have irregular timing as the camera settles.
        We also use the first valid frame to determine timestamp source.
        """
        if self._container is None:
            raise DeviceSourceError("Device not open")

        warmup_count = self._config.warmup_frames
        self._warmup_discarded = 0

        for frame in self._container.decode(video=0):
            # On first frame, check resolution and determine timestamp source
            if self._warmup_discarded == 0:
                self._verify_resolution(frame)
                self._determine_timestamp_source(frame)

            self._warmup_discarded += 1
            if self._warmup_discarded >= warmup_count:
                break

    def _verify_resolution(self, frame: av.VideoFrame) -> None:
        """Verify actual resolution matches requested."""
        expected = self._config.resolution
        actual = (frame.width, frame.height)

        if actual != expected:
            raise DeviceSourceError(
                f"Resolution mismatch: requested {expected}, got {actual}. "
                f"Camera may not support {expected[0]}x{expected[1]}."
            )

    def _determine_timestamp_source(self, frame: av.VideoFrame) -> None:
        """
        Determine whether to use PTS or wall-clock timestamps.

        On tested hardware (Framework laptop, Linux 6.x), V4L2 provides
        PTS from the kernel's monotonic clock (time since boot). This is
        comparable across cameras on the same system.

        If PTS is unavailable or appears stream-relative (< 60s), we fall
        back to wall-clock.
        """
        if frame.pts is None or self._stream is None:
            self._timestamp_source = "wall_clock"
            self._first_pts = None
            return

        time_base = self._stream.time_base
        pts_seconds = float(frame.pts * time_base)

        # PTS > 60s suggests system-boot epoch (hours/days uptime)
        # PTS < 60s suggests stream-relative epoch
        if pts_seconds > 60:
            self._timestamp_source = "pts"
            self._first_pts = pts_seconds
        else:
            self._timestamp_source = "wall_clock"
            self._first_pts = None

    def _build_status(self) -> SourceStatus:
        """Build SourceStatus from current state."""
        return SourceStatus(
            device_path=self._device_path,
            resolution=self._config.resolution,
            actual_fps=self._calculate_fps(),
            first_pts_seconds=self._first_pts,
            timestamp_source=self._timestamp_source,
            warmup_frames_discarded=self._warmup_discarded,
        )

    def _cleanup(self) -> None:
        """Release device resources."""
        if self._container is not None:
            self._container.close()
            self._container = None
        self._stream = None
        self._frame_index = 0
        self._timestamps.clear()

    def _calculate_fps(self) -> float:
        """Calculate rolling average fps from recent timestamps."""
        if len(self._timestamps) < 2:
            return float(self._config.fps)  # Not enough data yet

        elapsed = self._timestamps[-1] - self._timestamps[0]
        if elapsed <= 0:
            return float(self._config.fps)

        return (len(self._timestamps) - 1) / elapsed

    def _get_frame_time(self, frame: av.VideoFrame) -> float:
        """Get timestamp for frame based on configured source."""
        if self._timestamp_source == "pts" and frame.pts is not None:
            if self._stream is None:
                return perf_counter()
            time_base = self._stream.time_base
            return float(frame.pts * time_base)
        else:
            return perf_counter()

    def __iter__(self) -> Iterator[FramePacket]:
        """
        Iterate over captured frames.

        Automatically calls start() if not already running.
        """
        if not self._is_running:
            self.start()

        if self._container is None:
            raise DeviceSourceError("Device not open after start()")

        for frame in self._container.decode(video=0):
            frame_time = self._get_frame_time(frame)
            self._timestamps.append(frame_time)

            bgr = frame_to_bgr(frame)

            packet = FramePacket(
                device_path=self._device_path,
                device_id=self._device_id,
                frame_index=self._frame_index,
                frame_time=frame_time,
                timestamp_source=self._timestamp_source,
                frame=bgr,
                fps=self._calculate_fps(),
            )

            self._frame_index += 1
            yield packet

    def __enter__(self) -> "DeviceSource":
        """Context manager entry - starts capture."""
        self.start()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        """Context manager exit - stops capture."""
        self.stop()
