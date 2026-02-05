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

    # Recording
    def start_recording(self, output_dir: Path) -> None: ...
    def stop_recording(self) -> RecordingResult | None: ...

    # Source replacement (config change without session restart)
    def replace_source(self, device_path: str, new_config: FrameSourceConfig) -> FrameSourceStatus: ...

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
- **Explicit lifecycle** via `start()`/`stop()` - no context manager (session is long-lived, injected into presenters)

**Pause/resume for focus mode**:
```python
def pause_producer(self, device_path: str) -> None: ...
def resume_producer(self, device_path: str) -> None: ...
def pause_all_except(self, device_path: str) -> None: ...
def resume_all(self) -> None: ...
```

**Source replacement** (config change without session restart):
```python
def replace_source(self, device_path: str, new_config: FrameSourceConfig) -> FrameSourceStatus: ...
```
Stops old producer, creates new FrameSource + FrameProducer with same queues. Blocked during recording (would corrupt MP4 encoder). Used by focus mode when user applies new resolution/format/fps.

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

## Part 2: Recording System (IMPLEMENTED)

### Camera Identification: `cam_id`

**Key design decision**: Cameras are identified by `cam_id`, an integer assigned when a camera is first added to the project.

| Concept | Purpose | Example |
|---------|---------|---------|
| `cam_id` | Stable identifier in all data files | `0`, `1`, `2` |
| `device_path` | Ephemeral V4L2 path (changes across reboots) | `/dev/video0` |
| `bus_info` | Stable USB identifier for matching cameras | `usb-0000:00:14.0-3.1` |

**Why `cam_id`?**
- `device_path` changes when cameras are plugged in different order
- `bus_info` is stable but unwieldy for filenames and CSV columns
- `cam_id` is simple, human-readable, and stays consistent for the project lifetime

**Assignment rules:**
- `cam_id` starts at 0
- Assigned sequentially when camera is first added to project
- Never reused (even if camera is removed)
- Persisted in `multiwebcam.toml`

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

**Responsibility**: Drains recording queues and writes MP4 + frametimes.csv for a single recording session.

```python
class FrameRecorder:
    """
    Drains recording queues and writes MP4 + frametimes.csv.

    Owns per-camera encoder threads. CaptureSession creates one FrameRecorder
    per recording session (start_recording creates it, stop_recording destroys it).
    """

    def __init__(
        self,
        recording_queues: dict[int, Queue[FramePacket]],  # cam_id -> queue
        output_dir: Path,
        codec: str = "h264",
        resolution: tuple[int, int] | None = None,  # If None, use first frame's resolution
    ) -> None: ...

    def start(self) -> None:
        """Start encoder threads. Call after is_recording flag is set."""
        ...

    def stop(self, drain_timeout: float = 10.0) -> RecordingResult:
        """
        Signal stop, drain remaining frames, finalize files.

        Returns RecordingResult with per-camera frame counts and any errors.
        """
        ...

    @property
    def is_running(self) -> bool: ...

    @property
    def frames_written(self) -> dict[int, int]:
        """Per-camera frame counts (cam_id -> count)."""
        ...

    @property
    def recording_duration(self) -> float:
        """Seconds since start() was called."""
        ...
```

**RecordingResult** (returned by stop()):

```python
@dataclass(frozen=True)
class RecordingResult:
    output_dir: Path
    frames_per_camera: dict[int, int]   # cam_id -> frame count
    duration_seconds: float
    errors: list[str]                   # Any non-fatal errors encountered
    frametimes_path: Path               # Path to frametimes.csv
```

### Thread Model

```
                    CaptureSession
                          |
            +-------------+-------------+
            |                           |
    is_recording.set()           FrameRecorder
                                       |
              +------------------------+------------------------+
              |                        |                        |
    CameraEncoder(cam_0)      CameraEncoder(cam_1)      CameraEncoder(cam_2)
    - drains queue           - drains queue           - drains queue
    - writes MP4             - writes MP4             - writes MP4
    - reports timestamps     - reports timestamps     - reports timestamps
              |                        |                        |
              +------------------------+------------------------+
                                       |
                              FrametimesCollector
                              (aggregates timestamps,
                               writes CSV on stop)
```

**Key design decisions**:

1. **One encoder thread per camera**: Each `CameraEncoder` drains its recording queue independently and writes to its own MP4 file. No cross-camera coordination during encoding.

2. **Timestamps collected centrally**: Each encoder thread reports `(cam_id, frame_index, frame_time)` to a thread-safe `FrametimesCollector`. The collector writes frametimes.csv when recording stops.

3. **Sentinel-based shutdown**: When `stop()` is called:
   - `is_recording` flag is cleared (producers stop pushing)
   - A `None` sentinel is pushed to each recording queue
   - Encoder threads drain until they see the sentinel, then exit
   - Main thread joins all encoder threads
   - frametimes.csv is written
   - MP4 containers are finalized

4. **FrameRecorder is ephemeral**: One instance per recording. CaptureSession creates it on `start_recording()`, destroys it on `stop_recording()`. This avoids state accumulation across recordings.

### CameraEncoder (Internal)

```python
class CameraEncoder:
    """
    Per-camera worker thread that drains queue and writes MP4.

    Internal to FrameRecorder - not part of public API.
    """

    def __init__(
        self,
        cam_id: int,
        queue: Queue[FramePacket | None],  # None = sentinel
        output_path: Path,
        codec: str,
        timestamp_callback: Callable[[int, int, float], None],  # (cam_id, frame_index, frame_time)
    ) -> None: ...

    def run(self) -> None:
        """
        Main loop: drain queue, encode frames, report timestamps.

        Exits when sentinel (None) is received.
        """
        ...
```

### frametimes.csv Format

**Simplified format** - uses `cam_id` as the stable identifier:

```csv
cam_id,frame_index,frame_time
0,0,1234.567890
1,0,1234.568123
2,0,1234.565012
0,1,1234.600456
1,1,1234.601234
2,1,1234.599876
0,2,1234.633123
1,2,1234.634012
2,2,1234.632456
```

**Column definitions**:
- `cam_id`: Stable camera identifier (integer, assigned per-project)
- `frame_index`: Per-camera sequential index (matches MP4 frame number)
- `frame_time`: PTS or wall-clock timestamp in seconds

**What's NOT in frametimes.csv**:
- `device_path` - Ephemeral, changes between sessions
- `timestamp_source` - Not needed for downstream processing
- `sync_index` - Temporal alignment is Caliscope's job, not ours

**Why this format?**

1. **Simple** - Three columns, easy to parse
2. **Lossless** - Every frame's exact timestamp is preserved
3. **Stable identifiers** - `cam_id` matches across sessions, unlike `device_path`
4. **Alignment-agnostic** - Caliscope applies clustering algorithm, not us

**File creation**: Written atomically at recording stop, not streamed during recording. This avoids partial writes if recording is interrupted.

### Video Filename Convention

Files use `cam_id` in filenames for consistency with frametimes.csv:

```
cam_0.mp4
cam_1.mp4
cam_2.mp4
```

The mapping from `cam_id` to human-readable label is stored in `multiwebcam.toml`, not embedded in filenames.

### Shutdown Sequence

When `CaptureSession.stop_recording()` is called:

```
1. is_recording.clear()
   - Producers immediately stop pushing to recording queues
   - Display and alignment queues continue normally

2. For each recording queue: queue.put(None)
   - Sentinel signals "no more frames coming"

3. FrameRecorder.stop(drain_timeout=10.0)
   a. Each CameraEncoder drains queue until sentinel
   b. Encoder threads join (with timeout)
   c. MP4 containers finalized
   d. FrametimesCollector writes CSV
   e. Returns RecordingResult

4. FrameRecorder instance is discarded
   - CaptureSession sets self._frame_recorder = None
```

**Drain guarantee**: The sentinel ensures all queued frames are written. The `drain_timeout` is a safety valve - if an encoder thread hangs, we don't block forever. Frames that couldn't be written are logged as errors in RecordingResult.

### Error Handling

**Encoder errors** (codec failure, corrupt frame):
- Log error with frame details
- Skip frame, continue with next
- Count skipped frames in RecordingResult.errors

**Disk full**:
- Encoder thread catches OSError
- Stops writing, logs error
- Recording continues for other cameras
- Error reported in RecordingResult

**Camera disconnect during recording**:
- Producer thread exits (handled by existing error handling)
- Recording queue receives no more frames
- Encoder drains what it has, then waits for sentinel
- Sentinel arrives during stop_recording()
- Other cameras' recordings are unaffected

**Thread timeout on stop**:
- If encoder thread doesn't exit within `drain_timeout`
- Log warning, force-terminate is NOT done (daemon threads exit with process)
- Return partial RecordingResult with warning

### Integration with CaptureSession

```python
# In CaptureSession

def start_recording(self, output_dir: Path) -> None:
    """
    Begin recording all cameras to output_dir.

    Args:
        output_dir: Directory for MP4 files and frametimes.csv
    """
    if self._is_recording.is_set():
        raise CaptureSessionError("Already recording")

    output_dir.mkdir(parents=True, exist_ok=True)

    # Extract recording queues with cam_id keys
    recording_queues = {
        cam_id: self._producer_queues[cam_id].recording
        for cam_id in self._producer_queues.keys()
    }

    # Create recorder
    self._frame_recorder = FrameRecorder(
        recording_queues=recording_queues,
        output_dir=output_dir,
    )

    # Start recording (order matters: flag first, then recorder)
    self._is_recording.set()
    self._frame_recorder.start()


def stop_recording(self) -> RecordingResult | None:
    """
    Stop recording and finalize files.

    Returns RecordingResult with frame counts and any errors,
    or None if not recording.
    """
    if not self._is_recording.is_set():
        return None

    # Clear flag first (producers stop pushing)
    self._is_recording.clear()

    # Send sentinels
    for queues in self._producer_queues.values():
        queues.recording.put(None)

    # Stop recorder (drains queues, finalizes files)
    result = self._frame_recorder.stop()
    self._frame_recorder = None

    return result
```

### Project Folder Structure

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

**Key points:**
- Filename = `cam_<cam_id>.mp4` (stable across sessions)
- Human-readable labels are stored in TOML, not filenames
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
  - Checked = active, will be recorded
  - Unchecked = ignored, excluded from recording
- `[F]` button - Enter focus mode for this camera
- Camera label (user-assigned, defaults to `cam_N`)
- FPS (this camera's actual frame rate)
- Jitter (this camera's timing consistency)
- `[IGNORED]` shown if checkbox unchecked (greyed out tile)

**Ignored camera behavior:**
- Tile appears greyed out with `[IGNORED]` status
- Checkbox is unchecked
- Still has a `cam_id` (identity is stable)
- User can toggle checkbox to re-enable
- Excluded from recording when ignored

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
- Record Extrinsic -> `calibration/extrinsic/cam_<id>.mp4` + frametimes.csv
- Record Trial -> `recordings/<trial_name>/cam_<id>.mp4` + frametimes.csv

---

### Focus Mode (Single Camera)

Enter by clicking [F] on any camera tile. Side-panel layout: large video on the left, configuration controls on the right.

```
+---------------------------------------------------------------------+
| multiwebcam                                        [Settings] [?]    |
+---------------------------------------------------------------------+
|  +----------------------------------------------+ +----------------+|
|  |                                              | | Configuration  ||
|  |                                              | |                ||
|  |            front_left (focused)              | | Format: [mjpeg]||
|  |                                              | | Res:  [1280x720]|
|  |            (AspectRatioLabel -                | | FPS:     [30]  ||
|  |             letterbox/pillarbox)              | |                ||
|  |                                              | | [  Apply  ]    ||
|  |                                              | |                ||
|  +----------------------------------------------+ | front_left     ||
|                                                    | (source 0)     ||
|                                                    | 29.8fps|2.1ms  ||
|                                                    |                ||
|                                                    | [Back to Grid] ||
|                                                    +----------------+|
+---------------------------------------------------------------------+
```

**Focus mode features:**
- Large preview (75% width) with aspect-ratio-preserving display
- Configuration side panel (25% width) with format/resolution/FPS dropdowns
- Apply button commits changes (stops old producer, restarts with new config)
- Resolution changes are blocked during recording (would corrupt MP4 encoder)
- V4L2 control sliders (exposure, gain, white balance, focus) - planned
- All settings save to TOML immediately when applied

**Config change flow:**
1. User selects format → cascades to available resolutions
2. User selects resolution → cascades to available framerates
3. User clicks Apply → CaptureSession.replace_source() swaps the producer
4. Profile updated and saved to TOML

**Actions from focus mode:**
- Record Intrinsic -> `calibration/intrinsic/cam_<id>.mp4` (no frametimes.csv)
- Back to Grid -> return to multi-camera view

**Why focus mode for intrinsic?**
Intrinsic calibration is per-camera (solo checkerboard views). You want a large preview to frame the checkerboard properly. Multi-camera recording (extrinsic/trials) happens from grid view.

---

### MVP Architecture (Passive View Pattern)

**Composition Root**: CaptureCoordinator owns session lifecycle and wires presenters to views.

```
CaptureCoordinator (composition root for capture subsystem)
├── CaptureSession (model, long-lived, explicit start/stop)
├── ActiveSources (runtime device_path ↔ cam_id mapping)
│
└── Creates/destroys on view switch:
    ├── SingleSourcePresenter + FocusView
    └── MultiSourcePresenter + GridView
```

**Key Principles:**

1. **Long-lived session** - CaptureSession created once, lives for app lifetime. Switching views doesn't restart capture.

2. **Presenter owns QTimer** - Polls `session.get_latest_frames()` at display rate, converts numpy→QPixmap, emits signals.

3. **Passive views** - Views connect to presenter signals. Presenters never call view methods directly.

4. **Composition root wiring** - All signal/slot connections happen in Coordinator. Presenters and Views never import each other.

**SingleSourcePresenter** (focus mode):
```python
class SingleSourcePresenter(QObject):
    frame_ready = Signal(QPixmap)
    stats_updated = Signal(object)

    def __init__(self, session: CaptureSession, device_path: str, poll_ms: int = 33): ...
    def activate(self) -> None:   # Pause other producers, start timer
    def deactivate(self) -> None: # Resume all, stop timer
```

**MultiSourcePresenter** (grid mode):
```python
class MultiSourcePresenter(QObject):
    frames_ready = Signal(dict)       # cam_id -> QPixmap
    stats_updated = Signal(dict)      # cam_id -> SourceStats
    alignment_updated = Signal(object)
    recording_started = Signal()
    recording_stopped = Signal(object)  # RecordingResult

    def __init__(self, session: CaptureSession, cam_id_lookup: dict[str, int], poll_ms: int = 33): ...
    def activate(self) -> None:
    def deactivate(self) -> None:
    def start_recording(self, output_dir: Path) -> None: ...
    def stop_recording(self) -> RecordingResult | None: ...
```

**Coordinator wiring example:**
```python
# In CaptureCoordinator.show_focus_view()
presenter = SingleSourcePresenter(self._session, device_path)
view = FocusView()
presenter.frame_ready.connect(view.display_frame)
presenter.stats_updated.connect(view.update_stats)
view.back_requested.connect(self._on_back_to_grid)
presenter.activate()
return view
```

---

## Part 5: Camera Profiles and Config (PARTIALLY IMPLEMENTED)

### SourceProfile

**Location**: `src/multiwebcam/profiles/profile.py`

**Status**: IMPLEMENTED (needs update for controls dict)

**Naming rationale**: This package captures frames from video devices. "Camera" implies optical properties, calibration, physical location - that's Caliscope's domain. Internally we use "source". Output files use `cam_` prefix (`cam_0.mp4`) because that's Caliscope's expected format.

```python
@dataclass(frozen=True)
class ControlValue:
    """A V4L2 control setting with its constraints."""
    value: int                  # Current/desired value
    min: int                    # Minimum allowed
    max: int                    # Maximum allowed


@dataclass(frozen=True)
class SourceProfile:
    source_id: int                  # Stable identifier (maps to Caliscope's camera_id)
    bus_info: str                   # Stable USB identifier for matching
    label: str                      # User-assigned label (defaults to "source_N")
    ignore: bool = False            # If True, excluded from recording
    resolution: tuple[int, int] = (1280, 720)
    pixel_format: str = "mjpeg"
    capture_fps: int = 30
    controls: dict[str, ControlValue] = field(default_factory=dict)
```

**Key fields:**
- `source_id`: Stable integer, assigned when source first added to project. Maps 1:1 to Caliscope's `camera_id`.
- `label`: Human-readable name, defaults to `source_N`, user can change
- `bus_info`: USB topology identifier, used to match sources on reload
- `ignore`: If True, source appears greyed out and is excluded from recording
- `controls`: Dict of V4L2 control name -> ControlValue (value + min/max range)

**Why controls dict instead of hardcoded fields?**
- V4L2 control names vary by camera (`exposure_absolute` vs `exposure_time_absolute`)
- Different cameras support different controls
- Storing min/max enables UI sliders without re-querying hardware
- Forward compatible - new controls don't require schema changes

### ProfileRepository

**Location**: `src/multiwebcam/profiles/repository.py`

**Status**: IMPLEMENTED (needs update for controls dict)

```python
class ProfileRepository:
    def __init__(self, project_path: Path) -> None: ...
    def load_all(self) -> list[CameraProfile]: ...
    def save(self, profile: CameraProfile) -> None: ...
    def delete(self, cam_id: int) -> bool: ...
    def get_by_bus_info(self, bus_info: str) -> CameraProfile | None: ...
    def get_by_cam_id(self, cam_id: int) -> CameraProfile | None: ...
    def next_cam_id(self) -> int: ...  # Returns max(cam_ids) + 1, or 0 if empty
```

### Project Config (multiwebcam.toml)

Compact inline format - each source is a self-contained block:

```toml
[[sources]]
source_id = 0
label = "front_left"
bus_info = "usb-0000:00:14.0-3.1"
ignore = false
resolution = [1280, 720]
pixel_format = "mjpeg"
capture_fps = 30
controls.brightness = { value = 128, min = 0, max = 255 }
controls.exposure_time_absolute = { value = 150, min = 2, max = 1250 }
controls.gain = { value = 32, min = 0, max = 100 }

[[sources]]
source_id = 1
label = "overhead"
bus_info = "usb-0000:00:14.0-3.2"
ignore = false
resolution = [1280, 720]
pixel_format = "mjpeg"
capture_fps = 30
controls.brightness = { value = 100, min = 0, max = 255 }
controls.exposure_time_absolute = { value = 200, min = 3, max = 2047 }
controls.gain = { value = 40, min = 0, max = 255 }

[[sources]]
source_id = 2
label = "side"
bus_info = "usb-0000:00:14.0-4"
ignore = true
resolution = [1280, 720]
pixel_format = "mjpeg"
capture_fps = 30
controls.brightness = { value = 64, min = -64, max = 64 }
controls.exposure_time_absolute = { value = 100, min = 1, max = 5000 }
```

### V4L2 Control Discovery

**Location**: `scripts/pyav_exploration/08_camera_controls.py` (needs integration into package)

**Target**: `src/multiwebcam/sources/controls.py` (TO CREATE)

Production-ready code exists in the exploration script:

```python
@dataclass(frozen=True)
class V4L2Control:
    """A V4L2 camera control discovered from hardware."""
    name: str                   # e.g., "brightness"
    control_type: str           # "int", "bool", "menu"
    min_value: int | None
    max_value: int | None
    step: int | None
    default_value: int | None
    current_value: int | None
    menu_items: tuple[tuple[int, str], ...] | None = None


@dataclass(frozen=True)
class DeviceControls:
    """All V4L2 controls for a device."""
    device_path: str
    controls: tuple[V4L2Control, ...]

    def get_control(self, name: str) -> V4L2Control | None: ...


def query_device_controls(device_path: str) -> DeviceControls: ...
def set_device_control(device_path: str, control_name: str, value: int) -> bool: ...
def get_device_control(device_path: str, control_name: str) -> int | None: ...
```

**Key findings from 08_camera_controls.py:**

1. **Auto vs Manual modes** - Must set to Manual before adjusting related controls:
   - `exposure_auto`: 1=Manual, 3=Aperture Priority (auto)
   - `white_balance_temperature_auto`: 0=Manual, 1=Auto
   - `focus_auto`: 0=Manual, 1=Auto

2. **Control dependencies** - Some controls only work when auto is disabled:
   - `exposure_absolute` only works when `exposure_auto=1`
   - `white_balance_temperature` only works when wb_auto=0

3. **Set controls BEFORE opening PyAV stream** - Recommended workflow:
   1. Configure controls with v4l2-ctl subprocess
   2. Then open stream with PyAV
   3. Controls persist while device is open

4. **Per-camera variation** - Available controls vary significantly by camera model

### Planned: Startup Workflow

**Fresh start (no project):**
1. Launch app with no arguments
2. Discover connected cameras, connect with default settings
3. Assign temporary `cam_id` values (0, 1, 2, ...)
4. User configures each camera (resolution, exposure, etc.)
5. User saves: File > Save Project -> picks folder -> creates `multiwebcam.toml`
6. That folder becomes the project root, `cam_id` assignments are now permanent

**Open existing project:**
1. Launch app -> File > Open -> select folder containing `multiwebcam.toml`
2. Load camera profiles from TOML
3. Discover connected cameras (get `bus_info` for each)
4. Match cameras by `bus_info`:
   - If match found -> auto-assign `cam_id` from profile
   - If no match -> prompt user to confirm assignment
5. Apply saved settings automatically (resolution, exposure, gain, focus, etc.)
6. If configured camera not found -> show "offline" placeholder in grid (greyed, checkbox unchecked)
7. User can start recording immediately with known-good settings

**Mismatch handling:**
When `bus_info` doesn't match (camera plugged into different USB port):
- Show dialog: "Camera 'front_left' was at usb-X, now found at usb-Y. Use this camera?"
- User confirms or reassigns
- Update `bus_info` in TOML if confirmed

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

### Current Structure (Updated)

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
|   +-- controls.py         # [TO CREATE] V4L2Control, query_device_controls()
|
+-- pipeline/
|   +-- __init__.py
|   +-- signals.py          # StartSignal, StopSignal, ShutdownSignal [IMPLEMENTED]
|   +-- producer.py         # FrameProducer, ProducerQueues [IMPLEMENTED]
|   +-- alignment.py        # AlignmentMonitor, AlignmentStats, Cluster [IMPLEMENTED]
|   +-- report.py           # CameraStats [IMPLEMENTED]
|   +-- session.py          # CaptureSession [IMPLEMENTED]
|
+-- recording/              # [IMPLEMENTED]
|   +-- __init__.py
|   +-- recorder.py         # FrameRecorder, RecordingResult
|   +-- encoder.py          # CameraEncoder (internal)
|   +-- frametimes.py       # FrametimesCollector, write_frametimes_csv()
|
+-- profiles/               # [IMPLEMENTED - needs controls update]
|   +-- __init__.py
|   +-- profile.py          # SourceProfile, ControlValue dataclasses
|   +-- repository.py       # ProfileRepository
|
+-- ui/                     # [NOT IMPLEMENTED]
    +-- __init__.py
    +-- conversion.py       # frame_to_pixmap() utility
    +-- coordinator.py      # CaptureCoordinator (composition root)
    +-- presenters/
    |   +-- __init__.py
    |   +-- single_source.py  # SingleSourcePresenter (focus mode)
    |   +-- multi_source.py   # MultiSourcePresenter (grid mode)
    +-- views/
        +-- __init__.py
        +-- aspect_ratio_label.py  # AspectRatioLabel (aspect-preserving pixmap display)
        +-- grid_view.py      # GridView with SourceTile widgets
        +-- focus_view.py     # FocusView (large preview + stats)
        +-- source_tile.py    # Single source display widget
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

### Phase 2: Recording (COMPLETE)

**Goal**: Save frames to MP4 + frametimes.csv without frame loss.

- [x] `recording/frametimes.py` - FrametimesCollector
- [x] `recording/encoder.py` - CameraEncoder
- [x] `recording/recorder.py` - FrameRecorder, RecordingResult
- [x] Integration with CaptureSession
- [x] Test script validating frame counts and timestamps

**Tested**: Recording validated with multiple cameras. Frame counts match, frametimes.csv correctly populated.

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

### Phase 5: Camera Profiles (IN PROGRESS)

**Goal**: Save/load camera settings per project.

- [x] `profiles/camera_profile.py` - CameraProfile dataclass (basic)
- [x] `profiles/repository.py` - ProfileRepository (TOML persistence)
- [x] Profile matching by bus_info
- [ ] Update CameraProfile to use `controls: dict[str, ControlValue]`
- [ ] Create `sources/controls.py` - V4L2 control discovery (port from 08_camera_controls.py)
- [ ] Update ProfileRepository for controls dict TOML format
- [ ] V4L2 control widgets (exposure, gain sliders) - deferred to UI phase

**Dependencies**: Phase 2 complete

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

3. ~~**Camera label assignment**: How does user map device_path to meaningful labels? Via profile editor.~~ **Resolved**: Users edit the `label` field in the profile editor. Defaults to `cam_N`.

4. **Reconnection handling**: If a camera disconnects during recording, what happens to the other cameras? Current answer: they keep recording, disconnected camera's file is finalized.

5. ~~**Memory pressure**: Current design doesn't auto-regulate fps on memory pressure. Recording queues could grow unbounded if recorder can't keep up. May need monitoring + backpressure.~~ **Resolved**: FrameRecorder drains queues continuously. If encoder can't keep up with capture rate, queue grows; if it exceeds buffer size, producers block (bounded queue). This is acceptable for recording - slight latency increase won't affect recorded content.

6. ~~**Camera identification in data files**: Should we use device_path, port, or something else?~~ **Resolved**: Use `cam_id` (integer). It's stable across sessions, simple, and matches Caliscope's `port` concept (will eventually be renamed to `cam_id` in Caliscope for consistency).

7. ~~**Temporal alignment responsibility**: Should multiwebcam produce sync_index clusters?~~ **Resolved**: No. Temporal alignment (clustering frames into sync groups) is Caliscope's job. Multiwebcam just records truthfully with accurate timestamps. The "widen bucket until duplicate" algorithm is used by Caliscope for alignment.

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
