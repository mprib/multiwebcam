#!/usr/bin/env python3
"""
Script 13: Drop Detection via PTS Analysis

Detect dropped frames using PTS (presentation timestamp) gaps in the stream.
Complements script 12's wall-clock analysis with hardware timestamp analysis.

Key questions answered:
1. Does the camera/driver report dropped frames via PTS gaps?
2. Are PTS intervals consistent with expected framerate?
3. How do PTS-detected drops correlate with wall-clock gaps?

Usage:
    uv run python scripts/pyav_exploration/13_drop_detection.py [device] [--duration SECONDS]
"""

import argparse
from dataclasses import dataclass
from time import perf_counter

import av
import cv2
import numpy as np


@dataclass(frozen=True, slots=True)
class DropEvent:
    """Information about a detected drop."""

    frame_index: int
    pts_gap: int  # PTS units
    pts_gap_seconds: float
    expected_gap_seconds: float
    estimated_drops: int
    wall_gap_seconds: float


@dataclass(frozen=True, slots=True)
class DropAnalysis:
    """Summary of drop detection analysis."""

    total_frames: int
    duration_seconds: float
    pts_available: bool
    pts_time_base: str
    expected_pts_delta: float  # seconds
    drop_events: list[DropEvent]
    total_estimated_drops: int
    drop_rate_percent: float


def frame_to_bgr(frame) -> np.ndarray:
    """Convert PyAV frame to BGR numpy array."""
    if frame.format.name in ("yuvj422p", "yuvj420p"):
        rgb_frame = frame.reformat(format="rgb24")
        return cv2.cvtColor(rgb_frame.to_ndarray(), cv2.COLOR_RGB2BGR)
    else:
        return frame.to_ndarray(format="bgr24")


def detect_drops(
    device: str,
    duration_seconds: float = 60.0,
    target_fps: float = 30.0,
    resolution: str = "640x480",
) -> DropAnalysis:
    """
    Capture frames and detect drops via PTS analysis.

    Args:
        device: V4L2 device path
        duration_seconds: How long to capture
        target_fps: Expected framerate
        resolution: Capture resolution

    Returns:
        DropAnalysis with drop detection results
    """
    options = {
        "input_format": "mjpeg",
        "video_size": resolution,
        "framerate": str(int(target_fps)),
    }

    print(f"Opening {device}...")
    container = av.open(device, format="v4l2", options=options)
    stream = container.streams.video[0]
    time_base = stream.time_base

    print(f"Stream time_base: {time_base} ({float(time_base):.9f})")

    # Expected PTS delta per frame
    expected_delta_seconds = 1.0 / target_fps
    drop_threshold = expected_delta_seconds * 1.5  # 50% over expected

    pts_values: list[int | None] = []
    wall_times: list[float] = []
    drop_events: list[DropEvent] = []

    start_time = perf_counter()
    frame_index = 0

    print(f"\nCapturing for {duration_seconds}s...")

    for frame in container.decode(video=0):
        wall_time = perf_counter()

        pts_values.append(frame.pts)
        wall_times.append(wall_time)

        # Convert frame (prevents lazy decode issues)
        _ = frame_to_bgr(frame)

        # Check for drops (starting from frame 1)
        if frame_index > 0 and frame.pts is not None and pts_values[-2] is not None:
            prev_pts = pts_values[-2]
            pts_gap = frame.pts - prev_pts
            pts_gap_seconds = float(pts_gap * time_base)
            wall_gap_seconds = wall_times[-1] - wall_times[-2]

            if pts_gap_seconds > drop_threshold:
                estimated_drops = max(0, round(pts_gap_seconds / expected_delta_seconds) - 1)
                drop_events.append(
                    DropEvent(
                        frame_index=frame_index,
                        pts_gap=pts_gap,
                        pts_gap_seconds=pts_gap_seconds,
                        expected_gap_seconds=expected_delta_seconds,
                        estimated_drops=estimated_drops,
                        wall_gap_seconds=wall_gap_seconds,
                    )
                )

        frame_index += 1
        elapsed = wall_time - start_time

        # Progress every 100 frames
        if frame_index % 100 == 0:
            drops_so_far = len(drop_events)
            print(f"  Frame {frame_index}: {elapsed:.1f}s elapsed, {drops_so_far} drops detected")

        if elapsed >= duration_seconds:
            break

    container.close()
    final_time = perf_counter()

    # Check PTS availability
    pts_available = any(p is not None for p in pts_values)

    total_estimated_drops = sum(e.estimated_drops for e in drop_events)
    expected_frames = frame_index + total_estimated_drops
    drop_rate = total_estimated_drops / expected_frames * 100 if expected_frames > 0 else 0

    return DropAnalysis(
        total_frames=frame_index,
        duration_seconds=final_time - start_time,
        pts_available=pts_available,
        pts_time_base=str(time_base),
        expected_pts_delta=expected_delta_seconds,
        drop_events=drop_events[:50],  # First 50 only
        total_estimated_drops=total_estimated_drops,
        drop_rate_percent=drop_rate,
    )


def print_report(analysis: DropAnalysis, target_fps: float) -> None:
    """Print drop analysis report."""
    print("\n" + "=" * 70)
    print("Drop Detection Report")
    print("=" * 70)

    print(f"\nCapture Summary")
    print("-" * 40)
    print(f"  Frames captured: {analysis.total_frames}")
    print(f"  Duration: {analysis.duration_seconds:.2f}s")
    actual_fps = analysis.total_frames / analysis.duration_seconds
    print(f"  Actual FPS: {actual_fps:.2f} (target: {target_fps})")

    print(f"\nPTS Configuration")
    print("-" * 40)
    print(f"  PTS available: {'Yes' if analysis.pts_available else 'No'}")
    print(f"  Time base: {analysis.pts_time_base}")
    print(f"  Expected delta: {analysis.expected_pts_delta*1000:.2f}ms per frame")

    if not analysis.pts_available:
        print("\n  WARNING: PTS not available from this camera/driver")
        print("  Cannot detect drops via hardware timestamps")
        print("  Falling back to wall-clock analysis only")
        return

    print(f"\nDrop Detection")
    print("-" * 40)
    print(f"  Drop events: {len(analysis.drop_events)}")
    print(f"  Estimated frames dropped: {analysis.total_estimated_drops}")
    print(f"  Drop rate: {analysis.drop_rate_percent:.3f}%")

    if analysis.drop_events:
        print("\n  First 10 events:")
        print(f"  {'Frame':<8} {'PTS Gap':<12} {'Expected':<10} {'Drops':<6} {'Wall Gap':<10}")
        print("  " + "-" * 50)
        for event in analysis.drop_events[:10]:
            print(
                f"  {event.frame_index:<8} "
                f"{event.pts_gap_seconds*1000:>8.1f}ms   "
                f"{event.expected_gap_seconds*1000:>6.1f}ms   "
                f"{event.estimated_drops:<6} "
                f"{event.wall_gap_seconds*1000:>7.1f}ms"
            )

    # Correlation check
    if analysis.drop_events:
        pts_gaps = [e.pts_gap_seconds for e in analysis.drop_events]
        wall_gaps = [e.wall_gap_seconds for e in analysis.drop_events]
        if len(pts_gaps) > 1:
            correlation = np.corrcoef(pts_gaps, wall_gaps)[0, 1]
            print(f"\n  PTS vs Wall-Clock correlation: {correlation:.3f}")
            if correlation > 0.9:
                print("  -> Strong correlation: PTS and wall-clock agree on drops")
            elif correlation > 0.5:
                print("  -> Moderate correlation: some disagreement")
            else:
                print("  -> Weak correlation: timing sources disagree")

    # Verdict
    print("\n" + "=" * 70)
    print("Verdict")
    print("=" * 70)

    if analysis.drop_rate_percent < 0.1:
        print("EXCELLENT: Near-zero drop rate (<0.1%)")
    elif analysis.drop_rate_percent < 1.0:
        print("GOOD: Drop rate under 1%")
        print("  Acceptable for most applications")
    elif analysis.drop_rate_percent < 5.0:
        print("MARGINAL: Drop rate 1-5%")
        print("  May cause issues for motion-sensitive applications")
        print("  Consider: lower resolution, lower fps, or different USB port")
    else:
        print("POOR: Drop rate >5%")
        print("  USB bandwidth or system load issues likely")
        print("  Recommendations:")
        print("    - Check USB bus topology (lsusb -t)")
        print("    - Move camera to dedicated USB controller")
        print("    - Reduce resolution or framerate")
        print("    - Check system CPU load")


def main():
    parser = argparse.ArgumentParser(description="Detect dropped frames via PTS analysis")
    parser.add_argument("device", nargs="?", default="/dev/video0", help="V4L2 device path")
    parser.add_argument(
        "--duration", type=float, default=60.0, help="Capture duration in seconds (default: 60)"
    )
    parser.add_argument("--fps", type=float, default=30.0, help="Target framerate (default: 30)")
    parser.add_argument("--resolution", default="640x480", help="Capture resolution")
    args = parser.parse_args()

    print("=" * 70)
    print("PyAV Exploration - Script 13: Drop Detection")
    print("=" * 70)
    print(f"\nDevice: {args.device}")
    print(f"Duration: {args.duration}s")
    print(f"Target FPS: {args.fps}")
    print(f"Resolution: {args.resolution}")

    analysis = detect_drops(
        args.device,
        duration_seconds=args.duration,
        target_fps=args.fps,
        resolution=args.resolution,
    )

    print_report(analysis, args.fps)


if __name__ == "__main__":
    main()
