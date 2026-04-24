from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class AutopilotStatus:
    enabled: bool
    interval_minutes: int
    message: str = "Autopilot skeleton is present; scheduled execution is disabled by default."


class BoardAutopilotScheduler:
    """Placeholder for the future background board-control loop.

    It intentionally has no hidden write path. Future autopilot actions must reuse
    the same CRM tool registry, audit service and verification flow as Telegram runs.
    """

    def __init__(self, *, enabled: bool, interval_minutes: int) -> None:
        self._enabled = enabled
        self._interval_minutes = max(1, int(interval_minutes))

    def status(self) -> AutopilotStatus:
        return AutopilotStatus(
            enabled=self._enabled,
            interval_minutes=self._interval_minutes,
        )
