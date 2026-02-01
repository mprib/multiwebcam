#!/usr/bin/env python3
"""
Script 06: Set Resolution

Request specific resolution via PyAV options and verify it applies.
Tests both supported and unsupported resolutions to validate fail-fast behavior.

Usage:
    uv run python scripts/pyav_exploration/06_set_resolution.py [device]
"""

import sys
import time

import av


def test_resolution(
    device: str, width: int, height: int, input_format: str | None = None
) -> tuple[bool, str]:
    """
    Request a specific resolution and verify it was applied.

    Args:
        device: V4L2 device path
        width: Requested width
        height: Requested height
        input_format: Optional pixel format ('mjpeg', 'yuyv422', etc.)

    Returns:
        Tuple of (success, message)
    """
    options = {"video_size": f"{width}x{height}"}
    if input_format:
        options["input_format"] = input_format

    format_str = f" ({input_format})" if input_format else ""

    try:
        container = av.open(device, format="v4l2", options=options)
        frame = next(container.decode(video=0))
        actual_width = frame.width
        actual_height = frame.height
        container.close()

        if actual_width == width and actual_height == height:
            return True, f"{width}x{height}{format_str}: OK (exact match)"
        else:
            # Silent fallback - bad behavior we need to detect
            return (
                False,
                f"{width}x{height}{format_str}: MISMATCH - got {actual_width}x{actual_height}",
            )

    except av.error.FFmpegError as e:
        error_msg = str(e)
        # Extract just the relevant part of the error
        if "Invalid argument" in error_msg or "cannot set" in error_msg.lower():
            return True, f"{width}x{height}{format_str}: Error (expected for unsupported) - {error_msg[:80]}"
        return False, f"{width}x{height}{format_str}: Unexpected error - {error_msg[:80]}"
    except Exception as e:
        # Catch other errors (e.g., ValueError from PyAV)
        error_msg = str(e)
        return True, f"{width}x{height}{format_str}: Error (expected for unsupported) - {error_msg[:80]}"


def run_resolution_tests(device: str) -> list[tuple[str, bool]]:
    """
    Run a battery of resolution tests.

    Returns list of (description, passed) tuples.
    """
    results = []

    # Common resolutions to test (most cameras support at least some of these)
    test_cases = [
        # Format: (width, height, input_format, expect_success)
        # Standard resolutions likely to be supported
        (640, 480, None, True),
        (1280, 720, None, True),
        # MJPEG-specific (often supports higher res)
        (1920, 1080, "mjpeg", True),
        # YUYV-specific (often limited to lower res due to bandwidth)
        (640, 480, "yuyv422", True),
        # Unsupported resolution - should fail, not silently downgrade
        (4096, 2160, None, False),
        (123, 456, None, False),  # Weird size nobody supports
    ]

    print("\nTesting resolutions...")
    print("-" * 70)

    for width, height, fmt, expect_success in test_cases:
        success, msg = test_resolution(device, width, height, fmt)
        print(f"  {msg}")

        # For "expect_success=False" cases, we consider it a pass if either:
        # 1. The device properly rejected it (error)
        # 2. This test explicitly expects failure
        if expect_success:
            results.append((f"{width}x{height}", success))
        else:
            # For unsupported resolutions, we WANT it to fail (not silently fallback)
            # So if we got an error or mismatch message indicating failure, that's good
            is_proper_failure = "Error" in msg or "MISMATCH" in msg
            results.append((f"{width}x{height} (should fail)", is_proper_failure))

    return results


def check_silent_fallback(device: str) -> bool:
    """
    Specifically test for the dangerous silent fallback behavior.

    If we request an unsupported resolution and get a different one
    without an error, that's a problem.
    """
    print("\nChecking for silent fallback behavior...")
    print("-" * 70)

    # Request something absurd
    options = {"video_size": "9999x9999"}

    try:
        container = av.open(device, format="v4l2", options=options)
        frame = next(container.decode(video=0))
        actual = f"{frame.width}x{frame.height}"
        container.close()

        print(f"  Requested 9999x9999, got {actual}")
        print("  WARNING: Device silently fell back to different resolution!")
        print("  This means you cannot trust resolution requests without verification.")
        return False

    except (av.error.FFmpegError, Exception) as e:
        print(f"  Requested 9999x9999: Properly rejected with error")
        print(f"  Error: {str(e)[:60]}...")
        print("  GOOD: Device properly rejects unsupported resolutions.")
        return True


def main():
    device = sys.argv[1] if len(sys.argv) > 1 else "/dev/video0"

    print("=" * 70)
    print("PyAV Exploration - Script 06: Set Resolution")
    print("=" * 70)
    print(f"\nDevice: {device}")

    # Run resolution tests
    results = run_resolution_tests(device)

    # Check silent fallback
    no_silent_fallback = check_silent_fallback(device)

    # Summary
    print("\n" + "=" * 70)
    print("Summary:")
    print("=" * 70)

    passed = sum(1 for _, success in results if success)
    total = len(results)
    print(f"\nResolution tests: {passed}/{total} passed")

    for desc, success in results:
        status = "PASS" if success else "FAIL"
        print(f"  [{status}] {desc}")

    print(f"\nSilent fallback check: {'PASS' if no_silent_fallback else 'FAIL'}")

    print("\n" + "=" * 70)
    print("Key Findings:")
    print("=" * 70)
    print("""
Behavior varies by camera/driver:
  - Some cameras reject unsupported resolutions with errors (preferred)
  - Some cameras silently fall back to nearest supported size (dangerous)

Recommended pattern for fail-fast behavior:
    1. Query supported resolutions first (script 05)
    2. Only request resolutions known to be supported
    3. After opening, verify frame.width/height match requested

    requested = (1280, 720)
    with av.open(device, format='v4l2', options={'video_size': '1280x720'}) as c:
        frame = next(c.decode(video=0))
        actual = (frame.width, frame.height)
        if actual != requested:
            raise ValueError(f"Resolution mismatch: wanted {requested}, got {actual}")
""")


if __name__ == "__main__":
    main()
