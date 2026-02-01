#!/usr/bin/env python3
"""
Script 03: Frame to Numpy Conversion

Measure overhead of converting PyAV frames to numpy arrays.
Tests both native format and BGR24 conversion.

Usage:
    uv run python scripts/pyav_exploration/03_frame_to_numpy.py [device]
"""

import sys
from time import perf_counter
import av
import numpy as np


def benchmark_conversion(device: str, num_frames: int = 100):
    """Capture frames and time the numpy conversion."""

    print(f"\nBenchmarking {device} ({num_frames} frames)...")

    container = av.open(device, format='v4l2')
    stream = container.streams.video[0]

    print(f"Stream: {stream.width}x{stream.height}, native format will vary by frame")

    # Collect timing data
    native_times = []
    bgr_times = []

    for i, frame in enumerate(container.decode(video=0)):
        # Time native format conversion
        t0 = perf_counter()
        arr_native = frame.to_ndarray()
        native_times.append(perf_counter() - t0)

        # Time BGR24 conversion (what we'll use for OpenCV)
        t0 = perf_counter()
        arr_bgr = frame.to_ndarray(format='bgr24')
        bgr_times.append(perf_counter() - t0)

        if i == 0:
            print(f"\nFrame format: {frame.format.name}")
            print(f"Native array: shape={arr_native.shape}, dtype={arr_native.dtype}")
            print(f"BGR24 array:  shape={arr_bgr.shape}, dtype={arr_bgr.dtype}")
            print(f"C-contiguous: {arr_bgr.flags['C_CONTIGUOUS']}")

        if i >= num_frames - 1:
            break

    container.close()

    # Report results
    print(f"\n--- Results ({len(native_times)} frames) ---")
    print(f"Native conversion: avg={np.mean(native_times)*1000:.2f}ms, max={np.max(native_times)*1000:.2f}ms")
    print(f"BGR24 conversion:  avg={np.mean(bgr_times)*1000:.2f}ms, max={np.max(bgr_times)*1000:.2f}ms")

    overhead = np.mean(bgr_times) - np.mean(native_times)
    print(f"BGR24 overhead:    {overhead*1000:.2f}ms per frame")

    # Verdict
    avg_bgr = np.mean(bgr_times) * 1000
    if avg_bgr < 1.0:
        verdict = "EXCELLENT (<1ms)"
    elif avg_bgr < 5.0:
        verdict = "ACCEPTABLE (<5ms)"
    else:
        verdict = "SLOW (>5ms) - may bottleneck capture"

    print(f"\nVerdict: {verdict}")

    return {
        'native_avg': np.mean(native_times),
        'bgr_avg': np.mean(bgr_times),
        'bgr_max': np.max(bgr_times),
    }


def main():
    device = sys.argv[1] if len(sys.argv) > 1 else '/dev/video0'

    print("=" * 60)
    print("PyAV Exploration - Script 03: Frame to Numpy Conversion")
    print("=" * 60)

    benchmark_conversion(device)

    print("\n" + "=" * 60)


if __name__ == '__main__':
    main()
