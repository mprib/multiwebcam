#!/usr/bin/env python3
"""
Script 02: Open Single Device

Verify PyAV can open a V4L2 device and grab a frame.
Defaults to MJPEG at 1080p for maximum quality within USB bandwidth.

Note: For MJPEG (yuvj422p), use frame.reformat(format='rgb24') then cvtColor.
Direct to_ndarray(format='bgr24') produces garbage.

Usage:
    uv run python scripts/pyav_exploration/02_open_single_device.py [device] [--yuyv] [--save]

Options:
    --yuyv  Use YUYV (raw) instead of MJPEG
    --save  Save frame to /tmp/frame_test.png for inspection
"""

import sys

import av
import cv2


def frame_to_bgr(frame) -> "np.ndarray":
    """
    Convert PyAV frame to BGR numpy array.

    For MJPEG (yuvj422p): reformat to rgb24, then cvtColor to BGR.
    For YUYV: direct to_ndarray works.
    """
    if frame.format.name in ("yuvj422p", "yuvj420p"):
        # MJPEG path - reformat to rgb24 first (bgr24 is broken)
        rgb_frame = frame.reformat(format="rgb24")
        img_rgb = rgb_frame.to_ndarray()
        return cv2.cvtColor(img_rgb, cv2.COLOR_RGB2BGR)
    else:
        # Raw formats (YUYV, etc) - direct conversion works
        return frame.to_ndarray(format="bgr24")


def main():
    # Parse args
    args = sys.argv[1:]
    device = "/dev/video0"
    use_mjpeg = True
    save_frame = False

    for arg in args:
        if arg == "--yuyv":
            use_mjpeg = False
        elif arg == "--save":
            save_frame = True
        elif arg.startswith("/dev/"):
            device = arg

    # Build options
    options = {}
    if use_mjpeg:
        options["input_format"] = "mjpeg"
        options["video_size"] = "1920x1080"
        format_name = "MJPEG 1080p"
    else:
        options["video_size"] = "640x480"  # YUYV limited by bandwidth
        format_name = "YUYV 480p"

    print(f"Opening {device} with {format_name}...")
    container = av.open(device, format="v4l2", options=options)

    stream = container.streams.video[0]
    print(f"Stream: {stream.codec_context.name}, {stream.width}x{stream.height}")

    for frame in container.decode(video=0):
        print(f"Frame: {frame.width}x{frame.height}, format={frame.format.name}")

        img = frame_to_bgr(frame)
        print(f"Array: shape={img.shape}, dtype={img.dtype}")

        if save_frame:
            path = "/tmp/frame_test.png"
            cv2.imwrite(path, img)
            print(f"Saved to {path}")

        break

    container.close()
    print("Done.")


if __name__ == "__main__":
    main()
