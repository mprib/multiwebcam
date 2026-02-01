#!/usr/bin/env python3
"""
Script 12: Continuous Capture & Jitter Analysis

Measure timing jitter during extended continuous frame capture.
Validates PyAV can run stably for 5+ minutes without memory leaks or degradation.

Key questions answered:
1. What is the inter-frame jitter over extended capture?
2. Does jitter increase over time (thermal/driver issues)?
3. Is memory stable (no frame accumulation)?
4. What percentage of frames exceed expected interval by >50%?

Usage:
    uv run python scripts/pyav_exploration/12_continuous_capture.py [device] [--duration MINUTES]
"""

import argparse
import os
import sys
from dataclasses import dataclass
from time import perf_counter

import av
import cv2
import numpy as np


@dataclass(frozen=True, slots=True)
class CaptureStats:
    """Statistics from continuous capture session."""

    frame_count: int
    duration_seconds: float
    actual_fps: float
    interval_mean_ms: float
    interval_std_ms: float
    interval_min_ms: float
    interval_max_ms: float
    interval_p95_ms: float
    interval_p99_ms: float
    jitter_events: list[tuple[int, float]]  # (frame_index, interval_ms)
    memory_samples: list[int]  # RSS at intervals


def frame_to_bgr(frame) -> np.ndarray:
    """Convert PyAV frame to BGR numpy array."""
    if frame.format.name in ("yuvj422p", "yuvj420p"):
        rgb_frame = frame.reformat(format="rgb24")
        return cv2.cvtColor(rgb_frame.to_ndarray(), cv2.COLOR_RGB2BGR)
    else:
        return frame.to_ndarray(format="bgr24")


def get_rss_mb() -> int:
    """Get current process RSS memory in MB."""
    with open("/proc/self/statm") as f:
        # statm fields: size resident shared text lib data dt
        # resident is in pages, page size typically 4KB
        fields = f.read().split()
        resident_pages = int(fields[1])
        page_size = os.sysconf("SC_PAGE_SIZE")
        return (resident_pages * page_size) // (1024 * 1024)


def continuous_capture(
    device: str,
    duration_minutes: float = 5.0,
    target_fps: float = 30.0,
    resolution: str = "640x480",
) -> CaptureStats:
    """
    Capture continuously and collect timing statistics.

    Args:
        device: V4L2 device path
        duration_minutes: How long to capture
        target_fps: Expected framerate
        resolution: Capture resolution

    Returns:
        CaptureStats with timing analysis
    """
    duration_seconds = duration_minutes * 60
    target_interval_ms = 1000.0 / target_fps
    jitter_threshold_ms = target_interval_ms * 1.5  # 50% over expected

    options = {
        "input_format": "mjpeg",
        "video_size": resolution,
        "framerate": str(int(target_fps)),
    }

    print(f"Opening {device} at {resolution} {target_fps}fps (MJPEG)...")
    container = av.open(device, format="v4l2", options=options)

    timestamps: list[float] = []
    memory_samples: list[int] = []
    last_memory_check = 0.0
    memory_interval = 10.0  # Sample memory every 10 seconds

    start_time = perf_counter()
    initial_rss = get_rss_mb()
    memory_samples.append(initial_rss)

    print(f"\nCapturing for {duration_minutes:.1f} minutes...")
    print(f"Target interval: {target_interval_ms:.1f}ms, jitter threshold: {jitter_threshold_ms:.1f}ms")
    print()

    frame_count = 0
    for frame in container.decode(video=0):
        now = perf_counter()
        timestamps.append(now)

        # Convert frame to ensure no lazy decoding issues
        _ = frame_to_bgr(frame)

        elapsed = now - start_time

        # Memory sampling
        if elapsed - last_memory_check >= memory_interval:
            memory_samples.append(get_rss_mb())
            last_memory_check = elapsed

        frame_count += 1

        # Progress every 30 seconds
        if frame_count % (int(target_fps) * 30) == 0:
            current_fps = frame_count / elapsed if elapsed > 0 else 0
            current_rss = get_rss_mb()
            print(
                f"  {elapsed/60:.1f}min: {frame_count} frames, "
                f"{current_fps:.1f} fps, RSS={current_rss}MB"
            )

        if elapsed >= duration_seconds:
            break

    container.close()
    final_time = perf_counter()

    # Calculate intervals
    intervals_ms = [
        (timestamps[i + 1] - timestamps[i]) * 1000 for i in range(len(timestamps) - 1)
    ]

    # Find jitter events
    jitter_events = [
        (i + 1, interval)
        for i, interval in enumerate(intervals_ms)
        if interval > jitter_threshold_ms
    ]

    total_duration = final_time - start_time
    actual_fps = (len(timestamps) - 1) / total_duration if total_duration > 0 else 0

    return CaptureStats(
        frame_count=len(timestamps),
        duration_seconds=total_duration,
        actual_fps=actual_fps,
        interval_mean_ms=float(np.mean(intervals_ms)),
        interval_std_ms=float(np.std(intervals_ms)),
        interval_min_ms=float(np.min(intervals_ms)),
        interval_max_ms=float(np.max(intervals_ms)),
        interval_p95_ms=float(np.percentile(intervals_ms, 95)),
        interval_p99_ms=float(np.percentile(intervals_ms, 99)),
        jitter_events=jitter_events[:20],  # First 20 only
        memory_samples=memory_samples,
    )


def print_report(stats: CaptureStats, target_fps: float) -> None:
    """Print analysis report."""
    target_interval = 1000.0 / target_fps
    expected_frames = int(stats.duration_seconds * target_fps)

    print("\n" + "=" * 70)
    print("Continuous Capture Report")
    print("=" * 70)

    print(f"\nCapture Summary")
    print("-" * 40)
    print(f"  Duration: {stats.duration_seconds:.1f}s ({stats.duration_seconds/60:.1f} minutes)")
    print(f"  Frames: {stats.frame_count} (expected ~{expected_frames})")
    print(f"  Actual FPS: {stats.actual_fps:.2f} (target: {target_fps})")
    fps_ratio = stats.actual_fps / target_fps * 100
    print(f"  FPS achievement: {fps_ratio:.1f}%")

    print(f"\nInter-Frame Intervals")
    print("-" * 40)
    print(f"  Target: {target_interval:.2f}ms")
    print(f"  Mean:   {stats.interval_mean_ms:.2f}ms")
    print(f"  Stddev: {stats.interval_std_ms:.2f}ms")
    print(f"  Min:    {stats.interval_min_ms:.1f}ms")
    print(f"  Max:    {stats.interval_max_ms:.1f}ms")
    print(f"  P95:    {stats.interval_p95_ms:.1f}ms")
    print(f"  P99:    {stats.interval_p99_ms:.1f}ms")

    print(f"\nJitter Events (>{target_interval * 1.5:.0f}ms)")
    print("-" * 40)
    print(f"  Count: {len(stats.jitter_events)}")
    jitter_rate = len(stats.jitter_events) / stats.frame_count * 100 if stats.frame_count > 0 else 0
    print(f"  Rate: {jitter_rate:.3f}%")
    if stats.jitter_events:
        print("  First 5 events:")
        for frame_idx, interval in stats.jitter_events[:5]:
            print(f"    Frame {frame_idx}: {interval:.1f}ms")

    print(f"\nMemory Analysis")
    print("-" * 40)
    if len(stats.memory_samples) > 1:
        initial = stats.memory_samples[0]
        final = stats.memory_samples[-1]
        peak = max(stats.memory_samples)
        growth = final - initial
        print(f"  Initial RSS: {initial}MB")
        print(f"  Final RSS:   {final}MB")
        print(f"  Peak RSS:    {peak}MB")
        print(f"  Growth:      {growth:+d}MB")

        if growth > 50:
            print("  WARNING: Significant memory growth detected")
        else:
            print("  OK: Memory stable")
    else:
        print("  Insufficient samples")

    # Verdict
    print("\n" + "=" * 70)
    print("Verdict")
    print("=" * 70)

    issues = []
    if fps_ratio < 95:
        issues.append(f"FPS below target ({fps_ratio:.1f}% of target)")
    if stats.interval_std_ms > 5:
        issues.append(f"High jitter (stddev {stats.interval_std_ms:.1f}ms)")
    if jitter_rate > 1:
        issues.append(f"Excessive jitter events ({jitter_rate:.2f}%)")
    if len(stats.memory_samples) > 1 and stats.memory_samples[-1] - stats.memory_samples[0] > 50:
        issues.append("Memory leak suspected")

    if not issues:
        print("PASS: Continuous capture is stable")
        print(f"  - FPS within tolerance ({fps_ratio:.1f}%)")
        print(f"  - Jitter acceptable (stddev {stats.interval_std_ms:.1f}ms)")
        print(f"  - Memory stable")
    else:
        print("ISSUES DETECTED:")
        for issue in issues:
            print(f"  - {issue}")


def main():
    parser = argparse.ArgumentParser(
        description="Test continuous capture stability and measure jitter"
    )
    parser.add_argument("device", nargs="?", default="/dev/video0", help="V4L2 device path")
    parser.add_argument(
        "--duration", type=float, default=5.0, help="Capture duration in minutes (default: 5)"
    )
    parser.add_argument("--fps", type=float, default=30.0, help="Target framerate (default: 30)")
    parser.add_argument("--resolution", default="640x480", help="Capture resolution")
    args = parser.parse_args()

    print("=" * 70)
    print("PyAV Exploration - Script 12: Continuous Capture")
    print("=" * 70)
    print(f"\nDevice: {args.device}")
    print(f"Duration: {args.duration} minutes")
    print(f"Target FPS: {args.fps}")
    print(f"Resolution: {args.resolution}")

    stats = continuous_capture(
        args.device,
        duration_minutes=args.duration,
        target_fps=args.fps,
        resolution=args.resolution,
    )

    print_report(stats, args.fps)


if __name__ == "__main__":
    main()
