"""Tests for ProfileRepository."""

import pytest

from multiwebcam.profiles.camera_profile import CameraProfile
from multiwebcam.profiles.repository import ProfileParseError, ProfileRepository


def test_load_empty_project(tmp_path):
    """load_all returns empty list when no TOML exists."""
    repo = ProfileRepository(tmp_path)
    assert repo.load_all() == []


def test_save_and_load_single_profile(tmp_path):
    """Profile round-trips through TOML correctly."""
    repo = ProfileRepository(tmp_path)
    profile = CameraProfile.with_defaults(cam_id=0, bus_info="usb-0000:00:14.0-1")

    repo.save(profile)
    loaded = repo.load_all()

    assert len(loaded) == 1
    assert loaded[0] == profile


def test_save_updates_existing_profile(tmp_path):
    """Saving profile with same cam_id replaces it."""
    repo = ProfileRepository(tmp_path)
    profile1 = CameraProfile.with_defaults(cam_id=0, bus_info="usb-1")
    profile2 = profile1.with_label("updated_label")

    repo.save(profile1)
    repo.save(profile2)
    loaded = repo.load_all()

    assert len(loaded) == 1
    assert loaded[0].label == "updated_label"


def test_save_multiple_profiles(tmp_path):
    """Can save multiple profiles."""
    repo = ProfileRepository(tmp_path)
    profile0 = CameraProfile.with_defaults(cam_id=0, bus_info="usb-1")
    profile1 = CameraProfile.with_defaults(cam_id=1, bus_info="usb-2")

    repo.save(profile0)
    repo.save(profile1)
    loaded = repo.load_all()

    assert len(loaded) == 2
    assert loaded[0].cam_id == 0
    assert loaded[1].cam_id == 1


def test_get_by_bus_info(tmp_path):
    """Can retrieve profile by bus_info."""
    repo = ProfileRepository(tmp_path)
    profile = CameraProfile.with_defaults(cam_id=0, bus_info="usb-0000:00:14.0-3.1")
    repo.save(profile)

    found = repo.get_by_bus_info("usb-0000:00:14.0-3.1")
    assert found == profile

    not_found = repo.get_by_bus_info("usb-nonexistent")
    assert not_found is None


def test_get_by_cam_id(tmp_path):
    """Can retrieve profile by cam_id."""
    repo = ProfileRepository(tmp_path)
    profile = CameraProfile.with_defaults(cam_id=5, bus_info="usb-1")
    repo.save(profile)

    found = repo.get_by_cam_id(5)
    assert found == profile

    not_found = repo.get_by_cam_id(999)
    assert not_found is None


def test_next_cam_id_increments(tmp_path):
    """next_cam_id returns max + 1."""
    repo = ProfileRepository(tmp_path)

    # Empty repository
    assert repo.next_cam_id() == 0

    # After adding cam_0
    repo.save(CameraProfile.with_defaults(cam_id=0, bus_info="usb-1"))
    assert repo.next_cam_id() == 1

    # After adding cam_5 (should skip to 6, not 2)
    repo.save(CameraProfile.with_defaults(cam_id=5, bus_info="usb-2"))
    assert repo.next_cam_id() == 6


def test_delete_profile(tmp_path):
    """Can delete profile by cam_id."""
    repo = ProfileRepository(tmp_path)
    repo.save(CameraProfile.with_defaults(cam_id=0, bus_info="usb-1"))
    repo.save(CameraProfile.with_defaults(cam_id=1, bus_info="usb-2"))

    deleted = repo.delete(0)
    assert deleted is True
    assert len(repo.load_all()) == 1
    assert repo.get_by_cam_id(0) is None
    assert repo.get_by_cam_id(1) is not None


def test_delete_nonexistent(tmp_path):
    """Deleting nonexistent profile returns False."""
    repo = ProfileRepository(tmp_path)
    repo.save(CameraProfile.with_defaults(cam_id=0, bus_info="usb-1"))

    deleted = repo.delete(999)
    assert deleted is False
    assert len(repo.load_all()) == 1


def test_malformed_toml_raises(tmp_path):
    """Invalid TOML raises ProfileParseError."""
    toml_path = tmp_path / "multiwebcam.toml"
    toml_path.write_text("this is not valid { toml")

    repo = ProfileRepository(tmp_path)
    with pytest.raises(ProfileParseError):
        repo.load_all()


def test_v4l2_controls_optional(tmp_path):
    """V4L2 controls can be None (omitted in TOML)."""
    repo = ProfileRepository(tmp_path)
    profile = CameraProfile(
        cam_id=0,
        bus_info="usb-1",
        label="test",
        exposure=None,  # Explicitly None
        gain=32,  # Has a value
    )

    repo.save(profile)
    loaded = repo.load_all()[0]

    assert loaded.exposure is None
    assert loaded.gain == 32


def test_v4l2_controls_all_set(tmp_path):
    """All V4L2 controls round-trip correctly."""
    repo = ProfileRepository(tmp_path)
    profile = CameraProfile(
        cam_id=0,
        bus_info="usb-1",
        label="test",
        exposure=150,
        gain=32,
        white_balance=4500,
        focus=75,
    )

    repo.save(profile)
    loaded = repo.load_all()[0]

    assert loaded.exposure == 150
    assert loaded.gain == 32
    assert loaded.white_balance == 4500
    assert loaded.focus == 75


def test_forward_compatibility_unknown_fields(tmp_path):
    """Unknown fields in TOML are ignored."""
    toml_path = tmp_path / "multiwebcam.toml"
    toml_path.write_text(
        """
[[cameras]]
cam_id = 0
label = "test"
bus_info = "usb-1"
ignore = false
resolution = [1280, 720]
pixel_format = "mjpeg"
capture_fps = 30
future_field = "should_be_ignored"
another_unknown = 123
"""
    )

    repo = ProfileRepository(tmp_path)
    profiles = repo.load_all()

    assert len(profiles) == 1
    assert profiles[0].cam_id == 0
    assert profiles[0].label == "test"


def test_missing_required_field_raises(tmp_path):
    """Missing required field raises ProfileParseError."""
    toml_path = tmp_path / "multiwebcam.toml"
    toml_path.write_text(
        """
[[cameras]]
cam_id = 0
# Missing bus_info and label
"""
    )

    repo = ProfileRepository(tmp_path)
    with pytest.raises(ProfileParseError):
        repo.load_all()


if __name__ == "__main__":
    """Debug harness for manual testing."""
    from pathlib import Path

    debug_dir = Path(__file__).parent / "tmp"
    debug_dir.mkdir(parents=True, exist_ok=True)

    print("=== Running manual tests ===\n")

    # Test basic save/load
    print("Test: save and load profile")
    repo = ProfileRepository(debug_dir)
    profile = CameraProfile.with_defaults(cam_id=0, bus_info="usb-test-1", label="debug_camera")
    repo.save(profile)
    loaded = repo.load_all()
    print(f"Saved and loaded: {loaded[0]}")
    print(f"TOML file: {debug_dir / 'multiwebcam.toml'}\n")

    # Test multiple profiles
    print("Test: multiple profiles")
    repo.save(CameraProfile.with_defaults(cam_id=1, bus_info="usb-test-2", label="camera_2"))
    repo.save(
        CameraProfile(
            cam_id=2,
            bus_info="usb-test-3",
            label="camera_3",
            exposure=150,
            gain=32,
        )
    )
    all_profiles = repo.load_all()
    print(f"Total profiles: {len(all_profiles)}")
    for p in all_profiles:
        print(f"  cam_id={p.cam_id}, label={p.label}, bus_info={p.bus_info}")

    print("\nDone. Check TOML file for structure.")
