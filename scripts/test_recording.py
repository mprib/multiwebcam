"""Test script for multi-camera recording system."""

from __future__ import annotations

import csv
import logging
import time
from pathlib import Path

import av

from multiwebcam.pipeline.session import CaptureSession
from multiwebcam.sources.config import FrameSourceConfig
from multiwebcam.sources.device import FrameSource
from multiwebcam.sources.discovery import discover_frame_sources

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


def discover_cameras(max_cameras: int = 2) -> list[FrameSource]:
    """
    Discover available cameras and create FrameSource instances.

    Args:
        max_cameras: Maximum number of cameras to use (default 2)

    Returns:
        List of FrameSource instances
    """
    logger.info("Discovering cameras...")
    options_list = discover_frame_sources()

    if not options_list:
        logger.error("No cameras found!")
        return []

    logger.info(f"Found {len(options_list)} camera(s):")
    for opts in options_list:
        logger.info(f"  {opts.path}: {opts.model}")

    # Create sources with default config (720p30 MJPEG)
    sources = []
    for opts in options_list[:max_cameras]:
        config = opts.suggested_config()
        logger.info(f"Creating source for {opts.path}: {config.resolution[0]}x{config.resolution[1]}@{config.fps}fps")
        source = FrameSource(opts.path, config)
        sources.append(source)

    return sources


def validate_mp4_file(mp4_path: Path, expected_min_frames: int) -> tuple[bool, int, str]:
    """
    Validate an MP4 file exists and has frames.

    Args:
        mp4_path: Path to MP4 file
        expected_min_frames: Minimum expected frame count

    Returns:
        (is_valid, frame_count, error_message)
    """
    if not mp4_path.exists():
        return False, 0, f"File does not exist: {mp4_path}"

    try:
        container = av.open(str(mp4_path))
        stream = container.streams.video[0]

        # Count frames by decoding
        frame_count = 0
        for _ in container.decode(video=0):
            frame_count += 1

        container.close()

        if frame_count < expected_min_frames:
            return False, frame_count, f"Frame count {frame_count} < expected minimum {expected_min_frames}"

        return True, frame_count, ""

    except Exception as e:
        return False, 0, f"Failed to read MP4: {e}"


def validate_frametimes_csv(csv_path: Path, expected_frame_counts: dict[int, int]) -> tuple[bool, str]:
    """
    Validate frametimes.csv format and content.

    Args:
        csv_path: Path to frametimes.csv
        expected_frame_counts: Per-camera expected frame counts (cam_id -> count)

    Returns:
        (is_valid, error_message)
    """
    if not csv_path.exists():
        return False, f"File does not exist: {csv_path}"

    try:
        with open(csv_path, "r") as f:
            reader = csv.DictReader(f)

            # Validate header
            expected_columns = {"cam_id", "frame_index", "frame_time"}
            if set(reader.fieldnames or []) != expected_columns:
                return False, f"Invalid columns. Expected {expected_columns}, got {reader.fieldnames}"

            # Count rows per camera
            actual_counts: dict[int, int] = {}
            for row in reader:
                cam_id = int(row["cam_id"])
                actual_counts[cam_id] = actual_counts.get(cam_id, 0) + 1

                # Validate frame_time is a float
                try:
                    float(row["frame_time"])
                except ValueError:
                    return False, f"Invalid frame_time: {row['frame_time']}"

            # Check frame counts match expectations
            for cam_id, expected_count in expected_frame_counts.items():
                actual_count = actual_counts.get(cam_id, 0)
                # Allow small margin for timing differences
                if abs(actual_count - expected_count) > 2:
                    return (
                        False,
                        f"cam_{cam_id}: frame count mismatch (expected ~{expected_count}, got {actual_count})",
                    )

        return True, ""

    except Exception as e:
        return False, f"Failed to read CSV: {e}"


def run_test(recording_duration: float = 5.0) -> None:
    """
    Test the recording system.

    Args:
        recording_duration: How long to record in seconds
    """
    logger.info("=" * 60)
    logger.info("Multi-Camera Recording Test")
    logger.info("=" * 60)

    # Discover cameras
    sources = discover_cameras(max_cameras=5)
    if not sources:
        logger.error("No cameras available for testing")
        return

    logger.info(f"Using {len(sources)} camera(s) for test")

    # Create output directory in ./tmp/ for inspection
    output_dir = Path("./tmp/recording")
    output_dir.mkdir(parents=True, exist_ok=True)
    logger.info(f"Output directory: {output_dir}")

    # Define cam_ids (extract from device path)
    cam_ids = {}
    for source in sources:
        # Extract device_id from path (e.g., /dev/video0 -> 0)
        try:
            device_id = int(source.device_path.split('video')[-1])
            cam_ids[source.device_path] = device_id
        except ValueError:
            # Fallback to enumeration if path doesn't match expected format
            cam_ids[source.device_path] = len(cam_ids)

    logger.info("\nCamera IDs:")
    for path, cam_id in cam_ids.items():
        logger.info(f"  {path} -> cam_{cam_id}")

    # Create capture session
    logger.info("\nStarting capture session...")
    with CaptureSession(sources, enable_monitoring=True) as session:
        logger.info("Session started, warming up for 1 second...")
        time.sleep(1.0)

        # Check if frames are being captured
        frames = session.get_latest_frames()
        active_cameras = sum(1 for packet in frames.values() if packet is not None)
        logger.info(f"Captured frames from {active_cameras}/{len(sources)} camera(s)")

        if active_cameras == 0:
            logger.error("No frames captured, aborting test")
            return

        # Start recording
        logger.info(f"\nStarting recording for {recording_duration}s...")
        session.start_recording(output_dir, cam_ids)

        # Record for specified duration
        start_time = time.perf_counter()
        while time.perf_counter() - start_time < recording_duration:
            time.sleep(0.5)

            # Show progress
            elapsed = time.perf_counter() - start_time
            logger.info(f"Recording... {elapsed:.1f}s / {recording_duration:.1f}s")

        # Stop recording
        logger.info("\nStopping recording...")
        result = session.stop_recording()

        if result is None:
            logger.error("stop_recording() returned None!")
            return

        # Display results
        logger.info("\n" + "=" * 60)
        logger.info("Recording Results")
        logger.info("=" * 60)
        logger.info(f"Output directory: {result.output_dir}")
        logger.info(f"Duration: {result.duration_seconds:.2f}s")
        logger.info(f"Frametimes CSV: {result.frametimes_path}")

        logger.info("\nFrames per camera:")
        total_frames = 0
        for cam_id, count in result.frames_per_camera.items():
            logger.info(f"  cam_{cam_id}: {count} frames")
            total_frames += count

        logger.info(f"\nTotal frames: {total_frames}")

        if result.errors:
            logger.warning(f"\nErrors encountered ({len(result.errors)}):")
            for error in result.errors:
                logger.warning(f"  {error}")

        # Validation
        logger.info("\n" + "=" * 60)
        logger.info("Validation")
        logger.info("=" * 60)

        all_valid = True

        # Calculate expected minimum frames (assume at least 20fps even if requested 30fps)
        expected_min_frames = int(recording_duration * 20)

        # Validate MP4 files
        for cam_id, expected_frame_count in result.frames_per_camera.items():
            mp4_path = result.output_dir / f"cam_{cam_id}.mp4"

            valid, actual_count, error = validate_mp4_file(mp4_path, expected_min_frames)
            if valid:
                logger.info(f"[OK] cam_{cam_id}.mp4: {actual_count} frames")
            else:
                logger.error(f"[FAIL] cam_{cam_id}.mp4: {error}")
                all_valid = False

        # Validate frametimes.csv
        valid, error = validate_frametimes_csv(result.frametimes_path, result.frames_per_camera)
        if valid:
            logger.info("[OK] frametimes.csv: format and counts valid")
        else:
            logger.error(f"[FAIL] frametimes.csv: {error}")
            all_valid = False

        # Final verdict
        logger.info("\n" + "=" * 60)
        if all_valid:
            logger.info("[OK] TEST PASSED")
        else:
            logger.error("[FAIL] TEST FAILED")
        logger.info("=" * 60)


if __name__ == "__main__":
    run_test(recording_duration=5.0)
