"""Recording intent dataclass for grid view recording decisions."""

from dataclasses import dataclass


@dataclass(frozen=True)
class GridRecordingIntent:
    """Encapsulates user's recording destination choice from the grid view.

    Attributes:
        is_extrinsic: True if recording to calibration/extrinsic/, False for recordings/<name>/
        recording_name: The user-supplied or auto-generated name. Only meaningful when
            is_extrinsic is False.
    """

    is_extrinsic: bool
    recording_name: str
