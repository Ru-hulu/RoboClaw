"""FastMCP contracts for the SAM3 perception service."""

from __future__ import annotations

from typing import Annotated

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations
from pydantic import Field

from .models import (
    Sam3PerceptionStatusResult,
    Sam3TargetObjectPoseErrorResult,
    Sam3TargetObjectPoseResult,
)
from .program import Sam3PerceptionManager


def register_sam3_segmentation_tools(
    mcp: FastMCP,
    process_manager: Sam3PerceptionManager,
) -> None:
    """Register SAM3 perception lifecycle and target-pose RPC tools."""

    manager = process_manager

    @mcp.tool(
        name="start_sam3_perception",
        title="Start SAM3 Perception",
        description=(
            "Start RoboClaw's long-running SAM3 perception service. The service "
            "loads the SAM3 worker once, listens to LCM RGB-D image channels from "
            "the Gazebo/RealSense bridge, and exposes a target-pose RPC over LCM. "
            "Its image callbacks should ignore incoming frames unless an active "
            "target-pose RPC is waiting, so the service does not continuously cache "
            "latest RGB-D frames. This only starts the service; it does not run a "
            "target-object query."
        ),
        annotations=ToolAnnotations(
            readOnlyHint=False,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
    )
    async def start_sam3_perception() -> Sam3PerceptionStatusResult:
        return await manager.start()

    @mcp.tool(
        name="get_sam3_perception_status",
        title="Get SAM3 Perception Status",
        description=(
            "Read the SAM3 perception service process state. This does not start "
            "SAM3, load the model, or send a target-pose request."
        ),
        annotations=ToolAnnotations(
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
    )
    async def get_sam3_perception_status() -> Sam3PerceptionStatusResult:
        return await manager.get_status()

    @mcp.tool(
        name="stop_sam3_perception",
        title="Stop SAM3 Perception",
        description=(
            "Stop RoboClaw's long-running SAM3 perception service if this MCP "
            "server started it. Repeated calls are safe."
        ),
        annotations=ToolAnnotations(
            readOnlyHint=False,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
    )
    async def stop_sam3_perception() -> Sam3PerceptionStatusResult:
        return await manager.stop()

    @mcp.tool(
        name="get_target_object_pose",
        title="Get Target Object Pose",
        description=(
            "Request a target object's 3D pose from the running SAM3 perception "
            "service. Call start_gazebo_realsense_camera first so RGB-D images are "
            "bridged from ROS to LCM, then call start_sam3_perception so the SAM3 "
            "service is listening. This tool sends one LCM target-pose RPC using "
            "the prompt, waits for the matching response, and returns whether the "
            "pose is valid plus the target center position in the camera frame."
        ),
        annotations=ToolAnnotations(
            readOnlyHint=False,
            destructiveHint=False,
            idempotentHint=False,
            openWorldHint=False,
        ),
    )
    async def get_target_object_pose(
        prompt: Annotated[
            str,
            Field(
                min_length=1,
                max_length=256,
                description=(
                    "Target object phrase. Use a short English noun phrase when "
                    "possible, for example 'red cube'."
                ),
            ),
        ],
    ) -> Sam3TargetObjectPoseResult | Sam3TargetObjectPoseErrorResult:
        return await manager.get_target_object_pose(prompt)
