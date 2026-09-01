"""FastMCP contracts for one-shot SAM3 current-view segmentation."""

from __future__ import annotations

from typing import Annotated, Literal

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations
from pydantic import BaseModel, Field

from robot_runtime.perception.sam3.errors import Sam3RuntimeError

from .models import Sam3CurrentViewResult
from .program import (
    DEFAULT_IMAGE_TOPIC,
    Sam3JobState,
    Sam3JobStatus,
    Sam3OneShotProcessManager,
)


class Sam3ToolErrorResult(BaseModel):
    """Stable failure result that does not terminate the MCP transport."""

    ok: Literal[False] = False
    error_code: str = Field(description="Stable SAM3 runtime error code.")
    message: str = Field(description="Concise recovery-oriented error message.")
    result_json_path: str | None = Field(
        default=None,
        description="Aggregate JSON path when the ROS node wrote a failure result.",
    )


class Sam3StatusResult(BaseModel):
    """Current or most recent one-shot segmentation job state."""

    state: Sam3JobState
    pid: int | None
    return_code: int | None
    current_request_id: str | None
    last_result_json_path: str | None
    message: str


def register_sam3_segmentation_tools(
    mcp: FastMCP,
    process_manager: Sam3OneShotProcessManager,
) -> None:
    """Register current-view segmentation, status, and cancel tools."""

    manager = process_manager

    @mcp.tool(
        name="segment_current_view_with_sam3",
        title="Segment Current View with SAM3",
        description=(
            "Segment objects matching a text prompt from RoboClaw's current ROS "
            "camera view. This starts one short-lived ROS node, loads SAM3 for this "
            "request, subscribes to a sensor_msgs/msg/Image topic, processes the "
            "requested number of frames, writes an aggregate JSON result, returns "
            "mask/box/overlay artifact paths, and exits to release GPU memory. Use "
            "this for low-frequency task-level perception, not continuous video "
            "tracking."
        ),
        annotations=ToolAnnotations(
            readOnlyHint=False,
            destructiveHint=False,
            idempotentHint=False,
            openWorldHint=False,
        ),
    )
    async def segment_current_view_with_sam3(
        text_prompt: Annotated[
            str,
            Field(
                min_length=1,
                max_length=256,
                description="Object category or phrase to segment, such as 'red cube'.",
            ),
        ],
        frame_count: Annotated[
            int,
            Field(
                ge=1,
                le=10,
                description="Number of camera frames to segment before exiting.",
            ),
        ] = 3,
        confidence_threshold: Annotated[
            float,
            Field(
                ge=0.0,
                le=1.0,
                allow_inf_nan=False,
                description="Minimum SAM3 score retained in each frame result.",
            ),
        ] = 0.5,
        image_topic: Annotated[
            str,
            Field(
                min_length=1,
                max_length=256,
                description="ROS sensor_msgs/msg/Image topic to sample.",
            ),
        ] = DEFAULT_IMAGE_TOPIC,
        frame_timeout_sec: Annotated[
            float,
            Field(
                gt=0.0,
                le=60.0,
                allow_inf_nan=False,
                description="Maximum seconds to wait for the requested camera frames.",
            ),
        ] = 10.0,
    ) -> Sam3CurrentViewResult | Sam3ToolErrorResult:
        try:
            return await manager.segment_current_view(
                text_prompt=text_prompt,
                frame_count=frame_count,
                confidence_threshold=confidence_threshold,
                image_topic=image_topic,
                frame_timeout_sec=frame_timeout_sec,
            )
        except Sam3RuntimeError as error:
            status = await manager.get_status()
            return Sam3ToolErrorResult(
                error_code=error.code.value,
                message=error.message,
                result_json_path=status.last_result_json_path,
            )

    @mcp.tool(
        name="get_sam3_status",
        title="Get SAM3 Status",
        description=(
            "Read the current or most recent one-shot SAM3 job state. This does not "
            "start the ROS node or load the SAM3 model."
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
        name="cancel_sam3_segmentation",
        title="Cancel SAM3 Segmentation",
        description=(
            "Terminate the active one-shot SAM3 current-view job if it is still "
            "running. Repeated calls are safe."
        ),
        annotations=ToolAnnotations(
            readOnlyHint=False,
            destructiveHint=True,
            idempotentHint=True,
            openWorldHint=False,
        ),
    )
    async def cancel_sam3_segmentation() -> Sam3StatusResult:
        return _status_result(await manager.cancel())


def _status_result(status: Sam3JobStatus) -> Sam3StatusResult:
    return Sam3StatusResult(
        state=status.state,
        pid=status.pid,
        return_code=status.return_code,
        current_request_id=status.current_request_id,
        last_result_json_path=status.last_result_json_path,
        message=status.message,
    )
