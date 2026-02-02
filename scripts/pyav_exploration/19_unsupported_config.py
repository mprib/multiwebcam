#!/usr/bin/env python3
"""
Exploration Script 19: Unsupported Configuration Behavior

PURPOSE:
Document what happens when we request unsupported resolution/fps combinations.

BACKGROUND:
Different cameras and drivers handle unsupported configs differently:
- Some silently fall back to nearest supported config
- Some return an error
- Some partially honor the request (e.g., right resolution, wrong fps)

Understanding this behavior is crucial for fail-fast configuration.

APPROACH:
1. Request definitely-unsupported configurations
2. Document the error/fallback behavior
3. Determine how to reliably detect config failures
"""

from __future__ import annotations

import sys
from dataclasses import dataclass

import av
from av.error import FFmpegError


@dataclass
class UnsupportedConfigTest:
    """Result of testing unsupported configuration."""

    description: str
    width: int
    height: int
    fps: int
    pixel_format: str
    behavior: str  # "error", "fallback", or "accepted"
    actual_resolution: tuple[int, int] | None = None
    error_message: str | None = None


def test_config(
    device_path: str,
    width: int,
    height: int,
    fps: int,
    pixel_format: str,
    description: str,
) -> UnsupportedConfigTest:
    """Test a configuration and document the behavior."""
    try:
        container = av.open(
            device_path,
            format="v4l2",
            options={
                "input_format": pixel_format,
                "video_size": f"{width}x{height}",
                "framerate": str(fps),
            },
        )

        # Try to decode a frame
        for frame in container.decode(video=0):
            actual = (frame.width, frame.height)
            container.close()

            requested = (width, height)
            if actual == requested:
                return UnsupportedConfigTest(
                    description=description,
                    width=width,
                    height=height,
                    fps=fps,
                    pixel_format=pixel_format,
                    behavior="accepted",
                    actual_resolution=actual,
                )
            else:
                return UnsupportedConfigTest(
                    description=description,
                    width=width,
                    height=height,
                    fps=fps,
                    pixel_format=pixel_format,
                    behavior="fallback",
                    actual_resolution=actual,
                )

        container.close()
        return UnsupportedConfigTest(
            description=description,
            width=width,
            height=height,
            fps=fps,
            pixel_format=pixel_format,
            behavior="error",
            error_message="No frames decoded",
        )

    except FFmpegError as e:
        return UnsupportedConfigTest(
            description=description,
            width=width,
            height=height,
            fps=fps,
            pixel_format=pixel_format,
            behavior="error",
            error_message=str(e),
        )
    except Exception as e:
        return UnsupportedConfigTest(
            description=description,
            width=width,
            height=height,
            fps=fps,
            pixel_format=pixel_format,
            behavior="error",
            error_message=f"Unexpected: {e}",
        )


def run_tests(device_path: str) -> list[UnsupportedConfigTest]:
    """Run tests for various unsupported configurations."""
    import time

    tests = [
        # Impossible resolutions
        ("8K resolution (way too high)", 7680, 4320, 30, "mjpeg"),
        ("Unusual resolution (prime numbers)", 1279, 719, 30, "mjpeg"),
        ("Very small resolution", 16, 16, 30, "mjpeg"),
        ("Zero dimensions", 0, 0, 30, "mjpeg"),
        # Impossible framerates
        ("Extremely high fps", 1280, 720, 1000, "mjpeg"),
        ("Zero fps", 1280, 720, 0, "mjpeg"),
        # Invalid pixel format
        ("Nonexistent pixel format", 1280, 720, 30, "rgb48be"),
        # YUYV at high resolution (usually bandwidth limited)
        ("YUYV at 1080p (bandwidth heavy)", 1920, 1080, 30, "yuyv422"),
    ]

    results = []
    for description, width, height, fps, fmt in tests:
        print(f"Testing: {description}...", flush=True)
        result = test_config(device_path, width, height, fps, fmt, description)
        results.append(result)
        # Small delay to let device reset between tests
        time.sleep(0.5)

        if result.behavior == "error":
            print(f"  -> ERROR: {result.error_message}")
        elif result.behavior == "fallback":
            actual = result.actual_resolution
            print(f"  -> FALLBACK: Got {actual[0]}x{actual[1]} instead")
        else:
            print(f"  -> ACCEPTED (unexpected!)")

    return results


def main():
    print("=" * 70)
    print("V4L2 Unsupported Configuration Behavior")
    print("=" * 70)
    print()

    # Use provided device or default
    if len(sys.argv) > 1:
        device_path = sys.argv[1]
    else:
        device_path = "/dev/video0"

    print(f"Device: {device_path}")
    print()
    print("Testing unsupported configurations to document driver behavior:\n")

    results = run_tests(device_path)

    # Summary
    print()
    print("=" * 70)
    print("Summary")
    print("=" * 70)

    errors = [r for r in results if r.behavior == "error"]
    fallbacks = [r for r in results if r.behavior == "fallback"]
    accepted = [r for r in results if r.behavior == "accepted"]

    print(f"\n  Errors (driver rejected): {len(errors)}")
    print(f"  Fallbacks (silently changed): {len(fallbacks)}")
    print(f"  Accepted (unexpected): {len(accepted)}")

    if fallbacks:
        print("\n  WARNING: Silent fallbacks detected!")
        print("  This means we MUST verify actual frame dimensions after opening.")
        print("  FrameSource already does this in _verify_resolution().")

    print()
    print("Recommendations:")
    print("  1. Always verify frame dimensions match request (already implemented)")
    print("  2. Query supported formats BEFORE attempting to open (script 17)")
    print("  3. Present only valid options to users (fail-fast at config time)")
    print()
    print("IMPORTANT FINDING:")
    print("  Errors during decode can leave the device in 'busy' state!")
    print("  Subsequent opens fail with EBUSY until device resets.")
    print("  This reinforces the need to validate configs BEFORE opening.")
    print()
    print("  Best practice:")
    print("    1. Query device capabilities (v4l2-ctl --list-formats-ext)")
    print("    2. Only offer supported options to user")
    print("    3. Never attempt to open with unsupported config")


if __name__ == "__main__":
    main()
