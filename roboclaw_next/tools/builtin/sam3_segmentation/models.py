"""Pydantic contracts for SAM3 perception MCP tools."""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel


class Sam3PerceptionState(str, Enum):
    """Lifecycle state for the long-running SAM3 perception service."""

    STOPPED = "stopped"
    STARTING = "starting"
    RUNNING = "running"
    FAILED = "failed"


class Sam3PerceptionStatusResult(BaseModel):
    """Current SAM3 perception service process state."""

    state: Sam3PerceptionState
    pid: int | None
    return_code: int | None
    last_error: str | None
    message: str
