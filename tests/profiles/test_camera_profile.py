"""Tests for CameraProfile dataclass."""

import pytest

from multiwebcam.profiles.camera_profile import CameraProfile, ControlValue


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
    assert profile.controls == {}


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
    controls = {
        "exposure": ControlValue(150, 3, 2047),
        "gain": ControlValue(32, 0, 100),
    }
    updated = profile.with_updates(
        label="new_label",
        resolution=(1920, 1080),
        controls=controls,
    )

    # Original unchanged
    assert profile.label == "cam_0"
    assert profile.resolution == (1280, 720)
    assert profile.controls == {}

    # Updated has new values
    assert updated.label == "new_label"
    assert updated.resolution == (1920, 1080)
    assert updated.controls == controls


def test_immutability():
    """Profile is frozen (immutable)."""
    profile = CameraProfile.with_defaults(cam_id=0, bus_info="usb-1")

    # Attempting to modify should raise
    try:
        profile.label = "new_label"  # type: ignore[misc]
        assert False, "Should not allow mutation"
    except AttributeError:
        pass  # Expected


def test_control_value_creation():
    """ControlValue stores value with min/max constraints."""
    cv = ControlValue(value=128, min=0, max=255)

    assert cv.value == 128
    assert cv.min == 0
    assert cv.max == 255


def test_control_value_validation():
    """ControlValue validates min <= max and value in range."""
    # Valid case
    ControlValue(value=50, min=0, max=100)

    # Invalid case - min > max
    with pytest.raises(ValueError, match="min.*cannot be greater than max"):
        ControlValue(value=50, min=100, max=0)

    # Invalid case - value below min
    with pytest.raises(ValueError, match="value.*must be between"):
        ControlValue(value=-10, min=0, max=100)

    # Invalid case - value above max
    with pytest.raises(ValueError, match="value.*must be between"):
        ControlValue(value=200, min=0, max=100)

    # Edge cases - value at boundaries should be valid
    ControlValue(value=0, min=0, max=100)
    ControlValue(value=100, min=0, max=100)


def test_control_value_immutability():
    """ControlValue is frozen."""
    cv = ControlValue(value=128, min=0, max=255)

    try:
        cv.value = 200  # type: ignore[misc]
        assert False, "Should not allow mutation"
    except AttributeError:
        pass  # Expected


def test_with_control():
    """with_control adds/updates a control."""
    profile = CameraProfile.with_defaults(cam_id=0, bus_info="usb-1")

    # Add first control
    brightness = ControlValue(value=128, min=0, max=255)
    updated = profile.with_control("brightness", brightness)

    assert profile.controls == {}  # Original unchanged
    assert updated.controls == {"brightness": brightness}

    # Add second control
    exposure = ControlValue(value=150, min=3, max=2047)
    updated2 = updated.with_control("exposure", exposure)

    assert updated.controls == {"brightness": brightness}  # Previous unchanged
    assert updated2.controls == {"brightness": brightness, "exposure": exposure}


def test_with_control_updates_existing():
    """with_control can update an existing control."""
    brightness1 = ControlValue(value=128, min=0, max=255)
    brightness2 = ControlValue(value=200, min=0, max=255)

    profile = CameraProfile.with_defaults(cam_id=0, bus_info="usb-1")
    profile = profile.with_control("brightness", brightness1)
    updated = profile.with_control("brightness", brightness2)

    assert profile.controls["brightness"].value == 128
    assert updated.controls["brightness"].value == 200
