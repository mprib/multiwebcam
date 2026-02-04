# Triple-Queue Architecture with Alignment Monitoring

## Overview

Implement a three-queue-per-camera architecture that separates display (transient), recording (gold standard), and alignment monitoring (quality metrics). This replaces the previous single-queue approach and adds lightweight alignment quality tracking.

## Motivation

**Problem 1**: Current single display queue (maxsize=1) serves both display AND stats calculation
- Stats use frame counter + wall-clock interval (inaccurate)
- Can't calculate true FPS from actual frame timestamps
- Can't measure frame interval jitter

**Problem 2**: No alignment quality visibility during capture
- Removed complex FrameAligner (~400 lines, 62% partial clusters)
- But CV engineer says users need alignment feedback
- Need lightweight alternative for monitoring, not clustering

**Problem 3**: No recording queue infrastructure
- Future recording needs separate queue (preserve all frames)
- Display queue drops frames (maxsize=1) - wrong for recording

## Goals

1. **Accurate per-camera metrics**: FPS and jitter from actual frame timestamps
2. **Alignment quality visibility**: Cluster completeness, temporal spread
3. **Recording infrastructure**: Separate queue ready for FrameRecorder implementation
4. **Clean architecture**: Session owns queues, clear data flow

## Non-Goals

- Full frame clustering for real-time use (deferred to Caliscope post-processing)
- Recording implementation (future PR - just the queue infrastructure)
- Dynamic fps adjustment (future enhancement if needed)

## Architecture

### Queue Ownership: Session owns all queues

**Pattern**: CaptureSession creates queues, passes to producers and consumers

```python
@dataclass
class ProducerQueues:
    """Bundle of output queues for a single camera."""
    display: Queue[FramePacket | None]       # maxsize=1, drop-oldest
    recording: Queue[FramePacket]             # large, blocking
    alignment: Queue[FramePacket]             # large, for monitoring

class CaptureSession:
    def __init__(self, sources, recording_buffer_seconds=5.0, alignment_window_seconds=3.0):
        self._producer_queues: dict[str, ProducerQueues] = {}
        self.recording_buffer_seconds = recording_buffer_seconds
        self.alignment_window_seconds = alignment_window_seconds

    def start(self):
        # Create queues for each camera
        for source in self.sources:
            path = source.device_path
            buffer_size = int(recording_buffer_seconds * 30)  # assume ~30fps

            self._producer_queues[path] = ProducerQueues(
                display=Queue(maxsize=1),
                recording=Queue(maxsize=buffer_size),
                alignment=Queue(maxsize=buffer_size),
            )

        # Start producers with all three queues
        for source in self.sources:
            queues = self._producer_queues[source.device_path]
            producer = FrameProducer(
                source,
                output_queues=[queues.display, queues.recording, queues.alignment],
            )
            producer.start()

        # Start alignment monitor
        alignment_queues = {p: q.alignment for p, q in self._producer_queues.items()}
        self._alignment_monitor = AlignmentMonitor(
            alignment_queues,
            expected_cameras=len(self.sources),
            window_seconds=self.alignment_window_seconds,
        )
        self._alignment_monitor.start()
```

**Rationale**: Session already orchestrates lifecycle. Centralized ownership makes data flow visible and enables memory monitoring.

### Producer: Push to multiple queues

```python
class FrameProducer:
    def __init__(
        self,
        source: FrameSource,
        output_queues: list[Queue[FramePacket]],
    ):
        self.source = source
        self.output_queues = output_queues
        self._frames_captured = 0

    @property
    def frames_captured(self) -> int:
        """Total frames captured (thread-safe read via GIL)."""
        return self._frames_captured

    def _run(self):
        for packet in self.source:
            if self._shutdown_event.is_set():
                break

            packet.frame.flags.writeable = False
            self._frames_captured += 1

            # Display queue: drop-oldest (index 0 by convention)
            try:
                self.output_queues[0].get_nowait()
            except Empty:
                pass
            self.output_queues[0].put_nowait(packet)

            # Recording and alignment queues: blocking put (index 1, 2)
            for queue in self.output_queues[1:]:
                queue.put(packet)  # blocks if full (backpressure)
```

**Note**: Producer doesn't know what queues are for, just pushes to all. Index 0 is special (drop-oldest), rest are blocking.

### Alignment Monitor: Collect-until-duplicate

```python
@dataclass(frozen=True, slots=True)
class FrameMetadata:
    """Lightweight frame metadata (no image array)."""
    device_path: str
    frame_index: int
    frame_time: float

@dataclass(frozen=True, slots=True)
class Cluster:
    """Frames collected before duplicate camera appeared."""
    frames: list[FrameMetadata]
    window_duration: float  # Time from first frame to duplicate
    completeness: float     # Fraction of expected cameras present

    @property
    def spread_ms(self) -> float:
        """Temporal spread: max(pts) - min(pts) in milliseconds."""
        if len(self.frames) < 2:
            return 0.0
        times = [f.frame_time for f in self.frames]
        return (max(times) - min(times)) * 1000

class AlignmentMonitor:
    """
    Monitors multi-camera alignment quality using collect-until-duplicate.

    Drains alignment queues, builds clusters, computes statistics.
    Does NOT produce aligned output - purely observational.
    """

    def __init__(
        self,
        alignment_queues: dict[str, Queue[FramePacket]],
        expected_cameras: int,
        window_seconds: float = 3.0,
    ):
        self._queues = alignment_queues
        self._expected_cameras = expected_cameras
        self._window_seconds = window_seconds

        # Rolling window of recent clusters
        self._recent_clusters: deque[Cluster] = deque()

        # Per-camera frame tracking for jitter calculation
        self._camera_frames: dict[str, deque[FrameMetadata]] = {
            path: deque() for path in alignment_queues.keys()
        }

        self._shutdown_event = Event()
        self._thread: Thread | None = None

    def _run(self):
        """Background thread: drain queues, build clusters, update stats."""
        while not self._shutdown_event.is_set():
            # Drain all alignment queues
            all_frames = self._drain_queues()

            # Build clusters using collect-until-duplicate
            new_clusters = self._build_clusters(all_frames)

            # Update rolling window
            self._recent_clusters.extend(new_clusters)
            self._evict_old_clusters()

            # Update per-camera frame history
            self._update_camera_frames(all_frames)

            time.sleep(0.1)  # Avoid busy loop

    def _drain_queues(self) -> list[FrameMetadata]:
        """Drain alignment queues, extract metadata only."""
        all_metadata = []
        for device_path, queue in self._queues.items():
            while True:
                try:
                    packet = queue.get_nowait()
                    metadata = FrameMetadata(
                        device_path=packet.device_path,
                        frame_index=packet.frame_index,
                        frame_time=packet.frame_time,
                    )
                    all_metadata.append(metadata)
                except Empty:
                    break

        # Sort by timestamp for cluster algorithm
        all_metadata.sort(key=lambda m: m.frame_time)
        return all_metadata

    def _build_clusters(self, frames: list[FrameMetadata]) -> list[Cluster]:
        """
        Collect frames until duplicate camera appears.

        Algorithm:
        - Start with empty window
        - Add frames until we see a camera twice
        - Emit cluster, start new window with duplicate frame
        """
        clusters = []
        window = []
        seen_cameras = set()
        window_start_time = None

        for frame in frames:
            if frame.device_path in seen_cameras:
                # Duplicate camera - emit cluster
                if window:
                    window_duration = frame.frame_time - window_start_time
                    completeness = len(window) / self._expected_cameras
                    clusters.append(Cluster(
                        frames=window,
                        window_duration=window_duration,
                        completeness=completeness,
                    ))

                # Start new window with this frame
                window = [frame]
                seen_cameras = {frame.device_path}
                window_start_time = frame.frame_time
            else:
                # New camera in window
                if not window:
                    window_start_time = frame.frame_time
                window.append(frame)
                seen_cameras.add(frame.device_path)

        return clusters

    def get_alignment_stats(self) -> AlignmentStats | None:
        """Get alignment quality over recent window."""
        if not self._recent_clusters:
            return None

        complete_clusters = [c for c in self._recent_clusters if c.completeness == 1.0]
        complete_pct = (len(complete_clusters) / len(self._recent_clusters)) * 100

        spreads = [c.spread_ms for c in self._recent_clusters]
        mean_spread = sum(spreads) / len(spreads)
        max_spread = max(spreads)

        durations = [c.window_duration * 1000 for c in self._recent_clusters]
        mean_duration = sum(durations) / len(durations)

        return AlignmentStats(
            complete_cluster_pct=complete_pct,
            mean_spread_ms=mean_spread,
            max_spread_ms=max_spread,
            mean_window_duration_ms=mean_duration,
            total_clusters=len(self._recent_clusters),
        )

    def get_camera_stats(self) -> dict[str, CameraStats]:
        """Get per-camera stats (fps, jitter) from recent frames."""
        stats = {}
        for device_path, frames in self._camera_frames.items():
            if len(frames) < 2:
                continue

            # Calculate FPS from timestamps
            duration = frames[-1].frame_time - frames[0].frame_time
            if duration > 0:
                measured_fps = (len(frames) - 1) / duration
            else:
                measured_fps = 0.0

            # Calculate jitter (stddev of inter-frame intervals)
            intervals = [
                frames[i+1].frame_time - frames[i].frame_time
                for i in range(len(frames) - 1)
            ]
            if intervals:
                mean_interval = sum(intervals) / len(intervals)
                variance = sum((x - mean_interval) ** 2 for x in intervals) / len(intervals)
                jitter_ms = (variance ** 0.5) * 1000
            else:
                jitter_ms = 0.0

            stats[device_path] = CameraStats(
                device_path=device_path,
                frames_in_window=len(frames),
                measured_fps=measured_fps,
                jitter_ms=jitter_ms,
                queue_depth=self._queues[device_path].qsize(),
            )

        return stats
```

### Updated CameraStats

```python
@dataclass(frozen=True, slots=True)
class CameraStats:
    """Per-camera statistics over measurement window."""
    device_path: str
    frames_in_window: int      # Frames in measurement window
    measured_fps: float        # From actual frame timestamps
    jitter_ms: float           # Stddev of inter-frame intervals
    queue_depth: int           # Current alignment queue depth
```

### New AlignmentStats

```python
@dataclass(frozen=True, slots=True)
class AlignmentStats:
    """Multi-camera alignment quality over measurement window."""
    complete_cluster_pct: float      # 0-100, % of clusters with all cameras
    mean_spread_ms: float            # Average temporal spread within clusters
    max_spread_ms: float             # Worst-case spread (for flagging issues)
    mean_window_duration_ms: float   # Average time to collect complete cluster
    total_clusters: int              # Clusters in measurement window
```

## Data Flow

```
                    ┌─────────────────┐
                    │ Display Queue   │
                    │ (maxsize=1)     │
              ┌────▶│ drop-oldest     │────▶ get_latest_frames() → UI
              │     └─────────────────┘
              │
┌───────────┐ │     ┌─────────────────┐
│FrameSource│─┼────▶│ Recording Queue │
│ (PyAV)    │ │     │ (maxsize=150)   │────▶ FrameRecorder (future)
└───────────┘ │     │ blocking put    │
              │     └─────────────────┘
              │
              │     ┌─────────────────┐
              │     │ Alignment Queue │
              └────▶│ (maxsize=150)   │────▶ AlignmentMonitor
                    │ blocking put    │       ├─ Cluster stats
                    └─────────────────┘       └─ Camera stats
```

## Implementation Tasks

### Phase 1: Queue Infrastructure

1. Create `ProducerQueues` dataclass in `producer.py`
2. Update `FrameProducer.__init__` to accept `output_queues: list[Queue]`
3. Update `FrameProducer._run()` to push to all queues (drop-oldest for [0], blocking for [1:])
4. Update `CaptureSession.__init__` to create `_producer_queues: dict[str, ProducerQueues]`
5. Update `CaptureSession.start()` to pass all three queues to producers

### Phase 2: Alignment Monitoring

6. Create `pipeline/alignment.py` with:
   - `FrameMetadata` dataclass
   - `Cluster` dataclass
   - `AlignmentStats` dataclass
   - `AlignmentMonitor` class
7. Update `CameraStats` in `report.py` to add `jitter_ms` field, rename `frames_received` → `frames_in_window`
8. Integrate `AlignmentMonitor` into `CaptureSession.start()`
9. Add `CaptureSession.get_alignment_stats()` method
10. Update `CaptureSession.get_camera_stats()` to use AlignmentMonitor when available

### Phase 3: Cleanup & Export

11. Update `__init__.py` to export new types: `ProducerQueues`, `AlignmentStats`, `AlignmentMonitor`
12. Update module docstring to reflect three-queue architecture
13. Remove old monitoring code that used producer properties (if AlignmentMonitor active)

## Testing Strategy

### Unit Tests (Future)

- `test_cluster_building()`: Verify collect-until-duplicate algorithm with synthetic timestamps
- `test_fps_calculation()`: Check FPS from actual timestamps vs wall-clock
- `test_jitter_calculation()`: Verify stddev of intervals
- `test_alignment_stats()`: Check completeness, spread calculations

### Manual Testing

1. **Single camera**: Verify stats show reasonable fps, low jitter
2. **Multi-camera**: Check alignment stats, cluster completeness
3. **Mixed FPS**: One camera 30fps, another 15fps - verify completeness ~50% as expected
4. **Shutdown**: All queues drain cleanly, no thread hangs

## Migration Path

**Backward compatibility**: Existing `get_latest_frames()` API unchanged. New `get_alignment_stats()` is additive.

**Old monitoring code**: The previous `_update_monitoring_stats()` using producer properties can remain as fallback if `AlignmentMonitor` disabled.

## Performance Considerations

**Memory**:
- Alignment queue: 150 frames × 3 cameras × 6MB/frame (1080p) = ~2.7GB
- Metadata only: 150 frames × 3 cameras × 40 bytes = ~18KB (negligible)
- AlignmentMonitor stores metadata, not frame arrays

**CPU**:
- Draining queues: `O(n)` where n = frames in queue
- Sorting frames: `O(n log n)`
- Building clusters: `O(n)` single pass
- Combined: ~hundreds of microseconds for typical drain

**Thread count**: +1 (AlignmentMonitor thread)

## Success Criteria

1. ✅ Per-camera FPS calculated from actual frame timestamps (not wall-clock)
2. ✅ Jitter measurement (stddev of inter-frame intervals)
3. ✅ Alignment quality metrics (completeness %, temporal spread)
4. ✅ Clean shutdown (all threads terminate within 5s)
5. ✅ Type checking passes (basedpyright)
6. ✅ Works with 1-4 cameras at various FPS

## Future Work (Out of Scope)

- FrameRecorder implementation (drains recording queue, writes MP4 + frametimes.csv)
- Dynamic fps adjustment based on queue depth
- Alignment quality thresholds/warnings
- Historical stats tracking (trends over time)
