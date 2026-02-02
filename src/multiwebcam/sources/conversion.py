"""Frame conversion utilities for PyAV."""

import av
import cv2
import numpy as np


def frame_to_bgr(frame: av.VideoFrame) -> np.ndarray:
    """
    Convert a PyAV VideoFrame to BGR numpy array.

    Handles the MJPEG color conversion quirk: PyAV's direct bgr24 conversion
    produces garbage for yuvj422p/yuvj420p formats. We route through rgb24
    and use OpenCV for the final conversion.

    Returns:
        BGR image as numpy array, shape (H, W, 3), dtype uint8.
        The array is a COPY - safe to hold across decode calls.
    """
    format_name = frame.format.name

    if format_name in ("yuvj422p", "yuvj420p"):
        # MJPEG decoded format - direct bgr24 is broken
        rgb_frame = frame.reformat(format="rgb24")
        arr = rgb_frame.to_ndarray()
        return cv2.cvtColor(arr, cv2.COLOR_RGB2BGR).copy()
    else:
        # YUYV or other formats - direct conversion works
        return frame.to_ndarray(format="bgr24").copy()
