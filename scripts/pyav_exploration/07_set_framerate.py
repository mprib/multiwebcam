#!/usr/bin/env python3
"""
Script 07: Set Framerate

Request a specific framerate and measure actual delivery over 5+ seconds.
Reports requested vs actual fps, jitter metrics, and frame interval statistics.

Usage:
    uv run python scripts/pyav_exploration/07_set_framerate.py [device]
"""

import sys
from time import perf_counter

import av
import numpy as np


def measure_framerate(
    device: str,
    requested_fps: int,
    duration_seconds: float = 5.0,
    resolution: str = "640x480",
) -> dict:
    """
    Request a framerate and measure actual delivery.

    Args:
        device: V4L2 device path
        requested_fps: Requested framerate
        duration_seconds: How long to capture
        resolution: Resolution to use (lower = less bandwidth = more reliable fps)

    Returns:
        Dictionary with timing statistics
    """
    options = {
        "video_size": resolution,
        "framerate": str(requested_fps),
    }

    container = av.open(device, format="v4l2", options=options)

    frame_times = []
    start_time = perf_counter()

    print(f"  Capturing for {duration_seconds}s at {requested_fps}fps requested...")

    for frame in container.decode(video=0):
        frame_times.append(perf_counter())

        if frame_times[-1] - start_time >= duration_seconds:
            break

    container.close()

    # Calculate statistics
    elapsed = frame_times[-1] - frame_times[0]
    frame_count = len(frame_times)
    actual_fps = (frame_count - 1) / elapsed if elapsed > 0 else 0

    # Frame intervals (time between consecutive frames)
    intervals = np.diff(frame_times)
    expected_interval = 1.0 / requested_fps

    # Jitter metrics
    interval_mean = np.mean(intervals)
    interval_std = np.std(intervals)
    interval_min = np.min(intervals)
    interval_max = np.max(intervals)

    return {
        "requested_fps": requested_fps,
        "actual_fps": actual_fps,
        "frame_count": frame_count,
        "elapsed_seconds": elapsed,
        "interval_mean_ms": interval_mean * 1000,
        "interval_std_ms": interval_std * 1000,
        "interval_min_ms": interval_min * 1000,
        "interval_max_ms": interval_max * 1000,
        "fps_accuracy_percent": (actual_fps / requested_fps) * 100 if requested_fps > 0 else 0,
    }


def print_results(stats: dict) -> None:
    """Print formatted statistics."""
    print(f"\n  Frames received: {stats['frame_count']} in {stats['elapsed_seconds']:.2f}s")
    print(f"  Actual fps: {stats['actual_fps']:.2f} ({stats['fps_accuracy_percent']:.1f}% of requested)")

    print(f"\n  Frame interval statistics:")
    print(f"    Mean: {stats['interval_mean_ms']:.2f}ms (expected: {1000/stats['requested_fps']:.2f}ms)")
    print(f"    Std dev: {stats['interval_std_ms']:.2f}ms")
    print(f"    Min: {stats['interval_min_ms']:.2f}ms")
    print(f"    Max: {stats['interval_max_ms']:.2f}ms")

    # Verdict
    accuracy = stats["fps_accuracy_percent"]
    jitter = stats["interval_std_ms"]

    if accuracy >= 95 and jitter < 5:
        verdict = "EXCELLENT - accurate fps with low jitter"
    elif accuracy >= 90:
        verdict = "ACCEPTABLE - fps within 10% of requested"
    elif accuracy >= 80:
        verdict = "MARGINAL - consider lower fps or resolution"
    else:
        verdict = "POOR - significant frame drops or delivery issues"

    print(f"\n  Verdict: {verdict}")


def run_framerate_tests(device: str) -> list[dict]:
    """Test multiple framerates and collect statistics."""
    results = []

    # Test common framerates at a resolution likely to work
    test_fps = [30, 15, 10]

    print(f"\nTesting framerates on {device}...")
    print("=" * 60)

    for fps in test_fps:
        print(f"\n[{fps} fps requested]")
        try:
            stats = measure_framerate(device, fps)
            print_results(stats)
            results.append(stats)
        except Exception as e:
            print(f"  Error: {e}")
            results.append({"requested_fps": fps, "error": str(e)})

    return results


def test_high_fps_degradation(device: str) -> None:
    """
    Test what happens when we request fps higher than USB bandwidth allows.

    At higher resolutions, USB bandwidth may limit achievable fps.
    """
    print("\n" + "=" * 60)
    print("Testing high-resolution fps limits...")
    print("=" * 60)

    test_cases = [
        ("640x480", 30),
        ("1280x720", 30),
        ("1920x1080", 30),
    ]

    for resolution, fps in test_cases:
        print(f"\n[{resolution} @ {fps}fps requested]")
        try:
            stats = measure_framerate(device, fps, duration_seconds=3.0, resolution=resolution)
            accuracy = stats["fps_accuracy_percent"]
            status = "OK" if accuracy >= 90 else "DEGRADED" if accuracy >= 50 else "POOR"
            print(f"  Actual: {stats['actual_fps']:.1f}fps ({accuracy:.1f}%) - {status}")
        except Exception as e:
            error_short = str(e)[:60]
            print(f"  Error: {error_short}")


def main():
    device = sys.argv[1] if len(sys.argv) > 1 else "/dev/video0"

    print("=" * 70)
    print("PyAV Exploration - Script 07: Set Framerate")
    print("=" * 70)
    print(f"\nDevice: {device}")
    print("Note: Using 640x480 for fps tests (more reliable delivery)")

    # Run basic framerate tests
    results = run_framerate_tests(device)

    # Test resolution/fps interaction
    test_high_fps_degradation(device)

    # Summary
    print("\n" + "=" * 70)
    print("Summary:")
    print("=" * 70)

    for stats in results:
        if "error" in stats:
            print(f"  {stats['requested_fps']}fps: ERROR")
        else:
            accuracy = stats["fps_accuracy_percent"]
            jitter = stats["interval_std_ms"]
            print(f"  {stats['requested_fps']}fps: actual={stats['actual_fps']:.1f}fps ({accuracy:.0f}%), jitter={jitter:.1f}ms")

    print("\n" + "=" * 70)
    print("Key Findings:")
    print("=" * 70)
    print("""
USB camera fps behavior:

1. Requested vs Actual:
   - USB cameras may deliver slightly fewer frames than requested
   - 95%+ accuracy is normal; below 90% indicates bandwidth issues

2. Jitter (frame interval variation):
   - USB cameras are NOT real-time devices
   - Expect 2-10ms jitter even at low resolutions
   - High jitter + low fps = USB bandwidth saturation

3. Resolution/FPS tradeoff:
   - Higher resolution = more USB bandwidth = fewer fps achievable
   - YUYV at 1080p may only achieve 5fps
   - MJPEG allows higher res at higher fps (compressed)

4. For temporal alignment (multi-camera):
   - Jitter means frames won't be perfectly synchronized
   - Use wall-clock timestamps, not frame counts
   - Expect 10-50ms alignment error between cameras
""")


if __name__ == "__main__":
    main()
