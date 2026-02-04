# Multiwebcam Architecture

Consolidated architecture specification for the multiwebcam capture and recording system.

---

## Project Vision

A multi-camera capture and recording system built on PyAV/FFmpeg for cheap USB webcams.

**What this is:** Capture frames from multiple cameras independently with accurate timestamps. Record all frames to MP4 + frametimes.csv for offline processing. Display latest frames for real-time framing/exposure feedback.

**What this is NOT:** True synchronization. That requires hardware genlock, external triggers, or specialized cameras.

**The pitch:** Consumer USB webcams, no special hardware. For room-scale capture, casual 3D reconstruction, multi-angle documentation, the typical 10-50ms alignment precision is acceptable.

**Philosophy:** Record truthfully, align later. Temporal alignment is deferred to post-processing (Caliscope) where full timestamp data enables better decisions. Real-time alignment adds complexity without benefit for recording workflows.

---

## Part 1: Pipeline Architecture (IMPLEMENTED)

### Triple-Queue Design

The core innovation: each camera pushes frames to THREE separate queues with different behaviors.

```
FrameSource --> FrameProducer --> Display Queue (maxsize=1, drop-oldest)
                              --> Recording Queue (blocking, preserve ALL)
                              --> Alignment Queue (blocking, for monitoring)
```

**Why three queues?**

| Queue | Purpose | Behavior | Drop Policy |
|-------|---------|----------|-------------|
| Display | Latest frame for UI | maxsize=1 | Drop oldest (always latest) |
| Recording | Lossless capture | Large buffer | Never drop |
| Alignment | Quality monitoring | Large buffer | Drained by monitor |

This design achieves two critical goals:
1. **Never drop frames for recording** - every frame is preserved
2. **Always have latest frame for display** - no stale UI

### Layer Structure

```
+-----------------------------------------------+
|                    View                       |  Qt widgets (NOT IMPLEMENTED)
+-----------------------------------------------+
|                  Presenter                    |  Workflow coordination (NOT IMPLEMENTED)
+-----------------------------------------------+
|              CaptureSession                   |  Application service
|     (owns Sources, Producers, Queues, Monitor)|
+-----------------------------------------------+
| FrameSource | FrameProducer | AlignmentMonitor|  Domain/Infrastructure
+-----------------------------------------------+
```

### Core Components

#### FrameSource

**Location**: `src/multiwebcam/sources/device.py`

**Status**: IMPLEMENTED

Passive iterator that yields FramePackets from a V4L2 device. No threading, no queues.

```python
class FrameSource:
    def __init__(self, device_path: str, config: FrameSourceConfig | None = None): ...
    def start(self) -> FrameSourceStatus: ...
    def stop(self) -> None: ...
    def __iter__(self) -> Iterator[FramePacket]: ...

    @property
    def is_running(self) -> bool: ...
    @property
    def device_path(self) -> str: ...
    @property
    def device_id(self) -> int: ...
```

**Key behaviors**:
- Opens device via PyAV with V4L2 backend
- Validates resolution matches requested (fails fast if camera silently falls back)
- Determines timestamp source (PTS vs wall-clock) based on first frame
- Discards warmup frames during USB enumeration
- Yields immutable FramePacket instances

#### FramePacket

**Location**: `src/multiwebcam/sources/frame_packet.py`

**Status**: IMPLEMENTED

Immutable frame data flowing through the pipeline.

```python
@dataclass(frozen=True, slots=True)
class FramePacket:
    device_path: str                            # e.g., "/dev/video0"
    device_id: int                              # Extracted from path (e.g., 0)
    frame_index: int                            # Sequential from this source
    frame_time: float                           # Timestamp in seconds
    timestamp_source: Literal["pts", "wall_clock"]
    frame: np.ndarray                           # BGR, shape (H, W, 3)
    fps: float                                  # Rolling average
```

#### FrameProducer

**Location**: `src/multiwebcam/pipeline/producer.py`

**Status**: IMPLEMENTED

Threaded wrapper that pulls frames from FrameSource and pushes to three queues.

```python
@dataclass
class ProducerQueues:
    display: Queue[FramePacket]     # maxsize=1, drop-oldest
    recording: Queue[FramePacket]   # large, conditional on is_recording
    alignment: Queue[FramePacket]   # large, for monitoring

class FrameProducer:
    def __init__(
        self,
        source: FrameSource,
        queues: ProducerQueues,
        is_recording: Event,        # Shared flag from CaptureSession
    ) -> None: ...

    def start(self) -> None: ...
    def stop(self, timeout: float = 5.0) -> None: ...

    @property
    def is_running(self) -> bool: ...
    @property
    def device_path(self) -> str: ...
    @property
    def frames_captured(self) -> int: ...
```

**Key behaviors**:
- Runs a daemon thread that iterates over the source
- Display queue: drop-oldest (try get_nowait, then put_nowait)
- Alignment queue: blocking put (always)
- Recording queue: conditional put (only when `is_recording.is_set()`)
- Sets `frame.flags.writeable = False` to enforce immutability
- Clean shutdown via Event + source.stop() from main thread

#### AlignmentMonitor

**Location**: `src/multiwebcam/pipeline/alignment.py`

**Status**: IMPLEMENTED

Drains alignment queues, builds clusters, computes quality statistics. Does NOT produce aligned output - purely observational.

```python
@dataclass(frozen=True, slots=True)
class FrameMetadata:
    device_path: str
    frame_index: int
    frame_time: float

@dataclass(frozen=True, slots=True)
class Cluster:
    frames: list[FrameMetadata]
    window_duration: float      # Time from first frame to duplicate
    completeness: float         # Fraction of expected cameras present

    @property
    def spread_ms(self) -> float: ...

@dataclass(frozen=True, slots=True)
class AlignmentStats:
    complete_cluster_pct: float     # 0-100, % with all cameras
    mean_spread_ms: float           # Average temporal spread
    max_spread_ms: float            # Worst-case spread
    mean_window_duration_ms: float  # Average collection time
    total_clusters: int

class AlignmentMonitor:
    def __init__(
        self,
        alignment_queues: dict[str, Queue[FramePacket]],
        expected_cameras: int,
        window_seconds: float = 3.0,
    ): ...

    def start(self) -> None: ...
    def stop(self, timeout: float = 5.0) -> None: ...
    def get_alignment_stats(self) -> AlignmentStats | None: ...
    def get_camera_stats(self) -> dict[str, CameraStats]: ...
```

**Alignment algorithm (collect-until-duplicate)**:

This replaces the previous nearest-neighbor clustering. Much simpler:

1. Drain all alignment queues, extract metadata only (no image data)
2. Sort frames by timestamp
3. Iterate through sorted frames:
   - If camera NOT in current window: add to window
   - If camera IS in current window (duplicate): emit cluster, start new window with this frame
4. Calculate cluster metrics (spread, completeness)

**Why collect-until-duplicate?**

- Simple to implement and debug
- No fixed tolerance thresholds to tune
- Naturally handles varying frame rates
- Provides useful quality metrics without the complexity of real-time alignment
- Key insight: we don't NEED aligned output - we just need to know alignment quality

#### CameraStats

**Location**: `src/multiwebcam/pipeline/report.py`

**Status**: IMPLEMENTED

```python
@dataclass(frozen=True, slots=True)
class CameraStats:
    device_path: str
    frames_in_window: int       # Frames in measurement window
    measured_fps: float         # Actual frame rate from timestamps
    jitter_ms: float            # Stddev of inter-frame intervals
    queue_depth: int            # Current alignment queue depth
```

#### CaptureSession

**Location**: `src/multiwebcam/pipeline/session.py`

**Status**: IMPLEMENTED

Application service that orchestrates the pipeline.

```python
class CaptureSession:
    def __init__(
        self,
        sources: list[FrameSource],
        enable_monitoring: bool = True,
        monitor_interval_seconds: float = 2.0,
        recording_buffer_seconds: float = 5.0,
        alignment_window_seconds: float = 3.0,
    ) -> None: ...

    def start(self) -> None: ...
    def stop(self) -> None: ...

    # Display (consumes from display queues)
    def get_latest_frames(self) -> dict[str, FramePacket | None]: ...

    # Monitoring
    def get_camera_stats(self) -> dict[str, CameraStats] | None: ...
    def get_alignment_stats(self) -> AlignmentStats | None: ...

    # Recording (TODO: FrameRecorder implementation)
    def start_recording(self, output_dir: Path) -> None: ...
    def stop_recording(self) -> None: ...

    @property
    def is_recording(self) -> bool: ...
    @property
    def active_device_paths(self) -> list[str]: ...
```

**Key behaviors**:
- Creates ProducerQueues bundle for each camera
- Owns shared `is_recording` Event flag (producers check this)
- Starts all sources in parallel via ThreadPoolExecutor
- Validates PTS epoch compatibility across cameras
- Creates and starts AlignmentMonitor (if monitoring enabled)
- Context manager support (`with CaptureSession(...) as session:`)

### Data Flow

```
                                     +------------------+
                                     |  CaptureSession  |
                                     |  (owns queues,   |
                                     |   is_recording   |
                                     |   Event flag)    |
                                     +--------+---------+
                                              |
              +-------------------------------+-------------------------------+
              |                               |                               |
     +--------v--------+             +--------v--------+             +--------v--------+
     |   FrameSource   |             |   FrameSource   |             |   FrameSource   |
     |   /dev/video0   |             |   /dev/video2   |             |   /dev/video4   |
     +--------+--------+             +--------+--------+             +--------+--------+
              |                               |                               |
              v                               v                               v
     +--------+--------+             +--------+--------+             +--------+--------+
     |  FrameProducer  |             |  FrameProducer  |             |  FrameProducer  |
     |    Thread 0     |             |    Thread 2     |             |    Thread 4     |
     +--------+--------+             +--------+--------+             +--------+--------+
              |                               |                               |
              v                               v                               v
     +--------+--------+             +--------+--------+             +--------+--------+
     | Display Queue 0 |             | Display Queue 2 |             | Display Queue 4 |
     | (maxsize=1)     |             | (maxsize=1)     |             | (maxsize=1)     |
     +--------+--------+             +--------+--------+             +--------+--------+
              |                               |                               |
              +-------------------------------+-------------------------------+
                                              |
                                              v
                                     +--------+--------+
                                     |  get_latest_    |
                                     |  frames() polls |
                                     +-----------------+

     +--------+--------+             +--------+--------+             +--------+--------+
     | Recording Q 0   |             | Recording Q 2   |             | Recording Q 4   |
     | (conditional)   |             | (conditional)   |             | (conditional)   |
     +--------+--------+             +--------+--------+             +--------+--------+
              |                               |                               |
              +-------------------------------+-------------------------------+
                                              |
                                              v
                                     +--------+--------+
                                     |  FrameRecorder  |
                                     |  (TODO)         |
                                     +-----------------+

     +--------+--------+             +--------+--------+             +--------+--------+
     | Alignment Q 0   |             | Alignment Q 2   |             | Alignment Q 4   |
     +--------+--------+             +--------+--------+             +--------+--------+
              |                               |                               |
              +-------------------------------+-------------------------------+
                                              |
                                              v
                                     +--------+--------+
                                     | AlignmentMonitor|
                                     | (drains,builds  |
                                     |  clusters)      |
                                     +-----------------+
```

**Queue ownership**: CaptureSession creates and owns all queues. Producers receive queue references at construction.

### Configuration

**FrameSourceConfig** (per-camera):

```python
@dataclass(frozen=True, slots=True)
class FrameSourceConfig:
    resolution: tuple[int, int] = (1280, 720)
    fps: int = 30
    pixel_format: str = "mjpeg"
    warmup_frames: int = 5
    v4l2_options: dict[str, str] = field(default_factory=dict)
```

**CaptureSession parameters**:

| Parameter | Default | Purpose |
|-----------|---------|---------|
| `enable_monitoring` | True | Enable AlignmentMonitor |
| `monitor_interval_seconds` | 2.0 | Fallback monitoring window |
| `recording_buffer_seconds` | 5.0 | Recording queue size (seconds * 30fps) |
| `alignment_window_seconds` | 3.0 | Rolling window for alignment stats |

### PTS Validation

On startup, CaptureSession validates that all cameras use compatible timestamp epochs:

1. Start all cameras in parallel (ThreadPoolExecutor)
2. Collect first PTS from each camera
3. Check spread: if `max(pts) - min(pts) >= 60s`, timestamps are incompatible
4. Log warning if some cameras use wall-clock while others use PTS
5. Proceed with capture - downstream (Caliscope) handles alignment

This is validation, not correction. If timestamps are incompatible, we log it and proceed. The recording will still work; alignment quality may be degraded.

---

## Part 2: Recording System (PARTIALLY IMPLEMENTED)

### Current State

**Implemented**:
- `is_recording` Event flag shared between CaptureSession and FrameProducers
- Recording queue infrastructure (conditional push when flag set)
- `start_recording()` / `stop_recording()` stubs on CaptureSession

**Not implemented**:
- FrameRecorder (drains recording queues to disk)
- MP4 encoding via PyAV
- frametimes.csv writing

### Planned: FrameRecorder

**Location**: `src/multiwebcam/recording/recorder.py` (to be created)

```python
class FrameRecorder:
    """Drains recording queues and writes MP4 + frametimes.csv."""

    def __init__(
        self,
        recording_queues: dict[str, Queue[FramePacket]],
        output_dir: Path,
        codec: str = "h264",
    ) -> None: ...

    def start(self) -> None: ...
    def stop(self) -> None: ...

    @property
    def frames_written(self) -> dict[str, int]: ...
    @property
    def duration_seconds(self) -> float: ...
```

**Thread model**:
- One thread per camera (drains recording queue, writes to MP4)
- Main thread collects frame indices for frametimes.csv
- On stop: finalize MP4s, write frametimes.csv

### frametimes.csv Format

```csv
frame_index,camera_0_pts,camera_2_pts,camera_4_pts
0,1234.567,1234.568,1234.565
1,1234.600,1234.601,1234.599
2,1234.633,1234.634,1234.632
3,1234.667,-1,1234.665
```

- One row per "aligned" frame index
- Column per camera (device_id in header)
- Value = PTS timestamp in seconds
- `-1` = frame missing from that camera

**Note**: "aligned" here means the Nth frame from each camera, NOT temporally aligned. Temporal alignment happens in Caliscope using the PTS values.

### Project Folder Structure

```
<project_root>/
+-- multiwebcam.toml              # Camera profiles and settings
+-- calibration/
|   +-- intrinsic/
|   |   +-- front_left.mp4        # One per camera, overwrite on re-record
|   |   +-- overhead.mp4
|   |   +-- side.mp4
|   +-- extrinsic/
|       +-- front_left.mp4        # ONE set per project, overwrite on re-record
|       +-- overhead.mp4
|       +-- side.mp4
|       +-- frametimes.csv
+-- recordings/
    +-- <trial_name>/             # Multiple trials, user names each one
        +-- front_left.mp4
        +-- overhead.mp4
        +-- side.mp4
        +-- frametimes.csv
```

**Key points:**
- Filename = camera label (user-assigned, not device path)
- Intrinsic: one MP4 per camera, no frametimes.csv, overwrite on re-record
- Extrinsic: one set per project (no subfolders), overwrite on re-record
- Recordings: multiple named trials, each in its own subfolder
- frametimes.csv only for multi-camera recordings (extrinsic + trials)

---

## Part 3: Device Discovery (IMPLEMENTED)

**Location**: `src/multiwebcam/sources/discovery.py`

Query V4L2 device capabilities before opening.

```python
@dataclass(frozen=True, slots=True)
class VideoMode:
    pixel_format: str   # e.g., "MJPG", "YUYV"
    width: int
    height: int
    fps: float

@dataclass(frozen=True, slots=True)
class FrameSourceOptions:
    path: str           # e.g., "/dev/video0"
    model: str          # Hardware name from V4L2
    driver: str         # e.g., "uvcvideo"
    bus_info: str       # e.g., "usb-0000:00:14.0-2"
    modes: tuple[VideoMode, ...]

    def supports(self, config: FrameSourceConfig) -> bool: ...
    def suggested_config(self) -> FrameSourceConfig: ...
    def formats(self) -> set[str]: ...
    def resolutions(self, pixel_format: str) -> set[tuple[int, int]]: ...
    def framerates(self, pixel_format: str, width: int, height: int) -> list[float]: ...

def discover_frame_sources() -> list[FrameSourceOptions]: ...
def get_frame_source_options(device_path: str) -> FrameSourceOptions | None: ...
```

**Usage pattern**:

```python
# Discover all cameras
options_list = discover_frame_sources()
for opts in options_list:
    print(f"{opts.path}: {opts.model}")
    print(f"  Suggested config: {opts.suggested_config()}")

# Check if a specific config is supported
config = FrameSourceConfig(resolution=(1920, 1080), fps=30)
if opts.supports(config):
    source = FrameSource(opts.path, config)
else:
    source = FrameSource(opts.path, opts.suggested_config())
```

---

## Part 4: UI Structure (NOT IMPLEMENTED)

### Two View Modes

The app has two view modes: **Grid View** (multi-camera) and **Focus Mode** (single camera).

---

### Grid View (Multi-Camera)

The main view showing all cameras simultaneously.

```
+---------------------------------------------------------------------+
| multiwebcam                                        [Settings] [?]    |
+---------------------------------------------------------------------+
| File                                                                 |
+---------------------------------------------------------------------+
|  +-------------------+  +-------------------+  +-------------------+ |
|  | [x]          [F]  |  | [x]          [F]  |  | [ ]          [F]  | |
|  |    front_left     |  |     overhead      |  |       side        | |
|  |    29.8 fps       |  |    30.1 fps       |  |    [OFFLINE]      | |
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
- `[x]` checkbox - Enable/ignore this camera (unchecked = offline placeholder)
- `[F]` button - Enter focus mode for this camera
- Camera label (user-assigned)
- FPS (this camera's actual frame rate)
- Jitter (this camera's timing consistency)
- `[OFFLINE]` shown if camera ignored or not connected

**Global controls:**
- Recording FPS slider - Controls pull rate from ALL cameras
- Recording type selector - Extrinsic or Trial
- Trial name field - Only shown when Trial selected

**Status bar (global metrics):**
- Camera count (active/configured)
- Alignment spread (how far apart timestamps are across cameras)
- Cluster completeness (% of clusters with all cameras present)
- Average FPS

**Actions from grid view:**
- Record Extrinsic → `calibration/extrinsic/<camera>.mp4` + frametimes.csv
- Record Trial → `recordings/<trial_name>/<camera>.mp4` + frametimes.csv

---

### Focus Mode (Single Camera)

Enter by clicking [F] on any camera tile. Large preview for framing and settings adjustment.

```
+---------------------------------------------------------------------+
| multiwebcam                                        [Settings] [?]    |
+---------------------------------------------------------------------+
| File                                                                 |
+---------------------------------------------------------------------+
|  +---------------------------------------------------------------+  |
|  |                                                               |  |
|  |                                                               |  |
|  |                    front_left (focused)                       |  |
|  |                    /dev/video0                                |  |
|  |                    29.8 fps | jitter: 2.1ms                   |  |
|  |                                                               |  |
|  |                                                               |  |
|  +---------------------------------------------------------------+  |
|                                                                      |
|  Resolution: [v 1280x720]   Format: [v MJPEG]   FPS: [v 30]         |
|                                                                      |
|  Exposure:       [----*------] 150                                  |
|  Gain:           [--*--------] 32                                   |
|  White Balance:  [---*-------] 4500                                 |
|  Focus:          [------*----] 75                                   |
|                                                                      |
|  [Record Intrinsic]                            [Back to Grid]       |
+---------------------------------------------------------------------+
```

**Focus mode features:**
- Large preview for precise framing
- Resolution/format/FPS dropdowns (changes require camera restart)
- V4L2 control sliders (exposure, gain, white balance, focus)
- All settings save to TOML immediately when changed

**Actions from focus mode:**
- Record Intrinsic → `calibration/intrinsic/<camera>.mp4` (no frametimes.csv)
- Back to Grid → return to multi-camera view

**Why focus mode for intrinsic?**
Intrinsic calibration is per-camera (solo checkerboard views). You want a large preview to frame the checkerboard properly. Multi-camera recording (extrinsic/trials) happens from grid view.

---

### Planned: MVP Layer Design

| Component | Responsibility |
|-----------|----------------|
| `CaptureView` | Renders camera tiles, handles Record/Stop clicks |
| `CapturePresenter` | Owns CaptureSession, converts stats to UI model |
| `MainWindow` | File menu, project lifecycle |

### Planned: Qt Integration via PipelineBridge

```python
class PipelineBridge(QObject):
    """Polls queues on QTimer, emits Qt signals."""

    frames_ready = Signal(dict)         # device_path -> QPixmap
    stats_updated = Signal(dict)        # device_path -> CameraStats
    alignment_updated = Signal(object)  # AlignmentStats

    def __init__(
        self,
        session: CaptureSession,
        poll_interval_ms: int = 33,  # ~30fps UI refresh
    ) -> None: ...

    def start(self) -> None: ...
    def stop(self) -> None: ...
```

---

## Part 5: Camera Profiles and Config (NOT IMPLEMENTED)

### Planned: CameraProfile

```python
@dataclass(frozen=True)
class CameraProfile:
    label: str                      # User-assigned label
    bus_info: str                   # Stable USB identifier
    resolution: tuple[int, int]
    pixel_format: str
    capture_fps: int
    exposure: int                   # Manual value (required)
    gain: int
    white_balance: int
    focus: int
```

**No auto mode**: All V4L2 control values are required integers. Scientific reproducibility requires explicit settings.

### Planned: ProfileRepository

```python
class ProfileRepository:
    def __init__(self, project_path: Path) -> None: ...
    def load_all(self) -> list[CameraProfile]: ...
    def save(self, profile: CameraProfile) -> None: ...
    def delete(self, label: str) -> None: ...
    def get_by_bus_info(self, bus_info: str) -> CameraProfile | None: ...
```

### Planned: Project Config (multiwebcam.toml)

```toml
[project]
name = "lab_recording_2024"

[[cameras]]
label = "front_left"
bus_info = "usb-0000:00:14.0-3.1"
resolution = [1280, 720]
pixel_format = "mjpeg"
capture_fps = 30
exposure = 150
gain = 32
white_balance = 4500
focus = 75
```

### Planned: Startup Workflow

**Fresh start (no project):**
1. Launch app with no arguments
2. Discover connected cameras, connect with default settings
3. User configures each camera (resolution, exposure, etc.)
4. User saves: File > Save Project → picks folder → creates `multiwebcam.toml`
5. That folder becomes the project root

**Open existing project:**
1. Launch app → File > Open → select folder containing `multiwebcam.toml`
2. Load camera profiles from TOML
3. Match cameras by `bus_info` (stable USB identifier)
4. **Apply saved settings automatically** (resolution, exposure, gain, focus, etc.)
5. If configured camera not found → show "offline" placeholder in grid
6. User can start recording immediately with known-good settings

**Config persistence:**
- Settings save to TOML immediately when changed (via rtoml, instant)
- No "Save" button needed - changes are always persisted

---

## Part 6: Module Structure

### Current Structure

```
src/multiwebcam/
+-- __init__.py
+-- sources/
|   +-- __init__.py
|   +-- config.py           # FrameSourceConfig, FrameSourceStatus [IMPLEMENTED]
|   +-- device.py           # FrameSource [IMPLEMENTED]
|   +-- discovery.py        # FrameSourceOptions, discover_frame_sources() [IMPLEMENTED]
|   +-- frame_packet.py     # FramePacket [IMPLEMENTED]
|   +-- conversion.py       # frame_to_bgr() [IMPLEMENTED]
|
+-- pipeline/
    +-- __init__.py
    +-- signals.py          # StartSignal, StopSignal, ShutdownSignal [IMPLEMENTED]
    +-- producer.py         # FrameProducer, ProducerQueues [IMPLEMENTED]
    +-- alignment.py        # AlignmentMonitor, AlignmentStats, Cluster [IMPLEMENTED]
    +-- report.py           # CameraStats [IMPLEMENTED]
    +-- session.py          # CaptureSession [IMPLEMENTED]
```

### Planned Structure

```
src/multiwebcam/
+-- recording/              # [NOT IMPLEMENTED]
|   +-- __init__.py
|   +-- recorder.py         # FrameRecorder
|   +-- frametimes.py       # frametimes.csv writing
|
+-- profiles/               # [NOT IMPLEMENTED]
|   +-- __init__.py
|   +-- camera_profile.py   # CameraProfile dataclass
|   +-- repository.py       # ProfileRepository
|
+-- ui/                     # [NOT IMPLEMENTED]
    +-- __init__.py
    +-- main_window.py      # MainWindow
    +-- presenter.py        # CapturePresenter
    +-- camera_tile.py      # CameraTileWidget
    +-- controls.py         # V4L2 control widgets
    +-- bridge.py           # PipelineBridge (Qt integration)
```

---

## Implementation Roadmap

### Phase 1: Triple-Queue Capture Pipeline (COMPLETE)

- [x] FrameSource (PyAV V4L2 capture)
- [x] FrameSourceConfig, FrameSourceStatus
- [x] FramePacket (frozen dataclass)
- [x] Device discovery (v4l2-ctl query)
- [x] FrameProducer (threaded, triple-queue push)
- [x] ProducerQueues (display, recording, alignment)
- [x] AlignmentMonitor (collect-until-duplicate algorithm)
- [x] CameraStats, AlignmentStats
- [x] CaptureSession orchestration
- [x] Recording queue infrastructure (conditional on Event flag)
- [x] PTS validation across cameras
- [x] Manual testing with 5 cameras

**Tested**: The pipeline has been validated with 5 cameras running simultaneously. Alignment stats show typical spread of 10-30ms, with >95% complete clusters at 30fps.

### Phase 2: Recording (NEXT)

**Goal**: Save frames to MP4 + frametimes.csv without frame loss.

Tasks:
1. `recording/recorder.py` - FrameRecorder class
   - Per-camera worker threads drain recording queues
   - PyAV MP4 encoding (h264)
   - Track frame indices for frametimes.csv
2. `recording/frametimes.py` - CSV writing
   - One row per frame index
   - PTS values per camera column
3. Integration with CaptureSession
   - `start_recording()` spawns FrameRecorder
   - `stop_recording()` finalizes files
4. Test script validating lossless capture

**Dependencies**: None (Phase 1 complete)

### Phase 3: Qt Display (NO RECORDING)

**Goal**: Live preview only, no recording UI yet.

Tasks:
1. `ui/bridge.py` - PipelineBridge (QTimer polling)
2. `ui/camera_tile.py` - CameraTileWidget
3. `ui/main_window.py` - MainWindow with grid layout
4. Status bar with fps, alignment metrics
5. Test with 5 cameras

**Dependencies**: Phase 1, Qt/PySide6 setup

### Phase 4: Qt Recording Integration

**Goal**: Record button in UI.

Tasks:
1. Recording panel (Start/Stop buttons)
2. Duration display
3. Output directory selection
4. Integration with FrameRecorder

**Dependencies**: Phase 2, Phase 3

### Phase 5: Camera Profiles

**Goal**: Save/load camera settings per project.

Tasks:
1. `profiles/camera_profile.py` - CameraProfile dataclass
2. `profiles/repository.py` - ProfileRepository (TOML persistence)
3. V4L2 control widgets (exposure, gain sliders)
4. Profile save/load on app lifecycle

**Dependencies**: Phase 3

### Phase 6: Project Management

**Goal**: Create/open projects, manage recordings.

Tasks:
1. File menu (New/Open Project)
2. Project folder structure creation
3. Recording type selection (intrinsic/extrinsic/general)
4. Recording browser

**Dependencies**: Phase 4, Phase 5

---

## Open Questions

1. **V4L2 control availability**: Not all cameras support all controls. Need graceful handling of missing controls in UI.

2. **Recording codec options**: Should we expose codec settings or use sensible defaults? Initial recommendation: defaults only (h264).

3. **Camera label assignment**: How does user map device_path to meaningful labels? Via profile editor.

4. **Reconnection handling**: If a camera disconnects during recording, what happens to the other cameras? Current answer: they keep recording, disconnected camera's file is finalized.

5. **Memory pressure**: Current design doesn't auto-regulate fps on memory pressure. Recording queues could grow unbounded if recorder can't keep up. May need monitoring + backpressure.

---

## Scope Boundary

### This application DOES:

- Capture frames from multiple USB cameras via PyAV
- Display live preview with per-camera fps and alignment metrics
- Record to MP4 + frametimes.csv (lossless)
- Save/load camera profiles (resolution, fps, V4L2 controls)

### This application DOES NOT:

- Run calibration algorithms (that's Caliscope)
- Do 3D reconstruction or triangulation
- Process or analyze recorded footage
- Provide video playback
- Perform real-time temporal alignment (deferred to Caliscope)
- Provide auto-exposure/gain/white-balance modes

---

## References

- [PyAV Documentation](https://pyav.org/docs/develop/)
- [PyAV Numpy Cookbook](https://pyav.org/docs/develop/cookbook/numpy.html)
- [FFmpeg V4L2 Input](https://ffmpeg.org/ffmpeg-devices.html#video4linux2_002c-v4l2)
