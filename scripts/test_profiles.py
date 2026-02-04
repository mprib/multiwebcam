"""Manual test for profile save/load workflow.

Run with cameras connected:
    uv run python scripts/test_profiles.py

Creates a test project, saves profiles, and reloads to verify matching.
"""

from pathlib import Path

from multiwebcam.profiles.camera_profile import CameraProfile
from multiwebcam.profiles.repository import ProfileRepository
from multiwebcam.sources.discovery import discover_frame_sources


def main():
    # Create test project directory
    test_dir = Path("./test_project")
    test_dir.mkdir(exist_ok=True)

    print("=== Discovering cameras ===")
    discovered = discover_frame_sources()
    for opts in discovered:
        print(f"  {opts.path}: {opts.model}")
        print(f"    bus_info: {opts.bus_info}")

    if not discovered:
        print("No cameras found!")
        return

    print("\n=== Creating profiles ===")
    repo = ProfileRepository(test_dir)

    for i, opts in enumerate(discovered):
        profile = CameraProfile.with_defaults(
            cam_id=i,
            bus_info=opts.bus_info,
            label=f"camera_{i}",
        )
        repo.save(profile)
        print(f"  Saved: cam_id={profile.cam_id}, label={profile.label}")

    print(f"\nTOML saved to: {test_dir / 'multiwebcam.toml'}")

    print("\n=== Reloading profiles ===")
    loaded = repo.load_all()
    for profile in loaded:
        print(f"  cam_id={profile.cam_id}, label={profile.label}, bus_info={profile.bus_info}")

    print("\n=== Matching against discovery ===")
    for opts in discovered:
        profile = repo.get_by_bus_info(opts.bus_info)
        if profile:
            print(f"  {opts.path} -> cam_id={profile.cam_id} ({profile.label})")
        else:
            print(f"  {opts.path} -> NO MATCH")

    print("\n=== Testing update workflow ===")
    # Update first profile
    if loaded:
        first = loaded[0]
        updated = first.with_label("updated_label").with_resolution((1920, 1080))
        repo.save(updated)
        print(f"  Updated cam_id={first.cam_id} -> label={updated.label}, resolution={updated.resolution}")

        # Reload and verify
        reloaded = repo.get_by_cam_id(first.cam_id)
        assert reloaded is not None
        print(f"  Verified: label={reloaded.label}, resolution={reloaded.resolution}")

    print("\n=== Testing next_cam_id ===")
    next_id = repo.next_cam_id()
    print(f"  Next available cam_id: {next_id}")

    print("\nDone! Check test_project/multiwebcam.toml for TOML structure.")


if __name__ == "__main__":
    main()
