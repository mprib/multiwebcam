# PyAV Exploration Reference

Single source of truth for V4L2/PyAV behavior discovered during exploration.

---

## V4L2 Device Detection

### Capability Flags

```python
V4L2_CAP_VIDEO_CAPTURE = 0x00000001  # Can capture video frames
V4L2_CAP_VIDEO_OUTPUT  = 0x00000002  # Can output video
V4L2_CAP_META_CAPTURE  = 0x00800000  # Metadata node (skip)
V4L2_CAP_STREAMING     = 0x04000000  # Supports streaming I/O
```

### Querying Capabilities via ioctl

```python
VIDIOC_QUERYCAP = 0x80685600  # ioctl command code

# v4l2_capability struct (104 bytes):
# offset 0:  driver[16]
# offset 16: card[32]
# offset 48: bus_info[32]
# offset 80: version (uint32)
# offset 84: capabilities (uint32) - driver-level, same for all nodes
# offset 88: device_caps (uint32)  - per-device, USE THIS ONE
```

Read offset 88 for per-device capabilities. Offset 84 returns driver-level caps (misleading).

### Device Node Pattern

USB cameras expose two `/dev/video*` nodes each:
- **Even nodes** (video0, video2, ...): Capture devices → use these
- **Odd nodes** (video1, video3, ...): Metadata nodes → skip these

Check `device_caps & V4L2_CAP_VIDEO_CAPTURE` to confirm.

---

## Test Hardware

Framework laptop with 4 cameras (device nodes shift when reconnected):

| Camera | Connection | Notes |
|--------|------------|-------|
| Laptop Webcam (2nd Gen) | Built-in | Always reliable |
| Razer Kiyo Pro | Direct USB-C expansion card | Works reliably |
| Logitech C930e | Direct USB-C expansion card | Works reliably |
| eMeet C960 | Through USB dock | Works alongside display+power |

**Key findings**:
- Cameras through USB dock work while dock also handles display + power
- One expansion card slot was defective (no power/display/data) - hardware issue
- Device nodes (`/dev/videoN`) shift based on plug order - don't hardcode

---

## Dependencies

### Required

| Package | Purpose | Install |
|---------|---------|---------|
| `av` (PyAV) | FFmpeg bindings for capture | `uv add av` |
| `ffmpeg` | Backend for PyAV | `sudo apt install ffmpeg` |

### Development Only

| Package | Purpose | Install |
|---------|---------|---------|
| `v4l-utils` | Validate ioctl code, explore controls | `sudo apt install v4l-utils` |

End users should not need v4l-utils - ioctl code handles device detection.

---

## Frame Conversion Performance

All tested cameras output YUYV422 natively. Conversion to BGR24 (needed for OpenCV) benchmarked at 640x480:

| Camera | BGR24 Conversion (avg) | BGR24 Conversion (max) |
|--------|------------------------|------------------------|
| Laptop Webcam | 1.08ms | 2.38ms |
| Razer Kiyo Pro | 1.02ms | 2.01ms |
| Logitech C930e | 1.09ms | 2.55ms |
| eMeet C960 (via dock) | 1.04ms | 1.98ms |

**Verdict**: ~1ms conversion overhead is negligible vs 33ms frame budget at 30fps (~3%).

Native format (no conversion) is ~0.1ms - ten times faster, but outputs 2-channel YUV array instead of 3-channel BGR.

---

## USB Troubleshooting Guide

### Camera Not Detected?

**Step 1: Check USB-level detection**
```bash
lsusb | grep -i cam
```
If camera appears here, USB sees it. If not, it's a hardware/port issue.

**Step 2: Check V4L2 driver detection**
```bash
v4l2-ctl --list-devices
```
If camera is in `lsusb` but not here, the driver didn't attach. Try unplugging and replugging.

**Step 3: Check for stale device nodes**
```bash
ls /dev/video*
```
Device nodes can persist after camera disconnects. Opening a stale node gives "No such device" error.

### Common Issues

| Symptom | Likely Cause | Fix |
|---------|--------------|-----|
| Camera in `lsusb` but not `v4l2-ctl` | Driver didn't attach | Unplug/replug, check `dmesg` |
| "No such device" on existing `/dev/video*` | Stale device node | Re-enumerate with `v4l2-ctl --list-devices` |
| Works in one port, not another | Bad port or bandwidth contention | Try different port, avoid USB hubs |
| Intermittent detection | Power delivery issue | Use powered hub, avoid daisy-chaining |

### USB Bandwidth

- Cameras on the same USB controller share bandwidth
- Check which controller each device is on: `lsusb -t`
- Spread cameras across different controllers when possible
- USB docks can work for cameras even while running display + power (tested)

### Device Node Numbering

Device paths (`/dev/video0`, `/dev/video2`, etc.) are assigned at plug-in time and shift based on order. **Never hardcode device paths.** Use device enumeration at runtime.

### Tested Configurations

| Setup | Result |
|-------|--------|
| 3 cameras, direct USB-C ports | Reliable |
| 4 cameras, mixed direct + dock | Reliable |
| Camera through dock + display + power | Works |
| Defective expansion card slot | Fails for all devices (power, display, data) |

---

## Future Optimizations

- **Preview decimation**: Convert to BGR only every Nth frame for display (6Hz preview sufficient for framing). Record at full rate in native format.

---

## Open Questions

- Hardware timestamps vs `perf_counter()` accuracy
- USB bandwidth limits for multi-camera 1080p30
- MJPEG vs YUYV tradeoffs per camera
- Frame timing jitter characteristics
