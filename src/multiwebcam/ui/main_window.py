"""Main application window with view switching."""

import logging
from pathlib import Path

from PySide6.QtWidgets import QMainWindow, QStackedWidget

from multiwebcam.ui.coordinator import CaptureCoordinator

logger = logging.getLogger(__name__)


class MainWindow(QMainWindow):
    """Main application window with view switching.

    Owns the CaptureCoordinator and manages view transitions between
    grid mode (all sources) and focus mode (single source).
    """

    def __init__(self, project_path: Path, parent=None) -> None:
        super().__init__(parent)
        self._coordinator = CaptureCoordinator(project_path)
        self._coordinator.initialize()

        self._stack = QStackedWidget()
        self.setCentralWidget(self._stack)

        self._show_grid_view()
        self._coordinator.start()

    def _show_grid_view(self) -> None:
        self._cleanup_views()
        try:
            view = self._coordinator.create_grid_view()
        except RuntimeError:
            logger.exception("Failed to enter grid mode")
            return
        view.focus_requested.connect(self._on_focus_requested)
        self._stack.addWidget(view)
        self._stack.setCurrentWidget(view)

    def _show_focus_view(self, source_id: int) -> None:
        self._cleanup_views()
        try:
            view = self._coordinator.create_focus_view(source_id)
        except (ValueError, RuntimeError):
            logger.exception(f"Failed to enter focus mode for source {source_id}")
            self._show_grid_view()
            return
        view.back_requested.connect(self._show_grid_view)
        self._stack.addWidget(view)
        self._stack.setCurrentWidget(view)

    def _on_focus_requested(self, source_id: int) -> None:
        self._show_focus_view(source_id)

    def _cleanup_views(self) -> None:
        """Remove old views from stack."""
        while self._stack.count() > 0:
            widget = self._stack.widget(0)
            self._stack.removeWidget(widget)
            widget.deleteLater()

    def closeEvent(self, event) -> None:
        self._cleanup_views()
        self._coordinator.stop()
        event.accept()
