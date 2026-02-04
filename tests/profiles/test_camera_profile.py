"""Tests for CameraProfile dataclass."""

from multiwebcam.profiles.camera_profile import CameraProfile


def test_with_defaults():
    """with_defaults creates profile with sensible defaults."""
    profile = CameraProfile.with_defaults(cam_id=0, bus_info="usb-1")

    assert profile.cam_id == 0
    assert profile.bus_info == "usb-1"
    assert profile.label == "cam_0"
    assert profile.ignore is False
    assert profile.resolution == (1280, 720)
    assert profile.pixel_format == "mjpeg"
    assert profile.capture_fps == 30
    assert profile.exposure is None
    assert profile.gain is None
    assert profile.white_balance is None
    assert profile.focus is None


def test_with_defaults_custom_label():
    """with_defaults accepts custom label."""
    profile = CameraProfile.with_defaults(cam_id=5, bus_info="usb-2", label="front_camera")

    assert profile.cam_id == 5
    assert profile.label == "front_camera"


def test_with_resolution():
    """with_resolution returns new profile with updated resolution."""
    profile = CameraProfile.with_defaults(cam_id=0, bus_info="usb-1")
    updated = profile.with_resolution((1920, 1080))

    # Original unchanged
    assert profile.resolution == (1280, 720)

    # Updated has new resolution
    assert updated.resolution == (1920, 1080)
    assert updated.cam_id == 0  # Other fields unchanged


def test_with_label():
    """with_label returns new profile with updated label."""
    profile = CameraProfile.with_defaults(cam_id=0, bus_info="usb-1")
    updated = profile.with_label("updated_label")

    assert profile.label == "cam_0"
    assert updated.label == "updated_label"
    assert updated.cam_id == 0


def test_with_ignore():
    """with_ignore returns new profile with updated ignore flag."""
    profile = CameraProfile.with_defaults(cam_id=0, bus_info="usb-1")
    updated = profile.with_ignore(True)

    assert profile.ignore is False
    assert updated.ignore is True


def test_with_updates():
    """with_updates can change multiple fields at once."""
    profile = CameraProfile.with_defaults(cam_id=0, bus_info="usb-1")
    updated = profile.with_updates(
        label="new_label",
        resolution=(1920, 1080),
        exposure=150,
        gain=32,
    )

    # Original unchanged
    assert profile.label == "cam_0"
    assert profile.resolution == (1280, 720)
    assert profile.exposure is None

    # Updated has new values
    assert updated.label == "new_label"
    assert updated.resolution == (1920, 1080)
    assert updated.exposure == 150
    assert updated.gain == 32


def test_immutability():
    """Profile is frozen (immutable)."""
    profile = CameraProfile.with_defaults(cam_id=0, bus_info="usb-1")

    # Attempting to modify should raise
    try:
        profile.label = "new_label"  # type: ignore[misc]
        assert False, "Should not allow mutation"
    except AttributeError:
        pass  # Expected
