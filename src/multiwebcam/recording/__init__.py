"""Recording system for multi-camera capture."""

from multiwebcam.recording.frametimes import FrametimesCollector, write_frametimes_csv
from multiwebcam.recording.recorder import FrameRecorder, RecordingResult

__all__ = [
    "FrameRecorder",
    "RecordingResult",
    "FrametimesCollector",
    "write_frametimes_csv",
]
