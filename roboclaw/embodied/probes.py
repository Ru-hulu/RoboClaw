"""Embodied onboarding probe contracts."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, Protocol

ToolRunner = Callable[[str, dict[str, Any], Callable[..., Awaitable[None]] | None], Awaitable[str]]


@dataclass(frozen=True)
class ProbeResult:
    """Structured probe result returned to onboarding."""

    ok: bool
    detail: str = ""


class ProbeProvider(Protocol):
    """Robot-specific onboarding probe provider."""

    id: str

    async def probe_serial_device(
        self,
        serial_by_id: str,
        *,
        run_tool: ToolRunner,
        on_progress: Callable[..., Awaitable[None]] | None = None,
    ) -> ProbeResult:
        """Probe one stable serial device path."""


__all__ = [
    "ProbeProvider",
    "ProbeResult",
    "ToolRunner",
]
