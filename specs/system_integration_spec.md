# System Integration Specification

Master reference document for multiwebcam system architecture. Single source of truth for all components, their responsibilities, and how they connect.

Last updated: 2026-02-04

---

## Table of Contents

1. [System Overview](#system-overview)
2. [Component Inventory](#component-inventory)
3. [Data Flow Diagram](#data-flow-diagram)
4. [Discovery & Device Management](#discovery--device-management)
5. [Capture Pipeline](#capture-pipeline)
6. [Recording System](#recording-system)
7. [Camera Profiles & Persistence](#camera-profiles--persistence)
8. [V4L2 Controls](#v4l2-controls)
9. [UI Structure](#ui-structure)
10. [Implementation Status](#implementation-status)
11. [Integration Gaps](#integration-gaps)
12. [Implementation Sequence](#implementation-sequence)
13. [Project Folder Structure](#project-folder-structure)

---

## System Overview

### Purpose

Multi-camera capture and recording system for USB webcams. Captures frames from multiple cameras with accurate timestamps, records to MP4 + frametimes.csv for offline processing by Caliscope.

### Non-Goals

- True hardware synchronization (requires genlock, not consumer USB)
- Real-time temporal alignment (deferred to Caliscope)
- Calibration algorithms (that's Caliscope's job)
- Auto-exposure/gain modes (scientific reproducibility requires explicit settings)

### Key Identifiers

| Concept | Purpose | Stability | Example |
|---------|---------|-----------|---------|
| `cam_id` | Stable integer in all data files | Permanent (project lifetime) | `0`, `1`, `2` |
| `bus_info` | USB topology for camera matching | Stable across reboots | `usb-0000:00:14.0-3.1` |
| `device_path` | V4L2 device node | Ephemeral (changes on reboot) | `/dev/video0` |

---

## Component Inventory

### Package Structure

```
src/multiwebcam/
+-- __init__.py                 # Exports: CameraProfile, ProfileRepository
+-- sources/
|   +-- __init__.py
|   +-- config.py               # FrameSourceConfig, FrameSourceStatus
|   +-- device.py               # FrameSource (PyAV capture iterator)
|   +-- discovery.py            # FrameSourceOptions, discover_frame_sources()
|   +-- frame_packet.py         # FramePacket (frozen dataclass)
|   +-- conversion.py           # frame_to_bgr() helper
|   +-- controls.py             # [TO CREATE] V4L2Control, query_device_controls()
|
+-- pipeline/
|   +-- __init__.py
|   +-- signals.py              # StartSignal, StopSignal, ShutdownSignal
|   +-- producer.py             # FrameProducer, ProducerQueues
|   +-- alignment.py            # AlignmentMonitor, AlignmentStats, Cluster
|   +-- report.py               # CameraStats
|   +-- session.py              # CaptureSession (orchestration)
|
+-- recording/
|   +-- __init__.py
|   +-- frametimes.py           # FrametimesCollector, write_frametimes_csv()
|   +-- encoder.py              # CameraEncoder (per-camera worker thread)
|   +-- recorder.py             # FrameRecorder, RecordingResult
|
+-- profiles/
    +-- __init__.py
    +-- camera_profile.py       # CameraProfile (frozen dataclass)
    +-- repository.py           # ProfileRepository (TOML persistence)
```

### Exploration Scripts (Validated Knowledge)

Located in `scripts/pyav_exploration/`. These validate PyAV/V4L2 behavior and inform package design.

| Script | Purpose | Key Findings |
|--------|---------|--------------|
| `01_enumerate_v4l2_devices.py` | Device detection | Filter metadata nodes via capability flags |
| `02_open_single_device.py` | Basic PyAV capture | Context manager handles cleanup |
| `03_frame_to_numpy.py` | Frame conversion | ~1ms BGR24 conversion overhead |
| `04_device_cleanup.py` | Resource cleanup | No fd leaks with context manager |
| `05_query_capabilities.py` | V4L2 capability query | Per-device caps at offset 88 |
| `06_set_resolution.py` | Resolution setting | Cameras may silently fall back |
| `07_set_framerate.py` | Framerate behavior | Expect 85-95% of requested fps |
| `08_camera_controls.py` | V4L2 control discovery | **Ready to integrate** - parses v4l2-ctl output |
| `09_color_space_verification.py` | Color conversion | MJPEG needs special handling |
| `10_frame_format_validation.py` | Format validation | Verify what camera actually delivers |
| `11_timestamp_analysis.py` | PTS timestamps | Use PTS with runtime validation |
| `12_continuous_capture.py` | Stability testing | Memory stable during capture |
| `13_drop_detection.py` | Frame drop detection | Monitor queue depths |
| `14_error_recovery.py` | Error handling | Camera disconnect handling |
| `15_multicam_record_test.py` | Multi-camera recording | Integration validation |
| `16_device_enumeration.py` | Device listing | Filter by capability flags |
| `17_format_resolution_query.py` | Detailed format query | Parse --list-formats-ext |
| `18_config_verification.py` | Config validation | Verify settings match request |
| `19_unsupported_config.py` | Error handling | Handle unsupported configs |
| `20_device_capabilities.py` | Complete capabilities | DeviceCapabilities dataclass |
| `21_v4l2_buffer_control.py` | Buffer management | V4L2 buffer settings |

---

## Data Flow Diagram

### Capture Pipeline

```
+---------------------------------------------------------------------+
|                         discover_frame_sources()                      |
|                              (discovery.py)                           |
|    Returns: list[FrameSourceOptions] with bus_info, modes, etc.      |
+---------------------------------------------------------------------+
                                    |
                                    v
+---------------------------------------------------------------------+
|                         ProfileRepository                            |
|                          (repository.py)                             |
|    Matches discovered cameras by bus_info, loads saved settings      |
+---------------------------------------------------------------------+
                                    |
                                    v
+---------------------------------------------------------------------+
|                          FrameSource(s)                              |
|                           (device.py)                                |
|    PyAV V4L2 iterator, yields FramePacket                           |
+---------------------------------------------------------------------+
                                    |
              +---------------------+---------------------+
              |                     |                     |
              v                     v                     v
+---------------------+   +---------------------+   +---------------------+
| FrameProducer       |   | FrameProducer       |   | FrameProducer       |
| (producer.py)       |   | (producer.py)       |   | (producer.py)       |
| - thread per camera |   | - thread per camera |   | - thread per camera |
| - pushes to 3 queues|   | - pushes to 3 queues|   | - pushes to 3 queues|
+---------------------+   +---------------------+   +---------------------+
        |                         |                         |
        v                         v                         v
   +---------+               +---------+               +---------+
   | Display |               | Display |               | Display |
   | Queue   |               | Queue   |               | Queue   |
   | (1 slot)|               | (1 slot)|               | (1 slot)|
   +---------+               +---------+               +---------+
        |                         |                         |
        +------------+------------+------------+------------+
                     |                         |
                     v                         v
            +----------------+        +------------------+
            | Recording      |        | Alignment        |
            | Queues         |        | Queues           |
            | (if recording) |        | (for monitoring) |
            +----------------+        +------------------+
                     |                         |
                     v                         v
            +----------------+        +------------------+
            | FrameRecorder  |        | AlignmentMonitor |
            | (recorder.py)  |        | (alignment.py)   |
            +----------------+        +------------------+
                     |
                     v
            +----------------+
            | cam_N.mp4      |
            | frametimes.csv |
            +----------------+
```

### Key Data Types

| Type | Location | Purpose |
|------|----------|---------|
| `FramePacket` | `sources/frame_packet.py` | Immutable frame data flowing through pipeline |
| `FrameSourceConfig` | `sources/config.py` | Per-camera capture settings |
| `FrameSourceStatus` | `sources/config.py` | Actual negotiated settings after start |
| `FrameSourceOptions` | `sources/discovery.py` | Available modes before opening |
| `VideoMode` | `sources/discovery.py` | Single format+resolution+fps combo |
| `CameraProfile` | `profiles/camera_profile.py` | Persisted camera configuration |
| `CameraStats` | `pipeline/report.py` | Per-camera performance metrics |
| `AlignmentStats` | `pipeline/alignment.py` | Multi-camera alignment quality |
| `RecordingResult` | `recording/recorder.py` | Recording session outcome |
| `V4L2Control` | `sources/controls.py` | [TO CREATE] Control metadata with range |
| `ControlValue` | `profiles/camera_profile.py` | [TO CREATE] Value + min/max |

---

## Discovery & Device Management

### What Exists

**`src/multiwebcam/sources/discovery.py`** - COMPLETE

- `discover_frame_sources()` - Returns `list[FrameSourceOptions]` for all capture devices
- `get_frame_source_options(device_path)` - Query single device
- Uses `v4l2-ctl --info` and `v4l2-ctl --list-formats-ext`
- Filters out metadata nodes (no VIDEO_CAPTURE capability)
- Returns `bus_info` for stable camera identification

**Key Fields in FrameSourceOptions:**
```python
@dataclass(frozen=True, slots=True)
class FrameSourceOptions:
    path: str           # e.g., "/dev/video0"
    model: str          # Hardware name from V4L2
    driver: str         # e.g., "uvcvideo"
    bus_info: str       # e.g., "usb-0000:00:14.0-2" - STABLE ACROSS REBOOTS
    modes: tuple[VideoMode, ...]

    def supports(self, config: FrameSourceConfig) -> bool: ...
    def suggested_config(self) -> FrameSourceConfig: ...
    def formats(self) -> set[str]: ...
    def resolutions(self, pixel_format: str) -> set[tuple[int, int]]: ...
    def framerates(self, pixel_format: str, width: int, height: int) -> list[float]: ...
```

---

## Capture Pipeline

### What Exists

**`src/multiwebcam/sources/device.py`** - COMPLETE

- `FrameSource` class - Passive iterator yielding `FramePacket`
- Opens device via PyAV with V4L2 backend
- Validates resolution matches requested (fails fast)
- Determines timestamp source (PTS vs wall-clock)
- Discards warmup frames

**`src/multiwebcam/pipeline/producer.py`** - COMPLETE

- `FrameProducer` - Threaded wrapper around FrameSource
- Pushes to three queues: display (drop-oldest), recording (conditional), alignment (always)
- `ProducerQueues` dataclass bundles the three queues

**`src/multiwebcam/pipeline/session.py`** - COMPLETE

- `CaptureSession` - Orchestrates multiple producers
- Creates queue bundles per camera
- Parallel camera startup with PTS validation
- `get_latest_frames()` for display
- `start_recording()` / `stop_recording()` integration

**`src/multiwebcam/pipeline/alignment.py`** - COMPLETE

- `AlignmentMonitor` - Drains alignment queues, computes quality stats
- Collect-until-duplicate algorithm for clustering

### Triple-Queue Design

The core innovation: each camera pushes frames to THREE separate queues with different behaviors.

```
FrameSource --> FrameProducer --> Display Queue (maxsize=1, drop-oldest)
                            --> Recording Queue (blocking, preserve ALL)
                            --> Alignment Queue (blocking, for monitoring)
```

| Queue | Purpose | Behavior | Drop Policy |
|-------|---------|----------|-------------|
| Display | Latest frame for UI | maxsize=1 | Drop oldest (always latest) |
| Recording | Lossless capture | Large buffer | Never drop |
| Alignment | Quality monitoring | Large buffer | Drained by monitor |

---

## Recording System

### What Exists

**`src/multiwebcam/recording/`** - COMPLETE

| File | Class | Purpose |
|------|-------|---------|
| `frametimes.py` | `FrametimesCollector` | Thread-safe timestamp collection |
| `encoder.py` | `CameraEncoder` | Per-camera worker thread, PyAV h264 encoding |
| `recorder.py` | `FrameRecorder`, `RecordingResult` | Orchestrates encoders, writes frametimes.csv |

### Integration

- `CaptureSession.start_recording(output_dir, cam_ids)` creates `FrameRecorder`
- `CaptureSession.stop_recording()` drains queues, returns `RecordingResult`
- Sentinel-based shutdown (None = stop signal)
- Files: `cam_<cam_id>.mp4` + `frametimes.csv`

### frametimes.csv Format

```csv
cam_id,frame_index,frame_time
0,0,1234.567890
1,0,1234.568123
0,1,1234.600456
...
```

---

## Camera Profiles & Persistence

### Current State (NEEDS UPDATE)

**`src/multiwebcam/profiles/camera_profile.py`** has hardcoded V4L2 control fields:

```python
# CURRENT (problematic)
exposure: int | None = None
gain: int | None = None
white_balance: int | None = None
focus: int | None = None
```

**Problems with this design:**
1. Camera control names vary by device (`exposure_absolute` vs `exposure_time_absolute`)
2. No storage of min/max/step constraints for UI sliders
3. No way to store camera-specific controls that aren't in our hardcoded list
4. Applying controls requires guessing the correct V4L2 name

### Proposed Design: Controls Dict with Metadata

Replace hardcoded fields with a flexible `controls` dict:

```python
@dataclass(frozen=True)
class ControlValue:
    """A V4L2 control setting with its constraints.

    Stores the value the user wants AND the valid range,
    so we can validate values and build sliders without re-querying.
    """
    value: int                  # Current/desired value
    min: int                    # Minimum allowed
    max: int                    # Maximum allowed


@dataclass(frozen=True)
class CameraProfile:
    """Persistent camera configuration."""

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

    # V4L2 controls - dict of control_name -> ControlValue
    # Key is the ACTUAL V4L2 control name for this camera (e.g., "exposure_time_absolute")
    controls: dict[str, ControlValue] = field(default_factory=dict)
```

### TOML Format for Controls

Compact inline format - each camera is a self-contained block:

```toml
[[cameras]]
cam_id = 0
bus_info = "usb-0000:c1:00.4-1"
label = "laptop_webcam"
resolution = [1280, 720]
pixel_format = "mjpeg"
capture_fps = 30
controls.brightness = { value = 128, min = 0, max = 255 }
controls.exposure_time_absolute = { value = 156, min = 2, max = 1250 }
controls.gain = { value = 32, min = 0, max = 100 }

[[cameras]]
cam_id = 1
bus_info = "usb-0000:c3:00.4-1.3"
label = "front_camera"
resolution = [1920, 1080]
pixel_format = "mjpeg"
capture_fps = 30
controls.brightness = { value = 64, min = -64, max = 64 }
controls.exposure_time_absolute = { value = 20, min = 1, max = 5000 }
controls.gain = { value = 4, min = 0, max = 100 }
```

### Why Store Constraints in Profile?

1. **UI sliders need range** - Can build slider without re-querying device
2. **Validation** - Can check if saved value is still valid
3. **Offline cameras** - Can display settings even if camera not connected
4. **Migration check** - If camera's range changes, we can detect it

### ProfileRepository Changes

```python
def _profile_to_dict(self, profile: CameraProfile) -> dict:
    d = {
        "cam_id": profile.cam_id,
        "label": profile.label,
        "bus_info": profile.bus_info,
        "ignore": profile.ignore,
        "resolution": list(profile.resolution),
        "pixel_format": profile.pixel_format,
        "capture_fps": profile.capture_fps,
    }

    # Serialize controls as inline tables (compact format)
    if profile.controls:
        d["controls"] = {}
        for name, ctrl in profile.controls.items():
            d["controls"][name] = {
                "value": ctrl.value,
                "min": ctrl.min,
                "max": ctrl.max,
            }

    return d


def _dict_to_profile(self, d: dict) -> CameraProfile:
    # ... existing fields ...

    # Parse controls
    controls = {}
    if "controls" in d:
        for name, ctrl_dict in d["controls"].items():
            controls[name] = ControlValue(
                value=ctrl_dict["value"],
                min=ctrl_dict["min"],
                max=ctrl_dict["max"],
            )

    return CameraProfile(
        # ... existing fields ...
        controls=controls,
    )
```

---

## V4L2 Controls

### What Exists in Exploration

**`scripts/pyav_exploration/08_camera_controls.py`** contains production-ready code:

```python
@dataclass
class V4L2Control:
    """A V4L2 camera control with its properties."""
    name: str
    id: str                     # v4l2 control ID (e.g., "exposure_auto")
    type: str                   # int, bool, menu
    min: int | None
    max: int | None
    step: int | None
    default: int | None
    current: int | None
    menu_items: dict[int, str] | None = None

def parse_controls(output: str) -> list[V4L2Control]:
    """Parse output from v4l2-ctl --list-ctrls-menus."""
    ...

def query_controls(device: str) -> list[V4L2Control]:
    """Query all available controls for a device."""
    ...

def set_control(device: str, control_name: str, value: int) -> bool:
    """Set a control value."""
    ...

def get_control_value(device: str, control_name: str) -> int | None:
    """Get current value of a control."""
    ...

def categorize_controls(controls: list[V4L2Control]) -> dict[str, list[V4L2Control]]:
    """Group controls by category for display."""
    ...
```

### Integration Path: Create `src/multiwebcam/sources/controls.py`

**Step 1: Define frozen dataclasses**

```python
# src/multiwebcam/sources/controls.py
"""V4L2 camera control discovery and manipulation."""

from __future__ import annotations

import re
import subprocess
import logging
from dataclasses import dataclass
from typing import Literal

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class V4L2Control:
    """A V4L2 camera control with its properties.

    Immutable representation of a control discovered from v4l2-ctl.
    """
    name: str                                           # e.g., "brightness"
    control_type: Literal["int", "bool", "menu"]        # Control type
    min_value: int | None                               # Minimum allowed
    max_value: int | None                               # Maximum allowed
    step: int | None                                    # Step size
    default_value: int | None                           # Factory default
    current_value: int | None                           # Current setting
    menu_items: tuple[tuple[int, str], ...] | None = None  # For menu type


@dataclass(frozen=True, slots=True)
class DeviceControls:
    """All V4L2 controls available on a device.

    Provides categorized access to controls.
    """
    device_path: str
    controls: tuple[V4L2Control, ...]

    def get_control(self, name: str) -> V4L2Control | None:
        """Find control by name (case-insensitive)."""
        name_lower = name.lower()
        for ctrl in self.controls:
            if ctrl.name.lower() == name_lower:
                return ctrl
        return None

    def exposure_controls(self) -> list[V4L2Control]:
        """Get exposure-related controls."""
        return [c for c in self.controls
                if "exposure" in c.name.lower() or "gain" in c.name.lower()]

    def white_balance_controls(self) -> list[V4L2Control]:
        """Get white balance controls."""
        return [c for c in self.controls
                if any(x in c.name.lower() for x in ["white", "balance", "temperature"])]

    def focus_controls(self) -> list[V4L2Control]:
        """Get focus controls."""
        return [c for c in self.controls if "focus" in c.name.lower()]

    def image_controls(self) -> list[V4L2Control]:
        """Get image adjustment controls (brightness, contrast, etc.)."""
        keywords = ["brightness", "contrast", "saturation", "sharpness", "hue"]
        return [c for c in self.controls
                if any(x in c.name.lower() for x in keywords)]
```

**Step 2: Port query functions**

```python
def query_device_controls(device_path: str) -> DeviceControls:
    """Query all V4L2 controls for a device.

    Args:
        device_path: V4L2 device path (e.g., "/dev/video0")

    Returns:
        DeviceControls with all discovered controls

    Raises:
        subprocess.CalledProcessError: If v4l2-ctl fails
        subprocess.TimeoutExpired: If query takes too long
    """
    result = subprocess.run(
        ["v4l2-ctl", "-d", device_path, "--list-ctrls-menus"],
        capture_output=True,
        text=True,
        timeout=5,
    )

    if result.returncode != 0:
        logger.warning(f"v4l2-ctl failed for {device_path}: {result.stderr}")
        return DeviceControls(device_path=device_path, controls=())

    controls = _parse_controls(result.stdout)
    return DeviceControls(device_path=device_path, controls=tuple(controls))


def set_device_control(device_path: str, control_name: str, value: int) -> bool:
    """Set a V4L2 control value.

    Args:
        device_path: V4L2 device path
        control_name: Name of control (e.g., "brightness")
        value: Integer value to set

    Returns:
        True if successful, False otherwise
    """
    result = subprocess.run(
        ["v4l2-ctl", "-d", device_path, "--set-ctrl", f"{control_name}={value}"],
        capture_output=True,
        text=True,
        timeout=5,
    )

    if result.returncode != 0:
        logger.warning(f"Failed to set {control_name}={value}: {result.stderr}")
        return False

    return True


def get_device_control(device_path: str, control_name: str) -> int | None:
    """Get current value of a V4L2 control.

    Args:
        device_path: V4L2 device path
        control_name: Name of control

    Returns:
        Current value, or None if query failed
    """
    result = subprocess.run(
        ["v4l2-ctl", "-d", device_path, "--get-ctrl", control_name],
        capture_output=True,
        text=True,
        timeout=5,
    )

    if result.returncode == 0:
        match = re.search(r":\s*(-?\d+)", result.stdout)
        if match:
            return int(match.group(1))

    return None


def _parse_controls(output: str) -> list[V4L2Control]:
    """Parse output from v4l2-ctl --list-ctrls-menus.

    Example input:
        brightness 0x00980900 (int)    : min=0 max=255 step=1 default=128 value=128
        exposure_auto 0x009a0901 (menu)   : min=0 max=3 default=3 value=3
                            1: Manual Mode
                            3: Aperture Priority Mode
    """
    controls = []
    current_control = None

    control_pattern = re.compile(
        r"^\s*(\w+)\s+0x[\da-f]+\s+\((\w+)\)\s*:\s*(.+)$", re.IGNORECASE
    )
    menu_pattern = re.compile(r"^\s*(\d+):\s*(.+)$")

    for line in output.splitlines():
        match = control_pattern.match(line)
        if match:
            # Save previous control
            if current_control is not None:
                controls.append(current_control)

            name = match.group(1)
            ctrl_type = match.group(2)
            properties = match.group(3)

            # Parse properties
            props = {}
            for prop in ["min", "max", "step", "default", "value"]:
                prop_match = re.search(rf"{prop}=(-?\d+)", properties)
                if prop_match:
                    props[prop] = int(prop_match.group(1))

            current_control = {
                "name": name,
                "control_type": ctrl_type,
                "min_value": props.get("min"),
                "max_value": props.get("max"),
                "step": props.get("step"),
                "default_value": props.get("default"),
                "current_value": props.get("value"),
                "menu_items": [] if ctrl_type == "menu" else None,
            }
            continue

        # Try to match menu item
        menu_match = menu_pattern.match(line)
        if menu_match and current_control and current_control["menu_items"] is not None:
            idx = int(menu_match.group(1))
            label = menu_match.group(2).strip()
            current_control["menu_items"].append((idx, label))

    # Don't forget last control
    if current_control is not None:
        controls.append(current_control)

    # Convert to frozen dataclasses
    result = []
    for c in controls:
        menu_items = tuple(c["menu_items"]) if c["menu_items"] else None
        result.append(V4L2Control(
            name=c["name"],
            control_type=c["control_type"],
            min_value=c["min_value"],
            max_value=c["max_value"],
            step=c["step"],
            default_value=c["default_value"],
            current_value=c["current_value"],
            menu_items=menu_items,
        ))

    return result
```

### How Controls Connect to Profiles

**Workflow: Discovering controls for a new camera**

```python
from multiwebcam.sources.discovery import discover_frame_sources
from multiwebcam.sources.controls import query_device_controls
from multiwebcam.profiles import CameraProfile, ControlValue, ProfileRepository

# 1. Discover cameras
options = discover_frame_sources()
camera = options[0]  # Pick one

# 2. Query its controls
device_controls = query_device_controls(camera.path)

# 3. Build profile with discovered controls
controls_dict = {}
for ctrl in device_controls.controls:
    if ctrl.control_type == "int" and ctrl.current_value is not None:
        controls_dict[ctrl.name] = ControlValue(
            value=ctrl.current_value,
            min=ctrl.min_value or 0,
            max=ctrl.max_value or 255,
        )

profile = CameraProfile(
    cam_id=0,
    bus_info=camera.bus_info,
    label="my_camera",
    controls=controls_dict,
)

# 4. Save profile
repo = ProfileRepository(project_path)
repo.save(profile)
```

**Workflow: Applying controls from a loaded profile**

```python
from multiwebcam.sources.controls import set_device_control

# Load profile
profile = repo.get_by_bus_info(camera.bus_info)

# Apply each control before opening the camera
for control_name, control_value in profile.controls.items():
    success = set_device_control(camera.path, control_name, control_value.value)
    if not success:
        logger.warning(f"Failed to apply {control_name}={control_value.value}")

# Now open the camera with FrameSource
```

### Key Findings from 08_camera_controls.py

```
V4L2 Camera Control Patterns:

1. Auto vs Manual modes:
   - exposure_auto: 1=Manual, 3=Aperture Priority (auto)
   - white_balance_temperature_auto: 0=Manual, 1=Auto
   - focus_auto: 0=Manual, 1=Auto

   Must set to Manual before adjusting related controls!

2. Control dependencies:
   - exposure_absolute only works when exposure_auto=1
   - white_balance_temperature only works when wb_auto=0
   - Some controls require stream restart to take effect

3. Setting controls BEFORE PyAV open:
   Recommended workflow:
   1. Configure controls with v4l2-ctl
   2. Then open stream with PyAV
   3. Controls persist while device is open

4. Per-camera variation:
   - Available controls vary significantly by camera
   - Cheap cameras may have fewer controls
   - Some controls may be read-only despite appearing in list
```

---

## UI Structure

### Two View Modes

The app has two view modes: **Grid View** (multi-camera) and **Focus Mode** (single camera).

### Grid View (Multi-Camera)

```
+---------------------------------------------------------------------+
| multiwebcam                                        [Settings] [?]    |
+---------------------------------------------------------------------+
| File                                                                 |
+---------------------------------------------------------------------+
|  +-------------------+  +-------------------+  +-------------------+ |
|  | [x]          [F]  |  | [x]          [F]  |  | [ ]          [F]  | |
|  |    front_left     |  |     overhead      |  |       side        | |
|  |    29.8 fps       |  |    30.1 fps       |  |    [IGNORED]      | |
|  |    jitter: 2.1ms  |  |    jitter: 1.8ms  |  |                   | |
|  +-------------------+  +-------------------+  +-------------------+ |
|                                                                      |
|  Recording FPS: [====*=====] 30        Recording Type: (*) Extrinsic |
|                                                        ( ) Trial     |
|  Trial Name: [________________]                                      |
|                                                                      |
|  [Record All] [Stop]                            Duration: 00:00:00  |
+---------------------------------------------------------------------+
| Cameras: 2/3 | Spread: 17ms | Complete: 83% | FPS: 29.9 avg         |
+---------------------------------------------------------------------+
```

**Per-tile elements:**
- `[x]` checkbox - Include/ignore this camera for recording
- `[F]` button - Enter focus mode for this camera
- Camera label (user-assigned, defaults to `cam_N`)
- FPS (this camera's actual frame rate)
- Jitter (this camera's timing consistency)

### Focus Mode (Single Camera)

```
+---------------------------------------------------------------------+
| multiwebcam                                        [Settings] [?]    |
+---------------------------------------------------------------------+
| File                                                                 |
+---------------------------------------------------------------------+
|  +---------------------------------------------------------------+  |
|  |                                                               |  |
|  |                    front_left (focused)                       |  |
|  |                    cam_id: 0 | /dev/video0                    |  |
|  |                    29.8 fps | jitter: 2.1ms                   |  |
|  |                                                               |  |
|  +---------------------------------------------------------------+  |
|                                                                      |
|  Resolution: [v 1280x720]   Format: [v MJPEG]   FPS: [v 30]         |
|                                                                      |
|  Exposure:       [----*------] 150  [0-1250]                        |
|  Gain:           [--*--------] 32   [0-100]                         |
|  White Balance:  [---*-------] 4500 [2000-6500]                     |
|  Focus:          [------*----] 75   [0-255]                         |
|                                                                      |
|  [Record Intrinsic]                            [Back to Grid]       |
+---------------------------------------------------------------------+
```

**Focus mode features:**
- Large preview for precise framing
- Resolution/format/FPS dropdowns (changes require camera restart)
- V4L2 control sliders with actual ranges from discovery
- All settings save to TOML immediately when changed

---

## Implementation Status

### Complete (Production Ready)

| Component | Location | Notes |
|-----------|----------|-------|
| Device Discovery | `sources/discovery.py` | Returns bus_info, modes |
| FrameSource | `sources/device.py` | PyAV capture iterator |
| FramePacket | `sources/frame_packet.py` | Frozen dataclass |
| FrameProducer | `pipeline/producer.py` | Triple-queue design |
| CaptureSession | `pipeline/session.py` | Full orchestration |
| AlignmentMonitor | `pipeline/alignment.py` | Quality statistics |
| FrameRecorder | `recording/recorder.py` | MP4 + frametimes.csv |
| CameraProfile | `profiles/camera_profile.py` | Frozen dataclass (NEEDS UPDATE for controls) |
| ProfileRepository | `profiles/repository.py` | TOML persistence (NEEDS UPDATE for controls) |

### In Exploration (Ready to Integrate)

| Component | Location | Status |
|-----------|----------|--------|
| V4L2 Control Discovery | `scripts/pyav_exploration/08_camera_controls.py` | **Ready to move to `sources/controls.py`** |

### Not Implemented

| Component | Notes |
|-----------|-------|
| `sources/controls.py` | Port from 08_camera_controls.py |
| Qt UI | Grid view, focus mode, settings panels |
| PipelineBridge | Qt/QTimer polling of queues |
| Profile-session integration | Load profiles -> configure cameras -> start session |
| Project management | New/Open/Save project workflow |

---

## Integration Gaps

### Gap 1: V4L2 Control Discovery Not in Package

**Current State:**
- `08_camera_controls.py` has complete control discovery/query code
- `CameraProfile` stores hardcoded control fields (exposure, gain, white_balance, focus)
- No connection between them

**What's Needed:**
1. Create `src/multiwebcam/sources/controls.py` (see V4L2 Controls section)
2. Update `CameraProfile` to use `controls: dict[str, ControlValue]`
3. Update `ProfileRepository` to serialize/deserialize controls dict

### Gap 2: Profile -> FrameSourceConfig Conversion

**Current State:**
- `CameraProfile` stores settings
- `FrameSourceConfig` is what `FrameSource` accepts
- No function to convert between them (and apply V4L2 controls)

**What's Needed:**
```python
def apply_profile_and_create_config(
    profile: CameraProfile,
    device_path: str,
) -> FrameSourceConfig:
    """Apply V4L2 controls and create capture config.

    1. Set auto-mode controls to manual
    2. Apply all profile controls via v4l2-ctl
    3. Return FrameSourceConfig for capture
    """
    from multiwebcam.sources.controls import set_device_control

    # Apply each control
    for control_name, control_value in profile.controls.items():
        set_device_control(device_path, control_name, control_value.value)

    return FrameSourceConfig(
        resolution=profile.resolution,
        fps=profile.capture_fps,
        pixel_format=profile.pixel_format,
    )
```

### Gap 3: Profile-Session Integration

**Current State:**
- `CaptureSession` takes `list[FrameSource]` directly
- No workflow to: load profiles -> match cameras -> apply controls -> create session

**What's Needed:**
```python
def create_session_from_profiles(
    repo: ProfileRepository,
    discovered: list[FrameSourceOptions],
) -> tuple[CaptureSession, dict[str, CameraProfile]]:
    """Build CaptureSession from saved profiles.

    1. Match profiles to discovered cameras by bus_info
    2. Apply V4L2 controls to each matched camera
    3. Create FrameSources with profile settings
    4. Return session and the profile mapping
    """
    matched = {}
    sources = []

    for options in discovered:
        profile = repo.get_by_bus_info(options.bus_info)
        if profile is None:
            # New camera - create default profile
            profile = CameraProfile.with_defaults(
                cam_id=repo.next_cam_id(),
                bus_info=options.bus_info,
            )
            repo.save(profile)

        if profile.ignore:
            continue

        # Apply controls and create config
        config = apply_profile_and_create_config(profile, options.path)
        source = FrameSource(options.path, config)
        sources.append(source)
        matched[options.path] = profile

    return CaptureSession(sources), matched
```

---

## Implementation Sequence

### Phase A: V4L2 Control Integration (NEXT)

1. **Create `src/multiwebcam/sources/controls.py`**
   - Port `V4L2Control` dataclass from `08_camera_controls.py`
   - Make frozen, add slots
   - Port `query_device_controls()`, `set_device_control()`, `get_device_control()`
   - Add `DeviceControls` wrapper

2. **Create `ControlValue` dataclass**
   - Add to `profiles/camera_profile.py`
   - Stores value + constraints

3. **Update `CameraProfile`**
   - Replace `exposure`, `gain`, `white_balance`, `focus` with `controls: dict[str, ControlValue]`
   - Add migration note for existing TOML files

4. **Update `ProfileRepository`**
   - Serialize controls as nested TOML tables
   - Handle missing controls gracefully

5. **Write tests**
   - `tests/sources/test_controls.py` - parsing, query
   - `tests/profiles/test_camera_profile.py` - controls dict
   - `tests/profiles/test_repository.py` - TOML round-trip

### Phase B: Profile-Session Integration

6. **Create profile-session bridge**
   - `apply_profile_and_create_config()` function
   - `create_session_from_profiles()` function

7. **Integration tests**
   - Profile -> controls applied -> camera opened -> capture works

### Phase C: Qt UI

8. **Basic grid view** (no controls editing)
9. **Focus mode with control sliders**
10. **PipelineBridge for Qt integration**

---

## Project Folder Structure

```
<project_root>/
+-- multiwebcam.toml              # Camera profiles and settings
+-- calibration/
|   +-- intrinsic/
|   |   +-- cam_0.mp4             # One per camera, overwrite on re-record
|   |   +-- cam_1.mp4
|   |   +-- cam_2.mp4
|   +-- extrinsic/
|       +-- cam_0.mp4             # ONE set per project, overwrite on re-record
|       +-- cam_1.mp4
|       +-- cam_2.mp4
|       +-- frametimes.csv
+-- recordings/
    +-- <trial_name>/             # Multiple trials, user names each one
        +-- cam_0.mp4
        +-- cam_1.mp4
        +-- cam_2.mp4
        +-- frametimes.csv
```

---

## Quick Reference

### Creating a Capture Session (Current API)

```python
from multiwebcam.sources.discovery import discover_frame_sources
from multiwebcam.sources.device import FrameSource
from multiwebcam.sources.config import FrameSourceConfig
from multiwebcam.pipeline.session import CaptureSession

# Discover cameras
options = discover_frame_sources()

# Create sources with default config
sources = [FrameSource(opt.path, opt.suggested_config()) for opt in options]

# Start session
with CaptureSession(sources) as session:
    while True:
        frames = session.get_latest_frames()
        # Display frames...

    # Recording
    session.start_recording(Path("output"), cam_ids={...})
    # ... record ...
    result = session.stop_recording()
```

### Using Profiles (Current API)

```python
from pathlib import Path
from multiwebcam.profiles import CameraProfile, ProfileRepository

# Load profiles
repo = ProfileRepository(Path("project_dir"))
profiles = repo.load_all()

# Match with discovered cameras
discovered = discover_frame_sources()
for profile in profiles:
    matched = next((d for d in discovered if d.bus_info == profile.bus_info), None)
    if matched:
        print(f"cam_{profile.cam_id} ({profile.label}) at {matched.path}")

# Update and save
updated = profile.with_resolution((1920, 1080))
repo.save(updated)
```

### V4L2 Control Discovery (After Integration)

```python
from multiwebcam.sources.controls import query_device_controls, set_device_control

# Query controls
device_controls = query_device_controls("/dev/video0")
for ctrl in device_controls.controls:
    print(f"{ctrl.name}: {ctrl.current_value} [{ctrl.min_value}-{ctrl.max_value}]")

# Set manual exposure
set_device_control("/dev/video0", "exposure_auto", 1)  # Manual mode
set_device_control("/dev/video0", "exposure_absolute", 250)
```

---

## Files Referenced

### Core Package
- `src/multiwebcam/sources/discovery.py` - Device discovery
- `src/multiwebcam/sources/device.py` - FrameSource
- `src/multiwebcam/sources/config.py` - FrameSourceConfig
- `src/multiwebcam/sources/controls.py` - **TO CREATE** - V4L2 control discovery
- `src/multiwebcam/pipeline/session.py` - CaptureSession
- `src/multiwebcam/recording/recorder.py` - FrameRecorder
- `src/multiwebcam/profiles/camera_profile.py` - CameraProfile (NEEDS UPDATE)
- `src/multiwebcam/profiles/repository.py` - ProfileRepository (NEEDS UPDATE)

### Exploration Scripts
- `scripts/pyav_exploration/08_camera_controls.py` - **Source for controls.py**
- `scripts/pyav_exploration/NOTES.md` - Hardware findings
