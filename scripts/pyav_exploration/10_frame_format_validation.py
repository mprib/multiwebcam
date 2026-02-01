#!/usr/bin/env python3
"""
Script 10: Frame Format Validation

Verify numpy array format matches expectations:
- dtype: uint8
- shape: (height, width, 3)
- memory layout: C-contiguous
- value range: 0-255
- OpenCV compatibility

Usage:
    uv run python scripts/pyav_exploration/10_frame_format_validation.py [device]
"""

import argparse
import sys

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


def capture_frame(device: str, resolution: str = "640x480") -> np.ndarray:
    """Capture a single frame using PyAV."""
    options = {
        "input_format": "mjpeg",
        "video_size": resolution,
    }
    container = av.open(device, format="v4l2", options=options)

    for frame in container.decode(video=0):
        result = frame_to_bgr(frame)
        break

    container.close()
    return result


def validate_array_properties(arr: np.ndarray, expected_shape: tuple) -> dict:
    """Validate numpy array properties."""
    results = {}

    # dtype
    results["dtype"] = {
        "expected": "uint8",
        "actual": str(arr.dtype),
        "pass": arr.dtype == np.uint8,
    }

    # shape
    results["shape"] = {
        "expected": str(expected_shape),
        "actual": str(arr.shape),
        "pass": arr.shape == expected_shape,
    }

    # channels
    results["channels"] = {
        "expected": 3,
        "actual": arr.shape[2] if len(arr.shape) == 3 else 1,
        "pass": len(arr.shape) == 3 and arr.shape[2] == 3,
    }

    # C-contiguous (row-major, standard for OpenCV)
    results["c_contiguous"] = {
        "expected": True,
        "actual": arr.flags["C_CONTIGUOUS"],
        "pass": arr.flags["C_CONTIGUOUS"],
    }

    # Writeable (needed for in-place operations)
    results["writeable"] = {
        "expected": True,
        "actual": arr.flags["WRITEABLE"],
        "pass": arr.flags["WRITEABLE"],
    }

    # Value range
    results["value_range"] = {
        "expected": "[0, 255]",
        "actual": f"[{arr.min()}, {arr.max()}]",
        "pass": arr.min() >= 0 and arr.max() <= 255,
    }

    return results


def test_opencv_operations(arr: np.ndarray) -> dict:
    """Test compatibility with common OpenCV operations."""
    results = {}

    # cvtColor - convert to grayscale
    try:
        gray = cv2.cvtColor(arr, cv2.COLOR_BGR2GRAY)
        results["cvtColor_gray"] = {
            "pass": True,
            "output_shape": str(gray.shape),
        }
    except Exception as e:
        results["cvtColor_gray"] = {"pass": False, "error": str(e)}

    # cvtColor - convert to HSV
    try:
        hsv = cv2.cvtColor(arr, cv2.COLOR_BGR2HSV)
        results["cvtColor_hsv"] = {
            "pass": True,
            "output_shape": str(hsv.shape),
        }
    except Exception as e:
        results["cvtColor_hsv"] = {"pass": False, "error": str(e)}

    # resize
    try:
        resized = cv2.resize(arr, (320, 240))
        results["resize"] = {
            "pass": True,
            "output_shape": str(resized.shape),
        }
    except Exception as e:
        results["resize"] = {"pass": False, "error": str(e)}

    # GaussianBlur
    try:
        blurred = cv2.GaussianBlur(arr, (5, 5), 0)
        results["gaussian_blur"] = {
            "pass": True,
            "output_shape": str(blurred.shape),
        }
    except Exception as e:
        results["gaussian_blur"] = {"pass": False, "error": str(e)}

    # Canny edge detection
    try:
        gray = cv2.cvtColor(arr, cv2.COLOR_BGR2GRAY)
        edges = cv2.Canny(gray, 100, 200)
        results["canny"] = {
            "pass": True,
            "output_shape": str(edges.shape),
        }
    except Exception as e:
        results["canny"] = {"pass": False, "error": str(e)}

    # cornerHarris
    try:
        gray = cv2.cvtColor(arr, cv2.COLOR_BGR2GRAY).astype(np.float32)
        corners = cv2.cornerHarris(gray, 2, 3, 0.04)
        results["corner_harris"] = {
            "pass": True,
            "output_shape": str(corners.shape),
        }
    except Exception as e:
        results["corner_harris"] = {"pass": False, "error": str(e)}

    # findContours
    try:
        gray = cv2.cvtColor(arr, cv2.COLOR_BGR2GRAY)
        _, thresh = cv2.threshold(gray, 127, 255, cv2.THRESH_BINARY)
        contours, _ = cv2.findContours(thresh, cv2.RETR_TREE, cv2.CHAIN_APPROX_SIMPLE)
        results["find_contours"] = {
            "pass": True,
            "num_contours": len(contours),
        }
    except Exception as e:
        results["find_contours"] = {"pass": False, "error": str(e)}

    # Draw operations (modify in-place)
    try:
        test_arr = arr.copy()
        cv2.circle(test_arr, (100, 100), 50, (0, 255, 0), 2)
        cv2.rectangle(test_arr, (50, 50), (150, 150), (255, 0, 0), 2)
        cv2.putText(test_arr, "Test", (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 0, 255), 2)
        results["draw_operations"] = {"pass": True}
    except Exception as e:
        results["draw_operations"] = {"pass": False, "error": str(e)}

    return results


def main():
    parser = argparse.ArgumentParser(description="Validate frame format")
    parser.add_argument("device", nargs="?", default="/dev/video0", help="V4L2 device path")
    parser.add_argument("--resolution", default="640x480", help="Capture resolution")
    parser.add_argument("--no-display", action="store_true", help="Skip visual preview")
    args = parser.parse_args()

    width, height = map(int, args.resolution.split("x"))
    expected_shape = (height, width, 3)

    print("=" * 70)
    print("PyAV Exploration - Script 10: Frame Format Validation")
    print("=" * 70)
    print(f"\nDevice: {args.device}")
    print(f"Resolution: {args.resolution}")

    # Capture frame
    print("\nCapturing frame...")
    arr = capture_frame(args.device, args.resolution)

    # Validate array properties
    print("\n" + "=" * 70)
    print("Array Properties")
    print("=" * 70)

    props = validate_array_properties(arr, expected_shape)
    all_pass = True

    for name, result in props.items():
        status = "OK" if result["pass"] else "FAIL"
        print(f"  {name}: {result['actual']} (expected: {result['expected']}) - {status}")
        if not result["pass"]:
            all_pass = False

    # Memory info
    print("\n  Additional info:")
    print(f"    strides: {arr.strides}")
    print(f"    nbytes: {arr.nbytes:,} bytes ({arr.nbytes / 1024:.1f} KB)")
    print(f"    data pointer aligned: {arr.ctypes.data % 16 == 0}")

    # Test OpenCV operations
    print("\n" + "=" * 70)
    print("OpenCV Compatibility")
    print("=" * 70)

    opencv_results = test_opencv_operations(arr)

    for name, result in opencv_results.items():
        if result["pass"]:
            extra = ""
            if "output_shape" in result:
                extra = f" -> {result['output_shape']}"
            elif "num_contours" in result:
                extra = f" -> {result['num_contours']} contours"
            print(f"  {name}: OK{extra}")
        else:
            print(f"  {name}: FAIL - {result.get('error', 'Unknown error')}")
            all_pass = False

    # Verdict
    print("\n" + "=" * 70)
    print("Verdict")
    print("=" * 70)

    if all_pass:
        print("  PASS: All validations passed")
        print("  PyAV frames are fully compatible with OpenCV operations")
    else:
        print("  FAIL: Some validations failed (see above)")

    # Preview
    if not args.no_display:
        print("\nPress any key to close preview...")
        cv2.imshow("Captured Frame", arr)
        cv2.waitKey(0)
        cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
