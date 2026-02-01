#!/usr/bin/env python3
"""
PyAV Exploration - Script 15: Multi-Camera Recording Test

THE BIG QUESTION: Can we capture from multiple cameras AND encode to disk
simultaneously without dropping frames or corrupting files?

This is the integration test that matters. If this works, the I/O layer is solid.

Usage:
    uv run python scripts/pyav_exploration/15_multicam_record_test.py
    uv run python scripts/pyav_exploration/15_multicam_record_test.py --duration 60
    uv run python scripts/pyav_exploration/15_multicam_record_test.py --devices /dev/video2 /dev/video4

Post-hoc analysis is printed at the end showing drops per camera.
"""

import argparse
import subprocess
import threading
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from queue import Queue, Empty
from time import perf_counter, sleep

import av
import cv2
import numpy as np
import pandas as pd

from multiwebcam.sources import DeviceSource, CaptureConfig, FramePacket


@dataclass
class RecordingStats:
    """Stats collected during recording."""
    device_id: int
    frames_captured: int
    frames_encoded: int
    drops_detected: int
    mean_fps: float
    file_size_mb: float


def get_available_cameras() -> list[str]:
    """Get list of available video devices (filtering metadata nodes)."""
    result = subprocess.run(
        ["v4l2-ctl", "--list-devices"],
        capture_output=True,
        text=True,
    )

    devices = []
    lines = result.stdout.strip().split("\n")
    for line in lines:
        line = line.strip()
        if line.startswith("/dev/video"):
            # Only take even-numbered devices (skip metadata nodes)
            dev_num = int(line.replace("/dev/video", ""))
            if dev_num % 2 == 0:
                devices.append(line)

    return devices


def capture_and_encode_worker(
    device_path: str,
    output_dir: Path,
    duration: float,
    timestamps: list[dict],
    timestamps_lock: threading.Lock,
    stop_event: threading.Event,
) -> RecordingStats:
    """
    Capture from one camera and encode to MP4.

    This runs in its own thread - one per camera.
    """
    device_id = int(device_path.replace("/dev/video", ""))
    output_video = output_dir / f"cam{device_id}.mp4"

    config = CaptureConfig(
        resolution=(1280, 720),
        fps=30,
        pixel_format="mjpeg",
        warmup_frames=5,
    )

    source = DeviceSource(device_path, config=config)

    # Open encoder
    output_container = av.open(str(output_video), mode="w")
    stream = output_container.add_stream("libx264", rate=30)
    stream.width = 1280
    stream.height = 720
    stream.pix_fmt = "yuv420p"
    stream.options = {"preset": "ultrafast", "crf": "23"}

    frames_captured = 0
    frames_encoded = 0
    start_time = perf_counter()
    last_pts = None
    drops = 0

    try:
        source.start()

        for packet in source:
            if stop_event.is_set() or (perf_counter() - start_time) >= duration:
                break

            frames_captured += 1

            # Record timestamp for post-hoc analysis
            with timestamps_lock:
                timestamps.append({
                    "port": device_id,
                    "frame_time": packet.frame_time,
                    "frame_index": packet.frame_index,
                    "wall_time": perf_counter(),
                })

            # Check for drops via PTS gap
            if last_pts is not None:
                delta = packet.frame_time - last_pts
                if delta > 0.040:  # >40ms gap at 30fps
                    drops += 1
            last_pts = packet.frame_time

            # Encode frame
            # Convert BGR to RGB, then to PyAV frame
            rgb = cv2.cvtColor(packet.frame, cv2.COLOR_BGR2RGB)
            av_frame = av.VideoFrame.from_ndarray(rgb, format="rgb24")
            av_frame = av_frame.reformat(format="yuv420p")

            for av_packet in stream.encode(av_frame):
                output_container.mux(av_packet)
            frames_encoded += 1

            # Progress indicator every 100 frames
            if frames_captured % 100 == 0:
                elapsed = perf_counter() - start_time
                fps = frames_captured / elapsed
                print(f"  {device_path}: {frames_captured} frames, {fps:.1f} fps")

    finally:
        source.stop()

        # Flush encoder
        for av_packet in stream.encode(None):
            output_container.mux(av_packet)
        output_container.close()

    elapsed = perf_counter() - start_time
    file_size = output_video.stat().st_size / (1024 * 1024)

    return RecordingStats(
        device_id=device_id,
        frames_captured=frames_captured,
        frames_encoded=frames_encoded,
        drops_detected=drops,
        mean_fps=frames_captured / elapsed,
        file_size_mb=file_size,
    )


def analyze_timestamps(df: pd.DataFrame) -> None:
    """Post-hoc analysis of captured timestamps."""
    print("\n" + "=" * 70)
    print("Post-Hoc Timestamp Analysis")
    print("=" * 70)

    for port in sorted(df["port"].unique()):
        port_df = df[df["port"] == port].sort_values("frame_time")

        # Check for gaps
        deltas = port_df["frame_time"].diff().dropna() * 1000  # to ms

        expected_delta = 33.33  # ms at 30fps
        large_gaps = (deltas > 40).sum()

        print(f"\nPort {port}:")
        print(f"  Frames: {len(port_df)}")
        print(f"  Duration: {port_df['frame_time'].max() - port_df['frame_time'].min():.2f}s")
        print(f"  Delta stats: mean={deltas.mean():.2f}ms, std={deltas.std():.2f}ms")
        print(f"  Delta range: [{deltas.min():.2f}, {deltas.max():.2f}]ms")
        print(f"  Large gaps (>40ms): {large_gaps}")

        # Check frame index continuity
        indices = port_df["frame_index"].values
        expected_indices = np.arange(indices[0], indices[0] + len(indices))
        index_gaps = np.sum(indices != expected_indices)
        if index_gaps > 0:
            print(f"  WARNING: {index_gaps} frame index discontinuities")


def main():
    parser = argparse.ArgumentParser(
        description="Test multi-camera capture + encoding simultaneously"
    )
    parser.add_argument(
        "--duration", type=float, default=30.0,
        help="Recording duration in seconds (default: 30)"
    )
    parser.add_argument(
        "--devices", nargs="+",
        help="Specific devices to use (default: auto-detect)"
    )
    parser.add_argument(
        "--output-dir", type=Path, default=Path("recordings"),
        help="Output directory for recordings (default: ./recordings)"
    )
    args = parser.parse_args()

    # Get devices
    if args.devices:
        devices = args.devices
    else:
        devices = get_available_cameras()
        # Skip laptop webcam (usually video0), limit to 4
        devices = [d for d in devices if d != "/dev/video0"][:4]

    if not devices:
        print("No cameras found!")
        return

    print("=" * 70)
    print("Multi-Camera Recording Test")
    print("=" * 70)
    print(f"\nDevices: {devices}")
    print(f"Duration: {args.duration}s")
    print(f"Output: {args.output_dir}")

    # Create output directory
    args.output_dir.mkdir(exist_ok=True)

    # Shared state
    timestamps: list[dict] = []
    timestamps_lock = threading.Lock()
    stop_event = threading.Event()

    # Launch threads
    print(f"\nStarting {len(devices)} camera threads...")
    threads: list[tuple[threading.Thread, str]] = []
    results: dict[str, RecordingStats] = {}

    def thread_target(device: str):
        stats = capture_and_encode_worker(
            device,
            args.output_dir,
            args.duration,
            timestamps,
            timestamps_lock,
            stop_event,
        )
        results[device] = stats

    for device in devices:
        t = threading.Thread(target=thread_target, args=(device,))
        t.start()
        threads.append((t, device))

    # Wait for completion
    try:
        for t, device in threads:
            t.join()
    except KeyboardInterrupt:
        print("\nStopping...")
        stop_event.set()
        for t, device in threads:
            t.join(timeout=5.0)

    # Save timestamps
    timestamps_file = args.output_dir / "frame_timestamps.csv"
    df = pd.DataFrame(timestamps)
    df.to_csv(timestamps_file, index=False)
    print(f"\nTimestamps saved to: {timestamps_file}")

    # Print results
    print("\n" + "=" * 70)
    print("Recording Results")
    print("=" * 70)

    total_frames = 0
    total_drops = 0

    for device in devices:
        if device in results:
            stats = results[device]
            total_frames += stats.frames_captured
            total_drops += stats.drops_detected

            print(f"\n{device} (cam{stats.device_id}):")
            print(f"  Frames: {stats.frames_captured} captured, {stats.frames_encoded} encoded")
            print(f"  FPS: {stats.mean_fps:.1f}")
            print(f"  Drops: {stats.drops_detected}")
            print(f"  File: {stats.file_size_mb:.1f} MB")

    # Overall summary
    print("\n" + "-" * 70)
    print(f"TOTAL: {total_frames} frames, {total_drops} drops ({100*total_drops/max(total_frames,1):.2f}%)")

    # Post-hoc analysis
    if not df.empty:
        analyze_timestamps(df)

    # Verdict
    print("\n" + "=" * 70)
    drop_rate = total_drops / max(total_frames, 1)
    if drop_rate < 0.01:
        print("VERDICT: SUCCESS - <1% frame drops")
    elif drop_rate < 0.05:
        print("VERDICT: ACCEPTABLE - <5% frame drops")
    else:
        print("VERDICT: PROBLEM - >5% frame drops, investigate I/O contention")
    print("=" * 70)


if __name__ == "__main__":
    main()
