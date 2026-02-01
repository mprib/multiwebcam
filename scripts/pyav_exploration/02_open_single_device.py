#!/usr/bin/env python3
"""
Script 02: Open Single Device

Verify PyAV can open a V4L2 device and grab a frame.

Usage:
    uv run python scripts/pyav_exploration/02_open_single_device.py [device]
"""

import sys
import av

def main():
    device = sys.argv[1] if len(sys.argv) > 1 else '/dev/video0'

    print(f"Opening {device}...")
    container = av.open(device, format='v4l2')

    stream = container.streams.video[0]
    print(f"Stream: {stream.codec_context.name}, {stream.width}x{stream.height}")

    for frame in container.decode(video=0):
        print(f"Frame: pts={frame.pts}, {frame.width}x{frame.height}, format={frame.format.name}")

        # Convert to numpy
        img = frame.to_ndarray(format='bgr24')
        print(f"Array: shape={img.shape}, dtype={img.dtype}")
        break

    container.close()
    print("Done.")

if __name__ == '__main__':
    main()
