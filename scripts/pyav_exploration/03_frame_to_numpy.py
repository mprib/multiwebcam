#!/usr/bin/env python3
"""
Script 03: Frame to Numpy Conversion - MJPEG vs YUYV Comparison

Compare MJPEG and YUYV capture:
- Achievable resolution at 30fps
- Frame data size (bandwidth proxy)
- Decode/conversion time to BGR24

Usage:
    uv run python scripts/pyav_exploration/03_frame_to_numpy.py [device]
"""

import sys
from time import perf_counter

import av
import cv2
import numpy as np


def frame_to_bgr(frame) -> np.ndarray:
    """
    Convert PyAV frame to BGR numpy array.

    For MJPEG (yuvj422p): reformat to rgb24, then cvtColor to BGR.
    For YUYV: direct to_ndarray works.
    """
    if frame.format.name in ("yuvj422p", "yuvj420p"):
        # MJPEG path - reformat to rgb24 first (bgr24 is broken)
        rgb_frame = frame.reformat(format="rgb24")
        img_rgb = rgb_frame.to_ndarray()
        return cv2.cvtColor(img_rgb, cv2.COLOR_RGB2BGR)
    else:
        # Raw formats (YUYV, etc) - direct conversion works
        return frame.to_ndarray(format="bgr24")


def benchmark_format(
    device: str,
    input_format: str,
    resolution: str,
    num_frames: int = 50,
) -> dict | None:
    """
    Benchmark a specific format/resolution combination.

    Returns dict with timing and size stats, or None if format not supported.
    """
    options = {
        "input_format": input_format,
        "video_size": resolution,
    }

    try:
        container = av.open(device, format="v4l2", options=options)
    except av.error.FFmpegError:
        return None

    # Collect data
    bgr_times = []
    frame_sizes = []
    arr = None

    for i, packet in enumerate(container.demux(video=0)):
        if packet.size > 0:
            frame_sizes.append(packet.size)

        # Decode and convert
        for frame in packet.decode():
            t0 = perf_counter()
            arr = frame_to_bgr(frame)
            bgr_times.append(perf_counter() - t0)

            if len(bgr_times) >= num_frames:
                break

        if len(bgr_times) >= num_frames:
            break

    container.close()

    if not bgr_times or arr is None:
        return None

    return {
        "format": input_format,
        "resolution": resolution,
        "actual_res": f"{arr.shape[1]}x{arr.shape[0]}",
        "frame_size_kb": np.mean(frame_sizes) / 1024 if frame_sizes else 0,
        "bgr_time_ms": np.mean(bgr_times) * 1000,
        "bgr_time_max_ms": np.max(bgr_times) * 1000,
    }


def estimate_bandwidth(frame_size_kb: float, fps: int = 30) -> float:
    """Estimate bandwidth in Mbps for given frame size and fps."""
    return (frame_size_kb * 1024 * 8 * fps) / 1_000_000


def main():
    device = sys.argv[1] if len(sys.argv) > 1 else "/dev/video0"

    print("=" * 70)
    print("PyAV Exploration - Script 03: MJPEG vs YUYV Comparison")
    print("=" * 70)
    print(f"\nDevice: {device}")
    print("\nTesting formats (50 frames each)...")

    # Test configurations
    tests = [
        ("mjpeg", "1920x1080"),
        ("mjpeg", "1280x720"),
        ("mjpeg", "640x480"),
        ("yuyv422", "640x480"),
        ("yuyv422", "1280x720"),  # Likely to fail or be slow on USB 2.0
    ]

    results = []
    for fmt, res in tests:
        print(f"\n  Testing {fmt} @ {res}...", end=" ", flush=True)
        result = benchmark_format(device, fmt, res)
        if result:
            bw = estimate_bandwidth(result["frame_size_kb"])
            print(f"OK ({result['bgr_time_ms']:.1f}ms decode, {bw:.1f} Mbps)")
            result["bandwidth_mbps"] = bw
            results.append(result)
        else:
            print("FAILED (not supported or error)")

    # Summary table
    print("\n" + "=" * 70)
    print("Results Summary")
    print("=" * 70)
    print(f"\n{'Format':<10} {'Resolution':<12} {'Frame KB':<10} {'Bandwidth':<12} {'Decode ms':<10}")
    print("-" * 60)

    for r in results:
        print(
            f"{r['format']:<10} {r['actual_res']:<12} {r['frame_size_kb']:<10.1f} "
            f"{r['bandwidth_mbps']:<12.1f} {r['bgr_time_ms']:<10.2f}"
        )

    # Analysis
    print("\n" + "=" * 70)
    print("Analysis")
    print("=" * 70)

    mjpeg_1080 = next((r for r in results if r["format"] == "mjpeg" and "1920" in r["actual_res"]), None)
    yuyv_480 = next((r for r in results if r["format"] == "yuyv422" and "640" in r["actual_res"]), None)

    if mjpeg_1080 and yuyv_480:
        size_ratio = yuyv_480["frame_size_kb"] / mjpeg_1080["frame_size_kb"]
        pixel_ratio = (1920 * 1080) / (640 * 480)
        print(f"\nMJPEG 1080p vs YUYV 480p:")
        print(f"  Pixels: {pixel_ratio:.1f}x more with MJPEG")
        print(f"  Frame size: MJPEG is {1/size_ratio:.1f}x larger (but {pixel_ratio:.1f}x more pixels)")
        print(f"  Bandwidth: MJPEG {mjpeg_1080['bandwidth_mbps']:.1f} Mbps vs YUYV {yuyv_480['bandwidth_mbps']:.1f} Mbps")

    print("""
Key insight:
  MJPEG at 1080p uses LESS bandwidth than YUYV at 480p
  while delivering 6.75x more pixels.

  USB 2.0 limit: ~384 Mbps (isochronous)
  USB 3.0 limit: ~4000 Mbps

  MJPEG is the only practical choice for multi-camera 1080p on USB 2.0.
""")

    # Check for YUYV 720p failure
    yuyv_720 = next((r for r in results if r["format"] == "yuyv422" and "1280" in r["resolution"]), None)
    if yuyv_720 is None:
        print("  Note: YUYV 720p failed - this camera can't deliver raw 720p (bandwidth limit).")


if __name__ == "__main__":
    main()
