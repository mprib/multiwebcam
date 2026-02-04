#!/usr/bin/env python3
"""
Test script for triple-queue architecture with alignment monitoring.

This script verifies:
1. ProducerQueues creation and usage
2. FrameProducer pushing to all three queues
3. AlignmentMonitor draining alignment queues
4. CaptureSession integration

Usage:
    uv run python scripts/pyav_exploration/test_triple_queue.py
"""

import time
from pathlib import Path

from multiwebcam.pipeline import AlignmentStats, CameraStats, CaptureSession
from multiwebcam.sources import FrameSource, FrameSourceConfig


def main():
    """Test the triple-queue architecture."""
    print("Testing Triple-Queue Architecture")
    print("=" * 60)

    # Find available cameras
    import subprocess

    result = subprocess.run(
        ["v4l2-ctl", "--list-devices"],
        capture_output=True,
        text=True,
    )

    devices = []
    for line in result.stdout.strip().split("\n"):
        line = line.strip()
        if line.startswith("/dev/video"):
            dev_num = int(line.replace("/dev/video", ""))
            if dev_num % 2 == 0:  # Skip metadata nodes
                devices.append(line)

    if len(devices) < 1:
        print("ERROR: Need at least 1 camera for testing")
        return

    print(f"\nFound cameras: {devices}")
    print(f"Using: {devices[:2]}")  # Use up to 2 cameras

    # Create sources
    config = FrameSourceConfig(
        resolution=(640, 480),
        fps=30,
        pixel_format="mjpeg",
        warmup_frames=5,
    )

    sources = [FrameSource(device, config=config) for device in devices[:2]]

    # Test 1: Queue Infrastructure
    print("\nTest 1: Creating CaptureSession with triple queues...")
    session = CaptureSession(
        sources,
        enable_monitoring=True,
        monitor_interval_seconds=2.0,
        recording_buffer_seconds=5.0,
        alignment_window_seconds=3.0,
    )

    print("  ✓ Session created")

    # Test 2: Start session (queues created, producers started, monitor started)
    print("\nTest 2: Starting session...")
    session.start()
    print("  ✓ Session started")
    print(f"  - Active devices: {session.active_device_paths}")

    # Test 3: Verify producers are pushing to all queues
    print("\nTest 3: Verifying producers push to all queues...")
    time.sleep(2.0)  # Let some frames accumulate

    for device_path, queues in session._producer_queues.items():
        display_size = queues.display.qsize()
        recording_size = queues.recording.qsize()
        alignment_size = queues.alignment.qsize()
        print(f"  {device_path}:")
        print(f"    Display queue: {display_size} (should be 1)")
        print(f"    Recording queue: {recording_size}")
        print(f"    Alignment queue: {alignment_size}")

    # Test 4: Get latest frames (display queue)
    print("\nTest 4: Getting latest frames...")
    frames = session.get_latest_frames()
    for device_path, packet in frames.items():
        if packet is not None:
            print(f"  {device_path}: frame {packet.frame_index}, time={packet.frame_time:.3f}s")
        else:
            print(f"  {device_path}: No frame yet")

    # Test 5: Wait for alignment monitor to collect data
    print("\nTest 5: Waiting for alignment monitor to collect data...")
    time.sleep(3.0)  # Let monitor build some clusters

    # Test 6: Get camera stats from AlignmentMonitor
    print("\nTest 6: Getting per-camera stats from AlignmentMonitor...")
    camera_stats = session.get_camera_stats()
    if camera_stats:
        for device_path, stats in camera_stats.items():
            print(f"  {device_path}:")
            print(f"    Frames in window: {stats.frames_in_window}")
            print(f"    Measured FPS: {stats.measured_fps:.2f}")
            print(f"    Jitter: {stats.jitter_ms:.2f}ms")
            print(f"    Queue depth: {stats.queue_depth}")
    else:
        print("  No stats available yet")

    # Test 7: Get alignment stats (if multiple cameras)
    if len(sources) > 1:
        print("\nTest 7: Getting alignment quality stats...")
        alignment_stats = session.get_alignment_stats()
        if alignment_stats:
            print(f"  Total clusters: {alignment_stats.total_clusters}")
            print(f"  Complete clusters: {alignment_stats.complete_cluster_pct:.1f}%")
            print(f"  Mean spread: {alignment_stats.mean_spread_ms:.2f}ms")
            print(f"  Max spread: {alignment_stats.max_spread_ms:.2f}ms")
            print(f"  Mean window duration: {alignment_stats.mean_window_duration_ms:.2f}ms")
        else:
            print("  No alignment stats available yet")
    else:
        print("\nTest 7: Skipped (need 2+ cameras for alignment)")

    # Test 8: Stop session cleanly
    print("\nTest 8: Stopping session...")
    session.stop()
    print("  ✓ Session stopped")

    print("\n" + "=" * 60)
    print("All tests completed successfully!")


if __name__ == "__main__":
    main()
