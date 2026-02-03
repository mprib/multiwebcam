"""Temporally aligned frame cluster."""

from __future__ import annotations

from dataclasses import dataclass

from multiwebcam.sources.frame_packet import FramePacket


@dataclass(frozen=True, slots=True)
class FrameCluster:
    """
    A group of frames from the nearest-neighbor alignment algorithm.

    Frames in a cluster were NOT captured simultaneously (hardware genlock
    would be required). Instead, they represent the best temporal match
    from each camera at this sync index.

    Note: Some cameras may have None if their frame was closer to the
    next cluster than the current one. This is valid - the algorithm
    uses relative comparison, not a fixed tolerance window.

    Attributes:
        cluster_index: Sequential cluster number (0-based)
        cluster_time: Mean timestamp of included frames (seconds)
        frames: Map from device_path to FramePacket (None if skipped)
    """

    cluster_index: int
    cluster_time: float
    frames: dict[str, FramePacket | None]

    @property
    def device_paths(self) -> list[str]:
        """Ordered list of device paths in this cluster."""
        return sorted(self.frames.keys())

    @property
    def frame_count(self) -> int:
        """Number of non-None frames in this cluster."""
        return sum(1 for f in self.frames.values() if f is not None)

    @property
    def is_complete(self) -> bool:
        """True if all cameras have frames (no None values)."""
        return all(f is not None for f in self.frames.values())
