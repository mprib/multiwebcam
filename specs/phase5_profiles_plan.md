# Phase 5: Camera Profiles and Persistence

Implementation plan for camera profile persistence via TOML, with stable camera identification using `bus_info` matching.

---

## 1. Overview

### Goal

Persist camera settings to `multiwebcam.toml` so users can:
- Save camera configurations (resolution, exposure, gain, etc.)
- Re-open a project and have cameras automatically matched by `bus_info`
- Ignore/enable cameras via checkbox (persisted across sessions)
- Use consistent `cam_id` values in all data files

### Key Identifiers

| Concept | Purpose | Stability | Example |
|---------|---------|-----------|---------|
| `cam_id` | Stable integer in all data files | Permanent (project lifetime) | `0`, `1`, `2` |
| `bus_info` | USB topology identifier for matching | Stable across reboots | `usb-0000:00:14.0-3.1` |
| `device_path` | V4L2 device node | Ephemeral (changes on reboot) | `/dev/video0` |

### Key Dataclasses

- **CameraProfile**: Frozen dataclass holding all persisted camera settings
- **ProfileRepository**: Load/save profiles to TOML file

### Integration Points

- `CaptureSession.start_recording()` already accepts `cam_ids: dict[str, int]`
- `discover_frame_sources()` already returns `FrameSourceOptions` with `bus_info`
- Recording system uses `cam_id` for filenames and frametimes.csv

---

## 2. CameraProfile Dataclass

**Location**: `src/multiwebcam/profiles/camera_profile.py`

```python
@dataclass(frozen=True)
class CameraProfile:
    """Persistent camera configuration.

    Immutable. To modify, create a new profile with changed values.
    """

    # Identity (required)
    cam_id: int                         # Stable identifier, never reused
    bus_info: str                       # USB topology for matching

    # Display (required with default)
    label: str                          # User-assigned name

    # Control flags (required with default)
    ignore: bool = False                # If True, excluded from recording

    # Capture settings (required with defaults)
    resolution: tuple[int, int] = (1280, 720)
    pixel_format: str = "mjpeg"
    capture_fps: int = 30

    # V4L2 controls (optional - not all cameras support all controls)
    exposure: int | None = None
    gain: int | None = None
    white_balance: int | None = None
    focus: int | None = None
```

### Field Notes

**Required vs Optional**:
- `cam_id` and `bus_info` are required (no defaults) - identity must be explicit
- `label` defaults to `cam_{cam_id}` but is set at construction time
- V4L2 controls are `int | None` because not all cameras support all controls

**Why frozen?**
- Thread safety - profiles may be read from multiple threads
- Predictability - callers know the profile won't change under them
- To "update" a profile, create a new one (repository saves it)

**Why no `device_path`?**
- Device paths are ephemeral - they change on reboot
- The profile stores `bus_info` for matching; `device_path` is discovered at runtime

### Factory Method

```python
@classmethod
def with_defaults(cls, cam_id: int, bus_info: str, label: str | None = None) -> CameraProfile:
    """Create profile with sensible defaults.

    Args:
        cam_id: Stable identifier for this camera
        bus_info: USB topology identifier for matching
        label: Display name (defaults to 'cam_{cam_id}')
    """
    return cls(
        cam_id=cam_id,
        bus_info=bus_info,
        label=label or f"cam_{cam_id}",
    )
```

### Update Pattern

```python
def with_resolution(self, resolution: tuple[int, int]) -> CameraProfile:
    """Return new profile with updated resolution."""
    return dataclasses.replace(self, resolution=resolution)

def with_label(self, label: str) -> CameraProfile:
    """Return new profile with updated label."""
    return dataclasses.replace(self, label=label)

def with_ignore(self, ignore: bool) -> CameraProfile:
    """Return new profile with updated ignore flag."""
    return dataclasses.replace(self, ignore=ignore)

# Generic update for multiple fields
def with_updates(self, **kwargs) -> CameraProfile:
    """Return new profile with updated fields."""
    return dataclasses.replace(self, **kwargs)
```

---

## 3. ProfileRepository

**Location**: `src/multiwebcam/profiles/repository.py`

### TOML File Location

The repository is initialized with a project path. The TOML file is always `<project_path>/multiwebcam.toml`.

```python
class ProfileRepository:
    """Load and save camera profiles to TOML.

    Operates on a single file: <project_path>/multiwebcam.toml
    Uses rtoml for fast, correct TOML serialization.
    """

    def __init__(self, project_path: Path) -> None:
        """
        Args:
            project_path: Directory containing multiwebcam.toml
        """
        self._project_path = project_path
        self._toml_path = project_path / "multiwebcam.toml"
```

### Methods

```python
def load_all(self) -> list[CameraProfile]:
    """Load all profiles from TOML.

    Returns empty list if file doesn't exist (fresh project).
    Raises ProfileParseError if file exists but is malformed.
    """

def save(self, profile: CameraProfile) -> None:
    """Save or update a profile.

    If a profile with the same cam_id exists, it's replaced.
    If not, the profile is appended.
    Creates the TOML file if it doesn't exist.
    """

def delete(self, cam_id: int) -> bool:
    """Delete a profile by cam_id.

    Returns True if deleted, False if not found.
    """

def get_by_bus_info(self, bus_info: str) -> CameraProfile | None:
    """Find profile matching the given bus_info."""

def get_by_cam_id(self, cam_id: int) -> CameraProfile | None:
    """Find profile by cam_id."""

def next_cam_id(self) -> int:
    """Return next available cam_id.

    Returns max(existing_cam_ids) + 1, or 0 if no profiles exist.
    """
```

### Thread Safety

ProfileRepository is **not thread-safe** by design:
- It's expected to be used from the main thread (UI/coordinator)
- File I/O is fast (rtoml is instant for small files)
- Adding locks would complicate the API for no benefit

If thread safety is needed later, wrap the repository instance (don't add locks internally).

### Error Handling

```python
class ProfileError(Exception):
    """Base exception for profile operations."""

class ProfileParseError(ProfileError):
    """TOML file exists but is malformed."""

class ProfileNotFoundError(ProfileError):
    """Requested profile doesn't exist."""
```

**Error scenarios**:

| Scenario | Behavior |
|----------|----------|
| File doesn't exist | `load_all()` returns empty list (not an error) |
| File is invalid TOML | Raise `ProfileParseError` with line number |
| Missing required field | Raise `ProfileParseError` with field name |
| Unknown field in TOML | Ignore (forward compatibility) |
| Write to read-only path | Raise `OSError` (let it bubble up) |

### TOML Format

```toml
[project]
name = "lab_recording_2024"

[[cameras]]
cam_id = 0
label = "front_left"
bus_info = "usb-0000:00:14.0-3.1"
ignore = false
resolution = [1280, 720]
pixel_format = "mjpeg"
capture_fps = 30
exposure = 150
gain = 32
white_balance = 4500
focus = 75

[[cameras]]
cam_id = 1
label = "overhead"
bus_info = "usb-0000:00:14.0-3.2"
ignore = false
resolution = [1280, 720]
pixel_format = "mjpeg"
capture_fps = 30
# V4L2 controls omitted if None (camera doesn't support them)

[[cameras]]
cam_id = 2
label = "side"
bus_info = "usb-0000:00:14.0-4"
ignore = true  # User disabled this camera
resolution = [1280, 720]
pixel_format = "mjpeg"
capture_fps = 30
exposure = 100
```

**Notes**:
- `[[cameras]]` is TOML array-of-tables syntax
- V4L2 control fields are omitted when `None` (not written as `exposure = null`)
- `[project]` section is optional but supports future metadata

---

## 4. Startup Flow

### Fresh Start (No Project)

```
1. User launches app (no arguments or File > New)
2. discover_frame_sources() -> list[FrameSourceOptions]
3. For each discovered camera:
   - Assign temporary cam_id (0, 1, 2, ...)
   - Create CameraProfile.with_defaults(cam_id, bus_info)
   - Store in memory (not yet persisted)
4. Start CaptureSession with all discovered cameras
5. User adjusts settings (resolution, exposure, etc.)
   - UI updates in-memory profiles
   - Changes are NOT persisted yet
6. User saves: File > Save Project As -> picks folder
   - ProfileRepository(folder).save() for each profile
   - Creates multiwebcam.toml
   - cam_id assignments are now permanent
```

**Key point**: Profiles exist in memory before being saved. The "project" doesn't exist until the user saves.

### Open Existing Project

```
1. User: File > Open -> selects folder containing multiwebcam.toml
2. ProfileRepository(folder).load_all() -> list[CameraProfile]
3. discover_frame_sources() -> list[FrameSourceOptions]
4. Match cameras by bus_info:
   For each profile in loaded profiles:
       found = discover.find_by_bus_info(profile.bus_info)
       if found:
           matched[profile.cam_id] = (profile, found)
       else:
           offline[profile.cam_id] = profile
5. Handle mismatches (see below)
6. Start CaptureSession with matched cameras
7. Apply saved settings (resolution, exposure, etc.)
```

### Mismatch Handling

**Scenario 1: Camera plugged into different USB port**

The camera exists (same model) but at a different `bus_info`.

```
Profile says:  cam_0 at usb-0000:00:14.0-3.1 (label: "front_left")
Discovered:    Same model at usb-0000:00:14.0-5
```

Options:
- **Auto-accept with prompt**: "Camera 'front_left' moved from port 3.1 to 5. Update profile?" [Yes/No]
- If Yes: Update `bus_info` in profile, save immediately
- If No: Treat as offline (user may want to reconnect at original port)

**Scenario 2: Camera not found (offline)**

Profile exists but no matching `bus_info` in discovered cameras.

```
Profile says:  cam_2 at usb-0000:00:14.0-4 (label: "side")
Discovered:    (nothing at that bus_info)
```

Behavior:
- Show "offline" placeholder in grid (greyed tile)
- Checkbox is unchecked (effectively `ignore = true`)
- User can toggle checkbox when camera is reconnected
- Profile is NOT deleted (preserves cam_id for future use)

**Scenario 3: New camera discovered**

Camera exists at `bus_info` that's not in any profile.

```
Discovered:    Model X at usb-0000:00:14.0-6
Profiles:      (no profile with that bus_info)
```

Behavior:
- Assign next available `cam_id` via `repository.next_cam_id()`
- Create new profile with defaults
- Add to grid (user can configure settings)
- Save profile to TOML

---

## 5. Integration with CaptureSession

### How CaptureSession Gets cam_id Assignments

CaptureSession already accepts `cam_ids: dict[str, int]` in `start_recording()`. The caller (UI/coordinator) builds this mapping from profiles.

```python
# In coordinator/presenter layer
def start_recording(self, output_dir: Path) -> None:
    # Build cam_id mapping from current profiles
    cam_ids = {}
    for device_path, profile in self._active_profiles.items():
        if not profile.ignore:
            cam_ids[device_path] = profile.cam_id

    self._session.start_recording(output_dir, cam_ids=cam_ids)
```

### Where Ignore Flag Is Checked

The `ignore` flag is checked when building the list of active cameras:
1. **At session start**: Only non-ignored cameras are passed to CaptureSession
2. **At recording start**: Only non-ignored cameras get `cam_id` entries

```python
# In coordinator/presenter layer
def _build_sources(self) -> list[FrameSource]:
    sources = []
    for profile in self._profiles:
        if profile.ignore:
            continue  # Skip ignored cameras
        config = self._profile_to_config(profile)
        sources.append(FrameSource(self._device_paths[profile.cam_id], config))
    return sources
```

### V4L2 Control Application

**This is Phase 5 scope** - applying controls when opening a camera.

The flow:
1. Load profile from TOML
2. Build `FrameSourceConfig` from profile
3. Pass V4L2 control values via `v4l2_options` dict

```python
def _profile_to_config(self, profile: CameraProfile) -> FrameSourceConfig:
    v4l2_options = {}

    # Add V4L2 controls if specified in profile
    if profile.exposure is not None:
        v4l2_options["exposure_absolute"] = str(profile.exposure)
    if profile.gain is not None:
        v4l2_options["gain"] = str(profile.gain)
    # ... etc

    return FrameSourceConfig(
        resolution=profile.resolution,
        fps=profile.capture_fps,
        pixel_format=profile.pixel_format,
        v4l2_options=v4l2_options,
    )
```

**Note**: The exact V4L2 control names vary by camera. We'll need to discover available controls at runtime (future enhancement).

---

## 6. Testing Strategy

### Unit Tests for ProfileRepository

**Location**: `tests/profiles/test_repository.py`

```python
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

def test_get_by_bus_info(tmp_path):
    """Can retrieve profile by bus_info."""
    repo = ProfileRepository(tmp_path)
    profile = CameraProfile.with_defaults(cam_id=0, bus_info="usb-0000:00:14.0-3.1")
    repo.save(profile)

    found = repo.get_by_bus_info("usb-0000:00:14.0-3.1")
    assert found == profile

    not_found = repo.get_by_bus_info("usb-nonexistent")
    assert not_found is None

def test_next_cam_id_increments(tmp_path):
    """next_cam_id returns max + 1."""
    repo = ProfileRepository(tmp_path)

    assert repo.next_cam_id() == 0

    repo.save(CameraProfile.with_defaults(cam_id=0, bus_info="usb-1"))
    assert repo.next_cam_id() == 1

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
        gain=32,        # Has a value
    )

    repo.save(profile)
    loaded = repo.load_all()[0]

    assert loaded.exposure is None
    assert loaded.gain == 32
```

### Integration Test: Save, Reload, Match

**Location**: `tests/profiles/test_profile_matching.py`

```python
def test_profile_matching_by_bus_info(tmp_path):
    """Profiles match discovered cameras by bus_info."""
    # Setup: save profiles
    repo = ProfileRepository(tmp_path)
    repo.save(CameraProfile(
        cam_id=0,
        bus_info="usb-0000:00:14.0-3.1",
        label="front",
        resolution=(1920, 1080),
        capture_fps=30,
    ))
    repo.save(CameraProfile(
        cam_id=1,
        bus_info="usb-0000:00:14.0-3.2",
        label="back",
        resolution=(1280, 720),
        capture_fps=60,
    ))

    # Simulate discovery (mock FrameSourceOptions)
    discovered = [
        FrameSourceOptions(
            path="/dev/video0",
            model="Webcam A",
            driver="uvcvideo",
            bus_info="usb-0000:00:14.0-3.1",  # Matches cam_0
            modes=(),
        ),
        FrameSourceOptions(
            path="/dev/video2",
            model="Webcam B",
            driver="uvcvideo",
            bus_info="usb-0000:00:14.0-3.2",  # Matches cam_1
            modes=(),
        ),
    ]

    # Match
    profiles = repo.load_all()
    matched = {}
    for opts in discovered:
        profile = repo.get_by_bus_info(opts.bus_info)
        if profile:
            matched[opts.path] = profile

    # Verify
    assert matched["/dev/video0"].cam_id == 0
    assert matched["/dev/video0"].label == "front"
    assert matched["/dev/video2"].cam_id == 1
    assert matched["/dev/video2"].label == "back"
```

### Manual Test Script

**Location**: `scripts/test_profiles.py`

```python
"""Manual test for profile save/load workflow.

Run with cameras connected:
    uv run python scripts/test_profiles.py

Creates a test project, saves profiles, and reloads to verify matching.
"""

from pathlib import Path
from multiwebcam.sources.discovery import discover_frame_sources
from multiwebcam.profiles.repository import ProfileRepository
from multiwebcam.profiles.camera_profile import CameraProfile

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

if __name__ == "__main__":
    main()
```

---

## 7. File Structure

### New Files to Create

```
src/multiwebcam/profiles/
    __init__.py
    camera_profile.py    # CameraProfile dataclass
    repository.py        # ProfileRepository

tests/profiles/
    __init__.py
    test_camera_profile.py
    test_repository.py
    test_profile_matching.py

scripts/
    test_profiles.py     # Manual validation script
```

### Existing Files to Modify

**`src/multiwebcam/__init__.py`**:
- Export `CameraProfile`, `ProfileRepository`

**`pyproject.toml`**:
- Add `rtoml` dependency (if not already present)

**No changes to**:
- `CaptureSession` - already accepts `cam_ids` parameter
- `FrameRecorder` - already uses `cam_id` for filenames
- `discover_frame_sources` - already returns `bus_info`

---

## 8. Implementation Order

### Step 1: CameraProfile Dataclass

**Files**: `src/multiwebcam/profiles/__init__.py`, `src/multiwebcam/profiles/camera_profile.py`

**Test at this step**:
```python
profile = CameraProfile.with_defaults(cam_id=0, bus_info="usb-1")
assert profile.label == "cam_0"
assert profile.ignore is False

updated = profile.with_label("front_camera")
assert updated.label == "front_camera"
assert updated.cam_id == 0  # Unchanged
```

### Step 2: ProfileRepository - Basic Load/Save

**Files**: `src/multiwebcam/profiles/repository.py`, `tests/profiles/test_repository.py`

**Test at this step**:
- `load_all()` returns empty list for new project
- `save()` creates TOML file
- `load_all()` returns saved profile
- Round-trip preserves all fields

### Step 3: ProfileRepository - Query Methods

**Files**: Same as Step 2

**Test at this step**:
- `get_by_bus_info()` finds matching profile
- `get_by_cam_id()` finds by ID
- `next_cam_id()` increments correctly
- `delete()` removes profile

### Step 4: Error Handling

**Files**: Same as Step 2

**Test at this step**:
- Malformed TOML raises `ProfileParseError`
- Missing required fields raise `ProfileParseError`
- Unknown fields are ignored (forward compatibility)

### Step 5: Manual Validation Script

**Files**: `scripts/test_profiles.py`

**Test at this step**:
- Run with real cameras
- Verify bus_info matching works
- Verify TOML file is human-readable

### Step 6: Integration with Discovery

At this point, the building blocks exist. Integration with CaptureSession and UI is deferred to Phase 6 (Project Management) when the full startup flow is implemented.

---

## Open Questions

1. **V4L2 control names**: The exact FFmpeg/V4L2 option names for exposure, gain, etc. vary by camera. Do we need a control discovery step, or hardcode common names?

2. **Profile migration**: If we add fields to CameraProfile in the future, how do we handle old TOML files? Current plan: unknown fields are ignored on load, new fields get defaults.

3. **Multiple projects**: Should `ProfileRepository` support a "global" config (default settings for all projects)? Current answer: No - keep it simple, per-project only.

4. **bus_info stability**: On some systems, USB enumeration order can change. Do we need a fallback matching strategy (e.g., by model name + serial number)? Current answer: Defer until it's a real problem.
