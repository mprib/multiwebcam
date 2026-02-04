# Recording System Implementation Summary

## Overview

Implemented Phase 2 (Recording System) for the multiwebcam project. The recording system drains frames from recording queues and writes them to MP4 files plus a frametimes.csv file.

## Files Created

### Core Recording Module

1. **`src/multiwebcam/recording/__init__.py`**
   - Public API exports for the recording module

2. **`src/multiwebcam/recording/frametimes.py`**
   - `FrametimesCollector`: Thread-safe timestamp collection
   - `write_frametimes_csv()`: Atomic CSV writing
   - Format: `device_path,frame_index,frame_time,timestamp_source`

3. **`src/multiwebcam/recording/encoder.py`**
   - `CameraEncoder`: Per-camera worker thread
   - Drains recording queue, encodes to MP4 via PyAV (h264)
   - Reports timestamps to collector
   - Sentinel-based shutdown (None = stop signal)

4. **`src/multiwebcam/recording/recorder.py`**
   - `FrameRecorder`: Orchestrates multiple CameraEncoders
   - `RecordingResult`: Frozen dataclass with frame counts, errors, paths
   - Creates one encoder thread per camera
   - Manages central FrametimesCollector
   - Drains queues and finalizes files on stop

### Integration

5. **`src/multiwebcam/pipeline/session.py`** (modified)
   - Implemented `start_recording(output_dir, camera_labels)`:
     - Creates FrameRecorder
     - Sets is_recording flag
     - Starts encoder threads
   - Implemented `stop_recording() -> RecordingResult`:
     - Clears is_recording flag
     - Pushes sentinel (None) to recording queues
     - Drains queues and finalizes files
     - Returns RecordingResult

6. **`src/multiwebcam/pipeline/__init__.py`** (modified)
   - Added RecordingResult to public exports

### Testing

7. **`scripts/test_recording.py`**
   - Auto-discovers available cameras
   - Creates CaptureSession with 1-2 cameras
   - Records for 5 seconds to temp directory
   - Validates:
     - MP4 files exist and contain expected frame count
     - frametimes.csv format is correct
     - Frame counts match across MP4 and CSV
   - Prints summary and cleanup temp directory

## Architecture

### Thread Model

```
CaptureSession
    |
    +-- is_recording.set()
    |
    +-- FrameRecorder
            |
            +-- CameraEncoder(cam0) --> cam0.mp4
            +-- CameraEncoder(cam2) --> cam2.mp4
            +-- CameraEncoder(cam4) --> cam4.mp4
            |
            +-- FrametimesCollector --> frametimes.csv
```

### Recording Flow

1. **Start Recording**:
   - `CaptureSession.start_recording(output_dir, camera_labels)`
   - Creates FrameRecorder with recording queues
   - Sets `is_recording` Event flag
   - FrameRecorder spawns encoder threads
   - Producers start pushing to recording queues

2. **During Recording**:
   - Each encoder thread drains its queue
   - Encodes frames to MP4 via PyAV
   - Reports timestamps to FrametimesCollector

3. **Stop Recording**:
   - `CaptureSession.stop_recording()`
   - Clears `is_recording` flag (producers stop pushing)
   - Pushes sentinel (None) to each recording queue
   - Encoders drain remaining frames and exit
   - FrametimesCollector writes CSV atomically
   - Returns RecordingResult with frame counts and errors

### Data Formats

**MP4 Files**:
- Codec: h264
- Format: yuv420p
- One file per camera: `{camera_label}.mp4`

**frametimes.csv**:
```csv
device_path,frame_index,frame_time,timestamp_source
/dev/video0,0,1234.567000,pts
/dev/video2,0,1234.568000,pts
/dev/video0,1,1234.600000,pts
/dev/video2,1,1234.601000,pts
```

- Long format (one row per frame)
- Sorted by (device_path, frame_index)
- 6 decimal places for sub-millisecond precision
- Preserves per-camera frame indices

## Key Design Decisions

1. **One encoder thread per camera**: Independent encoding, no cross-camera coordination needed during recording

2. **Sentinel-based shutdown**: Clean signal (None) to stop encoder threads, ensures all queued frames are written

3. **Atomic CSV write**: Timestamps collected in memory, written once at recording stop (avoids partial writes)

4. **Long format CSV**: Preserves per-camera frame indices and timestamps for flexible post-processing in Caliscope

5. **Ephemeral FrameRecorder**: One instance per recording session, created on start_recording(), destroyed on stop

6. **Error handling**: Encoders log errors and continue with next frame; errors reported in RecordingResult

## Testing

Run the test script:

```bash
uv run python scripts/test_recording.py
```

This will:
- Auto-discover cameras (uses up to 2)
- Record for 5 seconds
- Validate MP4 files and frametimes.csv
- Print summary of results

Expected output:
- MP4 files with ~150 frames (5s * 30fps)
- frametimes.csv with matching row count
- All validation checks passing

## Integration with Spec

This implementation follows the design specified in:
- `specs/multiwebcam_architecture.md` - Part 2: Recording System

All requirements met:
- ✓ PyAV for MP4 encoding (h264)
- ✓ One encoder thread per camera
- ✓ Sentinel value is None
- ✓ frametimes.csv is long format
- ✓ RecordingResult is frozen dataclass
- ✓ Atomic CSV write at recording stop
- ✓ Integration with CaptureSession
- ✓ Test script with validation

## Next Steps

Phase 3 (Qt Display) can now proceed with confidence that the recording backend is solid. The recording system is completely independent of the display layer.
