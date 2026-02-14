"""Single source presenter for focus mode."""

from pathlib import Path

from PySide6.QtCore import QObject, QTimer, Signal
from PySide6.QtGui import QPixmap

from multiwebcam.pipeline.session import CaptureSession
from multiwebcam.sources.config import FrameSourceConfig
from multiwebcam.sources.controls import V4L2Control, query_controls, set_control
from multiwebcam.sources.discovery import FrameSourceOptions
from multiwebcam.ui.conversion import frame_to_pixmap

# All capture uses MJPEG — lower USB bandwidth, universally supported.
_PIXEL_FORMAT = "mjpeg"


class SingleSourcePresenter(QObject):
    """Presenter for focus mode - shows one source with detailed controls.

    Pauses other sources when active to reduce CPU load.
    Emits signals for view updates - never calls view methods directly.

    Format is locked to MJPEG. Only resolution and framerate are
    user-configurable.
    """

    frame_ready = Signal(QPixmap)
    stats_updated = Signal(object)  # CameraStats dataclass

    # Configuration signals
    config_applied = Signal(object)        # FrameSourceConfig that was applied
    config_error = Signal(str)             # Error message
    resolutions_available = Signal(object)  # list[str] of "WxH" strings
    framerates_available = Signal(object)   # list[str] of fps strings
    initial_config_ready = Signal(str, str)  # (resolution_str, fps_str) after combos populated

    # V4L2 control signals
    controls_ready = Signal(object)           # list[V4L2Control]
    control_persist_requested = Signal(str, int)  # (control_name, value) for coordinator to persist
    controls_cleared = Signal()               # All controls reset to defaults

    # Recording signals (see also: MultiSourcePresenter for parallel pattern)
    recording_started = Signal()
    recording_stopped = Signal()

    def __init__(
        self,
        session: CaptureSession,
        device_path: str,
        source_id: int,
        source_options: FrameSourceOptions | None = None,
        current_config: FrameSourceConfig | None = None,
        poll_ms: int = 33,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._session = session
        self._device_path = device_path
        self._source_id = source_id
        self._source_options = source_options
        self._current_config = current_config
        self._poll_ms = poll_ms
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._on_poll)
        self._active = False
        self._current_controls: list[V4L2Control] = []

    def activate(self) -> None:
        """Start presenting - pauses other sources, starts polling."""
        if self._active:
            return
        self._session.pause_all_except(self._device_path)
        self._timer.start(self._poll_ms)
        self._active = True

        # Emit initial resolution/framerate options if available
        if self._source_options is not None:
            self._emit_initial_capabilities()

        self._emit_controls()

    def deactivate(self) -> None:
        """Stop presenting - resumes all sources, stops polling."""
        if not self._active:
            return
        if self._session.is_recording:
            self.stop_recording()
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
        """Emit resolution/framerate options for MJPEG format."""
        if self._source_options is None or self._current_config is None:
            return

        resolutions = self._source_options.resolutions(_PIXEL_FORMAT)
        res_strings = sorted(
            [f"{w}x{h}" for w, h in resolutions],
            key=lambda s: int(s.split("x")[0]),
            reverse=True,
        )
        self.resolutions_available.emit(res_strings)

        # Emit framerates for current resolution
        w, h = self._current_config.resolution
        fps_list = self._source_options.framerates(_PIXEL_FORMAT, w, h)
        fps_strings = [str(int(f)) for f in fps_list]
        self.framerates_available.emit(fps_strings)

        # Emit current config AFTER combos are populated so view can select correctly
        self.initial_config_ready.emit(
            f"{w}x{h}",
            str(self._current_config.fps),
        )

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
            _PIXEL_FORMAT, int(w), int(h)
        )
        fps_strings = [str(int(f)) for f in fps_list]
        self.framerates_available.emit(fps_strings)

    def apply_config_result(self, new_config: FrameSourceConfig) -> None:
        """Called when config change succeeds."""
        self._current_config = new_config
        self.config_applied.emit(new_config)

    def apply_config_error(self, error: str) -> None:
        """Called when config change fails."""
        self.config_error.emit(error)

    def _emit_controls(self) -> None:
        """Query V4L2 controls for this device and emit them."""
        controls = query_controls(self._device_path)
        if controls:
            self._current_controls = controls
            self.controls_ready.emit(controls)

    def on_control_changed(self, name: str, value: int) -> None:
        """Handle control change from UI — apply to device and request persistence."""
        if set_control(self._device_path, name, value):
            self.control_persist_requested.emit(name, value)

    def on_restore_defaults(self) -> None:
        """Reset all V4L2 controls to hardware defaults and refresh UI."""
        for ctrl in self._current_controls:
            if ctrl.default is not None:
                set_control(self._device_path, ctrl.name, ctrl.default)
        self.controls_cleared.emit()
        self._emit_controls()

    def start_recording(self, output_dir: Path) -> None:
        """Start recording from this source only."""
        # See also: MultiSourcePresenter.start_recording (parallel pattern)
        cam_ids = {self._device_path: self._source_id}
        self._session.start_recording(output_dir, cam_ids=cam_ids)
        self.recording_started.emit()

    def stop_recording(self) -> None:
        """Stop recording."""
        result = self._session.stop_recording()
        if result:
            self.recording_stopped.emit()
