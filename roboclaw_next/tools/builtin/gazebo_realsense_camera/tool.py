"""FastMCP contracts for the Gazebo RealSense listener node."""

from __future__ import annotations

from typing import Annotated, Literal

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations
from pydantic import BaseModel, Field

from .models import GazeboRealsenseCameraStatusResult
from .program import (
    DEFAULT_COLOR_IMAGE_TOPIC,
    DEFAULT_DEPTH_IMAGE_TOPIC,
    GazeboRealsenseCameraManager,
)


class GazeboRealsenseCameraErrorResult(BaseModel):
    """Stable failure result that does not terminate the MCP transport."""

    ok: Literal[False] = False
    message: str


def register_gazebo_realsense_camera_tool(
    mcp: FastMCP,
    manager: GazeboRealsenseCameraManager | None = None,
) -> None:
    """Register Gazebo RealSense listener lifecycle Tools."""

    camera_manager = manager or GazeboRealsenseCameraManager()

    @mcp.tool(
        name="start_gazebo_realsense_camera",
        title="Start Gazebo RealSense Camera",
        description=(
            "Start RoboClaw's Gazebo RealSense listener node. The node subscribes "
            "to the existing Gazebo RGB and depth image topics, then relays "
            "received sensor_msgs/msg/Image payloads over fixed LCM channels. "
            "This tool returns after the node receives its first image message, "
            "while the listener process keeps running in the background."
        ),
        annotations=ToolAnnotations(
            readOnlyHint=False,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
    )
    async def start_gazebo_realsense_camera(
        color_image_topic: Annotated[
            str,
            Field(
                min_length=1,
                max_length=256,
                description="ROS sensor_msgs/msg/Image topic for RGB images.",
            ),
        ] = DEFAULT_COLOR_IMAGE_TOPIC,
        depth_image_topic: Annotated[
            str,
            Field(
                min_length=1,
                max_length=256,
                description="ROS sensor_msgs/msg/Image topic for depth images.",
            ),
        ] = DEFAULT_DEPTH_IMAGE_TOPIC,
        frame_timeout_sec: Annotated[
            float,
            Field(
                gt=0.0,
                le=60.0,
                allow_inf_nan=False,
                description="Maximum seconds to wait for the first image message.",
            ),
        ] = 10.0,
    ) -> GazeboRealsenseCameraStatusResult | GazeboRealsenseCameraErrorResult:
        try:
            return await camera_manager.start(
                color_image_topic=color_image_topic,
                depth_image_topic=depth_image_topic,
                frame_timeout_sec=frame_timeout_sec,
            )
        except (OSError, TimeoutError, ValueError) as error:
            return GazeboRealsenseCameraErrorResult(message=str(error))

    @mcp.tool(
        name="get_gazebo_realsense_camera_status",
        title="Get Gazebo RealSense Camera Status",
        description="Read the current Gazebo RealSense listener process state.",
        annotations=ToolAnnotations(
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
    )
    async def get_gazebo_realsense_camera_status() -> GazeboRealsenseCameraStatusResult:
        return await camera_manager.get_status()

    @mcp.tool(
        name="stop_gazebo_realsense_camera",
        title="Stop Gazebo RealSense Camera",
        description="Stop the active Gazebo RealSense listener node.",
        annotations=ToolAnnotations(
            readOnlyHint=False,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
    )
    async def stop_gazebo_realsense_camera() -> GazeboRealsenseCameraStatusResult:
        return await camera_manager.stop()
