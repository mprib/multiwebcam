"""Tests for ProfileRepository."""

import pytest

from multiwebcam.profiles.profile import ControlValue, SourceProfile
from multiwebcam.profiles.repository import ProfileParseError, ProfileRepository


def test_load_empty_project(tmp_path):
    """load_all returns empty list when no TOML exists."""
    repo = ProfileRepository(tmp_path)
    assert repo.load_all() == []


def test_save_and_load_single_profile(tmp_path):
    """Profile round-trips through TOML correctly."""
    repo = ProfileRepository(tmp_path)
    profile = SourceProfile.with_defaults(source_id=0, bus_info="usb-0000:00:14.0-1")

    repo.save(profile)
    loaded = repo.load_all()

    assert len(loaded) == 1
    assert loaded[0] == profile


def test_save_updates_existing_profile(tmp_path):
    """Saving profile with same source_id replaces it."""
    repo = ProfileRepository(tmp_path)
    profile1 = SourceProfile.with_defaults(source_id=0, bus_info="usb-1")
    profile2 = profile1.with_label("updated_label")

    repo.save(profile1)
    repo.save(profile2)
    loaded = repo.load_all()

    assert len(loaded) == 1
    assert loaded[0].label == "updated_label"


def test_save_multiple_profiles(tmp_path):
    """Can save multiple profiles."""
    repo = ProfileRepository(tmp_path)
    profile0 = SourceProfile.with_defaults(source_id=0, bus_info="usb-1")
    profile1 = SourceProfile.with_defaults(source_id=1, bus_info="usb-2")

    repo.save(profile0)
    repo.save(profile1)
    loaded = repo.load_all()

    assert len(loaded) == 2
    assert loaded[0].source_id == 0
    assert loaded[1].source_id == 1


def test_get_by_bus_info(tmp_path):
    """Can retrieve profile by bus_info."""
    repo = ProfileRepository(tmp_path)
    profile = SourceProfile.with_defaults(source_id=0, bus_info="usb-0000:00:14.0-3.1")
    repo.save(profile)

    found = repo.get_by_bus_info("usb-0000:00:14.0-3.1")
    assert found == profile

    not_found = repo.get_by_bus_info("usb-nonexistent")
    assert not_found is None


def test_get_by_source_id(tmp_path):
    """Can retrieve profile by source_id."""
    repo = ProfileRepository(tmp_path)
    profile = SourceProfile.with_defaults(source_id=5, bus_info="usb-1")
    repo.save(profile)

    found = repo.get_by_source_id(5)
    assert found == profile

    not_found = repo.get_by_source_id(999)
    assert not_found is None


def test_next_source_id_increments(tmp_path):
    """next_source_id returns max + 1."""
    repo = ProfileRepository(tmp_path)

    # Empty repository
    assert repo.next_source_id() == 0

    # After adding source_0
    repo.save(SourceProfile.with_defaults(source_id=0, bus_info="usb-1"))
    assert repo.next_source_id() == 1

    # After adding source_5 (should skip to 6, not 2)
    repo.save(SourceProfile.with_defaults(source_id=5, bus_info="usb-2"))
    assert repo.next_source_id() == 6


def test_delete_profile(tmp_path):
    """Can delete profile by source_id."""
    repo = ProfileRepository(tmp_path)
    repo.save(SourceProfile.with_defaults(source_id=0, bus_info="usb-1"))
    repo.save(SourceProfile.with_defaults(source_id=1, bus_info="usb-2"))

    deleted = repo.delete(0)
    assert deleted is True
    assert len(repo.load_all()) == 1
    assert repo.get_by_source_id(0) is None
    assert repo.get_by_source_id(1) is not None


def test_delete_nonexistent(tmp_path):
    """Deleting nonexistent profile returns False."""
    repo = ProfileRepository(tmp_path)
    repo.save(SourceProfile.with_defaults(source_id=0, bus_info="usb-1"))

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


def test_controls_empty(tmp_path):
    """Empty controls dict is omitted from TOML."""
    repo = ProfileRepository(tmp_path)
    profile = SourceProfile.with_defaults(source_id=0, bus_info="usb-1")

    repo.save(profile)

    # Check TOML doesn't have controls section
    toml_content = (tmp_path / "multiwebcam.toml").read_text()
    assert "controls" not in toml_content

    loaded = repo.load_all()[0]
    assert loaded.controls == {}


def test_controls_roundtrip(tmp_path):
    """Controls dict with ControlValue round-trips correctly."""
    repo = ProfileRepository(tmp_path)
    controls = {
        "exposure": ControlValue(value=150, min=3, max=2047),
        "brightness": ControlValue(value=128, min=0, max=255),
        "gain": ControlValue(value=32, min=0, max=100),
    }
    profile = SourceProfile(
        source_id=0,
        bus_info="usb-1",
        label="test",
        controls=controls,
    )

    repo.save(profile)
    loaded = repo.load_all()[0]

    assert loaded.controls == controls
    assert loaded.controls["exposure"].value == 150
    assert loaded.controls["exposure"].min == 3
    assert loaded.controls["exposure"].max == 2047
    assert loaded.controls["brightness"].value == 128
    assert loaded.controls["gain"].value == 32


def test_controls_toml_format(tmp_path):
    """Verify TOML format for controls."""
    repo = ProfileRepository(tmp_path)
    controls = {
        "brightness": ControlValue(value=128, min=0, max=255),
    }
    profile = SourceProfile(
        source_id=0,
        bus_info="usb-1",
        label="test",
        controls=controls,
    )

    repo.save(profile)

    # Check TOML structure
    toml_content = (tmp_path / "multiwebcam.toml").read_text()
    assert "controls" in toml_content
    assert "brightness" in toml_content
    assert "value = 128" in toml_content
    assert "min = 0" in toml_content
    assert "max = 255" in toml_content


def test_forward_compatibility_unknown_fields(tmp_path):
    """Unknown fields in TOML are ignored."""
    toml_path = tmp_path / "multiwebcam.toml"
    toml_path.write_text(
        """
[[sources]]
source_id = 0
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
    assert profiles[0].source_id == 0
    assert profiles[0].label == "test"


def test_missing_required_field_raises(tmp_path):
    """Missing required field raises ProfileParseError."""
    toml_path = tmp_path / "multiwebcam.toml"
    toml_path.write_text(
        """
[[sources]]
source_id = 0
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
    profile = SourceProfile.with_defaults(source_id=0, bus_info="usb-test-1", label="debug_source")
    repo.save(profile)
    loaded = repo.load_all()
    print(f"Saved and loaded: {loaded[0]}")
    print(f"TOML file: {debug_dir / 'multiwebcam.toml'}\n")

    # Test multiple profiles
    print("Test: multiple profiles")
    repo.save(SourceProfile.with_defaults(source_id=1, bus_info="usb-test-2", label="source_2"))

    # Test with controls
    controls = {
        "exposure": ControlValue(value=150, min=3, max=2047),
        "brightness": ControlValue(value=128, min=0, max=255),
    }
    repo.save(
        SourceProfile(
            source_id=2,
            bus_info="usb-test-3",
            label="source_3",
            controls=controls,
        )
    )
    all_profiles = repo.load_all()
    print(f"Total profiles: {len(all_profiles)}")
    for p in all_profiles:
        print(f"  source_id={p.source_id}, label={p.label}, bus_info={p.bus_info}, controls={len(p.controls)}")

    print("\nDone. Check TOML file for structure.")
