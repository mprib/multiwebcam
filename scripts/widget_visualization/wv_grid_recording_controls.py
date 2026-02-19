"""Visual test for proposed GridView recording destination controls.

Layout proposal:
  - Destination row (above action row): [Extrinsic Calibration cb] [Recording name: input] <stretch> [dest summary] [Open Folder]
  - Action row (existing): [Record] [Stop] <stretch> [duration] [Refresh: combo] [Mirror]
  - Status row: alignment stats label

The destination row shows WHERE recordings go. The action row shows WHAT to do.
When "Extrinsic Calibration" is checked, the name input hides (destination is implicit).
When unchecked, a QLineEdit appears with an auto-generated default name.

States captured:
  01: Default state -- extrinsic unchecked, recording name visible
  02: Extrinsic checked -- name input hidden
  03: Recording in progress -- destination controls disabled
  04: Stopping -- everything disabled
  05: Full window with 4 mock camera tiles
  06: Controls-only close-up (custom recording)
  07: Controls close-up with extrinsic checked

Usage:
    python scripts/widget_visualization/wv_grid_recording_controls.py
    xvfb-run --auto-servernum python scripts/widget_visualization/wv_grid_recording_controls.py
"""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))
sys.path.insert(0, str(Path(__file__).parent))

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from utils import capture_widget, clear_output_dir, process_events_for


class MockSourceTile(QFrame):
    """Simplified stand-in for SourceTile -- just a colored rectangle."""

    def __init__(self, source_id: int, label: str, color: QColor, parent=None):
        super().__init__(parent)
        self.setFrameStyle(QFrame.Shape.Box | QFrame.Shadow.Sunken)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(2)

        frame_label = QLabel()
        frame_label.setMinimumSize(280, 180)
        frame_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        pixmap = QPixmap(280, 180)
        pixmap.fill(color)
        painter = QPainter(pixmap)
        painter.setPen(Qt.GlobalColor.white)
        font = painter.font()
        font.setPointSize(20)
        font.setBold(True)
        painter.setFont(font)
        painter.drawText(pixmap.rect(), Qt.AlignmentFlag.AlignCenter, f"cam_{source_id}")
        painter.end()
        frame_label.setPixmap(pixmap)
        layout.addWidget(frame_label)

        info_row = QHBoxLayout()
        name_label = QLabel(label)
        name_label.setStyleSheet("font-weight: bold;")
        res_label = QLabel("1280x720")
        res_label.setStyleSheet("color: #AAAAAA;")
        ignore_cb = QCheckBox("Ignore")
        info_row.addWidget(name_label)
        info_row.addStretch()
        info_row.addWidget(ignore_cb)
        info_row.addWidget(res_label)
        layout.addLayout(info_row)

        stats_label = QLabel("29.8 fps | 2.1ms jitter")
        stats_label.setStyleSheet("font-size: 10px; color: #888888;")
        layout.addWidget(stats_label)

        focus_btn = QPushButton("Focus")
        layout.addWidget(focus_btn)


class GridViewProposal(QWidget):
    """Proposed GridView layout with recording destination controls."""

    focus_requested = Signal(int)
    record_requested = Signal()
    stop_requested = Signal()
    poll_interval_changed = Signal(int)
    mirror_toggled = Signal(bool)
    ignore_toggled = Signal(int, bool)

    open_folder_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)

        main_layout = QVBoxLayout(self)

        # Grid for source tiles
        self._grid_widget = QWidget()
        self._grid_layout = QGridLayout(self._grid_widget)
        main_layout.addWidget(self._grid_widget, stretch=1)

        # Separator
        separator = QFrame()
        separator.setFrameShape(QFrame.Shape.HLine)
        separator.setFrameShadow(QFrame.Shadow.Sunken)
        main_layout.addWidget(separator)

        # Destination row (NEW)
        dest_row = QHBoxLayout()
        dest_row.setContentsMargins(0, 4, 0, 4)

        self._extrinsic_cb = QCheckBox("Extrinsic Calibration")
        self._extrinsic_cb.setToolTip(
            "When checked, recordings are saved to calibration/extrinsic/.\n"
            "When unchecked, recordings are saved to recordings/<name>/."
        )
        dest_row.addWidget(self._extrinsic_cb)
        dest_row.addSpacing(12)

        self._name_label = QLabel("Recording name:")
        self._name_label.setStyleSheet("color: #AAAAAA;")
        dest_row.addWidget(self._name_label)

        self._name_input = QLineEdit("recording_001")
        self._name_input.setMinimumWidth(160)
        self._name_input.setMaximumWidth(240)
        self._name_input.setPlaceholderText("e.g. trial_001")
        dest_row.addWidget(self._name_input)

        self._dest_summary = QLabel("")
        self._dest_summary.setStyleSheet(
            "color: #888888; font-style: italic; font-size: 11px;"
        )
        dest_row.addWidget(self._dest_summary)

        dest_row.addStretch()

        self._open_folder_btn = QPushButton("Open Folder")
        self._open_folder_btn.setToolTip("Open project folder in file manager")
        self._open_folder_btn.setFlat(True)
        self._open_folder_btn.setStyleSheet(
            "QPushButton { color: #0078d4; text-decoration: underline;"
            "  padding: 4px 8px; }"
            "QPushButton:hover { color: #106ebe; }"
            "QPushButton:pressed { color: #005a9e; }"
        )
        dest_row.addWidget(self._open_folder_btn)

        main_layout.addLayout(dest_row)

        # Action row (existing controls)
        action_row = QHBoxLayout()
        action_row.setContentsMargins(0, 0, 0, 0)

        self._record_btn = QPushButton("Record")
        self._record_btn.setStyleSheet(
            "QPushButton {"
            "  background-color: #c0392b; color: white; border: none;"
            "  border-radius: 4px; padding: 8px 20px; font-weight: bold;"
            "}"
            "QPushButton:hover { background-color: #e74c3c; }"
            "QPushButton:pressed { background-color: #922b21; }"
            "QPushButton:disabled { background-color: #555555; color: #888888; }"
        )
        self._stop_btn = QPushButton("Stop")
        self._stop_btn.setEnabled(False)
        self._stop_btn.setStyleSheet(
            "QPushButton {"
            "  background-color: #555555; color: white; border: none;"
            "  border-radius: 4px; padding: 8px 20px; font-weight: bold;"
            "}"
            "QPushButton:hover { background-color: #666666; }"
            "QPushButton:pressed { background-color: #444444; }"
            "QPushButton:disabled { background-color: #333333; color: #666666; }"
        )
        self._duration_label = QLabel("00:00:00")

        action_row.addWidget(self._record_btn)
        action_row.addWidget(self._stop_btn)
        action_row.addStretch()
        action_row.addWidget(self._duration_label)
        action_row.addSpacing(16)
        action_row.addWidget(QLabel("Refresh:"))
        self._fps_combo = QComboBox()
        self._fps_combo.addItems(["15 fps", "30 fps", "60 fps"])
        self._fps_combo.setCurrentText("30 fps")
        action_row.addWidget(self._fps_combo)
        action_row.addSpacing(16)
        self._mirror_cb = QCheckBox("Mirror")
        action_row.addWidget(self._mirror_cb)

        main_layout.addLayout(action_row)

        # Status bar
        self._status_label = QLabel("Spread: 12.3ms | Complete: 98%")
        self._status_label.setStyleSheet("color: #888888; font-size: 11px;")
        main_layout.addWidget(self._status_label)

        # Wire signals
        self._extrinsic_cb.toggled.connect(self._on_extrinsic_toggled)
        self._name_input.textChanged.connect(self._on_name_changed)
        self._open_folder_btn.clicked.connect(self.open_folder_requested.emit)
        self._record_btn.clicked.connect(self.record_requested.emit)
        self._stop_btn.clicked.connect(self.stop_requested.emit)
        self._mirror_cb.toggled.connect(self.mirror_toggled.emit)

        self._update_dest_summary()

    def _on_extrinsic_toggled(self, checked: bool) -> None:
        self._name_label.setVisible(not checked)
        self._name_input.setVisible(not checked)
        self._update_dest_summary()

    def _on_name_changed(self, text: str) -> None:
        self._update_dest_summary()

    def _update_dest_summary(self) -> None:
        if self._extrinsic_cb.isChecked():
            self._dest_summary.setText("-> calibration/extrinsic/")
        else:
            name = self._name_input.text() or "untitled"
            self._dest_summary.setText(f"-> recordings/{name}/")

    def set_recording_name(self, name: str) -> None:
        self._name_input.blockSignals(True)
        self._name_input.setText(name)
        self._name_input.blockSignals(False)
        self._update_dest_summary()

    def set_destination_enabled(self, enabled: bool) -> None:
        self._extrinsic_cb.setEnabled(enabled)
        self._name_input.setEnabled(enabled)

    def set_recording(self, is_recording: bool) -> None:
        self._record_btn.setEnabled(not is_recording)
        self._stop_btn.setEnabled(is_recording)
        self._stop_btn.setText("Stop")
        self.set_destination_enabled(not is_recording)
        if not is_recording:
            self._duration_label.setText("00:00:00")

    def set_stopping(self) -> None:
        self._record_btn.setEnabled(False)
        self._stop_btn.setEnabled(False)
        self._stop_btn.setText("Stopping...")
        self.set_destination_enabled(False)

    def add_mock_tile(self, source_id: int, label: str, color: QColor) -> None:
        tile = MockSourceTile(source_id, label, color)
        idx = self._grid_layout.count()
        row, col = divmod(idx, 3)
        self._grid_layout.addWidget(tile, row, col)


def main() -> None:
    clear_output_dir()
    app = QApplication(sys.argv)

    print("=" * 60)
    print("GRID VIEW RECORDING DESTINATION CONTROLS")
    print("=" * 60)

    # Test 1: Default state
    print("\n[1] Default state: extrinsic unchecked, recording name visible\n")
    view = GridViewProposal()
    view.add_mock_tile(0, "HD Pro Webcam C920", QColor(30, 80, 140))
    view.add_mock_tile(1, "USB Camera", QColor(80, 30, 140))
    view.add_mock_tile(2, "Logitech BRIO", QColor(30, 140, 80))
    view.resize(1000, 700)
    view.show()
    process_events_for(200)
    capture_widget(view, "01_default_custom_recording.png")
    view.close()

    # Test 2: Extrinsic checked
    print("\n[2] Extrinsic calibration checked: name input hidden\n")
    view = GridViewProposal()
    view.add_mock_tile(0, "HD Pro Webcam C920", QColor(30, 80, 140))
    view.add_mock_tile(1, "USB Camera", QColor(80, 30, 140))
    view.add_mock_tile(2, "Logitech BRIO", QColor(30, 140, 80))
    view._extrinsic_cb.setChecked(True)
    view.resize(1000, 700)
    view.show()
    process_events_for(200)
    capture_widget(view, "02_extrinsic_checked.png")
    view.close()

    # Test 3: Recording in progress
    print("\n[3] Recording in progress: destination controls disabled\n")
    view = GridViewProposal()
    view.add_mock_tile(0, "HD Pro Webcam C920", QColor(30, 80, 140))
    view.add_mock_tile(1, "USB Camera", QColor(80, 30, 140))
    view.add_mock_tile(2, "Logitech BRIO", QColor(30, 140, 80))
    view.set_recording(True)
    view._duration_label.setText("00:01:23")
    view.resize(1000, 700)
    view.show()
    process_events_for(200)
    capture_widget(view, "03_recording_in_progress.png")
    view.close()

    # Test 4: Stopping
    print("\n[4] Stopping state: all controls disabled\n")
    view = GridViewProposal()
    view.add_mock_tile(0, "HD Pro Webcam C920", QColor(30, 80, 140))
    view.add_mock_tile(1, "USB Camera", QColor(80, 30, 140))
    view.add_mock_tile(2, "Logitech BRIO", QColor(30, 140, 80))
    view.set_stopping()
    view.resize(1000, 700)
    view.show()
    process_events_for(200)
    capture_widget(view, "04_stopping.png")
    view.close()

    # Test 5: 4 cameras, extrinsic
    print("\n[5] Four cameras, extrinsic mode\n")
    view = GridViewProposal()
    view.add_mock_tile(0, "HD Pro Webcam C920", QColor(30, 80, 140))
    view.add_mock_tile(1, "USB Camera", QColor(80, 30, 140))
    view.add_mock_tile(2, "Logitech BRIO", QColor(30, 140, 80))
    view.add_mock_tile(3, "Integrated Webcam", QColor(140, 80, 30))
    view._extrinsic_cb.setChecked(True)
    view.resize(1200, 800)
    view.show()
    process_events_for(200)
    capture_widget(view, "05_four_cameras_extrinsic.png")
    view.close()

    # Test 6: Controls close-up
    print("\n[6] Controls-only close-up\n")
    view = GridViewProposal()
    view.resize(900, 120)
    view.show()
    process_events_for(200)
    capture_widget(view, "06_controls_closeup.png")
    view.close()

    # Test 7: Controls close-up extrinsic
    print("\n[7] Controls close-up with extrinsic checked\n")
    view = GridViewProposal()
    view._extrinsic_cb.setChecked(True)
    view.resize(900, 120)
    view.show()
    process_events_for(200)
    capture_widget(view, "07_controls_closeup_extrinsic.png")
    view.close()

    print("\n" + "=" * 60)
    print("VERIFICATION COMPLETE")
    print("=" * 60)
    print("\nScreenshots saved to: scripts/widget_visualization/output/")


if __name__ == "__main__":
    main()
