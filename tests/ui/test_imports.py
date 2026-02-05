"""Test that UI infrastructure imports correctly."""

import numpy as np
import pytest
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QApplication

from multiwebcam.profiles import SourceProfile
from multiwebcam.ui import CaptureCoordinator, SourceInfo, frame_to_pixmap
from multiwebcam.ui.presenters import MultiSourcePresenter, SingleSourcePresenter


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
