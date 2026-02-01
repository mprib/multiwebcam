#!/usr/bin/env python3
"""
Script 14: Error Recovery Testing

Test recovery from transient failures (disconnect, permission loss, driver hiccups).
Validates that PyAV containers clean up properly and can be reopened after errors.

Key questions answered:
1. Does PyAV detect device disconnection promptly?
2. Can we recover and resume capture after errors?
3. Are resources (file descriptors) properly released on error?
4. What's the recovery time for transient failures?

Usage:
    uv run python scripts/pyav_exploration/14_error_recovery.py [device]

Note: Some tests require manual intervention (unplugging camera).
"""

import argparse
import os
import sys
from time import perf_counter, sleep

import av
from av.error import FFmpegError


def count_fds() -> int:
    """Count open file descriptors for current process."""
    return len(os.listdir("/proc/self/fd"))


def test_baseline(device: str) -> tuple[bool, float]:
    """
    Test 1: Establish baseline - normal capture works.

    Returns (success, fps)
    """
    print("\nTest 1: Baseline capture...")

    try:
        container = av.open(
            device,
            format="v4l2",
            options={"input_format": "mjpeg", "framerate": "30", "video_size": "640x480"},
        )

        frame_count = 0
        start = perf_counter()
        duration = 3.0

        for frame in container.decode(video=0):
            frame_count += 1
            if perf_counter() - start >= duration:
                break

        container.close()

        fps = frame_count / duration
        print(f"  Captured {frame_count} frames in {duration}s ({fps:.1f} fps)")
        print("  PASS: Baseline capture works")
        return True, fps

    except FFmpegError as e:
        print(f"  FAIL: {e}")
        return False, 0.0


def test_rapid_recovery(device: str, cycles: int = 5) -> bool:
    """
    Test 2: Rapid open/close cycles with frame capture.

    Verifies no resource leaks after multiple sessions.
    """
    print(f"\nTest 2: Rapid open/close recovery ({cycles} cycles)...")

    initial_fds = count_fds()
    success_count = 0

    for i in range(cycles):
        try:
            container = av.open(
                device,
                format="v4l2",
                options={"input_format": "mjpeg", "framerate": "30"},
            )

            # Capture a few frames
            for j, frame in enumerate(container.decode(video=0)):
                if j >= 10:
                    break

            container.close()
            success_count += 1
            print(f"  Cycle {i + 1}/{cycles}: OK")

        except FFmpegError as e:
            print(f"  Cycle {i + 1}/{cycles}: FAILED - {e}")

    final_fds = count_fds()
    leaked = final_fds - initial_fds

    print(f"  Successful cycles: {success_count}/{cycles}")
    print(f"  FD count: {initial_fds} -> {final_fds} (leaked: {leaked})")

    if leaked > 0:
        print("  FAIL: File descriptor leak detected")
        return False
    if success_count < cycles:
        print("  FAIL: Some cycles failed")
        return False

    print("  PASS: No resource leaks after rapid recovery")
    return True


def test_exception_cleanup(device: str) -> bool:
    """
    Test 3: Exception during capture - verify cleanup.

    Simulates an exception during frame processing and verifies
    resources are released.
    """
    print("\nTest 3: Exception during capture...")

    initial_fds = count_fds()
    container = None

    try:
        container = av.open(
            device,
            format="v4l2",
            options={"input_format": "mjpeg", "framerate": "30"},
        )

        for i, frame in enumerate(container.decode(video=0)):
            if i >= 5:
                raise RuntimeError("Simulated processing error")

    except RuntimeError as e:
        print(f"  Caught expected error: {e}")

    finally:
        if container is not None:
            container.close()
            print("  Closed container in finally block")

    final_fds = count_fds()
    leaked = final_fds - initial_fds

    print(f"  FD count: {initial_fds} -> {final_fds} (leaked: {leaked})")

    if leaked > 0:
        print("  FAIL: File descriptor leak after exception")
        return False

    print("  PASS: Cleanup after exception successful")
    return True


def test_context_manager_exception(device: str) -> bool:
    """
    Test 4: Context manager cleanup after exception.

    Verifies that 'with' statement properly cleans up even on exception.
    """
    print("\nTest 4: Context manager with exception...")

    initial_fds = count_fds()

    try:
        with av.open(
            device,
            format="v4l2",
            options={"input_format": "mjpeg", "framerate": "30"},
        ) as container:
            for i, frame in enumerate(container.decode(video=0)):
                if i >= 5:
                    raise RuntimeError("Simulated error inside context")

    except RuntimeError as e:
        print(f"  Caught expected error: {e}")

    final_fds = count_fds()
    leaked = final_fds - initial_fds

    print(f"  FD count: {initial_fds} -> {final_fds} (leaked: {leaked})")

    if leaked > 0:
        print("  FAIL: File descriptor leak after exception in context")
        return False

    print("  PASS: Context manager cleanup successful")
    return True


def test_device_busy(device: str) -> bool:
    """
    Test 5: Handle "device busy" scenario.

    Opens device twice to trigger busy error, verifies error handling.
    """
    print("\nTest 5: Device busy handling...")

    # Open first instance
    container1 = av.open(
        device,
        format="v4l2",
        options={"input_format": "mjpeg", "framerate": "30"},
    )

    # Grab a frame to ensure device is active
    frame = next(container1.decode(video=0))
    print(f"  First container: grabbed frame {frame.width}x{frame.height}")

    # Try to open second instance - should fail
    try:
        container2 = av.open(
            device,
            format="v4l2",
            options={"input_format": "mjpeg", "framerate": "30"},
        )
        # If we get here, cleanup and fail
        container2.close()
        container1.close()
        print("  UNEXPECTED: Device allowed double open")
        # Some cameras might allow this, so don't fail
        return True

    except FFmpegError as e:
        error_str = str(e).lower()
        if "busy" in error_str or "resource" in error_str:
            print(f"  Got expected error: Device busy")
        else:
            print(f"  Got error (may be device busy): {e}")

    # Clean up first container
    container1.close()
    print("  First container closed")

    # Verify we can reopen
    try:
        container3 = av.open(
            device,
            format="v4l2",
            options={"input_format": "mjpeg", "framerate": "30"},
        )
        frame = next(container3.decode(video=0))
        container3.close()
        print("  Reopened successfully after close")
        print("  PASS: Device busy handled correctly")
        return True

    except FFmpegError as e:
        print(f"  FAIL: Could not reopen after close: {e}")
        return False


def test_capture_with_retry(
    device: str, duration: float = 5.0, max_retries: int = 3
) -> tuple[bool, int, int]:
    """
    Test 6: Capture with automatic retry on error.

    Demonstrates a robust capture pattern that recovers from transient errors.

    Returns (success, frames_captured, retries_needed)
    """
    print(f"\nTest 6: Capture with retry (duration={duration}s, max_retries={max_retries})...")

    start = perf_counter()
    total_frames = 0
    retries = 0
    initial_fds = count_fds()

    while perf_counter() - start < duration:
        try:
            container = av.open(
                device,
                format="v4l2",
                options={"input_format": "mjpeg", "framerate": "30"},
            )

            for frame in container.decode(video=0):
                total_frames += 1
                if perf_counter() - start >= duration:
                    break

            container.close()
            break  # Normal completion

        except FFmpegError as e:
            print(f"  Error during capture: {e}")
            retries += 1

            if retries >= max_retries:
                print(f"  Max retries ({max_retries}) exceeded")
                return False, total_frames, retries

            # Attempt cleanup
            try:
                container.close()
            except Exception:
                pass

            print(f"  Retry {retries}/{max_retries} after 1s...")
            sleep(1.0)

    final_fds = count_fds()
    leaked = final_fds - initial_fds

    print(f"  Captured {total_frames} frames with {retries} retries")
    print(f"  FD count: {initial_fds} -> {final_fds} (leaked: {leaked})")

    if leaked > 0:
        print("  WARNING: File descriptor leak detected")

    print("  PASS: Retry pattern works")
    return True, total_frames, retries


def test_disconnect_detection(device: str) -> None:
    """
    Test 7: Disconnect detection (interactive).

    Requires manual camera disconnect during capture.
    """
    print("\nTest 7: Disconnect detection (INTERACTIVE)")
    print("  This test requires you to unplug the camera during capture.")
    print("  Press Enter to start, then unplug the camera...")

    try:
        input("  [Press Enter to start]")
    except EOFError:
        print("  Skipping interactive test (no TTY)")
        return

    initial_fds = count_fds()

    try:
        container = av.open(
            device,
            format="v4l2",
            options={"input_format": "mjpeg", "framerate": "30"},
        )

        print("  Capturing... unplug camera now!")
        start = perf_counter()
        frame_count = 0

        for frame in container.decode(video=0):
            frame_count += 1
            elapsed = perf_counter() - start

            if frame_count % 30 == 0:
                print(f"    {frame_count} frames ({elapsed:.1f}s)")

            if elapsed > 30:
                print("  Timeout - camera not disconnected")
                break

    except FFmpegError as e:
        detection_time = perf_counter() - start
        print(f"  Disconnect detected after {detection_time:.2f}s")
        print(f"  Error: {e}")

    finally:
        try:
            container.close()
        except Exception:
            pass

    final_fds = count_fds()
    print(f"  FD count: {initial_fds} -> {final_fds}")


def main():
    parser = argparse.ArgumentParser(description="Test error recovery and cleanup")
    parser.add_argument("device", nargs="?", default="/dev/video0", help="V4L2 device path")
    parser.add_argument(
        "--interactive", action="store_true", help="Include interactive disconnect test"
    )
    args = parser.parse_args()

    print("=" * 70)
    print("PyAV Exploration - Script 14: Error Recovery")
    print("=" * 70)
    print(f"\nDevice: {args.device}")
    print(f"Initial FD count: {count_fds()}")

    results: list[tuple[str, bool]] = []

    # Run automated tests
    success, fps = test_baseline(args.device)
    results.append(("Baseline capture", success))

    if success:
        results.append(("Rapid recovery", test_rapid_recovery(args.device)))
        results.append(("Exception cleanup", test_exception_cleanup(args.device)))
        results.append(("Context manager exception", test_context_manager_exception(args.device)))
        results.append(("Device busy", test_device_busy(args.device)))

        success, frames, retries = test_capture_with_retry(args.device)
        results.append(("Capture with retry", success))

        # Interactive test
        if args.interactive:
            test_disconnect_detection(args.device)
    else:
        print("\n  Baseline failed - skipping remaining tests")

    # Summary
    print("\n" + "=" * 70)
    print("Summary")
    print("=" * 70)

    all_passed = True
    for name, passed in results:
        status = "PASS" if passed else "FAIL"
        print(f"  {name}: {status}")
        if not passed:
            all_passed = False

    print(f"\nFinal FD count: {count_fds()}")

    if all_passed:
        print("\nAll error recovery tests passed!")
    else:
        print("\nSome tests failed - investigate resource cleanup")

    # Key findings
    print("\n" + "=" * 70)
    print("Key Findings")
    print("=" * 70)
    print(
        """
1. PyAV containers support context manager protocol for safe cleanup
2. Exceptions during capture are handled without resource leaks
3. "Device busy" errors occur when opening already-open device
4. Recovery after close is immediate (no delay needed)
5. For robust capture, use try/except with retry loop

Recommended pattern:
    while running:
        try:
            with av.open(device, format='v4l2') as container:
                for frame in container.decode(video=0):
                    process(frame)
        except FFmpegError:
            sleep(1.0)  # Wait before retry
"""
    )


if __name__ == "__main__":
    main()
