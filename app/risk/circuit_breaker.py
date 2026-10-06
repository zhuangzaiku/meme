from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CircuitStatus:
    paused: bool
    consecutive_losses: int
    reason: str | None = None


class CircuitBreaker:
    def __init__(self, max_consecutive_losses: int = 3) -> None:
        self.max_consecutive_losses = max_consecutive_losses
        self._consecutive_losses = 0
        self._paused = False
        self._reason: str | None = None

    def record(self, outcome: str) -> None:
        if outcome == "loss":
            self._consecutive_losses += 1
            if self._consecutive_losses >= self.max_consecutive_losses:
                self._paused = True
                self._reason = "consecutive loss limit reached"
        elif outcome == "win":
            self._consecutive_losses = 0

    def pause(self, reason: str) -> None:
        self._paused = True
        self._reason = reason

    def resume(self) -> None:
        self._paused = False
        self._reason = None

    def status(self) -> CircuitStatus:
        return CircuitStatus(self._paused, self._consecutive_losses, self._reason)
