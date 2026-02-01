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

### Live USB Monitoring

The most useful debugging tool for USB issues:

```bash
sudo dmesg -w
```

This watches kernel messages in real-time. Plug/unplug devices and watch what happens:

| Message | Meaning |
|---------|---------|
| `New USB device found, idVendor=...` | Device detected, enumeration starting |
| `Found UVC 1.00 device <name>` | Camera driver attached successfully |
| `device descriptor read/64, error -71` | Electrical/cable issue |
| `device not accepting address` | Power or signal integrity problem |
| `cannot set alt` or `No space left on device` | Bandwidth exhaustion |
| `GET_CABLE_PROPERTY failed (-5)` | USB-C PD negotiation issue (often harmless) |
| (nothing at all) | Port may be dead or disabled |

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
| Camera not detected via USB-C adapter | Connection order issue | See below |

### USB-C Adapter Connection Order

When using USB-C to USB-A adapters, **connection order matters**:

**Fails**: Plug adapter into port first, then plug camera into adapter
- Port negotiates with empty adapter
- Camera hot-plugs into already-negotiated adapter
- Enumeration often fails silently

**Works**: Connect camera to adapter first, then plug the whole assembly into port
- Port sees complete device tree at once
- Proper enumeration and power negotiation

This is a USB-C Power Delivery quirk. The `GET_CABLE_PROPERTY failed (-5)` error in dmesg is a symptom but usually not fatal if the device eventually enumerates.

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

## Resource Cleanup (Phase 2)

PyAV containers properly implement the context manager protocol. No file descriptor leaks observed.

**Recommended pattern**:
```python
with av.open(device, format='v4l2') as container:
    for frame in container.decode(video=0):
        # process frame
        ...
```

Key findings:
- 10 rapid open/close cycles: no fd leaks
- Context manager handles cleanup even when exceptions occur
- No delay needed between close and reopen
- Both explicit `close()` and context manager work, but context manager is safer

---

## Pixel Formats & Resolutions (Phase 2)

### MJPEG vs YUYV Trade-offs

| Format | Pros | Cons |
|--------|------|------|
| MJPEG | Higher res at higher fps, less USB bandwidth | Compression artifacts, CPU decode (minimal) |
| YUYV | No compression artifacts, lower latency | Limited to lower res/fps due to bandwidth |

### Bandwidth Measurements (Logitech C930e)

| Format | Resolution | Frame Size | Bandwidth | Decode Time |
|--------|------------|------------|-----------|-------------|
| MJPEG | 1920x1080 | 110 KB | 27 Mbps | 2.5ms |
| MJPEG | 1280x720 | 60 KB | 15 Mbps | 0.5ms |
| MJPEG | 640x480 | 24 KB | 6 Mbps | 0.2ms |
| YUYV | 640x480 | 600 KB | 148 Mbps | 1.2ms |
| YUYV | 1280x720 | 1800 KB | 442 Mbps | 2.3ms |

**Key finding**: MJPEG 1080p uses 5.5x LESS bandwidth than YUYV 480p while delivering 6.8x more pixels.

USB 2.0 isochronous limit: ~384 Mbps. YUYV 720p (442 Mbps) exceeds this - only works on USB 3.0.

**Decision**: MJPEG is the default for all capture. No practical reason to use YUYV.

### MJPEG Color Conversion Fix

**Problem**: PyAV's `frame.to_ndarray(format='bgr24')` produces garbage for MJPEG frames (yuvj422p format). Symptoms: purple tint, yellow blocks, scrambled tiles.

**Root cause**: PyAV's yuvj422p → bgr24 conversion is broken. The `yuvj422p` format (full-range JPEG YUV 4:2:2) isn't properly handled.

**Solution**: Reformat to rgb24 first, then use OpenCV to convert:

```python
def frame_to_bgr(frame) -> np.ndarray:
    if frame.format.name in ("yuvj422p", "yuvj420p"):
        # MJPEG - reformat to rgb24 (bgr24 is broken)
        rgb_frame = frame.reformat(format="rgb24")
        return cv2.cvtColor(rgb_frame.to_ndarray(), cv2.COLOR_RGB2BGR)
    else:
        # YUYV - direct conversion works
        return frame.to_ndarray(format="bgr24")
```

**What doesn't work**:
- `frame.to_ndarray(format='bgr24')` - garbage output
- `frame.reformat(format='bgr24').to_ndarray()` - scrambled tiles
- Raw packet → `cv2.imdecode()` - corrupt JPEG errors
- Raw packet → PIL decode - works but slower

### Per-Camera Capability Comparison

| Camera | Max MJPEG | Max YUYV @30fps | Notes |
|--------|-----------|-----------------|-------|
| Laptop Webcam | 1920x1080@30 | 640x480 | Limited YUYV options |
| Razer Kiyo Pro | 1920x1080@30 | 640x480 | Good across formats |
| Logitech C930e | 1920x1080@30 | 848x480 | Many resolution options |
| eMeet C960 | (not tested) | (not tested) | |

### Resolution Setting Behavior

Some cameras **silently fall back** to nearest supported resolution instead of erroring:
```python
# DANGEROUS: May get different resolution without error
container = av.open(device, format='v4l2', options={'video_size': '4096x2160'})

# SAFE: Verify what you actually got
frame = next(container.decode(video=0))
if (frame.width, frame.height) != (requested_width, requested_height):
    raise ValueError(f"Resolution mismatch")
```

**Best practice**: Query supported resolutions first (via `v4l2-ctl --list-formats-ext`), only request known-good values.

---

## Framerate Behavior (Phase 2)

### Expected vs Actual FPS

USB cameras are **not real-time devices**. Expect:
- 85-95% of requested framerate under normal conditions
- Higher jitter at lower framerates (counter-intuitive)
- Resolution affects achievable fps (more pixels = more bandwidth)

### Jitter Characteristics

Tested on Razer Kiyo Pro at 640x480:

| Requested FPS | Actual FPS | Jitter (stddev) | Max Interval |
|---------------|------------|-----------------|--------------|
| 30 | 26.9 (90%) | 27.6ms | 356ms |
| 15 | 13.6 (91%) | 60.4ms | 570ms |
| 10 | 8.7 (87%) | 110.4ms | 836ms |

**Key insight**: Jitter increases at lower framerates. USB delivery is bursty.

### Implications for Multi-Camera Sync

- Frames won't arrive at predictable intervals
- Use wall-clock timestamps, not frame indices
- Expect 10-50ms alignment error between cameras
- High-res + multiple cameras = more bandwidth contention = more jitter

---

## Camera Controls (Phase 2)

### Control Categories

| Category | Common Controls |
|----------|-----------------|
| Exposure | `auto_exposure`, `exposure_time_absolute`, `gain` |
| White Balance | `white_balance_automatic`, `white_balance_temperature` |
| Focus | `focus_automatic_continuous`, `focus_absolute` |
| Image | `brightness`, `contrast`, `saturation`, `sharpness` |

### Auto vs Manual Mode Dependencies

Controls have dependencies - must disable auto before manual adjustment:

```bash
# Switch to manual exposure first
v4l2-ctl -d /dev/video0 --set-ctrl auto_exposure=1
# Now exposure_time_absolute will work
v4l2-ctl -d /dev/video0 --set-ctrl exposure_time_absolute=500
```

### Per-Camera Control Comparison

| Control | Laptop Webcam | Razer Kiyo Pro | Logitech C930e |
|---------|---------------|----------------|----------------|
| Focus | No | Yes (0-600) | Yes |
| Gain | No | Yes (0-255) | Yes |
| Zoom | No | Yes (100-400) | Yes |
| Pan/Tilt | No | Yes | Yes |

Cheap webcams have fewer controls. The laptop webcam has no focus control (fixed focus lens).

### Setting Controls Workflow

1. Configure controls with v4l2-ctl **before** opening PyAV stream
2. Open stream with PyAV
3. Controls persist while device is open
4. Some controls (like resolution-related) require stream restart

---

## Future Optimizations

- **Preview decimation**: Convert to BGR only every Nth frame for display (6Hz preview sufficient for framing). Record at full rate in native format.

---

## Open Questions

- Hardware timestamps vs `perf_counter()` accuracy
- USB bandwidth limits for multi-camera 1080p30 (partially answered: jitter increases with load)
- ~~MJPEG vs YUYV tradeoffs per camera~~ (answered in Phase 2)
- ~~Frame timing jitter characteristics~~ (answered in Phase 2)
