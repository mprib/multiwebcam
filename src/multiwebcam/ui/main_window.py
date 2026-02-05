"""Main application window with view switching."""

import logging
from pathlib import Path

from PySide6.QtCore import Qt
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
        self._project_path = project_path

        # Create coordinator (composition root for capture subsystem)
        self._coordinator = CaptureCoordinator(project_path)
        self._coordinator.initialize()

        # Central widget with stacked views
        self._stack = QStackedWidget()
        self.setCentralWidget(self._stack)

        # Track current presenter for cleanup
        self._current_presenter = None

        # Start with grid view
        self._show_grid_view()

        # Start capture
        self._coordinator.start()

    def _show_grid_view(self) -> None:
        """Switch to grid view showing all sources."""
        self._cleanup_current()

        view, presenter = self._coordinator.create_grid_view()
        view.focus_requested.connect(self._on_focus_requested)

        self._stack.addWidget(view)
        self._stack.setCurrentWidget(view)
        presenter.activate()
        self._current_presenter = presenter

    def _show_focus_view(self, source_id: int) -> None:
        """Switch to focus view for a specific source."""
        self._cleanup_current()

        view, presenter = self._coordinator.create_focus_view(source_id)
        view.back_requested.connect(self._show_grid_view)

        self._stack.addWidget(view)
        self._stack.setCurrentWidget(view)
        presenter.activate()
        self._current_presenter = presenter

    def _on_focus_requested(self, source_id: int) -> None:
        """Handle focus request from grid view."""
        try:
            self._show_focus_view(source_id)
        except ValueError as e:
            logger.warning(f"Cannot focus source {source_id}: {e}")

    def _cleanup_current(self) -> None:
        """Deactivate current presenter and remove old views from stack."""
        if self._current_presenter:
            self._current_presenter.deactivate()
            self._current_presenter = None

        # Remove old widgets from stack to avoid memory leaks
        while self._stack.count() > 0:
            widget = self._stack.widget(0)
            self._stack.removeWidget(widget)
            widget.deleteLater()

    def closeEvent(self, event) -> None:
        """Clean shutdown on window close."""
        self._cleanup_current()
        self._coordinator.stop()
        event.accept()
