"""Calibration driver contracts."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Protocol, TYPE_CHECKING

if TYPE_CHECKING:
    from roboclaw.embodied.execution.orchestration.runtime.executor import (
        ExecutionContext,
        ProcedureExecutionResult,
    )


ProgressCallback = Callable[[str], Awaitable[None]]


class CalibrationDriver(Protocol):
    """Robot-specific calibration flow driver."""

    id: str

    async def begin(
        self,
        context: ExecutionContext,
        *,
        on_progress: ProgressCallback | None = None,
    ) -> ProcedureExecutionResult:
        """Start or resume calibration preparation for one runtime."""

    async def advance(
        self,
        context: ExecutionContext,
        user_input: str | None = None,
        *,
        on_progress: ProgressCallback | None = None,
    ) -> ProcedureExecutionResult:
        """Advance one interactive calibration flow."""

    def describe(self, context: ExecutionContext) -> ProcedureExecutionResult:
        """Describe the current calibration phase without advancing it."""

    def phase(self, context: ExecutionContext) -> str | None:
        """Return the current in-memory calibration phase for one runtime."""

    def cleanup(self, runtime_id: str) -> None:
        """Clean up any in-memory calibration state for one runtime."""


__all__ = [
    "CalibrationDriver",
    "ProgressCallback",
]
