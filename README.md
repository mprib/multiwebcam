# multiwebcam

Multi-camera capture and recording for USB webcams on Linux.

## Status: Under Active Revision

This project is being rebuilt from the ground up. The previous OpenCV-based implementation has been replaced with a PyAV/FFmpeg backend for more reliable V4L2 device handling.

**Platform:** Linux only. USB webcam support on Linux is inherently fussy—different cameras have different quirks, V4L2 drivers vary, and USB bandwidth constraints are real. No promises are made about this software working on your specific hardware configuration.

**Current state:**
- Frame capture via PyAV (working)
- Multi-camera recording to MP4 + timestamps (working)
- Camera profile persistence (working)
- Qt UI for live preview and recording (not yet implemented)

## What This Does

Captures frames from multiple USB webcams simultaneously and records them to individual MP4 files with accurate timestamps. The output is designed to feed into [Caliscope](https://github.com/mprib/caliscope) for multi-camera calibration and 3D reconstruction.

This is **not** hardware-synchronized capture. Consumer USB webcams have no genlock capability. We capture frames independently and record timestamps so downstream tools can align them temporally (typical precision: 10-50ms).

## Requirements

- Linux with V4L2 support
- Python 3.11+
- v4l2-utils (`sudo apt install v4l-utils`)
- USB webcams (tested with Logitech C920, eMeet C960, Razer Kiyo Pro)

## Installation

```bash
git clone https://github.com/mprib/multiwebcam
cd multiwebcam
uv sync
```

## Usage

The GUI is not yet implemented. For now, see `scripts/` for example usage of the capture pipeline.

## License

See LICENSE file.
