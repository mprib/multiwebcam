"""Focus view for single source with detailed controls."""

from PySide6.QtCore import Signal
from PySide6.QtGui import QFont, QPixmap
from PySide6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from multiwebcam.pipeline.report import CameraStats
from multiwebcam.sources.controls import V4L2Control
from multiwebcam.ui.views.aspect_ratio_label import AspectRatioLabel
from multiwebcam.ui.views.control_panel import ControlPanel


class FocusView(QWidget):
    """Large preview of single source with configuration panel.

    Format is locked to MJPEG (lower USB bandwidth, universal support).
    Only resolution and framerate are user-configurable.

    Signals:
        back_requested: User wants to return to grid view
        resolution_selected: User changed resolution combo
        apply_requested: User clicked Apply button
    """

    back_requested = Signal()
    resolution_selected = Signal(str)
    apply_requested = Signal()
    record_requested = Signal()
    stop_requested = Signal()

    def __init__(self, source_id: int, label: str, parent=None):
        super().__init__(parent)
        self._source_id = source_id
        self._control_panel: ControlPanel | None = None

        # Main horizontal layout: video on left, settings panel on right
        main_layout = QHBoxLayout(self)

        # Left: Video display (75% width)
        self._frame_label = AspectRatioLabel()
        self._frame_label.setMinimumSize(640, 480)
        main_layout.addWidget(self._frame_label, stretch=3)

        # Right: Settings panel (25% width)
        self._panel_layout = QVBoxLayout()
        main_layout.addLayout(self._panel_layout, stretch=1)

        # Configuration section header
        config_header = QLabel("Configuration")
        config_header_font = QFont()
        config_header_font.setBold(True)
        config_header.setFont(config_header_font)
        self._panel_layout.addWidget(config_header)

        # Configuration controls using QFormLayout
        config_form = QFormLayout()
        self._panel_layout.addLayout(config_form)

        self._resolution_combo = QComboBox()
        config_form.addRow("Resolution:", self._resolution_combo)

        self._framerate_combo = QComboBox()
        config_form.addRow("Framerate:", self._framerate_combo)

        # Apply button
        self._apply_btn = QPushButton("Apply")
        self._panel_layout.addWidget(self._apply_btn)

        # Recording buttons
        recording_layout = QHBoxLayout()
        self._record_btn = QPushButton("Record")
        self._stop_btn = QPushButton("Stop")
        self._stop_btn.setEnabled(False)
        recording_layout.addWidget(self._record_btn)
        recording_layout.addWidget(self._stop_btn)
        self._panel_layout.addLayout(recording_layout)

        # Separator spacing
        self._panel_layout.addSpacing(20)

        # Source info label
        self._info_label = QLabel(f"{label} (source {source_id})")
        self._panel_layout.addWidget(self._info_label)

        # Stats label
        self._stats_label = QLabel("-- fps | -- jitter")
        self._panel_layout.addWidget(self._stats_label)

        # Push back button to bottom
        self._panel_layout.addStretch()

        # Back button
        self._back_btn = QPushButton("Back to Grid")
        self._panel_layout.addWidget(self._back_btn)

        # Wire up signals
        self._resolution_combo.currentTextChanged.connect(self.resolution_selected.emit)
        self._apply_btn.clicked.connect(self.apply_requested.emit)
        self._record_btn.clicked.connect(self.record_requested.emit)
        self._stop_btn.clicked.connect(self.stop_requested.emit)
        self._back_btn.clicked.connect(self.back_requested.emit)

    @property
    def source_id(self) -> int:
        return self._source_id

    def display_frame(self, pixmap: QPixmap) -> None:
        """Update the displayed frame."""
        self._frame_label.display_pixmap(pixmap)

    def update_stats(self, stats: CameraStats) -> None:
        """Update stats display."""
        self._stats_label.setText(f"{stats.measured_fps:.1f} fps | {stats.jitter_ms:.1f}ms jitter")

    def populate_resolutions(self, resolutions: list[str]) -> None:
        """Populate resolution combo. Blocks signals during population."""
        self._resolution_combo.blockSignals(True)
        self._resolution_combo.clear()
        self._resolution_combo.addItems(resolutions)
        self._resolution_combo.blockSignals(False)

    def populate_framerates(self, framerates: list[str]) -> None:
        """Populate framerate combo. Blocks signals during population."""
        self._framerate_combo.blockSignals(True)
        self._framerate_combo.clear()
        self._framerate_combo.addItems(framerates)
        self._framerate_combo.blockSignals(False)

    def set_current_config(self, resolution: str, framerate: str) -> None:
        """Set current selection in combos without triggering signals."""
        self._resolution_combo.blockSignals(True)
        self._framerate_combo.blockSignals(True)

        self._resolution_combo.setCurrentText(resolution)
        self._framerate_combo.setCurrentText(framerate)

        self._resolution_combo.blockSignals(False)
        self._framerate_combo.blockSignals(False)

    def set_config_enabled(self, enabled: bool) -> None:
        """Enable/disable all config controls (disabled during recording)."""
        self._resolution_combo.setEnabled(enabled)
        self._framerate_combo.setEnabled(enabled)
        self._apply_btn.setEnabled(enabled)

    @property
    def selected_resolution(self) -> tuple[int, int]:
        """Parse 'WxH' string back to tuple."""
        text = self._resolution_combo.currentText()
        if not text or "x" not in text:
            return (0, 0)
        w, h = text.split("x")
        return (int(w), int(h))

    @property
    def selected_framerate(self) -> int:
        """Return currently selected framerate."""
        text = self._framerate_combo.currentText()
        return int(text) if text else 0

    def set_controls(self, controls: list[V4L2Control]) -> None:
        """Create and embed the control panel in the side panel.

        Inserts below the config section, above info/stats labels.
        Replaces any existing control panel.
        """
        # Remove existing panel if any
        if self._control_panel is not None:
            self._panel_layout.removeWidget(self._control_panel)
            self._control_panel.deleteLater()

        self._control_panel = ControlPanel(controls, self)
        # Insert before the info label
        idx = self._panel_layout.indexOf(self._info_label)
        self._panel_layout.insertWidget(idx, self._control_panel)

    @property
    def control_panel(self) -> ControlPanel | None:
        """The embedded control panel, or None if not yet created."""
        return self._control_panel

    def set_recording(self, recording: bool) -> None:
        """Update UI state for recording mode.

        During recording: disable config controls, record, and back.
        Control panel stays functional (adjust exposure mid-recording).
        """
        self._record_btn.setEnabled(not recording)
        self._stop_btn.setEnabled(recording)
        self.set_config_enabled(not recording)
        self._back_btn.setEnabled(not recording)
