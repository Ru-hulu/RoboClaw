"""Pydantic contracts for SAM3 perception MCP tools."""

from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field, FiniteFloat, model_validator
from typing_extensions import Self


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
    current_request_id: str | None
    last_request_id: str | None
    last_error: str | None
    message: str


class Sam3TargetObjectPoseResult(BaseModel):
    """Result returned by the SAM3 target-pose RPC."""

    ok: Literal[True] = True
    request_id: str
    pose_valid: bool = Field(
        description="Whether the returned target object pose can be used."
    )
    frame_id: str | None = Field(
        default=None,
        description="Coordinate frame of the returned pose when pose_valid is true.",
    )
    position_xyz: list[FiniteFloat] | None = Field(
        default=None,
        min_length=3,
        max_length=3,
        description="Target center position [x, y, z] when pose_valid is true.",
    )
    score: float | None = Field(
        default=None,
        ge=0.0,
        le=1.0,
        allow_inf_nan=False,
        description="Optional perception confidence score.",
    )
    message: str

    @model_validator(mode="after")
    def validate_pose_payload(self) -> Self:
        if not self.pose_valid:
            return self
        if self.frame_id is None or self.position_xyz is None:
            raise ValueError(
                "A valid target pose must include frame_id and position_xyz."
            )
        return self


class Sam3TargetObjectPoseErrorResult(BaseModel):
    """Stable target-pose failure result that keeps the MCP transport alive."""

    ok: Literal[False] = False
    error_code: str = Field(description="Stable target-pose failure code.")
    message: str = Field(description="Concise recovery-oriented error message.")
    request_id: str | None = Field(
        default=None,
        description="Target-pose request id when a request was sent.",
    )
