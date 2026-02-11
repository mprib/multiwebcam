NOTE: This project is currently in substantial flux as I basically do a complete re-write using PyAV rather than OpenCV. It's more of a personal project at this time as I work through polishing it up. I may not have time to dedicate to making meaningful progress on it until April of 2026. Caveat emptor.

# multiwebcam

Multi-camera capture and recording for USB webcams on Linux. Output feeds into [Caliscope](https://github.com/mprib/caliscope) for calibration and 3D reconstruction.

## What This Does

Captures video from multiple USB webcams simultaneously, recording to individual MP4 files with accurate timestamps. Each camera gets:
- `cam_N.mp4` - H.264 encoded video
- `cam_N_frametimes.csv` - Frame timestamps for temporal alignment

This is **not** hardware-synchronized capture. Consumer USB webcams have no genlock. We capture independently and record timestamps so Caliscope can align frames temporally (typical precision: 10-50ms).

## Requirements

- Linux with V4L2 support
- Python 3.11+
- v4l2-utils (`sudo apt install v4l-utils`)
- USB webcams

### Camera Compatibility

Simple, "dumb" USB webcams work best. Cameras that just stream frames without complex firmware (like the **eMeet C960** or **Logitech C920**) are reliable and predictable.

Feature-rich cameras (autofocus, dynamic exposure modes, HDR) tend to be **less** reliable. Their firmware can hang when V4L2 controls are changed mid-stream, sometimes requiring a physical USB replug to recover. The **Razer Kiyo Pro**, for example, freezes when switching exposure modes during capture.

**Tested and recommended**: eMeet C960

**Known issues**: Razer Kiyo Pro (firmware hangs on exposure mode changes), Logitech C920/C930e (similar firmware instability)

## Installation

```bash
git clone https://github.com/mprib/multiwebcam
cd multiwebcam
uv sync
```

## Usage

Run from any directory you want to use as a project folder:

```bash
mwc
# or
multiwebcam
```

On first run, cameras are discovered and saved to `multiwebcam.toml`. On subsequent runs, the saved configuration is loaded.

### Controls

- **Grid View**: Shows all cameras with live preview and stats
- **Focus**: Click to see single camera large
- **Back to Grid**: Return to multi-camera view
- **Record/Stop**: Start/stop recording to `recordings/` folder

### Output Structure

```
your_project/
├── multiwebcam.toml      # Camera configuration
└── recordings/
    ├── cam_0.mp4
    ├── cam_0_frametimes.csv
    ├── cam_1.mp4
    ├── cam_1_frametimes.csv
    └── ...
```

## Troubleshooting

**Camera not detected?**
```bash
v4l2-ctl --list-devices
```

**Dark/overexposed image?**
Check exposure mode:
```bash
v4l2-ctl -d /dev/video0 --get-ctrl=auto_exposure
v4l2-ctl -d /dev/video0 --set-ctrl=auto_exposure=3  # Auto mode
```

**Permission denied?**
Add user to video group:
```bash
sudo usermod -aG video $USER
# Log out and back in
```

## License

BSD-2-Clause. See LICENSE file.

## Related

- [Caliscope](https://github.com/mprib/caliscope) - Multi-camera calibration and 3D reconstruction
