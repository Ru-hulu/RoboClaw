"""Stable, JSON-safe errors for the SAM3 runtime boundary."""

from __future__ import annotations

from enum import StrEnum


class Sam3ErrorCode(StrEnum):
    """Machine-readable failures returned by the runtime and MCP tools."""

    INVALID_INPUT = "INVALID_INPUT"
    MODEL_UNAVAILABLE = "MODEL_UNAVAILABLE"
    SOURCE_REVISION_MISMATCH = "SOURCE_REVISION_MISMATCH"
    CHECKPOINT_MISMATCH = "CHECKPOINT_MISMATCH"
    GPU_OOM = "GPU_OOM"
    INFERENCE_TIMEOUT = "INFERENCE_TIMEOUT"
    WORKER_EXITED = "WORKER_EXITED"
    OUTPUT_EXISTS = "OUTPUT_EXISTS"
    OUTPUT_WRITE_FAILED = "OUTPUT_WRITE_FAILED"


class Sam3RuntimeError(RuntimeError):
    """Runtime failure carrying a stable error code and safe message."""

    def __init__(self, code: Sam3ErrorCode, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(message)

    def to_dict(self) -> dict[str, object]:
        """Return the public JSON error representation."""

        return {"code": self.code.value, "message": self.message}
