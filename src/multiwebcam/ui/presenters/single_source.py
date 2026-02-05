"""Single source presenter for focus mode."""

from PySide6.QtCore import QObject, QTimer, Signal
from PySide6.QtGui import QPixmap

from multiwebcam.pipeline.session import CaptureSession
from multiwebcam.sources.config import FrameSourceConfig
from multiwebcam.sources.discovery import FrameSourceOptions
from multiwebcam.ui.conversion import frame_to_pixmap


class SingleSourcePresenter(QObject):
    """Presenter for focus mode - shows one source with detailed controls.

    Pauses other sources when active to reduce CPU load.
    Emits signals for view updates - never calls view methods directly.
    """

    frame_ready = Signal(QPixmap)
    stats_updated = Signal(object)  # SourceStats dataclass

    # Configuration signals
    config_change_requested = Signal(object)  # FrameSourceConfig to apply
    config_applied = Signal(object)           # FrameSourceConfig that was applied
    config_error = Signal(str)                # Error message
    resolutions_available = Signal(object)    # list[str] of "WxH" strings
    framerates_available = Signal(object)     # list[str] of fps strings

    def __init__(
        self,
        session: CaptureSession,
        device_path: str,
        source_options: FrameSourceOptions | None = None,
        current_config: FrameSourceConfig | None = None,
        poll_ms: int = 33,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._session = session
        self._device_path = device_path
        self._source_options = source_options
        self._current_config = current_config
        self._poll_ms = poll_ms
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._on_poll)
        self._active = False

        # Track pending format selection for cascading combos
        self._pending_format: str = (
            current_config.pixel_format if current_config else ""
        )

    def activate(self) -> None:
        """Start presenting - pauses other sources, starts polling."""
        if self._active:
            return
        self._session.pause_all_except(self._device_path)
        self._timer.start(self._poll_ms)
        self._active = True

        # Emit initial format/resolution/framerate options if available
        if self._source_options is not None:
            self._emit_initial_capabilities()

    def deactivate(self) -> None:
        """Stop presenting - resumes all sources, stops polling."""
        if not self._active:
            return
        self._timer.stop()
        self._session.resume_all()
        self._active = False

    @property
    def is_active(self) -> bool:
        return self._active

    @property
    def device_path(self) -> str:
        return self._device_path

    def _on_poll(self) -> None:
        """Timer callback - fetch frame and emit signals."""
        frames = self._session.get_latest_frames()
        frame_packet = frames.get(self._device_path)

        if frame_packet is not None:
            pixmap = frame_to_pixmap(frame_packet.frame)
            self.frame_ready.emit(pixmap)

        # Emit stats if available
        stats = self._session.get_camera_stats()
        if stats and self._device_path in stats:
            self.stats_updated.emit(stats[self._device_path])

    def _emit_initial_capabilities(self) -> None:
        """Emit format/resolution/framerate options for the current config."""
        if self._source_options is None or self._current_config is None:
            return

        # Emit resolutions for current format
        resolutions = self._source_options.resolutions(
            self._current_config.pixel_format
        )
        res_strings = sorted(
            [f"{w}x{h}" for w, h in resolutions],
            key=lambda s: int(s.split("x")[0]),
            reverse=True,
        )
        self.resolutions_available.emit(res_strings)

        # Emit framerates for current format + resolution
        w, h = self._current_config.resolution
        fps_list = self._source_options.framerates(
            self._current_config.pixel_format, w, h
        )
        fps_strings = [str(int(f)) for f in fps_list]
        self.framerates_available.emit(fps_strings)

    def on_format_selected(self, format_name: str) -> None:
        """Handle format combo change - cascade to resolution options."""
        if self._source_options is None:
            return

        # Update pending format for cascade
        self._pending_format = format_name

        # Emit available resolutions
        resolutions = self._source_options.resolutions(format_name)
        res_strings = sorted(
            [f"{w}x{h}" for w, h in resolutions],
            key=lambda s: int(s.split("x")[0]),
            reverse=True,
        )
        self.resolutions_available.emit(res_strings)

        # Also emit fps for first resolution
        if resolutions:
            first_res = sorted(resolutions, key=lambda r: r[0], reverse=True)[0]
            fps_list = self._source_options.framerates(
                format_name, first_res[0], first_res[1]
            )
            fps_strings = [str(int(f)) for f in fps_list]
            self.framerates_available.emit(fps_strings)

    def on_resolution_selected(self, resolution_str: str) -> None:
        """Handle resolution combo change - cascade to framerate options."""
        if (
            self._source_options is None
            or not resolution_str
            or "x" not in resolution_str
        ):
            return

        w, h = resolution_str.split("x")
        fps_list = self._source_options.framerates(
            self._pending_format, int(w), int(h)
        )
        fps_strings = [str(int(f)) for f in fps_list]
        self.framerates_available.emit(fps_strings)

    def request_config_change(
        self, pixel_format: str, resolution: tuple[int, int], fps: int
    ) -> None:
        """Build a new config from user selections and request the change."""
        new_config = FrameSourceConfig(
            resolution=resolution,
            fps=fps,
            pixel_format=pixel_format,
        )
        self.config_change_requested.emit(new_config)

    def apply_config_result(self, new_config: FrameSourceConfig) -> None:
        """Called when config change succeeds."""
        self._current_config = new_config
        self.config_applied.emit(new_config)

    def apply_config_error(self, error: str) -> None:
        """Called when config change fails."""
        self.config_error.emit(error)

    @property
    def available_formats(self) -> list[str]:
        """Get available formats for this source."""
        if self._source_options is None:
            return []
        return sorted(self._source_options.formats())
