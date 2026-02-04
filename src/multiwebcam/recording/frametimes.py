"""Frametimes collection and CSV writing for recordings."""

from __future__ import annotations

import csv
import logging
from dataclasses import dataclass
from pathlib import Path
from threading import Lock
from typing import Literal

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class FrametimeEntry:
    """A single frame's timestamp metadata."""

    cam_id: int
    frame_index: int
    frame_time: float


class FrametimesCollector:
    """
    Thread-safe collector for frame timestamps during recording.

    Encoder threads report timestamps as frames are written. When recording
    stops, the collector writes all timestamps to CSV in a single atomic operation.

    Usage:
        collector = FrametimesCollector()

        # From encoder threads
        collector.add_frametime(cam_id=0, frame_index=0, frame_time=1234.567)
        collector.add_frametime(cam_id=1, frame_index=0, frame_time=1234.568)

        # On recording stop
        collector.write_csv(output_dir / "frametimes.csv")
    """

    def __init__(self) -> None:
        self._entries: list[FrametimeEntry] = []
        self._lock = Lock()

    def add_frametime(
        self,
        cam_id: int,
        frame_index: int,
        frame_time: float,
    ) -> None:
        """
        Record a frame's timestamp.

        Thread-safe - can be called from multiple encoder threads.

        Args:
            cam_id: Integer camera ID
            frame_index: Per-camera sequential frame index
            frame_time: Timestamp in seconds
        """
        entry = FrametimeEntry(
            cam_id=cam_id,
            frame_index=frame_index,
            frame_time=frame_time,
        )
        with self._lock:
            self._entries.append(entry)

    def write_csv(self, output_path: Path) -> None:
        """
        Write all collected timestamps to CSV.

        Format:
            cam_id,frame_index,frame_time
            0,0,1234.567
            1,0,1234.568
            ...

        Sorts entries by (cam_id, frame_index) before writing.

        Args:
            output_path: Path to write frametimes.csv
        """
        with self._lock:
            # Sort by cam_id, then frame index for deterministic output
            sorted_entries = sorted(self._entries, key=lambda e: (e.cam_id, e.frame_index))

        write_frametimes_csv(sorted_entries, output_path)
        logger.info(f"Wrote {len(sorted_entries)} frametimes to {output_path}")

    @property
    def frame_count(self) -> int:
        """Total number of frametimes collected."""
        with self._lock:
            return len(self._entries)


def write_frametimes_csv(entries: list[FrametimeEntry], output_path: Path) -> None:
    """
    Write frametime entries to CSV file.

    Args:
        entries: List of FrametimeEntry to write
        output_path: Path to output CSV file
    """
    with open(output_path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["cam_id", "frame_index", "frame_time"])

        for entry in entries:
            writer.writerow(
                [
                    entry.cam_id,
                    entry.frame_index,
                    f"{entry.frame_time:.6f}",  # 6 decimal places for sub-millisecond precision
                ]
            )
