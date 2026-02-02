#!/usr/bin/env python3
"""
Exploration Script 18: Configuration Verification

PURPOSE:
Verify that requested configuration actually takes effect when opening a device.

BACKGROUND:
Some cameras silently fall back to different settings if requested config isn't
supported. We need to detect this and fail fast rather than proceeding with
unexpected settings.

APPROACH:
1. Open device with PyAV using requested config
2. Decode one frame
3. Check actual frame dimensions match requested
4. Report any mismatches

This supports the "fail-fast configuration" principle from CLAUDE.md.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass

import av
from av.error import FFmpegError


@dataclass
class ConfigVerification:
    """Result of configuration verification."""

    device_path: str
    requested_resolution: tuple[int, int]
    actual_resolution: tuple[int, int]
    requested_fps: int
    pixel_format: str
    resolution_matches: bool
    error: str | None = None

    def __str__(self) -> str:
        if self.error:
            return f"ERROR: {self.error}"

        status = "OK" if self.resolution_matches else "MISMATCH"
        req = f"{self.requested_resolution[0]}x{self.requested_resolution[1]}"
        actual = f"{self.actual_resolution[0]}x{self.actual_resolution[1]}"

        if self.resolution_matches:
            return f"[{status}] {req} @ {self.requested_fps}fps - Verified"
        else:
            return f"[{status}] Requested {req}, got {actual}"


def verify_config(
    device_path: str,
    width: int,
    height: int,
    fps: int = 30,
    pixel_format: str = "mjpeg",
) -> ConfigVerification:
    """
    Verify that requested configuration takes effect.

    Opens device, decodes one frame, checks dimensions.

    Returns ConfigVerification with result details.
    """
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

        # Decode one frame to verify actual dimensions
        stream = container.streams.video[0]

        for frame in container.decode(video=0):
            actual_width = frame.width
            actual_height = frame.height

            container.close()

            requested = (width, height)
            actual = (actual_width, actual_height)
            matches = requested == actual

            return ConfigVerification(
                device_path=device_path,
                requested_resolution=requested,
                actual_resolution=actual,
                requested_fps=fps,
                pixel_format=pixel_format,
                resolution_matches=matches,
            )

        container.close()
        return ConfigVerification(
            device_path=device_path,
            requested_resolution=(width, height),
            actual_resolution=(0, 0),
            requested_fps=fps,
            pixel_format=pixel_format,
            resolution_matches=False,
            error="No frames decoded",
        )

    except FFmpegError as e:
        return ConfigVerification(
            device_path=device_path,
            requested_resolution=(width, height),
            actual_resolution=(0, 0),
            requested_fps=fps,
            pixel_format=pixel_format,
            resolution_matches=False,
            error=str(e),
        )
    except Exception as e:
        return ConfigVerification(
            device_path=device_path,
            requested_resolution=(width, height),
            actual_resolution=(0, 0),
            requested_fps=fps,
            pixel_format=pixel_format,
            resolution_matches=False,
            error=f"Unexpected error: {e}",
        )


def test_common_configs(device_path: str) -> list[ConfigVerification]:
    """Test common resolution/fps configurations."""
    configs = [
        # Common 16:9 resolutions
        (1920, 1080, 30, "mjpeg"),
        (1280, 720, 30, "mjpeg"),
        (640, 480, 30, "mjpeg"),
        (640, 360, 30, "mjpeg"),
        # Higher fps
        (1280, 720, 60, "mjpeg"),
        (640, 480, 60, "mjpeg"),
        # YUYV (uncompressed)
        (640, 480, 30, "yuyv422"),
    ]

    results = []
    for width, height, fps, fmt in configs:
        print(f"Testing {width}x{height} @ {fps}fps ({fmt})...", end=" ", flush=True)
        result = verify_config(device_path, width, height, fps, fmt)
        print(result)
        results.append(result)

    return results


def main():
    print("=" * 70)
    print("V4L2 Configuration Verification")
    print("=" * 70)
    print()

    # Use provided device or default
    if len(sys.argv) > 1:
        device_path = sys.argv[1]
    else:
        device_path = "/dev/video0"

    print(f"Device: {device_path}")
    print()

    print("Testing common configurations:\n")
    results = test_common_configs(device_path)

    # Summary
    print()
    print("-" * 70)
    ok = sum(1 for r in results if r.resolution_matches)
    total = len(results)
    print(f"\nSummary: {ok}/{total} configurations verified")

    # Show failures
    failures = [r for r in results if not r.resolution_matches and not r.error]
    if failures:
        print("\nResolution mismatches (camera fell back to different settings):")
        for f in failures:
            print(f"  {f}")

    errors = [r for r in results if r.error]
    if errors:
        print("\nConfigurations that failed to open:")
        for e in errors:
            print(f"  {e.requested_resolution[0]}x{e.requested_resolution[1]}: {e.error}")


if __name__ == "__main__":
    main()
