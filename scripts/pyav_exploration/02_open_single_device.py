#!/usr/bin/env python3
"""
Script 02: Open Single Device

Verify PyAV can open a V4L2 device and grab a frame.
Defaults to MJPEG at 1080p for maximum quality within USB bandwidth.

Usage:
    uv run python scripts/pyav_exploration/02_open_single_device.py [device] [--yuyv] [--save]

Options:
    --yuyv  Use YUYV (raw) instead of MJPEG
    --save  Save frame to /tmp/frame_test.png for inspection
"""

import sys

import av


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
        print(f"Frame: pts={frame.pts}, {frame.width}x{frame.height}, format={frame.format.name}")

        # Convert to numpy
        img = frame.to_ndarray(format="bgr24")
        print(f"Array: shape={img.shape}, dtype={img.dtype}")

        if save_frame:
            import cv2

            path = "/tmp/frame_test.png"
            cv2.imwrite(path, img)
            print(f"Saved to {path}")

        break

    container.close()
    print("Done.")


if __name__ == "__main__":
    main()
