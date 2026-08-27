"""FastMCP contracts for SAM3 image segmentation and worker lifecycle."""

from __future__ import annotations

from typing import Annotated, Literal

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations
from pydantic import BaseModel, Field

from robot_runtime.perception.sam3.errors import Sam3RuntimeError

from .models import Sam3SegmentationResult
from .program import (
    Sam3WorkerProcessManager,
    Sam3WorkerState,
    Sam3WorkerStatus,
)


class Sam3ToolErrorResult(BaseModel):
    """Stable failure result that does not terminate the MCP transport."""

    ok: Literal[False] = False
    error_code: str = Field(description="Stable SAM3 runtime error code.")
    message: str = Field(description="Concise recovery-oriented error message.")


class Sam3StatusResult(BaseModel):
    """Current worker process state without starting the model."""

    state: Sam3WorkerState
    pid: int | None
    current_request_id: str | None
    last_activity_at: str | None
    idle_timeout_sec: float = Field(gt=0.0, allow_inf_nan=False)
    load_duration_ms: float | None = Field(default=None, ge=0.0, allow_inf_nan=False)
    message: str


def register_sam3_segmentation_tools(
    mcp: FastMCP,
    process_manager: Sam3WorkerProcessManager,
) -> None:
    """Register image inference, status, and unload tools."""

    manager = process_manager

    @mcp.tool(
        name="segment_image_with_sam3",
        title="Segment Image with SAM3",
        description=(
            "Segment objects matching a text prompt in one local image. The image "
            "must be under a configured allowed input root. Returns scores, pixel "
            "boxes, mask metadata, worker PID, and paths to result.json, masks.npz, "
            "per-instance mask PNG files, and overlay.png. It does not process video "
            "or ROS image topics. The first call may load the model; later calls "
            "within the idle window reuse it. Use get_sam3_status to inspect the "
            "worker and unload_sam3 to release GPU memory immediately."
        ),
        annotations=ToolAnnotations(
            readOnlyHint=False,
            destructiveHint=False,
            idempotentHint=False,
            openWorldHint=False,
        ),
    )
    async def segment_image_with_sam3(
        image_path: Annotated[
            str,
            Field(
                min_length=1,
                max_length=4096,
                description="Local JPEG, PNG, or WebP path under an allowed input root.",
            ),
        ],
        text_prompt: Annotated[
            str,
            Field(
                min_length=1,
                max_length=256,
                description="Object category or phrase to segment, such as 'red cup'.",
            ),
        ],
        confidence_threshold: Annotated[
            float,
            Field(
                ge=0.0,
                le=1.0,
                allow_inf_nan=False,
                description="Minimum SAM3 score retained in the result.",
            ),
        ] = 0.5,
    ) -> Sam3SegmentationResult | Sam3ToolErrorResult:
        try:
            result = await manager.infer(
                image_path,
                text_prompt,
                confidence_threshold,
            )
        except Sam3RuntimeError as error:
            return Sam3ToolErrorResult(
                error_code=error.code.value,
                message=error.message,
            )
        return Sam3SegmentationResult.model_validate({"ok": True, **result})

    @mcp.tool(
        name="get_sam3_status",
        title="Get SAM3 Status",
        description=(
            "Read the SAM3 worker state, PID, model load duration, and idle timeout. "
            "This tool never starts or loads the SAM3 model."
        ),
        annotations=ToolAnnotations(
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
    )
    async def get_sam3_status() -> Sam3StatusResult:
        return _status_result(await manager.get_status())

    @mcp.tool(
        name="unload_sam3",
        title="Unload SAM3",
        description=(
            "Stop the SAM3 worker and immediately release its model GPU memory. "
            "Completed segmentation artifacts are preserved. Repeated calls are safe."
        ),
        annotations=ToolAnnotations(
            readOnlyHint=False,
            destructiveHint=True,
            idempotentHint=True,
            openWorldHint=False,
        ),
    )
    async def unload_sam3() -> Sam3StatusResult:
        return _status_result(await manager.unload())


def _status_result(status: Sam3WorkerStatus) -> Sam3StatusResult:
    return Sam3StatusResult(
        state=status.state,
        pid=status.pid,
        current_request_id=status.current_request_id,
        last_activity_at=status.last_activity_at,
        idle_timeout_sec=status.idle_timeout_sec,
        load_duration_ms=status.load_duration_ms,
        message=status.message,
    )
