"""Unified capture presenter for grid and focus modes."""

import logging
import time
from pathlib import Path

from PySide6.QtCore import QObject, QThread, QTimer, Signal
from PySide6.QtGui import QPixmap

from multiwebcam.pipeline.session import CaptureSession
from multiwebcam.sources.config import FrameSourceConfig
from multiwebcam.sources.controls import V4L2Control, query_controls, set_control
from multiwebcam.sources.discovery import FrameSourceOptions
from multiwebcam.ui.conversion import frame_to_pixmap

logger = logging.getLogger(__name__)

_PIXEL_FORMAT = "mjpeg"


class _StopRecordingWorker(QThread):
    """Worker thread for non-blocking recording stop.

    Signal named stop_completed (not finished) to avoid shadowing QThread.finished.
    """

    stop_completed = Signal(object)  # RecordingResult | None

    def __init__(self, session: CaptureSession) -> None:
        super().__init__()
        self._session = session

    def run(self) -> None:
        try:
            result = self._session.stop_recording()
        except Exception:
            logger.exception("Error during recording stop")
            result = None
        self.stop_completed.emit(result)


class CapturePresenter(QObject):
    """Long-lived presenter that switches between grid and focus modes.

    Created once alongside the session. Mode switches don't destroy the presenter.
    Recording logic is implemented once and works in both modes.
    """

    # Grid mode display
    frames_ready = Signal(object)          # dict[int, QPixmap]
    grid_stats_updated = Signal(object)    # dict[int, CameraStats]
    alignment_updated = Signal(object)     # AlignmentStats

    # Focus mode display
    frame_ready = Signal(QPixmap)
    focus_stats_updated = Signal(object)   # CameraStats

    # Focus mode configuration
    resolutions_available = Signal(object)
    framerates_available = Signal(object)
    initial_config_ready = Signal(str, str)
    config_applied = Signal(object)
    config_error = Signal(str)

    # Focus mode V4L2 controls
    controls_ready = Signal(object)        # list[V4L2Control]
    control_persist_requested = Signal(str, int)
    controls_cleared = Signal()

    # Recording (shared across modes)
    recording_started = Signal()
    recording_stopping = Signal()          # stop initiated, drain in progress
    recording_stopped = Signal()           # stop complete
    recording_duration = Signal(float)     # elapsed seconds
    recording_queue_depth = Signal(object) # dict[int, int]: source_id -> depth

    def __init__(
        self,
        session: CaptureSession,
        source_id_lookup: dict[str, int],
        grid_poll_ms: int = 33,
        focus_poll_ms: int = 33,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._session = session
        self._source_id_lookup = source_id_lookup
        self._grid_poll_ms = grid_poll_ms
        self._focus_poll_ms = focus_poll_ms

        self._mode: str = "idle"
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._on_poll)

        self._focused_device_path: str | None = None
        self._focused_source_id: int | None = None
        self._source_options: FrameSourceOptions | None = None
        self._current_config: FrameSourceConfig | None = None
        self._current_controls: list[V4L2Control] = []

        self._mirror: bool = False

        self._stop_worker: _StopRecordingWorker | None = None
        self._recording_start_time: float | None = None
        self._recording_device_paths: list[str] = []

    @property
    def focused_device_path(self) -> str | None:
        return self._focused_device_path

    @property
    def focused_source_id(self) -> int | None:
        return self._focused_source_id

    @property
    def mirror(self) -> bool:
        return self._mirror

    def set_mirror(self, enabled: bool) -> None:
        self._mirror = enabled

    @property
    def mode(self) -> str:
        return self._mode

    def enter_grid_mode(self) -> None:
        """Switch to grid mode -- resume all cameras, start grid polling."""
        if self._session.is_recording or self._stop_worker is not None:
            raise RuntimeError("Cannot switch mode while recording or stopping")
        self._session.resume_all()
        self._focused_device_path = None
        self._focused_source_id = None
        self._mode = "grid"
        self._timer.start(self._grid_poll_ms)

    def enter_focus_mode(
        self,
        device_path: str,
        source_id: int,
        source_options: FrameSourceOptions | None = None,
        current_config: FrameSourceConfig | None = None,
    ) -> None:
        """Switch to focus mode -- pause others, start focus polling."""
        if self._session.is_recording or self._stop_worker is not None:
            raise RuntimeError("Cannot switch mode while recording or stopping")
        self._session.resume_all()
        self._session.pause_all_except(device_path)
        self._focused_device_path = device_path
        self._focused_source_id = source_id
        self._source_options = source_options
        self._current_config = current_config
        self._mode = "focus"
        self._timer.start(self._focus_poll_ms)

        if source_options is not None and current_config is not None:
            self._emit_initial_capabilities()
        self._emit_controls()

    def set_grid_poll_interval(self, ms: int) -> None:
        """Change the grid mode polling interval."""
        self._grid_poll_ms = ms
        if self._mode == "grid":
            self._timer.setInterval(ms)

    # --- Recording lifecycle ---

    def start_recording(self, output_dir: Path, cam_ids: dict[str, int] | None = None) -> None:
        """Start recording. cam_ids defaults based on current mode."""
        if self._stop_worker is not None:
            return

        if cam_ids is None:
            if self._mode == "focus":
                cam_ids = {self._focused_device_path: self._focused_source_id}
            else:
                cam_ids = dict(self._source_id_lookup.items())

        self._session.start_recording(output_dir, cam_ids=cam_ids)
        self._recording_device_paths = list(cam_ids.keys())
        self._recording_start_time = time.monotonic()
        self.recording_started.emit()

    def stop_recording(self) -> None:
        """Stop recording asynchronously. Emits recording_stopping immediately."""
        if self._stop_worker is not None:
            return
        if not self._session.is_recording:
            return

        self.recording_stopping.emit()
        self._stop_worker = _StopRecordingWorker(self._session)
        self._stop_worker.stop_completed.connect(self._on_stop_complete)
        self._stop_worker.start()

    def _on_stop_complete(self, result: object) -> None:
        """Handle async stop completion on main thread."""
        if self._stop_worker is not None:
            self._stop_worker.wait()
            self._stop_worker = None
        self._recording_device_paths = []
        self._recording_start_time = None
        self.recording_stopped.emit()

    def shutdown(self) -> None:
        """Stop everything. Called once during app close."""
        self._timer.stop()
        if self._stop_worker is not None:
            self._stop_worker.wait()
            self._stop_worker = None
        if self._session.is_recording:
            self._session.stop_recording()
        self._mode = "idle"

    # --- Poll ---

    def _on_poll(self) -> None:
        if self._mode == "grid":
            self._poll_grid()
        elif self._mode == "focus":
            self._poll_focus()
        self._poll_recording()

    def _poll_grid(self) -> None:
        frames = self._session.get_latest_frames()
        pixmaps = {}
        for device_path, packet in frames.items():
            if packet is not None and device_path in self._source_id_lookup:
                source_id = self._source_id_lookup[device_path]
                pixmaps[source_id] = frame_to_pixmap(packet.frame, mirror=self._mirror)
        if pixmaps:
            self.frames_ready.emit(pixmaps)

        stats = self._session.get_camera_stats()
        if stats:
            stats_by_id = {
                self._source_id_lookup[p]: s
                for p, s in stats.items()
                if p in self._source_id_lookup
            }
            if stats_by_id:
                self.grid_stats_updated.emit(stats_by_id)

        alignment = self._session.get_alignment_stats()
        if alignment:
            self.alignment_updated.emit(alignment)

    def _poll_focus(self) -> None:
        frames = self._session.get_latest_frames()
        packet = frames.get(self._focused_device_path)
        if packet is not None:
            self.frame_ready.emit(frame_to_pixmap(packet.frame, mirror=self._mirror))

        stats = self._session.get_camera_stats()
        if stats and self._focused_device_path in stats:
            self.focus_stats_updated.emit(stats[self._focused_device_path])

    def _poll_recording(self) -> None:
        """Emit recording signals. Works during both recording and drain."""
        is_recording = self._session.is_recording
        is_draining = self._stop_worker is not None

        if not is_recording and not is_draining:
            return

        # Duration (only while actively recording, not during drain)
        if is_recording and self._recording_start_time is not None:
            elapsed = time.monotonic() - self._recording_start_time
            self.recording_duration.emit(elapsed)

        # Queue depths (during recording AND drain)
        if self._recording_device_paths:
            depths = self._session.get_queue_sizes(self._recording_device_paths)
            if depths:
                depths_by_id = {
                    self._source_id_lookup[p]: d
                    for p, d in depths.items()
                    if p in self._source_id_lookup
                }
                self.recording_queue_depth.emit(depths_by_id)

    # --- Focus mode capabilities ---

    def _emit_initial_capabilities(self) -> None:
        if self._source_options is None or self._current_config is None:
            return

        resolutions = self._source_options.resolutions(_PIXEL_FORMAT)
        res_strings = sorted(
            [f"{w}x{h}" for w, h in resolutions],
            key=lambda s: int(s.split("x")[0]),
            reverse=True,
        )
        self.resolutions_available.emit(res_strings)

        w, h = self._current_config.resolution
        fps_list = self._source_options.framerates(_PIXEL_FORMAT, w, h)
        fps_strings = [str(int(f)) for f in fps_list]
        self.framerates_available.emit(fps_strings)

        self.initial_config_ready.emit(
            f"{w}x{h}",
            str(self._current_config.fps),
        )

    def on_resolution_selected(self, resolution_str: str) -> None:
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
        self._current_config = new_config
        self.config_applied.emit(new_config)

    def apply_config_error(self, error: str) -> None:
        self.config_error.emit(error)

    # --- V4L2 controls ---

    def _emit_controls(self) -> None:
        if self._focused_device_path is None:
            return
        controls = query_controls(self._focused_device_path)
        if controls:
            self._current_controls = controls
            self.controls_ready.emit(controls)

    def on_control_changed(self, name: str, value: int) -> None:
        if self._focused_device_path and set_control(self._focused_device_path, name, value):
            self.control_persist_requested.emit(name, value)

    def on_restore_defaults(self) -> None:
        if self._focused_device_path is None:
            return
        for ctrl in self._current_controls:
            if ctrl.default is not None:
                set_control(self._focused_device_path, ctrl.name, ctrl.default)
        self.controls_cleared.emit()
        self._emit_controls()
