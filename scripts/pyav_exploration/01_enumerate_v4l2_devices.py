#!/usr/bin/env python3
"""
Phase 1: Device Discovery & Basics
Script 01: Enumerate V4L2 Devices

Purpose: Find all V4L2 video devices and distinguish real cameras from metadata nodes.

Expected behavior:
- List all /dev/video* devices
- Query device capabilities via sysfs
- Filter capture devices from metadata/output nodes
- Report device name, driver, and capabilities
"""

from pathlib import Path
import subprocess
from dataclasses import dataclass
import os
import fcntl
import struct


# V4L2 capability flags (from videodev2.h)
V4L2_CAP_VIDEO_CAPTURE = 0x00000001
V4L2_CAP_VIDEO_OUTPUT = 0x00000002
V4L2_CAP_VIDEO_OVERLAY = 0x00000004
V4L2_CAP_META_CAPTURE = 0x00800000
V4L2_CAP_META_OUTPUT = 0x00002000

# V4L2 ioctl codes (from videodev2.h)
# VIDIOC_QUERYCAP = _IOR('V', 0, sizeof(v4l2_capability))
# On x86_64 Linux: 0x80685600
VIDIOC_QUERYCAP = 0x80685600


@dataclass
class V4L2Device:
    """Information about a V4L2 device."""

    path: Path
    name: str
    driver: str
    device_caps: int

    @property
    def is_video_capture(self) -> bool:
        """True if device supports video capture (not metadata)."""
        return bool(self.device_caps & V4L2_CAP_VIDEO_CAPTURE)

    @property
    def is_metadata(self) -> bool:
        """True if device is a metadata node."""
        return bool(self.device_caps & (V4L2_CAP_META_CAPTURE | V4L2_CAP_META_OUTPUT))

    @property
    def is_output(self) -> bool:
        """True if device supports video output."""
        return bool(self.device_caps & V4L2_CAP_VIDEO_OUTPUT)

    @property
    def recommendation(self) -> str:
        """User-facing recommendation for this device."""
        if self.is_video_capture and not self.is_metadata:
            return "[RECOMMENDED]"
        elif self.is_metadata:
            return "[SKIP - metadata]"
        elif self.is_output:
            return "[SKIP - output]"
        else:
            return "[SKIP - unknown type]"

    @property
    def device_type(self) -> str:
        """Human-readable device type."""
        types = []
        if self.device_caps & V4L2_CAP_VIDEO_CAPTURE:
            types.append("capture")
        if self.device_caps & V4L2_CAP_VIDEO_OUTPUT:
            types.append("output")
        if self.device_caps & V4L2_CAP_META_CAPTURE:
            types.append("metadata")
        if self.device_caps & V4L2_CAP_VIDEO_OVERLAY:
            types.append("overlay")

        return ", ".join(types) if types else "unknown"


def query_device_info(device_path: Path) -> V4L2Device | None:
    """
    Query device information from sysfs.

    Args:
        device_path: Path to /dev/videoN device

    Returns:
        V4L2Device if information can be read, None if device doesn't exist in sysfs
    """
    device_name = device_path.name  # e.g., "video0"
    sys_path = Path(f"/sys/class/video4linux/{device_name}")

    if not sys_path.exists():
        return None

    try:
        # Read device name
        name_file = sys_path / "name"
        name = name_file.read_text().strip() if name_file.exists() else "Unknown"

        # Read device capabilities
        # Note: Some older kernels may not have device_caps, fall back to checking with v4l2-ctl
        caps_file = sys_path / "device" / "capabilities"
        if not caps_file.exists():
            # Try alternative location
            caps_file = sys_path / "dev_debug" / "capabilities"

        # Read device_caps - this is the reliable way to check capabilities
        # We need to parse the "caps" file which contains hex capabilities
        dev = sys_path / "dev"
        if dev.exists():
            # Use v4l2-ctl to get accurate capabilities
            device_caps = query_caps_via_v4l2ctl(device_path)
        else:
            device_caps = 0

        # Read driver name from device symlink
        device_link = sys_path / "device"
        if device_link.exists():
            # Try to read driver from device/driver symlink
            driver_link = device_link / "driver"
            if driver_link.exists() and driver_link.is_symlink():
                driver = driver_link.resolve().name
            else:
                driver = "unknown"
        else:
            driver = "unknown"

        return V4L2Device(
            path=device_path,
            name=name,
            driver=driver,
            device_caps=device_caps
        )

    except Exception as e:
        print(f"  Warning: Could not read sysfs info for {device_path}: {e}")
        return None


def query_caps_via_ioctl(device_path: Path) -> int:
    """
    Query device capabilities using direct ioctl call.

    This is a fallback when v4l2-ctl is not available. Opens the device
    file and uses VIDIOC_QUERYCAP ioctl to read the v4l2_capability struct.

    Args:
        device_path: Path to /dev/videoN device

    Returns:
        Device capabilities as integer bitmask, or 0 if query fails
    """
    try:
        # Open device read-only, non-blocking
        fd = os.open(str(device_path), os.O_RDONLY | os.O_NONBLOCK)
        try:
            # v4l2_capability struct layout (104 bytes total):
            # - driver[16]: char[16]
            # - card[32]: char[32]
            # - bus_info[32]: char[32]
            # - version: uint32 (4 bytes)
            # - capabilities: uint32 (4 bytes) - overall driver caps
            # - device_caps: uint32 (4 bytes) - THIS device's caps (offset 84)
            # - reserved[12]: uint32[3]
            buf = bytearray(104)
            fcntl.ioctl(fd, VIDIOC_QUERYCAP, buf)

            # Extract device_caps at offset 88 (little-endian uint32)
            # Note: offset 84 is "capabilities" (driver-level), 88 is "device_caps" (per-device)
            device_caps = struct.unpack_from('<I', buf, 88)[0]
            return device_caps
        finally:
            os.close(fd)
    except (OSError, PermissionError) as e:
        # Device might not exist, or user lacks permissions
        return 0


def query_caps_via_v4l2ctl(device_path: Path) -> int:
    """
    Query device capabilities using v4l2-ctl.

    This is more reliable than direct ioctl as v4l2-ctl handles device
    quirks and variations. Falls back to ioctl if v4l2-ctl is not installed.

    Args:
        device_path: Path to /dev/videoN device

    Returns:
        Device capabilities as integer bitmask
    """
    try:
        result = subprocess.run(
            ['v4l2-ctl', '--device', str(device_path), '--all'],
            capture_output=True,
            text=True,
            timeout=2
        )

        # Parse output for "Device Caps" line
        # Example: "Device Caps      : 0x04200001"
        for line in result.stdout.splitlines():
            if "Device Caps" in line:
                # Extract hex value
                hex_value = line.split(":")[-1].strip()
                return int(hex_value, 16)

        return 0

    except FileNotFoundError:
        # v4l2-ctl not installed, fall back to direct ioctl
        return query_caps_via_ioctl(device_path)
    except (subprocess.TimeoutExpired, subprocess.CalledProcessError):
        # v4l2-ctl exists but failed - try ioctl as fallback
        return query_caps_via_ioctl(device_path)


def enumerate_v4l2_devices() -> list[V4L2Device]:
    """
    Enumerate all V4L2 video devices on the system.

    Returns:
        List of V4L2Device objects for all found devices
    """
    devices = []

    # Find all /dev/video* devices
    dev_path = Path("/dev")
    video_devices = sorted(dev_path.glob("video*"))

    for device_path in video_devices:
        # Only consider character devices (not directories, symlinks, etc.)
        if not device_path.is_char_device():
            continue

        device_info = query_device_info(device_path)
        if device_info:
            devices.append(device_info)

    return devices


def print_device_summary(devices: list[V4L2Device]) -> None:
    """Print a formatted summary of all devices."""
    print(f"\nFound {len(devices)} video devices:\n")

    for device in devices:
        print(f"  {device.path}: {device.name}")
        print(f"    Driver: {device.driver}")
        print(f"    Type: {device.device_type}")
        print(f"    Capabilities: 0x{device.device_caps:08x}")
        print(f"    Status: {device.recommendation}")
        print()

    # Summary
    capture_devices = [d for d in devices if d.is_video_capture and not d.is_metadata]
    metadata_devices = [d for d in devices if d.is_metadata]

    print("Summary:")
    print(f"  Capture devices (usable): {len(capture_devices)}")
    print(f"  Metadata nodes (skip): {len(metadata_devices)}")
    print(f"  Other: {len(devices) - len(capture_devices) - len(metadata_devices)}")

    if capture_devices:
        print("\nRecommended devices for capture:")
        for device in capture_devices:
            print(f"  {device.path} - {device.name}")


def main() -> None:
    """Main entry point."""
    print("=" * 70)
    print("V4L2 Device Enumeration")
    print("=" * 70)
    print("\nThis script finds all V4L2 video devices and identifies which are")
    print("suitable for video capture (vs metadata nodes that should be skipped).")
    print("\nNote: Many USB cameras expose 2 nodes - one for video, one for metadata.")
    print("Only the capture node can be used with PyAV.")

    # Check if v4l2-ctl is available
    v4l2ctl_available = True
    try:
        subprocess.run(['v4l2-ctl', '--version'],
                      capture_output=True,
                      check=True,
                      timeout=1)
    except (subprocess.CalledProcessError, FileNotFoundError):
        v4l2ctl_available = False
        print("\nNote: v4l2-ctl not found. Using ioctl fallback for device capabilities.")
        print("For best results, install v4l-utils:")
        print("  sudo apt-get install v4l-utils")
        print()

    # Enumerate devices
    devices = enumerate_v4l2_devices()

    if not devices:
        print("\nNo V4L2 devices found!")
        print("Check that:")
        print("  1. Cameras are connected")
        print("  2. You have permissions to access /dev/video*")
        print("  3. Camera drivers are loaded (lsmod | grep uvcvideo)")
        return

    # Print results
    print_device_summary(devices)

    print("\n" + "=" * 70)
    print("Key Findings:")
    print("=" * 70)
    print("""
1. Metadata nodes appear as separate /dev/video* entries
2. Only devices with VIDEO_CAPTURE capability can produce frames
3. Same camera may expose multiple device nodes (video + metadata)
4. Device numbering is not sequential - gaps are normal

Next Steps:
- Script 02 will attempt to open capture devices with PyAV
- We'll use the [RECOMMENDED] devices from this list
""")


if __name__ == "__main__":
    main()
