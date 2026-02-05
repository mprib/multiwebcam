"""Single source presenter for focus mode."""

from PySide6.QtCore import QObject, QTimer, Signal
from PySide6.QtGui import QPixmap

from multiwebcam.pipeline.session import CaptureSession
from multiwebcam.ui.conversion import frame_to_pixmap


class SingleSourcePresenter(QObject):
    """Presenter for focus mode - shows one source with detailed controls.

    Pauses other sources when active to reduce CPU load.
    Emits signals for view updates - never calls view methods directly.
    """

    frame_ready = Signal(QPixmap)
    stats_updated = Signal(object)  # SourceStats dataclass

    def __init__(
        self,
        session: CaptureSession,
        device_path: str,
        poll_ms: int = 33,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._session = session
        self._device_path = device_path
        self._poll_ms = poll_ms
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._on_poll)
        self._active = False

    def activate(self) -> None:
        """Start presenting - pauses other sources, starts polling."""
        if self._active:
            return
        self._session.pause_all_except(self._device_path)
        self._timer.start(self._poll_ms)
        self._active = True

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
