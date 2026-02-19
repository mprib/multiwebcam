"""Utilities for auto-generating recording names."""

import re
from pathlib import Path


def next_recording_name(recordings_dir: Path) -> str:
    """Return 'recording_NNN' where NNN is one past the highest existing.

    Scans recordings_dir for folders matching the pattern 'recording_NNN'
    and returns the next name in sequence. Returns 'recording_001' if no
    matching folders exist or if the directory does not exist.

    Args:
        recordings_dir: Path to the recordings directory to scan.

    Returns:
        A string like 'recording_001', 'recording_002', etc.
    """
    if not recordings_dir.exists():
        return "recording_001"

    pattern = re.compile(r"^recording_(\d+)$")
    highest = 0
    for entry in recordings_dir.iterdir():
        if entry.is_dir():
            match = pattern.match(entry.name)
            if match:
                n = int(match.group(1))
                if n > highest:
                    highest = n

    return f"recording_{highest + 1:03d}"
