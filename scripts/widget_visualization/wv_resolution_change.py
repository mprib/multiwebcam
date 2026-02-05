"""Debug script to test CaptureSession.replace_source() for resolution changes.

Tests changing resolution on a real camera using only valid configs from device discovery.
Works at the pipeline layer (no Qt UI).

Usage:
    python scripts/widget_visualization/wv_resolution_change.py
"""

import logging
import sys
import time
import traceback
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from multiwebcam.pipeline.session import CaptureSession
from multiwebcam.sources import (
    FrameSource,
    FrameSourceConfig,
    discover_frame_sources,
)

# Enable logging to see pipeline details
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)

logger = logging.getLogger(__name__)


def main() -> None:
    print("=" * 60)
    print("RESOLUTION CHANGE TEST")
    print("=" * 60)
    print()

    # Step 1: Discover cameras
    print("Step 1: Discovering cameras...")
    options_list = discover_frame_sources()

    if not options_list:
        print("  No cameras found. Exiting.")
        return

    print(f"  Found {len(options_list)} camera(s)")
    print()

    # Step 2: Pick first camera
    options = options_list[0]
    device_path = options.path
    print("Step 2: Selected camera")
    print(f"  Model: {options.model}")
    print(f"  Path: {device_path}")
    print(f"  Bus info: {options.bus_info}")
    print()

    # Step 3: Get MJPEG resolutions
    print("Step 3: Querying MJPEG resolutions...")
    mjpeg_resolutions = options.resolutions("mjpeg")

    if not mjpeg_resolutions:
        print("  No MJPEG resolutions available. Exiting.")
        return

    print(f"  Found {len(mjpeg_resolutions)} MJPEG resolution(s):")
    for res in sorted(mjpeg_resolutions, key=lambda r: r[0] * r[1]):
        print(f"    {res[0]}x{res[1]}")
    print()

    # Step 4: Pick two different resolutions
    if len(mjpeg_resolutions) < 2:
        print("  Need at least 2 MJPEG resolutions to test. Exiting.")
        return

    # Sort by pixel count
    sorted_resolutions = sorted(mjpeg_resolutions, key=lambda r: r[0] * r[1])
    res_1 = sorted_resolutions[0]  # Smallest
    res_2 = sorted_resolutions[-1]  # Largest

    # If they're the same (edge case), pick first two distinct ones
    if res_1 == res_2 and len(sorted_resolutions) >= 2:
        res_1 = sorted_resolutions[0]
        res_2 = sorted_resolutions[1]

    print("Step 4: Selected resolutions for test")
    print(f"  Resolution 1: {res_1[0]}x{res_1[1]} (smallest)")
    print(f"  Resolution 2: {res_2[0]}x{res_2[1]} (largest)")
    print()

    # Step 5: Build configs with valid fps
    print("Step 5: Building configs...")

    fps_1_options = options.framerates("mjpeg", res_1[0], res_1[1])
    if not fps_1_options:
        print(f"  No framerates available for {res_1[0]}x{res_1[1]}. Exiting.")
        return
    fps_1 = fps_1_options[0]  # Pick first available

    fps_2_options = options.framerates("mjpeg", res_2[0], res_2[1])
    if not fps_2_options:
        print(f"  No framerates available for {res_2[0]}x{res_2[1]}. Exiting.")
        return
    fps_2 = fps_2_options[0]  # Pick first available

    config_1 = FrameSourceConfig(
        resolution=res_1,
        fps=int(fps_1),
        pixel_format="mjpeg",
    )

    config_2 = FrameSourceConfig(
        resolution=res_2,
        fps=int(fps_2),
        pixel_format="mjpeg",
    )

    print(f"  Config 1: {config_1.resolution[0]}x{config_1.resolution[1]} @ {config_1.fps}fps")
    print(f"  Config 2: {config_2.resolution[0]}x{config_2.resolution[1]} @ {config_2.fps}fps")
    print()

    # Step 6: Create session with first config
    print("Step 6: Creating CaptureSession with config 1...")
    source = FrameSource(device_path, config_1)
    session = CaptureSession([source])
    print("  Session created")
    print()

    # Step 7: Start session and poll frames
    print("Step 7: Starting session...")
    session.start()
    print("  Session started")
    print()

    print("Step 8: Polling frames with config 1 (5 attempts)...")
    frames_received = 0
    for i in range(5):
        time.sleep(0.5)
        frames = session.get_latest_frames()
        packet = frames.get(device_path)
        if packet:
            frames_received += 1
            print(
                f"  [{i+1}/5] Frame received: "
                f"shape={packet.frame.shape}, "
                f"fps={packet.fps:.1f}, "
                f"index={packet.frame_index}"
            )
        else:
            print(f"  [{i+1}/5] No frame yet")

    if frames_received == 0:
        print("  WARNING: No frames received with config 1. Test may fail.")
    print()

    # Step 9: Replace source with config 2
    print("Step 9: Calling replace_source() with config 2...")
    print(f"  Replacing {device_path}")
    print(f"  New config: {config_2.resolution[0]}x{config_2.resolution[1]} @ {config_2.fps}fps")

    try:
        status = session.replace_source(device_path, config_2)
        print(f"  replace_source() returned: {status}")
        replace_success = True
    except Exception as e:
        print(f"  replace_source() FAILED with exception:")
        print()
        traceback.print_exc()
        print()
        replace_success = False

    if not replace_success:
        print("Step 10: Skipped (replace_source failed)")
        print()
        print("Step 11: Stopping session...")
        session.stop()
        print("  Session stopped")
        print()
        print("=" * 60)
        print("RESULT: FAIL - replace_source raised exception")
        print("=" * 60)
        return

    # Step 10: Poll frames with new config
    print()
    print("Step 10: Polling frames with config 2 (5 attempts)...")
    new_frames_received = 0
    new_resolution_verified = False

    for i in range(5):
        time.sleep(0.5)
        frames = session.get_latest_frames()
        packet = frames.get(device_path)
        if packet:
            new_frames_received += 1
            frame_h, frame_w = packet.frame.shape[:2]
            expected_w, expected_h = config_2.resolution

            if frame_w == expected_w and frame_h == expected_h:
                new_resolution_verified = True

            print(
                f"  [{i+1}/5] Frame received: "
                f"shape={packet.frame.shape}, "
                f"fps={packet.fps:.1f}, "
                f"index={packet.frame_index}"
            )
        else:
            print(f"  [{i+1}/5] No frame yet")

    print()

    # Step 11: Stop session
    print("Step 11: Stopping session...")
    session.stop()
    print("  Session stopped")
    print()

    # Step 12: Results
    print("=" * 60)
    if new_frames_received == 0:
        print("RESULT: FAIL - No frames received after replace_source")
    elif not new_resolution_verified:
        print("RESULT: FAIL - Frames received but resolution did not change")
        print(f"  Expected: {config_2.resolution[0]}x{config_2.resolution[1]}")
        print(f"  Got: {frame_w}x{frame_h}")  # type: ignore[possibly-undefined]
    else:
        print("RESULT: PASS - Resolution change successful")
        print(f"  Config 1: {config_1.resolution[0]}x{config_1.resolution[1]} @ {config_1.fps}fps")
        print(f"  Config 2: {config_2.resolution[0]}x{config_2.resolution[1]} @ {config_2.fps}fps")
        print(f"  Frames received with new config: {new_frames_received}/5")
    print("=" * 60)


if __name__ == "__main__":
    main()
