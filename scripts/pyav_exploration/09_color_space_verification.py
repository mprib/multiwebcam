#!/usr/bin/env python3
"""
Script 09: Color Space Verification

Verify that PyAV BGR output matches OpenCV's expectations.
Compare PyAV captures to OpenCV captures of the same scene.

This validates the MJPEG color conversion fix (yuvj422p -> rgb24 -> BGR).

Usage:
    uv run python scripts/pyav_exploration/09_color_space_verification.py [device]
"""

import argparse
import sys
from pathlib import Path
from time import sleep

import av
import cv2
import numpy as np


def frame_to_bgr(frame) -> np.ndarray:
    """Convert PyAV frame to BGR numpy array."""
    if frame.format.name in ("yuvj422p", "yuvj420p"):
        rgb_frame = frame.reformat(format="rgb24")
        return cv2.cvtColor(rgb_frame.to_ndarray(), cv2.COLOR_RGB2BGR)
    else:
        return frame.to_ndarray(format="bgr24")


def capture_pyav(device: str, resolution: str = "640x480") -> np.ndarray:
    """Capture a single frame using PyAV."""
    options = {
        "input_format": "mjpeg",
        "video_size": resolution,
    }
    container = av.open(device, format="v4l2", options=options)

    # Skip first few frames (auto-exposure settling)
    for i, frame in enumerate(container.decode(video=0)):
        if i >= 10:
            result = frame_to_bgr(frame)
            break

    container.close()
    return result


def capture_opencv(device: str, resolution: str = "640x480") -> np.ndarray:
    """Capture a single frame using OpenCV."""
    width, height = map(int, resolution.split("x"))

    cap = cv2.VideoCapture(device)
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)

    # Skip first few frames (auto-exposure settling)
    for _ in range(10):
        cap.read()

    ret, frame = cap.read()
    cap.release()

    if not ret:
        raise RuntimeError(f"OpenCV failed to capture from {device}")

    return frame


def analyze_channel_ordering(img: np.ndarray, name: str) -> dict:
    """Analyze BGR channel statistics."""
    b, g, r = cv2.split(img)
    return {
        "name": name,
        "B_mean": float(np.mean(b)),
        "G_mean": float(np.mean(g)),
        "R_mean": float(np.mean(r)),
        "B_std": float(np.std(b)),
        "G_std": float(np.std(g)),
        "R_std": float(np.std(r)),
    }


def compare_images(pyav_img: np.ndarray, opencv_img: np.ndarray) -> dict:
    """Compare two images numerically."""
    # Absolute difference
    diff = cv2.absdiff(pyav_img, opencv_img)
    mean_diff = np.mean(diff)
    max_diff = np.max(diff)

    # Per-channel difference
    b_diff = np.mean(np.abs(pyav_img[:, :, 0].astype(float) - opencv_img[:, :, 0].astype(float)))
    g_diff = np.mean(np.abs(pyav_img[:, :, 1].astype(float) - opencv_img[:, :, 1].astype(float)))
    r_diff = np.mean(np.abs(pyav_img[:, :, 2].astype(float) - opencv_img[:, :, 2].astype(float)))

    return {
        "mean_abs_diff": mean_diff,
        "max_diff": max_diff,
        "B_diff": b_diff,
        "G_diff": g_diff,
        "R_diff": r_diff,
    }


def check_color_sanity(img: np.ndarray) -> dict:
    """Check for common color space errors."""
    b, g, r = cv2.split(img)

    # RGB/BGR swap detection: if a known-blue object appears red
    # We can't detect this without a reference, but we can check for
    # unusual channel distributions

    # Check if image looks "greenish" (YUV not converted)
    # YUV images have green channel much higher than R/B
    green_dominance = np.mean(g) / (np.mean(r) + np.mean(b) + 1e-6) * 2

    # Check for purple tint (common MJPEG conversion error)
    # Purple = high R, high B, low G
    purple_score = (np.mean(r) + np.mean(b)) / (np.mean(g) + 1e-6) / 2

    return {
        "green_dominance": green_dominance,
        "purple_score": purple_score,
        "likely_yuv_not_converted": green_dominance > 1.5,
        "likely_color_swap": purple_score > 1.5,
    }


def main():
    parser = argparse.ArgumentParser(description="Verify color space handling")
    parser.add_argument("device", nargs="?", default="/dev/video0", help="V4L2 device path")
    parser.add_argument("--resolution", default="640x480", help="Capture resolution")
    parser.add_argument("--save", action="store_true", help="Save comparison images")
    parser.add_argument("--no-display", action="store_true", help="Skip visual preview")
    args = parser.parse_args()

    print("=" * 70)
    print("PyAV Exploration - Script 09: Color Space Verification")
    print("=" * 70)
    print(f"\nDevice: {args.device}")
    print(f"Resolution: {args.resolution}")

    # Capture with PyAV
    print("\nCapturing with PyAV (MJPEG)...")
    pyav_img = capture_pyav(args.device, args.resolution)
    print(f"  Shape: {pyav_img.shape}, dtype: {pyav_img.dtype}")

    # Small delay to let camera settle
    sleep(0.5)

    # Capture with OpenCV
    print("\nCapturing with OpenCV...")
    try:
        opencv_img = capture_opencv(args.device, args.resolution)
        print(f"  Shape: {opencv_img.shape}, dtype: {opencv_img.dtype}")
        have_opencv = True
    except Exception as e:
        print(f"  OpenCV capture failed: {e}")
        print("  Continuing with PyAV-only analysis...")
        have_opencv = False

    # Analyze PyAV image
    print("\n" + "=" * 70)
    print("PyAV Channel Analysis")
    print("=" * 70)
    pyav_stats = analyze_channel_ordering(pyav_img, "PyAV")
    print(f"  B: mean={pyav_stats['B_mean']:.1f}, std={pyav_stats['B_std']:.1f}")
    print(f"  G: mean={pyav_stats['G_mean']:.1f}, std={pyav_stats['G_std']:.1f}")
    print(f"  R: mean={pyav_stats['R_mean']:.1f}, std={pyav_stats['R_std']:.1f}")

    # Color sanity check
    sanity = check_color_sanity(pyav_img)
    print(f"\n  Green dominance: {sanity['green_dominance']:.2f} (>1.5 = likely YUV issue)")
    print(f"  Purple score: {sanity['purple_score']:.2f} (>1.5 = likely color swap)")

    if sanity["likely_yuv_not_converted"]:
        print("\n  WARNING: Image may have unconverted YUV data (greenish tint)")
    elif sanity["likely_color_swap"]:
        print("\n  WARNING: Image may have RGB/BGR swap (purple tint)")
    else:
        print("\n  Color channels appear normal")

    # Compare with OpenCV if available
    if have_opencv:
        print("\n" + "=" * 70)
        print("OpenCV Channel Analysis")
        print("=" * 70)
        opencv_stats = analyze_channel_ordering(opencv_img, "OpenCV")
        print(f"  B: mean={opencv_stats['B_mean']:.1f}, std={opencv_stats['B_std']:.1f}")
        print(f"  G: mean={opencv_stats['G_mean']:.1f}, std={opencv_stats['G_std']:.1f}")
        print(f"  R: mean={opencv_stats['R_mean']:.1f}, std={opencv_stats['R_std']:.1f}")

        print("\n" + "=" * 70)
        print("Comparison")
        print("=" * 70)
        comparison = compare_images(pyav_img, opencv_img)
        print(f"  Mean absolute difference: {comparison['mean_abs_diff']:.2f}")
        print(f"  Max difference: {comparison['max_diff']}")
        print(f"  Per-channel diff: B={comparison['B_diff']:.2f}, "
              f"G={comparison['G_diff']:.2f}, R={comparison['R_diff']:.2f}")

        # Verdict
        print("\n" + "=" * 70)
        print("Verdict")
        print("=" * 70)

        # Images won't be identical due to:
        # - Different capture times (lighting/motion)
        # - Different decode paths
        # - Sensor noise
        # Accept if mean diff < 20 (out of 255)
        if comparison["mean_abs_diff"] < 20:
            print("  PASS: PyAV and OpenCV produce similar output")
            print(f"  Mean difference ({comparison['mean_abs_diff']:.1f}) is within tolerance (20)")
        else:
            print("  WARNING: Significant difference between PyAV and OpenCV")
            print(f"  Mean difference ({comparison['mean_abs_diff']:.1f}) exceeds tolerance (20)")
            print("  This may indicate color space issues OR scene changed between captures")

    # Save images if requested
    if args.save:
        output_dir = Path("/tmp")
        pyav_path = output_dir / "color_test_pyav.png"
        cv2.imwrite(str(pyav_path), pyav_img)
        print(f"\nSaved PyAV image: {pyav_path}")

        if have_opencv:
            opencv_path = output_dir / "color_test_opencv.png"
            cv2.imwrite(str(opencv_path), opencv_img)
            print(f"Saved OpenCV image: {opencv_path}")

            # Side-by-side comparison
            combined = np.hstack([pyav_img, opencv_img])
            combined_path = output_dir / "color_test_comparison.png"
            cv2.imwrite(str(combined_path), combined)
            print(f"Saved comparison: {combined_path}")

    # Interactive preview
    if not args.no_display:
        print("\n" + "=" * 70)
        print("Visual Inspection")
        print("=" * 70)
        print("Press any key to close the preview window...")

        if have_opencv:
            # Show side by side
            combined = np.hstack([pyav_img, opencv_img])
            # Add labels
            cv2.putText(combined, "PyAV", (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 0), 2)
            cv2.putText(combined, "OpenCV", (pyav_img.shape[1] + 10, 30),
                        cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 0), 2)
            cv2.imshow("Color Comparison: PyAV (left) vs OpenCV (right)", combined)
        else:
            cv2.imshow("PyAV Capture", pyav_img)

        cv2.waitKey(0)
        cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
