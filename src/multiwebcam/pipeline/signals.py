"""Inter-thread control signals for the capture pipeline."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class StartSignal:
    """Signal to begin capturing frames."""

    pass


@dataclass(frozen=True, slots=True)
class StopSignal:
    """Signal to stop capturing but keep thread alive."""

    pass


@dataclass(frozen=True, slots=True)
class ShutdownSignal:
    """Signal to shut down thread completely."""

    pass
