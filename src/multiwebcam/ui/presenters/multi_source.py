"""Multi-source presenter for grid mode."""

from pathlib import Path

from PySide6.QtCore import QObject, QTimer, Signal
from PySide6.QtGui import QPixmap

from multiwebcam.pipeline.session import CaptureSession
from multiwebcam.recording.recorder import RecordingResult
from multiwebcam.ui.conversion import frame_to_pixmap


class MultiSourcePresenter(QObject):
    """Presenter for grid mode - shows all sources simultaneously.

    Handles recording start/stop and emits batched frame updates.
    """

    # Use 'object' for complex Python types - Qt can't serialize dicts directly
    frames_ready = Signal(object)  # dict[int, QPixmap]: source_id -> QPixmap
    stats_updated = Signal(object)  # dict[int, CameraStats]: source_id -> CameraStats
    alignment_updated = Signal(object)  # AlignmentStats
    recording_started = Signal()
    recording_stopped = Signal(object)  # RecordingResult

    def __init__(
        self,
        session: CaptureSession,
        source_id_lookup: dict[str, int],  # device_path -> source_id
        poll_ms: int = 33,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._session = session
        self._source_id_lookup = source_id_lookup
        self._poll_ms = poll_ms
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._on_poll)
        self._active = False

    def activate(self) -> None:
        """Start presenting - resumes all sources, starts polling."""
        if self._active:
            return
        self._session.resume_all()
        self._timer.start(self._poll_ms)
        self._active = True

    def deactivate(self) -> None:
        """Stop presenting - stops polling (sources keep running)."""
        if not self._active:
            return
        self._timer.stop()
        self._active = False

    @property
    def is_active(self) -> bool:
        return self._active

    def start_recording(self, output_dir: Path) -> None:
        """Start recording all sources."""
        # Build cam_ids mapping for output filenames (Caliscope compatibility)
        # source_id maps to cam_id, which determines cam_N.mp4 filename
        cam_ids = {
            device_path: source_id for device_path, source_id in self._source_id_lookup.items()
        }
        self._session.start_recording(output_dir, cam_ids=cam_ids)
        self.recording_started.emit()

    def stop_recording(self) -> RecordingResult | None:
        """Stop recording and return result."""
        result = self._session.stop_recording()
        if result:
            self.recording_stopped.emit(result)
        return result

    @property
    def is_recording(self) -> bool:
        return self._session.is_recording

    def _on_poll(self) -> None:
        """Timer callback - fetch frames and emit signals."""
        # Get frames and convert to pixmaps keyed by source_id
        frames = self._session.get_latest_frames()
        pixmaps: dict[int, QPixmap] = {}

        for device_path, packet in frames.items():
            if packet is not None and device_path in self._source_id_lookup:
                source_id = self._source_id_lookup[device_path]
                pixmaps[source_id] = frame_to_pixmap(packet.frame)

        if pixmaps:
            self.frames_ready.emit(pixmaps)

        # Emit stats keyed by source_id
        stats = self._session.get_camera_stats()
        if stats:
            stats_by_id = {
                self._source_id_lookup[path]: stat
                for path, stat in stats.items()
                if path in self._source_id_lookup
            }
            if stats_by_id:
                self.stats_updated.emit(stats_by_id)

        # Emit alignment stats
        alignment = self._session.get_alignment_stats()
        if alignment:
            self.alignment_updated.emit(alignment)
