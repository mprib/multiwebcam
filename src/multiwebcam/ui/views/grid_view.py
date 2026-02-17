"""Grid view showing all sources simultaneously."""

from PySide6.QtCore import Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from multiwebcam.pipeline.alignment import AlignmentStats
from multiwebcam.pipeline.report import CameraStats
from multiwebcam.ui.views.source_tile import SourceTile


class GridView(QWidget):
    """Displays all sources in a grid with recording controls.

    Signals:
        focus_requested(int): User wants to focus source with given source_id
        record_requested: User clicked record button
        stop_requested: User clicked stop button
        poll_interval_changed(int): User changed poll interval (milliseconds)
        ignore_toggled(int, bool): User toggled ignore for a source (source_id, ignored)
        mirror_toggled(bool): User toggled horizontal flip
    """

    focus_requested = Signal(int)  # source_id
    record_requested = Signal()
    stop_requested = Signal()
    poll_interval_changed = Signal(int)  # milliseconds
    mirror_toggled = Signal(bool)
    ignore_toggled = Signal(int, bool)  # source_id, ignored

    def __init__(self, parent=None):
        super().__init__(parent)
        self._tiles: dict[int, SourceTile] = {}
        self._ignored_source_ids: set[int] = set()

        # Main layout
        main_layout = QVBoxLayout(self)

        # Grid for source tiles
        self._grid_widget = QWidget()
        self._grid_layout = QGridLayout(self._grid_widget)
        main_layout.addWidget(self._grid_widget, stretch=1)

        # Recording controls
        controls = QHBoxLayout()
        self._record_btn = QPushButton("Record")
        self._stop_btn = QPushButton("Stop")
        self._stop_btn.setEnabled(False)
        self._duration_label = QLabel("00:00:00")

        self._record_btn.clicked.connect(self.record_requested.emit)
        self._stop_btn.clicked.connect(self.stop_requested.emit)

        controls.addWidget(self._record_btn)
        controls.addWidget(self._stop_btn)
        controls.addStretch()
        controls.addWidget(self._duration_label)
        controls.addSpacing(16)
        controls.addWidget(QLabel("Refresh:"))
        self._fps_combo = QComboBox()
        self._fps_combo.addItems(["15 fps", "30 fps", "60 fps"])
        self._fps_combo.setCurrentText("30 fps")
        self._fps_combo.currentTextChanged.connect(self._on_fps_changed)
        controls.addWidget(self._fps_combo)
        controls.addSpacing(16)
        self._mirror_cb = QCheckBox("Mirror")
        self._mirror_cb.toggled.connect(self.mirror_toggled.emit)
        controls.addWidget(self._mirror_cb)
        main_layout.addLayout(controls)

        # Status bar
        self._status_label = QLabel("Ready")
        main_layout.addWidget(self._status_label)

    def _on_fps_changed(self, text: str) -> None:
        fps = int(text.split()[0])
        self.poll_interval_changed.emit(1000 // fps)

    def add_source(self, source_id: int, label: str, ignore: bool = False) -> None:
        """Add a source tile to the grid."""
        tile = SourceTile(source_id, label, ignore=ignore)
        tile.focus_requested.connect(lambda sid=source_id: self.focus_requested.emit(sid))
        tile.ignore_toggled.connect(lambda ignored, sid=source_id: self._on_tile_ignore_toggled(sid, ignored))
        self._tiles[source_id] = tile
        if ignore:
            self._ignored_source_ids.add(source_id)
            self._update_record_enabled()

        # Arrange in grid (3 columns)
        idx = len(self._tiles) - 1
        row, col = divmod(idx, 3)
        self._grid_layout.addWidget(tile, row, col)

    def _on_tile_ignore_toggled(self, source_id: int, ignored: bool) -> None:
        if ignored:
            self._ignored_source_ids.add(source_id)
        else:
            self._ignored_source_ids.discard(source_id)
        self._update_record_enabled()
        self.ignore_toggled.emit(source_id, ignored)

    def _update_record_enabled(self) -> None:
        all_ignored = self._tiles and len(self._ignored_source_ids) >= len(self._tiles)
        self._record_btn.setEnabled(not all_ignored)

    def display_frames(self, frames: dict[int, QPixmap]) -> None:
        """Update frames for multiple sources."""
        for source_id, pixmap in frames.items():
            if source_id in self._tiles:
                self._tiles[source_id].display_frame(pixmap)

    def update_stats(self, stats: dict[int, CameraStats]) -> None:
        """Update stats for multiple sources."""
        for source_id, stat in stats.items():
            if source_id in self._tiles:
                self._tiles[source_id].update_stats(stat.measured_fps, stat.jitter_ms)

    def update_alignment(self, alignment: AlignmentStats | None) -> None:
        """Update alignment stats in status bar."""
        if alignment:
            self._status_label.setText(
                f"Spread: {alignment.mean_spread_ms:.1f}ms | "
                f"Complete: {alignment.complete_cluster_pct:.0f}%"
            )

    def set_recording(self, is_recording: bool) -> None:
        """Update UI for recording state."""
        self._record_btn.setEnabled(not is_recording)
        self._stop_btn.setEnabled(is_recording)
        self._stop_btn.setText("Stop")
        for source_id, tile in self._tiles.items():
            tile.set_focus_enabled(
                not is_recording, reason="Recording..." if is_recording else ""
            )
            if is_recording and source_id not in self._ignored_source_ids:
                tile.set_queue_visible(True)
            else:
                tile.set_queue_visible(False)
        if not is_recording:
            self._duration_label.setText("00:00:00")

    def set_stopping(self) -> None:
        """Recording stop in progress -- disable everything interactive."""
        self._record_btn.setEnabled(False)
        self._stop_btn.setEnabled(False)
        self._stop_btn.setText("Stopping...")
        for tile in self._tiles.values():
            tile.set_focus_enabled(False, reason="Stopping...")
            tile.set_ignore_enabled(False)

    def update_duration(self, seconds: float) -> None:
        """Update recording duration display."""
        h, rem = divmod(int(seconds), 3600)
        m, s = divmod(rem, 60)
        self._duration_label.setText(f"{h:02d}:{m:02d}:{s:02d}")

    def update_queue_depth(self, depths: dict[int, int]) -> None:
        """Update per-camera queue depth display."""
        for source_id, tile in self._tiles.items():
            depth = depths.get(source_id, 0)
            tile.set_queue_depth(depth)

    def set_mirror(self, enabled: bool) -> None:
        """Set mirror checkbox state without triggering signal."""
        self._mirror_cb.blockSignals(True)
        self._mirror_cb.setChecked(enabled)
        self._mirror_cb.blockSignals(False)

    def set_tile_resolution(self, source_id: int, resolution: str) -> None:
        """Set resolution label for a tile."""
        if source_id in self._tiles:
            self._tiles[source_id].set_resolution(resolution)
