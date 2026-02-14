"""Test that UI infrastructure imports correctly."""

import numpy as np
import pytest
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QApplication

from multiwebcam.profiles import SourceProfile
from multiwebcam.ui import CaptureCoordinator, FocusView, GridView, SourceInfo, SourceTile, frame_to_pixmap
from multiwebcam.ui.presenters import CapturePresenter


@pytest.fixture(scope="module")
def qapp():
    """Create QApplication for tests that need Qt widgets."""
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    yield app


def test_frame_to_pixmap(qapp):
    """frame_to_pixmap converts BGR numpy array to QPixmap."""
    # Create a small test image (BGR)
    frame = np.zeros((100, 100, 3), dtype=np.uint8)
    frame[25:75, 25:75] = [255, 0, 0]  # Blue square in BGR

    pixmap = frame_to_pixmap(frame)

    assert isinstance(pixmap, QPixmap)
    assert pixmap.width() == 100
    assert pixmap.height() == 100


def test_source_info_dataclass():
    """SourceInfo can be constructed with profile and options."""
    profile = SourceProfile.with_defaults(source_id=0, bus_info="usb-0000:00:14.0-1")

    info = SourceInfo(
        source_id=0,
        device_path="/dev/video0",
        profile=profile,
        options=None,
        error=None,
    )

    assert info.source_id == 0
    assert info.device_path == "/dev/video0"
    assert info.profile == profile
    assert info.error is None


def test_source_info_with_error():
    """SourceInfo can track error state for disconnected sources."""
    profile = SourceProfile.with_defaults(source_id=0, bus_info="usb-0000:00:14.0-1")

    info = SourceInfo(
        source_id=0,
        device_path="",
        profile=profile,
        options=None,
        error="Source not connected",
    )

    assert info.error == "Source not connected"
    assert info.device_path == ""


def test_capture_coordinator_construction(tmp_path):
    """CaptureCoordinator can be constructed with a project path."""
    coordinator = CaptureCoordinator(tmp_path)

    assert coordinator.session is None  # Not initialized yet
    assert coordinator.sources == {}


def test_capture_coordinator_initialize(tmp_path):
    """initialize() discovers sources and creates session if any found."""
    coordinator = CaptureCoordinator(tmp_path)
    coordinator.initialize()

    # Session exists if sources were discovered (may have real cameras)
    # If no cameras connected, session is None and sources is empty
    if coordinator.sources:
        assert coordinator.session is not None
    else:
        assert coordinator.session is None


def test_source_tile_construction(qapp):
    """SourceTile can be constructed with source_id and label."""
    tile = SourceTile(source_id=0, label="Test Camera")

    assert tile.source_id == 0
    # Tile has expected child widgets
    assert tile._frame_label is not None
    assert tile._name_label.text() == "Test Camera"
    assert tile._focus_btn is not None


def test_grid_view_construction(qapp):
    """GridView can be constructed and add sources."""
    view = GridView()

    # Initially empty
    assert len(view._tiles) == 0

    # Can add sources
    view.add_source(0, "Camera 0")
    view.add_source(1, "Camera 1")

    assert len(view._tiles) == 2
    assert 0 in view._tiles
    assert 1 in view._tiles


def test_focus_view_construction(qapp):
    """FocusView can be constructed with source_id and label."""
    view = FocusView(source_id=0, label="Test Camera")

    assert view.source_id == 0
    assert "Test Camera" in view._info_label.text()
    assert view._frame_label is not None
    assert view._back_btn is not None
