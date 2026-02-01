#!/usr/bin/env python3
"""
Script 11: Timestamp Analysis

Compare pts (presentation timestamp) vs wall-clock (perf_counter) for frame timing.
Analyze jitter, drift, and determine best approach for multi-camera temporal alignment.

Key questions answered:
1. What is the relationship between pts and wall-clock time?
2. How much jitter exists in frame timing?
3. Is there drift between pts and wall-clock over time?
4. What timestamp approach should we use for cross-camera alignment?

Usage:
    uv run python scripts/pyav_exploration/11_timestamp_analysis.py [device] [--duration N]
"""

import argparse
import sys
from dataclasses import dataclass
from time import perf_counter

import av
import cv2
import numpy as np


@dataclass(frozen=True, slots=True)
class FrameTiming:
    """Timing data for a single captured frame."""

    frame_index: int
    pts: int | None  # Presentation timestamp from stream (stream time units)
    pts_seconds: float | None  # PTS converted to seconds using time_base
    wall_time: float  # Wall-clock time from perf_counter()
    capture_duration: float  # Time spent in decode call


def frame_to_bgr(frame) -> np.ndarray:
    """Convert PyAV frame to BGR numpy array."""
    if frame.format.name in ("yuvj422p", "yuvj420p"):
        rgb_frame = frame.reformat(format="rgb24")
        return cv2.cvtColor(rgb_frame.to_ndarray(), cv2.COLOR_RGB2BGR)
    else:
        return frame.to_ndarray(format="bgr24")


def capture_with_timing(
    device: str,
    duration_seconds: float = 10.0,
    resolution: str = "640x480",
) -> list[FrameTiming]:
    """
    Capture frames and record both pts and wall-clock timestamps.

    Returns list of FrameTiming objects for analysis.
    """
    options = {
        "input_format": "mjpeg",
        "video_size": resolution,
        "framerate": "30",
    }

    container = av.open(device, format="v4l2", options=options)
    stream = container.streams.video[0]

    # Get time_base for converting pts to seconds
    time_base = stream.time_base
    print(f"Stream time_base: {time_base} ({float(time_base):.9f})")

    timings: list[FrameTiming] = []
    start_time = perf_counter()
    frame_index = 0

    print(f"\nCapturing for {duration_seconds} seconds...")

    for frame in container.decode(video=0):
        capture_end = perf_counter()

        # Record timing
        pts_seconds = None
        if frame.pts is not None and time_base is not None:
            pts_seconds = float(frame.pts * time_base)

        timing = FrameTiming(
            frame_index=frame_index,
            pts=frame.pts,
            pts_seconds=pts_seconds,
            wall_time=capture_end,
            capture_duration=0.0,  # Filled in post-processing
        )
        timings.append(timing)

        frame_index += 1
        elapsed = capture_end - start_time

        if elapsed >= duration_seconds:
            break

        # Progress indicator every 100 frames
        if frame_index % 100 == 0:
            print(f"  {frame_index} frames captured ({elapsed:.1f}s)")

    container.close()

    # Calculate capture durations (time between frames)
    # Replace the frozen dataclass entries with computed durations
    processed_timings = []
    for i, t in enumerate(timings):
        if i == 0:
            duration = 0.0
        else:
            duration = t.wall_time - timings[i - 1].wall_time
        processed_timings.append(
            FrameTiming(
                frame_index=t.frame_index,
                pts=t.pts,
                pts_seconds=t.pts_seconds,
                wall_time=t.wall_time,
                capture_duration=duration,
            )
        )

    return processed_timings


def analyze_wall_clock(timings: list[FrameTiming]) -> dict:
    """Analyze wall-clock timing statistics."""
    if len(timings) < 2:
        return {}

    # Frame intervals from wall clock
    intervals_ms = [t.capture_duration * 1000 for t in timings[1:]]

    total_duration = timings[-1].wall_time - timings[0].wall_time
    actual_fps = (len(timings) - 1) / total_duration if total_duration > 0 else 0

    return {
        "total_frames": len(timings),
        "total_duration_s": total_duration,
        "actual_fps": actual_fps,
        "interval_mean_ms": np.mean(intervals_ms),
        "interval_std_ms": np.std(intervals_ms),
        "interval_min_ms": np.min(intervals_ms),
        "interval_max_ms": np.max(intervals_ms),
    }


def analyze_pts(timings: list[FrameTiming]) -> dict:
    """Analyze PTS (presentation timestamp) statistics."""
    valid_pts = [t for t in timings if t.pts_seconds is not None]

    if len(valid_pts) < 2:
        return {"pts_available": False}

    # PTS intervals
    pts_intervals_ms = []
    for i in range(1, len(valid_pts)):
        interval = (valid_pts[i].pts_seconds - valid_pts[i - 1].pts_seconds) * 1000
        pts_intervals_ms.append(interval)

    pts_duration = valid_pts[-1].pts_seconds - valid_pts[0].pts_seconds

    return {
        "pts_available": True,
        "pts_frames": len(valid_pts),
        "pts_duration_s": pts_duration,
        "pts_interval_mean_ms": np.mean(pts_intervals_ms),
        "pts_interval_std_ms": np.std(pts_intervals_ms),
        "pts_interval_min_ms": np.min(pts_intervals_ms),
        "pts_interval_max_ms": np.max(pts_intervals_ms),
    }


def analyze_pts_epoch(timings: list[FrameTiming]) -> dict:
    """
    Analyze PTS epoch to determine if it's system-relative or stream-relative.

    V4L2 cameras typically provide timestamps based on the kernel's monotonic
    clock (time since boot), which would be comparable across cameras.
    """
    valid_pts = [t for t in timings if t.pts_seconds is not None]

    if not valid_pts:
        return {"epoch_determined": False}

    first_pts_seconds = valid_pts[0].pts_seconds

    # If PTS is in the range of hours/days, it's likely system boot time
    pts_hours = first_pts_seconds / 3600
    pts_days = first_pts_seconds / 86400

    if first_pts_seconds > 3600:  # More than an hour
        return {
            "epoch_determined": True,
            "epoch_type": "system_boot",
            "first_pts_hours": pts_hours,
            "first_pts_days": pts_days,
            "note": "PTS appears to be time since system boot (monotonic clock)",
        }
    else:
        return {
            "epoch_determined": True,
            "epoch_type": "stream_start",
            "first_pts_seconds": first_pts_seconds,
            "note": "PTS appears to start at stream open",
        }


def analyze_drift(timings: list[FrameTiming]) -> dict:
    """
    Analyze drift between PTS time and wall-clock time.

    Drift indicates whether the stream's internal clock is running
    faster or slower than the system clock.
    """
    valid_pts = [t for t in timings if t.pts_seconds is not None]

    if len(valid_pts) < 2:
        return {"drift_available": False}

    # Calculate offset: wall_time - pts_time at each frame
    # Normalize to first frame
    first_wall = valid_pts[0].wall_time
    first_pts = valid_pts[0].pts_seconds

    offsets_ms = []
    for t in valid_pts:
        wall_elapsed = t.wall_time - first_wall
        pts_elapsed = t.pts_seconds - first_pts
        offset = (wall_elapsed - pts_elapsed) * 1000  # milliseconds
        offsets_ms.append(offset)

    wall_duration = valid_pts[-1].wall_time - valid_pts[0].wall_time

    # Drift rate: ms of drift per second of capture
    total_drift_ms = offsets_ms[-1] - offsets_ms[0]
    drift_rate_ms_per_sec = total_drift_ms / wall_duration if wall_duration > 0 else 0

    return {
        "drift_available": True,
        "total_drift_ms": total_drift_ms,
        "drift_rate_ms_per_sec": drift_rate_ms_per_sec,
        "offset_std_ms": np.std(offsets_ms),
    }


def detect_dropped_frames(timings: list[FrameTiming], nominal_fps: float = 30.0) -> dict:
    """Detect likely dropped frames from timing gaps."""
    if len(timings) < 2:
        return {}

    nominal_interval_ms = 1000.0 / nominal_fps
    threshold_ms = nominal_interval_ms * 1.5  # 50% over expected

    drops = []
    for i, t in enumerate(timings[1:], start=1):
        if t.capture_duration * 1000 > threshold_ms:
            drops.append(
                {
                    "frame": i,
                    "gap_ms": t.capture_duration * 1000,
                    "expected_ms": nominal_interval_ms,
                }
            )

    return {
        "dropped_count": len(drops),
        "drops": drops[:10],  # First 10 only
    }


def print_report(
    wall_stats: dict,
    pts_stats: dict,
    pts_epoch: dict,
    drift_stats: dict,
    drop_stats: dict,
) -> None:
    """Print analysis report."""
    print("\n" + "=" * 70)
    print("Timestamp Analysis Report")
    print("=" * 70)

    # Wall-clock analysis
    print("\nWall-Clock Timing (perf_counter)")
    print("-" * 40)
    print(f"  Frames captured: {wall_stats.get('total_frames', 0)}")
    print(f"  Duration: {wall_stats.get('total_duration_s', 0):.2f}s")
    print(f"  Actual FPS: {wall_stats.get('actual_fps', 0):.2f}")
    print(f"  Interval: mean={wall_stats.get('interval_mean_ms', 0):.2f}ms, "
          f"std={wall_stats.get('interval_std_ms', 0):.2f}ms")
    print(f"  Interval range: [{wall_stats.get('interval_min_ms', 0):.1f}, "
          f"{wall_stats.get('interval_max_ms', 0):.1f}]ms")

    # PTS analysis
    print("\nPTS (Presentation Timestamp)")
    print("-" * 40)
    if pts_stats.get("pts_available"):
        print(f"  PTS frames: {pts_stats.get('pts_frames', 0)}")
        print(f"  PTS duration: {pts_stats.get('pts_duration_s', 0):.2f}s")
        print(f"  PTS interval: mean={pts_stats.get('pts_interval_mean_ms', 0):.2f}ms, "
              f"std={pts_stats.get('pts_interval_std_ms', 0):.2f}ms")
        print(f"  PTS interval range: [{pts_stats.get('pts_interval_min_ms', 0):.1f}, "
              f"{pts_stats.get('pts_interval_max_ms', 0):.1f}]ms")
    else:
        print("  PTS not available (frame.pts is None)")

    # PTS epoch analysis
    print("\nPTS Epoch Analysis")
    print("-" * 40)
    if pts_epoch.get("epoch_determined"):
        epoch_type = pts_epoch.get("epoch_type", "unknown")
        if epoch_type == "system_boot":
            print(f"  Epoch type: SYSTEM BOOT (monotonic clock)")
            print(f"  First PTS: {pts_epoch.get('first_pts_hours', 0):.2f} hours since boot")
            print(f"  Note: {pts_epoch.get('note', '')}")
            print("  ** PTS values ARE comparable across cameras on the same system **")
        else:
            print(f"  Epoch type: STREAM START")
            print(f"  First PTS: {pts_epoch.get('first_pts_seconds', 0):.4f}s")
            print(f"  Note: {pts_epoch.get('note', '')}")
    else:
        print("  Could not determine PTS epoch")

    # Drift analysis
    print("\nDrift (Wall-Clock vs PTS)")
    print("-" * 40)
    if drift_stats.get("drift_available"):
        total_drift = drift_stats.get("total_drift_ms", 0)
        drift_rate = drift_stats.get("drift_rate_ms_per_sec", 0)
        print(f"  Total drift: {total_drift:.2f}ms over capture duration")
        print(f"  Drift rate: {drift_rate:.3f}ms/sec")
        print(f"  Offset jitter: {drift_stats.get('offset_std_ms', 0):.2f}ms (stddev)")

        # Interpret drift
        if abs(drift_rate) < 0.1:
            print("  Interpretation: PTS and wall-clock are well-synchronized")
        elif drift_rate > 0:
            print("  Interpretation: Wall-clock running FASTER than PTS clock")
        else:
            print("  Interpretation: Wall-clock running SLOWER than PTS clock")
    else:
        print("  Cannot analyze drift (PTS not available)")

    # Dropped frames
    print("\nDropped Frames")
    print("-" * 40)
    drop_count = drop_stats.get("dropped_count", 0)
    print(f"  Detected drops: {drop_count}")
    if drop_count > 0:
        for d in drop_stats.get("drops", [])[:5]:
            print(f"    Frame {d['frame']}: gap={d['gap_ms']:.1f}ms "
                  f"(expected ~{d['expected_ms']:.1f}ms)")

    # Recommendations
    print("\n" + "=" * 70)
    print("Recommendations for Multi-Camera Sync")
    print("=" * 70)

    if pts_epoch.get("epoch_type") == "system_boot":
        print("""
OBSERVATION: On this system, V4L2 provides hardware timestamps from the
kernel's monotonic clock (time since boot). This appears comparable across
cameras.

RECOMMENDATION: Use PTS with runtime validation
  frame_time = float(frame.pts * stream.time_base)

Why PTS (when available):
  + Kernel-provided timestamp at frame capture, not Python decode time
  + Not affected by Python scheduling jitter or USB transfer latency
  + More accurate representation of when the frame was actually captured

IMPORTANT: Runtime validation required!
  This behavior may vary by kernel/driver/hardware. When opening multiple
  cameras, check that first PTS values are within ~60s of each other.
  If not, PTS epochs differ and you must fall back to perf_counter().

  spread = max(pts_values) - min(pts_values)
  if spread > 60:
      use_wall_clock = True  # Different epochs, can't compare PTS

The "drift" reported above is USB transfer + decode latency, not clock drift.

Expected alignment precision:
  - USB camera jitter: typically 2-30ms stddev
  - Frames in a FrameCluster may be 10-50ms apart
  - This is temporal alignment, not true hardware synchronization
""")
    else:
        print("""
OBSERVATION: PTS epoch appears to be stream-relative (not system boot).
This means PTS values are NOT directly comparable across cameras.

RECOMMENDATION: Use wall-clock (perf_counter)
  frame_time = perf_counter()  # after decode

Note: This includes USB transfer and decode latency, so timestamps
represent "when Python received the frame" not "when camera captured it".

Expected alignment precision:
  - USB camera jitter: typically 2-30ms stddev
  - Frames in a FrameCluster may be 10-50ms apart
  - This is temporal alignment, not true hardware synchronization
""")


def main():
    parser = argparse.ArgumentParser(description="Analyze frame timing and timestamps")
    parser.add_argument("device", nargs="?", default="/dev/video0", help="V4L2 device path")
    parser.add_argument("--duration", type=float, default=10.0, help="Capture duration (seconds)")
    parser.add_argument("--resolution", default="640x480", help="Capture resolution")
    args = parser.parse_args()

    print("=" * 70)
    print("PyAV Exploration - Script 11: Timestamp Analysis")
    print("=" * 70)
    print(f"\nDevice: {args.device}")
    print(f"Duration: {args.duration}s")
    print(f"Resolution: {args.resolution}")

    # Capture with timing data
    timings = capture_with_timing(
        args.device,
        duration_seconds=args.duration,
        resolution=args.resolution,
    )

    print(f"\nCaptured {len(timings)} frames")

    # Analyze
    wall_stats = analyze_wall_clock(timings)
    pts_stats = analyze_pts(timings)
    pts_epoch = analyze_pts_epoch(timings)
    drift_stats = analyze_drift(timings)
    drop_stats = detect_dropped_frames(timings)

    # Report
    print_report(wall_stats, pts_stats, pts_epoch, drift_stats, drop_stats)

    # Dump raw timing data for inspection
    print("\n" + "=" * 70)
    print("Sample Timing Data (first 10 frames)")
    print("=" * 70)
    print(f"{'Frame':<8} {'PTS':<12} {'PTS(s)':<12} {'Wall(s)':<12} {'Interval(ms)':<12}")
    print("-" * 56)
    for t in timings[:10]:
        pts_str = str(t.pts) if t.pts is not None else "None"
        pts_sec_str = f"{t.pts_seconds:.4f}" if t.pts_seconds is not None else "None"
        wall_rel = t.wall_time - timings[0].wall_time
        print(f"{t.frame_index:<8} {pts_str:<12} {pts_sec_str:<12} "
              f"{wall_rel:<12.4f} {t.capture_duration * 1000:<12.2f}")


if __name__ == "__main__":
    main()
